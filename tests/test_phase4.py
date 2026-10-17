from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import settings
from r6_rebuild.application import Application
from r6_rebuild.bridge import BridgeAPI
from r6_rebuild.storage import SettingsStore, InstanceLock, read_bounded


def legacy_bytes(document):
    rows = []
    for p in document['operators']:
        rows.append(','.join(p[w]['parameters'][f] for w in ('primary', 'secondary')
                             for f in ('interval_seconds', 'x', 'y')))
    return ('^^^' + json.dumps(rows)).encode()


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.d = settings.defaults()

    def test_all_450_strings_survive_own_format(self):
        self.assertEqual(settings.decode(settings.encode(self.d)), self.d)
        self.assertEqual(len(self.d['operators']), 75)

    def test_all_450_strings_survive_verified_legacy_format(self):
        loaded, notices = settings.import_document(legacy_bytes(self.d), self.d)
        self.assertEqual(loaded, self.d)
        self.assertTrue(any('não contém' in n for n in notices))

    def test_legacy_keeps_factors_flags_selection_preferences(self):
        original = deepcopy(self.d)
        self.d['sensitivity'] = {'x': '1.25', 'y': '0.5'}
        self.d['selected_operator'], self.d['selected_weapon'] = 'ash', 'secondary'
        self.d['operators'][0]['primary']['enabled'] = False
        self.d['ui']['view'] = 'reticles'
        loaded, _ = settings.import_document(legacy_bytes(original), self.d)
        self.assertEqual(loaded, self.d)

    def test_legacy_special_values_sign_and_secondary_speed_not_converted(self):
        d, _ = settings.import_document(legacy_bytes(self.d), self.d)
        p = {v['id']: v for v in d['operators']}
        self.assertEqual(p['ash']['secondary']['parameters']['interval_seconds'], '0.04')
        self.assertEqual(p['jager']['primary']['parameters']['y'], '6')
        self.assertEqual(p['fuze']['secondary']['parameters'], {'interval_seconds':'0','x':'0.099','y':'-0.2'})
        self.assertEqual(p['vigil']['primary']['parameters']['interval_seconds'], '0.00099')

    def test_unknown_version_duplicate_keys_transients_and_wrong_type_rejected(self):
        for edit in [lambda d:d.update(version=2),lambda d:d.update(version=True),
                     lambda d:d.update(global_paused=False),lambda d:d.update(residuals={'x':'1/2'}),
                     lambda d:d.update(input={}),lambda d:d.update(operators=None)]:
            d = deepcopy(self.d);edit(d)
            with self.assertRaises(ValueError):settings.decode(json.dumps(d).encode())
        with self.assertRaises(ValueError):settings.parse_json('{"x":1,"x":2}')

    def test_missing_extra_reordered_and_renamed_operators_rejected(self):
        for edit in [lambda d:d['operators'].pop(),lambda d:d['operators'].append(d['operators'][0]),
                     lambda d:d['operators'].reverse(),lambda d:d['operators'][0].update(id='wrong')]:
            d = deepcopy(self.d);edit(d)
            with self.assertRaises(ValueError):settings.validate(d)

    def test_invalid_numeric_values_and_new_subminimum_rejected(self):
        for value in ['NaN','Infinity','1e999999999','1.1234567','1000001',0.4,True]:
            d = deepcopy(self.d);d['operators'][0]['primary']['parameters']['x'] = value
            with self.assertRaises((ValueError,TypeError)):settings.validate(d)
        self.d['operators'][0]['primary']['parameters']['interval_seconds'] = '0.00099'
        with self.assertRaises(ValueError):settings.validate(self.d)

    def test_negative_zero_and_trailing_zeroes_are_not_rewritten(self):
        self.d['operators'][0]['primary']['parameters']['x'] = '-0.400000'
        self.d['operators'][0]['secondary']['parameters']['y'] = '-0.0'
        self.assertEqual(settings.decode(settings.encode(self.d)),self.d)

    def test_bad_utf8_oversize_and_invalid_legacy_rejected(self):
        for raw in [b'\xff', b'x'*(settings.MAX_BYTES+1),b'^^^[]',b'[]',b'prefix^^^[]',
                    ('^^^'+json.dumps(['1,2,3']*75)).encode(),
                    ('^^^'+json.dumps([True]*75)).encode()]:
            with self.assertRaises((ValueError,UnicodeError)):settings.import_document(raw,self.d)

    def test_unknown_preferences_and_nonpositive_factors_rejected(self):
        for edit in [lambda d:d['ui'].update(view='unknown'),lambda d:d['ui']['reticle'].update(mark='<script>'),
                     lambda d:d['ui']['reticle'].update(opacity='101'),
                     lambda d:d['sensitivity'].update(x='0')]:
            d=deepcopy(self.d);edit(d)
            with self.assertRaises(ValueError):settings.validate(d)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=SettingsStore(self.temp.name)
        self.d,self.notices=self.store.load()

    def test_save_reload_and_last_valid_backup(self):
        old=self.store.path.read_bytes()
        self.d['sensitivity']['x']='1.25'
        self.store.save(self.d)
        self.assertEqual(self.store.load()[0],self.d)
        self.assertEqual(self.store.backup.read_bytes(),old)

    def test_invalid_primary_quarantined_and_backup_restored(self):
        self.d['sensitivity']['x']='2';self.store.save(self.d)
        corrupt=b'{"bad":'
        self.store.path.write_bytes(corrupt)
        restored,notices=self.store.load()
        self.assertEqual(restored['sensitivity']['x'],'1')
        files=list(self.store.directory.glob('settings.invalid-*.json'))
        self.assertEqual(len(files),1);self.assertEqual(files[0].read_bytes(),corrupt)
        self.assertTrue(any('recuperada' in n for n in notices))

    def test_both_invalid_preserve_bytes_and_recover_defaults(self):
        self.store.path.write_bytes(b'[]');self.store.backup.write_bytes(b'bad backup')
        restored,notices=self.store.load()
        self.assertEqual(restored,settings.defaults())
        self.assertEqual(self.store.backup.read_bytes(),b'bad backup')
        self.assertEqual(len(notices),3)
        self.assertEqual(next(self.store.directory.glob('settings.last-valid.invalid-*.json')).read_bytes(),b'bad backup')

    def test_missing_and_bad_structures_are_recovered_not_crashed(self):
        for corrupt in (b'null',b'[]',b'{}',b'\xff'):
            self.store.path.write_bytes(corrupt)
            document,notices=self.store.load()
            self.assertEqual(document,settings.defaults());self.assertTrue(notices)

    def test_backup_failure_does_not_change_valid_primary(self):
        from r6_rebuild import storage
        before=self.store.path.read_bytes();self.d['sensitivity']['x']='2'
        with patch.object(storage,'atomic_write',side_effect=OSError('backup denied')):
            with self.assertRaises(OSError):self.store.save(self.d)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_absent_primary_recovers_existing_backup(self):
        self.d['sensitivity']['x']='2';self.store.save(self.d)
        self.store.path.unlink()
        restored,notices=self.store.load()
        self.assertEqual(restored['sensitivity']['x'],'1')

    def test_failed_replace_keeps_primary_and_cleans_own_temp(self):
        before=self.store.path.read_bytes()
        self.d['sensitivity']['y']='2'
        from r6_rebuild import storage
        real=storage.os.replace
        def fail(src,dst):
            if Path(dst)==self.store.path:raise OSError('disk unavailable')
            real(src,dst)
        with patch.object(storage.os,'replace',side_effect=fail):
            with self.assertRaises(OSError):self.store.save(self.d)
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertFalse(list(self.store.directory.glob('*.tmp')))

    def test_invalid_save_does_not_touch_files(self):
        before=self.store.path.read_bytes();self.d['version']=999
        with self.assertRaises(ValueError):self.store.save(self.d)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_second_instance_cannot_write_same_directory(self):
        first=InstanceLock(self.temp.name)
        try:
            with self.assertRaises(RuntimeError):InstanceLock(self.temp.name)
        finally:first.close()
        next_instance=InstanceLock(self.temp.name);next_instance.close()


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Application(self.temp.name);self.addCleanup(lambda:self.app.close())

    def send(self,action,**payload):return self.app.dispatch(action,payload)

    def edit(self,field,value,weapon='primary',operator='jager'):
        return self.send('update_parameter',operator=operator,weapon=weapon,field=field,value=value)

    def test_restart_keeps_settings_but_starts_paused_without_inputs(self):
        self.edit('x','-0.400000')
        self.send('toggle_weapon',weapon='secondary',operator='ash')
        self.send('select_operator',id='ash');self.send('select_weapon',weapon='secondary')
        self.send('set_multiplier',axis='x',value='1.25')
        self.send('set_reticle',field='mark',value='⊕')
        self.send('toggle_pause');self.send('simulate_start')
        before=self.app.configuration();self.app.close()
        self.app=Application(self.temp.name)
        self.assertEqual(before,self.app.configuration())
        s=self.app.snapshot();self.assertTrue(s['paused'])
        self.assertFalse(s['diagnostics']['input']['left_pressed'])
        self.assertEqual(s['diagnostics']['residuals'],{'x':'0','y':'0'})

    def test_commands_never_clear_pauses_or_other_weapon_flags(self):
        self.send('toggle_weapon',weapon='primary',operator='jager')
        self.edit('y','-0.2');self.send('set_multiplier',axis='y',value='1.5')
        self.send('select_operator',id='ash');self.send('select_weapon',weapon='secondary')
        self.send('select_operator',id='jager')
        s=self.app.snapshot();p=next(p for p in s['operators'] if p['id']=='jager')
        self.assertTrue(s['paused']);self.assertFalse(p['primary']['enabled']);self.assertTrue(p['secondary']['enabled'])
        self.send('toggle_pause');self.send('toggle_pause')
        self.assertEqual(self.app.snapshot()['operators'],s['operators'])

    def test_explicit_target_edit_does_not_drift_with_selection(self):
        self.send('select_operator',id='ash');self.edit('x','-0.4')
        s=self.app.snapshot();self.assertEqual(s['selected'],'ash')
        self.assertEqual(next(p for p in s['operators'] if p['id']=='jager')['primary']['x'],'-0.4')

    def test_same_effective_values_and_inactive_edits_preserve_generation(self):
        s=self.app.snapshot();generation=s['diagnostics']['generation']
        self.edit('y','6.000000');self.edit('x','-0.4',operator='ash')
        self.assertEqual(self.app.snapshot()['diagnostics']['generation'],generation)

    def test_uniform_multipliers_for_both_weapons(self):
        self.send('set_multiplier',axis='x',value='1.25');self.send('set_multiplier',axis='y',value='1.5')
        for weapon in ('primary','secondary'):
            self.edit('x','-0.4',weapon);self.edit('y','0.4',weapon)
            s=self.send('select_weapon',weapon=weapon)
            self.assertEqual(s['diagnostics']['effective'],{'x':'-1/2','y':'3/5'})

    def test_real_runtime_accumulates_and_diagnostics_show_requested_observed(self):
        self.edit('x','-0.4');self.edit('y','0.4');self.edit('interval_seconds','0.005')
        self.send('toggle_pause');self.send('simulate_start')
        self.assertTrue(self.app.runtime.wait_for_cycles(8))
        s=self.app.snapshot();d=s['diagnostics']
        self.assertGreaterEqual(d['total_y'],3)
        self.assertEqual(d['requested_seconds'],'0.005')
        self.assertGreaterEqual(d['last']['timing']['observed_interval_ns'],5_000_000)
        self.send('simulate_stop')
        self.assertEqual(self.app.snapshot()['diagnostics']['residuals'],{'x':'0','y':'0'})

    def test_start_simulation_does_not_unpause(self):
        s=self.send('simulate_start');self.assertTrue(s['paused']);self.assertFalse(s['diagnostics']['eligible'])
        self.assertEqual(s['diagnostics']['cycles'],0)

    def test_vigil_remains_editable_but_not_eligible(self):
        self.send('select_operator',id='vigil');self.edit('x','0.4',operator='vigil')
        self.send('toggle_pause');s=self.send('simulate_start')
        self.assertFalse(s['diagnostics']['eligible'])

    def test_failed_save_leaves_runtime_and_config_unchanged(self):
        before=self.app.configuration()
        with patch.object(self.app.store,'save',side_effect=OSError('full disk')):
            with self.assertRaises(OSError):self.edit('x','-0.8')
        self.assertEqual(before,self.app.configuration())

    def test_invalid_command_does_not_mutate_or_save(self):
        before=self.app.export_bytes()
        for action,payload in [('unknown',{}),('toggle_pause',{'extra':True}),
                               ('update_parameter',{'operator':'jager','weapon':'primary','field':'x','value':'NaN'})]:
            with self.assertRaises((ValueError,TypeError)):self.app.dispatch(action,payload)
        self.assertEqual(self.app.export_bytes(),before)

    def test_preview_import_nonmutating_then_confirm_atomic_and_paused(self):
        old=self.app.configuration();new=deepcopy(old);new['sensitivity']['x']='2'
        self.send('toggle_pause')
        preview=self.app.preview_import(settings.encode(new))
        self.assertEqual(self.app.configuration(),old)
        s=self.app.confirm_import(preview['token'])
        self.assertTrue(s['paused']);self.assertEqual(s['multipliers']['x'],'2')
        self.assertEqual(settings.decode(self.app.store.backup.read_bytes()),old)

    def test_import_requires_fresh_matching_token(self):
        p=self.app.preview_import(self.app.export_bytes())
        with self.assertRaises(ValueError):self.app.confirm_import('wrong')
        self.send('toggle_pause')
        with self.assertRaises(ValueError):self.app.confirm_import(p['token'])

    def test_invalid_import_keeps_state_and_disk(self):
        before=self.app.export_bytes();disk=self.app.store.path.read_bytes()
        with self.assertRaises(ValueError):self.app.preview_import(b'^^^[]')
        self.assertEqual(before,self.app.export_bytes());self.assertEqual(disk,self.app.store.path.read_bytes())

    def test_idle_focus_loss_does_not_expire_import_confirmation(self):
        p=self.app.preview_import(self.app.export_bytes())
        self.send('simulate_stop')
        self.assertTrue(self.app.confirm_import(p['token'])['paused'])

    def test_steps_use_backend_current_value_and_validate_bounds(self):
        self.edit('x','-0.4')
        for _ in range(3):self.send('step_parameter',operator='jager',weapon='primary',field='x',direction=1)
        p=self.app.configuration()['operators'][33]['primary']['parameters']
        self.assertEqual(p['x'],'-0.1')
        with self.assertRaises(ValueError):self.send('step_parameter',operator='jager',weapon='primary',field='x',direction=True)

    def test_expired_simulation_timer_cannot_stop_new_run(self):
        self.send('simulate_start');old=self.app._simulation_epoch
        self.send('simulate_start');self.app._stop_input(old)
        self.assertTrue(self.app.snapshot()['diagnostics']['input']['left_pressed'])

    def test_export_contains_no_residues_or_transient_pause_input(self):
        raw=self.app.export_bytes()
        for key in (b'residual',b'left_pressed',b'global_paused',b'reset_generation'):self.assertNotIn(key,raw)

    def test_bridge_errors_return_confirmed_state_and_queue_keeps_working(self):
        api=BridgeAPI(self.app)
        try:
            rejected=api.invoke('set_multiplier',{'axis':'x','value':'0'})
            self.assertFalse(rejected['ok']);self.assertEqual(rejected['state']['multipliers']['x'],'1')
            accepted=api.invoke('select_weapon',{'weapon':'secondary'})
            self.assertTrue(accepted['ok']);self.assertEqual(accepted['state']['weapon'],'secondary')
        finally:api._close()

    def test_bridge_import_export_dialog_cancellation_does_not_mutate(self):
        api=BridgeAPI(self.app)
        class Window:
            def create_file_dialog(self,*args,**kwargs):return None
        api._window=Window();before=self.app.export_bytes()
        try:
            self.assertTrue(api.invoke('import_file')['ok'])
            self.assertFalse(api.invoke('export_file')['exported'])
            self.assertEqual(before,self.app.export_bytes())
        finally:api._close()

    def test_native_bridge_file_roundtrip_and_confirmation(self):
        api=BridgeAPI(self.app)
        target=Path(self.temp.name)/'exported.json'
        class Window:
            def create_file_dialog(self,*args,**kwargs):return (str(target),)
        api._window=Window()
        try:
            self.assertTrue(api.invoke('export_file')['exported'])
            exported=target.read_bytes();self.assertEqual(exported,self.app.export_bytes())
            self.edit('x','-0.4')
            reply=api.invoke('import_file');self.assertTrue(reply['ok'])
            self.send('simulate_stop')  # browser blur arrives after native picker
            result=api.invoke('confirm_import',{'token':reply['import_preview']['token']})
            self.assertTrue(result['ok']);self.assertTrue(result['state']['paused'])
            self.assertEqual(self.app.export_bytes(),exported)
        finally:api._close()

    def test_native_close_handler_has_event_compatible_return(self):
        from r6_rebuild.desktop import stop_on_close
        self.assertIsNone(stop_on_close(self.app))

    def test_failed_import_save_keeps_runtime_and_disk(self):
        before=self.app.export_bytes();new=settings.defaults();new['sensitivity']['x']='2'
        preview=self.app.preview_import(settings.encode(new))
        with patch.object(self.app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.app.confirm_import(preview['token'])
        self.assertEqual(self.app.export_bytes(),before)


class AssetIsolationTests(unittest.TestCase):
    def test_desktop_http_only_serves_allowlisted_assets(self):
        from r6_rebuild.desktop import Assets
        handler=object.__new__(Assets)
        for path in ('/.local/settings.json','/../../main.exe','/src/r6_rebuild/application.py','/api/snapshot'):
            self.assertTrue(handler.translate_path(path).endswith('not-found'))
        self.assertTrue(handler.translate_path('/bridge-client.js').endswith('bridge-client.js'))


if __name__=='__main__':unittest.main()
