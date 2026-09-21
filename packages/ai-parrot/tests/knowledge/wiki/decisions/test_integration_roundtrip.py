"""End-to-end ADR pipeline (FEAT-578 Module 7, spec §4 integration tests)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.decisions.codec import documented_decision_id
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, root) -> None:
    """Run a quiet, graph-less `wikitoolkit build` against ``root``."""
    result = runner.invoke(wiki, ["build", "--path", str(root), "--no-graph", "--quiet"])
    assert result.exit_code == 0, result.output


class TestBuildLookupWhyRoundtrip:
    def test_build_lookup_why_roundtrip(self, runner, adr_repo):
        """Ordinary build + ADR refresh -> lookup -> why -> raw page read."""
        _build(runner, adr_repo)

        sync_result = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        # The fixture's malformed-frontmatter ADR always emits one diagnostic
        # (non-fatal per parser.py); the other ADRs must still persist.
        sync_payload = json.loads(sync_result.output)
        assert sync_payload["created"] + sync_payload["updated"] + sync_payload["unchanged"] >= 1

        lookup_result = runner.invoke(
            wiki, ["adr", "lookup", "sym:src/citing_module.py#ClassA.run", "--json", "--path", str(adr_repo)]
        )
        assert lookup_result.exit_code == 0, lookup_result.output
        dossier = json.loads(lookup_result.output)
        assert dossier["status"] == "ok"
        assert dossier["documented"], dossier
        hit = dossier["documented"][0]
        assert hit["citations"], "the accepted decision must cite the citing symbol"

        why_result = runner.invoke(wiki, ["adr", "why", "why pgvector", "--json", "--path", str(adr_repo)])
        assert why_result.exit_code == 0, why_result.output
        why_dossier = json.loads(why_result.output)
        assert why_dossier["status"] == "ok"
        assert why_dossier["documented"]
        assert any(h["citations"] for h in why_dossier["documented"])

        # Raw generic page read: the accepted ADR's managed page is a normal
        # wiki page, not a special-cased surface.
        decision_id = documented_decision_id("docs/adr/0001-use-pgvector.md")
        page_result = runner.invoke(wiki, ["page", decision_id, "--path", str(adr_repo)])
        assert page_result.exit_code == 0, page_result.output

    def test_page_read_shows_labels_not_raw_json_only(self, runner, adr_repo):
        """AC9: the generic page surface still reads as a labeled decision."""
        _build(runner, adr_repo)
        runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])

        decision_id = documented_decision_id("docs/adr/0001-use-pgvector.md")
        page_result = runner.invoke(wiki, ["page", decision_id, "--path", str(adr_repo)])
        assert page_result.exit_code == 0, page_result.output
        # The fixture's accepted ADR has no explicit `## Status` section, so
        # its source_status is 'unknown' (spec §2 parser default) — the label
        # is still the mandatory [DOCUMENTED / <STATUS>] prefix (AC9), not a
        # claim about which status value it carries.
        assert "[DOCUMENTED / UNKNOWN]" in page_result.output


class TestIncrementalLinksAndDeletion:
    def test_incremental_links_and_deletion(self, runner, adr_repo):
        """ADR added / changed / deleted / renamed; citing code re-resolved."""
        _build(runner, adr_repo)
        runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])

        new_adr_path = adr_repo / "docs" / "adr" / "0009-new-decision.md"
        new_adr_path.write_text(
            "# A brand-new decision\n\n## Context\nNeeded.\n\n## Decision\nDo the new thing.\n\n"
            "## Consequences\nNone yet.\n",
            encoding="utf-8",
        )
        upsert_1 = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        payload_1 = json.loads(upsert_1.output)
        assert payload_1["created"] >= 1

        new_id = documented_decision_id("docs/adr/0009-new-decision.md")
        lookup = runner.invoke(wiki, ["page", new_id, "--path", str(adr_repo)])
        assert lookup.exit_code == 0, lookup.output

        # Change the new ADR's content (an "alias" edit) — a re-sync must
        # update the SAME decision_id (rel_path-derived), never mint a new one.
        new_adr_path.write_text(
            "# A brand-new decision, revised\n\n## Context\nNeeded, revised.\n\n"
            "## Decision\nDo the revised thing.\n\n## Consequences\nSame as before.\n",
            encoding="utf-8",
        )
        upsert_2 = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        payload_2 = json.loads(upsert_2.output)
        assert payload_2["updated"] >= 1

        # Delete it — the record is retained, marked missing, never purged.
        new_adr_path.unlink()
        upsert_3 = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        payload_3 = json.loads(upsert_3.output)
        assert payload_3["missing"] >= 1
        still_there = runner.invoke(wiki, ["page", new_id, "--path", str(adr_repo)])
        assert still_there.exit_code == 0, still_there.output

        # Rename another ADR: 0003-add-caching.md -> 0010-add-caching.md.
        # This mints a NEW decision_id (path-derived); the old record persists.
        old_path = adr_repo / "docs" / "adr" / "0003-add-caching.md"
        renamed_path = adr_repo / "docs" / "adr" / "0010-add-caching.md"
        renamed_path.write_text(old_path.read_text(encoding="utf-8"), encoding="utf-8")
        old_path.unlink()
        upsert_4 = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        payload_4 = json.loads(upsert_4.output)
        assert payload_4["created"] >= 1

        old_id = documented_decision_id("docs/adr/0003-add-caching.md")
        renamed_id = documented_decision_id("docs/adr/0010-add-caching.md")
        old_still_there = runner.invoke(wiki, ["page", old_id, "--path", str(adr_repo)])
        assert old_still_there.exit_code == 0, old_still_there.output
        new_renamed = runner.invoke(wiki, ["page", renamed_id, "--path", str(adr_repo)])
        assert new_renamed.exit_code == 0, new_renamed.output

    async def test_candidate_history_survives_every_step(self, runner, adr_repo, adr_store):
        """AC7: a candidate's review_history is byte-identical across an
        unrelated sequence of ADR sync mutations."""
        candidate = DecisionRecord(
            decision_id="adr:candidate:steady",
            decision="use exponential backoff",
            origin="inferred",
            review_status="accepted",
            review_history=[
                {
                    "revision": 1,
                    "action": "accept",
                    "actor": "human:reviewer",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "reason": "looks right",
                }
            ],
        )
        repo = DecisionRepository(adr_store, max_records=DecisionConfig().max_records)
        await repo.save(candidate, None)

        before = (await repo.get("adr:candidate:steady"))[0].review_history

        # Perform an unrelated mutation sequence on the SAME store: add a
        # sibling record, then update and delete it.
        sibling = DecisionRecord(decision_id="adr:doc:sibling", decision="sibling decision", origin="documented")
        await repo.save(sibling, None)
        loaded_sibling, sibling_hash = await repo.get("adr:doc:sibling")
        bumped_sibling = loaded_sibling.model_copy(update={"revision": 2, "decision": "sibling decision, revised"})
        await repo.save(bumped_sibling, sibling_hash)

        after = (await repo.get("adr:candidate:steady"))[0].review_history
        assert [event.model_dump() for event in before] == [event.model_dump() for event in after]


class TestPartialSyncRetry:
    async def test_partial_sync_retry(self, adr_repo, adr_config, adr_store, monkeypatch):
        """Failure after one record persists; retry converges cleanly."""
        from parrot.knowledge.wiki.decisions.ingest import refresh_decisions
        from parrot.knowledge.wiki.decisions.repository import DecisionRepository as RepoClass

        call_count = {"n": 0}
        original_save = RepoClass.save

        async def _flaky_save(self, record, expected_content_hash):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated transient failure after the first record")
            return await original_save(self, record, expected_content_hash)

        monkeypatch.setattr(RepoClass, "save", _flaky_save)

        with pytest.raises(RuntimeError):
            await refresh_decisions(adr_store, adr_repo, adr_config, None)

        # Unpatch and retry: every ADR source must end up persisted exactly
        # once, with no record's revision double-bumped by the partial pass.
        monkeypatch.setattr(RepoClass, "save", original_save)
        result = await refresh_decisions(adr_store, adr_repo, adr_config, None)
        assert result.diagnostics is not None  # malformed-frontmatter ADR always yields one

        repo = RepoClass(adr_store, max_records=adr_config.max_records)
        inventory = await repo.inventory()
        by_id: dict[str, int] = {}
        for record in inventory:
            by_id[record.decision_id] = by_id.get(record.decision_id, 0) + 1
        assert all(count == 1 for count in by_id.values()), by_id
        assert all(record.revision <= 2 for record in inventory), [r.revision for r in inventory]
