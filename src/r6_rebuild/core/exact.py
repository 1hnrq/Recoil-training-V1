"""Exact decimal arithmetic; no input capture, output device or scheduler."""

from dataclasses import dataclass
from fractions import Fraction

from ..profiles.models import Parameters, _decimal


@dataclass(frozen=True, slots=True)
class Sensitivity:
    """Global factors in UI units: 1 means 1x, not the legacy internal 1000."""

    x: str = "1"
    y: str = "1"

    def __post_init__(self):
        for field in ("x", "y"):
            if _decimal(getattr(self, field), field) <= 0:
                raise ValueError("sensitivity factors must be positive")

    @property
    def fractions(self) -> tuple[Fraction, Fraction]:
        return Fraction(self.x), Fraction(self.y)


def effective_axes(parameters: Parameters, sensitivity: Sensitivity) -> tuple[Fraction, Fraction]:
    """Multiply once, uniformly for every route/weapon; never change the profile."""
    mx, my = sensitivity.fractions
    return Fraction(parameters.x) * mx, Fraction(parameters.y) * my


def interval_nanoseconds(parameters: Parameters) -> int:
    if not parameters.configured:
        raise ValueError("interval must be at least 0.001 s to simulate")
    ns = Fraction(parameters.interval_seconds) * 1_000_000_000
    # Clock resolution is an integer ns. Round UP only at the scheduling edge;
    # never shorten the requested delay or rewrite the stored decimal string.
    return -(-ns.numerator // ns.denominator)


class FractionalAccumulator:
    def __init__(self):
        self.reset()

    @property
    def residuals(self) -> tuple[Fraction, Fraction]:
        return self._x, self._y

    def reset(self) -> None:
        self._x = Fraction(0)
        self._y = Fraction(0)

    def step(self, x: Fraction, y: Fraction, *, horizontal_selected: bool) -> tuple[int, int]:
        if not isinstance(x, Fraction) or not isinstance(y, Fraction):
            raise TypeError("axes must be exact Fractions, never binary floats")
        if type(horizontal_selected) is not bool:
            raise TypeError("horizontal_selected must be bool")
        total_x = self._x + (x if horizontal_selected else 0)
        total_y = self._y + y
        # int(Fraction) truncates toward zero, including negative values.
        dx, dy = int(total_x), int(total_y)
        self._x, self._y = total_x - dx, total_y - dy
        return dx, dy
