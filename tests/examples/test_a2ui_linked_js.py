"""FEAT-610 — static/linked.js contract, exercised for real with node (hard asserts, fake ``fetch``)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "examples" / "a2ui" / "static"

HARNESS = r"""
import assert from 'node:assert/strict';
import {
  queryUrl, fetchSource, deriveConditions, createLane, SourceUnavailable, DEFAULT_MAX_FETCH_ROWS,
} from './linked.js';

const calls = [];
let responder = () => [];
globalThis.fetch = async (url, init) => {
  const body = init && init.body ? JSON.parse(init.body) : null;
  calls.push({ url, body, headers: init && init.headers });
  const out = responder(url, body);
  if (out instanceof Response) return out;
  return new Response(JSON.stringify(out), { status: 200, headers: { 'content-type': 'application/json' } });
};
const reset = () => { calls.length = 0; responder = () => []; };

const source = (over = {}) => ({
  slug: 'polestar_graduates_directory', tenant: null, multi_output: null, locked: [], transform: null,
  conditions: {}, params: {},
  request: { placeholders: {}, filter: {}, fields: [], ordering: [], grouping: [], limit: null, offset: null },
  ...over,
});

// --- routes -------------------------------------------------------------------------------------------------------
assert.equal(queryUrl('https://h/', 'a b', null), 'https://h/api/v3/queries/a%20b');
assert.equal(queryUrl('https://h', 's', 'acme'), 'https://h/api/v1/acme/queries/s');

// --- deriveConditions never emits lane-time keys --------------------------------------------------------------------
const derived = deriveConditions({ placeholders: { refresh: true, querylimit: 1, a: 1 }, filter: {}, fields: [], ordering: [], grouping: [] }, {});
assert.deepEqual(derived, { a: 1 });
const page = deriveConditions({ placeholders: {}, filter: { c: 'US' }, fields: ['x'], ordering: ['x'], grouping: [], limit: 10, offset: 5 }, {});
assert.deepEqual(page, { filter: { c: 'US' }, fields: ['x'], ordering: ['x'], _offset: 5 });

// --- fetchSource: cap, bearer, refresh only when true, 404 ----------------------------------------------------------
reset();
await fetchSource(source({ request: { ...source().request, limit: 99999 } }), { refresh: true }, { baseUrl: 'https://h', token: 'T' });
assert.equal(calls[0].body.querylimit, DEFAULT_MAX_FETCH_ROWS);
assert.equal(calls[0].body.refresh, true);
assert.equal(calls[0].headers.Authorization, 'Bearer T');
reset();
await fetchSource(source(), { refresh: false }, { baseUrl: 'https://h', token: 'T' });
assert.ok(!('refresh' in calls[0].body));
reset();
responder = () => new Response('nope', { status: 404 });
await assert.rejects(fetchSource(source(), {}, { baseUrl: 'https://h', token: 'T' }), SourceUnavailable);

// --- lane: refreshSource is ONE request for its own key; refreshAll one per source ------------------------------------
const sources = { a: source({ request: { ...source().request, fields: ['count(*) as total'] } }), b: source(), c: source() };
reset();
responder = () => [{ total: 1 }];
const updates = [];
const lane = createLane(sources, { baseUrl: 'https://h', token: 'T', onUpdate: (u) => updates.push(u) });
lane.start();
await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.length, 3, 'start fetches each source once');
calls.length = 0;
updates.length = 0;
await lane.refreshSource('b');
assert.equal(calls.length, 1, 'refreshSource re-fetches only that key');
assert.equal(calls[0].body.refresh, true);
assert.deepEqual([...new Set(updates.map((u) => u.key))], ['b']);
calls.length = 0;
await lane.refreshAll();
assert.equal(calls.length, 3, 'refreshAll re-fetches every source');
calls.length = 0;
await Promise.all([lane.refreshSource('a'), lane.refreshSource('a')]);
assert.equal(calls.length, 1, 'concurrent refreshSource calls share one request');
calls.length = 0;
await lane.refreshSource('nope');
assert.equal(calls.length, 0, 'unknown key is a no-op');

// --- fetchPage: server paging over the source's own conditions -------------------------------------------------------
const grid = { g: source({ request: { ...source().request, fields: ['student_uid', 'country'], ordering: ['student_uid'], limit: 500, filter: { active: true } } }) };
reset();
responder = (url, body) => (body.fields && body.fields[0] === 'count(*) as total' ? [{ total: 17572 }] : [{ student_uid: 1, country: 'US' }]);
const glane = createLane(grid, { baseUrl: 'https://h', token: 'T', onUpdate: () => {} });
const result = await glane.fetchPage('g', { offset: 40, limit: 20, filter: { country: 'US', empty: '' } });
assert.equal(result.total, 17572);
assert.deepEqual(result.rows, [{ student_uid: 1, country: 'US' }]);
assert.equal(calls.length, 2, 'one page request + one count request');
const pageCall = calls.find((c) => c.body.fields[0] !== 'count(*) as total').body;
const countCall = calls.find((c) => c.body.fields[0] === 'count(*) as total').body;
assert.equal(pageCall.querylimit, 20);
assert.equal(pageCall._offset, 40);
assert.deepEqual(pageCall.ordering, ['student_uid'], 'stable ordering is always sent');
assert.deepEqual(pageCall.filter, { active: true, country: 'US' }, 'column filter merges; empty values are dropped');
assert.deepEqual(countCall.filter, pageCall.filter, 'count uses the same filter');
assert.ok(!('ordering' in countCall) && !('_offset' in countCall) && !('grouping' in countCall));
await assert.rejects(glane.fetchPage('missing'), /unknown source/);

// --- paged keys are excluded from start / refreshAll / refreshSource; fetchPage(refresh) bypasses the cache ------------
reset();
responder = () => [{ total: 1 }];
const plane = createLane({ ...sources, g: grid.g }, { baseUrl: 'https://h', token: 'T', onUpdate: () => {}, pagedKeys: ['g'] });
plane.start();
await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.length, 3, 'start skips the paged source');
calls.length = 0;
await plane.refreshAll();
assert.equal(calls.length, 3, 'refreshAll skips the paged source');
calls.length = 0;
await plane.refreshSource('g');
assert.equal(calls.length, 0, 'refreshSource on a paged key is a no-op');
await plane.fetchPage('g', { refresh: true });
assert.equal(calls.length, 2);
assert.ok(calls.every((c) => c.body.refresh === true), 'page and count both bypass the cache');

// --- linked dashboards: one shared parent fetch feeds N derived views; refresh cascades; params are ignored ------------
const GEO = [
  { country: 'US', licensee: 'a', graduates: 10 }, { country: 'MX', licensee: 'a', graduates: 5 },
  { country: 'US', licensee: 'b', graduates: 20 }, { country: null, licensee: 'b', graduates: 1 },
];
const dsources = {
  by_country: { kind: 'derived', from: 'geo', target: '/by_country/rows',
    transform: { ops: [{ op: 'group_by', by: ['country'], aggregate: { graduates: 'sum' } }, { op: 'sort', by: [{ column: 'graduates', direction: 'desc' }] }] } },
  geo: source({ kind: 'query_slug', request: { ...source().request, fields: ['country', 'licensee', 'count(*) as graduates'], grouping: ['country', 'licensee'] } }),
  by_licensee: { kind: 'derived', from: 'geo', target: '/by_licensee/rows',
    transform: { ops: [{ op: 'group_by', by: ['licensee'], aggregate: { graduates: 'sum' } }] } },
  top: { kind: 'derived', from: 'by_country', target: '/top/rows', transform: { ops: [{ op: 'limit', n: 1 }] } },
};
reset();
responder = () => GEO;
const dupdates = [];
const dlane = createLane(dsources, { baseUrl: 'https://h', token: 'T', onUpdate: (u) => dupdates.push(u) });
dlane.start();
await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.length, 1, 'start fetches the shared parent exactly once; derived views are never fetched');
const readyKeys = dupdates.filter((u) => u.status === 'ready').map((u) => u.key);
assert.deepEqual(readyKeys, ['geo', 'by_country', 'top', 'by_licensee'], 'parent first, then its derived views (chain included)');
const rowsOf = (key) => dupdates.filter((u) => u.status === 'ready' && u.key === key).at(-1).rows;
assert.deepEqual(rowsOf('by_country'), [{ country: 'US', graduates: 30 }, { country: 'MX', graduates: 5 }], 'group_by drops the NULL key, sort desc');
assert.deepEqual(rowsOf('by_licensee'), [{ licensee: 'a', graduates: 15 }, { licensee: 'b', graduates: 21 }]);
assert.deepEqual(rowsOf('top'), [{ country: 'US', graduates: 30 }]);
calls.length = 0;
dupdates.length = 0;
await dlane.refreshSource('by_licensee');
assert.equal(calls.length, 1, 'refreshing a derived view re-fetches its parent once');
assert.equal(calls[0].body.refresh, true);
assert.deepEqual(dupdates.filter((u) => u.status === 'ready').map((u) => u.key), ['geo', 'by_country', 'top', 'by_licensee'], 'the cascade recomputes every derived view');
calls.length = 0;
await dlane.refreshAll();
assert.equal(calls.length, 1, 'refreshAll fetches only the query-slug source');
calls.length = 0;
await dlane.setParam('by_country', 'firstdate', '2026-01-01');
assert.equal(calls.length, 0, 'a derived view takes no params');
dupdates.length = 0;
responder = () => new Response('nope', { status: 404 });
await dlane.refreshSource('geo');
assert.deepEqual(dupdates.filter((u) => u.status !== 'loading').map((u) => [u.key, u.status]).sort(),
  [['by_country', 'error'], ['by_licensee', 'error'], ['geo', 'unavailable'], ['top', 'error']], 'a parent failure takes its derived views down, snapshots kept');
await assert.rejects(dlane.fetchPage('by_country'), /unknown source/);

// --- the DSL port passes the shared golden fixtures (contract/fixtures/dsl) -------------------------------------------
const { applyTransform } = await import('./dsl.js');
const fixtures = JSON.parse(process.env.DSL_FIXTURES);
for (const fx of fixtures) {
  const out = applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {});
  assert.deepEqual(out, fx.expected, `dsl fixture ${fx.name}: ${fx.description}`);
}
assert.ok(fixtures.length >= 10, 'the golden DSL fixtures were loaded');
console.log('linked.js: all assertions passed');
"""

FIXTURES = (
    Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl"
)
# Fixtures whose expectations depend on pandas dtype/datetime semantics the row-based JS port does not model.
SKIPPED_FIXTURES = {"dtype_preservation.json", "tz_datetime_roundtrip.json"}


def test_linked_js_contract(tmp_path: Path) -> None:
    """linked.js: routes, conditions, cap, refresh semantics (AC8), server paging (AC9), derived views and the DSL port."""
    if shutil.which("node") is None:
        pytest.skip("node not found")
    for name in ("linked.js", "dsl.js"):
        shutil.copy(STATIC / name, tmp_path / name)
    fixtures = [
        {"name": path.name, **json.loads(path.read_text())}
        for path in sorted(FIXTURES.glob("*.json"))
        if path.name not in SKIPPED_FIXTURES
    ]
    (tmp_path / "test.mjs").write_text(HARNESS)
    result = subprocess.run(
        ["node", "test.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DSL_FIXTURES": json.dumps(fixtures)},
    )
    assert result.returncode == 0, f"node test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "all assertions passed" in result.stdout
