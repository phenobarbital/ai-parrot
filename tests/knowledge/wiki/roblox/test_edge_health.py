"""Resolved/missing/unavailable/malformed cross-namespace edge health
matrix (FEAT-532 TASK-2905).

Exercises ``FederatedWikiStore.broken_edges()``'s new federated-boundary
classification directly, plus ``LLMWikiToolkit.lint()``'s use of a
federation-aware read context for cross-reference checks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, NamespaceSkip
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit


async def _build_plane(
    storage_dir: Path,
    pages: list[tuple[str, str, str]],
    edges: list[tuple[str, str, str]] | None = None,
) -> SQLiteWikiStore:
    store = SQLiteWikiStore(storage_dir / "wiki.db")
    await store.upsert_pages(
        [WikiPageRecord(concept_id=cid, title=title, summary=body, body=body) for cid, title, body in pages]
    )
    if edges:
        await store.add_edges(list(edges))
    return store


def _handle(name: str, store: SQLiteWikiStore, storage_dir: Path) -> NamespaceHandle:
    return NamespaceHandle(
        name=name,
        store=store,
        config=WikiNamespaceConfig(store=str(storage_dir), weight=1.0),
        origin="repo",
        storage_dir=storage_dir,
        read_only=True,
    )


@pytest.fixture
async def fed(tmp_path: Path) -> FederatedWikiStore:
    """local: Main.luau references class/Players (resolved) and
    class/Typo (missing-in-available-namespace), plus a genuinely local
    dangling edge and an unavailable-namespace reference."""
    local = await _build_plane(
        tmp_path / "local",
        [("file:Main.luau", "Main", "x")],
        edges=[
            ("file:Main.luau", "roblox::class/Players", "references"),
            ("file:Main.luau", "roblox::class/Typo", "references"),
            ("file:Main.luau", "file:DoesNotExist.luau", "references"),  # local broken
            ("file:Main.luau", "unbuilt::class/Whatever", "references"),  # unavailable ns
        ],
    )
    await _build_plane(tmp_path / "roblox", [("class/Players", "Players", "the Players service")])
    roblox_store = SQLiteWikiStore(tmp_path / "roblox" / "wiki.db", read_only=True)
    return FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[_handle("roblox", roblox_store, tmp_path / "roblox")],
        skipped=[],
    )


# ---------------------------------------------------------------------------
# test_resolved_external_edge_is_healthy
# ---------------------------------------------------------------------------


async def test_resolved_external_edge_is_healthy(fed: FederatedWikiStore):
    """Available API page clears the candidate while ordinary local
    missing targets remain broken."""
    report = await fed.broken_edges()
    dsts = {e["dst"] for e in report}

    assert "roblox::class/Players" not in dsts  # resolved -> excluded entirely
    assert "file:DoesNotExist.luau" in dsts  # ordinary local broken edge remains
    local_entry = next(e for e in report if e["dst"] == "file:DoesNotExist.luau")
    assert local_entry["status"] == "broken"


# ---------------------------------------------------------------------------
# test_missing_page_is_broken
# ---------------------------------------------------------------------------


async def test_missing_page_is_broken(fed: FederatedWikiStore):
    """Typo in an available declared namespace is still reported."""
    report = await fed.broken_edges()
    typo_entry = next(e for e in report if e["dst"] == "roblox::class/Typo")
    assert typo_entry["status"] == "broken"
    assert "roblox" in typo_entry["reason"]


# ---------------------------------------------------------------------------
# test_unbuilt_namespace_is_unverifiable
# ---------------------------------------------------------------------------


async def test_unbuilt_namespace_is_unverifiable(fed: FederatedWikiStore):
    """Unavailable plane is diagnosed separately and local results survive."""
    report = await fed.broken_edges()
    unbuilt_entry = next(e for e in report if e["dst"] == "unbuilt::class/Whatever")
    assert unbuilt_entry["status"] == "unverifiable"
    assert "unbuilt" in unbuilt_entry["reason"]

    # Local results are unaffected by the unresolved namespace.
    assert any(e["dst"] == "file:DoesNotExist.luau" and e["status"] == "broken" for e in report)


async def test_unreachable_namespace_store_is_unverifiable_not_fatal(tmp_path: Path):
    """A namespace whose store raises on get_page degrades to
    unverifiable rather than crashing the whole lint."""
    local = await _build_plane(
        tmp_path / "local",
        [("file:Main.luau", "Main", "x")],
        edges=[("file:Main.luau", "roblox::class/Players", "references")],
    )
    broken_store = AsyncMock()
    broken_store.get_page.side_effect = RuntimeError("plane corrupted")
    fed = FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[
            NamespaceHandle(
                name="roblox",
                store=broken_store,
                config=WikiNamespaceConfig(store=str(tmp_path / "roblox"), weight=1.0),
                origin="repo",
                storage_dir=tmp_path / "roblox",
            )
        ],
        skipped=[],
    )
    report = await fed.broken_edges()
    entry = next(e for e in report if e["dst"] == "roblox::class/Players")
    assert entry["status"] == "unverifiable"


# ---------------------------------------------------------------------------
# test_malformed_namespace_and_concurrent_reads
# ---------------------------------------------------------------------------


async def test_malformed_namespace_and_concurrent_reads(fed: FederatedWikiStore):
    """Malformed ids are not suppressed and per-call skip notes do not leak."""
    # "not" parses as a *syntactically* valid but never-declared namespace
    # prefix (per split_namespaced_id) — it must still show up in the
    # report (classified "unverifiable", since "not" names no known
    # namespace) rather than being silently swallowed just because the
    # string contains "::".
    malformed_dst = "not::a:real:namespace:shape::??"
    await fed._local.add_edges([("file:Main.luau", malformed_dst, "references")])

    reports = await asyncio.gather(fed.broken_edges(), fed.broken_edges())
    for report in reports:
        dsts = {e["dst"] for e in report}
        assert "file:DoesNotExist.luau" in dsts  # concurrent calls agree, nothing leaked
        assert malformed_dst in dsts  # never silently dropped
        entry = next(e for e in report if e["dst"] == malformed_dst)
        assert entry["status"] in ("broken", "unverifiable")


# ---------------------------------------------------------------------------
# test_toolkit_lint_uses_read_context
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pi():
    pi = MagicMock()
    return pi


@pytest.fixture
def mock_gi():
    gi = MagicMock()
    return gi


@pytest.fixture
def mock_okf():
    okf = MagicMock()
    okf.lint_knowledge_base = AsyncMock(return_value={"orphan_nodes": 0})
    return okf


async def test_toolkit_lint_uses_read_context(fed: FederatedWikiStore, tmp_path: Path, mock_pi, mock_gi, mock_okf):
    """Configured federated lint classifies edges while checking local source staleness."""
    # NOTE: `wiki_name="local"` is a reserved routing selector
    # (`_is_namespace`/`_store_for` treat it as SELECTOR_LOCAL, which
    # `scoped()` resolves to the RAW unfederated local store — bypassing
    # classification entirely). The toolkit's own distinct wiki name
    # falls through to `self._store` (the full FederatedWikiStore), which
    # is the case this test means to exercise.
    config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "local")
    toolkit = LLMWikiToolkit(mock_pi, mock_gi, mock_okf, config, store=fed)

    report = await toolkit.lint("test-wiki")

    broken = [i for i in report["cross_ref_issues"] if i["kind"] == "broken_edge"]
    dsts = {i["dst"] for i in broken}
    assert "roblox::class/Players" not in dsts  # resolved, excluded
    assert "file:DoesNotExist.luau" in dsts  # local broken, still reported
    assert any(i["dst"] == "roblox::class/Typo" and i["status"] == "broken" for i in broken)
    assert any(i["dst"] == "unbuilt::class/Whatever" and i["status"] == "unverifiable" for i in broken)

    # Source staleness/orphan checks still ran against the LOCAL plane's
    # own bookkeeping (never delegated to a foreign namespace) — the OKF
    # mock was still invoked, and the report carries the local fields.
    mock_okf.lint_knowledge_base.assert_awaited_once()
    assert "orphan_sources" in report
    assert "stale_sources" in report


async def test_toolkit_lint_scopes_to_named_namespace(
    fed: FederatedWikiStore, tmp_path: Path, mock_pi, mock_gi, mock_okf
):
    """Naming a specific namespace routes cross-ref checks to JUST that
    namespace's own store (the new `_store_for` routing this task adds),
    while staleness/orphan checks remain tied to the toolkit's local
    plane regardless of which namespace's edges were linted."""
    config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "local")
    toolkit = LLMWikiToolkit(mock_pi, mock_gi, mock_okf, config, store=fed)

    report = await toolkit.lint("roblox")

    broken = [i for i in report["cross_ref_issues"] if i["kind"] == "broken_edge"]
    # The roblox plane's own store has no broken edges of its own (its
    # one page, class/Players, has no outgoing edges) — none of the
    # LOCAL plane's broken/unverifiable candidates leak into this scoped view.
    assert broken == []
    # Local source bookkeeping still ran (never skipped just because the
    # cross-ref check was scoped elsewhere).
    mock_okf.lint_knowledge_base.assert_awaited_once()
