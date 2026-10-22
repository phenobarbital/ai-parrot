"""A2UI finance example — the shared renderer against the REAL definition-only finance envelope under jsdom.

The envelope ships no rows: KPIs must show the placeholder first, then the live values once the lane fetched every
source exactly once from the v2 services route; the trend renders as a line series.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ._finance_envelope import real_finance_envelope

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "examples" / "a2ui" / "static"
UI_NODE_MODULES = ROOT / "packages" / "ai-parrot-server" / "ui" / "node_modules"

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

const options = [];
dom.window.echarts = { init(node) { const inst = { node, setOption(o) { options.push({ node, o }); } }; return inst; } };

const envelope = JSON.parse(readFileSync(process.env.ENVELOPE, 'utf8'));
const { mountDashboard, planDashboard, chartOption } = await import('./renderer.js');

const plan = planDashboard(envelope);
assert.deepEqual(Object.keys(plan.sources), ['kpi_rev_actual', 'kpi_rev_budget', 'kpi_rev_variance', 'kpi_ebitda_variance', 'by_division', 'by_project', 'trend', 'latest_rows']);
for (const key of Object.keys(plan.sources)) assert.deepEqual(plan.snapshot[key], [], `definition-only: ${key} ships no rows`);

// --- chartOption: line type -----------------------------------------------------------------------------------------
const lineOpt = chartOption(plan.byId.trend, [{ snapshot_date: '2026-09-01', rev_actual: 1, rev_budget: 2 }]);
assert.equal(lineOpt.series.length, 2);
assert.ok(lineOpt.series.every((s) => s.type === 'line'));
assert.equal(chartOption(plan.byId.by_division, [{ division: 'N', rev_actual: 1, rev_budget: 2 }]).series[0].type, 'bar');

// --- fake QuerySource ----------------------------------------------------------------------------------------------
const canon = (v) => JSON.stringify(v, (_, x) => (x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));
const keyOf = new Map();
for (const [key, src] of Object.entries(plan.sources)) keyOf.set(canon(src.conditions), key);
const calls = [];
const LATEST = [
  { snapshot_date: '2026-09-02', division: 'North', project: 'Alpha', rev_actual: 100, rev_budget: 90, ebitda_actual: 20, ebitda_budget: 25 },
  { snapshot_date: '2026-09-02', division: 'South', project: 'Gamma', rev_actual: 70, rev_budget: 70, ebitda_actual: 10, ebitda_budget: 12 },
];
const DATA = {
  kpi_rev_actual: [{ rev_actual: 170 }], kpi_rev_budget: [{ rev_budget: 160 }], kpi_rev_variance: [{ rev_variance: 10 }], kpi_ebitda_variance: [{ ebitda_variance: -7 }],
  by_division: [{ division: 'North', rev_actual: 100, rev_budget: 90 }, { division: 'South', rev_actual: 70, rev_budget: 70 }],
  by_project: [{ project: 'Alpha', rev_actual: 100 }, { project: 'Gamma', rev_actual: 70 }],
  trend: [{ snapshot_date: '2026-09-01', rev_actual: 150, rev_budget: 150 }, { snapshot_date: '2026-09-02', rev_actual: 170, rev_budget: 160 }],
};
globalThis.fetch = async (url, init) => {
  const body = JSON.parse(init.body);
  calls.push({ url, body });
  const { querylimit, refresh, _offset, ...conds } = body;
  const matched = keyOf.get(canon(conds));
  let out;
  if (matched && matched !== 'latest_rows') out = DATA[matched];
  else if (body.fields && body.fields[0] === 'count(*) as total') out = [{ total: LATEST.length }];
  else out = LATEST.slice(_offset ?? 0, (_offset ?? 0) + querylimit);
  return new Response(JSON.stringify(out), { status: 200, headers: { 'content-type': 'application/json' } });
};
const settle = () => new Promise((r) => setTimeout(r, 30));

const { widgets } = mountDashboard(envelope, { doc, container: doc.getElementById('dashboard'), token: 'T', baseUrl: 'http://h' });
const kpiValue = (k) => doc.querySelector(`[data-widget="${k}"] .kpi-value`).textContent;
assert.equal(kpiValue('kpi_rev_actual'), '—', 'no snapshot: the KPI shows the placeholder until the lane answers');
await settle();

assert.ok(calls.every((c) => c.url.startsWith('http://h/api/v2/services/queries/')), 'every fetch uses the v2 services route');
assert.ok(calls.some((c) => c.url.endsWith('/finance_projection_snapshots')), 'the trend hits the snapshots slug');
const laneCalls = calls.filter((c) => !(c.body.fields && (c.body.fields[0] === 'count(*) as total' || c.body.fields[0] === 'snapshot_date' && c.body.querylimit === 20)));
const perKey = {};
for (const c of laneCalls) { const { querylimit, refresh, _offset, ...conds } = c.body; const k = keyOf.get(canon(conds)); if (k) perKey[k] = (perKey[k] ?? 0) + 1; }
for (const key of ['kpi_rev_actual', 'kpi_rev_budget', 'kpi_rev_variance', 'kpi_ebitda_variance', 'by_division', 'by_project', 'trend']) {
  assert.equal(perKey[key], 1, `${key} is fetched exactly once on mount`);
}
assert.equal(calls.filter((c) => c.body.querylimit === 500).length, 0, 'the grid source is never fetched as a 500-row lane frame');

assert.deepEqual(['kpi_rev_actual', 'kpi_rev_budget', 'kpi_rev_variance', 'kpi_ebitda_variance'].map(kpiValue), ['170', '160', '10', '-7']);
const latest = (nodeKey) => options.filter((o) => o.node === widgets[nodeKey].element.querySelector('.chart')).at(-1).o;
assert.ok(latest('trend').series.every((s) => s.type === 'line'));
assert.deepEqual(latest('trend').xAxis.data, ['2026-09-01', '2026-09-02']);
assert.equal(latest('by_division').series.length, 2);
assert.equal(latest('by_project').series[0].type, 'pie');

const gridBox = doc.querySelector('[data-widget="latest_rows"]');
assert.equal(gridBox.querySelectorAll('tbody tr').length, 2);
assert.deepEqual([...gridBox.querySelectorAll('thead tr:first-child th')].map((t) => t.textContent), ['snapshot_date', 'division', 'project', 'rev_actual', 'rev_budget', 'ebitda_actual', 'ebitda_budget']);
const pageCall = calls.find((c) => c.body.fields && c.body.fields[0] === 'snapshot_date' && c.body.querylimit === 20);
assert.deepEqual(pageCall.body.ordering, ['division', 'project']);
console.log('finance renderer: all assertions passed');
process.exit(0);
"""


def test_finance_renderer_against_definition_only_envelope(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node not found")
    if not (UI_NODE_MODULES / "jsdom").exists():
        pytest.skip("jsdom not installed (packages/ai-parrot-server/ui/node_modules)")
    for name in ("renderer.js", "linked.js"):
        shutil.copy(STATIC / name, tmp_path / name)
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(real_finance_envelope()))
    (tmp_path / "test.mjs").write_text(HARNESS)
    result = subprocess.run(
        ["node", "test.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:" + str(Path(shutil.which("node")).parent),
            "ENVELOPE": str(envelope_path),
            "UI_NODE_MODULES": str(UI_NODE_MODULES),
        },
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "finance renderer: all assertions passed" in result.stdout
