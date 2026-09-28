"""FEAT-610 — the browser renderer, driven against a REAL envelope (built by the Python toolkit/builders) under jsdom.

The envelope is generated from ``examples/a2ui/dashboard.WIDGETS`` with the production builders, so any drift between the
wire shape and ``renderer.js`` fails here (this is what a stubbed renderer could never survive).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "examples" / "a2ui" / "static"
UI_NODE_MODULES = ROOT / "packages" / "ai-parrot-server" / "ui" / "node_modules"

from ._envelope import real_envelope  # noqa: E402


HARNESS = r"""
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

globalThis.__A2UI_NO_BOOT__ = true;
const require = createRequire(process.env.UI_NODE_MODULES + '/');
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><body><div id="notice"></div><main id="dashboard"></main></body>');
const doc = dom.window.document;
globalThis.document = doc;
globalThis.window = dom.window;

const inits = [];
const options = [];
dom.window.echarts = {
  init(node) {
    const inst = { node, setOption(o) { options.push({ node, o }); } };
    inits.push(inst);
    return inst;
  },
};

const envelope = JSON.parse(readFileSync(process.env.ENVELOPE, 'utf8'));
const { mountDashboard, planDashboard, parseBinding, chartOption, kpiText, label, login } = await import('./renderer.js');

// --- pure helpers on the real envelope -----------------------------------------------------------------------------
const plan = planDashboard(envelope);
assert.equal(plan.rootId, 'root');
assert.deepEqual(Object.keys(plan.sources), ['kpi_total', 'kpi_studio', 'kpi_mat', 'kpi_multi', 'by_country', 'by_licensee', 'by_course', 'graduates']);
assert.deepEqual(parseBinding(plan.byId.kpi_total.value), { key: 'kpi_total', column: 'total' });
assert.deepEqual(parseBinding(plan.byId.by_country.data), { key: 'by_country', column: null });
assert.equal(parseBinding(undefined), null);
assert.equal(label(null), 'Unassigned');
assert.equal(kpiText([{ total: 17572 }], 'total'), '17,572');
assert.equal(kpiText([], 'total'), '—');

// --- fake QuerySource ----------------------------------------------------------------------------------------------
const canon = (v) => JSON.stringify(v, (_, x) => (x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));
const keyOf = new Map();
for (const [key, src] of Object.entries(plan.sources)) keyOf.set(canon(src.conditions), key);
const calls = [];
const DATA = {
  kpi_total: [{ total: 17572 }], kpi_studio: [{ total: 9191 }], kpi_mat: [{ total: 6245 }], kpi_multi: [{ multi_graduates: 2884 }],
  by_country: Array.from({ length: 95 }, (_, i) => ({ country: i === 0 ? null : `C${i}`, graduates: i + 1 })),
  by_licensee: Array.from({ length: 23 }, (_, i) => ({ licensee: `L${i}`, graduates: i + 1 })),
  by_course: [
    { course: 'Pilates Studio', graduates: 9204 }, { course: 'Pilates Mat', graduates: 6247 },
    { course: 'Reformer', graduates: 3300 }, { course: null, graduates: 2048 },
  ],
};
globalThis.fetch = async (url, init) => {
  const body = JSON.parse(init.body);
  calls.push(body);
  const { querylimit, refresh, _offset, ...conds } = body;
  let out;
  const matched = keyOf.get(canon(conds));
  if (matched && matched !== 'graduates') {
    out = DATA[matched] ?? [];
  } else if (body.fields && body.fields[0] === 'count(*) as total') {
    out = [{ total: body.filter && body.filter.country ? 100 : 17572 }]; // the grid's parallel count request
  } else if (body.fields && body.fields[0] === 'student_uid') {
    out = Array.from({ length: querylimit }, (_, i) => ({ student_uid: (_offset ?? 0) + i, full_name: `n${i}`, country: 'US', licensee: 'l', is_requalified: false, last_diploma_date: null }));
  } else {
    out = [];
  }
  return new Response(JSON.stringify(out), { status: 200, headers: { 'content-type': 'application/json' } });
};
const settle = () => new Promise((r) => setTimeout(r, 30));

const { lane, widgets, refreshAll } = mountDashboard(envelope, { doc, container: doc.getElementById('dashboard'), token: 'T', baseUrl: 'http://h' });
await settle();

// --- AC7: all 8 widgets render with the live values ------------------------------------------------------------------
assert.deepEqual(Object.keys(widgets).sort(), Object.keys(plan.sources).sort());
const kpis = ['kpi_total', 'kpi_studio', 'kpi_mat', 'kpi_multi'].map((k) => doc.querySelector(`[data-widget="${k}"] .kpi-value`).textContent);
assert.deepEqual(kpis, ['17,572', '9,191', '6,245', '2,884']);
const latest = (nodeKey) => options.filter((o) => o.node === widgets[nodeKey].element.querySelector('.chart')).at(-1).o;
assert.equal(latest('by_country').xAxis.data.length, 95);
assert.equal(latest('by_country').xAxis.data[0], 'Unassigned', 'NULL bucket is labelled Unassigned');
assert.equal(latest('by_licensee').xAxis.data.length, 23);
const pie = latest('by_course').series[0];
assert.equal(pie.type, 'pie');
assert.deepEqual(pie.data.map((d) => d.value), [9204, 6247, 3300, 2048]);
assert.equal(pie.data.at(-1).name, 'Unassigned');
assert.equal(latest('by_country').series[0].type, 'bar');

// --- AC9: grid pages on the server, filters change rows and total ---------------------------------------------------
const gridBox = doc.querySelector('[data-widget="graduates"]');
assert.equal(gridBox.querySelectorAll('tbody tr').length, 20);
assert.match(gridBox.querySelector('.grid-info').textContent, /17,572 rows/);
assert.deepEqual([...gridBox.querySelectorAll('thead tr:first-child th')].map((t) => t.textContent), ['student_uid', 'full_name', 'country', 'licensee', 'is_requalified', 'last_diploma_date']);
calls.length = 0;
gridBox.querySelector('.grid-next').onclick();
await settle();
const pageCall = calls.find((c) => c.fields[0] === 'student_uid');
assert.equal(pageCall._offset, 20);
assert.equal(pageCall.querylimit, 20);
assert.deepEqual(pageCall.ordering, ['student_uid']);
calls.length = 0;
const filterInput = gridBox.querySelector('input[data-filter="country"]');
filterInput.value = 'US';
filterInput.onchange();
await settle();
assert.deepEqual(calls.find((c) => c.fields[0] === 'student_uid').filter, { country: 'US' });
assert.match(gridBox.querySelector('.grid-info').textContent, /page 1 \/ 5 · 100 rows/, 'total follows the filter, page resets');

// --- AC8: per-widget refresh = ONE request for its own source, only that widget repaints -------------------------------
const initsBefore = inits.length;
const before = options.length;
calls.length = 0;
doc.querySelector('[data-refresh="kpi_studio"]').onclick();
await settle();
assert.equal(calls.length, 1);
assert.equal(calls[0].refresh, true);
assert.deepEqual(calls[0].filter, plan.sources.kpi_studio.conditions.filter);
assert.equal(options.length, before, 'no chart repaints for a KPI refresh');
calls.length = 0;
doc.querySelector('[data-refresh="by_country"]').onclick();
await settle();
assert.equal(calls.length, 1);
assert.equal(inits.length, initsBefore, 'echarts instance is reused on refresh (no leak)');
assert.equal(options.length, before + 1);
calls.length = 0;
await refreshAll();
await settle();
assert.equal(calls.filter((c) => c.refresh === true).length, 8, 'refresh all re-fetches every source once, bypassing the cache');

// --- envelope text is never injected as HTML --------------------------------------------------------------------------
const evil = JSON.parse(JSON.stringify(envelope));
evil.components.find((c) => c.id === 'kpi_total').title = '<img src=x onerror="window.pwned=1">';
const dom2 = new JSDOM('<!doctype html><main id="d"></main>');
mountDashboard(evil, { doc: dom2.window.document, container: dom2.window.document.getElementById('d'), token: 'T', baseUrl: 'http://h' });
assert.equal(dom2.window.document.querySelector('img'), null);
assert.match(dom2.window.document.querySelector('.kpi-title').textContent, /<img/);

// --- login stores the JWT under ai_parrot_token ---------------------------------------------------------------------
let seen;
const store = new Map();
const token = await login('u', 'p', {
  fetchImpl: async (url, init) => { seen = { url, init }; return new Response(JSON.stringify({ token: 'JWT' }), { status: 200 }); },
  storage: { setItem: (k, v) => store.set(k, v) },
});
assert.equal(token, 'JWT');
assert.equal(store.get('ai_parrot_token'), 'JWT');
assert.equal(seen.url, '/api/v1/login');
assert.deepEqual(JSON.parse(seen.init.body), { username: 'u', password: 'p' });
console.log('renderer: all assertions passed');
process.exit(0);
"""


def test_renderer_against_real_envelope(tmp_path: Path) -> None:
    """renderer.js renders the 8 real widgets with the AC7 values and honours AC8/AC9 (needs node + the UI's jsdom)."""
    if shutil.which("node") is None:
        pytest.skip("node not found")
    if not (UI_NODE_MODULES / "jsdom").exists():
        pytest.skip("jsdom not installed (packages/ai-parrot-server/ui/node_modules)")
    for name in ("renderer.js", "linked.js"):
        shutil.copy(STATIC / name, tmp_path / name)
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(real_envelope()))
    (tmp_path / "test.mjs").write_text(HARNESS)
    result = subprocess.run(
        ["node", "test.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "UI_NODE_MODULES": str(UI_NODE_MODULES), "ENVELOPE": str(envelope_path)},
    )
    assert result.returncode == 0, f"renderer test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "all assertions passed" in result.stdout
