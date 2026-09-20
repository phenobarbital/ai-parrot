"""refresh_decisions idempotency, link repair and preservation (FEAT-578 M3)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.codec import documented_decision_id
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, refresh_decisions
from parrot.knowledge.wiki.decisions.models import DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


class TestDiscovery:
    def test_only_configured_globs_are_discovered(self, adr_repo, adr_config):
        found = discover_adr_sources(adr_repo, adr_config)
        assert all(p.startswith(("docs/adr/", "docs/adrs/", "docs/decisions/")) for p in found)

    def test_excluded_directories_win_over_globs(self, adr_repo, adr_config):
        """A matching glob inside an excluded dir is still excluded (spec §2)."""
        found = discover_adr_sources(adr_repo, adr_config)
        assert not any("node_modules" in p for p in found)
        assert "docs/adr/node_modules/0099-excluded.md" not in found


class TestRefresh:
    async def test_first_sync_creates_records(self, adr_repo, adr_config, adr_store):
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result.created > 0 and result.updated == 0

    async def test_second_sync_is_a_no_op(self, adr_repo, adr_config, adr_store):
        """Idempotent: unchanged sources bump nothing."""
        await refresh_decisions(adr_store, adr_repo, adr_config)
        before = {r.decision_id: r.revision for r in await DecisionRepository(adr_store).inventory()}
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result.created == 0 and result.updated == 0 and result.unchanged > 0
        after = {r.decision_id: r.revision for r in await DecisionRepository(adr_store).inventory()}
        assert after == before

    async def test_changed_adr_repairs_links_in_unchanged_code(self, adr_repo, adr_config, adr_store):
        """spec §2 Module 3 — the requirement most easily missed."""
        adr_path = adr_repo / "docs" / "adr" / "0050-repair-target.md"
        adr_path.write_text(
            "# Original decision\n\n## Context\nc\n\n## Decision\nOriginal decision text.\n\n## Consequences\nc\n",
            encoding="utf-8",
        )
        citing_path = adr_repo / "src" / "repair_citer.py"
        citing_path.write_text(
            '"""Cites ADR-77, which no ADR claims yet."""\n\n\ndef cited():\n    # see ADR-77\n    return 1\n',
            encoding="utf-8",
        )

        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert any(d.code == "ADR_REFERENCE_MISSING" for d in result.diagnostics)
        repo = DecisionRepository(adr_store)
        record, _hash = await repo.get(documented_decision_id("docs/adr/0050-repair-target.md"))
        assert record.links == []

        # Change ONLY the ADR file's claimed alias — the citing code never changes.
        adr_path.write_text(
            "---\nid: ADR-77\n---\n# Original decision\n\n## Context\nc\n\n## Decision\n"
            "Original decision text.\n\n## Consequences\nc\n",
            encoding="utf-8",
        )
        result2 = await refresh_decisions(adr_store, adr_repo, adr_config, paths=["docs/adr/0050-repair-target.md"])
        assert not any(d.code == "ADR_REFERENCE_MISSING" and "ADR-77" in d.message for d in result2.diagnostics)
        record2, _hash2 = await repo.get(documented_decision_id("docs/adr/0050-repair-target.md"))
        assert any(link.relation == "explains" and "repair_citer" in link.target_id for link in record2.links)

    async def test_removed_citation_removes_the_link(self, adr_repo, adr_config, adr_store):
        """A removal must delete the applicability link, not just stop adding."""
        adr_path = adr_repo / "docs" / "adr" / "0060-removal-target.md"
        adr_path.write_text(
            "# Removal target\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n", encoding="utf-8"
        )
        citing_path = adr_repo / "src" / "removal_citer.py"
        citing_path.write_text(
            '"""Module docstring."""\n\n# see ADR-60\n\n\ndef f():\n    return 1\n', encoding="utf-8"
        )

        repo = DecisionRepository(adr_store)
        await refresh_decisions(adr_store, adr_repo, adr_config)
        before, _ = await repo.get(documented_decision_id("docs/adr/0060-removal-target.md"))
        assert any(link.relation == "explains" for link in before.links)

        citing_path.write_text(
            '"""Module docstring, citation removed."""\n\n\ndef f():\n    return 1\n', encoding="utf-8"
        )
        await refresh_decisions(adr_store, adr_repo, adr_config)
        after, _ = await repo.get(documented_decision_id("docs/adr/0060-removal-target.md"))
        assert not any(link.relation == "explains" for link in after.links)

    async def test_removed_citation_removes_the_link_on_a_partial_sync(self, adr_repo, adr_config, adr_store):
        """A partial sync must still retract a stale link for an UNCHANGED ADR
        whose citing code changed elsewhere — the write loop must not only
        touch records whose own source was named in `paths` this pass."""
        adr_path = adr_repo / "docs" / "adr" / "0065-removal-target-partial.md"
        adr_path.write_text(
            "# Removal target (partial)\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n",
            encoding="utf-8",
        )
        citing_path = adr_repo / "src" / "removal_citer_partial.py"
        citing_path.write_text(
            '"""Module docstring."""\n\n# see ADR-65\n\n\ndef f():\n    return 1\n', encoding="utf-8"
        )
        unrelated_path = adr_repo / "docs" / "adr" / "0066-unrelated-partial.md"
        unrelated_path.write_text(
            "# Unrelated (untouched by the removal)\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n",
            encoding="utf-8",
        )

        repo = DecisionRepository(adr_store)
        await refresh_decisions(adr_store, adr_repo, adr_config)
        before, _ = await repo.get(documented_decision_id("docs/adr/0065-removal-target-partial.md"))
        assert any(link.relation == "explains" for link in before.links)

        # The citation disappears, but the PARTIAL sync below only names the
        # UNRELATED ADR file — 0065's own source is never reparsed this pass.
        citing_path.write_text(
            '"""Module docstring, citation removed."""\n\n\ndef f():\n    return 1\n', encoding="utf-8"
        )
        await refresh_decisions(adr_store, adr_repo, adr_config, paths=["docs/adr/0066-unrelated-partial.md"])
        after, _ = await repo.get(documented_decision_id("docs/adr/0065-removal-target-partial.md"))
        assert not any(link.relation == "explains" for link in after.links)

    async def test_deleted_adr_source_is_missing_not_deleted(self, adr_repo, adr_config, adr_store):
        """spec §2: retain records whose sources disappeared (AC7)."""
        adr_path = adr_repo / "docs" / "adr" / "0070-will-vanish.md"
        adr_path.write_text(
            "# Will vanish\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n", encoding="utf-8"
        )
        repo = DecisionRepository(adr_store)
        await refresh_decisions(adr_store, adr_repo, adr_config)
        assert (await repo.get(documented_decision_id("docs/adr/0070-will-vanish.md"))) is not None

        adr_path.unlink()
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result.missing >= 1
        assert (await repo.get(documented_decision_id("docs/adr/0070-will-vanish.md"))) is not None

    async def test_rename_creates_a_new_record(self, adr_repo, adr_config, adr_store):
        """V1 does not infer identity across renames (spec §2)."""
        old_path = adr_repo / "docs" / "adr" / "0080-original-name.md"
        old_path.write_text(
            "# Original name\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n", encoding="utf-8"
        )
        repo = DecisionRepository(adr_store)
        await refresh_decisions(adr_store, adr_repo, adr_config)

        new_path = adr_repo / "docs" / "adr" / "0080-renamed.md"
        old_path.rename(new_path)
        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        assert (await repo.get(documented_decision_id("docs/adr/0080-original-name.md"))) is not None
        assert (await repo.get(documented_decision_id("docs/adr/0080-renamed.md"))) is not None
        assert result.missing >= 1

    async def test_candidate_records_are_untouched(self, adr_repo, adr_config, adr_store):
        """AC7: a documented refresh never disturbs a reviewed candidate."""
        candidate = DecisionRecord(
            decision_id="adr:candidate:xyz",
            decision="an inferred rationale",
            origin="inferred",
            review_status="accepted",
            review_history=[
                {
                    "revision": 1,
                    "action": "accept",
                    "actor": "human:reviewer",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "before_sha1": "a",
                    "after_sha1": "b",
                }
            ],
        )
        repo = DecisionRepository(adr_store)
        await repo.save(candidate, None)
        before, before_hash = await repo.get("adr:candidate:xyz")

        await refresh_decisions(adr_store, adr_repo, adr_config)

        after, after_hash = await repo.get("adr:candidate:xyz")
        assert after == before
        assert after_hash == before_hash

    async def test_partial_failure_retries_to_convergence(self, adr_repo, adr_config, adr_store, monkeypatch):
        """spec §2: per-record atomic; a retry converges without duplicates."""
        a_path = adr_repo / "docs" / "adr" / "0090-first.md"
        a_path.write_text("# First\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n", encoding="utf-8")
        b_path = adr_repo / "docs" / "adr" / "0091-second.md"
        b_path.write_text("# Second\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nc\n", encoding="utf-8")

        from parrot.knowledge.wiki.decisions.models import DecisionError

        original_save = DecisionRepository.save
        target_id = documented_decision_id("docs/adr/0091-second.md")
        attempts: dict[str, int] = {}

        async def flaky_save(self, record, expected_content_hash):
            attempts[record.decision_id] = attempts.get(record.decision_id, 0) + 1
            if record.decision_id == target_id and attempts[record.decision_id] == 1:
                raise DecisionError("ADR_WRITE_UNSUPPORTED", "simulated failure", decision_id=record.decision_id)
            return await original_save(self, record, expected_content_hash)

        monkeypatch.setattr(DecisionRepository, "save", flaky_save)
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert any(d.decision_id == documented_decision_id("docs/adr/0091-second.md") for d in result.diagnostics)

        monkeypatch.setattr(DecisionRepository, "save", original_save)
        result2 = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result2.created + result2.unchanged >= 0  # convergence, not a crash

        repo = DecisionRepository(adr_store)
        inventory = await repo.inventory()
        ids = [r.decision_id for r in inventory]
        assert ids.count(documented_decision_id("docs/adr/0090-first.md")) == 1
        assert ids.count(documented_decision_id("docs/adr/0091-second.md")) == 1

    async def test_ambiguous_alias_stays_unresolved(self, adr_repo, adr_config, adr_store):
        """Two files claiming ADR-42 resolve to neither (spec §2)."""
        citing_path = adr_repo / "src" / "ambiguous_citer.py"
        citing_path.write_text('"""See ADR-42."""\n\n\ndef f():\n    return 1\n', encoding="utf-8")

        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert any(d.code == "ADR_REFERENCE_AMBIGUOUS" for d in result.diagnostics)

        repo = DecisionRepository(adr_store)
        dup_a, _ = await repo.get(documented_decision_id("docs/adr/0042-dup-a.md"))
        dup_b, _ = await repo.get(documented_decision_id("docs/adr/0042-dup-b.md"))
        assert not any(link.relation == "explains" for link in dup_a.links)
        assert not any(link.relation == "explains" for link in dup_b.links)

    async def test_empty_inventory_skips_the_code_walk(self, tmp_path, adr_config, adr_store, monkeypatch):
        """No alias in the inventory -> no citation can resolve, so don't walk.

        A project with no ADR yet would otherwise read, tokenize and
        ast.parse every Python file in the repository on every build, to
        resolve citations against an empty alias map.
        """
        from parrot.knowledge.wiki.decisions import ingest

        def _fail_discover(*args, **kwargs):
            raise AssertionError("refresh_decisions must not walk the code with an empty inventory")

        monkeypatch.setattr(ingest, "discover_python_files", _fail_discover)

        result = await refresh_decisions(adr_store, tmp_path, adr_config)
        assert result.created == 0 and result.updated == 0

    async def test_inventory_with_an_alias_still_walks_the_code(self, adr_repo, adr_config, adr_store, monkeypatch):
        """The guard is about an EMPTY alias map, never about skipping work."""
        from parrot.knowledge.wiki.decisions import ingest

        walked: list[object] = []
        real_discover = ingest.discover_python_files

        def _spy(root, *args, **kwargs):
            walked.append(root)
            return real_discover(root, *args, **kwargs)

        monkeypatch.setattr(ingest, "discover_python_files", _spy)

        await refresh_decisions(adr_store, adr_repo, adr_config)
        assert walked, "an inventory carrying ADR aliases must still resolve code citations"

    async def test_sync_makes_zero_llm_calls(self, adr_repo, adr_config, adr_store, monkeypatch):
        """AC5: ordinary scan/read paths never construct or invoke a client."""
        from parrot.clients.base import AbstractClient
        from parrot.clients.factory import LLMFactory

        def _fail_create(*args, **kwargs):
            raise AssertionError("refresh_decisions must never construct an LLM client")

        async def _fail_invoke(*args, **kwargs):
            raise AssertionError("refresh_decisions must never invoke an LLM client")

        monkeypatch.setattr(LLMFactory, "create", staticmethod(_fail_create))
        monkeypatch.setattr(AbstractClient, "invoke", _fail_invoke)

        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result is not None
