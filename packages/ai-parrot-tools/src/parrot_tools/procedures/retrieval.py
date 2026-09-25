"""Deterministic, authorized retrieval over the procedures graph (FEAT-601 M10)."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Callable, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.catalog import ManualCatalogStore
from parrot.knowledge.manuals.domain import CURATOR_ROLE as DOMAIN_CURATOR_ROLE
from parrot.knowledge.manuals.domain import TECHNICIAN_ROLE
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, ManualVersion, ProcedureRef

logger = logging.getLogger(__name__)

READ_ROLES: frozenset[str] = frozenset({TECHNICIAN_ROLE, DOMAIN_CURATOR_ROLE})
CURATOR_ROLE = DOMAIN_CURATOR_ROLE
PATTERNS: tuple[str, ...] = (
    "procedure_steps", "procedure_prerequisites", "procedures_for_equipment", "step_detail",
    "equipment_sharing_module", "procedure_in_force", "tips_for_procedure", "part_for_callout", "lookup",
)
_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("part_for_callout", ("which one is part", "qué pieza es", "cuál es la pieza", "callout")),
    ("tips_for_procedure", ("tips", "consejos", "trucos")),
    ("procedure_prerequisites", ("what do i need", "qué necesito", "prerequisites", "requisitos", "before i start")),
    ("step_detail", ("step ", "paso ", "next step", "siguiente paso")),
    ("equipment_sharing_module", ("shares", "comparte", "same module", "mismo módulo")),
    ("procedure_in_force", ("revision", "revisión", "as of", "vigente")),
    ("procedure_steps", ("how do i assemble", "how to assemble", "cómo ensamblo", "cómo se monta", "cómo instalo", "how do i install", "steps", "pasos", "procedure", "procedimiento")),
    ("procedures_for_equipment", ("procedures for", "procedimientos de", "what procedures", "qué procedimientos")),
)
_WORD_RE = re.compile(r"[\wáéíóúñü]+", re.UNICODE)
_STEP_RE = re.compile(r"(?:step|paso)\s+(\d+)", re.IGNORECASE)
_CALLOUT_RE = re.compile(r"(?:callout|pieza)\s*(\d+)", re.IGNORECASE)


class RequestContext(BaseModel):
    """The trusted identity for one request, built by the transport adapter."""

    authenticated: bool
    tenant_id: str
    user_id: str
    employee_id: str | None = None
    roles: frozenset[str] = frozenset()
    channel: str | None = None
    session_id: str | None = None
    equipment_serial: str | None = None
    equipment_model: str | None = None


class AuthorizationDenied(PermissionError):
    """A protected operation was refused before it happened."""

    def __init__(self, reason: str, *, pattern: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pattern = pattern


class Clarification(BaseModel):
    """A typed request for information that deterministic resolution lacks."""

    reason: str
    candidates: list[EquipmentRef | ProcedureRef] = Field(default_factory=list)
    pattern: str | None = None


class PatternPlan(BaseModel):
    """A classified question with its resolved graph bind values."""

    pattern: str
    bind_vars: dict[str, Any] = Field(default_factory=dict)
    manual_id: str | None = None
    procedure_id: str | None = None
    step_order: int | None = None
    as_of: date | None = None


class RetrievalResult(BaseModel):
    """Deterministic output for a single manual revision."""

    pattern: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    manual: ManualCard | None = None
    revision: ManualVersion | None = None
    fallback_sections: list[dict[str, Any]] = Field(default_factory=list)


def _normalize(text: str) -> str:
    """Lowercase and normalize word spacing for trigger matching."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def classify(question: str) -> str | None:
    """Return the first ordered trigger match, or ``None`` to fail closed."""
    normalized = f" {_normalize(question)} "
    for pattern, triggers in _TRIGGERS:
        if any(f" {_normalize(trigger)}" in normalized for trigger in triggers):
            return pattern
    return None


class ProcedureRetrieval:
    """Authorized deterministic catalog, graph, and PageIndex retrieval."""

    def __init__(self, *, catalog: ManualCatalogStore, graph_store: Any, tenant_context: Any, ontology: Any,
                 authorization: Any, pageindex: Any | None = None, today: Callable[[], date] = date.today) -> None:
        self.catalog = catalog
        self.graph_store = graph_store
        self.tenant_context = tenant_context
        self.ontology = ontology
        self.authorization = authorization
        self.pageindex = pageindex
        self._today = today
        self.logger = logging.getLogger(__name__)

    def authorize(self, context: RequestContext, *, pattern: Optional[str] = None, curator_only: bool = False) -> None:
        """Enforce authentication, matching tenant, and role access before every read."""
        if not context.authenticated or not context.user_id.strip():
            raise AuthorizationDenied("no authenticated principal", pattern=pattern)
        tenant = context.tenant_id.strip()
        if not tenant:
            raise AuthorizationDenied("request carries no tenant", pattern=pattern)
        if tenant != self.catalog.tenant_id:
            raise AuthorizationDenied(f"request tenant {tenant!r} does not match this catalog", pattern=pattern)
        if curator_only:
            if CURATOR_ROLE not in context.roles:
                raise AuthorizationDenied(f"{CURATOR_ROLE} is required for this operation", pattern=pattern)
            return
        if not set(context.roles) & READ_ROLES:
            raise AuthorizationDenied(f"none of {sorted(READ_ROLES)} granted", pattern=pattern)

    async def resolve_equipment(self, text: str, context: RequestContext) -> EquipmentRef | Clarification:
        """Resolve exactly one equipment reference through the tenant catalog."""
        self.authorize(context)
        hits = await self.catalog.resolve_equipment(text, limit=5)
        if not hits:
            return Clarification(reason="equipment not found")
        if len(hits) == 1:
            return hits[0]
        normalized = _normalize(text)
        exact = [hit for hit in hits if _normalize(hit.model) in normalized or any(_normalize(alias) in normalized for alias in hit.aliases)]
        if len(exact) == 1:
            return exact[0]
        return Clarification(reason="several equipment models match this question", candidates=list(hits))

    async def resolve_procedure(self, text: str, equipment: EquipmentRef | None,
                                context: RequestContext) -> ProcedureRef | Clarification:
        """Resolve one active procedure without allowing a caller to choose ties."""
        self.authorize(context)
        hits = await self.catalog.search(text, top_k=8)
        candidates: list[ProcedureRef] = []
        for hit in hits:
            card = hit.card
            if equipment and not any(ref.equipment_id == equipment.equipment_id for ref in card.equipment):
                continue
            for procedure in card.procedures:
                if procedure.active:
                    candidates.append(ProcedureRef(procedure_id=procedure.procedure_id, manual_id=card.manual_id,
                                                    slug=procedure.slug, title=procedure.title.value,
                                                    equipment_id=equipment.equipment_id if equipment else None))
        unique = {candidate.procedure_id: candidate for candidate in candidates}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if not unique:
            return Clarification(reason="procedure not found")
        return Clarification(reason="several procedures match this question", candidates=list(unique.values()))

    async def plan(self, question: str, context: RequestContext) -> PatternPlan | Clarification:
        """Classify and resolve every required graph bind, otherwise request clarification."""
        self.authorize(context)
        pattern = classify(question)
        if pattern is None:
            return Clarification(reason="unrecognised question", pattern=None)
        if pattern == "lookup":
            return Clarification(reason="lookup requires a manual", pattern=pattern)
        equipment = await self.resolve_equipment(question, context)
        if isinstance(equipment, Clarification):
            return equipment.model_copy(update={"pattern": pattern})
        binds: dict[str, Any] = {}
        if pattern in {"procedures_for_equipment", "equipment_sharing_module"}:
            binds["equipment_id"] = equipment.equipment_id
            return PatternPlan(pattern=pattern, bind_vars=binds, manual_id=None, as_of=self._today())
        procedure = await self.resolve_procedure(question, equipment, context)
        if isinstance(procedure, Clarification):
            return procedure.model_copy(update={"pattern": pattern})
        as_of = self._today()
        binds["procedure_id"] = procedure.procedure_id
        if pattern == "procedure_in_force":
            binds["as_of"] = as_of
        if pattern == "step_detail":
            match = _STEP_RE.search(question)
            if not match:
                return Clarification(reason="step number is required", pattern=pattern)
            order = int(match.group(1))
            card = await self.catalog.get(procedure.manual_id)
            selected = next((step for proc in (card.procedures if card else []) if proc.procedure_id == procedure.procedure_id for step in proc.steps if step.order == order), None)
            if selected is None:
                return Clarification(reason="step not found", pattern=pattern)
            binds = {"step_id": selected.identity.step_id}
            return PatternPlan(pattern=pattern, bind_vars=binds, manual_id=procedure.manual_id,
                               procedure_id=procedure.procedure_id, step_order=order, as_of=as_of)
        if pattern == "part_for_callout":
            match = _CALLOUT_RE.search(question)
            if not match:
                return Clarification(reason="callout label is required", pattern=pattern)
            return Clarification(reason="media reference is required", pattern=pattern)
        return PatternPlan(pattern=pattern, bind_vars=binds, manual_id=procedure.manual_id,
                           procedure_id=procedure.procedure_id, as_of=as_of)

    async def execute(self, plan: PatternPlan, context: RequestContext) -> RetrievalResult:
        """Run a graph plan and select the manual revision active on its effective date."""
        self.authorize(context, pattern=plan.pattern)
        if plan.pattern == "lookup":
            raise AuthorizationDenied("lookup has no graph pattern; call fallback_lookup", pattern=plan.pattern)
        rows = await self.execute_graph(plan, context)
        manual = await self.catalog.get(plan.manual_id) if plan.manual_id else None
        revision = next((item for item in (manual.versions if manual and plan.as_of else []) if item.in_force(plan.as_of)), None)
        return RetrievalResult(pattern=plan.pattern, rows=rows, manual=manual, revision=revision)

    async def execute_graph(self, plan: PatternPlan, context: RequestContext) -> list[dict[str, Any]]:
        """Authorize and execute exactly one ontology allowlisted traversal."""
        self.authorize(context, pattern=plan.pattern)
        if self.graph_store is None:
            raise RuntimeError("no graph store configured")
        rows = await self.graph_store.execute_traversal(self.tenant_context, self.aql_for(plan.pattern),
                                                        bind_vars=dict(plan.bind_vars), collection_binds={})
        result = list(rows or [])
        self._validate_projection(result, pattern=plan.pattern)
        return result

    async def fallback_lookup(self, question: str, manual_id: str, context: RequestContext) -> RetrievalResult:
        """Perform an authorized, LLM-free PageIndex search over a manual tree."""
        self.authorize(context, pattern="lookup")
        if self.pageindex is None:
            return RetrievalResult(pattern="lookup")
        sections = await self.pageindex.search(manual_id, question, top_k=5, use_llm_walk=False)
        projected = [{key: value for key, value in section.items() if key in {"node_id", "title", "page", "text", "excerpt"}}
                     for section in (sections or [])]
        return RetrievalResult(pattern="lookup", fallback_sections=projected, manual=await self.catalog.get(manual_id))

    def aql_for(self, pattern: str) -> str:
        """Return only an ontology-declared graph query, never caller-provided AQL."""
        if pattern not in PATTERNS or pattern == "lookup":
            raise AuthorizationDenied(f"{pattern!r} is not an allowlisted graph pattern", pattern=pattern)
        if self.ontology is None:
            raise RuntimeError("no ontology configured for graph retrieval")
        declared = self.ontology.traversal_patterns.get(pattern)
        if declared is None:
            raise AuthorizationDenied(f"{pattern!r} is not declared in the ontology", pattern=pattern)
        return declared.query_template

    @staticmethod
    def _validate_projection(rows: Sequence[dict[str, Any]], *, pattern: str) -> None:
        """Reject inactive traversal rows before an assembler can consume them."""
        required = {
            "procedure_steps": {"procedure", "step", "order"}, "procedure_prerequisites": {"step", "parts", "tools", "hazards"},
            "step_detail": {"step", "media", "parts", "tools", "hazards"}, "equipment_sharing_module": {"equipment", "module"},
            "procedure_in_force": {"procedure", "version"}, "tips_for_procedure": {"step", "tip"},
            "part_for_callout": {"part", "confidence", "origin"},
        }
        for row in rows:
            if row.get("active") is False or row.get("_active") is False:
                raise AuthorizationDenied("inactive graph projection", pattern=pattern)
            if pattern in required and not required[pattern].issubset(row):
                raise AuthorizationDenied("incomplete graph projection", pattern=pattern)
