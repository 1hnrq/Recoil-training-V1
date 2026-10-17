import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r6_rebuild import OperatorProfile, Parameters, WeaponProfile


class ParametersTests(unittest.TestCase):
    def test_decimal_spelling_and_sign_survive_json_round_trip(self):
        parameters = Parameters("0.03500", "-0.400", "+1.2500")
        restored = Parameters.from_dict(json.loads(json.dumps(parameters.to_dict())))
        self.assertEqual(restored, parameters)
        self.assertEqual(restored.to_dict(), {"interval_seconds": "0.03500", "x": "-0.400", "y": "+1.2500"})
        self.assertEqual(restored.x_decimal, Decimal("-0.4"))
        self.assertEqual(restored.y_decimal, Decimal("1.25"))

    def test_requested_intervals_remain_exact(self):
        for interval in ("0.035", "0.020", "0.010", "0.005", "0.001"):
            with self.subTest(interval=interval):
                parameters = Parameters(interval, "-2.1", "-8.199")
                self.assertTrue(parameters.configured)
                self.assertEqual(parameters.to_dict()["interval_seconds"], interval)
                self.assertEqual(parameters.interval_decimal, Decimal(interval))

    def test_zero_is_unconfigured_without_clamping(self):
        for interval in ("0", "0.000", "-0"):
            parameters = Parameters(interval, "2", "4")
            self.assertFalse(parameters.configured)
            self.assertEqual(parameters.interval_seconds, interval)

    def test_negative_interval_is_rejected(self):
        for interval in ("-0.001", "-1"):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                Parameters(interval, "0", "0")

    def test_legacy_subminimum_interval_is_preserved_but_not_eligible(self):
        parameters = Parameters("0.00099", "1", "2")
        self.assertEqual(parameters.to_dict()["interval_seconds"], "0.00099")
        self.assertFalse(parameters.configured)

    def test_nonfinite_values_are_rejected_in_every_field(self):
        for field in ("interval_seconds", "x", "y"):
            for value in ("NaN", "sNaN", "Infinity", "-Infinity"):
                data = {"interval_seconds": "0.035", "x": "0", "y": "0"}
                data[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Parameters(**data)

    def test_numbers_cannot_silently_enter_via_float(self):
        for field in ("interval_seconds", "x", "y"):
            for value in (0.035, 1, True, Decimal("0.035"), None):
                data = {"interval_seconds": "0.035", "x": "0", "y": "0"}
                data[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                    Parameters(**data)

    def test_ambiguous_text_is_rejected(self):
        for value in ("", " 1", "1 ", "1,25", "1_000", "oops"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Parameters("0.035", value, "0")

    def test_immutable_and_strict_fields(self):
        parameters = Parameters("0.035", "0", "0")
        with self.assertRaises(FrozenInstanceError):
            parameters.x = "5"
        with self.assertRaises(ValueError):
            Parameters.from_dict({**parameters.to_dict(), "unexpected": "x"})
        with self.assertRaises(ValueError):
            Parameters.from_dict({"x": "0", "y": "0"})


class ProfileTests(unittest.TestCase):
    def test_full_json_round_trip_and_snapshot_detachment(self):
        operator = OperatorProfile(
            "jager", "Jäger", WeaponProfile(Parameters("0.035", "-0.4", "1.25")),
            WeaponProfile(Parameters("0.010", "0", "-0.4"), enabled=False),
        )
        data = operator.to_dict()
        self.assertEqual(OperatorProfile.from_dict(json.loads(json.dumps(data))), operator)
        data["primary"]["parameters"]["x"] = "99"
        data["secondary"]["enabled"] = True
        self.assertEqual(operator.primary.parameters.x, "-0.4")
        self.assertFalse(operator.secondary.enabled)

    def test_invalid_identifiers_labels_and_boolean_flags(self):
        weapon = WeaponProfile(Parameters("0", "0", "0"))
        for invalid in ("Jäger", "some name", "", "-ash"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                OperatorProfile(invalid, "label", weapon, weapon)
        with self.assertRaises(ValueError):
            OperatorProfile("ash", " ", weapon, weapon)
        for invalid in ("false", 0, 1, None):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                WeaponProfile(weapon.parameters, enabled=invalid)


if __name__ == "__main__":
    unittest.main()
