"""HTTP-level integration without real credentials or outbound messages."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from bosai.http import Http, TransportError
from bosai.notification_service import Slack, Line


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, dict(self.headers), body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok' if self.path == '/slack' else b'{}')

            def do_GET(self):
                self.send_response(429)
                self.send_header('Retry-After', '12')
                self.end_headers()

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_slack_real_http(self):
        Slack(Http(timeout=2), self.base + '/slack').send('日本語のテスト', 'unused')
        self.assertEqual(self.received[0][2]['text'], '日本語のテスト')

    def test_line_real_http(self):
        base = self.base

        class LocalTransport(Http):
            def request(self, method, url, *args, **kwargs):
                self.original_url = url
                return super().request(method, base + '/line', *args, **kwargs)

        http = LocalTransport(timeout=2)
        Line(http, 'test-token', 'test-user').send('防災通知テスト', '8d2c1f67-a5b7-4836-8117-0252c95ff438')
        path, headers, body = self.received[0]
        self.assertEqual(http.original_url, 'https://api.line.me/v2/bot/message/push')
        self.assertEqual(body['messages'][0]['text'], '防災通知テスト')
        self.assertIn('X-Line-Retry-Key', {k.title(): v for k, v in headers.items()})

    def test_rate_limit_backoff_signal(self):
        with self.assertRaises(TransportError) as ctx:
            Http(timeout=2).request('GET', self.base)
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.retry_after, 12)
