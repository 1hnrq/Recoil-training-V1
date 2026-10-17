"""Copy-only first-run migration. Caller must hold the destination instance lock.

Validate before publishing, preserve original bytes, never overwrite an existing
destination or modify a source. Ambiguous or damaged sources require a choice.
"""
import os
from pathlib import Path
import tempfile

from .settings import decode
from .storage import read_bounded


def publish_new(path, raw):
    """Atomic, exclusive creation using a same-volume hard link, never replace.

Unsupported filesystem/permissions => fail safely; no truncation fallback.
"""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.migration-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)  # only the temporary file created above


def _candidate(directory):
    primary = directory / 'settings.json'
    backup = directory / 'settings.last-valid.json'
    records, errors = {}, []
    for path in (primary, backup):
        if path.exists():
            try:
                raw = read_bounded(path)
                records[path.name] = (raw, decode(raw))
            except (ValueError, UnicodeError) as exc:
                errors.append(f'{path.name}: {exc}')
    chosen = records.get(primary.name) or records.get(backup.name)
    if chosen is None:
        if errors:
            raise ValueError(f'Configuração antiga inválida em {directory}; origem preservada. ' + '; '.join(errors))
        return None
    return {'source': directory, 'raw': chosen[0], 'document': chosen[1],
            'backup': records.get(backup.name), 'recovered': primary.name not in records}


def migrate_settings(destination, candidates, *, required=False):
    destination = Path(destination).resolve()
    if any((destination / name).exists() for name in ('settings.json', 'settings.last-valid.json')):
        return []  # even an invalid existing destination belongs to the user
    found = []
    for directory in dict.fromkeys(Path(p).resolve() for p in candidates):
        if directory != destination:
            candidate = _candidate(directory)
            if candidate:
                found.append(candidate)
    if not found:
        if required:
            raise FileNotFoundError('Nenhuma configuração válida na pasta indicada para migração.')
        return []
    if any(item['document'] != found[0]['document'] for item in found[1:]):
        raise RuntimeError('Há configurações antigas diferentes. Escolha uma pasta com --migrate-from; nada foi substituído.')
    selected = found[0]
    destination.mkdir(parents=True, exist_ok=True)
    # Publish current config first: a crash before backup publication still
    # leaves the latest valid config. The complete source always remains intact.
    publish_new(destination / 'settings.json', selected['raw'])
    if selected['backup']:
        publish_new(destination / 'settings.last-valid.json', selected['backup'][0])
    return [f'Configurações copiadas de {selected["source"]}; origem preservada.' +
            (' Usado backup válido porque a configuração principal não era válida.' if selected['recovered'] else '')]
