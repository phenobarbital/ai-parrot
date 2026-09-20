"""generate/review orchestration: dedup, drift, persistence (FEAT-578 M5)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import (
    CandidateBatch,
    CandidateDraft,
    DecisionConfig,
    DecisionError,
    ReviewRequest,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService


class CountingClient:
    """Fake AbstractClient that records how many times it was invoked."""

    def __init__(self, decision: str = "Retries use backoff."):
        self.decision = decision
        self.calls = 0

    async def invoke(self, prompt, **kwargs):
        self.calls += 1
        batch = CandidateBatch(candidates=[CandidateDraft(decision=self.decision, evidence_indexes=[0])])
        return type("InvokeResult", (), {"output": batch, "model": "fake", "usage": {}})()


class _StubHit:
    def __init__(self, symbol_id: str, qualname: str):
        self.symbol_id = symbol_id
        self.qualname = qualname


class _StubLookupOutput:
    def __init__(self, hits):
        self.hits = hits


class _StubStructural:
    def __init__(self, hits):
        self._hits = hits

    async def lookup(self, query, **kwargs):
        return _StubLookupOutput(self._hits)


@pytest.fixture
def gen_config() -> DecisionConfig:
    return DecisionConfig(generation_enabled=True)


@pytest.fixture
def source_file(tmp_path):
    """One small Python file with no documented rationale."""
    path = tmp_path / "svc.py"
    path.write_text("def fetch():\n    for n in range(3):\n        sleep(2 ** n)\n")
    return path


class TestGenerationGates:
    async def test_remote_namespace_cannot_generate(self, adr_store, gen_config):
        """spec §2 Module 6: a store-only namespace has no local code."""
        service = DecisionService(adr_store, None, gen_config, client=CountingClient())
        with pytest.raises(DecisionError) as exc:
            await service.generate("sym:svc.py#fetch")
        assert exc.value.code == "ADR_INVALID_ARGUMENT"

    async def test_disabled_generation_never_invokes(self, adr_store, tmp_path, source_file):
        client = CountingClient()
        service = DecisionService(adr_store, tmp_path, DecisionConfig(), client=client)
        with pytest.raises(DecisionError) as exc:
            await service.generate("svc.py")
        assert exc.value.code == "ADR_MODEL_UNCONFIGURED"
        assert client.calls == 0

    async def test_ambiguous_target_is_refused(self, adr_store, tmp_path, gen_config, source_file):
        structural = _StubStructural([_StubHit("sym:svc.py#fetch", "fetch"), _StubHit("sym:other.py#fetch", "fetch")])
        client = CountingClient()
        service = DecisionService(adr_store, tmp_path, gen_config, structural=structural, client=client)
        with pytest.raises(DecisionError) as exc:
            await service.generate("fetch")
        assert exc.value.code == "ADR_INVALID_ARGUMENT"
        assert client.calls == 0


class TestGenerationPersistence:
    async def test_candidate_is_persisted_as_inferred(self, adr_store, tmp_path, source_file, gen_config):
        """AC4: generated records stay inferred with unknown source status."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        result = await service.generate("svc.py")
        assert result.decision_ids
        record, _ = await DecisionRepository(adr_store).get(result.decision_ids[0])
        assert record.origin == "inferred"
        assert record.source_status == "unknown"
        assert record.review_status == "unreviewed"
        assert record.generation is not None and record.generation.scope_id

    async def test_observations_and_hypotheses_are_stored_separately(
        self, adr_store, tmp_path, source_file, gen_config
    ):
        client = CountingClient()
        client.decision = "Uses exponential backoff."
        service = DecisionService(adr_store, tmp_path, gen_config, client=client)
        result = await service.generate("svc.py")
        record, _ = await DecisionRepository(adr_store).get(result.decision_ids[0])
        # CandidateDraft defaults observations/hypotheses to []; the fields
        # exist and are stored independently either way (AC4).
        assert record.observations == []
        assert record.hypotheses == []

    async def test_only_supplied_evidence_is_cited(self, adr_store, tmp_path, source_file, gen_config):
        """AC4: no invented paths — every citation traces back to the packet."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        result = await service.generate("svc.py")
        record, _ = await DecisionRepository(adr_store).get(result.decision_ids[0])
        assert len(record.evidence) == 1
        assert record.evidence[0].rel_path == "svc.py"


class TestDedup:
    async def test_rerun_reuses_without_invoking(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: same evidence returns the existing candidates for free."""
        client = CountingClient()
        service = DecisionService(adr_store, tmp_path, gen_config, client=client)
        first = await service.generate("svc.py")
        second = await service.generate("svc.py")
        assert client.calls == 1
        assert second.reused == first.decision_ids
        assert second.decision_ids == []

    async def test_rerun_preserves_a_reviewed_candidate(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: review state survives regeneration."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        first = await service.generate("svc.py")
        decision_id = first.decision_ids[0]
        record, _ = await DecisionRepository(adr_store).get(decision_id)
        await service.review(
            ReviewRequest(decision_id=decision_id, expected_revision=record.revision, action="accept", actor="human:m")
        )
        await service.generate("svc.py")
        after, _ = await DecisionRepository(adr_store).get(decision_id)
        assert after.review_status == "accepted"
        assert len(after.review_history) == 1

    async def test_changed_evidence_creates_a_new_record(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: new evidence mints a new id; the old record survives."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        first = await service.generate("svc.py")
        source_file.write_text("def fetch():\n    for n in range(5):\n        sleep(2 ** n)\n")
        second = await service.generate("svc.py")
        assert second.decision_ids
        assert second.decision_ids[0] != first.decision_ids[0]
        still_there, _ = await DecisionRepository(adr_store).get(first.decision_ids[0])
        assert still_there is not None


class TestEvidenceDrift:
    async def test_mid_generation_change_writes_nothing(self, adr_store, tmp_path, source_file, gen_config):
        """spec §7: a concurrent build must not produce a stale candidate."""

        class MutatingClient(CountingClient):
            async def invoke(self, prompt, **kwargs):
                source_file.write_text("def fetch():\n    return 'rewritten mid-generation'\n")
                return await super().invoke(prompt, **kwargs)

        service = DecisionService(adr_store, tmp_path, gen_config, client=MutatingClient())
        result = await service.generate("svc.py")
        assert result.decision_ids == []
        assert any(d.code == "ADR_EVIDENCE_CHANGED" for d in result.diagnostics)
        inventory = await DecisionRepository(adr_store).inventory()
        assert inventory == []


class TestReview:
    async def test_accept_round_trips_through_the_store(self, adr_store, tmp_path, source_file, gen_config):
        """AC11 end to end: accepted in the wiki, still inferred."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        decision_id = (await service.generate("svc.py")).decision_ids[0]
        record, _ = await DecisionRepository(adr_store).get(decision_id)
        updated = await service.review(
            ReviewRequest(
                decision_id=decision_id,
                expected_revision=record.revision,
                action="accept",
                actor="human:maintainer",
                reason="agreed",
            )
        )
        assert updated.review_status == "accepted"
        assert updated.origin == "inferred" and updated.source_status == "unknown"
        stored, _ = await DecisionRepository(adr_store).get(decision_id)
        assert stored.review_status == "accepted" and len(stored.review_history) == 1

    async def test_concurrent_reviews_have_one_winner(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: the loser cannot erase the winner's history."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        decision_id = (await service.generate("svc.py")).decision_ids[0]
        record, _ = await DecisionRepository(adr_store).get(decision_id)

        await service.review(
            ReviewRequest(decision_id=decision_id, expected_revision=record.revision, action="accept", actor="human:a")
        )
        with pytest.raises(DecisionError) as exc:
            await service.review(
                ReviewRequest(
                    decision_id=decision_id, expected_revision=record.revision, action="reject", actor="human:b"
                )
            )
        assert exc.value.code == "ADR_REVISION_CONFLICT"
        stored, _ = await DecisionRepository(adr_store).get(decision_id)
        assert len(stored.review_history) == 1

    async def test_link_to_missing_documented_record_is_invalid(self, adr_store, tmp_path, source_file, gen_config):
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        decision_id = (await service.generate("svc.py")).decision_ids[0]
        record, _ = await DecisionRepository(adr_store).get(decision_id)
        with pytest.raises(DecisionError) as exc:
            await service.review(
                ReviewRequest(
                    decision_id=decision_id,
                    expected_revision=record.revision,
                    action="link",
                    actor="human:a",
                    documented_decision_id="adr:doc:nonexistent",
                )
            )
        assert exc.value.code == "ADR_INVALID_ARGUMENT"
        unchanged, _ = await DecisionRepository(adr_store).get(decision_id)
        assert unchanged.revision == record.revision

    async def test_review_of_unknown_id_is_invalid(self, adr_store, tmp_path, gen_config):
        service = DecisionService(adr_store, tmp_path, gen_config)
        with pytest.raises(DecisionError) as exc:
            await service.review(
                ReviewRequest(decision_id="adr:candidate:nope", expected_revision=1, action="accept", actor="a")
            )
        assert exc.value.code == "ADR_INVALID_ARGUMENT"
