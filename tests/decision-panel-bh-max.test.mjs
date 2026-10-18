import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Minimal document for decision_panel.js: nodes keep attributes and children; nothing is rendered.
function node(tag) {
  return { tag, attrs: {}, children: [], className: '', textContent: '',
    setAttribute(k, v) { this.attrs[k] = String(v); }, addEventListener() {},
    appendChild(c) { this.children.push(c); return c; }, prepend(c) { this.children.unshift(c); },
    replaceChildren(...c) { this.children = c; } };
}
const document = { createElement: node, createTextNode: (t) => ({ text: t, children: [] }),
  getElementById: () => null, head: { appendChild() {} } };
const all = (n, pred, out = []) => { if (pred(n)) out.push(n); (n.children || []).forEach((c) => all(c, pred, out)); return out; };

function render(state) {
  const window = {};
  vm.runInNewContext(fs.readFileSync(new URL('../web/static/decision/decision_panel.js', import.meta.url), 'utf8'),
    { window, document, fetch: async () => ({}) });
  const root = node('section');
  const ctx = { getAppState: () => ({ profile: 'P' }), serverState: state, selected: null, api: async () => ({}),
    select() {}, on: () => () => {}, emit() {}, isOutdated: () => false, fmt: String, pkgName: (ids) => ids.join('+'),
    el: (tag) => node(tag), statusLine: (k, t) => node('div') };
  const panel = window.CityPilotDecision.panels.decision(root, ctx);
  panel.render();
  return root;
}

const STATE = { limits: { B_h_bus_hours: 30, K_new_infra_km: 2, N_a_actions: 3 }, N_a_max: 5, B_h_max: 120,
  reference_bus_hours: 105, objective: { P: { value: 'count', status: 'committed' } }, findings: {} };

test('the B_h slider maximum is B_h_max from /state, not derived from the reference package', () => {
  const ranges = all(render(STATE), (n) => n.tag === 'input' && n.attrs.type === 'range');
  const bh = ranges.find((n) => n.attrs.max === '120');
  assert.ok(bh, `no B_h slider with max 120; got ${JSON.stringify(ranges.map((r) => r.attrs.max))}`);
  const other = render({ ...STATE, B_h_max: 80, reference_bus_hours: 200 });
  const maxes = all(other, (n) => n.tag === 'input' && n.attrs.type === 'range').map((r) => r.attrs.max);
  assert.ok(maxes.includes('80') && !maxes.includes('200'));
});
