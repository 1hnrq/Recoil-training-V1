"""Simulation-only engine. Produces immutable records, never device calls."""

from dataclasses import dataclass
from fractions import Fraction
from random import Random
from typing import Callable

from .exact import FractionalAccumulator, effective_axes, interval_nanoseconds
from .state import ApplicationState


@dataclass(frozen=True, slots=True)
class SimulatedMovement:
    timestamp_ns: int
    operator_id: str
    weapon: str
    generation: int
    dx: int
    dy: int
    horizontal_selected: bool
    residual_x: str
    residual_y: str


class SimulationEngine:
    """Single-owner core. Use SimulationRuntime for synchronized threaded access."""

    def __init__(self, state: ApplicationState, *, seed: int | None = None,
                 coin: Callable[[], bool] | None = None):
        self.state = state
        rng = Random(seed)
        self._coin = coin if coin is not None else lambda: bool(rng.getrandbits(1))
        self._accumulator = FractionalAccumulator()
        self._generation = None
        self._axes = (Fraction(0), Fraction(0))
        self._period_ns = None

    def synchronize(self) -> None:
        generation = self.state.reset_generation
        if generation != self._generation:
            self._accumulator.reset()
            self._axes = effective_axes(self.state.active_profile.parameters, self.state.sensitivity)
            self._period_ns = (interval_nanoseconds(self.state.active_profile.parameters)
                               if self.state.active_profile.parameters.configured else None)
            self._generation = generation
        if not self.state.simulation_eligible:
            self._accumulator.reset()

    @property
    def residuals(self) -> tuple[Fraction, Fraction]:
        self.synchronize()
        return self._accumulator.residuals

    @property
    def period_ns(self) -> int | None:
        self.synchronize()
        return self._period_ns if self.state.simulation_eligible else None

    def step(self, timestamp_ns: int) -> SimulatedMovement | None:
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a nonnegative integer")
        self.synchronize()
        if not self.state.simulation_eligible:
            return None
        horizontal_selected = self._coin()
        dx, dy = self._accumulator.step(*self._axes, horizontal_selected=horizontal_selected)
        rx, ry = self._accumulator.residuals
        # A (0, 0) record is still an active simulation cycle, not an OS call.
        return SimulatedMovement(timestamp_ns, self.state.selected_operator,
                                 self.state.selected_weapon.value, self.state.reset_generation,
                                 dx, dy, horizontal_selected, str(rx), str(ry))
