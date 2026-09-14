import argparse
import fcntl
import hashlib
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from .areas import Areas
from .config import Config
from .http import Http
from .notification_service import Slack, Line, NotificationService
from .state_store import StateStore
from .weather_provider import JmaProvider
from .scheduler import Scheduler
from .forecast_provider import ForecastService


def main():
    p = argparse.ArgumentParser(description='気象庁XML 防災通知')
    p.add_argument('command', choices=['run', 'once', 'areas', 'status', 'healthcheck', 'test-notification', 'dismiss-failures'])
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        c = Config.from_env()
        if c.dry_run:
            c = replace(c, db=c.db + ".dry-run")
        areas = Areas(c.areas)
        if args.command == 'areas':
            for code in sorted(areas.selected):
                print(code, areas.name(code))
            return 0
        Path(c.db).parent.mkdir(parents=True, exist_ok=True)
        lock = open(c.db + '.lock', 'a')
        if args.command not in ('status', 'healthcheck'):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('同じDBを使う監視プロセスが既に動作しています') from None
        store = StateStore(c.db)
        if args.command in ('status', 'healthcheck'):
            statuses = {r[0]: r[1] for r in store.db.execute('SELECT status,COUNT(*) FROM outbox GROUP BY status')}
            last = float(store.meta('last_poll', '0'))
            healthy = time.time() - last < max(900, c.interval * 3) and not store.meta('source_error') and not statuses.get('failed', 0)
            pending_old = store.db.execute("SELECT MIN(created) FROM outbox WHERE status='pending'").fetchone()[0]
            healthy = healthy and (pending_old is None or time.time() - pending_old < 900)
            print(json.dumps({'healthy': healthy, 'last_success_unix': last, 'outbox': statuses,
                              'active_alerts': sum(a.level > 0 and not a.event and areas.intersects(a.area_code) for a in store.states().values())}))
            store.close()
            return 0 if args.command == 'status' or healthy else 1
        if args.command == 'dismiss-failures':
            with store.db:
                count = store.db.execute("UPDATE outbox SET status='dismissed' WHERE status='failed'").rowcount
            print(f'確認済みとして保留を終了しました: {count}件（再送なし）')
            store.close()
            return 0
        fingerprint = hashlib.sha256(json.dumps(sorted(areas.selected)).encode()).hexdigest()
        if store.meta('areas_hash') != fingerprint:
            store.set_meta('last_poll', '0')
            store.set_meta('last_long', '0')
            # Replay latest snapshots for newly selected municipalities.
            with store.db:
                store.db.execute('DELETE FROM seen')
            store.set_meta('areas_hash', fingerprint)
        http = Http(c.timeout)
        channels = {}
        if not c.dry_run:
            if c.slack:
                channels['slack'] = Slack(http, c.slack)
            if c.line_token:
                channels['line'] = Line(http, c.line_token, c.line_to)
        notifications = NotificationService(store, channels)
        if args.command == 'test-notification':
            if c.dry_run:
                raise ValueError('テスト通知は DRY_RUN=false と通知先の設定が必要です')
            ids = store.enqueue('【テスト通知・災害情報ではありません】防災通知の接続確認です。対象: ' + ', '.join(c.areas), list(channels))
            deadline = time.monotonic() + 60
            while True:
                notifications.flush()
                statuses = [store.db.execute('SELECT status FROM outbox WHERE id=?', (id,)).fetchone()[0] for id in ids]
                if all(status == 'sent' for status in statuses) or 'failed' in statuses or time.monotonic() >= deadline:
                    break
                time.sleep(1)
            pending = sum(status != 'sent' for status in statuses)
            store.close()
            return 1 if pending else 0
        runner = Scheduler(c, JmaProvider(http, store, areas), store, notifications, areas, ForecastService(Http(min(c.timeout, 5)), areas))
        try:
            if args.command == 'once':
                return 0 if runner.cycle() else 1
            runner.run()
        finally:
            store.close()
        return 0
    except (ValueError, OSError) as e:
        logging.error('%s', str(e))
        return 2


if __name__ == '__main__':
    sys.exit(main())
