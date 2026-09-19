"""Generation bounds, forgery rejection and failure mapping (FEAT-578 M5)."""

from __future__ import annotations

import asyncio

import pytest

from parrot.knowledge.wiki.decisions.evidence import build_evidence
from parrot.knowledge.wiki.decisions.generation import (
    build_packet,
    generate_candidates,
    recheck_evidence,
    resolve_client,
    validate_candidates,
)
from parrot.knowledge.wiki.decisions.models import (
    CandidateBatch,
    CandidateDraft,
    DecisionConfig,
    DecisionError,
    EvidenceRef,
)


class FakeClient:
    """A recording stand-in for AbstractClient. NO network calls in tests (spec §4)."""

    def __init__(self, output=None, raises: Exception | None = None, delay: float = 0.0):
        self.output = output
        self.raises = raises
        self.delay = delay
        self.calls: list[dict] = []

    async def invoke(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return type("InvokeResult", (), {"output": self.output, "model": "fake", "usage": {}})()


def _ev(path="a.py", start=1, end=2, excerpt="code") -> EvidenceRef:
    return EvidenceRef(
        page_id=f"file:{path}",
        rel_path=path,
        start_line=start,
        end_line=end,
        source_sha1="d",
        excerpt=excerpt,
        kind="code",
    )


def _cfg(**kw) -> DecisionConfig:
    return DecisionConfig(generation_enabled=True, **kw)


class TestConfiguration:
    def test_disabled_generation_is_unconfigured(self):
        with pytest.raises(DecisionError) as exc:
            resolve_client(DecisionConfig(), FakeClient())
        assert exc.value.code == "ADR_MODEL_UNCONFIGURED"

    def test_missing_env_and_client_is_unconfigured(self, monkeypatch):
        monkeypatch.delenv("WIKI_ADR_LLM", raising=False)
        with pytest.raises(DecisionError) as exc:
            resolve_client(_cfg(), None)
        assert exc.value.code == "ADR_MODEL_UNCONFIGURED"

    def test_injected_client_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("WIKI_ADR_LLM", "provider:model")
        client = FakeClient()
        assert resolve_client(_cfg(), client) is client


class TestBounds:
    def test_max_files_is_enforced(self):
        target = "sym:a.py#f"
        target_evidence = [_ev(path="a.py")]
        supplementary = [_ev(path=f"file{i}.py") for i in range(12)]
        packet, _rendered, diagnostics = build_packet(target, target_evidence + supplementary, _cfg(max_files=8))
        assert len({e.rel_path for e in packet}) <= 8
        # 1 (target) + up to 7 supplementary = 8 distinct files; 5 dropped.
        assert len(diagnostics) == 5
        assert all(d.code == "ADR_GENERATION_LIMIT" for d in diagnostics)

    def test_max_input_tokens_is_enforced(self):
        target = "sym:a.py#f"
        target_evidence = [_ev(path="a.py", excerpt="small")]
        oversized = [_ev(path=f"big{i}.py", excerpt="x " * 2000) for i in range(3)]
        packet, rendered, diagnostics = build_packet(target, target_evidence + oversized, _cfg(max_input_tokens=50))
        assert packet == target_evidence
        assert len(diagnostics) == 3

    def test_target_evidence_is_never_silently_dropped(self):
        """spec §2: trim supplementary first, then fail loudly."""
        target = "sym:a.py#f"
        target_evidence = [_ev(path="a.py", excerpt="x " * 20000)]
        with pytest.raises(DecisionError) as exc:
            build_packet(target, target_evidence, _cfg(max_input_tokens=50))
        assert exc.value.code == "ADR_GENERATION_LIMIT"

    def test_packet_indexes_are_stable(self):
        target = "sym:a.py#f"
        evidence = [_ev(path="a.py"), _ev(path="b.py"), _ev(path="c.py")]
        packet1, rendered1, _ = build_packet(target, evidence, _cfg())
        packet2, rendered2, _ = build_packet(target, evidence, _cfg())
        assert [e.rel_path for e in packet1] == [e.rel_path for e in packet2]
        assert rendered1 == rendered2


class TestValidation:
    def test_forged_index_is_rejected(self):
        """The model cannot cite evidence it was not given (AC4)."""
        batch = CandidateBatch(candidates=[CandidateDraft(decision="d", evidence_indexes=[7])])
        kept, diags = validate_candidates(batch, [_ev()], _cfg())
        assert kept == [] and diags

    def test_valid_sibling_survives_an_invalid_one(self):
        """spec §2: rejection is per candidate."""
        batch = CandidateBatch(
            candidates=[
                CandidateDraft(decision="good", evidence_indexes=[0]),
                CandidateDraft(decision="bad", evidence_indexes=[9]),
            ]
        )
        kept, diags = validate_candidates(batch, [_ev()], _cfg())
        assert [c.decision for c in kept] == ["good"] and diags

    def test_uncited_candidate_is_rejected(self):
        batch = CandidateBatch(candidates=[CandidateDraft(decision="d", evidence_indexes=[])])
        kept, diags = validate_candidates(batch, [_ev()], _cfg())
        assert kept == []
        assert len(diags) == 1
        assert diags[0].code == "ADR_INVALID_ARGUMENT"

    def test_max_candidates_is_capped(self):
        drafts = [CandidateDraft(decision=f"d{i}", evidence_indexes=[0]) for i in range(5)]
        batch = CandidateBatch(candidates=drafts)
        kept, diags = validate_candidates(batch, [_ev()], _cfg(max_candidates=3))
        assert len(kept) == 3
        assert any(d.code == "ADR_GENERATION_LIMIT" for d in diags)

    def test_model_cannot_supply_a_status_or_actor(self):
        """extra='forbid' is the mechanism (AC4)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CandidateDraft(decision="d", evidence_indexes=[0], source_status="accepted")


class TestInvocation:
    async def test_exactly_one_invocation_no_retries(self):
        """AC5: one explicit request makes at most one bounded invocation."""
        client = FakeClient(output=CandidateBatch(candidates=[CandidateDraft(decision="d", evidence_indexes=[0])]))
        await generate_candidates(client, "sym:a.py#f", [_ev()], _cfg())
        assert len(client.calls) == 1

    async def test_invocation_parameters_are_bounded(self):
        client = FakeClient(output=CandidateBatch(candidates=[]))
        await generate_candidates(client, "sym:a.py#f", [_ev()], _cfg(max_output_tokens=777))
        call = client.calls[0]
        assert call["temperature"] == 0.0
        assert call["use_tools"] is False
        assert call["max_tokens"] == 777
        assert call["output_type"] is CandidateBatch

    async def test_provider_failure_maps_to_model_failed(self):
        client = FakeClient(raises=RuntimeError("api key sk-secret-12345 rejected"))
        with pytest.raises(DecisionError) as exc:
            await generate_candidates(client, "sym:a.py#f", [_ev()], _cfg())
        assert exc.value.code == "ADR_MODEL_FAILED"

    async def test_provider_payload_is_not_leaked(self):
        """spec §2: never serialize a provider payload that may hold a secret."""
        client = FakeClient(raises=RuntimeError("api key sk-secret-12345 rejected"))
        with pytest.raises(DecisionError) as exc:
            await generate_candidates(client, "sym:a.py#f", [_ev()], _cfg())
        assert "sk-secret-12345" not in str(exc.value)

    async def test_timeout_maps_to_model_timeout(self):
        # delay (2s) deliberately exceeds timeout_seconds (1s) so this trips;
        # timeout_seconds is a bounded positive int (DecisionConfig: gt=0),
        # so the delay — not the bound — is what must be tuned to trigger it.
        client = FakeClient(output=CandidateBatch(candidates=[]), delay=2.0)
        with pytest.raises(DecisionError) as exc:
            await generate_candidates(client, "sym:a.py#f", [_ev()], _cfg(timeout_seconds=1))
        assert exc.value.code == "ADR_MODEL_TIMEOUT"


class TestEvidenceDrift:
    async def test_changed_source_blocks_the_whole_request(self, tmp_path):
        """spec §7/AC: a mid-generation build must write no candidate."""
        source_file = tmp_path / "a.py"
        source_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
        ref = build_evidence("a.py", source_file.read_text(encoding="utf-8"), "file:a.py", 1, 2, "code")

        source_file.write_text("changed1\nchanged2\nchanged3\n", encoding="utf-8")

        diagnostics = await recheck_evidence(tmp_path, [ref])
        assert len(diagnostics) == 1
        assert diagnostics[0].code == "ADR_EVIDENCE_CHANGED"

    async def test_unchanged_source_passes(self, tmp_path):
        source_file = tmp_path / "a.py"
        source_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
        ref = build_evidence("a.py", source_file.read_text(encoding="utf-8"), "file:a.py", 1, 2, "code")

        assert await recheck_evidence(tmp_path, [ref]) == []
