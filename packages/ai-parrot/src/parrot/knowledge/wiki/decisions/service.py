"""Decision retrieval service (FEAT-578 Module 4).

Zero LLM calls on every path in this file (AC5). ``generate`` and ``review``
are declared here for a complete public surface and implemented by the
generation/review task.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from parrot.clients import AbstractClient
from parrot.knowledge.wiki.decisions.evidence import verify_freshness
from parrot.knowledge.wiki.decisions.models import (
    DecisionConfig,
    DecisionDossier,
    DecisionHit,
    DecisionRecord,
    GenerationResult,
    ReviewRequest,
    SyncResult,
)
from parrot.knowledge.wiki.decisions.render import clamp_budget, clamp_limit, pack_dossier
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.symbols import parse_sym_id

#: Lifecycle values hidden unless ``include_history=True`` (spec §2).
HISTORICAL_STATUSES = frozenset({"rejected", "deprecated", "superseded"})

#: Field weights for the ``why`` score (spec §2), highest first.
FIELD_WEIGHTS = (("title", 4), ("decision", 3), ("context", 1), ("observations", 1))

#: Small, fixed bonus for an explicit matching symbol link. Deliberately
#: smaller than any single field weight (the lowest is 1) so it can only
#: ever act as a secondary tie-break among equal token-overlap scores,
#: never override the primary "sum distinct token overlaps" ordering.
_SYMBOL_LINK_BONUS = 0.5

#: Freshness precedence, worst first (spec §2: "missing > stale > unverified
#: > current"). Used to reduce a record's evidence spans to one label.
_FRESHNESS_RANK = {"current": 0, "unverified": 1, "stale": 2, "missing": 3}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize_query(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, deduplicated."""
    return {t.lower() for t in _TOKEN_RE.findall(text)}


class DecisionService:
    """Cited decision retrieval over one namespace's ADR plane."""

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path | None,
        config: DecisionConfig,
        structural: StructuralService | None = None,
        client: AbstractClient | None = None,
    ) -> None:
        """Bind one namespace, optional local evidence root, optional client.

        Args:
            root: Local project root, or ``None`` for a store-only/remote
                namespace. ``None`` makes every freshness answer
                ``unverified`` and forbids generation (spec §2 Module 6).
            structural: Injected to avoid a service->service import cycle
                (spec §2 Module 4). ``None`` disables name-based symbol
                disambiguation; exact ``sym:`` ids still work.
            client: Present ONLY for explicit generation. Never constructed
                here — a read path that could build a client would break AC5.
        """
        self._store = store
        self._root = root
        self._config = config
        self._structural = structural
        self._client = client
        self._repo = DecisionRepository(store, max_records=config.max_records)
        self.logger = logging.getLogger(__name__)

    async def _hit_from_record(self, record: DecisionRecord, score: float) -> DecisionHit:
        """Build a labeled hit, verifying evidence freshness.

        Freshness is the WORST outcome across the record's evidence: one
        stale span makes the hit stale, because a decision cited against
        changed code is not verified (spec §2). A record with NO evidence
        at all is vacuously ``current`` when a local root is available
        (nothing on disk contradicts it) — but ``root is None`` always
        yields ``unverified``, per :func:`verify_freshness`'s own contract,
        regardless of how much evidence the record carries.
        """
        if self._root is None:
            freshness = "unverified"
        else:
            freshness = "current"
            for ref in record.evidence:
                ref_freshness, _diagnostic = await verify_freshness(self._root, ref)
                if _FRESHNESS_RANK[ref_freshness] > _FRESHNESS_RANK[freshness]:
                    freshness = ref_freshness

        return DecisionHit(
            decision_id=record.decision_id,
            revision=record.revision,
            title=record.title,
            origin=record.origin,
            source_status=record.source_status,
            review_status=record.review_status,
            freshness=freshness,
            score=score,
            decision=record.decision,
            applicability=list(record.links),
            citations=list(record.evidence),
        )

    def _visible(self, record: DecisionRecord, include_history: bool) -> bool:
        """Whether ``record`` is shown by default."""
        if include_history:
            return True
        if record.source_status in HISTORICAL_STATUSES:
            return False
        if record.origin == "inferred" and record.review_status == "rejected":
            return False
        return True

    async def _resolve_symbol(self, symbol: str) -> tuple[str | None, list[str]]:
        """Resolve ``symbol`` to one exact ``sym:`` id.

        Returns:
            ``(symbol_id, alternatives)``. A bare name resolving to several
            symbols returns ``(None, [ids])`` so the caller can answer
            ``ambiguous`` — spec §2 forbids guessing a binding.
        """
        if symbol.startswith("sym:"):
            return symbol, []
        if self._structural is None:
            return None, []
        result = await self._structural.lookup(symbol, limit=50)
        matches = [
            hit.symbol_id for hit in result.hits if hit.qualname == symbol or hit.qualname.rsplit(".", 1)[-1] == symbol
        ]
        if len(matches) == 1:
            return matches[0], []
        if len(matches) > 1:
            return None, sorted(set(matches))
        return None, []

    async def for_symbol(
        self,
        symbol: str,
        *,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = 3000,
    ) -> DecisionDossier:
        """Return cited decisions applicable to one symbol.

        Includes links that name this exact symbol AND file-scope links for
        its file, labeled separately. Applicability is never propagated
        through the call graph (spec §2, AC2).

        Returns:
            A dossier with ``status='ambiguous'`` (plus ``alternatives``)
            when a bare name matches several symbols, ``'empty'`` when
            nothing matches, ``'ok'`` otherwise.
        """
        resolved_id, alternatives = await self._resolve_symbol(symbol)
        if resolved_id is None:
            if alternatives:
                return DecisionDossier(status="ambiguous", alternatives=alternatives)
            return DecisionDossier(status="empty")

        target_ids = {resolved_id}
        try:
            rel_path, _qualname, _ordinal = parse_sym_id(resolved_id)
            target_ids.add(f"file:{rel_path}")
        except ValueError:
            pass

        inventory = await self._repo.inventory()
        documented_hits: list[DecisionHit] = []
        candidate_hits: list[DecisionHit] = []
        for record in inventory:
            if not self._visible(record, include_history):
                continue
            matching_links = [link for link in record.links if link.target_id in target_ids]
            if not matching_links:
                continue
            hit = await self._hit_from_record(record, 0.0)
            hit.applicability = matching_links
            cited_indexes = sorted({idx for link in matching_links for idx in link.evidence_indexes})
            hit.citations = [record.evidence[idx] for idx in cited_indexes if idx < len(record.evidence)]
            if record.origin == "documented":
                documented_hits.append(hit)
            else:
                candidate_hits.append(hit)

        if not documented_hits and not candidate_hits:
            return DecisionDossier(status="empty")

        return pack_dossier(
            documented_hits,
            candidate_hits,
            limit=clamp_limit(limit),
            budget_tokens=clamp_budget(budget_tokens),
            status="ok",
        )

    def _score(self, record: DecisionRecord, tokens: set[str], symbol_ids: set[str]) -> float:
        """Deterministic relevance score (spec §2).

        Distinct token overlap weighted 4/3/1/1 over title / decision /
        context / observations, then a bonus for an explicit matching
        symbol link. The caller breaks remaining ties on ``decision_id`` so
        the ordering is total and reproducible.
        """
        field_text = {
            "title": record.title,
            "decision": record.decision,
            "context": record.context,
            "observations": " ".join(record.observations),
        }
        score = 0.0
        for field, weight in FIELD_WEIGHTS:
            overlap = tokens & tokenize_query(field_text[field])
            score += weight * len(overlap)
        if symbol_ids and any(link.target_id in symbol_ids for link in record.links):
            score += _SYMBOL_LINK_BONUS
        return score

    async def why(
        self,
        question: str,
        *,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = 3000,
    ) -> DecisionDossier:
        """Return ranked decision excerpts with citations and labeled candidates.

        A natural-language question need not name a symbol. When it does,
        the same ambiguity policy as :meth:`for_symbol` applies.
        """
        tokens = tokenize_query(question)
        symbol_ids: set[str] = set()
        candidate_tokens = set(tokens)
        if question.startswith("sym:"):
            candidate_tokens.add(question)
        for candidate in candidate_tokens:
            resolved_id, _alternatives = await self._resolve_symbol(candidate)
            if resolved_id is not None:
                symbol_ids.add(resolved_id)

        inventory = await self._repo.inventory()
        hits: list[DecisionHit] = []
        for record in inventory:
            if not self._visible(record, include_history):
                continue
            score = self._score(record, tokens, symbol_ids)
            hits.append(await self._hit_from_record(record, score))

        def _group_rank(hit: DecisionHit) -> int:
            if hit.origin == "documented" and hit.freshness == "current" and hit.source_status == "accepted":
                return 0
            if hit.origin == "documented":
                return 1
            return 2

        hits.sort(key=lambda h: (_group_rank(h), -h.score, h.decision_id))
        documented_hits = [h for h in hits if h.origin == "documented"]
        candidate_hits = [h for h in hits if h.origin == "inferred"]

        if not documented_hits and not candidate_hits:
            return DecisionDossier(status="empty")

        return pack_dossier(
            documented_hits,
            candidate_hits,
            limit=clamp_limit(limit),
            budget_tokens=clamp_budget(budget_tokens),
            status="ok",
        )

    async def sync(self, paths: list[str] | None = None) -> SyncResult:
        """Refresh ADR sources. Implemented by the orchestration task."""
        raise NotImplementedError("DecisionService.sync is implemented in FEAT-578 Module 5")

    async def generate(self, target: str) -> GenerationResult:
        """Generate bounded candidates. Implemented by the generation task."""
        raise NotImplementedError("DecisionService.generate is implemented in FEAT-578 Module 5")

    async def review(self, request: ReviewRequest) -> DecisionRecord:
        """Apply an attributed review. Implemented by the review task."""
        raise NotImplementedError("DecisionService.review is implemented in FEAT-578 Module 5")
