from dataclasses import dataclass, asdict
from datetime import datetime, timezone


def timestamp(value: str) -> float:
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('timezone required')
    return d.timestamp()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Alert:
    key: str
    area: str
    area_code: str
    kind: str
    level: int
    official_level: str
    issued_at: str
    summary: str
    url: str
    stream: str
    event: bool = False
    correction: bool = False
    forecast: str = ""

    def signature(self):
        return (self.kind, self.level, self.official_level)

    def dict(self):
        return asdict(self)


@dataclass
class Bulletin:
    id: str
    issued_at: str
    alerts: list[Alert]
    ignored: bool = False
