"""Strict, versioned settings. No transient input, pause or accumulator state."""

from copy import deepcopy
from decimal import Decimal
import json
import re
from fractions import Fraction

from .core.state import ApplicationState
from .core.exact import Sensitivity
from .profiles.catalog import from_catalog
from .profiles.models import OperatorProfile, _keys

from .paths import resource_root

ROOT = resource_root()
MAX_BYTES = 1024 * 1024
FORMAT = 'r6-rebuild.settings'
EDIT_DECIMAL = re.compile(r'[+-]?\d+(?:\.\d{1,6})?\Z')


def catalog():
    return json.loads((ROOT / 'data/profiles.json').read_text(encoding='utf-8'))


def defaults():
    return {'format': FORMAT, 'version': 1,
            'operators': [p.to_dict() for p in from_catalog(catalog())],
            'sensitivity': {'x': '1', 'y': '1'},
            'selected_operator': 'jager', 'selected_weapon': 'primary',
            'ui': {'view': 'weapons', 'reticle': {'mark': '+', 'opacity': '80', 'size': '70'}}}


def decimal_text(value, name):
    if not isinstance(value, str) or len(value) > 24 or not EDIT_DECIMAL.fullmatch(value):
        raise ValueError(f'{name}: use texto decimal com até 6 casas, sem expoente.')
    if abs(Decimal(value)) > 1000000:
        raise ValueError(f'{name}: limite absoluto de edição é 1000000.')
    return value  # preserve sign, trailing zeroes and spelling


def stepped(field, value, direction):
    if field not in ('x', 'y', 'interval_seconds') or type(direction) is not int or direction not in (-1, 1):
        raise ValueError('Incremento inválido.')
    amount = Fraction(decimal_text(value, field)) * 1000000
    amount += direction * (1000 if field == 'interval_seconds' else 100000)
    if amount.denominator != 1:
        raise ValueError('Valor não representável no contrato de edição.')
    n = abs(amount.numerator)
    result = f'{n // 1000000}.{n % 1000000:06d}'.rstrip('0').rstrip('.')
    return ('-' if amount < 0 else '') + result


def validate(document):
    _keys(document, {'format', 'version', 'operators', 'sensitivity',
                     'selected_operator', 'selected_weapon', 'ui'}, 'configuração')
    if document['format'] != FORMAT or type(document['version']) is not int or document['version'] != 1:
        raise ValueError('Formato/versão de configuração não suportado.')
    base = from_catalog(catalog())
    entries = document['operators']
    if not isinstance(entries, list) or len(entries) != len(base):
        raise ValueError('A configuração deve conter exatamente os 75 operadores.')
    for entry, original in zip(entries, base):
        profile = OperatorProfile.from_dict(entry)
        if (profile.id, profile.label) != (original.id, original.label):
            raise ValueError('IDs, nomes ou ordem dos 75 operadores divergentes.')
        for slot in ('primary', 'secondary'):
            params = getattr(profile, slot).parameters
            for key, value in params.to_dict().items():
                decimal_text(value, key)
            interval = params.interval_decimal
            if 0 < interval < Decimal('.001') and interval != getattr(original, slot).parameters.interval_decimal:
                raise ValueError('Intervalo submínimo novo não permitido; apenas legado identificado.')
    _keys(document['sensitivity'], {'x', 'y'}, 'sensibilidade')
    for axis, value in document['sensitivity'].items():
        decimal_text(value, axis)
    Sensitivity(**document['sensitivity'])
    if document['selected_operator'] not in [p.id for p in base]:
        raise ValueError('Operador selecionado desconhecido.')
    if document['selected_weapon'] not in ('primary', 'secondary'):
        raise ValueError('Arma selecionada desconhecida.')
    ui = document['ui']
    _keys(ui, {'view', 'reticle'}, 'preferências')
    if ui['view'] not in ('weapons', 'operators', 'reticles', 'files'):
        raise ValueError('Tela desconhecida.')
    _keys(ui['reticle'], {'mark', 'opacity', 'size'}, 'mira')
    if ui['reticle']['mark'] not in ('+', '⊕', '·', '⌖'):
        raise ValueError('Mira desconhecida.')
    for name, low, high in [('opacity', 0, 100), ('size', 20, 120)]:
        value = ui['reticle'][name]
        if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}', value) or not low <= int(value) <= high:
            raise ValueError(f'{name} da mira fora do limite.')
    return deepcopy(document)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'Chave JSON duplicada: {key}')
        obj[key] = value
    return obj


def parse_json(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Arquivo excede 1 MiB ou não é texto.')
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'Número inválido: {value}')))
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError('JSON inválido.') from error


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Arquivo excede 1 MiB.')
    try:
        return validate(parse_json(raw.decode('utf-8-sig')))
    except (TypeError, KeyError) as error:
        raise ValueError(f'Estrutura de configuração inválida: {error}') from error


def encode(document):
    return (json.dumps(validate(document), ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def state_from(document):
    document = validate(document)
    state = ApplicationState([OperatorProfile.from_dict(x) for x in document['operators']],
                             document['selected_operator'])
    state.select_weapon(document['selected_weapon'])
    state.set_sensitivity(**document['sensitivity'])
    # Startup/import always paused, no pressed buttons and no residues.
    return state


def from_snapshot(snapshot, ui):
    return validate({'format': FORMAT, 'version': 1, 'operators': snapshot['operators'],
                     'sensitivity': snapshot['sensitivity'], 'selected_operator': snapshot['selected_operator'],
                     'selected_weapon': snapshot['selected_weapon'], 'ui': ui})


def import_document(raw, current):
    """Legacy verified settings.txt: ^^^ + JSON array of 75 six-field strings."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Arquivo excede 1 MiB.')
    text = raw.decode('utf-8-sig')
    if text.startswith('^^^'):
        rows = parse_json(text[3:])
        if not isinstance(rows, list) or len(rows) != 75:
            raise ValueError('Legado requer 75 linhas na ordem documentada.')
        document = validate(current)
        for profile, row in zip(document['operators'], rows):
            if not isinstance(row, str) or len(row.split(',')) != 6:
                raise ValueError('Cada linha legada precisa de T1,X1,Y1,T2,X2,Y2.')
            values = row.split(',')
            for slot, offset in [('primary', 0), ('secondary', 3)]:
                profile[slot]['parameters'] = dict(zip(('interval_seconds', 'x', 'y'), values[offset:offset+3]))
        return validate(document), ['Legado: 450 valores-base; Y e Speed sem conversão.',
                                    'O arquivo legado não contém fatores, pausas ou seleção; estes foram preservados.',
                                    'Ordem de 75 operadores do snapshot documentado; outras versões não são identificáveis por esse formato.']
    return decode(raw), ['Formato próprio versionado; configurações serão substituídas após confirmação.']
