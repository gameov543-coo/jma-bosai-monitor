from dataclasses import replace
from .alert_evaluator import should_notify
import logging
import signal
import threading
import time
from .alert_parser import Parser, ParseError

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, config, provider, store, notifications, areas, forecasts=None):
        self.config, self.provider, self.store = config, provider, store
        self.notifications, self.parser = notifications, Parser(areas)
        self.forecasts = forecasts
        self.stop = threading.Event()

    def cycle(self):
        self.notifications.flush()
        errors = 0
        count = 0
        try:
            entries, long = self.provider.collect()
            for entry in entries:
                if self.stop.is_set():
                    return False
                try:
                    bulletin = self.parser.parse(self.provider.fetch(entry), entry.url, entry.product)
                    if entry.product in ('VPWW53', 'VPWW55', 'VPWW56'):
                        expected = {code for code in self.parser.areas.selected if entry.region in self.parser.areas.ancestors(code)}
                        observed = {a.area_code for a in bulletin.alerts if a.level == -1}
                        # Ignored training bulletins are valid but must not be mistaken for missing municipalities.
                        if not bulletin.ignored and not expected.issubset(observed):
                            raise ParseError('Expected municipality snapshot missing')
                    if self.forecasts is not None:
                        previous = self.store.states()
                        bulletin.alerts = [replace(a, forecast=self.forecasts.outlook(a))
                                           if a.level >= 2 and should_notify(previous.get(a.key), a, self.config.min_level)
                                           else a for a in bulletin.alerts]
                    texts = self.store.apply(bulletin, list(self.notifications.channels), self.config.min_level)
                    count += len(texts)
                    if self.config.dry_run:
                        for text in texts:
                            print(text + '\n', flush=True)
                except Exception as e:
                    errors += 1
                    log.error('bulletin_failed product=%s type=%s reason=%s', entry.product, type(e).__name__, str(e) if isinstance(e, ParseError) else '')
                # Official documents are fetched sequentially; bound load during recovery.
                self.stop.wait(0.1)
            if not errors:
                if long:
                    self.store.set_meta('last_long', time.time())
                self.store.set_meta('last_poll', time.time())
                if self.store.meta('source_error'):
                    self.store.enqueue('【監視復旧】気象庁の情報取得・解析が復旧しました。', list(self.notifications.channels))
                    self.store.set_meta('source_error', '')
            else:
                self.source_error()
        except Exception as e:
            errors += 1
            log.error('poll_failed type=%s', type(e).__name__)
            self.source_error()
        self.notifications.flush()
        self.store.set_meta('last_cycle', time.time())
        self.store.cleanup()
        log.info('cycle_complete changes=%d errors=%d', count, errors)
        return not errors

    def source_error(self):
        if not self.store.meta('source_error'):
            self.store.enqueue('【監視障害】気象庁の情報取得または解析に失敗しています。既存の警報を解除扱いにせず保持しています。公式情報と監視ログを確認してください。https://www.jma.go.jp/bosai/',
                               list(self.notifications.channels))
            self.store.set_meta('source_error', time.time())

    def run(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.stop.set())
        next_poll = 0
        while not self.stop.is_set():
            if time.monotonic() >= next_poll:
                start = time.monotonic()
                self.cycle()
                next_poll = max(start + self.config.interval, time.monotonic() + 1)
            else:
                self.notifications.flush()
            self.stop.wait(min(1, max(0, next_poll - time.monotonic())))
