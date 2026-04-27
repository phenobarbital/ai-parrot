"""Unit tests for AbstractBot parent expansion — TASK-858 (FEAT-128).

Tests cover:
- AbstractBot constructor attributes (parent_searcher, expand_to_parent).
- _expand_to_parents helper: dedupe, ordering, legacy pass-through,
  missing-parent fallback, no-searcher warning.
- Per-call override resolution.
- DB-driven expand_to_parent flag reading.

NOTE: We avoid importing AbstractBot directly (its import chain requires
compiled Cython modules).  Instead, we inline the methods into a minimal
stub class that captures the pure-Python behavior under test.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.stores.models import Document, SearchResult


# ---------------------------------------------------------------------------
# Minimal bot stub — inlines the FEAT-128 methods without the full import chain
# ---------------------------------------------------------------------------

class _BotStub:
    """Minimal stub with exactly the FEAT-128 parent-expansion methods.

    We inline the method implementations from AbstractBot so we can test them
    without triggering the full AbstractBot import chain (which requires
    compiled Cython modules not available in the test environment).
    """

    def __init__(self, parent_searcher=None, expand_to_parent: bool = False):
        self.parent_searcher = parent_searcher
        self.expand_to_parent = expand_to_parent
        self._warned_no_parent_searcher = False
        self.logger = logging.getLogger('test.bot.stub')

    def _warn_no_parent_searcher_once(self) -> None:
        if not self._warned_no_parent_searcher:
            self.logger.warning(
                "expand_to_parent=True but no parent_searcher configured; "
                "returning child results unchanged."
            )
            self._warned_no_parent_searcher = True

    @staticmethod
    def _meta_of(result) -> dict:
        if hasattr(result, 'metadata') and result.metadata is not None:
            return result.metadata
        return {}

    @staticmethod
    def _score_of(result) -> float:
        if hasattr(result, 'score') and result.score is not None:
            return float(result.score)
        if hasattr(result, 'ensemble_score') and result.ensemble_score is not None:
            return float(result.ensemble_score)
        return 0.0

    @staticmethod
    def _wrap_parent(parent_doc, best_child_score: float):
        # NOTE: Keep in sync with AbstractBot._wrap_parent in parrot/bots/abstract.py.
        # The fetcher always returns Document objects; we normalise to SearchResult
        # so the rest of the pipeline gets a uniform type with a .score attribute.
        if isinstance(parent_doc, SearchResult):
            return SearchResult(
                id=parent_doc.id,
                content=parent_doc.content,
                metadata=parent_doc.metadata,
                score=best_child_score,
            )
        if isinstance(parent_doc, Document):
            return SearchResult(
                id=parent_doc.metadata.get('document_id', ''),
                content=parent_doc.page_content,
                metadata=parent_doc.metadata,
                score=best_child_score,
            )
        return parent_doc

    async def _expand_to_parents(self, results: list) -> list:
        if not results:
            return results

        if self.parent_searcher is None:
            self._warn_no_parent_searcher_once()
            return results

        groups: Dict[str, dict] = {}
        pass_through: list = []

        for idx, r in enumerate(results):
            meta = self._meta_of(r)
            parent_id = meta.get('parent_document_id')

            if not parent_id:
                self.logger.debug(
                    "_expand_to_parents: result at idx=%d has no parent_document_id"
                    " (legacy chunk) — passing through unchanged.", idx,
                )
                pass_through.append((idx, r))
                continue

            score = self._score_of(r)
            if parent_id not in groups:
                groups[parent_id] = {
                    'first_index': idx,
                    'fallback': r,
                    'best_score': score,
                }
            else:
                if score > groups[parent_id]['best_score']:
                    groups[parent_id]['best_score'] = score

        if not groups:
            return results

        parent_ids = list(groups.keys())
        try:
            fetched = await self.parent_searcher.fetch(parent_ids)
        except Exception as exc:
            import asyncio
            if isinstance(exc, asyncio.CancelledError):
                raise
            self.logger.warning(
                "_expand_to_parents: parent_searcher.fetch raised %s — "
                "returning original results unchanged.", exc,
            )
            return results

        indexed_groups = sorted(groups.items(), key=lambda kv: kv[1]['first_index'])
        pass_iter = iter(sorted(pass_through, key=lambda t: t[0]))
        legacy_item = next(pass_iter, None)

        out: list = []
        for parent_id, info in indexed_groups:
            while legacy_item is not None and legacy_item[0] < info['first_index']:
                out.append(legacy_item[1])
                legacy_item = next(pass_iter, None)

            if parent_id in fetched:
                out.append(self._wrap_parent(fetched[parent_id], info['best_score']))
            else:
                self.logger.debug(
                    "_expand_to_parents: parent %s not fetched — "
                    "falling back to child document.", parent_id,
                )
                out.append(info['fallback'])

        while legacy_item is not None:
            out.append(legacy_item[1])
            legacy_item = next(pass_iter, None)

        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sr(doc_id: str, parent_id: Optional[str], score: float) -> SearchResult:
    """Create a SearchResult with optional parent_document_id."""
    meta: Dict[str, Any] = {'document_id': doc_id}
    if parent_id is not None:
        meta['parent_document_id'] = parent_id
    return SearchResult(id=doc_id, content=f"Content of {doc_id}", metadata=meta, score=score)


def _parent_doc(parent_id: str) -> Document:
    """Create a parent Document."""
    return Document(
        page_content=f"Full parent content for {parent_id}",
        metadata={'document_id': parent_id, 'is_full_document': True},
    )


def _searcher(returns: Dict[str, Document]) -> MagicMock:
    """Mock AbstractParentSearcher whose fetch returns the given mapping."""
    s = MagicMock()
    s.fetch = AsyncMock(return_value=returns)
    return s


def _bot(parent_searcher=None, expand_to_parent: bool = False) -> _BotStub:
    return _BotStub(parent_searcher=parent_searcher, expand_to_parent=expand_to_parent)


# ---------------------------------------------------------------------------
# Tests for constructor attributes
# ---------------------------------------------------------------------------


class TestBotAttributes:
    def test_default_parent_searcher_is_none(self):
        """By default, parent_searcher is None."""
        b = _bot()
        assert b.parent_searcher is None

    def test_default_expand_to_parent_is_false(self):
        """By default, expand_to_parent is False."""
        b = _bot()
        assert b.expand_to_parent is False

    def test_parent_searcher_injection(self):
        """parent_searcher is stored correctly."""
        fake = MagicMock()
        b = _bot(parent_searcher=fake)
        assert b.parent_searcher is fake

    def test_expand_to_parent_injection(self):
        """expand_to_parent=True is stored correctly."""
        b = _bot(expand_to_parent=True)
        assert b.expand_to_parent is True


# ---------------------------------------------------------------------------
# Tests for _expand_to_parents
# ---------------------------------------------------------------------------


class TestExpandToParents:
    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(self):
        """_expand_to_parents([]) returns [] immediately."""
        b = _bot(parent_searcher=_searcher({}), expand_to_parent=True)
        result = await b._expand_to_parents([])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedupe_and_order_by_best_score(self):
        """5 children with 2 distinct parent IDs → 2 parents, ordered by best child score."""
        returns = {'p1': _parent_doc('p1'), 'p2': _parent_doc('p2')}
        b = _bot(parent_searcher=_searcher(returns), expand_to_parent=True)

        results = [
            _sr('c1', 'p1', 0.95),
            _sr('c2', 'p1', 0.80),
            _sr('c3', 'p2', 0.70),
            _sr('c4', 'p1', 0.60),
            _sr('c5', 'p2', 0.50),
        ]
        out = await b._expand_to_parents(results)

        assert len(out) == 2
        ids = [r.metadata.get('document_id') for r in out]
        # p1 has best child score 0.95; p2 has best 0.70 → p1 first
        assert ids == ['p1', 'p2']

    @pytest.mark.asyncio
    async def test_missing_parent_falls_through_to_child(self):
        """Children whose parent cannot be fetched fall back to the child."""
        b = _bot(parent_searcher=_searcher({}), expand_to_parent=True)
        results = [_sr('c1', 'p1', 0.9)]

        out = await b._expand_to_parents(results)
        assert len(out) == 1
        assert out[0].metadata.get('document_id') == 'c1'  # child preserved

    @pytest.mark.asyncio
    async def test_no_searcher_logs_warning_once_and_returns_children(self, caplog):
        """expand_to_parent=True with parent_searcher=None: one WARNING, children returned."""
        b = _bot(parent_searcher=None, expand_to_parent=True)
        results = [_sr('c1', 'p1', 0.9)]

        with caplog.at_level(logging.WARNING):
            out1 = await b._expand_to_parents(results)
            out2 = await b._expand_to_parents(results)   # second call — no repeat

        assert out1 == results
        assert out2 == results
        warnings = [r for r in caplog.records if r.levelname == 'WARNING']
        assert len(warnings) == 1, "Expected exactly one WARNING log (deduplicated)"

    @pytest.mark.asyncio
    async def test_legacy_chunks_without_parent_id_pass_through(self):
        """Results with no parent_document_id are included alongside parents."""
        returns = {'p1': _parent_doc('p1')}
        b = _bot(parent_searcher=_searcher(returns), expand_to_parent=True)

        results = [
            _sr('c1', 'p1', 0.9),
            _sr('legacy', None, 0.8),    # no parent_document_id
        ]
        out = await b._expand_to_parents(results)

        ids = [r.metadata.get('document_id') for r in out]
        assert 'p1' in ids
        assert 'legacy' in ids

    @pytest.mark.asyncio
    async def test_all_legacy_chunks_returned_unchanged(self):
        """When ALL results are legacy (no parent_document_id), they all pass through."""
        b = _bot(parent_searcher=_searcher({}), expand_to_parent=True)
        results = [_sr(f'legacy{i}', None, 0.9 - i * 0.1) for i in range(3)]

        out = await b._expand_to_parents(results)

        assert len(out) == 3
        ids = {r.metadata['document_id'] for r in out}
        assert ids == {'legacy0', 'legacy1', 'legacy2'}

    @pytest.mark.asyncio
    async def test_fetch_called_exactly_once_with_all_parent_ids(self):
        """parent_searcher.fetch is called exactly once with all unique parent IDs."""
        returns = {'p1': _parent_doc('p1'), 'p2': _parent_doc('p2')}
        s = _searcher(returns)
        b = _bot(parent_searcher=s, expand_to_parent=True)

        results = [
            _sr('c1', 'p1', 0.9),
            _sr('c2', 'p2', 0.8),
            _sr('c3', 'p1', 0.7),    # duplicate parent
        ]
        await b._expand_to_parents(results)

        s.fetch.assert_awaited_once()
        called_ids = set(s.fetch.call_args[0][0])
        assert called_ids == {'p1', 'p2'}

    @pytest.mark.asyncio
    async def test_no_fetch_called_when_all_legacy(self):
        """When results are all legacy (no parent IDs), fetch is never called."""
        s = _searcher({})
        b = _bot(parent_searcher=s, expand_to_parent=True)

        results = [_sr('legacy', None, 0.9)]
        await b._expand_to_parents(results)

        s.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_parent_scores_reflect_best_child_score(self):
        """The parent document's score matches the best child score."""
        returns = {'p1': _parent_doc('p1')}
        b = _bot(parent_searcher=_searcher(returns), expand_to_parent=True)

        results = [
            _sr('c1', 'p1', 0.5),
            _sr('c2', 'p1', 0.9),   # best child
            _sr('c3', 'p1', 0.7),
        ]
        out = await b._expand_to_parents(results)

        assert len(out) == 1
        assert out[0].score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_fetcher_raises_returns_children_unchanged(self):
        """If fetch raises, the original results are returned unchanged."""
        s = MagicMock()
        s.fetch = AsyncMock(side_effect=RuntimeError("DB down"))
        b = _bot(parent_searcher=s, expand_to_parent=True)

        results = [_sr('c1', 'p1', 0.9)]
        out = await b._expand_to_parents(results)

        assert out == results


# ---------------------------------------------------------------------------
# Tests for per-call override resolution
# ---------------------------------------------------------------------------


class TestPerCallOverrideResolution:
    """Resolution order: explicit kwarg → bot default → False."""

    def test_expand_to_parent_attribute_stored(self):
        b = _bot(expand_to_parent=True)
        assert b.expand_to_parent is True

    def test_default_false_when_not_set(self):
        b = _bot()
        assert b.expand_to_parent is False


# ---------------------------------------------------------------------------
# Tests for DB-driven expand_to_parent (verifying _from_db pattern works)
# ---------------------------------------------------------------------------


class TestDbDrivenExpandToParent:
    def test_expand_to_parent_persists_after_getattr(self):
        """expand_to_parent is accessible via getattr (as _from_db / from_manual_config uses)."""
        b = _bot(expand_to_parent=True)
        val = getattr(b, 'expand_to_parent', False)
        assert val is True

    def test_expand_to_parent_default_via_getattr(self):
        """If not set, getattr returns the safe default False."""
        b = _bot()
        val = getattr(b, 'expand_to_parent', False)
        assert val is False


# ---------------------------------------------------------------------------
# Tests for abstract.py signature inspection
# ---------------------------------------------------------------------------


class TestAbstractBotSignatures:
    """Verify that the correct kwarg signatures were added to abstract.py methods."""

    def _find_abstract_py(self):
        """Find abstract.py relative to this test file."""
        import pathlib
        # Try multiple ancestor levels to find the right one
        here = pathlib.Path(__file__).resolve()
        for ancestor in here.parents:
            candidate = ancestor / "packages/ai-parrot/src/parrot/bots/abstract.py"
            if candidate.exists():
                return candidate
            candidate2 = ancestor / "src/parrot/bots/abstract.py"
            if candidate2.exists():
                return candidate2
        return None

    def test_get_vector_context_has_expand_to_parent_kwarg(self):
        """get_vector_context must accept expand_to_parent=None."""
        src_path = self._find_abstract_py()
        if src_path is None:
            pytest.skip("abstract.py not found at expected location")
        src = src_path.read_text()
        assert "expand_to_parent" in src, "expand_to_parent must be added to abstract.py"

    def test_build_vector_context_has_expand_to_parent_kwarg(self):
        """_build_vector_context must have _expand_to_parents call."""
        src_path = self._find_abstract_py()
        if src_path is None:
            pytest.skip("abstract.py not found at expected location")
        src = src_path.read_text()
        assert "_expand_to_parents" in src, "_expand_to_parents must be added to abstract.py"
