"""Desktop host. Local static assets + internal pywebview bridge, never HTTP RPC."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlsplit

from .application import Application
from .bridge import BridgeAPI
from .settings import ROOT, catalog
from .storage import InstanceLock
from .paths import configuration_directory, frozen, legacy_candidates
from .migration import migrate_settings


class Assets(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        route = unquote(urlsplit(path).path)
        names = ('index.html', 'app.js', 'model.js', 'bridge-client.js', 'preview-transport.js',
                 'styles.css', 'operator-icons.css')
        allowed = {'/' + name: ROOT / 'frontend' / name for name in names}
        allowed['/'] = ROOT / 'frontend/index.html'
        allowed['/data/profiles.json'] = ROOT / 'data/profiles.json'
        allowed['/assets/operators/LICENSE.txt'] = ROOT / 'frontend/assets/operators/LICENSE.txt'
        allowed.update({f'/assets/operators/{op["id"]}.svg': ROOT / f'frontend/assets/operators/{op["id"]}.svg'
                        for op in catalog()['operators']})
        return str(allowed.get(route, ROOT / '.preview/not-found'))

    def end_headers(self):
        # pywebview resolves RPC promises through its injected eval helper.
        # No network script origins; no external pages are hosted here.
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def log_message(self, *args):
        pass


def stop_on_close(app):
    # Event handlers must return None, not the (unhashable) snapshot mapping.
    app.emergency()


def run(directory=None, *, mock_output=False, migrate_from=None):
    import webview
    from .mouse_output import DiscardingMouseSink, WindowsMouseSink
    if mock_output and directory is None:
        raise ValueError('Teste sem saída requer --data-dir separado.')
    default_directory = directory is None
    directory = Path(directory) if directory else configuration_directory()
    lock = InstanceLock(directory)
    app = api = server = None
    try:
        candidates = [Path(migrate_from)] if migrate_from else (
            legacy_candidates() if frozen() and default_directory else [])
        notices = migrate_settings(directory, candidates, required=migrate_from is not None)
        app = Application(directory, sink=DiscardingMouseSink() if mock_output else WindowsMouseSink())
        app.notices.extend(notices)
        app.start_global_input()
        api = BridgeAPI(app)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Assets)
        server.daemon_threads = True
        Thread(target=server.serve_forever, name='R6-static-assets', daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/?integrated=1'
        window = webview.create_window('R6-Rebuild · TESTE SEM SAÍDA' if mock_output else 'R6-Rebuild', url, js_api=api,
                                       width=1040, height=650, min_size=(760, 510))
        api._window = window
        window.events.closing += lambda: stop_on_close(app)
        print(f'R6-Rebuild: configurações em {directory.resolve()}; início pausado em Simulação.', flush=True)
        webview.start(gui='edgechromium', debug=False, private_mode=True,
                      icon=str(ROOT / 'assets/branding/r6-rebuild.ico'))
    finally:
        try:
            if api:
                api._close()
            elif app:
                app.close()
        finally:
            try:
                if server:
                    server.shutdown()
                    server.server_close()
            finally:
                lock.close()
