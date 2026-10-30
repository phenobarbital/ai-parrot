"""Expert-facing tools: retrieval fan-out and ADR proposal (FEAT-778 M9)."""

from __future__ import annotations

from typing import Any

from parrot.experts.models import ExpertCapabilityError, ExpertManifest, KnowledgeContext
from parrot.tools.toolkit import AbstractToolkit


def _as_hits(payload: Any) -> list[Any]:
    """Normalize a backend payload into a list of hit items."""
    if isinstance(payload, dict):
        for key in ("results", "hits", "books"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    if isinstance(payload, list):
        return payload
    return [] if payload is None else [payload]


class ExpertKnowledgeToolkit(AbstractToolkit):
    """Search an expert's knowledge handles and propose ADRs for human review."""

    tool_prefix = "expert"

    def __init__(
        self,
        context: KnowledgeContext,
        manifest: ExpertManifest,
        *,
        wiki: Any = None,
        bookstore: Any = None,
        decisions: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._context = context
        self._manifest = manifest
        self._wiki = wiki
        self._bookstore = bookstore
        self._decisions = decisions

    async def knowledge_search(self, question: str, top_k: int = 8) -> dict[str, Any]:
        """Search this expert's knowledge: its wiki namespace and the bookstore.

        Returns hits tagged with the source and revision of the knowledge layer they came from;
        a backend that fails is reported under `errors` instead of aborting the search.

        Args:
            question: Natural-language question to search for.
            top_k: Maximum number of hits to return.
        """
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for layer in self._context.retrieval_handles():
            handle = layer.handle or {}
            try:
                if layer.source == "wiki" or layer.source.startswith("wiki:"):
                    if self._wiki is None:
                        raise RuntimeError("no wiki toolkit configured")
                    payload = await self._wiki.query(wiki_name=handle["wiki_name"], question=question)
                elif layer.source == "bookstore":
                    if self._bookstore is None:
                        raise RuntimeError("no bookstore toolkit configured")
                    payload = await self._bookstore.search(question, max_books=3)
                else:
                    continue
            except Exception as exc:  # noqa: BLE001 - backend failures are reported, never raised
                errors.append(f"{layer.source}: {exc}")
                continue
            for hit in _as_hits(payload):
                results.append({"source": layer.source, "revision": layer.revision, "hit": hit})
        return {"question": question, "results": results[:top_k], "errors": errors}

    async def propose_adr(self, target: str, rationale: str) -> dict[str, Any]:
        """Propose an architecture decision record for `target`.

        The record is born inferred and unreviewed; only a human review accepts it.

        Args:
            target: What the decision is about.
            rationale: Why the decision is proposed.
        """
        if "write" not in self._manifest.capabilities:
            raise ExpertCapabilityError(f"expert {self._manifest.name} lacks the 'write' capability")
        if self._decisions is None:
            raise ExpertCapabilityError("no DecisionService configured for this expert")
        result = await self._decisions.generate(target)
        return {
            "target": target,
            "rationale": rationale,
            "decision_ids": list(result.decision_ids),
            "reused": list(result.reused),
            "origin": "inferred",
            "review_status": "unreviewed",
        }
