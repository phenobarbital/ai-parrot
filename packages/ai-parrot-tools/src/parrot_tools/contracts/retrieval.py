"""Deterministic, authorized contract retrieval (FEAT-539 M9).

Everything in this module is **LLM-free**. It classifies a question against
ten explicit patterns, resolves entities against the *authorized* catalog,
binds every AQL/SQL value itself and executes only allowlisted YAML
patterns. There is no dynamic AQL, no LLM fallback and no client.

Two rules shape the design:

* **Authorization happens before any protected read.** The gate runs on the
  trusted request context (never on a client- or model-supplied role or
  tenant) and is default-deny with ``contract_reader OR contract_owner``;
  ``my_contracts`` additionally requires an authenticated identity and
  narrows results to the caller's management chain — including the
  evidence reads that follow.
* **Uncertainty fails closed.** An unclassifiable question, an ambiguous
  entity match or a stale/incomplete graph projection returns a typed
  clarification or denial, never a guess.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.contracts.catalog import ContractCatalogStore, ObligationWindow
from parrot.knowledge.contracts.models import ContractCard, Obligation
from parrot.knowledge.contracts.standards import find_standards

__all__ = (
    "PATTERNS",
    "READ_ROLES",
    "OWNER_ROLE",
    "INTERPRETATION_MARKERS",
    "is_interpretation",
    "MAX_TOP_K",
    "DEFAULT_TOP_K",
    "FUZZY_THRESHOLD",
    "RequestContext",
    "AuthorizationDenied",
    "Clarification",
    "PatternPlan",
    "RetrievalResult",
    "ContractRetrieval",
    "classify",
)

logger = logging.getLogger(__name__)

#: The two read roles; either grants a protected read (OR semantics).
READ_ROLES: tuple[str, str] = ("contract_reader", "contract_owner")

#: The role required for owner-only administrative operations.
OWNER_ROLE = "contract_owner"

#: Hard bound on any ``top_k`` a caller (or a model) may ask for.
MAX_TOP_K = 25
DEFAULT_TOP_K = 8

#: Minimum normalized similarity for a fuzzy entity match.
FUZZY_THRESHOLD = 0.85

#: The ten allowlisted patterns, most specific trigger first.
PATTERNS: tuple[str, ...] = (
    "contracts_requiring_standard",
    "notice_deadlines_within",
    "expiring_within",
    "contract_in_force",
    "contract_family",
    "signatories_of",
    "obligations_of_contract",
    "contracts_with_party",
    "my_contracts",
    "search_contracts",
)

#: Trigger phrases per pattern, matched most-specific first. Ordering is
#: what makes "when must we give notice" resolve to notice deadlines rather
#: than to the more generic expiry window.
_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "contracts_requiring_standard",
        ("require", "requires", "required", "compliance requirement", "certified"),
    ),
    (
        "notice_deadlines_within",
        (
            "notice deadline",
            "notice period",
            "give notice",
            "by when must we",
            "auto renewal deadline",
            "auto-renew deadline",
        ),
    ),
    (
        "expiring_within",
        ("expiring", "expire", "renewal", "renew", "up for renewal", "coming up"),
    ),
    ("contract_in_force", ("in force", "as of", "before the amendment", "version in force")),
    (
        "contract_family",
        ("family", "which sows", "under the msa", "which msa governs", "related agreements"),
    ),
    ("signatories_of", ("who signed", "signatories", "signed on behalf", "who executed")),
    (
        "obligations_of_contract",
        ("obligations", "obliged", "what does the contract require", "clauses of"),
    ),
    (
        "contracts_with_party",
        ("contracts with", "agreements with", "signed with", "our contract with"),
    ),
    ("my_contracts", ("my contracts", "contracts i own", "my team's contracts")),
    ("search_contracts", ("mentions", "find the contract", "search contracts", "clause about")),
)

#: Deontic/evaluative markers: these are judgement requests, not lookups.
INTERPRETATION_MARKERS: tuple[str, ...] = (
    "should we",
    "can we",
    "may we",
    "are we allowed",
    "is it ok",
    "compliant",
    "in breach",
    "accept the redline",
    "do we have to",
    "must we agree",
    "is it legal",
    "advise",
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_DATE_RE = re.compile(r"(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
_WINDOW_RE = re.compile(r"(\d{1,4})\s*(day|days|week|weeks|month|months)")


class RequestContext(BaseModel):
    """The **trusted** identity of one request.

    Built by the transport from authenticated session data. Roles, tenant
    and employee identity are never taken from the question, the model or
    a tool argument.

    Args:
        user_id: Authenticated user identifier.
        roles: Roles granted by the transport.
        tenant_id: Tenant the request belongs to.
        employee_id: The caller's employee id, when known.
        employee_graph_id: Full ``employees/<id>`` graph id for
            ``my_contracts``.
        department: Department of the caller.
        confirmed: Whether the transport collected an explicit human
            confirmation for a write operation.
    """

    user_id: Optional[str] = None
    roles: tuple[str, ...] = ()
    tenant_id: Optional[str] = None
    employee_id: Optional[str] = None
    employee_graph_id: Optional[str] = None
    department: Optional[str] = None
    confirmed: bool = False

    @property
    def authenticated(self) -> bool:
        """True when the transport supplied an authenticated identity."""
        return bool((self.user_id or "").strip())

    def has_any_role(self, roles: Sequence[str]) -> bool:
        """Whether the context carries at least one of ``roles``."""
        return bool(set(self.roles) & set(roles))


class AuthorizationDenied(PermissionError):
    """A protected read/write was refused before it happened."""

    def __init__(self, reason: str, *, pattern: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pattern = pattern


class Clarification(BaseModel):
    """A typed request for more information — never an invented answer."""

    reason: str
    pattern: Optional[str] = None
    candidates: list[str] = Field(default_factory=list)


class PatternPlan(BaseModel):
    """A classified question with every bind value already resolved."""

    pattern: str
    binds: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, str] = Field(default_factory=dict)
    interpretation_required: bool = False


class RetrievalResult(BaseModel):
    """Deterministic retrieval output handed to the answer service."""

    pattern: str
    cards: list[ContractCard] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    binds: dict[str, Any] = Field(default_factory=dict)
    used_graph: bool = False
    notes: list[str] = Field(default_factory=list)


def _normalize(text: str) -> str:
    """Lowercase and collapse a question for trigger matching."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def classify(question: str) -> Optional[str]:
    """Return the most specific pattern a question triggers.

    Args:
        question: The user's question.

    Returns:
        The pattern name, or ``None`` when nothing matches (which fails
        closed rather than guessing).
    """
    normalized = _normalize(question)
    for pattern, triggers in _TRIGGERS:
        for trigger in triggers:
            if _normalize(trigger) in normalized:
                return pattern
    return None


def is_interpretation(question: str) -> bool:
    """Whether a question asks for judgement rather than a lookup."""
    normalized = _normalize(question)
    return any(_normalize(marker) in normalized for marker in INTERPRETATION_MARKERS)


class ContractRetrieval:
    """Authorized, deterministic retrieval over catalog and graph.

    Args:
        catalog: The tenant-bound catalog (SQL is always available).
        graph_store: Optional ``OntologyGraphStore`` for YAML patterns.
        tenant_context: Optional ``TenantContext`` for graph reads.
        ontology: Optional merged ontology supplying the allowlisted AQL.
        authorization: Optional ``AuthorizationChecker``; the local
            role gate runs regardless.
        today: Injectable clock for date windows.
        ranker: Optional non-generative ranking callable for entity
            resolution; never an LLM.
    """

    def __init__(
        self,
        *,
        catalog: ContractCatalogStore,
        graph_store: Any = None,
        tenant_context: Any = None,
        ontology: Any = None,
        authorization: Any = None,
        today: Any = None,
        ranker: Any = None,
    ) -> None:
        self.catalog = catalog
        self.graph_store = graph_store
        self.tenant_context = tenant_context
        self.ontology = ontology
        self.authorization = authorization
        self.ranker = ranker
        self._today = today or (lambda: datetime.now(tz=timezone.utc).date())

    # -- the entry gate ----------------------------------------------------

    def authorize(
        self,
        context: RequestContext,
        *,
        pattern: Optional[str] = None,
        owner_only: bool = False,
    ) -> None:
        """Run the shared entry gate **before** any protected read.

        Args:
            context: The trusted request context.
            pattern: The pattern being served, for the denial message.
            owner_only: Require the owner role (verify/merge/retire).

        Raises:
            AuthorizationDenied: On a missing identity, a foreign tenant or
                insufficient roles. Default deny.
        """
        if not context.authenticated:
            raise AuthorizationDenied("no authenticated principal", pattern=pattern)
        if context.tenant_id and context.tenant_id != self.catalog.tenant_id:
            raise AuthorizationDenied(
                f"request tenant {context.tenant_id!r} does not match this catalog",
                pattern=pattern,
            )
        if owner_only:
            if OWNER_ROLE not in context.roles:
                raise AuthorizationDenied(f"{OWNER_ROLE} is required for this operation", pattern=pattern)
            return
        if pattern == "my_contracts":
            if not (context.employee_graph_id or context.employee_id):
                raise AuthorizationDenied(
                    "my_contracts requires an authenticated employee identity",
                    pattern=pattern,
                )
            return
        if not context.has_any_role(READ_ROLES):
            raise AuthorizationDenied(f"none of {list(READ_ROLES)} granted", pattern=pattern)

    # -- entity resolution against the authorized catalog ------------------

    async def resolve_contract(
        self,
        question: str,
        context: RequestContext,
    ) -> str | Clarification:
        """Resolve a contract id or title mentioned in the question.

        Matching is exact id, then exact title, then normalized fuzzy over
        the **authorized** catalog. Several equally good matches produce a
        :class:`Clarification` — never a pick.
        """
        cards = await self._authorized_cards(context)
        normalized = _normalize(question)
        for card in cards:
            if _normalize(card.contract_id) in normalized:
                return card.contract_id
        titled = [card.contract_id for card in cards if _normalize(card.title) and _normalize(card.title) in normalized]
        if len(titled) == 1:
            return titled[0]
        if len(titled) > 1:
            # Two cards share the title the question used: only a human can
            # say which one is meant.
            return Clarification(
                reason="several contracts share that title",
                candidates=sorted(titled),
            )

        scored: list[tuple[float, str]] = []
        for card in cards:
            score = self._similarity(_normalize(card.title), normalized)
            if score >= FUZZY_THRESHOLD:
                scored.append((score, card.contract_id))
        if not scored:
            return Clarification(reason="no contract in this catalog matches the question")
        scored.sort(key=lambda item: (-item[0], item[1]))
        best = scored[0][0]
        tied = [contract_id for score, contract_id in scored if score == best]
        if len(tied) > 1:
            return Clarification(
                reason="several contracts match this description",
                candidates=sorted(tied),
            )
        return scored[0][1]

    async def resolve_party(
        self,
        question: str,
        context: RequestContext,
    ) -> str | Clarification:
        """Resolve a counterparty mentioned in the question.

        Exact name, then catalog alias, then normalized fuzzy match.
        """
        normalized = _normalize(question)
        parties = await self.catalog.list_parties()
        named = [party.party_id for party in parties if _normalize(party.name) and _normalize(party.name) in normalized]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            return Clarification(
                reason="several counterparties share that name",
                candidates=sorted(named),
            )
        aliases = await self.catalog.all_party_aliases()
        for party_id, values in sorted(aliases.items()):
            for alias in values:
                if _normalize(alias) and _normalize(alias) in normalized:
                    return party_id

        scored: list[tuple[float, str]] = []
        for party in parties:
            score = self._similarity(_normalize(party.name), normalized)
            if score >= FUZZY_THRESHOLD:
                scored.append((score, party.party_id))
        if not scored:
            return Clarification(reason="no counterparty in this catalog matches the question")
        scored.sort(key=lambda item: (-item[0], item[1]))
        best = scored[0][0]
        tied = [party_id for score, party_id in scored if score == best]
        if len(tied) > 1:
            return Clarification(
                reason="several counterparties match this description",
                candidates=sorted(tied),
            )
        return scored[0][1]

    def _similarity(self, needle: str, haystack: str) -> float:
        """Normalized similarity, optionally via a configured ranker."""
        if not needle or not haystack:
            return 0.0
        if needle in haystack:
            return 1.0
        if self.ranker is not None:
            return float(self.ranker(needle, haystack))
        try:
            from rapidfuzz import fuzz  # noqa: PLC0415 - optional dependency
        except ImportError:  # pragma: no cover - depends on install extras
            return 0.0
        return float(fuzz.partial_ratio(needle, haystack)) / 100.0

    # -- planning ----------------------------------------------------------

    async def plan(self, question: str, context: RequestContext) -> PatternPlan | Clarification:
        """Classify a question and bind every value it needs.

        Authorization for the resolved pattern runs **before** any entity
        is read out of the catalog.
        """
        if is_interpretation(question):
            return PatternPlan(pattern="interpretation", interpretation_required=True)

        pattern = classify(question)
        if pattern is None:
            return Clarification(reason="the question does not match a supported pattern")

        # Gate first: entity resolution is already a protected read.
        self.authorize(context, pattern=pattern)

        today = self._today()
        binds: dict[str, Any] = {}
        entities: dict[str, str] = {}

        if pattern == "contracts_requiring_standard":
            # Resolve aliases over the FULL question so a trigger word does
            # not erase the entity ("which contracts require SOC 2?").
            standards = find_standards(question)
            if not standards:
                return Clarification(reason="no known compliance standard was named", pattern=pattern)
            if len(standards) > 1:
                return Clarification(
                    reason="several compliance standards were named",
                    pattern=pattern,
                    candidates=standards,
                )
            binds = {"standard_id": standards[0], "statuses": ["active"]}
            entities["standard"] = standards[0]
        elif pattern in ("expiring_within", "notice_deadlines_within"):
            binds = {"today": today, "until": today + self._window(question)}
        elif pattern in (
            "contract_family",
            "signatories_of",
            "obligations_of_contract",
            "contract_in_force",
        ):
            resolved = await self.resolve_contract(question, context)
            if isinstance(resolved, Clarification):
                return resolved.model_copy(update={"pattern": pattern})
            entities["contract"] = resolved
            binds = {"contract_id": resolved}
            if pattern == "obligations_of_contract":
                # Nullable, but ALWAYS bound.
                binds["kind"] = self._obligation_kind(question)
            if pattern == "contract_in_force":
                binds["as_of"] = self._as_of(question, today)
        elif pattern == "contracts_with_party":
            resolved = await self.resolve_party(question, context)
            if isinstance(resolved, Clarification):
                return resolved.model_copy(update={"pattern": pattern})
            entities["party"] = resolved
            binds = {"party_id": resolved}
        elif pattern == "my_contracts":
            binds = {"user_id": context.employee_graph_id or f"employees/{context.employee_id}"}
        elif pattern == "search_contracts":
            binds = {"query": question, "top_k": DEFAULT_TOP_K}

        return PatternPlan(pattern=pattern, binds=binds, entities=entities)

    @staticmethod
    def _window(question: str) -> Any:
        """Extract a bounded window from the question (default 90 days)."""
        from datetime import timedelta

        match = _WINDOW_RE.search((question or "").lower())
        if not match:
            return timedelta(days=90)
        amount = min(int(match.group(1)), 3650)
        unit = match.group(2)
        if unit.startswith("week"):
            return timedelta(weeks=amount)
        if unit.startswith("month"):
            return timedelta(days=amount * 30)
        return timedelta(days=amount)

    @staticmethod
    def _as_of(question: str, today: date) -> date:
        """Extract an explicit ISO date, else use the injected today."""
        match = _DATE_RE.search(question or "")
        if not match:
            return today
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _obligation_kind(question: str) -> Optional[str]:
        """Extract a closed obligation kind, or ``None`` (bound explicitly)."""
        from parrot.knowledge.contracts.models import OBLIGATION_KINDS

        normalized = _normalize(question)
        for kind in OBLIGATION_KINDS:
            if kind == "other":
                continue
            if _normalize(kind.replace("_", " ")) in normalized:
                return kind
        return None

    # -- execution ---------------------------------------------------------

    async def retrieve(self, question: str, context: RequestContext) -> RetrievalResult | Clarification:
        """Plan and execute one deterministic retrieval.

        Returns:
            A :class:`RetrievalResult`, or a :class:`Clarification` when
            classification or entity resolution was uncertain.

        Raises:
            AuthorizationDenied: When the gate refuses the request.
        """
        plan = await self.plan(question, context)
        if isinstance(plan, Clarification):
            return plan
        if plan.interpretation_required:
            return RetrievalResult(pattern="interpretation", notes=["judgement request"])
        return await self.execute(plan, context)

    async def execute(self, plan: PatternPlan, context: RequestContext) -> RetrievalResult:
        """Execute a bound plan against SQL (always) or the graph.

        SQL is authoritative and always available: search, date windows and
        the verification queue keep working with no ArangoDB at all.
        """
        self.authorize(context, pattern=plan.pattern)
        result = RetrievalResult(pattern=plan.pattern, binds=dict(plan.binds))

        if plan.pattern == "contracts_requiring_standard":
            standard_id = plan.binds["standard_id"]
            obligations = await self.catalog.obligations_due(
                ObligationWindow(until=date.max, standard_id=standard_id, limit=200)
            )
            contract_ids = {obligation.contract_id for obligation in obligations}
            cards = [
                card
                for card in await self.catalog.list_cards()
                if card.contract_id in contract_ids and card.status in plan.binds.get("statuses", ["active"])
            ]
            result.cards = cards
            result.obligations = [
                obligation
                for obligation in obligations
                if obligation.contract_id in {card.contract_id for card in cards}
            ]
        elif plan.pattern == "expiring_within":
            result.cards = await self.catalog.expiring(
                until=plan.binds["until"], key="expiration_date", since=plan.binds["today"]
            )
        elif plan.pattern == "notice_deadlines_within":
            result.cards = await self.catalog.expiring(
                until=plan.binds["until"], key="notice_deadline", since=plan.binds["today"]
            )
        elif plan.pattern == "contracts_with_party":
            party_id = plan.binds["party_id"]
            result.cards = [
                card
                for card in await self.catalog.list_cards()
                if any(party.party_id == party_id for party in card.parties)
            ]
        elif plan.pattern in ("contract_family", "signatories_of", "contract_in_force"):
            card = await self._authorized_card(plan.binds["contract_id"], context)
            result.cards = [card]
            if plan.pattern == "contract_family":
                result.cards.extend(await self._family(card))
            if plan.pattern == "contract_in_force":
                as_of = plan.binds["as_of"]
                result.rows = [version.model_dump(mode="json") for version in card.versions if version.in_force(as_of)]
        elif plan.pattern == "obligations_of_contract":
            card = await self._authorized_card(plan.binds["contract_id"], context)
            kind = plan.binds.get("kind")
            obligations = await self.catalog.obligations_for(card.contract_id)
            result.cards = [card]
            result.obligations = [
                obligation
                for obligation in obligations
                if obligation.active and (kind is None or obligation.kind == kind)
            ]
        elif plan.pattern == "my_contracts":
            result.cards = await self._authorized_cards(context)
        elif plan.pattern == "search_contracts":
            hits = await self.catalog.search(plan.binds["query"], top_k=min(plan.binds["top_k"], MAX_TOP_K))
            allowed = {card.contract_id for card in await self._authorized_cards(context)}
            result.cards = [hit.card for hit in hits if hit.card.contract_id in allowed]
            result.rows = [
                {"contract_id": hit.card.contract_id, "rank": hit.rank}
                for hit in hits
                if hit.card.contract_id in allowed
            ]
        return result

    async def _family(self, card: ContractCard) -> list[ContractCard]:
        """Return the contract family, de-duplicated by contract identity."""
        cards = await self.catalog.list_cards()
        family: dict[str, ContractCard] = {}
        for other in cards:
            if other.contract_id == card.contract_id:
                continue
            if other.parent_contract_id == card.contract_id or (
                card.parent_contract_id and other.contract_id == card.parent_contract_id
            ):
                family[other.contract_id] = other
            elif card.parent_contract_id and other.parent_contract_id == card.parent_contract_id:
                family[other.contract_id] = other
        return [family[key] for key in sorted(family)]

    async def _authorized_cards(self, context: RequestContext) -> list[ContractCard]:
        """Every card this principal may read.

        ``my_contracts`` callers without a read role see only the contracts
        they own or that their management chain owns; the same narrowing
        applies to the evidence reads that follow.
        """
        cards = await self.catalog.list_cards()
        if context.has_any_role(READ_ROLES):
            return cards
        # Drop unknown identities: an absent employee id must never match
        # an absent owner, or every ownerless contract in the catalog
        # becomes readable by a caller who holds no roles at all.
        owned = {
            identity for identity in ({context.employee_id} | set(getattr(context, "manages", ()) or ())) if identity
        }
        if not owned:
            return []
        return [card for card in cards if card.owner_employee_id and card.owner_employee_id in owned]

    async def _authorized_card(self, contract_id: str, context: RequestContext) -> ContractCard:
        """Load one card, refusing anything outside the authorized set.

        Raises:
            AuthorizationDenied: When the card is not readable (which is
                also how a direct-tool bypass attempt is refused).
        """
        cards = {card.contract_id: card for card in await self._authorized_cards(context)}
        card = cards.get(contract_id)
        if card is None:
            raise AuthorizationDenied(f"contract {contract_id!r} is not in this principal's authorized set")
        return card

    # -- graph execution (allowlisted YAML patterns only) ------------------

    def aql_for(self, pattern: str) -> str:
        """Return the allowlisted AQL of a YAML pattern.

        Raises:
            AuthorizationDenied: For any pattern outside the allowlist.
            RuntimeError: When no ontology was configured.
        """
        if pattern not in PATTERNS:
            raise AuthorizationDenied(f"{pattern!r} is not an allowlisted pattern")
        if self.ontology is None:
            raise RuntimeError("no ontology configured for graph retrieval")
        declared = self.ontology.traversal_patterns.get(pattern)
        if declared is None:
            raise AuthorizationDenied(f"{pattern!r} is not declared in the ontology")
        return declared.query_template

    async def execute_graph(
        self,
        plan: PatternPlan,
        context: RequestContext,
        *,
        collection_binds: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Execute one allowlisted pattern against the graph.

        The projection's ``card_revision`` is validated against the
        authoritative catalog: a stale or incomplete projection fails
        closed instead of answering from it.

        Raises:
            AuthorizationDenied: When the gate refuses, the pattern is not
                allowlisted, or the projection is stale/incomplete.
            RuntimeError: When no graph store is configured.
        """
        self.authorize(context, pattern=plan.pattern)
        if self.graph_store is None:
            raise RuntimeError("no graph store configured; SQL retrieval remains available")
        aql = self.aql_for(plan.pattern)
        rows = await self.graph_store.execute_traversal(
            self.tenant_context,
            aql,
            bind_vars=dict(plan.binds),
            collection_binds=collection_binds or {},
        )
        return await self._validate_projection(rows or [])

    async def _validate_projection(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reject rows whose projected revision no longer matches the catalog."""
        for row in rows:
            contract = row.get("contract") if isinstance(row, dict) else None
            if not isinstance(contract, dict):
                continue
            if contract.get("active") is False:
                raise AuthorizationDenied(f"graph row for {contract.get('contract_id')!r} is inactive")
            contract_id = contract.get("contract_id")
            revision = contract.get("card_revision")
            if contract_id is None or revision is None:
                raise AuthorizationDenied("graph projection is incomplete; refusing to answer")
            card = await self.catalog.get(contract_id)
            if card is None or card.revision != revision:
                raise AuthorizationDenied(
                    f"graph projection of {contract_id!r} is stale "
                    f"(projected r{revision}, catalog r{card.revision if card else 'missing'})"
                )
        return rows
