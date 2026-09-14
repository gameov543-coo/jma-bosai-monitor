import logging
import time
from typing import Protocol
from .http import TransportError

log = logging.getLogger(__name__)


class Channel(Protocol):
    def send(self, text: str, retry_key: str): ...


class Slack:
    def __init__(self, http, webhook):
        self.http, self.webhook = http, webhook

    def send(self, text, retry_key):
        # plain_text prevents JMA/user text from turning into Slack mentions.
        r = self.http.request('POST', self.webhook, {
            'text': text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), 'blocks': [{'type': 'section', 'text': {'type': 'plain_text', 'text': text[i:i+3000]}} for i in range(0, len(text), 3000)],
            'unfurl_links': False, 'unfurl_media': False})
        if r.status != 200 or r.body.strip() != b'ok':
            raise TransportError(r.status, False)


class Line:
    def __init__(self, http, token, recipient):
        self.http, self.token, self.recipient = http, token, recipient

    def send(self, text, retry_key):
        r = self.http.request('POST', 'https://api.line.me/v2/bot/message/push',
                              {'to': self.recipient, 'messages': [{'type': 'text', 'text': text[:5000]}]},
                              {'Authorization': 'Bearer ' + self.token, 'X-Line-Retry-Key': retry_key})
        if r.status == 409 and r.headers.get('x-line-accepted-request-id'):
            return
        if r.status != 200:
            raise TransportError(r.status, False)


class NotificationService:
    def __init__(self, store, channels):
        self.store, self.channels = store, channels

    def flush(self):
        for row in self.store.pending():
            channel = self.channels.get(row['channel'])
            if channel is None:
                continue
            # LINE retry keys last 24 h; do not risk replaying an accepted old request.
            if time.time() - row['created'] >= 23 * 3600:
                self.store.failed(row, 'Delivery expired; inspect status before re-sending', permanent=True)
                continue
            try:
                channel.send(row['text'], row['id'])
            except TransportError as e:
                self.store.failed(row, e, permanent=not e.retryable, retry_after=e.retry_after)
                log.error('notification_failed channel=%s status=%s', row['channel'], e.status)
            except Exception as e:
                self.store.failed(row, type(e).__name__)
                log.error('notification_failed channel=%s type=%s', row['channel'], type(e).__name__)
            else:
                self.store.delivered(row['id'])
                log.info('notification_sent channel=%s id=%s', row['channel'], row['id'])
