import os
import unittest
from pathlib import Path
from unittest.mock import patch

from bosai.config import Config


class ConfigTests(unittest.TestCase):
    def config(self, **overrides):
        env = {'MONITOR_AREAS': '長野県 飯田市', 'DRY_RUN': 'true', **overrides}
        with patch.dict(os.environ, env, clear=True), patch('bosai.config.load_env'):
            return Config.from_env()

    def test_default_matches_minute_feed(self):
        self.assertEqual(self.config().interval, 60)
        self.assertEqual(Config(('長野県',)).interval, 60)

    def test_interval_override_and_bounds(self):
        for interval in (60, 120, 300, 3600):
            with self.subTest(interval=interval):
                self.assertEqual(self.config(CHECK_INTERVAL=str(interval)).interval, interval)
        for interval in ('0', '59', '3601', 'invalid'):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                self.config(CHECK_INTERVAL=interval)

    def test_example_runs_without_credentials(self):
        example = Path(__file__).resolve().parents[1] / '.env.example'
        # Docker image intentionally excludes all env files; host CI checks the example.
        if not example.exists():
            self.skipTest('example intentionally excluded from Docker image')
        with patch.dict(os.environ, {}, clear=True):
            from bosai.config import load_env
            load_env(example)
            with patch('bosai.config.load_env'):
                config = Config.from_env()
        self.assertTrue(config.dry_run)
        self.assertEqual(config.interval, 60)
        self.assertFalse(config.slack or config.line_token or config.line_to)
