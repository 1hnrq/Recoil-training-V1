import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from r6_rebuild.profiles.catalog import from_catalog
from r6_rebuild.profiles.models import Parameters
from r6_rebuild.core.state import ApplicationState


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT/'data/profiles.json').read_text(encoding='utf8'))
        self.profiles = from_catalog(self.catalog)

    def test_all_profiles_and_450_exact_text_values_reach_domain(self):
        self.assertEqual(len(self.profiles), 75)
        for raw, profile in zip(self.catalog['operators'], self.profiles):
            self.assertEqual(raw['id'], profile.id)
            for slot in ('primary', 'secondary'):
                for field in ('x', 'y', 'interval_seconds'):
                    self.assertEqual(raw[slot][field], getattr(getattr(profile, slot).parameters, field))

    def test_vigil_is_preserved_not_eligible_and_can_change_axis(self):
        state = ApplicationState(self.profiles, 'vigil')
        state.set_global_pause(False)
        state.set_mouse_buttons(left=True, right=True)
        self.assertEqual(state.active_profile.parameters.interval_seconds, '0.00099')
        self.assertFalse(state.simulation_eligible)
        state.update_parameters('primary', Parameters('0.00099', '2', '3'))
        self.assertFalse(state.simulation_eligible)
        state.update_parameters('primary', Parameters('0.001', '2', '3'))
        self.assertTrue(state.simulation_eligible)

    def test_new_subminimum_edit_is_atomic(self):
        state = ApplicationState(self.profiles, 'jager')
        before = state.snapshot()
        with self.assertRaises(ValueError):
            state.update_parameters('primary', Parameters('0.00099', '2', '3'))
        self.assertEqual(state.snapshot(), before)
