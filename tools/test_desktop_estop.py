"""Check the software stop contract without sending any chassis command."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from desktop_estop import RobotAPI, assess_state


class Handler(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.calls.append((self.path, json.loads(body)))
        payload = b'{"ok":true,"estop":true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


class TestDesktopStop(unittest.TestCase):
    def test_stop_sends_only_latching_request(self):
        Handler.calls = []
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = RobotAPI('127.0.0.1', server.server_port)
            self.assertTrue(api.stop()['estop'])
            self.assertEqual(Handler.calls, [('/api/estop', {'on': True})])
        finally:
            server.shutdown()
            server.server_close()

    def test_confirmation_requires_fresh_zero_output(self):
        state = {'estop': True, 'safety': {'estop': True, 'out': [0.0, 0.0, 0.0]},
                 'topics': {'safety': {'age': 0.1}}}
        self.assertIn('确认', assess_state(state)[0])
        state['topics']['safety']['age'] = 2.0
        self.assertIn('无法确认', assess_state(state)[0])
        state['topics']['safety']['age'] = 0.1
        state['safety']['out'][0] = 0.2
        self.assertIn('现场断电', assess_state(state)[0])
        state['safety']['out'][0] = float('nan')
        self.assertIn('现场断电', assess_state(state)[0])
        state['safety']['out'][0] = 'unknown'
        self.assertIn('无法确认', assess_state(state)[0])


if __name__ == '__main__':
    unittest.main()
