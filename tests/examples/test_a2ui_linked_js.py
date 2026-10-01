"""FEAT-610 — static/linked.js contract, exercised for real with node (hard asserts, fake ``fetch``)."""

from __future__ import annotations

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
console.log('linked.js: all assertions passed');
"""


def test_linked_js_contract(tmp_path: Path) -> None:
    """linked.js: routes, conditions, cap, refresh semantics (AC8) and server paging (AC9) with hard asserts."""
    if shutil.which("node") is None:
        pytest.skip("node not found")
    shutil.copy(STATIC / "linked.js", tmp_path / "linked.js")
    (tmp_path / "test.mjs").write_text(HARNESS)
    result = subprocess.run(["node", "test.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"node test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "all assertions passed" in result.stdout
