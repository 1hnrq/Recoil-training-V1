"""Read-only local static preview. No functional backend or connection to 8765."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_IDS = frozenset(op['id'] for op in json.loads((ROOT/'data/profiles.json').read_text(encoding='utf-8'))['operators'])


class PreviewHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        route = unquote(urlsplit(path).path)
        allowed = {'/': ROOT/'frontend/index.html', '/index.html': ROOT/'frontend/index.html',
                   '/styles.css': ROOT/'frontend/styles.css', '/app.js': ROOT/'frontend/app.js',
                   '/model.js': ROOT/'frontend/model.js', '/data/profiles.json': ROOT/'data/profiles.json',
                   '/bridge-client.js': ROOT/'frontend/bridge-client.js',
                   '/preview-transport.js': ROOT/'frontend/preview-transport.js',
                   '/operator-icons.css': ROOT/'frontend/operator-icons.css',
                   '/assets/operators/LICENSE.txt': ROOT/'frontend/assets/operators/LICENSE.txt'}
        allowed.update({f'/assets/operators/{op}.svg': ROOT/f'frontend/assets/operators/{op}.svg'
                        for op in OPERATOR_IDS})
        return str(allowed.get(route, ROOT/'.preview/not-found'))

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)


if __name__ == '__main__':
    print('Prévia estática: http://127.0.0.1:18765 — Ctrl+C para encerrar.', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 18765), PreviewHandler).serve_forever()
