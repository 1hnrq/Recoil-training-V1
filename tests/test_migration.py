"""Offline invariants for the frozen numeric catalogue, not a mouse runtime."""

import copy
import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_profiles", ROOT / "tools" / "audit_profiles.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = audit.read_json(ROOT / "data" / "profiles.json")
        cls.reference = audit.read_json(ROOT / "data" / "legacy_reference.json")
        cls.by_id = {operator["id"]: operator for operator in cls.catalog["operators"]}

    def test_all_450_parameters_preserve_original_decimal_spelling_and_value(self):
        report = audit.validate_catalog(self.catalog, self.reference)
        self.assertEqual(report["parameters_compared"], 450)
        self.assertEqual(report["operators"], 75)

    def test_all_75_index_to_identifier_mappings(self):
        for index, (operator, reference) in enumerate(zip(self.catalog["operators"], self.reference["records"]), 1):
            with self.subTest(index=index):
                self.assertEqual(operator["legacy_index"], index)
                self.assertEqual(operator["id"], reference["legacy_operator"].lower())
        self.assertEqual(self.by_id["jager"]["legacy_index"], 34)
        self.assertEqual(self.by_id["ash"]["legacy_index"], 5)
        self.assertEqual(self.by_id["iq"]["legacy_index"], 32)

    def test_every_display_conversion_round_trips_without_changing_values(self):
        for operator in self.catalog["operators"]:
            for slot in ("primary", "secondary"):
                with self.subTest(operator=operator["id"], slot=slot):
                    weapon = operator[slot]
                    restored = audit.from_legacy_display(audit.to_legacy_display(weapon, slot), slot)
                    self.assertEqual(restored, {k: Decimal(weapon[k]) for k in audit.FIELDS})

    def test_y_sign_is_display_only(self):
        for y in ("-0.4", "0", "8.199"):
            weapon = {"x": "-2.1", "y": y, "interval_seconds": "0.035"}
            self.assertEqual(audit.to_legacy_display(weapon, "primary")["y"], -Decimal(y))
            self.assertEqual(weapon["y"], y)

    def test_secondary_speed_display_tenfold_is_not_backend_interval(self):
        weapon = self.by_id["amaru"]["secondary"]
        display = audit.to_legacy_display(weapon, "secondary")
        self.assertEqual(display["speed"], Decimal("0.30"))
        self.assertEqual(audit.from_legacy_display(display, "secondary")["interval_seconds"], Decimal("0.03"))

    def test_route_matrix_preserves_observed_multiplier_inconsistency(self):
        operator = self.by_id["hibana"]
        for route, (slot, scaled, _) in audit.ROUTES.items():
            with self.subTest(route=route):
                result = audit.effective_route(operator, route, "1500", "500")
                self.assertEqual(result["interval_seconds"], Decimal(operator[slot]["interval_seconds"]))
                self.assertEqual(result["x"], Decimal(operator[slot]["x"]) * (Decimal("1.5") if scaled else 1))
                self.assertEqual(result["y"], Decimal(operator[slot]["y"]) * (Decimal("0.5") if scaled else 1))
        self.assertNotEqual(audit.effective_route(operator, "primary_hotkey", "1500", "500"),
                            audit.effective_route(operator, "enter_operator", "1500", "500"))

    def test_neutral_multipliers_preserve_every_raw_triple(self):
        for operator in self.catalog["operators"]:
            for route, (slot, _, _) in audit.ROUTES.items():
                self.assertEqual(audit.effective_route(operator, route),
                                 {k: Decimal(operator[slot][k]) for k in audit.FIELDS})

    def test_zero_intervals_are_preserved_and_never_marked_configured(self):
        report = audit.validate_catalog(self.catalog, self.reference)
        self.assertEqual(report["primary_zero_intervals"], 15)
        self.assertEqual(report["secondary_zero_intervals"], 69)
        # Fuze has nonzero axes but a zero interval: no fabricated fallback.
        weapon = self.by_id["fuze"]["secondary"]
        self.assertEqual(weapon["interval_seconds"], "0")
        self.assertEqual(weapon["x"], "0.099")
        self.assertEqual(weapon["y"], "-0.2")
        self.assertFalse(audit.configured(weapon))

    def test_all_zero_profiles_remain_distinct_operators(self):
        report = audit.validate_catalog(self.catalog, self.reference)
        expected = ["alibi", "fenrir", "gridlock", "grim", "melusi", "montagne", "osa",
                    "sens", "sentry", "smoke", "solis", "thatcher", "wamai", "warden", "zofia"]
        self.assertEqual(report["all_zero_operators"], expected)

    def test_subminimum_vigil_is_preserved_and_not_eligible(self):
        self.assertEqual(self.by_id['vigil']['primary']['interval_seconds'], '0.00099')
        self.assertFalse(audit.configured(self.by_id['vigil']['primary']))

    def test_mutation_of_any_of_450_values_is_detected(self):
        for index in range(75):
            for slot in ("primary", "secondary"):
                for field in audit.FIELDS:
                    changed = copy.deepcopy(self.catalog)
                    changed["operators"][index][slot][field] = "123456.789"
                    with self.assertRaises(ValueError):
                        audit.validate_catalog(changed, self.reference)

    def test_float_nonfinite_and_invalid_strings_rejected(self):
        for invalid in (0.035, "NaN", "Infinity", "-Infinity", "", " 0.1", "hello"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                audit.exact_decimal(invalid)

    def test_migration_does_not_mutate_catalogue(self):
        before = copy.deepcopy(self.catalog)
        audit.validate_catalog(self.catalog, self.reference)
        for route in audit.ROUTES:
            audit.effective_route(self.by_id["ash"], route, "0", "5000")
        self.assertEqual(self.catalog, before)


if __name__ == "__main__":
    unittest.main()
