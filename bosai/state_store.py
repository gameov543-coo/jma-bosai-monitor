"""Atomic state/outbox updates. A single process owns this SQLite database."""
import json
import sqlite3
import time
import uuid
from dataclasses import replace
from pathlib import Path
from .models import Alert, timestamp
from .alert_evaluator import should_notify, message


class StateStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS snapshots (scope TEXT PRIMARY KEY, issued REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, received REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, channel TEXT NOT NULL, text TEXT NOT NULL,
          created REAL NOT NULL, next_try REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '');
        ''')

    def meta(self, key, default=''):
        r = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def seen(self, id):
        return self.db.execute('SELECT 1 FROM seen WHERE id=?', (id,)).fetchone() is not None

    def states(self):
        return {r['key']: Alert(**json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM state')}

    def apply(self, bulletin, channels, minimum=1, event_max_age=10800, now=None):
        now = time.time() if now is None else now
        notifications = []
        with self.db:
            if self.seen(bulletin.id):
                return notifications
            previous = self.states()
            markers = [a for a in bulletin.alerts if a.level == -1]
            stale_scopes = set()
            for marker in markers:
                scope = marker.stream + ':' + marker.area_code
                row = self.db.execute('SELECT issued FROM snapshots WHERE scope=?', (scope,)).fetchone()
                if row and row[0] > timestamp(marker.issued_at):
                    stale_scopes.add(scope)
                else:
                    self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)', (scope, timestamp(marker.issued_at)))
            updates = {a.key: a for a in bulletin.alerts if a.level >= 0 and a.stream + ':' + a.area_code not in stale_scopes}
            for marker in markers:
                if marker.stream + ':' + marker.area_code in stale_scopes:
                    continue
                for key, old in previous.items():
                    if old.stream == marker.stream and old.area_code == marker.area_code and key not in updates:
                        updates[key] = replace(old, kind='解除', level=0, official_level='',
                                               issued_at=marker.issued_at, summary=marker.summary,
                                               url=marker.url, correction=marker.correction, forecast="")
            for key, new in updates.items():
                old = previous.get(key)
                if old and timestamp(new.issued_at) < timestamp(old.issued_at):
                    continue
                # One-shot reports expire silently: absence/age must never imply warning clearance.
                if new.event and now - timestamp(new.issued_at) > event_max_age:
                    continue
                if should_notify(old, new, minimum):
                    text = message(old, new)
                    notifications.append(text)
                    for channel in channels:
                        self.db.execute('INSERT INTO outbox(id,channel,text,created,next_try) VALUES (?,?,?,?,?)',
                                        (str(uuid.uuid4()), channel, text, now, now))
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(new.dict(), ensure_ascii=False)))
            self.db.execute('INSERT INTO seen VALUES (?,?)', (bulletin.id, now))
        return notifications

    def enqueue(self, text, channels):
        ids = []
        with self.db:
            for channel in channels:
                id = str(uuid.uuid4())
                ids.append(id)
                self.db.execute('INSERT INTO outbox(id,channel,text,created,next_try) VALUES (?,?,?,?,?)',
                                (id, channel, text, time.time(), time.time()))
        return ids

    def pending(self):
        return self.db.execute("SELECT o.* FROM outbox o WHERE o.status='pending' AND o.next_try<=? AND NOT EXISTS (SELECT 1 FROM outbox prior WHERE prior.channel=o.channel AND prior.status='pending' AND prior.rowid<o.rowid) ORDER BY o.rowid LIMIT 50", (time.time(),)).fetchall()

    def delivered(self, id):
        with self.db:
            self.db.execute("UPDATE outbox SET status='sent',error='' WHERE id=?", (id,))

    def failed(self, row, error, permanent=False, retry_after=0):
        delay = max(retry_after, min(3600, 30 * 2 ** min(row['attempts'], 7)))
        with self.db:
            self.db.execute('UPDATE outbox SET attempts=attempts+1,status=?,error=?,next_try=? WHERE id=?',
                            ('failed' if permanent else 'pending', str(error), time.time() + delay, row['id']))

    def cleanup(self):
        cutoff = time.time() - 30 * 86400
        with self.db:
            self.db.execute('DELETE FROM seen WHERE received<?', (cutoff,))
            self.db.execute("DELETE FROM outbox WHERE status='sent' AND created<?", (cutoff,))
            # Event keys include event ids; bound their retention without touching persistent warnings.
            for key, alert in self.states().items():
                if alert.event and timestamp(alert.issued_at) < cutoff:
                    self.db.execute('DELETE FROM state WHERE key=?', (key,))

    def close(self):
        self.db.close()
