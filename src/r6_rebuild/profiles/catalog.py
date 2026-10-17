"""Map an already loaded factual catalogue to immutable domain objects.

No file writes, production persistence or GUI integration.
"""
from .models import OperatorProfile, Parameters, WeaponProfile


def from_catalog(catalog: dict) -> tuple[OperatorProfile, ...]:
    if catalog.get('schema_version') != 1:
        raise ValueError('Unsupported catalogue schema')
    result = []
    for entry in catalog['operators']:
        weapons = {}
        for slot in ('primary', 'secondary'):
            source = entry[slot]
            weapons[slot] = WeaponProfile(Parameters(**{
                field: source[field] for field in ('interval_seconds', 'x', 'y')
            }), source['enabled'])
        result.append(OperatorProfile(entry['id'], entry['label'], **weapons))
    if not result or len({item.id for item in result}) != len(result):
        raise ValueError('Empty catalogue or duplicate ids')
    return tuple(result)
