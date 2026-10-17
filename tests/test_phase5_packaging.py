from contextlib import closing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import paths, settings
from r6_rebuild.migration import migrate_settings, publish_new
from r6_rebuild.storage import InstanceLock, SettingsStore


class BundledReconciliationTests(unittest.TestCase):
    def test_selfcheck_synchronization_uses_only_discard_output(self):
        from r6_rebuild.selfcheck import check_synchronization
        results = {}
        with patch('r6_rebuild.mouse_output.WindowsMouseSink', side_effect=AssertionError('No native output')):
            check_synchronization(results)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(results.values()))

    def test_selfcheck_reconciliation_uses_only_simulated_events(self):
        from r6_rebuild.selfcheck import check_reconciliation
        results = {}
        with patch('r6_rebuild.global_input.WindowsHooks', side_effect=AssertionError('no native hooks')):
            check_reconciliation(results)
        self.assertEqual(len(results), 7)
        self.assertTrue(all(results.values()))


class PathsTests(unittest.TestCase):
    def test_source_resources_and_settings_unchanged(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(paths.resource_root(), Path(__file__).resolve().parents[1])
            self.assertEqual(paths.configuration_directory(), paths.resource_root() / '.local')

    def test_frozen_resources_and_localappdata_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, '_MEIPASS', str(base / 'moved/_internal'), create=True), \
                    patch.dict(os.environ, {'LOCALAPPDATA': str(base / 'user')}):
                self.assertEqual(paths.resource_root(), base / 'moved/_internal')
                self.assertEqual(paths.configuration_directory(), base / 'user/R6-Rebuild')

    def test_missing_or_relative_appdata_fails_not_cwd_fallback(self):
        with patch.object(sys, 'frozen', True, create=True):
            for value in ('', 'relative'):
                with patch.dict(os.environ, {'LOCALAPPDATA': value}):
                    with self.assertRaises(RuntimeError): paths.configuration_directory()

    def test_candidates_only_adjacent_or_recognized_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'repo/dist/R6-Rebuild/R6-Rebuild.exe'
            self.assertEqual(paths.legacy_candidates(exe), [exe.parent / '.local'])
            for rel in ('pyproject.toml', 'src/r6_rebuild/settings.py', 'data/profiles.json'):
                p = root / 'repo' / rel; p.parent.mkdir(parents=True, exist_ok=True); p.touch()
            self.assertEqual(paths.legacy_candidates(exe), [exe.parent / '.local', root / 'repo/.local'])
            moved = root / 'other/R6-Rebuild.exe'
            self.assertEqual(paths.legacy_candidates(moved), [moved.parent / '.local'])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'old/.local'; self.source.mkdir(parents=True)
        self.dest = self.base / 'appdata/R6-Rebuild'
        self.document = settings.defaults()
        self.document['sensitivity'] = {'x': '1.2500', 'y': '0.5'}
        self.document['selected_weapon'] = 'secondary'
        self.document['operators'][33]['primary']['enabled'] = False
        self.raw = settings.encode(self.document)
        (self.source / 'settings.json').write_bytes(self.raw)

    def migrate(self, **kwargs):
        with closing(InstanceLock(self.dest)):
            return migrate_settings(self.dest, [self.source], **kwargs)

    def test_exact_bytes_and_all_decimal_values_preserved(self):
        self.assertTrue(self.migrate())
        self.assertEqual((self.dest / 'settings.json').read_bytes(), self.raw)
        self.assertEqual((self.source / 'settings.json').read_bytes(), self.raw)
        self.assertEqual(settings.decode(self.raw), SettingsStore(self.dest).load()[0])

    def test_bom_and_formatting_preserved_without_reencoding(self):
        raw = b'\xef\xbb\xbf' + self.raw.replace(b'\n', b'\r\n')
        (self.source / 'settings.json').write_bytes(raw)
        self.migrate(); self.assertEqual((self.dest / 'settings.json').read_bytes(), raw)

    def test_backup_preserved_byte_for_byte(self):
        backup = settings.encode(settings.defaults())
        (self.source / 'settings.last-valid.json').write_bytes(backup)
        self.migrate()
        self.assertEqual((self.dest / 'settings.last-valid.json').read_bytes(), backup)
        self.assertEqual((self.source / 'settings.last-valid.json').read_bytes(), backup)

    def test_invalid_primary_uses_valid_backup_without_touching_source(self):
        (self.source / 'settings.json').write_bytes(b'invalid')
        (self.source / 'settings.last-valid.json').write_bytes(self.raw)
        self.assertIn('backup', self.migrate()[0])
        self.assertEqual((self.dest / 'settings.json').read_bytes(), self.raw)
        self.assertEqual((self.source / 'settings.json').read_bytes(), b'invalid')

    def test_invalid_backup_does_not_replace_valid_primary(self):
        (self.source / 'settings.last-valid.json').write_bytes(b'broken')
        self.migrate()
        self.assertFalse((self.dest / 'settings.last-valid.json').exists())
        self.assertEqual((self.source / 'settings.last-valid.json').read_bytes(), b'broken')

    def test_all_invalid_stops_without_starting_defaults(self):
        (self.source / 'settings.json').write_bytes(b'broken')
        with self.assertRaises(ValueError): self.migrate()
        self.assertFalse((self.dest / 'settings.json').exists())

    def test_existing_destination_even_invalid_is_never_overwritten(self):
        self.dest.mkdir(parents=True)
        target = self.dest / 'settings.json'; target.write_bytes(b'owned')
        self.assertEqual(self.migrate(), [])
        self.assertEqual(target.read_bytes(), b'owned')

    def test_existing_backup_also_prevents_migration(self):
        self.dest.mkdir(parents=True)
        target = self.dest / 'settings.last-valid.json'; target.write_bytes(self.raw)
        self.assertEqual(self.migrate(), [])
        self.assertFalse((self.dest / 'settings.json').exists())

    def test_repeated_migration_is_idempotent(self):
        self.migrate()
        (self.source / 'settings.json').write_bytes(settings.encode(settings.defaults()))
        self.assertEqual(self.migrate(), [])
        self.assertEqual((self.dest / 'settings.json').read_bytes(), self.raw)

    def test_conflicting_sources_require_explicit_choice(self):
        other = self.base / 'other'; other.mkdir()
        (other / 'settings.json').write_bytes(settings.encode(settings.defaults()))
        with closing(InstanceLock(self.dest)):
            with self.assertRaises(RuntimeError): migrate_settings(self.dest, [self.source, other])
        self.assertFalse((self.dest / 'settings.json').exists())

    def test_equal_sources_and_duplicate_paths_are_safe(self):
        other = self.base / 'other'; other.mkdir()
        (other / 'settings.json').write_bytes(b'\xef\xbb\xbf' + self.raw)
        with closing(InstanceLock(self.dest)):
            self.assertEqual(len(migrate_settings(self.dest, [self.source, self.source, other])), 1)

    def test_missing_explicit_source_fails_but_empty_auto_discovery_is_ok(self):
        with closing(InstanceLock(self.dest)):
            self.assertEqual(migrate_settings(self.dest, [self.base / 'missing']), [])
            with self.assertRaises(FileNotFoundError):
                migrate_settings(self.dest, [self.base / 'missing'], required=True)

    def test_permission_or_disk_failure_does_not_modify_source(self):
        with patch('r6_rebuild.migration.publish_new', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.migrate()
        self.assertEqual((self.source / 'settings.json').read_bytes(), self.raw)
        self.assertFalse((self.dest / 'settings.json').exists())

    def test_exclusive_publication_never_overwrites_racing_file(self):
        target = self.base / 'race.json'; target.write_bytes(b'owned')
        with self.assertRaises(FileExistsError): publish_new(target, self.raw)
        self.assertEqual(target.read_bytes(), b'owned')
        self.assertFalse(list(self.base.glob('.migration-*.tmp')))

    def test_interrupted_backup_keeps_latest_primary_and_original_backup(self):
        (self.source / 'settings.last-valid.json').write_bytes(settings.encode(settings.defaults()))
        actual = publish_new
        def interrupted(path, raw):
            if path.name.endswith('last-valid.json'): raise OSError('interrupted')
            actual(path, raw)
        with patch('r6_rebuild.migration.publish_new', side_effect=interrupted):
            with self.assertRaises(OSError): self.migrate()
        self.assertEqual(SettingsStore(self.dest).load()[0], self.document)
        self.assertTrue((self.source / 'settings.last-valid.json').exists())

    def test_import_compatibility_and_safe_transients_after_migration(self):
        self.migrate()
        document, _ = SettingsStore(self.dest).load()
        imported, _ = settings.import_document(settings.encode(document), settings.defaults())
        state = settings.state_from(imported).snapshot()
        self.assertTrue(state['global_paused'])
        self.assertFalse(any(state['input'].values()))
        self.assertEqual(state['selected_weapon'], 'secondary')
        self.assertEqual(imported, self.document)

    def test_instance_lock_prevents_two_migrations(self):
        with self.assertRaises(RuntimeError):
            with closing(InstanceLock(self.dest)):
                InstanceLock(self.dest)
