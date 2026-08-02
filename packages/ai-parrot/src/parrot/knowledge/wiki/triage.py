"""Ingest triage cascade + novelty scorer for supervised wiki ingestion (FEAT-402).

Implements **Module 3** of the spec (§3) — the heart of supervised
ingestion. :class:`IngestTriageRouter` runs a cheap-first cascade per
document:

- **Stage 0 (free)**: duplicate content / oversized / disallowed-suffix
  documents are rejected via :class:`~parrot.knowledge.wiki.sources.
  SourceCollectionManager` bookkeeping alone — **zero** LLM calls.
- **Stage 1 (lightweight)**: :meth:`PageIndexLLMAdapter.ask_structured`
  produces a :class:`~parrot.knowledge.wiki.review.TriageOutput`. Novelty
  is then re-scored via :class:`NoveltyScorer` (grounding-backed, never
  LLM-self-assessed), and the composite is computed **in Python** from
  the charter's weights — the LLM never emits a composite.
- **Stage 2 (gray zone only)**: the heavy tier re-scores with the
  charter's few-shot examples in the prompt; the refined score re-routes
  within the band.

Design notes:
- Async throughout; the only sync work (content hashing) is cheap enough
  to run inline (a handful of KB of already-loaded text, not disk I/O).
- Every routed :class:`~parrot.knowledge.wiki.review.ManifestDocEntry`
  carries `decision_source` so the manifest is auditable: which stage
  decided (``"heuristic"`` or ``"model"``).
- See the task's "Contract corrections" note for two intentional,
  additive resolutions of gaps between the spec's terse interface list
  and what TASK-2069/2070 actually shipped: (1) size/suffix caps are
  router constructor parameters, not charter fields (`CharterScope` only
  has include/exclude rules); (2) an optional `heavy_adapter` parameter
  supports the two distinct model tiers the cascade needs, since a single
  `PageIndexLLMAdapter` is bound to one model at construction time.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Literal

from parrot.knowledge.graphindex.grounding import GroundingEvaluator
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.charter import Charter
from parrot.knowledge.wiki.review import (
    Claim,
    DimensionScores,
    ManifestDocEntry,
    TriageOutput,
)
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.sources import SourceCollectionManager

logger = logging.getLogger(__name__)

#: Default Stage-0 size cap (5 MiB of already-loaded text content).
DEFAULT_MAX_SIZE_BYTES = 5 * 1024 * 1024

#: Default cap on claims scored per document for novelty (spec §7 risk).
DEFAULT_MAX_CLAIMS_FOR_NOVELTY = 3

#: Novelty score used when there is no signal to compute one from
#: (no claims to ground, no search results to compare against). Neutral
#: — neither confidently novel nor confidently redundant.
_NO_SIGNAL_NOVELTY = 0.5


class NoveltyScorer:
    """Grounding-first novelty scorer with a search-proxy fallback.

    Primary path: grounds each (capped) claim against the GraphIndex
    plane via :class:`GroundingEvaluator.ground_claim`; novelty is
    ``1 - mean(groundedness)`` — content that already has strong graph
    support is not novel. Falls back to a top-k similarity proxy via
    :class:`WikiCombinedSearch.search` when no graph DB is available.

    Attributes:
        grounding_evaluator: Grounding evaluator over the GraphIndex
            plane, or ``None`` when the graph DB is absent.
        search: Wiki combined search, used only by the fallback path.
        max_claims: Maximum number of claims to ground per document.
        backend: ``"grounding"`` or ``"search-proxy"`` — fixed at
            construction time based on whether ``grounding_evaluator``
            was provided, so callers can read it before triaging any
            document (e.g. to populate
            ``ManifestRunHeader.novelty_backend``).
    """

    def __init__(
        self,
        grounding_evaluator: GroundingEvaluator | None = None,
        search: WikiCombinedSearch | None = None,
        max_claims: int = DEFAULT_MAX_CLAIMS_FOR_NOVELTY,
    ) -> None:
        """Initialize the novelty scorer.

        Args:
            grounding_evaluator: Grounding evaluator to use as the
                primary backend. When ``None``, the search-proxy
                fallback is used for every call.
            search: Combined wiki search, used by the fallback path.
                Ignored when ``grounding_evaluator`` is set.
            max_claims: Maximum number of claims to ground per document
                (charter-configurable in spirit; default 3 per spec §7).
        """
        self.grounding_evaluator = grounding_evaluator
        self.search = search
        self.max_claims = max_claims
        self.backend: Literal["grounding", "search-proxy"] = (
            "grounding" if grounding_evaluator is not None else "search-proxy"
        )
        self.logger = logging.getLogger(f"{__name__}.NoveltyScorer")

    async def score(self, claims: list[Claim], text: str) -> tuple[float, str]:
        """Score novelty for a document.

        Args:
            claims: Claims extracted from the document during triage.
                Mutated in place: each claim's ``grounded`` field is
                filled in when the grounding backend is used.
            text: The full document text, used only by the search-proxy
                fallback.

        Returns:
            A ``(novelty, backend)`` tuple, where ``backend`` is
            ``"grounding"`` or ``"search-proxy"``.
        """
        if self.grounding_evaluator is not None:
            return await self._score_via_grounding(claims)
        return await self._score_via_search_proxy(text)

    async def _score_via_grounding(self, claims: list[Claim]) -> tuple[float, str]:
        """Ground each (capped) claim; novelty = 1 - mean(groundedness)."""
        capped = claims[: self.max_claims]
        if not capped:
            # No claims to check against the graph: no evidence either
            # way. Treat as fully novel rather than guessing "grounded".
            return 1.0, "grounding"

        grounded_count = 0
        for claim in capped:
            result = await self.grounding_evaluator.ground_claim(claim.text)
            is_grounded = result.decision == "grounded"
            claim.grounded = is_grounded
            if is_grounded:
                grounded_count += 1

        mean_grounded = grounded_count / len(capped)
        novelty = max(0.0, min(1.0, 1.0 - mean_grounded))
        return novelty, "grounding"

    async def _score_via_search_proxy(self, text: str) -> tuple[float, str]:
        """Top-k similarity proxy when the GraphIndex plane is absent."""
        self.logger.warning(
            "GraphIndex plane absent; falling back to WikiCombinedSearch "
            "similarity proxy for novelty scoring"
        )
        if self.search is None or not text.strip():
            return _NO_SIGNAL_NOVELTY, "search-proxy"

        results = await self.search.search(text, top_k=5)
        if not results:
            # Nothing similar found in the existing wiki: fully novel.
            return 1.0, "search-proxy"

        top_similarity = max(result.score for result in results)
        novelty = max(0.0, min(1.0, 1.0 - top_similarity))
        return novelty, "search-proxy"


def _format_scope_rules(charter: Charter) -> str:
    """Render the charter's include/exclude scope rules as prompt text."""
    included = "\n".join(
        f"  - {rule.id}: {rule.description.strip()}" for rule in charter.scope.include
    ) or "  (none)"
    excluded = "\n".join(
        f"  - {rule.id}: {rule.description.strip()}" for rule in charter.scope.exclude
    ) or "  (none)"
    return f"INCLUDE (admissible content):\n{included}\n\nEXCLUDE (never admit):\n{excluded}"


def _build_stage1_prompt(charter: Charter, content: str) -> str:
    """Build the Stage-1 (lightweight tier) triage prompt.

    A module-level, pure function (not a method) so prompt construction
    is directly unit-testable without instantiating the router.

    Args:
        charter: The editorial charter driving scope and thresholds.
        content: The document content to triage.

    Returns:
        The prompt string to send to the lightweight-tier adapter.
    """
    scope = _format_scope_rules(charter)
    return (
        "You are triaging a document for admission into a curated wiki.\n\n"
        f"Editorial scope:\n{scope}\n\n"
        "Score the document on three dimensions, each in [0, 1]:\n"
        "  - density: how much admissible content per unit of document\n"
        "  - novelty: your best guess at how much this adds beyond what "
        "the wiki likely already covers (a more reliable, grounding-backed "
        "estimate is computed separately downstream — just give your best "
        "guess here)\n"
        "  - durability: how relevant this will still be in six months\n\n"
        "Do NOT compute a combined/composite score — only the per-dimension "
        "scores matter; a human/policy layer weighs them.\n"
        "Extract a handful of short, self-contained claims (facts) from the "
        "document, each with a `text` field.\n"
        "Set sensitive=true for personal data, salaries, or individual HR "
        "matters — such content is always discarded regardless of score.\n"
        "Write a 2-3 sentence `briefing` summarizing what the document is "
        "and contains.\n\n"
        f"Document:\n{content}"
    )


def _build_stage2_prompt(
    charter: Charter, content: str, stage1_output: TriageOutput
) -> str:
    """Build the Stage-2 (heavy tier, gray-zone-only) escalation prompt.

    Includes the charter's few-shot examples as anchors, per spec §2/§7.

    Args:
        charter: The editorial charter driving scope, thresholds, and
            few-shot examples.
        content: The document content to re-triage.
        stage1_output: The Stage-1 output that landed in the gray zone,
            included as context for the re-score.

    Returns:
        The prompt string to send to the heavy-tier adapter.
    """
    if charter.examples:
        examples_text = "\n".join(
            f"  - [{example.destination or 'n/a'}] {example.summary} "
            f"— {example.why}"
            for example in charter.examples
        )
    else:
        examples_text = "  (no examples on file yet)"

    return (
        _build_stage1_prompt(charter, content)
        + "\n\nThis document was borderline on the first pass "
        f"(briefing: {stage1_output.briefing!r}). Re-score it carefully, "
        "anchoring your judgment against these past editorial decisions:\n"
        f"{examples_text}"
    )


class IngestTriageRouter:
    """Runs the cheap-first triage cascade for one document at a time.

    Attributes:
        charter: The editorial charter (scope, weights, thresholds).
        adapter: Lightweight-tier LLM adapter (Stage 1).
        sources: Source collection manager, used for Stage-0 duplicate
            detection.
        novelty_scorer: Grounding-first novelty scorer.
        heavy_adapter: Heavy-tier LLM adapter (Stage 2, gray zone only).
            Defaults to reusing ``adapter`` when not given (see the
            task's Contract corrections note — the fixed constructor
            signature carries only one ``adapter`` positional parameter).
        max_size_bytes: Stage-0 size cap.
        allowed_suffixes: Optional Stage-0 suffix allowlist (lower-cased,
            including the leading dot, e.g. ``{".md", ".txt"}``). ``None``
            disables the suffix check.
    """

    def __init__(
        self,
        charter: Charter,
        adapter: PageIndexLLMAdapter,
        sources: SourceCollectionManager,
        novelty_scorer: NoveltyScorer,
        *,
        heavy_adapter: PageIndexLLMAdapter | None = None,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
        allowed_suffixes: frozenset[str] | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            charter: The editorial charter (scope, weights, thresholds).
            adapter: Lightweight-tier LLM adapter (Stage 1).
            sources: Source collection manager for Stage-0 duplicate
                detection.
            novelty_scorer: Grounding-first novelty scorer.
            heavy_adapter: Heavy-tier LLM adapter (Stage 2). Defaults to
                ``adapter`` when omitted.
            max_size_bytes: Stage-0 size cap in bytes.
            allowed_suffixes: Optional Stage-0 suffix allowlist.
        """
        self.charter = charter
        self.adapter = adapter
        self.heavy_adapter = heavy_adapter if heavy_adapter is not None else adapter
        self.sources = sources
        self.novelty_scorer = novelty_scorer
        self.max_size_bytes = max_size_bytes
        self.allowed_suffixes = allowed_suffixes
        self.logger = logging.getLogger(f"{__name__}.IngestTriageRouter")

    async def triage(self, path: Path, content: str) -> ManifestDocEntry:
        """Triage one document through the full cascade.

        Args:
            path: Path (or path-like identifier) of the document.
            content: The already-loaded document content.

        Returns:
            A :class:`ManifestDocEntry` with ``decision=None`` (the
            manifest layer / human review fills in ``decision`` later)
            and ``proposed_action`` set to the router's best guess.
        """
        file_hash = self._hash_content(content)

        heuristic_entry = self._heuristic_reject(path, content, file_hash)
        if heuristic_entry is not None:
            return heuristic_entry

        stage1_output = await self.adapter.ask_structured(
            _build_stage1_prompt(self.charter, content), TriageOutput
        )
        stage1_output = await self._apply_novelty(stage1_output, content)
        composite = self._composite(stage1_output.scores)

        if stage1_output.sensitive:
            return self._build_entry(
                path, file_hash, stage1_output, composite, "discard", "model"
            )

        band = self.charter.thresholds.route(composite)
        final_output, final_composite = stage1_output, composite

        if band == "gray":
            stage2_output = await self.heavy_adapter.ask_structured(
                _build_stage2_prompt(self.charter, content, stage1_output),
                TriageOutput,
            )
            stage2_output = await self._apply_novelty(stage2_output, content)
            stage2_composite = self._composite(stage2_output.scores)

            if stage2_output.sensitive:
                return self._build_entry(
                    path, file_hash, stage2_output, stage2_composite, "discard", "model"
                )

            final_output, final_composite = stage2_output, stage2_composite
            band = self.charter.thresholds.route(final_composite)

        proposed_action = self._band_to_action(band)
        return self._build_entry(
            path, file_hash, final_output, final_composite, proposed_action, "model"
        )

    # ------------------------------------------------------------------
    # Stage 0 — free heuristics
    # ------------------------------------------------------------------

    def _hash_content(self, content: str) -> str:
        """SHA-1 hex digest of the content, matching
        :class:`SourceManifestEntry.file_hash`'s algorithm (sources.py).
        """
        return hashlib.sha1(content.encode("utf-8")).hexdigest()

    def _heuristic_reject(
        self, path: Path, content: str, file_hash: str
    ) -> ManifestDocEntry | None:
        """Return a heuristic-reject entry, or ``None`` to proceed to Stage 1.

        Checks size cap, suffix allowlist, then duplicate content (both
        "unchanged since last ingest" via ``find_by_uri`` and "duplicate
        content under a different path" via a full ``list_sources()``
        scan).
        """
        size_bytes = len(content.encode("utf-8"))
        if size_bytes > self.max_size_bytes:
            return self._heuristic_entry(
                path,
                file_hash,
                f"exceeds max size ({size_bytes} > {self.max_size_bytes} bytes)",
            )

        if self.allowed_suffixes is not None and path.suffix.lower() not in self.allowed_suffixes:
            return self._heuristic_entry(
                path, file_hash, f"suffix {path.suffix!r} is not in the allowed set"
            )

        existing_id = self.sources.find_by_uri(str(path))
        if existing_id is not None:
            existing_entry = self.sources.get_source(existing_id)
            if existing_entry is not None and existing_entry.file_hash == file_hash:
                return self._heuristic_entry(
                    path, file_hash, "duplicate: unchanged since last ingest"
                )

        for entry in self.sources.list_sources():
            if entry.file_hash == file_hash:
                return self._heuristic_entry(
                    path, file_hash, f"duplicate content of {entry.source_uri}"
                )

        return None

    def _heuristic_entry(
        self, path: Path, file_hash: str, reason: str
    ) -> ManifestDocEntry:
        """Build a zero-score, discard entry for a Stage-0 rejection."""
        self.logger.debug("Stage-0 heuristic reject for %s: %s", path, reason)
        zero_scores = DimensionScores(density=0.0, novelty=0.0, durability=0.0)
        return ManifestDocEntry(
            source_uri=str(path),
            file_hash=file_hash,
            briefing=f"Rejected by heuristic: {reason}",
            scores=zero_scores,
            composite=0.0,
            proposed_action="discard",
            claims=[],
            decision=None,
            decision_source="heuristic",
        )

    # ------------------------------------------------------------------
    # Stage 1 / Stage 2 helpers
    # ------------------------------------------------------------------

    async def _apply_novelty(
        self, output: TriageOutput, content: str
    ) -> TriageOutput:
        """Overwrite the LLM's self-assessed novelty with the scorer's.

        The grounding-backed (or search-proxy) novelty estimate is more
        reliable than the LLM's own guess, so it always wins.
        """
        novelty, _backend = await self.novelty_scorer.score(output.claims, content)
        output.scores.novelty = novelty
        return output

    def _composite(self, scores: DimensionScores) -> float:
        """Compute the weighted composite from the charter's weights.

        The LLM never computes this — it is always Python code, per
        spec §5 acceptance criteria.
        """
        weights = self.charter.weights
        composite = (
            scores.density * weights["density"]
            + scores.novelty * weights["novelty"]
            + scores.durability * weights["durability"]
        )
        return round(composite, 4)

    def _band_to_action(
        self, band: Literal["admit", "gray", "reject"]
    ) -> Literal["admit", "archive", "discard"]:
        """Map a threshold band to a manifest proposed_action.

        Per the spec's Component Diagram (§2 Overview):
        ``admit -> WikiIngestOrchestrator.ingest(triage=...)``,
        ``archive -> orchestrator ingest with category=ARCHIVE``,
        ``reject -> SourceCollectionManager (status="rejected") only``
        (never ingested). So ``"admit"`` maps directly, ``"reject"`` maps
        to ``"discard"`` (fixed post-review: an earlier version of this
        method mapped reject to "archive", which silently paid the full
        two-LLM-call ingestion cost the cheap-first cascade exists to
        avoid, and contradicted this exact diagram — see spec §7 risk
        "double-LLM-cost on large corpora"). Any residual ``"gray"`` left
        after Stage-2 escalation still failed to resolve it maps to
        ``"archive"`` as a middle-ground default — genuinely uncertain
        content is kept (searchable, human-reviewable) rather than
        discarded outright. An explicit ``sensitive=true`` flag (handled
        earlier in :meth:`triage`, before this method is ever called)
        always forces ``"discard"`` regardless of band.
        """
        if band == "admit":
            return "admit"
        if band == "reject":
            return "discard"
        return "archive"  # residual "gray" after Stage-2 escalation

    def _build_entry(
        self,
        path: Path,
        file_hash: str,
        triage_output: TriageOutput,
        composite: float,
        proposed_action: Literal["admit", "archive", "discard"],
        decision_source: Literal["heuristic", "model", "human", "auto"],
    ) -> ManifestDocEntry:
        """Assemble the final :class:`ManifestDocEntry` for a document."""
        return ManifestDocEntry(
            source_uri=str(path),
            file_hash=file_hash,
            briefing=triage_output.briefing,
            scores=triage_output.scores,
            composite=composite,
            proposed_action=proposed_action,
            claims=triage_output.claims,
            decision=None,
            decision_source=decision_source,
        )
