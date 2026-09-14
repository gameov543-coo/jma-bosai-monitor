import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from bosai.areas import Areas
from bosai.alert_parser import Parser, ParseError, severity
from bosai.alert_evaluator import message
from bosai.models import Alert, Bulletin, timestamp, utcnow
from bosai.state_store import StateStore
from bosai.http import Http, Response, TransportError
from bosai.notification_service import Slack, Line, NotificationService
from bosai.weather_provider import JmaProvider
from bosai.config import Config
from bosai.scheduler import Scheduler

FIX = Path(__file__).parent / 'fixtures'
URL = 'https://www.data.jma.go.jp/developer/xml/data/test.xml'


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def alert(level=1, kind='大雨注意報', issued=None):
    return Alert('rain:2020201', '長野県 松本市松本', '2020201', kind, level, '', issued or utcnow(),
                 '低い土地の浸水に注意', URL, 'rain')


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/state.db'
        self.s = StateStore(self.path)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def apply(self, a, id, minimum=1):
        return self.s.apply(Bulletin(id, a.issued_at, [a]), ['slack', 'line'], minimum)

    def test_new_escalation_clear_repeat_restart(self):
        a = alert()
        self.assertEqual(len(self.apply(a, '1')), 1)
        self.assertEqual(self.apply(a, '2'), [])
        self.assertEqual(len(self.apply(replace(a, kind='大雨警報', level=2), '3')), 1)
        self.assertEqual(len(self.apply(replace(a, kind='大雨特別警報', level=3), '4')), 1)
        clear = replace(a, kind='解除', level=0)
        self.assertEqual(len(self.apply(clear, '5')), 1)
        self.s.close()
        self.s = StateStore(self.path)
        self.assertEqual(self.apply(clear, '6'), [])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0], 8)

    def test_threshold_and_clear(self):
        a = alert()
        self.assertEqual(self.apply(a, '1', 2), [])
        self.assertEqual(len(self.apply(replace(a, kind='大雨警報', level=2), '2', 2)), 1)
        self.assertEqual(len(self.apply(replace(a, kind='解除', level=0), '3', 2)), 1)

    def test_older_report_cannot_revert_state(self):
        self.apply(alert(3, '大雨特別警報', '2026-09-10T12:00:00+09:00'), 'new')
        self.assertEqual(self.apply(alert(1, issued='2026-09-10T10:00:00+09:00'), 'old'), [])
        self.assertEqual(next(iter(self.s.states().values())).level, 3)

    def test_no_initial_clear(self):
        self.assertEqual(self.apply(alert(0, '解除'), '1'), [])

    def test_seen_is_atomic_with_outbox(self):
        a = alert()
        self.apply(a, '1')
        self.assertEqual(self.apply(replace(a, level=3), '1'), [])
        self.assertEqual(len(self.s.pending()), 2)

    def test_one_shot_old_ignored(self):
        a = replace(alert(3, issued='2020-01-01T00:00:00Z'), event=True)
        self.assertEqual(self.apply(a, '1'), [])

    def test_delivery_failure_keeps_state_and_retries(self):
        self.apply(alert(), '1')
        h = FakeHttp([TransportError(503)])
        line_http = FakeHttp([Response(200, b'{}', {})])
        n = NotificationService(self.s, {'slack': Slack(h, 'https://example.invalid'), 'line': Line(line_http, 'secret', 'U123')})
        n.flush()
        rows = list(self.s.db.execute('SELECT channel,status FROM outbox'))
        self.assertEqual(dict(rows), {'slack': 'pending', 'line': 'sent'})
        self.assertEqual(self.apply(alert(), '2'), [])

    def test_snapshot_only_clears_same_municipality_and_stream(self):
        a = alert()
        other = replace(a, key='other', area_code='2021501')
        self.s.apply(Bulletin('1', a.issued_at, [a, other]), [])
        marker = replace(a, key='marker', kind='__snapshot__', level=-1)
        self.s.apply(Bulletin('2', a.issued_at, [marker]), [])
        self.assertEqual(self.s.states()[a.key].level, 0)
        self.assertEqual(self.s.states()['other'].level, 1)


class OfficialFixtureTests(unittest.TestCase):
    def test_rain_timeline(self):
        areas = Areas(['神奈川県 横浜市'])
        parser = Parser(areas)
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s.db')
            levels = []
            for i in range(8):
                b = parser.parse((FIX / f'rain_{i}.xml').read_bytes(), URL + str(i), 'VPWW55')
                s.apply(b, ['slack'], now=timestamp(b.issued_at))
                levels.append(max(a.level for a in s.states().values()))
                self.assertEqual(s.apply(b, ['slack']), [])
            self.assertIn(1, levels)
            self.assertIn(2, levels)
            self.assertIn(3, levels)
            self.assertEqual(levels[-1], 0)
            s.close()

    def test_river_mapping(self):
        p = Parser(Areas(['富山県 小矢部市']))
        b = p.parse((FIX / 'river.xml').read_bytes(), URL, 'VXKO50')
        self.assertTrue(b.alerts)
        self.assertTrue(all(a.level == 1 for a in b.alerts))
        b = p.parse((FIX / 'river_danger.xml').read_bytes(), URL, 'VXKO50')
        self.assertTrue(all(a.level == 3 for a in b.alerts))
        self.assertFalse(Parser(Areas(['長野県 松本市'])).parse((FIX / 'river.xml').read_bytes(), URL, 'VXKO50').alerts)

    def test_record_and_linear_event_regions(self):
        p = Parser(Areas(['北海道 美幌町']))
        b = p.parse((FIX / 'record.xml').read_bytes(), URL, 'VPBS50')
        self.assertTrue(b.alerts)
        self.assertTrue(all(a.level == 3 and a.event for a in b.alerts))
        b = Parser(Areas(['千葉県'])).parse((FIX / 'linear.xml').read_bytes(), URL, 'VPBS50')
        self.assertEqual(len(b.alerts), 3)

    def test_landslide(self):
        b = Parser(Areas(['神奈川県 小田原市'])).parse((FIX / 'landslide.xml').read_bytes(), URL, 'VXWW50')
        self.assertEqual(max(a.level for a in b.alerts), 3)

    def test_training_ignored_and_unknown_schema_rejected(self):
        p = Parser(Areas(['神奈川県']))
        data = (FIX / 'rain_0.xml').read_bytes()
        self.assertEqual(p.parse(data.replace('通常'.encode(), '訓練'.encode()), URL, 'VPWW55').alerts, [])
        with self.assertRaises(ParseError):
            p.parse(data.replace(b'<Warning ', b'<Unknown ').replace(b'</Warning>', b'</Unknown>'), URL, 'VPWW55')
        with self.assertRaises(ParseError):
            p.parse(b'<!DOCTYPE foo><foo/>', URL, 'VPWW55')

    def test_city_splits_and_invalid_area(self):
        self.assertEqual(len(Areas(['長野県 松本市', '長野県 塩尻市', '長野県 安曇野市']).selected), 5)
        with self.assertRaises(ValueError):
            Areas(['長野県 架空市'])


class NotificationTests(unittest.TestCase):
    def test_slack_payload(self):
        h = FakeHttp([Response(200, b'ok', {})])
        Slack(h, 'https://hooks.slack.com/services/test').send(message(None, alert()), 'id')
        payload = h.calls[0][0][2]
        for text in ('地域:', '情報種別:', '発表時刻:', 'LEVEL 1', '要約:', '公式情報:', '変化:'):
            self.assertIn(text, payload['text'])
        self.assertEqual(payload['blocks'][0]['text']['type'], 'plain_text')

    def test_line_payload_retry_key_and_409(self):
        h = FakeHttp([Response(200, b'{}', {}), Response(409, b'{}', {'x-line-accepted-request-id': 'x'})])
        line = Line(h, 'secret', 'U123')
        line.send('テスト', 'stable-id')
        line.send('テスト', 'stable-id')
        args = h.calls[0][0]
        self.assertEqual(args[2]['to'], 'U123')
        self.assertEqual(args[3]['X-Line-Retry-Key'], 'stable-id')
        self.assertEqual(args[3]['Authorization'], 'Bearer secret')

    def test_line_false_409_and_slack_bad_body_fail(self):
        with self.assertRaises(TransportError):
            Line(FakeHttp([Response(409, b'{}', {})]), 'secret', 'U').send('x', 'id')
        with self.assertRaises(TransportError):
            Slack(FakeHttp([Response(200, b'invalid', {})]), 'url').send('x', 'id')


class FailureTests(unittest.TestCase):
    def test_api_failure_preserves_warning_and_deduplicates_health_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = StateStore(tmp + '/s.db')
            a = alert()
            s.apply(Bulletin('1', a.issued_at, [a]), [])
            areas = Areas(['長野県 松本市'])
            h = FakeHttp([TransportError(503), TransportError(503)])
            provider = JmaProvider(h, s, areas)
            c = Config(('長野県 松本市',), dry_run=True)
            runner = Scheduler(c, provider, s, NotificationService(s, {}), areas)
            self.assertFalse(runner.cycle())
            self.assertFalse(runner.cycle())
            self.assertEqual(s.states()[a.key].level, 1)
            self.assertTrue(s.meta('source_error'))
            s.close()

    def test_http_timeout_retry_and_secret_redaction(self):
        import urllib.error
        h = Http(sleep=lambda _: None)
        with patch.object(h.opener, 'open', side_effect=urllib.error.URLError('secret-webhook')) as op:
            with self.assertRaises(TransportError) as ctx:
                h.request('GET', 'https://example.invalid', attempts=3)
            self.assertEqual(op.call_count, 3)
            self.assertNotIn('secret', str(ctx.exception))

    def test_config_validation(self):
        with patch.dict(os.environ, {'MONITOR_AREAS': '長野県', 'DRY_RUN': 'true', 'CHECK_INTERVAL': '1'}, clear=True):
            with self.assertRaises(ValueError):
                Config.from_env()


if __name__ == '__main__':
    unittest.main()
