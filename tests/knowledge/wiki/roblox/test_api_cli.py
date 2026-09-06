"""Click compatibility and zero-network defaults (FEAT-532 TASK-2908).

Drives ``wikitoolkit ingest roblox-api`` / ``wikitoolkit status`` with
``CliRunner`` — no real network, no LLM: ``ingest_roblox_api`` and
``get_roblox_status`` are monkeypatched at their point of use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# See test_cli.py's note: patch through the imported module object, not a
# dotted string, so PEP 420 namespace attribute resolution is reliable on CI.
import parrot.knowledge.pageindex.toolkit as _pageindex_toolkit  # noqa: F401
import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.roblox import ingest as roblox_ingest
from parrot.knowledge.wiki.roblox.models import RobloxApiIngestResult, RobloxApiManifest


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    return tmp_path


def _build(runner: CliRunner, repo: Path):
    return runner.invoke(wiki, ["build", "--path", str(repo), "--no-git"])


def _fake_result(*, reused: bool = True, published: bool = False, diagnostics=None) -> RobloxApiIngestResult:
    manifest = RobloxApiManifest(
        studio_version="0.123.0.456789",
        creator_docs_commit="a" * 40,
        renderer_schema_version=1,
        downloaded_at="2026-09-06T00:00:00+00:00",
        class_count=625,
        enum_count=120,
        structural_only_count=3,
    )
    return RobloxApiIngestResult(
        generation_dir="/home/user/.parrot/roblox/generations/gen-abc",
        manifest=manifest,
        reused=reused,
        published=published,
        diagnostics=diagnostics or [],
    )


# ---------------------------------------------------------------------------
# test_api_dispatch_has_no_llm_import
# ---------------------------------------------------------------------------


async def _fake_ingest_success(*, refresh: bool = False, **_kwargs):
    return _fake_result(reused=not refresh, published=refresh)


def test_api_dispatch_has_no_llm_import(runner: CliRunner, monkeypatch):
    """API path reaches generation orchestration before document/LLM setup."""
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_success)
    # Poison the document-pipeline's LLM import: if dispatch ever fell
    # through to the document path, this import would raise and the CLI
    # invocation would report a non-zero exit code / exception.
    monkeypatch.setitem(sys.modules, "parrot.knowledge.pageindex.toolkit", None)

    result = runner.invoke(wiki, ["ingest", "roblox-api"])

    assert result.exit_code == 0, result.output
    assert "Roblox API plane" in result.output


# ---------------------------------------------------------------------------
# test_default_first_use_offline
# ---------------------------------------------------------------------------


async def _fake_ingest_not_ingested(*, refresh: bool = False, **_kwargs):
    if refresh:
        return _fake_result(reused=False, published=True)
    raise roblox_ingest.RobloxApiNotIngestedError(
        "No Roblox API plane has been ingested yet. Run "
        "`wikitoolkit ingest roblox-api --refresh` to fetch and publish it."
    )


def test_default_first_use_offline(runner: CliRunner, monkeypatch):
    """Missing plane without --refresh makes no HTTP calls and provides explicit next command."""
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_not_ingested)

    result = runner.invoke(wiki, ["ingest", "roblox-api"])

    assert result.exit_code != 0
    assert "--refresh" in result.output


# ---------------------------------------------------------------------------
# test_refresh_and_document_flag_validation
# ---------------------------------------------------------------------------


def test_refresh_works(runner: CliRunner, monkeypatch):
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_not_ingested)

    result = runner.invoke(wiki, ["ingest", "roblox-api", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "Roblox API plane" in result.output


def test_explicit_document_flag_is_rejected(runner: CliRunner, monkeypatch):
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_success)

    result = runner.invoke(wiki, ["ingest", "roblox-api", "--dry-run"])

    assert result.exit_code != 0
    assert "--dry-run" in result.output


def test_default_flag_values_are_not_rejected(runner: CliRunner, monkeypatch):
    """Only EXPLICIT flags are rejected — Click defaults never trip the check."""
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_success)

    # --recursive is the (non-conflicting) default spelling of a True-default
    # flag — passing it explicitly at its own default value must not error.
    result = runner.invoke(wiki, ["ingest", "roblox-api", "--recursive"])

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# test_literal_document_source_compatibility
# ---------------------------------------------------------------------------


def test_literal_document_source_compatibility(runner: CliRunner, repo: Path, monkeypatch):
    """Existing ingest SOURCE and ./roblox-api keep their behavior.

    The dispatch is an exact string match on the bare reserved name —
    './roblox-api' (a literal relative path, per spec: "./roblox-api
    remains a literal local source") is a different string entirely and
    must fall through to ordinary document ingestion instead.
    """

    async def _boom(**_kwargs):
        raise AssertionError("ingest_roblox_api must not be called for a literal path source")

    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _boom)

    (repo / "roblox-api").mkdir()
    (repo / "roblox-api" / "note.md").write_text("just a doc", encoding="utf-8")

    result = runner.invoke(wiki, ["ingest", "./roblox-api", "--dry-run", "--path", str(repo)])

    # Never dispatched to the Roblox path — no "Roblox API plane" header,
    # and _boom (which would raise AssertionError, surfacing as a non-clean
    # result) was never invoked.
    assert "Roblox API plane" not in result.output
    assert not isinstance(result.exception, AssertionError)


def test_bare_roblox_api_dispatches_not_literal_path(runner: CliRunner, repo: Path, monkeypatch):
    """Bare 'roblox-api' (no path separator) claims the dispatch even when
    a same-named directory exists on disk — only an explicit './roblox-api'
    spelling addresses the literal path."""
    (repo / "roblox-api").mkdir()
    monkeypatch.setattr(roblox_ingest, "ingest_roblox_api", _fake_ingest_success)

    result = runner.invoke(wiki, ["ingest", "roblox-api", "--path", str(repo)])

    assert result.exit_code == 0, result.output
    assert "Roblox API plane" in result.output


# ---------------------------------------------------------------------------
# test_status_text_json_are_offline
# ---------------------------------------------------------------------------


def test_status_text_json_are_offline(runner: CliRunner, repo: Path, monkeypatch):
    """Stored timestamp/versions render without API acquisition or freshness probes."""
    import aiohttp

    def _boom_session(*_args, **_kwargs):
        raise AssertionError("status must never open an aiohttp session")

    monkeypatch.setattr(aiohttp, "ClientSession", _boom_session)

    fake_status = {
        "generation_id": "gen-abc",
        "studio_version": "0.123.0.456789",
        "creator_docs_commit": "a" * 40,
        "downloaded_at": "2026-09-06T00:00:00+00:00",
        "class_count": 625,
        "enum_count": 120,
    }
    monkeypatch.setattr(roblox_ingest, "get_roblox_status", lambda: fake_status)

    assert _build(runner, repo).exit_code == 0

    json_result = runner.invoke(wiki, ["status", "--path", str(repo), "--json"])
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["roblox_api"] == fake_status

    text_result = runner.invoke(wiki, ["status", "--path", str(repo)])
    assert text_result.exit_code == 0, text_result.output
    assert "Roblox API" in text_result.output
    assert "0.123.0.456789" in text_result.output


def test_status_shows_not_downloaded_when_absent(runner: CliRunner, repo: Path, monkeypatch):
    monkeypatch.setattr(roblox_ingest, "get_roblox_status", lambda: None)
    assert _build(runner, repo).exit_code == 0

    result = runner.invoke(wiki, ["status", "--path", str(repo)])
    assert result.exit_code == 0, result.output
    assert "not downloaded" in result.output
    assert "--refresh" in result.output
