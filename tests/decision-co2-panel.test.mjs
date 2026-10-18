import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Minimal DOM stand-in shaped like decision_panel.js el(): attrs on the node, on* handlers kept, null children skipped.
function el(tag, attrs, ...children) {
  return { tag, attrs: attrs || {}, children: children.flat().filter((c) => c !== null && c !== undefined && c !== false) };
}
const text = (n) => (typeof n === 'string' || typeof n === 'number' ? String(n) : n.children.map(text).join(' '));
const all = (n, pred, out = []) => { if (typeof n === 'object') { if (pred(n)) out.push(n); n.children.forEach((c) => all(c, pred, out)); } return out; };
const button = (root, label) => all(root, (n) => n.tag === 'button' && text(n) === label)[0];

const NEEDS = { status: 'needs_car_trip_km', break_even_trips: null, car_trip_km: null, car_trip_km_status: null,
  car_trip_km_source: 'not available: car_distance_km missing for restored ODs (od:P:aaa: no_path, ...)',
  car_distance_coverage: { restored: 773, missing: 36, by_reason: { no_path: 30, snap_failed: 6 } },
  reference_car_trip_km: 15.4, reference_car_trip_km_label: 'national, reference only', period_hours: 3,
  bus_vkm: 326.7, bus_kg: 320.1, per_trip_car_kg: null, net_kg: null, per_action_vkm: { SVC_M5_A: 326.7 },
  units: { bus_vkm: 'vehicle-km', bus_kg: 'kg CO2', per_trip_car_kg: 'kg CO2', net_kg: 'kg CO2' }, notes: [] };

function panel(api) {
  const window = { CityPilotDecision: { panels: {} } };
  vm.runInNewContext(fs.readFileSync(new URL('../web/static/decision/co2_panel.js', import.meta.url), 'utf8'), { window });
  const root = { children: [], replaceChildren() { this.children = []; }, appendChild(c) { this.children.push(c); } };
  const ctx = { el, api, selected: ['SVC_M5_A'], serverState: { co2_available: true, co2_defaults: {} },
    getAppState: () => ({ profile: 'P' }), isOutdated: () => false, on: () => {}, pkgName: (ids) => ids.join('+'),
    fmt: (v, d) => (v === null || v === undefined ? 'n/a' : d === undefined ? String(v) : Number(v).toFixed(d)),
    statusLine: (kind, t) => el('div', { class: `status ${kind}` }, t) };
  window.CityPilotDecision.panels.co2(root, ctx);
  return root;
}

test('missing car distances ask for a trip length; break-even comes from the entered value', async () => {
  const bodies = [];
  const root = panel(async (path, body) => {
    bodies.push(body);
    if (body.car_trip_km === undefined) return NEEDS;
    return { ...NEEDS, status: 'complete', car_trip_km: body.car_trip_km, car_trip_km_status: 'user', car_trip_km_source: 'user',
      per_trip_car_kg: body.car_trip_km * 0.125211, break_even_trips: Math.ceil(320.1 / (body.car_trip_km * 0.125211)) };
  });
  await button(root, 'Compute CO2').attrs.onclick();
  assert.match(text(root), /36 of 773 restored journeys have no modelled car distance; enter a car trip length/);
  assert.match(text(root), /30 no_path, 6 snap_failed/);
  assert.doesNotMatch(text(root), /od:P:aaa/);  // no list of OD ids in the panel
  const input = all(root, (n) => n.tag === 'input' && n.attrs['aria-label'] === 'car trip km')[0];
  input.attrs.oninput({ target: { value: '10' } });
  await button(root, 'Compute break-even').attrs.onclick();
  assert.equal(bodies.at(-1).car_trip_km, 10);
  assert.match(text(root), /Break-even: 256 avoided car trips/);
  assert.match(text(root), /your input/);
  assert.match(text(root), /36 of 773 restored journeys have no modelled car distance/);
});

test('without missing distances the modelled default is shown and no trip length is asked', async () => {
  const root = panel(async () => ({ ...NEEDS, status: 'complete', car_trip_km: 6, car_trip_km_status: 'modelled',
    car_trip_km_source: 'mean car_distance_km of 7 restored ODs', break_even_trips: 510, per_trip_car_kg: 0.75,
    car_distance_coverage: { restored: 7, missing: 0, by_reason: {} } }));
  await button(root, 'Compute CO2').attrs.onclick();
  assert.match(text(root), /Break-even: 510 avoided car trips/);
  assert.doesNotMatch(text(root), /enter a car trip length/);
  assert.equal(button(root, 'Compute break-even'), undefined);
});
