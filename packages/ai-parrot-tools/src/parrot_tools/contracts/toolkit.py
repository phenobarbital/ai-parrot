"""The contracts toolkit (FEAT-539 M9).

Agent-facing surface over the *same* service boundary the fixed answer flow
uses. Two rules matter here:

* **Tool metadata is not a permission.** ``requires_confirmation`` marks a
  tool for HITL in transports that honour it, but the service still checks
  the owner role and the trusted confirmation itself — a direct invocation
  cannot skip either.
* **Actor and tenant never come from a tool argument.** The toolkit is
  constructed with the trusted :class:`RequestContext`; a model can supply
  contract ids and field values, never who it is.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from parrot.knowledge.contracts.catalog import ObligationWindow
from parrot.tools.toolkit import AbstractToolkit

from .retrieval import MAX_TOP_K, ContractRetrieval, RequestContext
from .service import ContractsAnswerService

__all__ = ("MAX_SECTION_CHARS", "ContractsToolkit")

logger = logging.getLogger(__name__)

#: Hard bound on a returned section body.
MAX_SECTION_CHARS = 8_000

#: Hard bound on any list a tool returns.
MAX_ROWS = 50


class ContractsToolkit(AbstractToolkit):
    """Read and administer contracts through the shared service gate.

    Args:
        service: The shared :class:`ContractsAnswerService`.
        request_context: The **trusted** request context. Never derived
            from tool arguments.
        library: Optional contract library (evidence reads, verification).
        relations: Optional relation stage for ``related_contracts``.
        **kwargs: Forwarded to :class:`AbstractToolkit`.
    """

    name: str = "contracts"
    tool_prefix: str = "contracts"

    #: Unprefixed method names marked for human confirmation (FEAT-235).
    confirming_tools: frozenset = frozenset({"verify_card", "retire_answer"})

    exclude_tools: tuple[str, ...] = ("get_tools", "get_tools_sync")

    def __init__(
        self,
        *,
        service: ContractsAnswerService,
        request_context: RequestContext,
        library: Any = None,
        relations: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.request_context = request_context
        self.library = library
        self.relations = relations

    @property
    def retrieval(self) -> ContractRetrieval:
        """The deterministic retrieval layer behind the service."""
        return self.service.retrieval

    @property
    def catalog(self) -> Any:
        """The tenant-bound catalog."""
        return self.service.catalog

    def _gate(self, *, owner_only: bool = False) -> None:
        """Run the shared entry gate for this toolkit's request context."""
        self.retrieval.authorize(self.request_context, owner_only=owner_only)

    # -- read tools --------------------------------------------------------

    async def catalog_search(self, query: str, top_k: int = 8) -> dict[str, Any]:
        """Search the contract catalog by free text.

        Args:
            query: What to look for (title, summary, counterparty, clause).
            top_k: Maximum results (bounded by the service).

        Returns:
            Bounded contract briefs with their relevance rank.
        """
        self._gate()
        bounded = max(1, min(int(top_k), MAX_TOP_K))
        hits = await self.catalog.search(query, top_k=bounded)
        allowed = {
            card.contract_id
            for card in await self.retrieval._authorized_cards(self.request_context)
        }
        return {
            "query": query,
            "results": [
                {**hit.card.brief(), "rank": hit.rank}
                for hit in hits
                if hit.card.contract_id in allowed
            ],
        }

    async def get_card(self, contract_id: str) -> dict[str, Any]:
        """Return one contract's card.

        Args:
            contract_id: The contract to read.

        Returns:
            The card brief plus term, parties, signatories and provenance
            summary — bounded, without the full ToC or evidence bodies.
        """
        self._gate()
        card = await self.retrieval._authorized_card(contract_id, self.request_context)
        return {
            **card.brief(),
            "governing_law": card.governing_law,
            "parent_contract_id": card.parent_contract_id,
            "term": card.term.model_dump(mode="json"),
            "parties": [party.model_dump(mode="json") for party in card.parties],
            "signatories": [item.model_dump(mode="json") for item in card.signatories],
            "verification": card.verification,
            "stale_fields": list(card.stale_fields),
            "card_origin": card.card_origin,
            "revision": card.revision,
        }

    async def get_toc(self, contract_id: str) -> dict[str, Any]:
        """Return a contract's table of contents.

        Args:
            contract_id: The contract to read.

        Returns:
            Node ids, titles and page ranges — the map for ``read_section``.
        """
        self._gate()
        card = await self.retrieval._authorized_card(contract_id, self.request_context)
        return {
            "contract_id": card.contract_id,
            "toc": [entry.model_dump(mode="json") for entry in card.toc][:MAX_ROWS],
        }

    async def read_section(self, contract_id: str, node_id: str) -> dict[str, Any]:
        """Read one indexed section body.

        Retired evidence is unavailable: a node suppressed by an answer
        retirement is never returned, whichever version asks for it.

        Args:
            contract_id: The contract to read.
            node_id: The section node id.

        Returns:
            The section body, bounded, or an explicit reason.
        """
        self._gate()
        card = await self.retrieval._authorized_card(contract_id, self.request_context)
        if (card.contract_id, node_id) in await self.catalog.retired_citations():
            return {
                "contract_id": card.contract_id,
                "node_id": node_id,
                "body": None,
                "reason": "this section's evidence was retired",
            }
        if self.library is None:
            return {
                "contract_id": card.contract_id,
                "node_id": node_id,
                "body": None,
                "reason": "no contract library configured for section reads",
            }
        loader = self.library.published_loader(card.contract_id)
        from parrot.knowledge.contracts.carding import load_bodies  # noqa: PLC0415

        bodies = await load_bodies(loader, [node_id])
        body = bodies.get(node_id)
        return {
            "contract_id": card.contract_id,
            "node_id": node_id,
            "body": body[:MAX_SECTION_CHARS] if body else None,
            "reason": "" if body else "section not found",
        }

    async def obligations(
        self,
        contract_id: Optional[str] = None,
        kind: Optional[str] = None,
        standard_id: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict[str, Any]:
        """List obligations, optionally filtered.

        Args:
            contract_id: Restrict to one contract.
            kind: Restrict to one obligation kind.
            standard_id: Restrict to obligations naming a standard.
            until: ISO date bounding fixed due dates.

        Returns:
            Bounded obligation rows with their citable excerpt.
        """
        self._gate()
        if contract_id:
            card = await self.retrieval._authorized_card(contract_id, self.request_context)
            rows = [item for item in card.obligations if item.active]
            if kind:
                rows = [item for item in rows if item.kind == kind]
            if standard_id:
                rows = [item for item in rows if item.standard_id == standard_id]
        else:
            window = ObligationWindow(
                until=date.fromisoformat(until) if until else date.max,
                kinds=[kind] if kind else None,
                standard_id=standard_id,
                limit=MAX_ROWS,
            )
            allowed = {
                card.contract_id
                for card in await self.retrieval._authorized_cards(self.request_context)
            }
            rows = [
                item
                for item in await self.catalog.obligations_due(window)
                if item.contract_id in allowed
            ]
        return {
            "obligations": [item.model_dump(mode="json") for item in rows[:MAX_ROWS]]
        }

    async def expiring(self, days: int = 90, by_notice: bool = True) -> dict[str, Any]:
        """List contracts expiring (or whose notice deadline falls) soon.

        Args:
            days: Window length in days.
            by_notice: Use the notice deadline (with expiration fallback)
                instead of the expiration date.

        Returns:
            Bounded contract briefs ordered by the driving date.
        """
        self._gate()
        today = self.retrieval._today()
        cards = await self.catalog.expiring(
            until=today + timedelta(days=max(1, min(int(days), 3650))),
            key="notice_deadline" if by_notice else "expiration_date",
            since=today,
        )
        allowed = {
            card.contract_id
            for card in await self.retrieval._authorized_cards(self.request_context)
        }
        return {
            "window_days": days,
            "contracts": [
                card.brief() for card in cards if card.contract_id in allowed
            ][:MAX_ROWS],
        }

    async def verification_queue(self, limit: int = 20) -> dict[str, Any]:
        """List cards awaiting human verification, highest priority first.

        Args:
            limit: Maximum rows.

        Returns:
            Contract briefs with the reason each is queued.
        """
        self._gate()
        entries = await self.catalog.verification_queue(limit=max(1, min(int(limit), MAX_ROWS)))
        allowed = {
            card.contract_id
            for card in await self.retrieval._authorized_cards(self.request_context)
        }
        return {
            "queue": [
                {
                    "contract_id": entry.card.contract_id,
                    "title": entry.card.title,
                    "reason": entry.reason,
                    "fields": entry.fields,
                }
                for entry in entries
                if entry.card.contract_id in allowed
            ]
        }

    async def related_contracts(self, contract_id: str) -> dict[str, Any]:
        """List the family and judged relations of a contract.

        Args:
            contract_id: The contract to inspect.

        Returns:
            Family members plus active judged relations. Judgement itself
            never happens here — this only reads what was already judged.
        """
        self._gate()
        card = await self.retrieval._authorized_card(contract_id, self.request_context)
        family = await self.retrieval._family(card)
        relations = await self.catalog.active_relations(card.contract_id)
        return {
            "contract_id": card.contract_id,
            "parent_contract_id": card.parent_contract_id,
            "family": [item.brief() for item in family][:MAX_ROWS],
            "relations": [item.model_dump(mode="json") for item in relations][:MAX_ROWS],
        }

    # -- confirming write tools -------------------------------------------

    async def verify_card(
        self,
        contract_id: str,
        fields: Optional[dict[str, Any]] = None,
        merge_party_id: Optional[str] = None,
        keep_party_id: Optional[str] = None,
        owner_employee_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        """Verify/correct fields, merge parties or override ownership.

        Owner-only and confirming: the service re-checks the owner role and
        the trusted transport confirmation, so the metadata flag alone
        never authorises the write. The actor is taken from the trusted
        request context, never from an argument.

        Args:
            contract_id: The card to verify or correct.
            fields: ``path -> value`` map; ``None`` values confirm.
            merge_party_id: Party identity to fold into ``keep_party_id``.
            keep_party_id: Canonical party identity to keep.
            owner_employee_id: New owner (an ownership override).
            expected_revision: Revision the caller read.

        Returns:
            What was verified, corrected or merged.
        """
        if merge_party_id and keep_party_id:
            result = await self.service.merge_parties(
                keep_party_id, merge_party_id, request_context=self.request_context
            )
            return {"merged": result.model_dump(mode="json")}

        updates = dict(fields or {})
        if owner_employee_id is not None:
            updates["owner_employee_id"] = owner_employee_id
        result = await self.service.verify_card(
            contract_id,
            updates or None,
            request_context=self.request_context,
            expected_revision=expected_revision,
        )
        return {
            "contract_id": contract_id,
            "verified": list(result.verified),
            "corrected": list(result.corrected),
            "blockers": list(result.blockers),
            "card_verified": result.card_verified,
        }

    async def retire_answer(self, answer_id: str, reason: str) -> dict[str, Any]:
        """Retire a previously released answer and suppress its evidence.

        Owner-only and confirming, enforced by the service.

        Args:
            answer_id: The audited answer to retire.
            reason: Why it is being retired (recorded in the audit).

        Returns:
            The retirement record summary.
        """
        record = await self.service.retire_answer(
            answer_id, request_context=self.request_context, reason=reason
        )
        return {
            "answer_id": record.answer_id,
            "retired_by": record.retired_by,
            "retired_at": record.retired_at.isoformat() if record.retired_at else None,
            "reason": record.retirement_reason,
            "suppressed": sorted(
                f"{contract_id}:{node_id}"
                for contract_id, node_id in await self.catalog.retired_citations()
            ),
        }
