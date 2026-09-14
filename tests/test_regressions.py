import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from bosai.models import Bulletin, timestamp
from bosai.state_store import StateStore
from bosai.weather_provider import JmaProvider, Entry
from bosai.areas import Areas
from bosai.http import Response
from bosai.alert_parser import Parser, ParseError
from test_system import alert, FIX, URL, FakeHttp


class RegressionTests(unittest.TestCase):
    def test_old_warning_cannot_resurrect_after_initial_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s')
            newer = alert(0, '解除', '2026-09-10T12:00:00Z')
            marker = replace(newer, key='marker', kind='__snapshot__', level=-1)
            s.apply(Bulletin('new', newer.issued_at, [marker]), ['slack'])
            older = alert(2, '大雨警報', '2026-09-09T12:00:00Z')
            old_marker = replace(marker, issued_at=older.issued_at)
            self.assertEqual(s.apply(Bulletin('old', older.issued_at, [older, old_marker]), ['slack']), [])
            self.assertEqual(s.states(), {})
            s.close()

    def test_outbox_preserves_order_across_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s')
            s.enqueue('warning', ['slack'])
            s.enqueue('clear', ['slack'])
            rows = s.pending()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['text'], 'warning')
            s.failed(rows[0], 'timeout')
            self.assertEqual(s.pending(), [])
            s.delivered(rows[0]['id'])
            self.assertEqual(s.pending()[0]['text'], 'clear')
            s.close()

    def test_cold_start_merges_short_and_long(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s')
            p = JmaProvider(None, s, Areas(['長野県']))
            now = time.time()
            old = Entry('old', 'VPWW55', now - 1800, '200000')
            latest = Entry('latest', 'VPWW55', now, '200000')
            with patch.object(p, 'entries', side_effect=[[latest], [old]]) as method:
                entries, long = p.collect()
            self.assertEqual(entries, [latest])
            self.assertEqual(method.call_count, 2)
            s.close()

    def test_stale_feed_and_untrusted_url_rejected(self):
        template = '<feed xmlns="http://www.w3.org/2005/Atom"><updated>{}</updated>{}</feed>'
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s')
            p = JmaProvider(FakeHttp([Response(200, template.format('2020-01-01T00:00:00Z', '').encode(), {})]), s, Areas(['長野県']))
            with self.assertRaises(ParseError):
                p.entries()
            from bosai.models import utcnow
            body = template.format(utcnow(), '<entry><link href="https://attacker.invalid/VPWW55.xml"/></entry>')
            p.http = FakeHttp([Response(200, body.encode(), {})])
            with self.assertRaises(ParseError):
                p.entries()
            s.close()

    def test_snapshot_missing_kinds_does_not_clear(self):
        data = (FIX / 'rain_0.xml').read_bytes().replace(b'<Kind>', b'<Missing>').replace(b'</Kind>', b'</Missing>')
        with self.assertRaises(ParseError):
            Parser(Areas(['神奈川県 横浜市'])).parse(data, URL, 'VPWW55')

    def test_legacy_flood_and_river_clearance(self):
        legacy = Parser(Areas(['奈良県 大和高田市'])).parse((FIX / 'legacy.xml').read_bytes(), URL, 'VPWW53')
        self.assertTrue(any(a.kind == '洪水警報' and a.level == 2 for a in legacy.alerts))
        import xml.etree.ElementTree as ET
        r = ET.fromstring((FIX / 'river.xml').read_bytes())
        for element in r.findall('{*}Head/{*}Headline/{*}Information/{*}Item/{*}Kind/{*}Condition'):
            element.text = '解除'
        b = Parser(Areas(['富山県 小矢部市'])).parse(ET.tostring(r), URL, 'VXKO50')
        self.assertTrue(b.alerts)
        self.assertTrue(all(a.level == 0 for a in b.alerts))

    def test_permanent_failure_is_not_retried(self):
        from bosai.notification_service import NotificationService, Line
        from bosai.http import TransportError
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s')
            s.enqueue('test', ['line'])
            http = FakeHttp([TransportError(401, False)])
            n = NotificationService(s, {'line': Line(http, 'test', 'user')})
            n.flush()
            n.flush()
            self.assertEqual(len(http.calls), 1)
            self.assertEqual(s.db.execute('SELECT status FROM outbox').fetchone()[0], 'failed')
            s.close()

    def test_scheduler_polls_every_configured_interval(self):
        from bosai.scheduler import Scheduler
        from bosai.config import Config
        from unittest.mock import Mock
        class Clock:
            now = 0
            stopped = False
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
            def wait(self, seconds): self.now += seconds
        for interval in (60, 300):
            with self.subTest(interval=interval):
                clock = Clock()
                runner = Scheduler(Config(('長野県',), interval=interval), None, None, Mock(), Areas(['長野県']))
                runner.stop = clock
                calls = []
                def cycle():
                    calls.append(clock.now)
                    clock.now += 10  # Work duration must not accumulate into the interval.
                    if len(calls) == 2: clock.set()
                runner.cycle = cycle
                with patch('bosai.scheduler.time.monotonic', side_effect=lambda: clock.now), patch('bosai.scheduler.signal.signal'):
                    runner.run()
                self.assertEqual(calls, [0, interval])

    def test_cancelled_bulletin_never_means_all_clear(self):
        for fixture, region, product in [('rain_0.xml', '神奈川県 横浜市', 'VPWW55'),
                                         ('river.xml', '富山県 小矢部市', 'VXKO50')]:
            data = (FIX / fixture).read_bytes().replace('<InfoType>発表</InfoType>'.encode(), '<InfoType>取消</InfoType>'.encode())
            with self.subTest(product=product), self.assertRaisesRegex(ParseError, 'Cancelled bulletin'):
                Parser(Areas([region])).parse(data, URL, product)

    def test_river_emergency(self):
        b = Parser(Areas(['埼玉県 久喜市'])).parse((FIX / 'river_emergency.xml').read_bytes(), URL, 'VXKO50')
        self.assertTrue(b.alerts)
        self.assertTrue(all(a.level == 3 for a in b.alerts))


if __name__ == '__main__':
    unittest.main()
