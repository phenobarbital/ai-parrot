"""Integration tests for the Fireflies Meeting Registry (FEAT-472, TASK-2558).

Proves the three load-bearing, cross-module claims the unit tests (TASK-2553
through TASK-2557) cannot exercise individually:

- G5: the sync registry and the vault ingest share ONE row on one
  ``wiki.db`` (:func:`test_registry_shared_with_wiki_toolkit`).
- The full create -> revise -> analyse -> cheap-skip cycle holds
  end-to-end (:func:`test_end_to_end_create_revise_analyse`).
- G8: an existing (pre-registry) vault upgrades without duplicating
  anything (:func:`test_existing_vault_upgrade_no_duplicates`).

No network, no real LLM, no ArangoDB: ``_call_fireflies_tool`` is stubbed
via a keyed fake (same pattern as ``tests/test_fireflies_obsidian_sync.py``,
TASK-2556); the vault is a real local ``ObsidianToolkit``; the registry and
the wiki toolkit are real, sharing one sqlite ``wiki.db`` per test.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from parrot.agents.meeting_registry import MeetingRegistry
from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.tools.obsidian import ObsidianToolkit

pytestmark = pytest.mark.integration


def _fireflies_listing_text(items: list[dict]) -> str:
    """Build listing text in the format `_parse_fireflies_response` expects."""
    lines = [f"[{len(items)}]:"]
    for item in items:
        lines.append(f"  - id: {item['id']}")
        lines.append(f"    title: {item['title']}")
        lines.append(f"    dateString: {item['date']}T00:00:00.000Z")
        lines.append(f"    duration: {item.get('duration', 10)}")
    return "\n".join(lines)


@pytest.fixture
def fake_fireflies():
    """Stub state for `_call_fireflies_tool` (see tests/test_fireflies_obsidian_sync.py)."""
    state: dict = {"listing": [], "transcripts": {}, "summaries": {}, "calls": []}

    async def _call(tool_name: str, args: dict):
        state["calls"].append((tool_name, dict(args)))
        if tool_name == "fireflies_get_transcripts":
            return SimpleNamespace(success=True, result=_fireflies_listing_text(state["listing"]))
        if tool_name == "fireflies_get_transcript":
            tid = args["transcriptId"]
            return SimpleNamespace(success=True, result=state["transcripts"].get(tid, ""))
        if tool_name == "fireflies_get_summary":
            tid = args["transcriptId"]
            if tid in state["summaries"]:
                return SimpleNamespace(success=True, result=state["summaries"][tid])
            return SimpleNamespace(success=False, result="")
        raise AssertionError(f"unexpected Fireflies tool call: {tool_name}")

    state["call"] = _call
    return state


def _build_agent(vault_root: Path, registry_dir: Path, fake_fireflies) -> FirefliesObsidianAgent:
    """A FirefliesObsidianAgent with every external seam stubbed except the
    registry/vault (both real, on tmp dirs) — same construction pattern as
    ``tests/test_fireflies_obsidian_sync.py``.
    """
    inst = FirefliesObsidianAgent.__new__(FirefliesObsidianAgent)
    inst.name = "FirefliesObsidianIntegrationTest"
    inst.logger = logging.getLogger("test-fireflies-meeting-registry")
    inst.vault_path = vault_root
    inst.meetings_folder = "meetings"
    inst.default_filters = None
    inst.fireflies_token = "test-token"
    inst.registry_dir = registry_dir
    inst.registry = None
    inst._mcp_fireflies_initialized = True
    inst.obsidian_toolkit = ObsidianToolkit(
        vault_path=str(vault_root),
        backend="local",
        allowed_operations={"read", "bulk_read", "list", "search", "create", "update", "move", "delete"},
    )
    inst._ensure_fireflies_mcp = AsyncMock(return_value=None)
    inst._call_fireflies_tool = AsyncMock(side_effect=fake_fireflies["call"])
    inst.client = MagicMock()
    return inst


def _mock_pi() -> MagicMock:
    """Minimal ``PageIndexToolkit`` stub (same contract as
    ``tests/knowledge/wiki/conftest.py``'s ``mock_pi``) — no real LLM.
    """
    pi = MagicMock()
    pi.insert_markdown = AsyncMock(return_value={"tree_name": "meetings", "new_node_ids": ["m1"]})
    pi.insert_content = AsyncMock(
        return_value={
            "tree_name": "meetings",
            "new_node_ids": ["n1"],
            "title": "Meeting",
            "summary": "A meeting.",
        }
    )
    pi.create_tree = AsyncMock(return_value={"tree_name": "meetings"})
    pi.delete_tree = AsyncMock(return_value={"status": "deleted"})
    # ObsidianVaultLoader.incremental_update's own per-note contract
    # (parrot/loaders/obsidian/loader.py) — one node per note, keyed by an
    # incrementing counter so a repeat sync keeps returning fresh ids.
    _node_counter = iter(range(1, 10_000))
    pi.add_node = AsyncMock(side_effect=lambda *a, **k: {"node_id": f"node-{next(_node_counter)}"})
    pi.delete_node = AsyncMock(return_value={"status": "deleted"})
    return pi


def _write_note(
    meetings_dir: Path,
    filename: str,
    *,
    fireflies_id: str,
    title: str,
    date: str,
    has_analysis: bool = False,
    duration_minutes: float = 10.0,
) -> Path:
    frontmatter = {
        "fireflies_id": fireflies_id,
        "title": title,
        "date": date,
        "participants": [],
        "duration_minutes": duration_minutes,
        "synced_at": "2026-08-01T00:00:00+00:00",
    }
    block = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = "Meeting transcript body.\n"
    if has_analysis:
        body += "\n## Analysis\n\nKey takeaways here.\n"
    path = meetings_dir / filename
    path.write_text(f"---\n{block}---\n\n{body}", encoding="utf-8")
    return path


class TestRegistrySharedWithWikiToolkit:
    async def test_registry_shared_with_wiki_toolkit(self, tmp_path: Path, fake_fireflies):
        vault_root = tmp_path / "vault"
        (vault_root / "meetings").mkdir(parents=True)
        registry_dir = tmp_path / "registry"

        agent = _build_agent(vault_root, registry_dir, fake_fireflies)
        agent.registry = MeetingRegistry(registry_dir)

        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "Transcript v1 content"}
        sync_report = await agent.sync_fireflies_transcripts(limit=10)
        assert sync_report["synced"] == 1

        wiki_config = WikiConfig(wiki_name="meetings", storage_dir=registry_dir, sync_graph=False)
        wiki_toolkit = LLMWikiToolkit(_mock_pi(), None, None, wiki_config)

        await wiki_toolkit.ingest_obsidian_vault("meetings", str(vault_root / "meetings"), incremental=True)

        rows = agent.registry._manager.list_by_external_prefix("fireflies:")
        assert len(rows) == 1
        row = rows[0]
        assert row.external_id == "fireflies:abc"
        assert row.doc_metadata is not None and "fireflies" in row.doc_metadata
        assert row.pages_generated  # non-empty — the ingest wrote pages onto THIS row

        stamped = await agent.registry.mark_wiki_ingested()
        assert stamped == 1

        # Repair: rename the note on disk AND change its content (a
        # same-content rename alone is never observed — classify() has no
        # independent file-existence check; repair only runs ahead of an
        # actual create/revise, spec §2 step 3). Sync again: repair_path
        # finds "abc" by frontmatter, the row's source_uri is corrected,
        # the note is revised in place — still exactly one row.
        old_path = vault_root / "meetings" / "2026-08-01-standup.md"
        renamed_path = vault_root / "meetings" / "renamed-standup.md"
        old_path.rename(renamed_path)
        fake_fireflies["transcripts"] = {"abc": "Transcript v2, materially different content"}

        # force_refetch=True: unchanged listing metadata alone would
        # otherwise satisfy the cheap-skip path (see the equivalent note
        # in test_end_to_end_create_revise_analyse).
        second_sync = await agent.sync_fireflies_transcripts(limit=10, force_refetch=True)
        assert second_sync["revised"] == 1

        rows_after = agent.registry._manager.list_by_external_prefix("fireflies:")
        assert len(rows_after) == 1
        assert rows_after[0].source_id == row.source_id  # same row, not a new one

        await wiki_toolkit.ingest_obsidian_vault("meetings", str(vault_root / "meetings"), incremental=True)
        rows_final = agent.registry._manager.list_by_external_prefix("fireflies:")
        assert len(rows_final) == 1


class TestEndToEndCreateReviseAnalyse:
    async def test_end_to_end_create_revise_analyse(self, tmp_path: Path, fake_fireflies):
        vault_root = tmp_path / "vault"
        (vault_root / "meetings").mkdir(parents=True)
        registry_dir = tmp_path / "registry"

        agent = _build_agent(vault_root, registry_dir, fake_fireflies)
        agent.registry = MeetingRegistry(registry_dir)

        # v1 -> created.
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "v1 transcript content"}
        r1 = await agent.sync_fireflies_transcripts(limit=10)
        assert r1["synced"] == 1
        assert r1["revised"] == 0

        # v2, same id -> updated in place, analysis reset to pending.
        # force_refetch=True: the listing metadata (title/date/duration)
        # is otherwise unchanged, which alone would satisfy the cheap-skip
        # path (classify never inspects fetched content when that path
        # applies) — force_refetch bypasses it so the new transcript is
        # actually fetched and fingerprinted.
        fake_fireflies["transcripts"] = {"abc": "v2 transcript content, materially different"}
        r2 = await agent.sync_fireflies_transcripts(limit=10, force_refetch=True)
        assert r2["synced"] == 0
        assert r2["revised"] == 1
        record = await agent.registry.lookup("abc")
        assert record.analysis_status == "pending"
        v2_fingerprint = record.fingerprint

        # Analyse -> done, with the v2 fingerprint.
        agent.client.complete = AsyncMock(return_value="##Summary\nAll good\n##Follow Ups\n1. q1\n##Insights\n- i1")
        outcome = await agent.summarize_pending_transcripts()
        assert outcome["analyzed"] == ["2026-08-01-standup"]

        analysed_record = await agent.registry.lookup("abc")
        assert analysed_record.analysis_status == "done"
        assert analysed_record.analysis_fingerprint == v2_fingerprint

        # Sync v2 again (unchanged) -> cheap skip, no transcript fetch.
        fake_fireflies["calls"].clear()
        r3 = await agent.sync_fireflies_transcripts(limit=10)
        assert r3["skipped"] == 1
        assert all(name != "fireflies_get_transcript" for name, _ in fake_fireflies["calls"])


class TestExistingVaultUpgradeNoDuplicates:
    async def test_existing_vault_upgrade_no_duplicates(self, tmp_path: Path, fake_fireflies):
        vault_root = tmp_path / "vault"
        meetings_dir = vault_root / "meetings"
        meetings_dir.mkdir(parents=True)
        registry_dir = tmp_path / "registry"  # no wiki.db yet — pre-registry vault

        _write_note(meetings_dir, "2026-08-01-standup-a.md", fireflies_id="id-a", title="Standup A", date="2026-08-01")
        _write_note(
            meetings_dir,
            "2026-08-02-standup-b.md",
            fireflies_id="id-b",
            title="Standup B",
            date="2026-08-02",
            has_analysis=True,
        )
        _write_note(meetings_dir, "2026-08-03-standup-c1.md", fireflies_id="id-c", title="Standup C", date="2026-08-03")
        _write_note(
            meetings_dir,
            "2026-08-03-standup-c2.md",
            fireflies_id="id-c",
            title="Standup C",
            date="2026-08-03",
            has_analysis=True,
        )
        _write_note(meetings_dir, "2026-08-04-standup-d.md", fireflies_id="id-d", title="Standup D", date="2026-08-04")

        agent = _build_agent(vault_root, registry_dir, fake_fireflies)
        agent.registry = MeetingRegistry(registry_dir)

        # Mirrors what configure() does on first boot against a
        # pre-existing vault (spec §2 "Backfill").
        report = await agent.registry.backfill_from_vault(
            toolkit=agent.obsidian_toolkit,
            meetings_folder=agent.meetings_folder,
            analysis_heading=agent.ANALYSIS_HEADING,
        )
        assert report.seeded == 4
        assert len(report.duplicates) == 1

        remaining = sorted(p.name for p in meetings_dir.glob("*.md"))
        assert len(remaining) == 4  # the duplicate pair collapsed to one file

        # Syncing the same 4 ids afterward creates no NEW files — a
        # backfilled row's fingerprint is always None (nothing was ever
        # fetched from Fireflies for it), so the first post-backfill sync
        # always revises each row in place rather than cheap-skipping;
        # either way, none of them is ever re-created as a second file.
        fake_fireflies["listing"] = [
            {"id": "id-a", "title": "Standup A", "date": "2026-08-01", "duration": 10},
            {"id": "id-b", "title": "Standup B", "date": "2026-08-02", "duration": 10},
            {"id": "id-c", "title": "Standup C", "date": "2026-08-03", "duration": 10},
            {"id": "id-d", "title": "Standup D", "date": "2026-08-04", "duration": 10},
        ]
        fake_fireflies["transcripts"] = {
            "id-a": "Meeting transcript body.",
            "id-b": "Meeting transcript body.",
            "id-c": "Meeting transcript body.",
            "id-d": "Meeting transcript body.",
        }

        resync = await agent.sync_fireflies_transcripts(limit=10)
        assert resync["synced"] == 0

        remaining_after = sorted(p.name for p in meetings_dir.glob("*.md"))
        assert len(remaining_after) == 4
        assert remaining_after == remaining
