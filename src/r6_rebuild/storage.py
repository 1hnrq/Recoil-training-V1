"""Atomic replace + fsync, last-valid backup, quarantine and single-writer lock."""

import os
from pathlib import Path
import tempfile
import uuid

from .settings import MAX_BYTES, decode, defaults, encode


def read_bounded(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Arquivo excede 1 MiB.')
    return data


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # only our just-created temporary file


class SettingsStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'settings.json'
        self.backup = self.directory / 'settings.last-valid.json'

    def _quarantine(self, path):
        import shutil
        target = self.directory / f'{path.stem}.invalid-{uuid.uuid4().hex}.json'
        with path.open('rb') as source, target.open('xb') as output:
            shutil.copyfileobj(source, output)
        return target

    def save(self, document):
        raw = encode(document)  # validate everything before touching disk
        if self.path.exists():
            try:
                previous = read_bounded(self.path)
                decode(previous)
            except (ValueError, UnicodeError):
                previous = None
            if previous is not None:
                if previous == raw:
                    return
                atomic_write(self.backup, previous)
        atomic_write(self.path, raw)

    def load(self):
        notices = []
        if self.path.exists():
            try:
                return decode(read_bounded(self.path)), notices
            except (ValueError, UnicodeError) as error:
                quarantine = self._quarantine(self.path)
                notices.append(f'Configuração inválida preservada em {quarantine.name}: {error}')
        if self.backup.exists():
            try:
                restored = decode(read_bounded(self.backup))
                self.save(restored)
                return restored, notices + ['Última configuração válida recuperada do backup.']
            except (ValueError, UnicodeError) as error:
                quarantine = self._quarantine(self.backup)
                notices.append(f'Backup inválido preservado em {quarantine.name}: {error}')
        document = defaults()
        self.save(document)
        return document, notices + ['Catálogo inicial carregado; pausa geral ativa.']


class InstanceLock:
    """OS-held lock; a crash releases it, unlike a stale PID-only marker."""
    def __init__(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        self._file = (path / '.instance.lock').open('a+b')
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            self._file.write(b'0')
            self._file.flush()
        self._file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise RuntimeError('Já existe uma instância usando esta pasta de configurações.') from None

    def close(self):
        self._file.close()
