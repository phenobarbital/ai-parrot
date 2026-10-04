"""Tests for fixable plane rules (TASK-4014)."""

from __future__ import annotations

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.packs.plane_fix import (
    PLANE_FIX_RULES,
    AsymmetricRelatedRule,
    FtsIndexDriftRule,
)
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


async def _store(tmp_path, edges):
    store = SQLiteWikiStore(tmp_path / "w.db", wiki_name="w")
    await store.upsert_pages([WikiPageRecord(concept_id=c, title=c) for c in ("a", "b", "c")])
    await store.add_edges(edges)
    return store


async def _edges(store):
    return {(e["src"], e["dst"], e["rel"]) for e in await store.dump_edges()}


@pytest.mark.asyncio
async def test_asymmetric_references_fix(tmp_path):
    store = await _store(tmp_path, [("a", "b", "references", "asserted")])
    rule = AsymmetricRelatedRule()
    findings = await rule.check(LintContext(store))
    assert len(findings) == 1 and findings[0].fixable
    res = await rule.fix(LintContext(store), findings[0])
    assert res.applied
    assert ("b", "a", "related") in await _edges(store)
    assert await rule.check(LintContext(store)) == []


@pytest.mark.asyncio
async def test_contains_not_symmetrized(tmp_path):
    store = await _store(tmp_path, [("a", "b", "contains", "asserted")])
    assert await AsymmetricRelatedRule().check(LintContext(store)) == []


@pytest.mark.asyncio
async def test_broken_target_not_symmetrized(tmp_path):
    store = await _store(tmp_path, [("a", "ghost", "references", "asserted")])
    assert await AsymmetricRelatedRule().check(LintContext(store)) == []


@pytest.mark.asyncio
async def test_symmetric_reverse_references_satisfies(tmp_path):
    store = await _store(tmp_path, [("a", "b", "references", "asserted"), ("b", "a", "references", "asserted")])
    assert await AsymmetricRelatedRule().check(LintContext(store)) == []


@pytest.mark.asyncio
async def test_fix_idempotent(tmp_path):
    store = await _store(tmp_path, [("a", "b", "references", "asserted")])
    rule = AsymmetricRelatedRule()
    finding = (await rule.check(LintContext(store)))[0]
    first = await rule.fix(LintContext(store), finding)
    second = await rule.fix(LintContext(store), finding)
    assert first.applied and not second.applied
    assert len(await _edges(store)) == 2


@pytest.mark.asyncio
async def test_fts_drift_rule(tmp_path):
    class Fake:
        def __init__(self):
            self.drift = {"pages_fts": 1}

        async def index_drift(self):
            return self.drift

        async def rebuild_index(self):
            self.drift = {}
            return {"rebuilt": ["pages_fts"]}

    fake = Fake()
    rule = FtsIndexDriftRule()
    ctx = LintContext(fake)  # type: ignore[arg-type]
    findings = await rule.check(ctx)
    assert len(findings) == 1
    assert (await rule.fix(ctx, findings[0])).applied
    assert await rule.check(ctx) == []


def test_exports():
    assert PLANE_FIX_RULES == [AsymmetricRelatedRule, FtsIndexDriftRule]
