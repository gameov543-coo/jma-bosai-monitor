import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from bosai.forecast_provider import ForecastService, windows, FALLBACK
from bosai.areas import Areas
from bosai.models import Alert, Bulletin, timestamp
from bosai.state_store import StateStore
from bosai.alert_evaluator import message, should_notify
from test_system import FakeHttp
from bosai.http import TransportError

DATA = (Path(__file__).parent / 'fixtures/timeline_iida.xml').read_bytes()
NOW = timestamp('2026-09-11T19:30:00+09:00')


def warning():
    return Alert('rain:2020500', '長野県 飯田市', '2020500', '大雨警報', 2, '3',
                 '2026-09-11T19:30:00+09:00', 'テスト', 'https://www.jma.go.jp/', 'rain')


class ForecastTests(unittest.TestCase):
    def test_official_iida_forecast_overlaps_two_hours(self):
        rows = windows(DATA, '2020500', '大雨警報', NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[0] for r in rows], [timestamp('2026-09-11T18:00:00+09:00'), timestamp('2026-09-11T21:00:00+09:00')])
        self.assertTrue(any('１時間最大雨量' in s for r in rows for s in r[2]))
        self.assertFalse(any('２４時間' in s for r in rows for s in r[2]))

    def test_wrong_area_stale_and_no_future_window_not_used(self):
        self.assertEqual(windows(DATA, '2020201', '大雨警報', NOW), [])
        self.assertEqual(windows(DATA, '2020500', '大雨警報', NOW+86400), [])
        self.assertEqual(windows(DATA, '2020500', '大雨警報', NOW-86400), [])

    def test_outlook_displays_resolution_and_no_false_clearance(self):
        f = ForecastService(None, Areas(['長野県 飯田市']))
        f.cached_at = NOW
        f.documents = {'200000': [('https://www.data.jma.go.jp/test.xml', DATA)]}
        text = f.outlook(warning(), NOW)
        self.assertIn('3時間単位', text)
        self.assertIn('18:00〜21:00', text)
        self.assertIn('解除を意味しません', text)
        self.assertIn(text, message(None, replace(warning(), forecast=text)))

    def test_forecast_failure_keeps_warning_deliverable(self):
        f = ForecastService(FakeHttp([TransportError()]), Areas(['長野県 飯田市']))
        a = replace(warning(), forecast=f.outlook(warning(), NOW))
        self.assertEqual(a.forecast, FALLBACK)
        with tempfile.TemporaryDirectory() as d:
            s = StateStore(d + '/s')
            self.assertEqual(len(s.apply(Bulletin('1', a.issued_at, [a]), ['line'], now=NOW)), 1)
            self.assertIn(FALLBACK, s.pending()[0]['text'])
            s.close()

    def test_forecast_change_does_not_trigger_duplicate(self):
        self.assertFalse(should_notify(replace(warning(), forecast='old'), replace(warning(), forecast='new'), 1))
        self.assertTrue(should_notify(None, replace(warning(), level=1, kind='大雨注意報'), 1))

    def test_clearance_does_not_repeat_old_forecast(self):
        with tempfile.TemporaryDirectory() as d:
            s = StateStore(d + '/s')
            a = replace(warning(), forecast='old-forecast')
            s.apply(Bulletin('1', a.issued_at, [a]), [], now=NOW)
            marker = replace(a, key='marker', level=-1, kind='__snapshot__')
            msgs = s.apply(Bulletin('2', a.issued_at, [marker]), [], now=NOW)
            self.assertNotIn('old-forecast', msgs[0])
            s.close()

class SchedulerForecastTests(unittest.TestCase):
    def test_only_new_warning_gets_outlook(self):
        from unittest.mock import Mock
        from bosai.scheduler import Scheduler
        from bosai.config import Config
        from bosai.weather_provider import Entry
        from bosai.notification_service import NotificationService
        from bosai.models import utcnow
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(d + '/s')
            areas = Areas(['長野県 飯田市'])
            provider = Mock()
            provider.collect.return_value = ([Entry('x','VPBS50',0,'200000')], False)
            provider.fetch.return_value = b''
            forecast = Mock()
            forecast.outlook.return_value = 'forecast-data'
            scheduler = Scheduler(Config(('長野県 飯田市',)), provider, store, NotificationService(store, {}), areas, forecast)
            scheduler.parser = Mock()
            a = replace(warning(), issued_at=utcnow())
            for i, value in enumerate([replace(a, level=1, kind='大雨注意報'), a, a]):
                scheduler.parser.parse.return_value = Bulletin(str(i), a.issued_at, [value])
                self.assertTrue(scheduler.cycle())
            self.assertEqual(forecast.outlook.call_count, 1)
            store.close()
