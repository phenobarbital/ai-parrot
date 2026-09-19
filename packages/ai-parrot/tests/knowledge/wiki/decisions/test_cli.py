"""adr CLI surface, exit codes and JSON envelope (FEAT-578 M6)."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, adr_repo) -> None:
    """Run a quiet, graph-less `wikitoolkit build` against ``adr_repo``."""
    result = runner.invoke(wiki, ["build", "--path", str(adr_repo), "--no-graph", "--quiet"])
    assert result.exit_code == 0, result.output


class TestCommandSurface:
    def test_adr_group_is_registered(self, runner):
        result = runner.invoke(wiki, ["adr", "--help"])
        assert result.exit_code == 0
        for command in ("sync", "lookup", "why", "generate", "review", "export"):
            assert command in result.output

    def test_review_requires_attribution(self, runner):
        """Attribution is mandatory — no anonymous acceptance (spec §2)."""
        result = runner.invoke(
            wiki, ["adr", "review", "adr:candidate:a", "--action", "accept", "--expected-revision", "1"]
        )
        assert result.exit_code == 2  # click: missing --actor

    def test_revise_requires_an_edit_file(self, runner, adr_repo):
        result = runner.invoke(
            wiki,
            [
                "adr",
                "review",
                "adr:candidate:x",
                "--action",
                "revise",
                "--expected-revision",
                "1",
                "--actor",
                "human:m",
                "--path",
                str(adr_repo),
            ],
        )
        assert result.exit_code == 2, result.output

    def test_link_requires_documented_id(self, runner, adr_repo):
        result = runner.invoke(
            wiki,
            [
                "adr",
                "review",
                "adr:candidate:x",
                "--action",
                "link",
                "--expected-revision",
                "1",
                "--actor",
                "human:m",
                "--path",
                str(adr_repo),
            ],
        )
        assert result.exit_code == 2, result.output


class TestExitCodes:
    def test_empty_dossier_exits_zero(self, runner, adr_repo):
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "lookup", "sym:nope.py#gone", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "empty"

    def test_ambiguous_dossier_exits_zero(self, runner, adr_repo):
        """spec §2: an ambiguous dossier is a valid read result."""
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "lookup", "run", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ambiguous"
        assert payload["alternatives"]

    def test_invalid_argument_exits_two(self, runner, adr_repo):
        """--ns all is rejected in v1 (spec §2 Module 6)."""
        result = runner.invoke(wiki, ["adr", "why", "why", "--ns", "all", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 2

    def test_sync_with_error_diagnostics_exits_one(self, runner, adr_repo):
        """The fixture's malformed-frontmatter ADR always yields a diagnostic
        (non-fatal per parser.py), while the other ADRs still persist."""
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["diagnostics"]
        assert payload["created"] + payload["updated"] + payload["unchanged"] >= 1

    def test_generate_without_a_model_exits_one(self, runner, adr_repo, monkeypatch):
        """With generation disabled (the shipped default), generation refuses
        before ever resolving a model."""
        monkeypatch.delenv("WIKI_ADR_LLM", raising=False)
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "generate", "src/citing_module.py", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stderr or result.output)
        assert payload["error"]["code"] == "ADR_MODEL_UNCONFIGURED"


class TestJsonEnvelope:
    def test_error_envelope_shape(self, runner, adr_repo):
        result = runner.invoke(wiki, ["adr", "why", "q", "--ns", "all", "--json", "--path", str(adr_repo)])
        payload = json.loads(result.stderr or result.output)
        assert set(payload) == {"error"}
        assert payload["error"]["code"] == "ADR_INVALID_ARGUMENT"

    def test_stdout_stays_protocol_safe(self, runner, adr_repo):
        """Errors go to stderr so --json stdout is always parseable."""
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "lookup", "sym:nope.py#gone", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 0, result.output
        # The whole of stdout must decode as exactly one JSON document — a
        # stray log/warning line mixed into stdout would break this parse.
        payload = json.loads(result.output)
        assert payload["status"] == "empty"


class TestPostIngestRefresh:
    def test_build_refreshes_the_adr_plane(self, runner, adr_repo):
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["documented"]

    def test_build_makes_zero_llm_calls(self, runner, adr_repo, monkeypatch):
        """AC5: an ordinary build is fully offline."""
        from parrot.clients.factory import LLMFactory

        def _boom(*args, **kwargs):
            raise AssertionError("build must never construct an LLM client")

        monkeypatch.setattr(LLMFactory, "create", _boom)
        result = runner.invoke(wiki, ["build", "--path", str(adr_repo), "--no-graph", "--quiet"])
        assert result.exit_code == 0, result.output

    def test_a_broken_adr_never_fails_the_build(self, runner, adr_repo):
        """AC10: the ADR plane cannot break ordinary ingestion."""
        (adr_repo / "docs" / "adr" / "0098-no-decision-section.md").write_text(
            "# Broken\n\nThis ADR has no Decision section at all.\n", encoding="utf-8"
        )
        result = runner.invoke(wiki, ["build", "--path", str(adr_repo), "--no-graph", "--quiet"])
        assert result.exit_code == 0, result.output

    def test_upsert_refreshes_changed_paths(self, runner, adr_repo):
        _build(runner, adr_repo)
        adr_path = adr_repo / "docs" / "adr" / "0001-use-pgvector.md"
        adr_path.write_text(
            adr_path.read_text(encoding="utf-8").replace(
                "Use pgvector as the primary vector store.",
                "Use pgvector as the primary vector store, revised for the upsert test.",
            ),
            encoding="utf-8",
        )
        upsert_result = runner.invoke(
            wiki, ["upsert", "docs/adr/0001-use-pgvector.md", "--path", str(adr_repo), "--quiet"]
        )
        assert upsert_result.exit_code == 0, upsert_result.output
        lookup = runner.invoke(wiki, ["adr", "why", "revised upsert test", "--json", "--path", str(adr_repo)])
        assert lookup.exit_code == 0, lookup.output
        payload = json.loads(lookup.output)
        assert payload["documented"]
        assert "revised for the upsert test" in payload["documented"][0]["decision"]


class TestCliManagedPageGuard:
    def test_cli_note_refuses_an_adr_page(self, runner, adr_repo):
        _build(runner, adr_repo)
        lookup = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        assert lookup.exit_code == 0, lookup.output
        decision_id = json.loads(lookup.output)["documented"][0]["decision_id"]

        result = runner.invoke(wiki, ["note", decision_id, "extra text", "--path", str(adr_repo)])
        assert result.exit_code == 2, result.output

        # The record must still decode as a DecisionRecord (untouched).
        export = runner.invoke(wiki, ["adr", "export", decision_id, "--path", str(adr_repo)])
        assert export.exit_code == 0, export.output


class _FakeGenerationClient:
    """Fake AbstractClient producing one deterministic candidate."""

    model = "fake:test"

    async def invoke(self, prompt, **kwargs):
        from parrot.knowledge.wiki.decisions.models import CandidateBatch, CandidateDraft

        batch = CandidateBatch(
            candidates=[
                CandidateDraft(decision="Adopt a small in-process cache for repeated lookups.", evidence_indexes=[0])
            ]
        )
        return type("InvokeResult", (), {"output": batch, "model": "fake", "usage": {}})()


def _generate_one_candidate(adr_repo):
    """Directly drive DecisionService.generate() with a fake client.

    The CLI has no flag to inject a client (by design — `adr generate`
    always resolves via ``WIKI_ADR_LLM``), so this bypasses the CLI only
    for candidate creation; everything else in the test goes through
    `runner.invoke`.
    """
    from parrot.knowledge.wiki.cli import _open_store, _resolve_project
    from parrot.knowledge.wiki.decisions.service import DecisionService
    from parrot.knowledge.wiki.structural.service import StructuralService

    root, config = _resolve_project(str(adr_repo))
    config.decisions.generation_enabled = True
    store = _open_store(root, config)
    structural = StructuralService(store, root, config)
    service = DecisionService(store, root, config.decisions, structural=structural, client=_FakeGenerationClient())
    result = asyncio.run(service.generate("src/citing_module.py"))
    assert result.decision_ids, result.diagnostics
    return result.decision_ids[0]


class TestAcceptance:
    def test_maintainer_wiki_acceptance(self, runner, adr_repo):
        """AC11 through the operator surface — the Q3 acceptance path."""
        _build(runner, adr_repo)
        decision_id = _generate_one_candidate(adr_repo)

        files_before = sorted(p.relative_to(adr_repo).as_posix() for p in adr_repo.rglob("*") if p.is_file())

        review = runner.invoke(
            wiki,
            [
                "adr",
                "review",
                decision_id,
                "--action",
                "accept",
                "--expected-revision",
                "1",
                "--actor",
                "human:m",
                "--reason",
                "ok",
                "--path",
                str(adr_repo),
            ],
        )
        assert review.exit_code == 0, review.output
        assert "inferred" in review.output.lower()

        files_after = sorted(p.relative_to(adr_repo).as_posix() for p in adr_repo.rglob("*") if p.is_file())
        assert files_before == files_after  # no ADR file was written

        from parrot.knowledge.wiki.cli import _open_store, _resolve_project
        from parrot.knowledge.wiki.decisions.repository import DecisionRepository

        root, config = _resolve_project(str(adr_repo))
        store = _open_store(root, config)
        repo = DecisionRepository(store)
        loaded = asyncio.run(repo.get(decision_id))
        assert loaded is not None
        record, _hash = loaded
        assert record.origin == "inferred"
        assert record.source_status == "unknown"
        assert record.review_status == "accepted"

    def test_stale_revision_exits_one(self, runner, adr_repo):
        _build(runner, adr_repo)
        lookup = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        decision_id = json.loads(lookup.output)["documented"][0]["decision_id"]
        result = runner.invoke(
            wiki,
            [
                "adr",
                "review",
                decision_id,
                "--action",
                "accept",
                "--expected-revision",
                "999",
                "--actor",
                "human:m",
                "--path",
                str(adr_repo),
                "--json",
            ],
        )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stderr or result.output)
        assert payload["error"]["code"] == "ADR_REVISION_CONFLICT"

    def test_export_writes_nothing_to_disk(self, runner, adr_repo):
        """Q3: export prints; committing is the operator's choice."""
        _build(runner, adr_repo)
        lookup = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        decision_id = json.loads(lookup.output)["documented"][0]["decision_id"]
        files_before = sorted(p.relative_to(adr_repo).as_posix() for p in adr_repo.rglob("*") if p.is_file())
        result = runner.invoke(wiki, ["adr", "export", decision_id, "--path", str(adr_repo)])
        assert result.exit_code == 0, result.output
        assert "# " in result.output
        files_after = sorted(p.relative_to(adr_repo).as_posix() for p in adr_repo.rglob("*") if p.is_file())
        assert files_before == files_after
