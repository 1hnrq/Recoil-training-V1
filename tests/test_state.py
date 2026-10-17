import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r6_rebuild import ApplicationState, OperatorProfile, Parameters, Weapon, WeaponProfile


def make_operator(operator_id, label):
    # Deliberately share the immutable child initially to detect accidental
    # cross-weapon updates when the state machine later replaces it.
    weapon = WeaponProfile(Parameters("0.035", "-0.4", "1.25"))
    return OperatorProfile(operator_id, label, weapon, weapon)


class ApplicationStateTests(unittest.TestCase):
    def setUp(self):
        self.jager = make_operator("jager", "Jäger")
        self.ash = make_operator("ash", "Ash")
        self.source = [self.jager, self.ash]
        self.state = ApplicationState(self.source, "jager")

    def test_startup_is_paused_and_primary(self):
        self.assertTrue(self.state.global_paused)
        self.assertEqual(self.state.selected_weapon, Weapon.PRIMARY)
        self.assertFalse(self.state.left_pressed)
        self.assertFalse(self.state.right_pressed)
        self.assertFalse(self.state.simulation_eligible)

    def test_operator_change_selects_primary_without_unpausing(self):
        self.state.select_weapon("secondary")
        self.state.select_operator("ash")
        self.assertEqual(self.state.selected_weapon, Weapon.PRIMARY)
        self.assertTrue(self.state.global_paused)
        self.state.set_global_pause(False)
        self.state.select_weapon("secondary")
        self.state.select_operator("jager")
        self.assertFalse(self.state.global_paused)
        self.assertEqual(self.state.selected_weapon, Weapon.PRIMARY)

    def test_same_operator_keeps_selection(self):
        self.state.select_weapon("secondary")
        self.state.select_operator("jager")
        self.assertEqual(self.state.selected_weapon, Weapon.SECONDARY)

    def test_parameters_do_not_unpause_or_enable_a_disabled_weapon(self):
        self.state.set_weapon_enabled("primary", False)
        replacement = Parameters("0.001", "-1.25", "-0.4")
        self.state.update_parameters("primary", replacement)
        self.assertTrue(self.state.global_paused)
        self.assertFalse(self.state.active_profile.enabled)
        self.assertEqual(self.state.active_profile.parameters, replacement)

    def test_p_changes_only_global_pause(self):
        self.state.set_weapon_enabled("secondary", False)
        before = self.state.snapshot()["operators"]
        self.assertFalse(self.state.on_p_release())
        self.assertTrue(self.state.on_p_release())
        self.assertEqual(before, self.state.snapshot()["operators"])

    def test_enabled_flags_are_independent_across_operators_and_weapons(self):
        self.assertFalse(self.state.toggle_weapon_enabled("primary"))
        self.assertFalse(self.state.operators["jager"].primary.enabled)
        self.assertTrue(self.state.operators["jager"].secondary.enabled)
        self.assertTrue(self.state.operators["ash"].primary.enabled)
        self.assertTrue(self.state.operators["ash"].secondary.enabled)
        self.state.select_operator("ash")
        self.state.set_weapon_enabled("secondary", False)
        self.state.select_operator("jager")
        self.assertFalse(self.state.active_profile.enabled)
        self.assertTrue(self.state.global_paused)
        self.assertFalse(self.state.operators["ash"].secondary.enabled)

    def test_inactive_profile_update_does_not_touch_selection_or_active_parameters(self):
        before = self.state.active_profile
        self.state.update_parameters("secondary", Parameters("0.020", "10", "-20"), operator_id="ash")
        self.assertEqual(self.state.active_profile, before)
        self.assertEqual(self.state.selected_operator, "jager")
        self.assertEqual(self.state.selected_weapon, Weapon.PRIMARY)
        self.assertEqual(self.state.operators["ash"].secondary.parameters.y, "-20")

    def test_eligibility_requires_all_conditions_but_emits_nothing(self):
        self.state.set_mouse_buttons(left=True, right=True)
        self.assertFalse(self.state.simulation_eligible)
        self.state.set_global_pause(False)
        self.assertTrue(self.state.simulation_eligible)
        for left, right in ((False, False), (True, False), (False, True)):
            self.state.set_mouse_buttons(left=left, right=right)
            self.assertFalse(self.state.simulation_eligible)
        self.state.set_mouse_buttons(left=True, right=True)
        self.state.set_weapon_enabled("primary", False)
        self.assertFalse(self.state.simulation_eligible)
        self.state.set_weapon_enabled("primary", True)
        self.state.update_parameters("primary", Parameters("0", "2", "3"))
        self.assertFalse(self.state.simulation_eligible)

    def test_imported_profiles_and_snapshots_cannot_alias_state(self):
        self.source.clear()
        self.state.update_parameters("primary", Parameters("0.010", "99", "-99"))
        self.assertEqual(self.jager.primary.parameters.x, "-0.4")
        self.assertEqual(self.state.operators["jager"].secondary.parameters.x, "-0.4")
        snapshot = self.state.snapshot()
        snapshot["operators"][0]["primary"]["parameters"]["x"] = "123"
        snapshot["input"]["left_pressed"] = True
        self.assertEqual(self.state.active_profile.parameters.x, "99")
        self.assertFalse(self.state.left_pressed)
        with self.assertRaises(TypeError):
            self.state.operators["new"] = self.ash
        self.assertEqual(json.loads(json.dumps(self.state.snapshot())), self.state.snapshot())

    def test_invalid_commands_are_atomic(self):
        before = self.state.snapshot()
        calls = (
            lambda: self.state.select_operator("missing"),
            lambda: self.state.select_weapon("tertiary"),
            lambda: self.state.update_parameters("primary", {"x": "2"}),
            lambda: self.state.set_weapon_enabled("primary", "false"),
            lambda: self.state.set_weapon_enabled("primary", True, operator_id="missing"),
            lambda: self.state.set_global_pause(0),
            lambda: self.state.set_mouse_buttons(left=True, right=1),
        )
        for call in calls:
            with self.subTest(call=call), self.assertRaises((KeyError, ValueError, TypeError)):
                call()
            self.assertEqual(self.state.snapshot(), before)

    def test_constructor_rejects_empty_duplicates_and_unknown_selection(self):
        with self.assertRaises(ValueError):
            ApplicationState([])
        with self.assertRaises(ValueError):
            ApplicationState([self.jager, self.jager])
        with self.assertRaises(KeyError):
            ApplicationState([self.jager], "ash")


if __name__ == "__main__":
    unittest.main()
