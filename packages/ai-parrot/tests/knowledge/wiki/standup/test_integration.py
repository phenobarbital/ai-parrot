"""Regression cases for FEAT-627 cross-source standup integration."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.pipeline as subject
from parrot.interfaces.jira import parse_issue
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.jira_render import render_issue_document
from parrot.knowledge.wiki.project import WikiEffectiveConfig, WikiNamespaceConfig, WikiProjectConfig
from parrot.knowledge.wiki.repo_scan import build_file_slice, build_import_edges
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.tools import WikiStandupTool


async def _identity(_cfg: object, *, explicit: str | None = None, root: Path) -> StandupIdentity:
    """Return a local identity and make accidental Jira access impossible."""
    del explicit, root
    return StandupIdentity(wiki="human:tester", jira_account_id="5f8a:abc-123", jira_display_name="Jesus Lara")


def _effective(tmp_path: Path) -> WikiEffectiveConfig:
    """Build a project configuration whose plane lives under the test directory."""
    return WikiEffectiveConfig(
        config=WikiProjectConfig(wiki_name="integration", storage_dir=str(tmp_path / "plane")), env="local"
    )


def _store(tmp_path: Path, name: str) -> SQLiteWikiStore:
    """Open one isolated SQLite plane."""
    directory = tmp_path / "plane"
    directory.mkdir(exist_ok=True)
    return SQLiteWikiStore(directory / name, wiki_name="integration")


async def _scan_into(store: SQLiteWikiStore, root: Path, rel_path: str) -> WikiPageRecord:
    """Use the real file scanner and persist the resulting page record."""
    slice_ = build_file_slice(root, rel_path)
    assert slice_ is not None
    await store.upsert_pages([slice_.record])
    return slice_.record


def _options(anchor: date, **overrides: object) -> subject.StandupOptions:
    """Return deterministic, offline standup options."""
    values: dict[str, object] = {
        "anchor": anchor,
        "team": True,
        "use_llm": False,
        "write_file": False,
    }
    values.update(overrides)
    return subject.StandupOptions(**values)


@pytest.mark.asyncio
async def test_standup_end_to_end_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw_issue: dict[str, object]
) -> None:
    """Run real scanner, Jira renderer, native sources, SQLite writes, and Spanish rendering."""
    monkeypatch.setattr(subject, "resolve_identity", _identity)
    root = tmp_path / "project"
    root.mkdir()
    local = _store(tmp_path, "local.db")
    issues = _store(tmp_path, "issues.db")
    effective = _effective(tmp_path)

    meeting = root / "vault" / "planning.md"
    meeting.parent.mkdir()
    meeting.write_text(
        "---\ntype: meeting\nstatus: scheduled\ndate: 2026-10-07\nowner: human:tester\nproject: FEAT-627\n---\n# Planificación\n",
        encoding="utf-8",
    )
    draft = root / "docs" / "draft.md"
    draft.parent.mkdir()
    draft.write_text(
        "---\ntype: deliverable\nstatus: draft\nowner: human:tester\nproject: FEAT-627\n---\n# Diseño\n",
        encoding="utf-8",
    )
    await _scan_into(local, root, "vault/planning.md")
    await _scan_into(local, root, "docs/draft.md")
    await local.upsert_pages(
        [
            WikiPageRecord(
                concept_id="memory:standup",
                title="Remember the rollout",
                category="note",
                summary="memory",
                body="# Memory",
                origin="memory",
                asserted_by="human:tester",
                updated_at="2026-10-06T08:00:00+00:00",
            )
        ]
    )
    index = root / "sdd" / "tasks" / "index"
    index.mkdir(parents=True)
    (index / "feature.json").write_text(
        '{"tasks":[{"id":"TASK-77","title":"Ship standup","status":"in-progress",'
        '"assigned_to":"human:tester","feature":"FEAT-627"}]}',
        encoding="utf-8",
    )

    rendered = render_issue_document(
        parse_issue(raw_issue, base_url="https://example.atlassian.net", ac_field_id="customfield_10101"),
        fetched_at=datetime(2026, 10, 6, tzinfo=UTC),
    )
    jira_path = root / "issues" / "NAV-9372.md"
    jira_path.parent.mkdir()
    jira_path.write_text(rendered, encoding="utf-8")
    jira_record = await _scan_into(issues, root, "issues/NAV-9372.md")
    assert jira_record.attrs["type"] == "ticket"
    assert jira_record.attrs["x_assignee_id"] == "5f8a:abc-123"

    federation = FederatedWikiStore(
        local,
        "local",
        [NamespaceHandle("issues", issues, WikiNamespaceConfig(store=str(tmp_path / "issues-plane")))],
    )
    out_dir = tmp_path / "briefs"
    doc = await subject.run(
        root,
        _options(date(2026, 10, 6), language="es", write_file=True, out_dir=out_dir),
        store=federation,
        effective=effective,
    )

    assert set(doc.item_ids) >= {
        "file:vault/planning.md",
        "file:docs/draft.md",
        "issues::file:issues/NAV-9372.md",
        "memory:standup",
        "TASK-77",
    }
    assert doc.written_page is True
    assert doc.written_file is not None
    output = Path(doc.written_file).read_text(encoding="utf-8")
    assert "# Resumen diario" in output
    assert "## Por proyecto" in output
    stored = await local.get_page("brief:daily:2026-10-06", include_body=True)
    assert stored is not None
    assert stored["attrs"] == {
        "date": "2026-10-06",
        "items": json.dumps(sorted(set(doc.item_ids))),
        "language": "es",
        "owner": "human:tester",
        "period": "day",
        "source": "brief",
        "status": "draft",
        "type": "deliverable",
    }


@pytest.mark.asyncio
async def test_standup_rollup_week_month(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist three deterministic daily briefs and verify week/month source windows and deltas."""
    monkeypatch.setattr(subject, "resolve_identity", _identity)
    root = tmp_path / "project"
    root.mkdir()
    store = _store(tmp_path, "rollup.db")
    effective = _effective(tmp_path)
    source = root / "notes" / "a.md"
    source.parent.mkdir()
    source.write_text("---\ntype: deliverable\nstatus: draft\n---\n# Alpha\n", encoding="utf-8")
    await _scan_into(store, root, "notes/a.md")

    first = await subject.run(root, _options(date(2026, 10, 6)), store=store, effective=effective)
    await store.delete_page("file:notes/a.md")
    source = root / "notes" / "b.md"
    source.write_text("---\ntype: deliverable\nstatus: draft\n---\n# Beta\n", encoding="utf-8")
    await _scan_into(store, root, "notes/b.md")
    second = await subject.run(root, _options(date(2026, 10, 7)), store=store, effective=effective)
    third = await subject.run(root, _options(date(2026, 10, 8)), store=store, effective=effective)
    assert first.delta_new == []
    assert [item.id for item in second.delta_new] == ["file:notes/b.md"]
    assert [item.id for item in second.delta_closed] == ["file:notes/a.md"]
    assert third.previous_brief_id == "brief:daily:2026-10-07"

    week = await subject.run(
        root,
        _options(date(2026, 10, 8), period="week", write_page=False),
        store=store,
        effective=effective,
    )
    month = await subject.run(
        root,
        _options(date(2026, 10, 8), period="month", write_page=False),
        store=store,
        effective=effective,
    )
    expected = ["brief:daily:2026-10-06", "brief:daily:2026-10-07", "brief:daily:2026-10-08"]
    assert week.sources == expected
    assert month.sources == expected
    assert week.written_page is False and month.written_page is False


@pytest.mark.asyncio
async def test_build_parity_and_jira_attrs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw_issue: dict[str, object]
) -> None:
    """Keep code scanning stable, verify rendered Jira attrs, and prove the MCP default is read-only."""
    monkeypatch.setattr(subject, "resolve_identity", _identity)
    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "base.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "consumer.py").write_text("from base import VALUE\n", encoding="utf-8")
    base = build_file_slice(root, "src/base.py")
    consumer = build_file_slice(root, "src/consumer.py")
    assert base is not None and consumer is not None
    assert base.record.body == "# src/base.py\n\n## Content\nVALUE = 1\n"
    assert build_import_edges([base, consumer]) == [("file:src/consumer.py", "file:src/base.py", "references")]

    store = _store(tmp_path, "parity.db")
    await store.upsert_pages([base.record, consumer.record])
    jira_path = root / "issues" / "NAV-9372.md"
    jira_path.parent.mkdir()
    jira_path.write_text(
        render_issue_document(
            parse_issue(raw_issue, base_url="https://example.atlassian.net", ac_field_id="customfield_10101"),
            fetched_at=datetime(2026, 10, 6, tzinfo=UTC),
        ),
        encoding="utf-8",
    )
    jira_record = await _scan_into(store, root, "issues/NAV-9372.md")
    rows = await store.list_by_attrs({"type": "ticket", "project": "NAV", "x_assignee_id": "5f8a:abc-123"})
    assert [(row["concept_id"], row["attrs"]) for row in rows] == [(jira_record.concept_id, jira_record.attrs)]

    effective = _effective(tmp_path)
    before = await store.list_pages(limit=100)
    result = await WikiStandupTool(store, root, effective.config)._execute(date="2026-10-06")
    after = await store.list_pages(limit=100)
    assert result.success is True
    assert result.result["written_page"] is False and result.result["written_file"] is None
    assert after == before
