import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def load_env(path='.env'):
    if not Path(path).exists():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, val = line.partition('=')
        if not sep or not key.strip().replace('_', '').isalnum():
            raise ValueError('Invalid .env entry')
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key.strip(), val)


@dataclass(frozen=True)
class Config:
    areas: tuple[str, ...]
    interval: int = 60
    min_level: int = 1
    db: str = 'data/state.sqlite3'
    slack: str = ''
    line_token: str = ''
    line_to: str = ''
    timeout: int = 15
    dry_run: bool = False

    @classmethod
    def from_env(cls):
        load_env()
        c = cls(tuple(x.strip() for x in os.getenv('MONITOR_AREAS', '').split(',') if x.strip()),
                int(os.getenv('CHECK_INTERVAL', '60')), int(os.getenv('MIN_LEVEL', '1')),
                os.getenv('STATE_DB', 'data/state.sqlite3'), os.getenv('SLACK_WEBHOOK_URL', ''),
                os.getenv('LINE_CHANNEL_ACCESS_TOKEN', ''), os.getenv('LINE_TO', ''),
                int(os.getenv('HTTP_TIMEOUT', '15')), os.getenv('DRY_RUN', 'false').lower() == 'true')
        if not c.areas:
            raise ValueError('MONITOR_AREAS を設定してください')
        if not 60 <= c.interval <= 3600 or c.min_level not in (1, 2, 3) or not 1 <= c.timeout <= 60:
            raise ValueError('CHECK_INTERVAL=60..3600, MIN_LEVEL=1..3, HTTP_TIMEOUT=1..60')
        if bool(c.line_token) != bool(c.line_to):
            raise ValueError('LINE_CHANNEL_ACCESS_TOKEN と LINE_TO は両方必要です')
        if c.slack:
            u = urlsplit(c.slack)
            if u.scheme != 'https' or u.hostname not in ('hooks.slack.com', 'hooks.slack-gov.com') or not u.path.startswith('/services/'):
                raise ValueError('Slack Incoming Webhook URL が不正です')
        if not c.dry_run and not (c.slack or c.line_token):
            raise ValueError('Slack または LINE を設定してください。確認のみなら DRY_RUN=true')
        return c
