"""Unit tests for parrot.knowledge.wiki.triage (TASK-2071, FEAT-402)."""

from pathlib import Path

import pytest
from parrot.knowledge.wiki.charter import (
    CalibrationPolicy,
    Charter,
    CharterScope,
    Thresholds,
)
from parrot.knowledge.wiki.review import Claim, DimensionScores, TriageOutput
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer


def _make_charter(admit: float = 0.75, reject: float = 0.35) -> Charter:
    return Charter(
        version="1",
        scope=CharterScope(include=[], exclude=[]),
        weights={"density": 0.4, "novelty": 0.35, "durability": 0.25},
        thresholds=Thresholds(admit=admit, reject=reject),
        calibration=CalibrationPolicy(),
    )


class FakeAdapter:
    """Stub PageIndexLLMAdapter.ask_structured — counts calls, returns canned output."""

    def __init__(self, responses: list[TriageOutput]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        response = self.responses[self.calls]
        self.calls += 1
        return response


class FakeSourceEntry:
    def __init__(self, source_id: str, source_uri: str, file_hash: str) -> None:
        self.source_id = source_id
        self.source_uri = source_uri
        self.file_hash = file_hash


class FakeSources:
    """Stub SourceCollectionManager — just enough for Stage-0 duplicate checks."""

    def __init__(self, entries: list[FakeSourceEntry] | None = None) -> None:
        self._entries = entries or []

    def find_by_uri(self, source_uri: str):
        for entry in self._entries:
            if entry.source_uri == source_uri:
                return entry.source_id
        return None

    def get_source(self, source_id: str):
        for entry in self._entries:
            if entry.source_id == source_id:
                return entry
        return None

    def list_sources(self):
        return self._entries


class FakeNoveltyScorer:
    """Stub NoveltyScorer — returns a fixed novelty value, counts calls."""

    def __init__(self, novelty: float = 0.5, backend: str = "grounding") -> None:
        self.novelty = novelty
        self.backend = backend
        self.calls = 0

    async def score(self, claims, text):
        self.calls += 1
        return self.novelty, self.backend


def _triage_output(density, novelty, durability, sensitive=False, claims=None) -> TriageOutput:
    return TriageOutput(
        briefing="A test briefing.",
        scores=DimensionScores(density=density, novelty=novelty, durability=durability),
        claims=claims or [],
        sensitive=sensitive,
    )


@pytest.fixture
def charter():
    return _make_charter(admit=0.75, reject=0.35)


class TestHeuristicRejection:
    @pytest.mark.asyncio
    async def test_router_heuristic_duplicate(self, charter):
        """A file with content matching an already-tracked hash is rejected
        with ZERO LLM calls."""
        content = "duplicate content"
        import hashlib

        file_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
        sources = FakeSources(
            entries=[FakeSourceEntry("src1", "docs/other.md", file_hash)]
        )
        adapter = FakeAdapter(responses=[])
        novelty_scorer = FakeNoveltyScorer()

        router = IngestTriageRouter(charter, adapter, sources, novelty_scorer)
        entry = await router.triage(Path("docs/new.md"), content)

        assert entry.proposed_action == "discard"
        assert entry.decision_source == "heuristic"
        assert adapter.calls == 0
        assert novelty_scorer.calls == 0

    @pytest.mark.asyncio
    async def test_router_heuristic_oversized(self, charter):
        """A document exceeding max_size_bytes is rejected with ZERO LLM calls."""
        content = "x" * 100
        adapter = FakeAdapter(responses=[])
        router = IngestTriageRouter(
            charter, adapter, FakeSources(), FakeNoveltyScorer(), max_size_bytes=50
        )
        entry = await router.triage(Path("docs/big.md"), content)

        assert entry.proposed_action == "discard"
        assert entry.decision_source == "heuristic"
        assert adapter.calls == 0

    @pytest.mark.asyncio
    async def test_router_heuristic_disallowed_suffix(self, charter):
        """A document with a disallowed suffix is rejected with ZERO LLM calls."""
        adapter = FakeAdapter(responses=[])
        router = IngestTriageRouter(
            charter,
            adapter,
            FakeSources(),
            FakeNoveltyScorer(),
            allowed_suffixes=frozenset({".md"}),
        )
        entry = await router.triage(Path("docs/binary.exe"), "some content")

        assert entry.proposed_action == "discard"
        assert entry.decision_source == "heuristic"
        assert adapter.calls == 0


class TestCompositeAndRouting:
    @pytest.mark.asyncio
    async def test_router_composite_in_code(self, charter):
        """Composite is computed in Python from charter weights, matching
        Thresholds.route boundaries."""
        # density=1.0, durability=1.0, novelty overridden to 0.5 by the
        # novelty scorer stub. weights: density=0.4, novelty=0.35, durability=0.25
        # composite = 1.0*0.4 + 0.5*0.35 + 1.0*0.25 = 0.825 -> admit (>=0.75)
        output = _triage_output(density=1.0, novelty=0.1, durability=1.0)
        adapter = FakeAdapter(responses=[output])
        novelty_scorer = FakeNoveltyScorer(novelty=0.5)

        router = IngestTriageRouter(charter, adapter, FakeSources(), novelty_scorer)
        entry = await router.triage(Path("docs/a.md"), "content")

        assert entry.composite == pytest.approx(0.825)
        assert entry.proposed_action == "admit"
        assert entry.decision_source == "model"
        assert adapter.calls == 1

    @pytest.mark.asyncio
    async def test_router_low_composite_archives(self, charter):
        """A low composite (below reject) routes to archive, not admit."""
        output = _triage_output(density=0.0, novelty=0.0, durability=0.0)
        adapter = FakeAdapter(responses=[output])
        novelty_scorer = FakeNoveltyScorer(novelty=0.0)

        router = IngestTriageRouter(charter, adapter, FakeSources(), novelty_scorer)
        entry = await router.triage(Path("docs/b.md"), "content")

        assert entry.composite == pytest.approx(0.0)
        assert entry.proposed_action == "archive"


class TestSensitive:
    @pytest.mark.asyncio
    async def test_router_sensitive_forces_discard(self, charter):
        """sensitive=True forces discard even with a high composite score."""
        output = _triage_output(density=1.0, novelty=1.0, durability=1.0, sensitive=True)
        adapter = FakeAdapter(responses=[output])
        novelty_scorer = FakeNoveltyScorer(novelty=1.0)

        router = IngestTriageRouter(charter, adapter, FakeSources(), novelty_scorer)
        entry = await router.triage(Path("docs/hr.pdf"), "content")

        assert entry.proposed_action == "discard"
        # composite is still faithfully reported for auditability, even
        # though the action is forced to discard.
        assert entry.composite == pytest.approx(1.0)
        assert entry.decision_source == "model"


class TestGrayZoneEscalation:
    @pytest.mark.asyncio
    async def test_router_gray_zone_escalates(self, charter):
        """The heavy tier is invoked ONLY for gray-band documents."""
        # Stage 1: density=0.5, durability=0.5, novelty(stub)=0.5
        # composite = 0.5*0.4 + 0.5*0.35 + 0.5*0.25 = 0.5 -> gray (0.35 <= 0.5 < 0.75)
        stage1_output = _triage_output(density=0.5, novelty=0.2, durability=0.5)
        # Stage 2 escalation resolves it upward into admit.
        stage2_output = _triage_output(density=1.0, novelty=0.2, durability=1.0)

        adapter = FakeAdapter(responses=[stage1_output])
        heavy_adapter = FakeAdapter(responses=[stage2_output])
        novelty_scorer = FakeNoveltyScorer(novelty=0.5)

        router = IngestTriageRouter(
            charter,
            adapter,
            FakeSources(),
            novelty_scorer,
            heavy_adapter=heavy_adapter,
        )
        entry = await router.triage(Path("docs/gray.md"), "content")

        assert adapter.calls == 1
        assert heavy_adapter.calls == 1
        assert entry.proposed_action == "admit"
        assert entry.composite == pytest.approx(0.825)

    @pytest.mark.asyncio
    async def test_router_admit_band_skips_heavy_tier(self, charter):
        """A clearly-admit Stage-1 composite never calls the heavy tier."""
        output = _triage_output(density=1.0, novelty=0.5, durability=1.0)
        adapter = FakeAdapter(responses=[output])
        heavy_adapter = FakeAdapter(responses=[])
        novelty_scorer = FakeNoveltyScorer(novelty=0.9)

        router = IngestTriageRouter(
            charter, adapter, FakeSources(), novelty_scorer, heavy_adapter=heavy_adapter
        )
        entry = await router.triage(Path("docs/clear.md"), "content")

        assert adapter.calls == 1
        assert heavy_adapter.calls == 0
        assert entry.proposed_action == "admit"

    @pytest.mark.asyncio
    async def test_router_reject_band_skips_heavy_tier(self, charter):
        """A clearly-reject Stage-1 composite never calls the heavy tier."""
        output = _triage_output(density=0.0, novelty=0.0, durability=0.0)
        adapter = FakeAdapter(responses=[output])
        heavy_adapter = FakeAdapter(responses=[])
        novelty_scorer = FakeNoveltyScorer(novelty=0.0)

        router = IngestTriageRouter(
            charter, adapter, FakeSources(), novelty_scorer, heavy_adapter=heavy_adapter
        )
        entry = await router.triage(Path("docs/clear2.md"), "content")

        assert adapter.calls == 1
        assert heavy_adapter.calls == 0
        assert entry.proposed_action == "archive"

    @pytest.mark.asyncio
    async def test_router_defaults_heavy_adapter_to_adapter(self, charter):
        """When heavy_adapter is not given, the router reuses `adapter`
        for both stages (constructor default)."""
        stage1_output = _triage_output(density=0.5, novelty=0.2, durability=0.5)
        stage2_output = _triage_output(density=1.0, novelty=0.2, durability=1.0)
        adapter = FakeAdapter(responses=[stage1_output, stage2_output])
        novelty_scorer = FakeNoveltyScorer(novelty=0.5)

        router = IngestTriageRouter(charter, adapter, FakeSources(), novelty_scorer)
        entry = await router.triage(Path("docs/gray2.md"), "content")

        assert router.heavy_adapter is adapter
        assert adapter.calls == 2
        assert entry.proposed_action == "admit"


class TestNoveltyScorer:
    @pytest.mark.asyncio
    async def test_novelty_fallback_no_graph(self):
        """No grounding evaluator -> search-proxy fallback, backend recorded."""

        class StubResult:
            def __init__(self, score: float) -> None:
                self.score = score

        class StubSearch:
            def __init__(self, results):
                self.results = results
                self.calls = 0

            async def search(self, query, mode="combined", top_k=10, tree_name=None, weights=None):
                self.calls += 1
                return self.results

        search = StubSearch(results=[StubResult(score=0.8), StubResult(score=0.3)])
        scorer = NoveltyScorer(grounding_evaluator=None, search=search)

        assert scorer.backend == "search-proxy"

        novelty, backend = await scorer.score(claims=[], text="some document text")

        assert backend == "search-proxy"
        assert novelty == pytest.approx(0.2)  # 1 - max(0.8, 0.3)
        assert search.calls == 1

    @pytest.mark.asyncio
    async def test_novelty_grounding_backend(self):
        """A grounding evaluator makes the primary path used, backend == 'grounding'."""

        class StubGroundingResult:
            def __init__(self, decision: str) -> None:
                self.decision = decision

        class StubGroundingEvaluator:
            def __init__(self, decisions):
                self.decisions = decisions
                self.calls = 0

            async def ground_claim(self, claim: str):
                result = StubGroundingResult(self.decisions[self.calls])
                self.calls += 1
                return result

        evaluator = StubGroundingEvaluator(decisions=["grounded", "revise"])
        scorer = NoveltyScorer(grounding_evaluator=evaluator)

        assert scorer.backend == "grounding"

        claims = [Claim(text="claim 1"), Claim(text="claim 2")]
        novelty, backend = await scorer.score(claims, text="ignored")

        assert backend == "grounding"
        assert novelty == pytest.approx(0.5)  # 1 - mean([True, False])
        assert claims[0].grounded is True
        assert claims[1].grounded is False

    @pytest.mark.asyncio
    async def test_novelty_grounding_no_claims(self):
        """No claims to ground -> treated as fully novel, no evaluator calls."""

        class StubGroundingEvaluator:
            def __init__(self):
                self.calls = 0

            async def ground_claim(self, claim: str):
                self.calls += 1
                raise AssertionError("should not be called with zero claims")

        evaluator = StubGroundingEvaluator()
        scorer = NoveltyScorer(grounding_evaluator=evaluator)

        novelty, backend = await scorer.score(claims=[], text="ignored")

        assert novelty == 1.0
        assert backend == "grounding"
        assert evaluator.calls == 0
