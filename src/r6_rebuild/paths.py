"""Read-only bundled resources and writable per-user settings are separate."""
import os
from pathlib import Path
import sys


def frozen():
    return bool(getattr(sys, 'frozen', False))


def resource_root():
    if frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[2]


def configuration_directory():
    if not frozen():
        return resource_root() / '.local'
    base = os.environ.get('LOCALAPPDATA')
    if not base or not Path(base).is_absolute():
        raise RuntimeError('LOCALAPPDATA indisponível. Informe uma pasta com --data-dir.')
    return Path(base) / 'R6-Rebuild'


def legacy_candidates(executable=None):
    """No CWD/home scan or baked-in developer path. At most one source checkout.

Adjacent .local supports a transported legacy folder. A build inside this
checkout can find its old .local; after relocation use --migrate-from or import.
"""
    executable = Path(executable or sys.executable).resolve()
    candidates = [executable.parent / '.local']
    for parent in list(executable.parents)[1:5]:
        if ((parent / 'pyproject.toml').is_file()
                and (parent / 'src/r6_rebuild/settings.py').is_file()
                and (parent / 'data/profiles.json').is_file()):
            candidates.append(parent / '.local')
            break
    return list(dict.fromkeys(candidates))
