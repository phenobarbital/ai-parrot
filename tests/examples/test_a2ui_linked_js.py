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
assert.equal(queryUrl('https://h/', 'a b', null), 'https://h/api/v2/services/queries/a%20b');
assert.equal(queryUrl('https://h', 's', null, true), 'https://h/api/v3/queries/s');
assert.equal(queryUrl('https://h', 's', 'acme'), 'https://h/api/v1/acme/queries/s');
assert.equal(queryUrl('https://h', 's', 'acme', true), 'https://h/api/v1/acme/queries/s');

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
reset();
await fetchSource(source(), {}, { baseUrl: 'https://h', token: 'T' });
assert.equal(calls[0].url, 'https://h/api/v2/services/queries/polestar_graduates_directory');
reset();
await fetchSource(source({ is_multiquery: true }), {}, { baseUrl: 'https://h', token: 'T' });
assert.equal(calls[0].url, 'https://h/api/v3/queries/polestar_graduates_directory');
reset();
responder = () => new Response(null, { status: 204 });
assert.deepEqual(await fetchSource(source(), {}, { baseUrl: 'https://h', token: 'T' }), []);

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
assert.deepEqual(readyKeys, ['geo', 'by_country', 'by_licensee', 'top'], 'parent first, then its derived views (chain included)');
const rowsOf = (key) => dupdates.filter((u) => u.status === 'ready' && u.key === key).at(-1).rows;
assert.deepEqual(rowsOf('by_country'), [{ country: 'US', graduates: 30 }, { country: 'MX', graduates: 5 }], 'group_by drops the NULL key, sort desc');
assert.deepEqual(rowsOf('by_licensee'), [{ licensee: 'a', graduates: 15 }, { licensee: 'b', graduates: 21 }]);
assert.deepEqual(rowsOf('top'), [{ country: 'US', graduates: 30 }]);
calls.length = 0;
dupdates.length = 0;
await dlane.refreshSource('by_licensee');
assert.equal(calls.length, 1, 'refreshing a derived view re-fetches its parent once');
assert.equal(calls[0].body.refresh, true);
assert.deepEqual(dupdates.filter((u) => u.status === 'ready').map((u) => u.key), ['geo', 'by_country', 'by_licensee', 'top'], 'the cascade recomputes every derived view');
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

// --- adversarial graphs: no deadlock, no stale joined frame, one fetch per parent per pass ------------------------------
const withTimeout = (p, ms = 500) => Promise.race([p, new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${ms}ms`)), ms))]);
const joinOps = (w) => ({ ops: [{ op: 'join', with: w, how: 'left', on: [{ left: 'k', right: 'k' }] }] });
reset();
let qv = 0;
responder = (url) => (url.endsWith('/Q') ? [{ k: 1, qv: ++qv }] : [{ k: 1, v: url.split('/').pop() }]);
const gupdates = [];
const glatest = (key) => gupdates.filter((u) => u.status === 'ready' && u.key === key).at(-1)?.rows;
// J (query) joins D (derived from P); P's cascade waits on D while J waits on D: must not deadlock.
const graph = {
  J: source({ slug: 'J', kind: 'query_slug', transform: joinOps('D') }),
  P: source({ slug: 'P', kind: 'query_slug' }),
  D: { kind: 'derived', from: 'P', target: '/D/rows', transform: { ops: [{ op: 'rename', mapping: { v: 'pv' } }] } },
  Q: source({ slug: 'Q', kind: 'query_slug' }),
  E: { kind: 'derived', from: 'P', target: '/E/rows', transform: joinOps('Q') },
};
const glane2 = createLane(graph, { baseUrl: 'https://h', token: 'T', onUpdate: (u) => gupdates.push(u) });
glane2.start();
await withTimeout(new Promise((resolve) => {
  const tick = () => (gupdates.filter((u) => u.status === 'ready').length >= 5 ? resolve() : setTimeout(tick, 5));
  tick();
}));
assert.deepEqual([...calls.map((c) => c.url.split('/').pop())].sort(), ['J', 'P', 'Q'], 'each source fetched once (J declared before P still joins P\'s fetch)');
assert.equal(calls[0].url.split('/').pop(), 'P', 'dependencies first');
assert.deepEqual(glatest('J'), [{ k: 1, v: 'J', pv: 'P' }]);
assert.deepEqual(glatest('E'), [{ k: 1, v: 'P', qv: 1 }]);
calls.length = 0;
await withTimeout(glane2.refreshSource('Q'));
assert.deepEqual(glatest('E'), [{ k: 1, v: 'P', qv: 2 }], 'a derived view joining a sibling is recomputed when the sibling changes');
assert.equal(calls.length, 1);
calls.length = 0;
await withTimeout(glane2.refreshAll());
assert.deepEqual(glatest('E'), [{ k: 1, v: 'P', qv: 3 }], 'refreshAll never leaves a derived join on a stale sibling frame');
assert.deepEqual([...calls.map((c) => c.url.split('/').pop())].sort(), ['J', 'P', 'Q'], 'refreshAll: one fetch per query-slug source');
assert.equal(calls[0].url.split('/').pop(), 'P', 'refreshAll: dependencies first');

// --- the DSL port passes EVERY shared golden fixture (contract/fixtures/dsl), error fixtures included --------------------
const { applyTransform, TransformError } = await import('./dsl.js');
const fixtures = JSON.parse(process.env.DSL_FIXTURES);
for (const fx of fixtures) {
  if (fx.error) {
    assert.throws(() => applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {}), (err) => err instanceof TransformError && err.opIndex === fx.error.op_index, `dsl fixture ${fx.name}`);
    continue;
  }
  const out = applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {});
  assert.deepEqual(out, fx.expected, `dsl fixture ${fx.name}: ${fx.description}`);
}
assert.ok(fixtures.length >= 19, 'every golden DSL fixture was loaded');
console.log('linked.js: all assertions passed');
"""

FIXTURES = (
    Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl"
)


def test_linked_js_contract(tmp_path: Path) -> None:
    """linked.js: routes, conditions, cap, refresh semantics (AC8), server paging (AC9), derived views and the DSL port."""
    if shutil.which("node") is None:
        pytest.skip("node not found")
    for name in ("linked.js", "dsl.js"):
        shutil.copy(STATIC / name, tmp_path / name)
    fixtures = [{"name": path.name, **json.loads(path.read_text())} for path in sorted(FIXTURES.glob("*.json"))]
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
