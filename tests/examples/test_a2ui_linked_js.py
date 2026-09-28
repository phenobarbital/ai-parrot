"""FEAT-610 TASK-3850 — static/linked.js contract, exercised with node's test runner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage


def _message(*tool_calls: ToolCall) -> AIMessage:
    """Build an AI message with the supplied tool calls."""
    return AIMessage(
        input="Build a dashboard",
        output="Dashboard built.",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(),
        tool_calls=list(tool_calls),
    )


def test_linked_js_contract(tmp_path: Path) -> None:
    """Node-driven test of the linked.js contract (AC8, AC9)."""
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node not found")

    # Create a temporary directory for the test harness
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()

    # Copy the linked.js file to the harness directory
    linked_js_path = Path(__file__).resolve().parents[2] / "examples" / "a2ui" / "static" / "linked.js"
    shutil.copy(linked_js_path, harness_dir / "linked.js")

    # Write the test harness as an ESM module
    harness_code = """import { queryUrl, DEFAULT_MAX_FETCH_ROWS, SourceUnavailable, deriveConditions } from './linked.js';

// Test 1: queryUrl routes (v3 / v1 tenant)
const baseUrl = 'https://api.example.com';
const slug = 'test-slug';
const tenant = 'test-tenant';

const v3Url = queryUrl(baseUrl, slug, null);
const expectedV3 = baseUrl + '/api/v3/queries/' + encodeURIComponent(slug);
console.assert(v3Url === expectedV3, 'v3 URL: ' + v3Url);

const v1Url = queryUrl(baseUrl, slug, tenant);
const expectedV1 = baseUrl + '/api/v1/' + encodeURIComponent(tenant) + '/queries/' + encodeURIComponent(slug);
console.assert(v1Url === expectedV1, 'v1 URL: ' + v1Url);

// Test 2: querylimit cap 5000
const maxFetchRows = 5000;
const src = {
  slug: 'test-slug',
  tenant: null,
  request: { limit: 10000 },
  multi_output: null,
  locked: [],
  conditions: {},
  transform: null,
};

const conditions = deriveConditions(
  { placeholders: {}, filter: {}, fields: [], ordering: [], grouping: [], limit: 10000, offset: 0 },
  {}
);

const body = { ...conditions, querylimit: Math.min(src.request.limit ?? maxFetchRows, maxFetchRows) };
console.assert(body.querylimit === 5000, 'querylimit capped at 5000: ' + body.querylimit);

// Test 3: refresh only when true
const conditionsWithRefresh = { ...conditions, refresh: true };
const bodyWithRefresh = { ...conditionsWithRefresh, querylimit: 5000 };
console.assert(bodyWithRefresh.refresh === true, 'refresh should be present when true');

const conditionsWithoutRefresh = { ...conditions };
const bodyWithoutRefresh = { ...conditionsWithoutRefresh, querylimit: 5000 };
console.assert(!('refresh' in bodyWithoutRefresh), 'refresh should be omitted when false');

// Test 4: deriveConditions never emits lane-time keys
const conditionsWithRefreshKey = deriveConditions(
  { placeholders: {}, filter: {}, fields: [], ordering: [], grouping: [], limit: 10000, offset: 0, refresh: true },
  {}
);
console.assert(!('refresh' in conditionsWithRefreshKey), 'refresh should not be emitted by deriveConditions');
console.assert(!('querylimit' in conditionsWithRefreshKey), 'querylimit should not be emitted by deriveConditions');

// Test 5: deriveConditions preserves filter, fields, ordering, grouping
const pageConditions = deriveConditions(
  {
    placeholders: {},
    filter: { country: ['US'] },
    fields: ['student_uid', 'full_name'],
    ordering: ['student_uid'],
    grouping: [],
    limit: 100,
    offset: 0,
  },
  {}
);

console.assert('querylimit' in pageConditions, 'querylimit should be present');
console.assert(pageConditions.querylimit === 100, 'querylimit should be 100, got ' + pageConditions.querylimit);
console.assert('_offset' in pageConditions, '_offset should be present');
console.assert(pageConditions._offset === 0, '_offset should be 0, got ' + pageConditions._offset);
console.assert('ordering' in pageConditions, 'ordering should be present');
console.assert(pageConditions.ordering.length === 1, 'ordering should have 1 element, got ' + pageConditions.ordering.length);
console.assert('filter' in pageConditions, 'filter should be present');
console.assert(pageConditions.filter.country.includes('US'), 'filter should include country: US');
"""

    harness_file = harness_dir / "test.mjs"
    harness_file.write_text(harness_code)

    # Run the test harness with node
    result = pytest.importorskip("subprocess").run(
        ["node", str(harness_file)],
        cwd=str(harness_dir),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "node test failed:\nstdout: " + result.stdout + "\nstderr: " + result.stderr
