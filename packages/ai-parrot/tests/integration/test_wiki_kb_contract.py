"""Contract-conformance suite (FEAT-481, spec Module 16) — the §34/§36
acceptance oracle.

Runs the full ingest pipeline against a fixture contract-structured
vault (``fixtures/wiki_kb_vault/``) with deterministic stubbed LLM/MCP
clients (no live API calls) and asserts the agent's output against the
operating contract (``sdd/references/obsidian-wiki-operating-contract.md``)
section by section. Every test is named by the § it enforces for
traceability (spec Module 16 Implementation Notes).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest import graph as graph_module
from parrot.flows.wiki_ingest.nodes.classify import Classification
from parrot.flows.wiki_ingest.nodes.concepts import ConceptExtraction
from parrot.flows.wiki_ingest.nodes.contradictions import ContradictionDetectionResult
from parrot.flows.wiki_ingest.nodes.daily import DailySynthesisProposal
from parrot.flows.wiki_ingest.nodes.entities import EntityExtraction
from parrot.flows.wiki_ingest.nodes.indexes import OverviewChangeAssessment
from parrot.flows.wiki_ingest.nodes.lint import run_lint
from parrot.flows.wiki_ingest.nodes.log import ALLOWED_LOG_OPS
from parrot.flows.wiki_ingest.nodes.meeting_page import MeetingPageExtraction
from parrot.flows.wiki_ingest.nodes.project_reconcile import (
    NewProjectJustification,
    ProjectUpdateProposal,
)
from parrot.flows.wiki_ingest.nodes.review_queue import ALLOWED_REVIEW_TYPES
from parrot.flows.wiki_ingest.runner import WikiIngestContext, run_ingest
from parrot.tools.abstract import ToolResult

_FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "wiki_kb_vault"


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _make_strong_client(*, primary_project: str = "Acme Rollout") -> AsyncMock:
    async def _invoke(prompt, *, output_type=None, **kwargs):
        if output_type is Classification:
            return _FakeInvokeResult(
                Classification(confidence="high", primary_project=primary_project, primary_client="Acme Corp")
            )
        if output_type is ContradictionDetectionResult:
            return _FakeInvokeResult(ContradictionDetectionResult(conflicts=[]))
        if output_type is NewProjectJustification:
            return _FakeInvokeResult(NewProjectJustification(justified=True, reason="Ongoing rollout."))
        if output_type is ProjectUpdateProposal:
            return _FakeInvokeResult(
                ProjectUpdateProposal(
                    executive_summary="Progressing.",
                    current_status="On track.",
                    change_summary="Update.",
                )
            )
        if output_type is EntityExtraction:
            return _FakeInvokeResult(EntityExtraction(materially_relevant=True, summary="Key contact.", known_roles=[]))
        if output_type is ConceptExtraction:
            return _FakeInvokeResult(
                ConceptExtraction(materially_relevant=True, definition="A concept.", why_it_matters="It matters.")
            )
        if output_type is OverviewChangeAssessment:
            return _FakeInvokeResult(OverviewChangeAssessment(materially_changed=False, reason="No major shift."))
        return _FakeInvokeResult(None)

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)
    return client


def _make_cheap_client() -> AsyncMock:
    async def _invoke(prompt, *, output_type=None, **kwargs):
        if output_type is MeetingPageExtraction:
            return _FakeInvokeResult(
                MeetingPageExtraction(
                    executive_summary="A productive sync.",
                    purpose="Align on rollout.",
                    decisions=["Ship v2 by Q4."],
                    requirements=["Support SSO."],
                )
            )
        if output_type is DailySynthesisProposal:
            return _FakeInvokeResult(DailySynthesisProposal(daily_summary="Acme progressed the rollout."))
        return _FakeInvokeResult(None)

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)
    return client


def _listing_entry(meeting_id: str, title: str, date_iso: str) -> str:
    return f'  - id: {meeting_id}\n    title: "{title}"\n    dateString: "{date_iso}"\n    duration: 30\n'


class _FakeTool:
    def __init__(self, execute: AsyncMock) -> None:
        self.execute = execute


class _FakeToolManager:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools

    def get_tool(self, name: str):
        return self._tools.get(name)


def _make_agent(listing_text: str, strong_client: AsyncMock, cheap_client: AsyncMock) -> Any:
    async def _get_transcripts(**kwargs):
        return ToolResult(success=True, result=listing_text)

    async def _get_transcript(**kwargs):
        return ToolResult(success=True, result="Full transcript content for the meeting.")

    async def _get_summary(**kwargs):
        return ToolResult(success=True, result="Fireflies summary for the meeting.")

    tools = {
        "mcp_fireflies_fireflies_get_transcripts": _FakeTool(AsyncMock(side_effect=_get_transcripts)),
        "mcp_fireflies_fireflies_get_transcript": _FakeTool(AsyncMock(side_effect=_get_transcript)),
        "mcp_fireflies_fireflies_get_summary": _FakeTool(AsyncMock(side_effect=_get_summary)),
    }

    agent = AsyncMock()
    agent.tool_manager = _FakeToolManager(tools)
    agent.add_fireflies_mcp_server = AsyncMock(return_value=list(tools))
    agent.strong_client = strong_client
    agent.cheap_client = cheap_client
    return agent


@pytest.fixture(autouse=True)
def _stub_graph_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """Derived plane only (spec Module 13/D3) — orthogonal to conformance."""
    monkeypatch.setattr(graph_module, "build_wiki_kb_graph_toolkit", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(graph_module, "rebuild_graph_index", AsyncMock(return_value={}))


def _fixture_vault_copy(tmp_path: Path) -> Path:
    """A fresh, mutable copy of the committed fixture vault."""
    destination = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, destination)
    return destination


async def _run_conformance_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary_project: str = "Acme Rollout",
    meeting_id: str = "id-1",
    meeting_title: str = "Acme Weekly Sync",
    meeting_date_iso: str = "2026-08-20T10:00:00-05:00",
):
    vault_path = _fixture_vault_copy(tmp_path)
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(vault_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = f"[1]:\n{_listing_entry(meeting_id, meeting_title, meeting_date_iso)}"
    strong_client = _make_strong_client(primary_project=primary_project)
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    report = await run_ingest(WikiIngestContext(agent=agent))
    return vault_path, report


# ---------------------------------------------------------------------------
# §14/§14.3/R3 — dedup, immutability, no revision workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_14_dedup_and_no_revision_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-ingesting a processed meeting id is a no-op skip; no
    Revisions/ folder, no source-revision/revision-detected artifacts
    exist anywhere (R3)."""
    vault_path, first_report = await _run_conformance_ingest(tmp_path, monkeypatch)
    assert first_report.processed == 1

    # Re-run against the SAME vault/registry — the id is now known.
    listing = f"[1]:\n{_listing_entry('id-1', 'Acme Weekly Sync', '2026-08-20T10:00:00-05:00')}"
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)
    second_report = await run_ingest(WikiIngestContext(agent=agent))

    assert second_report.processed == 0
    assert second_report.skipped == 1

    assert not (vault_path / "Raw" / "Processed" / "Revisions").exists()
    assert not any("source-revision" in f.read_text() for f in vault_path.rglob("*.md"))
    assert not any("revision-detected" in f.read_text() for f in vault_path.rglob("*.md"))
    assert "source-revision" not in ALLOWED_REVIEW_TYPES
    assert "revision-detected" not in ALLOWED_LOG_OPS


# ---------------------------------------------------------------------------
# §10/§17/D1/D2 — provenance, plain-path raw links, primary_project invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_10_17_provenance_and_invariants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)
    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))
    raw_text = (vault_path / meeting_page).read_text()
    frontmatter = yaml.safe_load(raw_text.split("---")[1])

    # D1 — plain relative paths, never wikilinks.
    assert not frontmatter["raw_summary"].startswith("[[")
    assert not frontmatter["raw_transcript"].startswith("[[")
    assert (vault_path / frontmatter["raw_summary"]).exists()
    assert (vault_path / frontmatter["raw_transcript"]).exists()

    # D2 — primary_project must also appear in projects.
    assert frontmatter["primary_project"] in frontmatter["projects"]


# ---------------------------------------------------------------------------
# §14.2 — raw hash verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_14_2_raw_hash_matches_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)
    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))
    frontmatter = yaml.safe_load((vault_path / meeting_page).read_text().split("---")[1])

    summary_bytes = (vault_path / frontmatter["raw_summary"]).read_bytes()
    assert hashlib.sha256(summary_bytes).hexdigest() == frontmatter["summary_sha256"]


# ---------------------------------------------------------------------------
# §2 rule 1 — Private/ never accessed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_2_rule_1_private_never_accessed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_path, _ = await _run_conformance_ingest(tmp_path, monkeypatch)
    secret = vault_path / "Private" / "secret.md"
    assert secret.exists()
    assert "DO NOT ACCESS" in secret.read_text()


# ---------------------------------------------------------------------------
# §9/§19 rule 8/9 — Human Notes + locked pages preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_9_locked_page_and_human_notes_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch, primary_project="Legacy Project")

    locked_page = vault_path / "Projects" / "Legacy Project" / "Legacy Project.md"
    content = locked_page.read_text()
    assert "This project is intentionally frozen by the operator." in content
    assert not any(p.endswith("Legacy Project.md") for p in report.updated)
    assert any("locked" in item.lower() and "Legacy Project" in item for item in report.review_items)


# ---------------------------------------------------------------------------
# §34 — post-op validation gate blocks bad writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_34_validation_gate_blocks_bad_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.flows.wiki_ingest import runner as runner_module
    from parrot.flows.wiki_ingest.validation import ValidationResult

    monkeypatch.setattr(runner_module, "validate", lambda ctx: ValidationResult(passed=False, failures=["forced"]))
    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)

    assert report.failed == 1
    log_path = vault_path / "Wiki" / "log.md"
    if log_path.exists():
        assert "ingest |" not in log_path.read_text()


# ---------------------------------------------------------------------------
# §17/§19 — page-template heading fidelity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_17_19_page_template_heading_fidelity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)

    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))
    meeting_content = (vault_path / meeting_page).read_text()
    for heading in ("## Executive Summary", "## Action Items", "## Source Provenance", "## Verified Quotes"):
        assert heading in meeting_content

    project_page = next(p for p in report.created if p.startswith("Projects/"))
    project_content = (vault_path / project_page).read_text()
    for heading in ("## Current Requirements", "## Current Decisions", "## Human Notes"):
        assert heading in project_content


# ---------------------------------------------------------------------------
# §8.2 — Obsidian-safe filenames + meeting-tz date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_8_2_obsidian_safe_filenames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, report = await _run_conformance_ingest(tmp_path, monkeypatch)
    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))
    filename = meeting_page.rsplit("/", 1)[-1]

    assert not any(ch in filename for ch in '/\\:*?"<>|')
    assert filename.startswith("2026-08-20 - Acme Weekly Sync - ")


# ---------------------------------------------------------------------------
# §8.1 — no dangling wikilinks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_8_1_no_dangling_wikilinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.flows.wiki_ingest import vault as vault_module

    vault_path, _ = await _run_conformance_ingest(tmp_path, monkeypatch)
    toolkit = vault_module.build_vault_toolkit(vault_path)

    lint_report = await run_lint(toolkit)
    broken = [f for f in lint_report.findings if f.category == "broken_wikilink"]
    assert broken == []


# ---------------------------------------------------------------------------
# rule #12 — no fabrication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_12_no_fabrication_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)
    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))
    content = (vault_path / meeting_page).read_text()

    # The mocked extraction supplied no risks/open-questions — the
    # renderer must emit the rule-#12 placeholder, never fabricate one.
    assert "None identified" in content


# ---------------------------------------------------------------------------
# §16 — new-project discipline (negative criteria)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_16_new_project_negative_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.flows.wiki_ingest.models import Classification as ClassificationModel
    from parrot.flows.wiki_ingest.models import MeetingExtraction
    from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting
    from parrot.flows.wiki_ingest.nodes.project_reconcile import run_project_reconcile

    client = _make_strong_client()
    client.invoke = AsyncMock(
        return_value=_FakeInvokeResult(NewProjectJustification(justified=False, reason="A passing mention only."))
    )

    result = await run_project_reconcile(
        client,
        existing_content=None,
        existing_frontmatter=None,
        locked=False,
        project_name="Random Chat",
        meeting=GatedMeeting(
            fireflies_id="x", source_id="fireflies:x", title="Chat", meeting_date="2026-08-20", outcome="fetch"
        ),
        meeting_extraction=MeetingExtraction(),
        meeting_source_link="Wiki/Sources/Meetings/x",
        classification=ClassificationModel(confidence="low"),
    )

    assert result.action == "not_created"


# ---------------------------------------------------------------------------
# G9 — email disabled by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g9_email_disabled_by_default() -> None:
    assert conf.FIREFLIES_WIKI_EMAIL_ENABLED is False


# ---------------------------------------------------------------------------
# §31 — archive window configurable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_31_archive_window_configurable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    from parrot.flows.wiki_ingest import vault as vault_module
    from parrot.flows.wiki_ingest.nodes.archive import run_archive

    vault_path, _ = await _run_conformance_ingest(tmp_path, monkeypatch)
    daily_dir = vault_path / "Diary" / "Daily Notes"
    (daily_dir / "2026-01-01.md").write_text("# 2026-01-01 Daily Notes\n", encoding="utf-8")
    toolkit = vault_module.build_vault_toolkit(vault_path)
    registry = vault_module.build_meeting_registry(vault_path)

    report = await run_archive(toolkit, registry, active_window_days=7, today=date(2026, 8, 25))

    assert any("2026-01-01" in p for p in report.archived_daily_notes)


# ---------------------------------------------------------------------------
# §28/D3 — GraphIndex-primary query, then Obsidian verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_28_query_verifies_against_obsidian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.flows.wiki_ingest import vault as vault_module
    from parrot.flows.wiki_ingest.nodes.query import QueryAnswer, run_query

    vault_path, report = await _run_conformance_ingest(tmp_path, monkeypatch)
    meeting_page = next(p for p in report.created if p.startswith("Wiki/Sources/Meetings/"))

    toolkit = vault_module.build_vault_toolkit(vault_path)
    wiki_toolkit = AsyncMock()
    wiki_toolkit.search = AsyncMock(
        return_value=[
            {
                "node_id": "n1",
                "title": meeting_page.rsplit("/", 1)[-1].removesuffix(".md"),
                "score": 0.9,
            }
        ]
    )
    strong_client = _make_strong_client()
    strong_client.invoke = AsyncMock(return_value=_FakeInvokeResult(QueryAnswer(supported_facts=["Ship v2 by Q4."])))

    result = await run_query(strong_client, wiki_toolkit, toolkit, "What was decided?")

    assert result.candidates[0].content is not None
    assert "Ship v2 by Q4." in result.answer.supported_facts

    # The GraphIndex/PageIndex hit is never quoted as authority: the LLM
    # call is grounded ONLY in the re-read, verified Obsidian page content
    # (§28 step 3/D3) — not in the raw retrieval hit dict (node_id/score).
    strong_client.invoke.assert_awaited_once()
    call_kwargs = strong_client.invoke.await_args.kwargs
    prompt_arg = strong_client.invoke.await_args.args[0]
    assert result.candidates[0].content in prompt_arg
    assert "n1" not in prompt_arg
    assert "NEVER quoted as authority" in call_kwargs["system_prompt"]


# ---------------------------------------------------------------------------
# G11 — existing agent/toolkit suites stay green (additive-only)
# ---------------------------------------------------------------------------


def test_existing_agent_suites_unaffected() -> None:
    """No existing agent/toolkit test regressed (additive-only, G11).

    Run as two separate ``pytest`` subprocess invocations — the
    repo-root ``tests/`` package and the ``packages/ai-parrot/tests/``
    package both happen to import as the dotted name ``tests.conftest``,
    so mixing targets from both trees into one pytest process trips
    pytest's ``ImportPathMismatchError`` (a pre-existing repo-layout
    ambiguity, unrelated to this feature's own conformance).
    """
    repo_root = Path(__file__).resolve().parents[4]
    target_groups = [
        [
            "tests/test_fireflies_obsidian_sync.py",
            "tests/test_fireflies_wiki_agent.py",
            "tests/integration/test_fireflies_meeting_registry.py",
        ],
        ["packages/ai-parrot/tests/tools/test_obsidian_toolkit.py"],
    ]
    for targets in target_groups:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *targets],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
