"""Exact profile contracts, without persistence or a compensation algorithm.

Decimal inputs are strings, never floats. Their spelling is retained through
JSON-compatible mappings (including trailing zeros), while Decimal views permit
exact validation. A zero interval denotes an unconfigured profile; it is not
silently replaced with a minimum value.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping


MIN_INTERVAL_SECONDS = Decimal("0.001")
_DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_OPERATOR_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*\Z")


def _decimal(value: str, field: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an exact decimal string, not {type(value).__name__}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} is not a decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    if _DECIMAL_TEXT.fullmatch(value) is None:
        raise ValueError(f"{field} must be a decimal string without whitespace or separators")
    return parsed


def _keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    actual = set(value)
    if actual != expected:
        raise ValueError(f"{name} fields must be {sorted(expected)}")


@dataclass(frozen=True, slots=True)
class Parameters:
    interval_seconds: str
    x: str
    y: str

    def __post_init__(self) -> None:
        interval = _decimal(self.interval_seconds, "interval_seconds")
        _decimal(self.x, "x")
        _decimal(self.y, "y")
        if interval < 0:
            raise ValueError("interval_seconds cannot be negative")

    @property
    def configured(self) -> bool:
        # Preserve legacy Vigil 0.00099 verbatim without making it eligible.
        return self.interval_decimal >= MIN_INTERVAL_SECONDS

    @property
    def interval_decimal(self) -> Decimal:
        return Decimal(self.interval_seconds)

    @property
    def x_decimal(self) -> Decimal:
        return Decimal(self.x)

    @property
    def y_decimal(self) -> Decimal:
        return Decimal(self.y)

    def to_dict(self) -> dict[str, str]:
        return {"interval_seconds": self.interval_seconds, "x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Parameters":
        _keys(data, {"interval_seconds", "x", "y"}, "parameters")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class WeaponProfile:
    parameters: Parameters
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, Parameters):
            raise TypeError("parameters must be Parameters")
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {"parameters": self.parameters.to_dict(), "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WeaponProfile":
        _keys(data, {"parameters", "enabled"}, "weapon")
        return cls(Parameters.from_dict(data["parameters"]), data["enabled"])


@dataclass(frozen=True, slots=True)
class OperatorProfile:
    id: str
    label: str
    primary: WeaponProfile
    secondary: WeaponProfile

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _OPERATOR_ID.fullmatch(self.id) is None:
            raise ValueError("operator id must be a stable lowercase ASCII identifier")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("operator label must be nonempty")
        if not isinstance(self.primary, WeaponProfile) or not isinstance(self.secondary, WeaponProfile):
            raise TypeError("primary and secondary must be WeaponProfile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "primary": self.primary.to_dict(),
            "secondary": self.secondary.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperatorProfile":
        _keys(data, {"id", "label", "primary", "secondary"}, "operator")
        return cls(
            data["id"], data["label"],
            WeaponProfile.from_dict(data["primary"]),
            WeaponProfile.from_dict(data["secondary"]),
        )
