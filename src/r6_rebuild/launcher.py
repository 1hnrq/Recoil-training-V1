"""Console-free entry point; errors are visible instead of disappearing."""
import argparse
import os
from pathlib import Path
import sys
import traceback

from .paths import configuration_directory


def main(argv=None):
    # pythonw / PyInstaller --windowed may provide None streams.
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    parser = argparse.ArgumentParser(description='R6-Rebuild: início pausado em Simulação')
    parser.add_argument('--data-dir', type=Path, help='Configurações separadas; EXE padrão: LOCALAPPDATA/R6-Rebuild')
    parser.add_argument('--mock-output', action='store_true', help='QA sem API de movimento; requer --data-dir')
    parser.add_argument('--migrate-from', type=Path, help='Pasta .local antiga; copia somente se destino não existe')
    parser.add_argument('--self-check', type=Path, help='Verificação SEM movimento; pasta NOVA para relatório e dados de teste')
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            from .selfcheck import run
            run(args.self_check)
        else:
            from .desktop import run
            run(args.data_dir, mock_output=args.mock_output, migrate_from=args.migrate_from)
        return 0
    except Exception as error:
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        if args.self_check:
            return 1  # automation must not hang on a dialog
        message = (f'{type(error).__name__}: {error}\n\n'
                   'O programa foi encerrado sem ativar movimentos.\n'
                   'Requer Windows x64, .NET Framework e Microsoft Edge WebView2 Runtime.\n'
                   'Nenhum componente será instalado automaticamente.')
        try:
            directory = args.data_dir or configuration_directory()
            directory.mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            path = directory / f'error-{uuid4().hex}.log'
            with path.open('x', encoding='utf-8') as stream:
                stream.write(details)
            message += f'\n\nDetalhes: {path}'
        except (OSError, RuntimeError):
            pass
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'R6-Rebuild — falha ao iniciar', 0x10)
        return 1
