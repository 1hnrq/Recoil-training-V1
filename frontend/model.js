// Independent preview-only state. No hooks, persistence, scheduler or output API.
export const WEAPONS = ['primary', 'secondary'];
export const FIELDS = ['x', 'y', 'interval_seconds'];

export function units(value) {
  const text = String(value).trim().replace(',', '.');
  if (!/^[+-]?\d+(?:\.\d{1,6})?$/.test(text)) throw new Error('Use um decimal com até 6 casas.');
  const sign = text.startsWith('-') ? -1n : 1n;
  const [whole, fraction = ''] = text.replace(/^[+-]/, '').split('.');
  const result = sign * (BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, '0')));
  if (result > 1000000000000n || result < -1000000000000n) throw new Error('Valor fora do limite de edição da prévia.');
  return result;
}
export function decimal(value) {
  const sign = value < 0n ? '-' : '';
  const absolute = value < 0n ? -value : value;
  const fraction = String(absolute % 1000000n).padStart(6, '0').replace(/0+$/, '');
  return `${sign}${absolute / 1000000n}${fraction ? `.${fraction}` : ''}`;
}
export function validated(field, value) {
  if (!FIELDS.includes(field)) throw new Error('Campo desconhecido.');
  const parsed = units(value);
  if (field === 'interval_seconds' && (parsed < 0n || (parsed > 0n && parsed < 1000n))) {
    throw new Error('Intervalo: 0 (não configurado) ou pelo menos 0.001 s.');
  }
  return decimal(parsed);
}
export function createState(catalog) {
  const operators = structuredClone(catalog.operators);
  if (!operators.length || new Set(operators.map(op => op.id)).size !== operators.length) throw new Error('Catálogo inválido.');
  for (const op of operators) for (const weapon of WEAPONS) {
    for (const field of FIELDS) units(op[weapon][field]);
    if (units(op[weapon].interval_seconds) < 0n) throw new Error('Intervalo negativo no catálogo.');
    if (typeof op[weapon].enabled !== 'boolean') throw new Error('Estado de arma inválido.');
  }
  return {operators, selected: operators.some(op => op.id === 'jager') ? 'jager' : operators[0].id,
    weapon: 'primary', paused: true, view: 'weapons', multipliers: {x: '1', y: '1'}, modified: new Set()};
}
export function current(state) { return state.operators.find(op => op.id === state.selected); }
export function selectOperator(state, id) {
  if (!state.operators.some(op => op.id === id)) throw new Error('Operador desconhecido.');
  if (state.selected !== id) state.weapon = 'primary';
  state.selected = id;
  state.view = 'weapons';
}
export function selectWeapon(state, weapon) {
  if (!WEAPONS.includes(weapon)) throw new Error('Arma desconhecida.');
  state.weapon = weapon;
}
export function toggleWeapon(state, weapon) {
  if (!WEAPONS.includes(weapon)) throw new Error('Arma desconhecida.');
  current(state)[weapon].enabled = !current(state)[weapon].enabled;
}
export function updateParameter(state, weapon, field, value) {
  if (!WEAPONS.includes(weapon)) throw new Error('Arma desconhecida.');
  current(state)[weapon][field] = validated(field, value);
  state.modified.add(`${state.selected}:${weapon}:${field}`);
}
export function configured(weapon) { return units(weapon.interval_seconds) >= 1000n; }
export function legacyDisplay(weapon, slot) {
  return {x: weapon.x, y: decimal(-units(weapon.y)),
    interval_seconds: slot === 'secondary' ? decimal(units(weapon.interval_seconds) * 10n) : weapon.interval_seconds};
}
export function previewStatus(state) {
  if (state.paused) return 'Pausa geral';
  if (!current(state)[state.weapon].enabled) return 'Arma pausada';
  if (!configured(current(state)[state.weapon])) return 'Arma não configurada';
  return 'Habilitada na prévia';
}
