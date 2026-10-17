"""State contract for a later bridge, not a runtime input listener.

Startup is always globally paused. Selecting a *different* operator selects its
primary weapon, but changes no pause flags. Selecting the same operator keeps
the current weapon. Parameters and individual enable flags never clear the
global pause. Button flags are manually supplied data for tests; this module
does not capture keys, schedule work, or emit mouse movement.
"""

from dataclasses import replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..profiles.models import MIN_INTERVAL_SECONDS, OperatorProfile, Parameters, WeaponProfile
from .exact import Sensitivity, effective_axes


class Weapon(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class ApplicationState:
    def __init__(self, operators: Iterable[OperatorProfile], selected_operator: str | None = None):
        profiles: dict[str, OperatorProfile] = {}
        for profile in operators:
            if not isinstance(profile, OperatorProfile):
                raise TypeError("operators must contain OperatorProfile instances")
            if profile.id in profiles:
                raise ValueError(f"duplicate operator id: {profile.id}")
            # A detached snapshot makes ownership explicit, even though profiles
            # and all their children are immutable.
            profiles[profile.id] = OperatorProfile.from_dict(profile.to_dict())
        if not profiles:
            raise ValueError("at least one operator is required")
        chosen = selected_operator if selected_operator is not None else next(iter(profiles))
        if chosen not in profiles:
            raise KeyError(chosen)
        self._operators = profiles
        self._selected_operator = chosen
        self._selected_weapon = Weapon.PRIMARY
        self._global_paused = True
        self._left_pressed = False
        self._right_pressed = False
        self._sensitivity = Sensitivity()
        self._reset_generation = 0

    @property
    def reset_generation(self) -> int:
        """Sticky transition counter: a pause/resume between cycles is not lost."""
        return self._reset_generation

    @property
    def sensitivity(self) -> Sensitivity:
        return self._sensitivity

    def set_sensitivity(self, x: str, y: str) -> None:
        replacement = Sensitivity(x, y)
        parameters = self.active_profile.parameters
        if effective_axes(parameters, replacement) != effective_axes(parameters, self._sensitivity):
            self._reset_generation += 1
        self._sensitivity = replacement

    def clone(self) -> "ApplicationState":
        """Detached ownership for the threaded simulation runtime."""
        other = ApplicationState(self._operators.values(), self._selected_operator)
        other._selected_weapon = self._selected_weapon
        other._global_paused = self._global_paused
        other._left_pressed, other._right_pressed = self._left_pressed, self._right_pressed
        other._sensitivity = self._sensitivity
        other._reset_generation = self._reset_generation
        return other

    @property
    def operators(self) -> Mapping[str, OperatorProfile]:
        return MappingProxyType(self._operators)

    @property
    def selected_operator(self) -> str:
        return self._selected_operator

    @property
    def selected_weapon(self) -> Weapon:
        return self._selected_weapon

    @property
    def global_paused(self) -> bool:
        return self._global_paused

    @property
    def left_pressed(self) -> bool:
        return self._left_pressed

    @property
    def right_pressed(self) -> bool:
        return self._right_pressed

    @property
    def active_profile(self) -> WeaponProfile:
        return getattr(self._operators[self._selected_operator], self._selected_weapon.value)

    @property
    def simulation_eligible(self) -> bool:
        """Only a predicate, never an instruction to produce physical output."""
        return (
            self._left_pressed and self._right_pressed
            and not self._global_paused
            and self.active_profile.enabled
            and self.active_profile.parameters.configured
        )

    def select_operator(self, operator_id: str) -> None:
        if operator_id not in self._operators:
            raise KeyError(operator_id)
        if operator_id != self._selected_operator:
            self._reset_generation += 1
            self._selected_operator = operator_id
            self._selected_weapon = Weapon.PRIMARY

    def select_weapon(self, weapon: Weapon | str) -> None:
        selected = Weapon(weapon)
        if selected != self._selected_weapon:
            self._reset_generation += 1
        self._selected_weapon = selected

    def set_global_pause(self, paused: bool) -> None:
        paused = self._bool(paused, "paused")
        if paused and not self._global_paused:
            self._reset_generation += 1
        self._global_paused = paused

    def toggle_global_pause(self) -> bool:
        self.set_global_pause(not self._global_paused)
        return self._global_paused

    def on_p_release(self) -> bool:
        """Pure handler contract for a future key adapter; it registers no hook."""
        return self.toggle_global_pause()

    def set_mouse_buttons(self, *, left: bool, right: bool) -> None:
        # Validate both first, so invalid input cannot partially change state.
        new_left = self._bool(left, "left")
        new_right = self._bool(right, "right")
        if (self._left_pressed and not new_left) or (self._right_pressed and not new_right):
            self._reset_generation += 1
        self._left_pressed, self._right_pressed = new_left, new_right

    def set_weapon_enabled(
        self, weapon: Weapon | str, enabled: bool, *, operator_id: str | None = None
    ) -> None:
        selected = Weapon(weapon)
        enabled = self._bool(enabled, "enabled")
        target = self._target(operator_id)
        current = getattr(target, selected.value)
        if (target.id == self._selected_operator and selected == self._selected_weapon
                and current.enabled and not enabled):
            self._reset_generation += 1
        self._operators[target.id] = replace(
            target, **{selected.value: replace(current, enabled=enabled)}
        )

    def toggle_weapon_enabled(self, weapon: Weapon | str, *, operator_id: str | None = None) -> bool:
        selected = Weapon(weapon)
        target = self._target(operator_id)
        new_enabled = not getattr(target, selected.value).enabled
        self.set_weapon_enabled(selected, new_enabled, operator_id=target.id)
        return new_enabled

    def update_parameters(
        self, weapon: Weapon | str, parameters: Parameters, *, operator_id: str | None = None
    ) -> None:
        if not isinstance(parameters, Parameters):
            raise TypeError("parameters must be Parameters")
        selected = Weapon(weapon)
        target = self._target(operator_id)
        current = getattr(target, selected.value)
        if (parameters.interval_decimal != current.parameters.interval_decimal
                and 0 < parameters.interval_decimal < MIN_INTERVAL_SECONDS):
            raise ValueError("new interval_seconds must be zero or at least 0.001")
        old_values = (current.parameters.interval_decimal, current.parameters.x_decimal, current.parameters.y_decimal)
        new_values = (parameters.interval_decimal, parameters.x_decimal, parameters.y_decimal)
        if (target.id == self._selected_operator and selected == self._selected_weapon
                and old_values != new_values):
            self._reset_generation += 1
        self._operators[target.id] = replace(
            target, **{selected.value: replace(current, parameters=parameters)}
        )

    def snapshot(self) -> dict[str, Any]:
        """Detached, JSON-compatible diagnostic data; not a persistence format."""
        return {
            "schema_version": 1,
            "simulation_only": True,
            "reset_generation": self._reset_generation,
            "sensitivity": {"x": self._sensitivity.x, "y": self._sensitivity.y},
            "selected_operator": self._selected_operator,
            "selected_weapon": self._selected_weapon.value,
            "global_paused": self._global_paused,
            "input": {"left_pressed": self._left_pressed, "right_pressed": self._right_pressed},
            "simulation_eligible": self.simulation_eligible,
            "operators": [profile.to_dict() for profile in self._operators.values()],
        }

    def _target(self, operator_id: str | None) -> OperatorProfile:
        return self._operators[self._selected_operator if operator_id is None else operator_id]

    @staticmethod
    def _bool(value: bool, field: str) -> bool:
        if type(value) is not bool:
            raise TypeError(f"{field} must be bool")
        return value
