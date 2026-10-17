"""Mathematical comparison only; does not import or execute the original app."""

from fractions import Fraction as F
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import Parameters
from r6_rebuild.core.exact import FractionalAccumulator, Sensitivity, effective_axes


def compare(x: str, y: str, mx: str = '1', my: str = '1', cycles: int = 100) -> dict:
    axes = effective_axes(Parameters('0.001', x, y), Sensitivity(mx, my))
    acc = FractionalAccumulator()
    old_unscaled = [0, 0]
    old_scaled = [0, 0]
    new = [0, 0]
    selected_count = 0
    for index in range(cycles):
        selected = index % 2 == 0  # same exact 50/50 sequence for both models
        selected_count += selected
        old_unscaled[0] += int(F(x)) if selected else 0
        old_unscaled[1] += int(F(y))
        old_scaled[0] += int(axes[0]) if selected else 0
        old_scaled[1] += int(axes[1])
        dx, dy = acc.step(*axes, horizontal_selected=selected)
        new[0] += dx
        new[1] += dy
    return {'x': x, 'y': y, 'mx': mx, 'my': my, 'active_cycles': cycles,
            'horizontal_selected_cycles': selected_count,
            'effective_axes': [str(value) for value in axes],
            'old_routes_without_multipliers': old_unscaled,
            'old_routes_with_multipliers': old_scaled,
            'new_uniform_exact_accumulation': new,
            'residuals': [str(value) for value in acc.residuals]}


if __name__ == '__main__':
    print(json.dumps({'simulation_only': True, 'cases': [
        compare('-0.4', '0.4'), compare('-1.5', '1.25'),
        compare('0.4', '-0.2', '1.25', '1.5'), compare('2', '3', '1.5', '2')
    ]}, indent=2))
