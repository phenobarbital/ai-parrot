"""Regression cases for FEAT-627 brief pipeline."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.pipeline as subject
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiEffectiveConfig, WikiNamespaceConfig, WikiProjectConfig
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import BriefItem
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


class _CountingStore(SQLiteWikiStore):
    """Real SQLite plane that records close calls."""

    closed = 0

    async def close(self) -> None:
        type(self).closed += 1


async def _offline_stub(cfg: object, *, explicit: str | None = None, root: Path) -> StandupIdentity:
    return StandupIdentity(wiki="human:tester")


@pytest.fixture(autouse=True)
def _offline_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let the writing identity resolver probe a live Jira."""
    monkeypatch.setattr(subject, "resolve_identity", _offline_stub)


def _effective(tmp_path: Path) -> WikiEffectiveConfig:
    config = WikiProjectConfig(wiki_name="t", storage_dir=str(tmp_path / "store"))
    return WikiEffectiveConfig(config=config, env="local")


def _page(concept_id: str, title: str, attrs: dict[str, str], category: str = "document") -> WikiPageRecord:
    return WikiPageRecord(
        concept_id=concept_id,
        title=title,
        category=category,
        summary=title,
        body=f"# {title}",
        origin="authored",
        asserted_by="human:tester",
        attrs=attrs,
    )


def _local_store(tmp_path: Path, name: str = "wiki.db") -> SQLiteWikiStore:
    (tmp_path / "store").mkdir(parents=True, exist_ok=True)
    return SQLiteWikiStore(tmp_path / "store" / name, wiki_name="t")


def _opts(**kw: object) -> subject.StandupOptions:
    base: dict[str, object] = {"anchor": date(2026, 10, 6), "team": True, "use_llm": False}
    base.update(kw)
    return subject.StandupOptions(**base)  # type: ignore[arg-type]


def _hash_tree(path: Path) -> dict[str, str]:
    """Hash every file under a directory except SQLite sidecars."""
    out: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.name.endswith(("-wal", "-shm")):
            out[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return out


@pytest.mark.asyncio
async def test_all_sources_and_hygiene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All sources feed the brief and every Hygiene counter is computed."""
    monkeypatch.delenv("JIRA_WIKI_ISSUES_DIR", raising=False)
    store = _local_store(tmp_path)
    await store.upsert_pages(
        [
            _page("doc/draft", "Draft spec", {"type": "deliverable", "status": "draft", "source": "markdown"}),
            _page(
                "issues/ONE",
                "Ticket one",
                {"type": "ticket", "source": "jira", "status_raw": "Weird", "x_assignee": "someone"},
            ),
        ]
    )
    index = tmp_path / "sdd" / "tasks" / "index"
    index.mkdir(parents=True)
    (index / "f.json").write_text(
        json.dumps(
            {
                "feature_id": "FEAT-1",
                "tasks": [{"id": "TASK-1", "title": "Do it", "status": "in-progress", "feature": "f"}],
            }
        ),
        encoding="utf-8",
    )
    lint = tmp_path / "store" / "lint"
    lint.mkdir(parents=True)
    (lint / "report.json").write_text(json.dumps({"generated_at": "2026-10-01T00:00:00+00:00"}), encoding="utf-8")
    sync = subject.resolve_issues_dir() / ".parrot"
    sync.mkdir(parents=True)
    (sync / "jira_sync.json").write_text(
        json.dumps(
            {
                "scopes": {
                    "a": {
                        "jql": "x",
                        "jql_fingerprint": "f",
                        "last_watermark": "2026-10-02T10:00:00+0000",
                        "extractor_version": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    import parrot.knowledge.wiki.standup.collectors.decisions as decisions
    import parrot.knowledge.wiki.standup.collectors.ledger as ledger

    async def _ledger(ctx: object) -> list[BriefItem]:
        return [BriefItem(id="issue:1", kind="ticket", title="Blocked thing", status="blocked", source="ledger")]

    async def _decisions(ctx: object) -> list[BriefItem]:
        return [
            BriefItem(id="adr/1", kind="decision", title="Old", status="proposed", source="decision", age_days=30),
            BriefItem(id="adr/2", kind="decision", title="New", status="proposed", source="decision", age_days=1),
        ]

    monkeypatch.setattr(ledger, "collect", _ledger)
    monkeypatch.setattr(decisions, "collect", _decisions)

    # anchor far after the real clock so the jira ticket (updated now) is not stale; use a later anchor to make it stale
    anchor = date.today() + timedelta(days=60)
    doc = await subject.run(
        tmp_path, _opts(anchor=anchor, write_file=False), store=store, effective=_effective(tmp_path)
    )

    ids = set(doc.item_ids)
    assert {"doc/draft", "issues::issues/ONE", "TASK-1", "issue:1", "adr/1"} <= ids
    assert doc.hygiene.ledger_blockers == 1
    assert doc.hygiene.proposed_decisions_older_than == 1
    assert doc.hygiene.stale_tickets == 1
    assert doc.hygiene.unmapped_statuses == {"Weird": 1}
    assert doc.hygiene.jira_watermark == "2026-10-02T10:00:00+0000"
    assert doc.hygiene.attrs_indexed is not None and doc.hygiene.attrs_indexed >= 2
    assert doc.hygiene.last_lint == "2026-10-01T00:00:00+00:00"
    assert doc.hygiene.llm == "skipped: disabled"
    assert doc.written_page is True and doc.written_file is None
    assert "@" not in doc.model_dump_json()


@pytest.mark.asyncio
async def test_delta_and_period_sources(tmp_path: Path) -> None:
    """Delta is computed against the prior same-period brief; roll-ups list daily briefs."""
    store = _local_store(tmp_path)
    eff = _effective(tmp_path)
    pages = [
        _page("doc/a", "A", {"type": "deliverable", "status": "draft"}),
        _page("doc/b", "B", {"type": "deliverable", "status": "draft"}),
    ]
    await store.upsert_pages(pages)
    first = await subject.run(tmp_path, _opts(anchor=date(2026, 10, 6), write_file=False), store=store, effective=eff)
    assert first.previous_brief_id is None and first.delta_new == [] and first.delta_closed == []

    await store.delete_page("doc/b")
    await store.upsert_pages([_page("doc/c", "C", {"type": "deliverable", "status": "draft"})])
    second = await subject.run(tmp_path, _opts(anchor=date(2026, 10, 7), write_file=False), store=store, effective=eff)
    assert second.previous_brief_id == "brief:daily:2026-10-06"
    assert [i.id for i in second.delta_new] == ["doc/c"]
    assert [i.id for i in second.delta_closed] == ["doc/b"]
    from parrot.knowledge.wiki.standup.render import render_markdown

    assert "Since last brief" in render_markdown(second, "en")

    week = await subject.run(
        tmp_path,
        _opts(period="week", anchor=date(2026, 10, 8), write_page=False, write_file=False),
        store=store,
        effective=eff,
    )
    assert week.window.brief_id.startswith("brief:weekly:")
    assert week.sources == ["brief:daily:2026-10-06", "brief:daily:2026-10-07"]
    assert week.written_page is False


@pytest.mark.asyncio
async def test_offline_model_failure_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing model degrades to fallback bullets while page and file are still written."""
    store = _local_store(tmp_path)
    await store.upsert_pages([_page("doc/a", "Alpha", {"type": "deliverable", "status": "draft"})])

    class _Boom:
        async def ask(self, prompt: str, **_: object) -> str:
            raise ConnectionError("offline secret-token")

    import parrot.knowledge.wiki.llm_resolve as resolve

    monkeypatch.setattr(resolve, "resolve_optional_llm", lambda *a, **k: _Boom())
    out = tmp_path / "out"
    doc = await subject.run(tmp_path, _opts(use_llm=True, out_dir=out), store=store, effective=_effective(tmp_path))
    assert doc.hygiene.llm.startswith("failed")
    assert "secret-token" not in doc.hygiene.llm
    assert doc.on_your_plate and "Alpha" in doc.on_your_plate[0]
    assert doc.written_page is True
    assert doc.written_file is not None and Path(doc.written_file).read_text(encoding="utf-8").startswith("# ")

    monkeypatch.setattr(resolve, "resolve_optional_llm", lambda *a, **k: None)
    skipped = await subject.run(
        tmp_path, _opts(use_llm=True, write_page=False, write_file=False), store=store, effective=_effective(tmp_path)
    )
    assert skipped.hygiene.llm == "skipped: no model"


@pytest.mark.asyncio
async def test_readonly_and_resource_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Read-only runs mutate nothing; injected stores stay open; owned stores close."""
    eff = _effective(tmp_path)
    store = _local_store(tmp_path)
    await store.upsert_pages([_page("doc/a", "Alpha", {"type": "deliverable", "status": "draft"})])

    async def _no_identity(*a: object, **k: object) -> None:
        raise AssertionError("read-only mode must not use the writing identity resolver")

    monkeypatch.setattr(subject, "resolve_identity", _no_identity)
    home = Path(subject.parrot_home())
    before_store = _hash_tree(tmp_path / "store")
    before_home = _hash_tree(home)
    doc = await subject.run(
        tmp_path, _opts(write_page=False, write_file=False, out_dir=tmp_path / "never"), effective=eff
    )
    assert "doc/a" in doc.item_ids
    assert doc.written_page is False and doc.written_file is None
    assert _hash_tree(tmp_path / "store") == before_store
    assert _hash_tree(home) == before_home
    assert not (home / "jira_identity.json").exists()
    assert not (tmp_path / "never").exists()
    assert not (tmp_path / "store" / "lint").exists()

    # unbuilt plane in read-only mode is an actionable error, not a created plane
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(subject.StandupStoreError, match="wikitoolkit build"):
        await subject.run(empty, _opts(write_page=False, write_file=False), effective=_effective(empty))
    assert not (empty / "store").exists()

    # options override a copy of the config, never the shared one
    cfg_before = eff.config.standup.model_dump()
    es = await subject.run(
        tmp_path, _opts(language="es", horizon_days=3, write_page=False, write_file=False), effective=eff
    )
    assert es.language == "es" and es.window.start == date(2026, 10, 3)
    assert eff.config.standup.model_dump() == cfg_before

    monkeypatch.undo()
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setattr(subject, "resolve_identity", _offline_stub)

    # injected store: stays open and is the write target
    counting = _CountingStore(tmp_path / "store" / "wiki.db", wiki_name="t")
    _CountingStore.closed = 0
    await subject.run(tmp_path, _opts(write_file=False), store=counting, effective=eff)
    assert _CountingStore.closed == 0
    assert any(p["concept_id"] == "brief:daily:2026-10-06" for p in await counting.list_pages(category="brief"))

    # owned store: closed exactly once
    async def _open(*a: object, **k: object) -> _CountingStore:
        return counting

    monkeypatch.setattr(subject, "_open_local", _open)
    await subject.run(tmp_path, _opts(write_page=False, write_file=False), effective=eff)
    assert _CountingStore.closed == 1


@pytest.mark.asyncio
async def test_writes_never_target_scoped_foreign_namespace(tmp_path: Path) -> None:
    """A store scoped to a foreign namespace still writes the brief to the true local plane."""
    local = _local_store(tmp_path)
    foreign = _local_store(tmp_path, "foreign.db")
    handle = NamespaceHandle(name="issues", store=foreign, config=WikiNamespaceConfig(store="x"))
    scoped = FederatedWikiStore(local, "t", [handle], []).scoped("issues")
    await subject.run(tmp_path, _opts(write_file=False), store=scoped, effective=_effective(tmp_path))
    assert [p["concept_id"] for p in await local.list_pages(category="brief")] == ["brief:daily:2026-10-06"]
    assert await foreign.list_pages(category="brief") == []
