"""Regression cases for FEAT-627 wiki_standup MCP tool."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import parrot.knowledge.wiki.standup.pipeline as pipeline
import parrot.knowledge.wiki.tools as subject
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


async def _offline_stub(cfg: object, *, explicit: str | None = None, root: Path) -> StandupIdentity:
    return StandupIdentity(wiki="human:tester")


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Relocate every home/state path and never probe a live Jira."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "xdg-cache"))
    monkeypatch.setenv("JIRA_WIKI_ISSUES_DIR", str(tmp_path / "no-issues"))
    monkeypatch.setattr(pipeline, "resolve_identity", _offline_stub)
    return home


def _hash_tree(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.name.endswith(("-wal", "-shm")):
            out[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return out


async def _seed(store: SQLiteWikiStore) -> None:
    """Materialise the plane file so later hashes only see real content changes."""
    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id="seed/page",
                title="Seed",
                category="document",
                summary="seed",
                body="# Seed",
                origin="authored",
                asserted_by="human:tester",
            )
        ]
    )


async def _brief_ids(store: SQLiteWikiStore) -> set[str]:
    """Concept ids of every persisted brief page."""
    return {str(row["concept_id"]) for row in await store.list_pages(category="brief", limit=100)}


def _project(tmp_path: Path) -> tuple[Path, WikiProjectConfig, SQLiteWikiStore]:
    root = tmp_path / "proj"
    root.mkdir()
    config = WikiProjectConfig(wiki_name="t", storage_dir=str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    local = SQLiteWikiStore(config.db_path(root), wiki_name="t")
    return root, config, local


def test_readonly_default_and_schema() -> None:
    """The input schema defaults to read-only, no model call, day period."""
    params = subject.WikiStandupInput()
    assert params.period == "day"
    assert params.store is False and params.write_file is False and params.use_llm is False
    assert params.team is False and params.date is None
    assert params.horizon_days is None and params.language is None
    assert subject.WikiStandupTool.name == "wiki_standup"


@pytest.mark.asyncio
async def test_default_call_writes_nothing(tmp_path: Path, _isolated: Path) -> None:
    """A default call touches neither the plane, the output dir nor the home."""
    root, config, local = _project(tmp_path)
    await _seed(local)
    tool = subject.WikiStandupTool(local, root, config)
    before = (_hash_tree(tmp_path / "store"), _hash_tree(_isolated))
    result = await tool._execute(date="2026-10-06")
    assert result.success, result.error
    payload = result.result
    assert payload["written_page"] is False and payload["written_file"] is None
    assert payload["brief_id"] and isinstance(payload["markdown"], str) and payload["markdown"]
    assert isinstance(payload["diagnostics"], list)
    assert (_hash_tree(tmp_path / "store"), _hash_tree(_isolated)) == before
    assert payload["brief_id"] not in await _brief_ids(local)


@pytest.mark.asyncio
async def test_local_only_optin_writes(tmp_path: Path, _isolated: Path) -> None:
    """store=true writes the real local plane, never the injected foreign facade; write_file is independent."""
    root, config, local = _project(tmp_path)
    foreign = SQLiteWikiStore(tmp_path / "foreign.db", wiki_name="other")
    await _seed(local)
    await _seed(foreign)
    foreign_bytes = (tmp_path / "foreign.db").read_bytes()
    tool = subject.WikiStandupTool(foreign, root, config)

    page_only = await tool._execute(date="2026-10-06", store=True)
    assert page_only.success, page_only.error
    assert page_only.result["written_page"] is True
    assert page_only.result["written_file"] is None
    brief_id = page_only.result["brief_id"]
    assert brief_id in await _brief_ids(local)
    assert brief_id not in await _brief_ids(foreign)
    assert (tmp_path / "foreign.db").read_bytes() == foreign_bytes
    assert not list(_isolated.rglob("*.md"))

    file_only = await tool._execute(date="2026-10-07", write_file=True)
    assert file_only.success, file_only.error
    assert file_only.result["written_page"] is False
    written = file_only.result["written_file"]
    assert written and Path(written).is_file()
    assert file_only.result["brief_id"] not in await _brief_ids(local)
    assert file_only.result["brief_id"] not in await _brief_ids(foreign)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [{"date": "not-a-date"}, {"horizon_days": 0}, {"horizon_days": 91}, {"period": "year"}, {"language": "fr"}],
)
async def test_invalid_input_rejected_before_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: dict[str, object]
) -> None:
    """Bad date/horizon/enum values return a structured error and never reach the pipeline."""
    root, config, local = _project(tmp_path)
    runner = AsyncMock()
    monkeypatch.setattr(pipeline, "run", runner)
    result = await subject.WikiStandupTool(local, root, config)._execute(**bad)
    assert result.success is False and "Invalid wiki_standup input" in str(result.error)
    runner.assert_not_called()


def test_factory_context_guard(tmp_path: Path) -> None:
    """wiki_standup is registered only when root and config are both supplied."""
    root, config, local = _project(tmp_path)
    assert "wiki_standup" not in {t.name for t in subject.create_wiki_tools(local)}
    assert "wiki_standup" not in {t.name for t in subject.create_wiki_tools(local, root=root)}
    with_ctx = subject.create_wiki_tools(local, root=root, config=config)
    names = [t.name for t in with_ctx]
    assert names.count("wiki_standup") == 1
    assert len(subject.create_wiki_tools(local)) == 6
    assert len(with_ctx) == 7
