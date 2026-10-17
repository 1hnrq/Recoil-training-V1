"""Read-only profile migration audit; no application, socket or mouse calls.

The helpers model observed conversions for tests, not a runtime compatibility
layer. Default audit uses only the small frozen numerical reference. Supplying
--evidence-dir also checks every original numerical value, mapping and hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("interval_seconds", "x", "y")
# This is an explicit interpretation of observed paths, not copied source code.
ROUTES = {
    "primary_hotkey": ("primary", False, "Engine:an"),
    "primary_update": ("primary", False, "Engine:e_"),
    "enter_operator": ("primary", True, "Engine:ej"),
    "secondary_hotkey": ("secondary", True, "Engine:ar"),
    "secondary_update": ("secondary", True, "Engine:e`"),
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def exact_decimal(value: str) -> Decimal:
    """Reject floats so an earlier rounding step cannot go unnoticed."""
    if not isinstance(value, str) or value.strip() != value or not value:
        raise ValueError("A parameter must be a nonempty decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal parameter") from exc
    if not number.is_finite():
        raise ValueError("Non-finite decimal parameter")
    return number


def raw_values(operator: dict) -> tuple[str, ...]:
    return tuple(operator[weapon][field] for weapon in ("primary", "secondary")
                 for field in FIELDS)


def configured(weapon: dict) -> bool:
    """Readiness is separate from the user's enabled preference."""
    numbers = {field: exact_decimal(weapon[field]) for field in FIELDS}
    return numbers["interval_seconds"] >= Decimal("0.001")


def to_legacy_display(weapon: dict, slot: str) -> dict[str, Decimal]:
    """Numeric display transformation; not strings, rounding or multipliers."""
    if slot not in ("primary", "secondary"):
        raise ValueError("Unknown weapon slot")
    return {
        "x": exact_decimal(weapon["x"]),
        "y": -exact_decimal(weapon["y"]),
        "speed": exact_decimal(weapon["interval_seconds"])
        * (10 if slot == "secondary" else 1),
    }


def from_legacy_display(display: dict, slot: str) -> dict[str, Decimal]:
    if slot not in ("primary", "secondary"):
        raise ValueError("Unknown weapon slot")
    return {
        "x": Decimal(display["x"]),
        "y": -Decimal(display["y"]),
        "interval_seconds": Decimal(display["speed"])
        / (10 if slot == "secondary" else 1),
    }


def effective_route(operator: dict, route: str, x_multiplier: str = "1000",
                    y_multiplier: str = "1000") -> dict[str, Decimal]:
    """Observe the legacy route's values; never normalize profiles in place.

    Multipliers here use the original internal scale (1000 means 1x).
    The result precedes the original Python int() truncation, and therefore
    intentionally retains fractional settings for the proposed future core.
    """
    slot, apply_multiplier, _ = ROUTES[route]
    result = {field: exact_decimal(operator[slot][field]) for field in FIELDS}
    if apply_multiplier:
        result["x"] *= exact_decimal(x_multiplier) / 1000
        result["y"] *= exact_decimal(y_multiplier) / 1000
    return result


def validate_catalog(catalog: dict, reference: dict) -> dict:
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported catalogue schema")
    operators, records = catalog["operators"], reference["records"]
    if len(operators) != 75 or len(records) != 75:
        raise ValueError("Expected exactly 75 operators")
    if len({entry["id"] for entry in operators}) != 75:
        raise ValueError("Operator ids are not unique")
    if reference["source_sha256"] != catalog["source"]["hashes"]["frontend_project.json"]:
        raise ValueError("Reference provenance differs from catalogue")
    compared = 0
    for index, (operator, record) in enumerate(zip(operators, records), 1):
        if operator["legacy_index"] != index or record["legacy_index"] != index:
            raise ValueError(f"Index mismatch: {index}")
        if operator["id"] != record["legacy_operator"].lower():
            raise ValueError(f"Operator mapping mismatch: {index}")
        original = record["raw"].split(",")
        if len(original) != 6:
            raise ValueError(f"Expected six original values: {index}")
        if raw_values(operator) != tuple(original):
            raise ValueError(f"Decimal spelling changed: {operator['id']}")
        for field, expected in zip(raw_values(operator), original):
            if exact_decimal(field) != exact_decimal(expected):
                raise ValueError(f"Numerical value changed: {operator['id']}")
            compared += 1
        for slot in ("primary", "secondary"):
            weapon = operator[slot]
            if type(weapon["enabled"]) is not bool:
                raise ValueError("enabled must be a boolean preference")
            if exact_decimal(weapon["interval_seconds"]) < 0:
                raise ValueError("Negative original interval")
    return {
        "operators": len(operators), "parameters_compared": compared,
        "primary_zero_intervals": sum(exact_decimal(o["primary"]["interval_seconds"]) == 0 for o in operators),
        "secondary_zero_intervals": sum(exact_decimal(o["secondary"]["interval_seconds"]) == 0 for o in operators),
        "subminimum_intervals_preserved": [{"operator": o["id"], "weapon": slot,
                                           "interval_seconds": o[slot]["interval_seconds"]}
                                          for o in operators for slot in ("primary", "secondary")
                                          if 0 < exact_decimal(o[slot]["interval_seconds"]) < Decimal("0.001")],
        "all_zero_operators": [o["id"] for o in operators
                               if all(exact_decimal(v) == 0 for v in raw_values(o))],
        "exact_decimal_spelling_preserved": True,
    }


def input_descendants(blocks: dict, block_id: str) -> list[dict]:
    """Only static input references, not script execution or next-chain traversal."""
    pending, seen, found = [block_id], set(), []
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        block = blocks[key]
        if not isinstance(block, dict):
            continue
        found.append(block)
        for value in block.get("inputs", {}).values():
            if len(value) > 1 and isinstance(value[1], str) and value[1] in blocks:
                pending.append(value[1])
    return found


def verify_conversions(project: dict) -> dict:
    """Check the exact source blocks which support the conversion contract."""
    targets = {target["name"]: target for target in project["targets"]}
    display = targets["NumberDisplay"]["blocks"]
    # divisor, temporary-list index; Temp-Recoil-Vars is 1000 * raw value.
    expected = {"il": ("1000", "2"), "in": ("-1000", "3"),
                "iq": ("1000", "1"), "is": ("1000", "5"),
                "iu": ("-1000", "6"), "iw": ("100", "4")}
    for key, (divisor, index) in expected.items():
        block = display[key]
        item = display[block["inputs"]["NUM1"][1]]
        if (block["opcode"] != "operator_divide"
                or block["inputs"]["NUM2"][1][1] != divisor
                or item["opcode"] != "data_itemoflist"
                or item["fields"]["LIST"][0] != "Temp-Recoil-Vars"
                or item["inputs"]["INDEX"][1][1] != index):
            raise ValueError(f"Legacy display contract changed at NumberDisplay:{key}")
    engine = targets["Engine"]["blocks"]
    for slot, scaled, coordinate in ROUTES.values():
        key = coordinate.split(":", 1)[1]
        if engine[key]["opcode"] != "pythonBridge_sendMessage":
            raise ValueError(f"Route changed at {coordinate}")
        variable_names = set()
        for block in input_descendants(engine, key):
            for entry in block.get("inputs", {}).values():
                if len(entry) > 1 and isinstance(entry[1], list) and entry[1][0] == 12:
                    variable_names.add(entry[1][1])
        uses_multipliers = {"XMULTIPLIER", "YMULTIPLIER"} <= variable_names
        if uses_multipliers != scaled:
            raise ValueError(f"Multiplier route changed at {coordinate} ({slot})")
    return {"display_blocks_checked": 6, "multiplier_routes_checked": len(ROUTES)}


def audit_evidence(catalog: dict, evidence_dir: Path) -> dict:
    """Read only the supplied evidence directory; no network or output writes."""
    before = {}
    for name, expected in catalog["source"]["hashes"].items():
        digest = hashlib.sha256((evidence_dir / name).read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Evidence hash mismatch: {name}")
        before[name] = digest
    project = read_json(evidence_dir / "frontend_project.json")
    stage = next(t for t in project["targets"] if t["isStage"])
    rows = next(item[1] for item in stage["lists"].values() if item[0] == "OP-SETTINGS")
    costumes = next(t for t in project["targets"] if t["name"] == "OPS")["costumes"]
    if len(rows) != len(costumes):
        raise ValueError("Original OP-SETTINGS and costumes differ in size")
    reference = {
        "source_sha256": before["frontend_project.json"],
        "records": [{"legacy_index": i, "legacy_operator": costume["name"], "raw": row}
                    for i, (costume, row) in enumerate(zip(costumes, rows), 1)],
    }
    result = validate_catalog(catalog, reference)
    recovered = read_json(evidence_dir / "frontend_profiles_current.json")
    if recovered["source_sha256"] != before["frontend_project.json"]:
        raise ValueError("Recovered profile source hash differs")
    if len(recovered["profiles"]) != len(catalog["operators"]):
        raise ValueError("Recovered profile count differs")
    compared = 0
    for operator, item in zip(catalog["operators"], recovered["profiles"]):
        if item["index_1based"] != operator["legacy_index"] or item["operator"].lower() != operator["id"]:
            raise ValueError("Recovered profile mapping differs")
        for slot in ("primary", "secondary"):
            for field in FIELDS:
                if Decimal(item[slot][field]) != exact_decimal(operator[slot][field]):
                    raise ValueError(f"Recovered value differs: {operator['id']}.{slot}.{field}")
                compared += 1
    result.update(verify_conversions(project))
    result["independent_extracted_parameters_compared"] = compared
    result["evidence_sha256_verified"] = before
    result["read_only"] = True
    # Detect concurrent modifications too; this command itself performs no writes.
    for name, digest in before.items():
        if hashlib.sha256((evidence_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Evidence changed during audit: {name}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "profiles.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "data" / "legacy_reference.json")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    try:
        catalogue = read_json(args.catalog)
        result = validate_catalog(catalogue, read_json(args.reference))
        if args.evidence_dir is not None:
            result = audit_evidence(catalogue, args.evidence_dir)
        print(json.dumps({"status": "PASS", **result}, indent=2))
        return 0
    except (ValueError, KeyError, StopIteration, OSError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
