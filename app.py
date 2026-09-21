"""Loopback-only demonstration server. Use an authenticated service for a pilot."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json
import secrets

from demo import demo
from engine import Invalid, canonical
from store import Store, Conflict

ROOT = Path(__file__).resolve().parent


def make_server(db_path, port=8765):
    store = Store(db_path)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value, mime='application/json'):
            body = canonical(value).encode() if mime == 'application/json' else value.encode()
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}']

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Invalid host'})
            path = urlparse(self.path).path
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if path in assets:
                name, mime = assets[path]
                return self.send(200, (ROOT / 'static' / name).read_text(encoding='utf-8'), mime)
            if path == '/api/session':
                return self.send(200, {'token': token, 'mode': 'local-demo'})
            if path == '/api/demo':
                return self.send(200, demo())
            if path == '/api/runs':
                return self.send(200, store.list_runs())
            if path.startswith('/api/runs/'):
                try:
                    return self.send(200, store.get(path.split('/')[-1]))
                except Invalid as e:
                    return self.send(404, {'error': str(e)})
            self.send(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed() or self.headers.get('X-Nexus-Token') != token:
                return self.send(403, {'error': 'Invalid local session token'})
            if self.headers.get('Content-Type') != 'application/json':
                return self.send(415, {'error': 'Use application/json'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    return self.send(413, {'error': 'JSON body must be 1..2000000 bytes'})
                payload = json.loads(self.rfile.read(length))
                path = urlparse(self.path).path
                if path == '/api/plan':
                    return self.send(201, store.create(payload))
                if path == '/api/decision':
                    return self.send(200, store.decide(payload['run_id'], payload['action'], payload['actor'], payload['reason'], payload['snapshot_hash']))
                if path == '/api/export':
                    return self.send(200, store.export(payload['run_id']))
                return self.send(404, {'error': 'Not found'})
            except Conflict as e:
                self.send(409, {'error': str(e)})
            except (Invalid, ValueError, KeyError, TypeError) as e:
                self.send(400, {'error': str(e)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    (ROOT / 'runtime').mkdir(exist_ok=True)
    server = make_server(ROOT / 'runtime' / 'nexus.sqlite')
    print('NEXUS local demo: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
