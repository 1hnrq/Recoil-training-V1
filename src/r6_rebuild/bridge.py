"""Only allowlisted commands cross pywebview. One FIFO executor owns mutations."""

from concurrent.futures import ThreadPoolExecutor
from .storage import read_bounded, atomic_write


class BridgeAPI:
    def __init__(self, application):
        self._app = application
        self._queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix='R6-commands')
        self._window = None

    def invoke(self, action, payload=None):
        if action == 'diagnostics':
            if payload not in (None, {}):
                return {'ok': False, 'error': 'Diagnóstico não aceita parâmetros.'}
            return {'ok': True, 'diagnostics': self._app.diagnostics()}
        if action == 'emergency' and payload in (None, {}):
            self._app.emergency()  # never wait behind an open file picker
            return {'ok': True, 'state': self._app.snapshot()}
        if action == 'set_pause' and isinstance(payload, dict) and set(payload) == {'paused','epoch'} and payload['paused'] is True:
            self._app.request_pause(True, payload['epoch'])
            return {'ok': True, 'state': self._app.snapshot()}
        return self._queue.submit(self._invoke, action, payload).result()

    def _invoke(self, action, payload):
        try:
            if action == 'import_file':
                if payload not in (None, {}):
                    raise ValueError('Nenhum caminho externo é aceito pela ponte.')
                import webview
                with self._app.runtime.operational_block('importação / seletor de arquivo'):
                    self._app.dispatch('simulate_stop')
                    paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                            file_types=('Configurações (*.json;*.txt)',))
                    raw = read_bounded(paths[0]) if paths else None
                # Stamp AFTER removing the temporary block; no stale token.
                result = self._app.preview_import(raw) if raw is not None else None
                return {'ok': True, 'import_preview': result, 'state': self._app.snapshot()}
            if action == 'confirm_import':
                if not isinstance(payload, dict) or set(payload) != {'token'}:
                    raise ValueError('Token de importação obrigatório.')
                return {'ok': True, 'state': self._app.confirm_import(payload['token'])}
            if action == 'export_file':
                if payload not in (None, {}):
                    raise ValueError('Nenhum caminho externo é aceito pela ponte.')
                import webview
                with self._app.runtime.operational_block('exportação / seletor de arquivo'):
                    self._app.dispatch('simulate_stop')
                    paths = self._window.create_file_dialog(webview.FileDialog.SAVE,
                                                            save_filename='r6-rebuild.settings.json',
                                                            file_types=('R6 Rebuild (*.json)',))
                    if paths:
                        path = paths[0] if isinstance(paths, (list, tuple)) else paths
                        from pathlib import Path
                        if Path(path).suffix.lower() != '.json':
                            raise ValueError('Exporte para um arquivo .json; outros tipos não serão sobrescritos.')
                        # The UI dialog selects the exact target; no arbitrary-path RPC.
                        atomic_write(path, self._app.export_bytes())
                return {'ok': True, 'exported': bool(paths), 'state': self._app.snapshot()}
            return {'ok': True, 'state': self._app.dispatch(action, payload)}
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
            return {'ok': False, 'error': f'{type(error).__name__}: {error}', 'state': self._app.snapshot()}

    def _close(self):
        self._app.emergency()
        self._queue.shutdown(wait=True, cancel_futures=True)
        self._app.close()
