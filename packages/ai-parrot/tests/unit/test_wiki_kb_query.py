"""Unit tests for the §28 query workflow (FEAT-481, spec Module 13 /
TASK-2671): retrieval-then-verify, fact-type distinctions, synthesis
save gating.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.nodes.query import (
    QueryAnswer,
    QueryResult,
    build_synthesis_page,
    run_query,
)
from parrot.tools.obsidian import ObsidianToolkit


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(output: Any) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(output))
    return client


def _fake_wiki_toolkit(results: list[dict[str, Any]]) -> AsyncMock:
    toolkit = AsyncMock()
    toolkit.search = AsyncMock(return_value=results)
    return toolkit


def _vault_toolkit(tmp_path: Path) -> ObsidianToolkit:
    return ObsidianToolkit(
        vault_path=str(tmp_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )


@pytest.mark.asyncio
async def test_query_graphindex_then_verify_pages(tmp_path: Path) -> None:
    """Retrieval ranks candidates; the answer is built only from
    verified Obsidian page content, never the GraphIndex snippet."""
    meetings_dir = tmp_path / "Wiki" / "Sources" / "Meetings"
    meetings_dir.mkdir(parents=True)
    (meetings_dir / "Acme Sync.md").write_text(
        "# Acme Sync\n\n## Decisions\n- Ship v2 by Q4.\n", encoding="utf-8"
    )

    wiki_toolkit = _fake_wiki_toolkit(
        [{"node_id": "n1", "title": "Acme Sync", "score": 0.9, "source": "graphindex", "snippet": "STALE SNIPPET"}]
    )
    strong_client = _fake_client(QueryAnswer(supported_facts=["Ship v2 by Q4. — [[Wiki/Sources/Meetings/Acme Sync]]"]))
    vault_toolkit = _vault_toolkit(tmp_path)

    result = await run_query(strong_client, wiki_toolkit, vault_toolkit, "When does v2 ship?")

    assert result.candidates[0].vault_path is not None
    assert result.candidates[0].content is not None
    assert "STALE SNIPPET" not in strong_client.invoke.call_args.args[0]
    assert "Ship v2 by Q4." in strong_client.invoke.call_args.args[0]
    assert "Ship v2 by Q4." in result.answer.supported_facts[0]


@pytest.mark.asyncio
async def test_answer_distinguishes_fact_types(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "Wiki" / "Sources" / "Meetings"
    meetings_dir.mkdir(parents=True)
    (meetings_dir / "Acme Sync.md").write_text("# Acme Sync\n\nContent.\n", encoding="utf-8")

    wiki_toolkit = _fake_wiki_toolkit([{"node_id": "n1", "title": "Acme Sync", "score": 0.8}])
    answer = QueryAnswer(
        supported_facts=["Fact A."],
        inferences=["Likely B."],
        unknowns=["Unknown C."],
        unresolved_contradictions=["[[Wiki/Contradictions/Budget Conflict]]"],
    )
    strong_client = _fake_client(answer)
    vault_toolkit = _vault_toolkit(tmp_path)

    result = await run_query(strong_client, wiki_toolkit, vault_toolkit, "What is the status?")

    assert result.answer.supported_facts == ["Fact A."]
    assert result.answer.inferences == ["Likely B."]
    assert result.answer.unknowns == ["Unknown C."]
    assert result.answer.unresolved_contradictions == ["[[Wiki/Contradictions/Budget Conflict]]"]


@pytest.mark.asyncio
async def test_no_verified_candidates_produces_unknown_without_llm_call(tmp_path: Path) -> None:
    """When nothing in the vault matches, the answer is 'unknown' — the
    LLM is never asked to answer from unverified GraphIndex snippets."""
    wiki_toolkit = _fake_wiki_toolkit([{"node_id": "n1", "title": "Nonexistent Page", "score": 0.5}])
    strong_client = _fake_client(QueryAnswer())
    vault_toolkit = _vault_toolkit(tmp_path)

    result = await run_query(strong_client, wiki_toolkit, vault_toolkit, "Anything?")

    assert result.answer.unknowns
    strong_client.invoke.assert_not_called()


def test_build_synthesis_page_only_on_explicit_request() -> None:
    """build_synthesis_page is a separate, opt-in call — never invoked
    by run_query itself (§28 step 9: an ordinary query never writes)."""
    query_result = QueryResult(
        question="When does v2 ship?",
        answer=QueryAnswer(supported_facts=["Ship v2 by Q4. — [[Wiki/Sources/Meetings/Acme Sync]]"]),
    )

    frontmatter, content = build_synthesis_page(query_result, related_pages=["Projects/Acme Rollout/Acme Rollout"])

    assert frontmatter.question == "When does v2 ship?"
    assert "## Question\nWhen does v2 ship?" in content
    assert "Ship v2 by Q4." in content
    assert "[[Projects/Acme Rollout/Acme Rollout]]" in content
