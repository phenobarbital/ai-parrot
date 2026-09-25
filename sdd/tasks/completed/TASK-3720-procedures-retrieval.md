# TASK-3720: ProcedureRetrieval: authorize, resolve, plan, traverse, fallback (M10)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3701, TASK-3702
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** (first slice): the deterministic, LLM-free retrieval layer of the procedures answering pipeline — *authorize → resolve → plan → traverse*. It copies the shape of `parrot_tools.contracts.retrieval.ContractRetrieval` but with two deliberate differences:

1. **Tightened tenant gate (AC9, U5):** contracts rejects a tenant only when it is supplied *and* mismatched (`retrieval.py:305`). Here a **missing** tenant is also a denial.
2. **Procedures-shaped projection validation** and a PageIndex fallback (`answer_kind="lookup"`, G5).

This task also creates the `parrot_tools.procedures` package root (with a lazy `__getattr__` so no later task has to edit `__init__.py`) and the self-contained test doubles module `_doubles.py` that every later procedures test imports **read-only**.

Implements spec §3 M10 (`retrieval.py`), §4 tests `test_authorize_tightened_tenant_gate`, `test_classify_triggers_fail_closed`, and contributes to AC9, AC17, AC20 (serial/model fields on `RequestContext`).

---

## Scope

- Create `parrot_tools/procedures/__init__.py` with a **lazy** module-level `__getattr__` mapping every public name of `retrieval`, `assembly`, `verifier`, `service`, `toolkit`, `agent` (see blueprint `_EXPORTS`) — modules that do not exist yet simply raise `AttributeError` on access until their task lands.
- Create `parrot_tools/procedures/retrieval.py`: `READ_ROLES`, `CURATOR_ROLE`, `PATTERNS`, ordered bilingual `_TRIGGERS`, `RequestContext`, `AuthorizationDenied`, `Clarification`, `PatternPlan`, `RetrievalResult`, `classify()`, `ProcedureRetrieval` (`authorize`, `resolve_equipment`, `resolve_procedure`, `plan`, `execute`, `execute_graph`, `fallback_lookup`, `aql_for`, `_validate_projection`).
- Create the tests package `packages/ai-parrot-tools/tests/procedures/` with `__init__.py`, `_doubles.py` (fakes + builders) and `test_retrieval.py`.

**NOT in scope**: `assemble_procedure` (TASK-3721), `ProcedureVerifier` (TASK-3722), the release/audit/presign service (TASK-3723), toolkit/agent (TASK-3724/3725), CLI (TASK-3727). No `conftest.py` in `tests/procedures/` (it would make every later task exclusive). No edits to `parrot_tools/contracts/*`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/__init__.py` | CREATE | Package root, lazy `__getattr__` over all procedures submodules |
| `packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py` | CREATE | Authorization gate, trigger planner, traversal, fallback |
| `packages/ai-parrot-tools/tests/procedures/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot-tools/tests/procedures/_doubles.py` | CREATE | Self-contained fakes (catalog, graph, ontology, pageindex) + builders |
| `packages/ai-parrot-tools/tests/procedures/test_retrieval.py` | CREATE | Unit tests for this task |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging, re
from datetime import date
from typing import Any, Callable, Optional, Sequence
from pydantic import BaseModel, Field                     # pydantic v2 (verified: parrot_tools/contracts/retrieval.py:31)

# created by TASK-3699 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, ManualVersion
# created by TASK-3700 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import ProcedureRef
# created by TASK-3701 (packages/ai-parrot/src/parrot/knowledge/manuals/domain.py)
from parrot.knowledge.manuals.domain import TECHNICIAN_ROLE, CURATOR_ROLE as DOMAIN_CURATOR_ROLE
# created by TASK-3702 (packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py)
from parrot.knowledge.manuals.catalog import ManualCatalogStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py  — TEMPLATE, do not import from it
_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (...)        # line 83 — ordered, most specific first
class RequestContext(BaseModel): ...                              # line 142 — contracts uses an `authenticated` @property (170); FEAT-601 skeleton makes it a field
class AuthorizationDenied(PermissionError):                       # line 179
    def __init__(self, reason: str, *, pattern: Optional[str] = None) -> None   # line 182 — sets .reason/.pattern
def _normalize(text: str) -> str                                  # line 217 — lowercase + _WORD_RE tokens
def classify(question: str) -> Optional[str]                      # line 222 — substring triggers, returns None (fails closed)
class ContractRetrieval:                                           # line 246
    def authorize(self, context, *, pattern=None, owner_only=False) -> None   # line 282-319
        # line 305: `if context.tenant_id and context.tenant_id != self.catalog.tenant_id:` — ONLY mismatched is denied (FEAT-601 tightens this)
    async def plan(self, question, context) -> PatternPlan | Clarification     # line 431
    async def execute(self, plan, context) -> RetrievalResult                  # line 552
    def aql_for(self, pattern: str) -> str                                     # line 681 — allowlist check, then self.ontology.traversal_patterns.get(pattern).query_template
    async def execute_graph(self, plan, context, *, collection_binds=None)     # line 697 — authorize first, then graph_store.execute_traversal(tenant_context, aql, bind_vars=..., collection_binds=...)
    async def _validate_projection(self, rows)                                 # line 727 — contracts-shaped; FEAT-601 re-writes it as a staticmethod

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:
    async def execute_traversal(self, ctx: TenantContext, aql: str, bind_vars: dict[str, Any] | None = None, collection_binds=None) -> list[dict]   # line 271

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit:
    async def search(self, tree_name: str, query: str, top_k: int = 10, use_bm25: bool = True, use_llm_walk: bool = True,
                     rerank: bool = False, categories=None, metadata_filter=None) -> list[dict[str, Any]]   # line 414
    # manual_id == PageIndex tree_name (spec §2 Data Models). Pass use_llm_walk=False — retrieval is LLM-free.

# created by TASK-3702 — ManualCatalogStore (packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py)
#   tenant_id attribute; async get(manual_id); async search(query, top_k=8) -> list[SearchHit];
#   async resolve_equipment(query, *, limit=5) -> list[EquipmentRef]; async list_cards(...)
```

### Does NOT Exist
- ~~`parrot_tools.procedures`~~ — this task creates it.
- ~~`ContractRetrieval.authorize(..., curator_only=...)`~~ — contracts has `owner_only`; the procedures gate has `curator_only`.
- ~~An LLM call anywhere in retrieval~~ — retrieval is deterministic; `PageIndexToolkit.search` must be called with `use_llm_walk=False`.
- ~~`RequestContext.from_model_output` / building a context from tool arguments~~ — the context is built only by the transport adapter (TASK-3725).
- ~~`parrot.knowledge.ontology.<root> import ...`~~ — never import from the ontology package root (AC17).
- ~~`tests/procedures/conftest.py`~~ — deliberately not created; use `_doubles.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/_doubles.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_retrieval.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py#ContractRetrieval.authorize",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py#classify",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py#ContractRetrieval.execute_graph",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.execute_traversal",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.search"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Copy `ContractRetrieval` structurally (`parrot_tools/contracts/retrieval.py:246-760`): constructor stores collaborators; `authorize` is the entry gate called at the top of **every** protected read; `plan` classifies with the ordered trigger table and returns a typed `Clarification` whenever it cannot resolve every bind; `aql_for` reads `query_template` only from the ontology's allowlisted `traversal_patterns`; `execute_graph` authorizes then calls `execute_traversal` with `collection_binds`.

### Procedures-specific rules
- **Tenant gate (AC9):** deny when `not context.authenticated`, when `context.tenant_id` is empty/whitespace, when it differs from `self.catalog.tenant_id`, when no role in `READ_ROLES`, and when `curator_only` and `CURATOR_ROLE not in context.roles`.
- `READ_ROLES = frozenset({"technician", "manual_curator"})` must equal `{TECHNICIAN_ROLE, DOMAIN_CURATOR_ROLE}` from TASK-3701 — assert it in a test rather than silently diverging.
- `PATTERNS` is the fixed tuple from spec §3 M10; `"lookup"` is the PageIndex fallback and has **no** AQL (`aql_for("lookup")` raises `AuthorizationDenied`).
- `classify` fails closed (`None`) → `plan` returns `Clarification(reason="unrecognised question", pattern=None)`.
- Equipment resolution is deterministic: `catalog.resolve_equipment` (rapidfuzz under the hood, TASK-3702); 0 hits ⇒ `Clarification`; >1 hit with no exact model/alias match ⇒ `Clarification(candidates=...)`.
- `as_of` defaults to `self._today()` — procedures are bitemporal (G7); `procedure_in_force` binds it.
- `RequestContext.equipment_serial` / `equipment_model` are carried through into `PatternPlan.bind_vars` only when a pattern needs them — they are applied by `assemble_procedure` (TASK-3721), not filtered in AQL.

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py` — template (do not import from it)
- `packages/ai-parrot-tools/tests/contracts/test_retrieval.py` — in-memory doubles style
- `packages/ai-parrot-tools/src/parrot_tools/contracts/__init__.py` — package-root export style (eager there; lazy here)

---

## Implementation Blueprint

### Steps (in order)
1. Create `procedures/__init__.py` with the lazy `_EXPORTS` map — *because* TASK-3721…3725 add modules later and must never edit this file (it would create file overlaps in the task graph).
2. Write `retrieval.py` constants and models (block 1) — *because* every later M10/M11 task imports `RequestContext`, `Clarification`, `RetrievalResult` from here; the field names are fixed by the spec §3 skeleton.
3. Write `classify` and `ProcedureRetrieval.__init__`/`authorize` (block 2) — *because* the gate is the one AC9 checks and must run before any read.
4. Write resolution + `plan` (block 3), then `execute`/`execute_graph`/`fallback_lookup`/`aql_for`/`_validate_projection` (block 4).
5. Write `_doubles.py` — *because* later tasks (3721–3725, 3727, 3730) import these fakes read-only; keep them generic and data-driven (constructor-injected rows), never tailored to one test.
6. Write `test_retrieval.py` and run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/__init__.py` (CREATE)
```python
"""Procedures answering layer — retrieval, assembly, verification, release (FEAT-601).

The data plane lives in ``parrot.knowledge.manuals``; this satellite package owns
everything agent-facing. Exports are resolved lazily so importing the package never
pulls optional dependencies, and so each module can land independently.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    # retrieval (TASK-3720)
    "READ_ROLES": "retrieval", "CURATOR_ROLE": "retrieval", "PATTERNS": "retrieval",
    "RequestContext": "retrieval", "AuthorizationDenied": "retrieval", "Clarification": "retrieval",
    "PatternPlan": "retrieval", "RetrievalResult": "retrieval", "classify": "retrieval",
    "ProcedureRetrieval": "retrieval",
    # assembly (TASK-3721)
    "AssembledProcedure": "assembly", "assemble_procedure": "assembly",
    # verifier (TASK-3722)
    "ProcedureVerifier": "verifier", "VerificationOutcome": "verifier",
    # service (TASK-3723)
    "AnswerProducer": "service", "AnswerOutcome": "service", "ProceduresAnswerService": "service",
    # toolkit / guided / agent (TASK-3724, TASK-3725)
    "ProceduresToolkit": "toolkit", "ProceduresAgent": "agent", "PROCEDURES_SYSTEM_PROMPT": "agent",
    # re-export of the answer model (TASK-3700) for the public interface in spec §2
    "ProcedureAnswer": "parrot.knowledge.manuals.models",
}

__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access.

    Raises:
        AttributeError: When ``name`` is not exported (or its module has not landed yet).
    """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    target = module_name if "." in module_name else f"{__name__}.{module_name}"
    module = importlib.import_module(target)
    value = getattr(module, name)
    globals()[name] = value
    return value
```
**Why this shape**: a lazy map is the only way a package root can list names of modules that land in five later tasks without those tasks touching this file. `ModuleNotFoundError` for a not-yet-merged module is acceptable (it is a subclass of `ImportError`, surfaced on access only).

### `packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py` (CREATE) — block 1/4: constants + models
```python
"""Deterministic, authorized retrieval over the procedures graph (FEAT-601 M10).

LLM-free by construction: an ordered trigger table plans the question, the ontology's
allowlisted AQL executes it, and every protected read passes :meth:`ProcedureRetrieval.authorize`.
"""
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

READ_ROLES: frozenset[str] = frozenset({"technician", "manual_curator"})
CURATOR_ROLE: str = "manual_curator"
PATTERNS: tuple[str, ...] = (
    "procedure_steps", "procedure_prerequisites", "procedures_for_equipment", "step_detail",
    "equipment_sharing_module", "procedure_in_force", "tips_for_procedure", "part_for_callout", "lookup",
)

#: Ordered, most specific first; es/en. First match wins; no match fails closed.
_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("part_for_callout", ("which one is part", "qué pieza es", "cuál es la pieza", "callout")),
    ("tips_for_procedure", ("tips", "consejos", "trucos")),
    ("procedure_prerequisites", ("what do i need", "qué necesito", "prerequisites", "requisitos", "before i start")),
    ("step_detail", ("step ", "paso ", "next step", "siguiente paso")),
    ("equipment_sharing_module", ("shares", "comparte", "same module", "mismo módulo")),
    ("procedure_in_force", ("revision", "revisión", "as of", "vigente")),
    ("procedure_steps", ("how do i assemble", "how to assemble", "cómo ensamblo", "cómo se monta", "cómo instalo",
                         "how do i install", "steps", "pasos", "procedure", "procedimiento")),
    ("procedures_for_equipment", ("procedures for", "procedimientos de", "what procedures", "qué procedimientos")),
)
# FILL IN: finalize trigger phrases/order — bounded by spec §3 M10 (_TRIGGERS es/en) and test_classify_triggers_fail_closed;
#          a more specific pattern must precede any pattern whose triggers are substrings of it.

_WORD_RE = re.compile(r"[\wáéíóúñü]+", re.UNICODE)


class RequestContext(BaseModel):
    """The **trusted** identity of one request — built by the transport, never from model output."""

    authenticated: bool
    tenant_id: str
    user_id: str
    employee_id: str | None = None
    roles: frozenset[str] = frozenset()
    channel: str | None = None
    session_id: str | None = None
    equipment_serial: str | None = None   # Q7 — asked once per session, set via proc_set_equipment_serial
    equipment_model: str | None = None


class AuthorizationDenied(PermissionError):
    """A protected read/write was refused before it happened (default deny)."""

    def __init__(self, reason: str, *, pattern: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pattern = pattern


class Clarification(BaseModel):
    """A typed request for more information — never an invented answer."""

    reason: str
    candidates: list[EquipmentRef | ProcedureRef] = Field(default_factory=list)
    pattern: str | None = None


class PatternPlan(BaseModel):
    """A classified question with every bind value resolved."""

    pattern: str
    bind_vars: dict[str, Any] = Field(default_factory=dict)
    manual_id: str | None = None
    procedure_id: str | None = None
    step_order: int | None = None
    as_of: date | None = None


class RetrievalResult(BaseModel):
    """Deterministic retrieval output for one manual revision."""

    pattern: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    manual: ManualCard | None = None
    revision: ManualVersion | None = None
    fallback_sections: list[dict[str, Any]] = Field(default_factory=list)
```
**Why this shape**: field names are fixed by spec §3 M10; TASK-3721 (assembly) and TASK-3724/3725 construct/consume these exact models. `authenticated` is a field (not the contracts property) because the transport adapter states it explicitly.

### `retrieval.py` — block 2/4: `classify` + gate
```python
def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for trigger matching."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def classify(question: str) -> str | None:
    """Return the first pattern whose trigger occurs in ``question``; ``None`` fails closed."""
    normalized = f" {_normalize(question)} "
    for pattern, triggers in _TRIGGERS:
        for trigger in triggers:
            if f" {_normalize(trigger)}" in normalized:
                return pattern
    return None


class ProcedureRetrieval:
    """Authorized, deterministic retrieval over catalog, graph and (fallback) PageIndex.

    Args:
        catalog: Tenant-bound manual catalog (TASK-3702).
        graph_store: ``OntologyGraphStore`` (or a double with ``execute_traversal``).
        tenant_context: ``TenantContext`` for graph reads (``domain.resolve_context``).
        ontology: Merged ontology exposing ``traversal_patterns[name].query_template``.
        authorization: Optional ``AuthorizationChecker``; the local gate runs regardless.
        pageindex: Optional ``PageIndexToolkit`` for ``fallback_lookup``.
        today: Injectable clock for ``as_of``.
    """

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
        """Run the entry gate before EVERY protected read.

        Denies on: not authenticated; missing OR mismatched tenant; no ``READ_ROLES``;
        no ``CURATOR_ROLE`` when ``curator_only``.

        Raises:
            AuthorizationDenied: Default deny.
        """
        if not context.authenticated or not (context.user_id or "").strip():
            raise AuthorizationDenied("no authenticated principal", pattern=pattern)
        tenant = (context.tenant_id or "").strip()
        if not tenant:
            raise AuthorizationDenied("request carries no tenant", pattern=pattern)   # tightened vs contracts:305
        if tenant != self.catalog.tenant_id:
            raise AuthorizationDenied(f"request tenant {tenant!r} does not match this catalog", pattern=pattern)
        if curator_only:
            if CURATOR_ROLE not in context.roles:
                raise AuthorizationDenied(f"{CURATOR_ROLE} is required for this operation", pattern=pattern)
            return
        if not (set(context.roles) & READ_ROLES):
            raise AuthorizationDenied(f"none of {sorted(READ_ROLES)} granted", pattern=pattern)
        # FILL IN: optional `self.authorization` (AuthorizationChecker) consultation for pattern-level has_role
        #          rules — bounded by AC9/AC10 (OR semantics; it can only further deny, never grant past this gate)
```
**Why**: this is the single gate AC9 tests; `curator_only` replaces contracts' `owner_only`. `verification_queue_procedures` is the curator-only pattern (TASK-3701).

### `retrieval.py` — block 3/4: resolution + plan
```python
    async def resolve_equipment(self, text: str, context: RequestContext) -> EquipmentRef | Clarification:
        """Resolve equipment mentioned in ``text`` via the catalog (deterministic, rapidfuzz)."""
        self.authorize(context)
        hits = await self.catalog.resolve_equipment(text, limit=5)
        # FILL IN: 0 hits ⇒ Clarification("equipment not found"); exactly one, or one exact model/alias match ⇒ it;
        #          otherwise Clarification(candidates=hits) — bounded by spec §2 Answer ("Clarification when ambiguous")
        raise NotImplementedError

    async def resolve_procedure(self, text: str, equipment: EquipmentRef | None,
                                context: RequestContext) -> ProcedureRef | Clarification:
        """Resolve a procedure via catalog FTS (``search``) restricted to ``equipment`` when given."""
        self.authorize(context)
        hits = await self.catalog.search(text, top_k=8)
        # FILL IN: filter hits to active cards for `equipment`; collect ProcedureRef candidates (title match via
        #          catalog rank); unique ⇒ ProcedureRef; none ⇒ Clarification; many ⇒ Clarification(candidates) —
        #          bounded by G1 (the LLM never selects a procedure)
        raise NotImplementedError

    async def plan(self, question: str, context: RequestContext) -> PatternPlan | Clarification:
        """Classify ``question`` and resolve every bind; fails closed to :class:`Clarification`."""
        self.authorize(context)
        pattern = classify(question)
        if pattern is None:
            return Clarification(reason="unrecognised question", pattern=None)
        # FILL IN: resolve equipment → procedure; extract step order ("paso 3"/"step 3") for step_detail and the
        #          callout label for part_for_callout; set as_of=self._today(); build bind_vars per pattern
        #          (procedure_id, manual_id, as_of, step_order, callout) — bounded by the AQL bind names declared in
        #          procedures.ontology.yaml (TASK-3701); unresolved bind ⇒ Clarification(pattern=pattern)
        raise NotImplementedError
```
**Why**: resolution order (equipment → procedure → pattern binds) mirrors contracts `plan` (431-494); every ambiguity returns a typed `Clarification` so the LLM never picks.

### `retrieval.py` — block 4/4: execution
```python
    async def execute(self, plan: PatternPlan, context: RequestContext) -> RetrievalResult:
        """Run ``plan`` against the graph and attach the selected manual revision."""
        self.authorize(context, pattern=plan.pattern)
        if plan.pattern == "lookup":
            raise AuthorizationDenied("lookup has no graph pattern; call fallback_lookup", pattern=plan.pattern)
        rows = await self.execute_graph(plan, context)
        manual = await self.catalog.get(plan.manual_id) if plan.manual_id else None
        # FILL IN: select the ManualVersion in force at plan.as_of (ManualVersion.in_force) — bounded by G7
        #          (valid_from inclusive / valid_to exclusive); none in force ⇒ revision=None
        revision: ManualVersion | None = None
        return RetrievalResult(pattern=plan.pattern, rows=rows, manual=manual, revision=revision)

    async def execute_graph(self, plan: PatternPlan, context: RequestContext) -> list[dict[str, Any]]:
        """Execute one allowlisted pattern; authorize first."""
        self.authorize(context, pattern=plan.pattern)
        if self.graph_store is None:
            raise RuntimeError("no graph store configured")
        aql = self.aql_for(plan.pattern)
        rows = await self.graph_store.execute_traversal(self.tenant_context, aql, bind_vars=dict(plan.bind_vars),
                                                        collection_binds={})
        rows = list(rows or [])
        self._validate_projection(rows, pattern=plan.pattern)
        return rows

    async def fallback_lookup(self, question: str, manual_id: str, context: RequestContext) -> RetrievalResult:
        """PageIndex search over the manual tree → ``lookup`` result with page citations."""
        self.authorize(context, pattern="lookup")
        if self.pageindex is None:
            return RetrievalResult(pattern="lookup")
        sections = await self.pageindex.search(manual_id, question, top_k=5, use_llm_walk=False)
        # FILL IN: keep node_id/title/page/text excerpt per section — bounded by G5 ("not a verified procedure" line
        #          is rendered by the service, not here)
        return RetrievalResult(pattern="lookup", fallback_sections=list(sections or []),
                               manual=await self.catalog.get(manual_id))

    def aql_for(self, pattern: str) -> str:
        """Return the allowlisted AQL of a YAML pattern (``lookup`` has none)."""
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
        """Reject inactive or incomplete rows (fail closed)."""
        # FILL IN: per pattern, require the projected keys (e.g. procedure_steps rows carry step_id, order, text,
        #          node_id); any row with active is False ⇒ AuthorizationDenied — bounded by the query_template
        #          RETURN shapes in procedures.ontology.yaml (TASK-3701)
        return None
```
**Why**: `lookup` is explicitly excluded from the AQL allowlist (it is a PageIndex read). `execute_traversal` signature verified at `graph_store.py:271`.

### `packages/ai-parrot-tools/tests/procedures/__init__.py` (CREATE)
```python
"""Tests for the procedures answering layer (FEAT-601)."""
```

### `packages/ai-parrot-tools/tests/procedures/_doubles.py` (CREATE)
```python
"""Self-contained test doubles for the procedures suites (FEAT-601).

Imported READ-ONLY by later tasks' tests — never add task-specific behaviour here; inject data instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from parrot_tools.procedures.retrieval import RequestContext

TENANT = "t1"


def make_context(*, roles: tuple[str, ...] = ("technician",), tenant_id: str = TENANT, authenticated: bool = True,
                 user_id: str = "u1", employee_id: Optional[str] = "e1", **extra: Any) -> RequestContext:
    """Build a trusted request context (authenticated technician on tenant ``t1`` by default)."""
    return RequestContext(authenticated=authenticated, tenant_id=tenant_id, user_id=user_id, employee_id=employee_id,
                          roles=frozenset(roles), **extra)


@dataclass
class FakePattern:
    """Stand-in for ``TraversalPattern`` — only ``query_template`` is read."""

    query_template: str


@dataclass
class FakeOntology:
    """Exposes ``traversal_patterns`` like the merged ontology."""

    traversal_patterns: dict[str, FakePattern] = field(default_factory=dict)


@dataclass
class FakeGraphStore:
    """Returns scripted rows per AQL string and records every call."""

    rows_by_aql: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def execute_traversal(self, ctx: Any, aql: str, bind_vars: Optional[dict[str, Any]] = None,
                                collection_binds: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
        self.calls.append((aql, dict(bind_vars or {})))
        return list(self.rows_by_aql.get(aql, []))


class FakeCatalog:
    """Duck-typed in-memory ``ManualCatalogStore`` (tenant-bound, audit recording)."""

    def __init__(self, *, tenant_id: str = TENANT, cards: Optional[list[Any]] = None, equipment: Optional[list[Any]] = None,
                 fail_audit: bool = False) -> None:
        self.tenant_id = tenant_id
        self.cards = {card.manual_id: card for card in (cards or [])}
        self.equipment = list(equipment or [])
        self.fail_audit = fail_audit
        self.answers: list[Any] = []

    async def get(self, manual_id: str) -> Any:
        return self.cards.get(manual_id)

    async def list_cards(self, **_: Any) -> list[Any]:
        return list(self.cards.values())

    async def search(self, query: str, top_k: int = 8) -> list[Any]:
        # FILL IN: return SearchHit-like objects (card, rank, matched) over titles/procedure titles — bounded by the
        #          SearchHit model from TASK-3702 (reuse it, do not redefine)
        return []

    async def resolve_equipment(self, query: str, *, limit: int = 5) -> list[Any]:
        needle = query.lower()
        return [e for e in self.equipment if e.model.lower() in needle or any(a.lower() in needle for a in e.aliases)][:limit]

    async def record_answer(self, record: Any) -> None:
        if self.fail_audit:
            raise RuntimeError("audit store unavailable")
        self.answers.append(record)


class FakePageIndex:
    """Scripted ``PageIndexToolkit.search``."""

    def __init__(self, sections: Optional[list[dict[str, Any]]] = None) -> None:
        self.sections = list(sections or [])
        self.calls: list[dict[str, Any]] = []

    async def search(self, tree_name: str, query: str, top_k: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"tree_name": tree_name, "query": query, **kwargs})
        return list(self.sections)

# FILL IN: `make_card(...)` / `make_step(...)` builders producing a valid ManualCard with one 5-step assembly
#          procedure (evidence quotes, one primary figure MediaRef with storage_key, one hazard) and matching
#          `procedure_steps` traversal rows — bounded by the TASK-3699/3700 model validators (Step requires
#          substantiated evidence; MediaRef never stores a URL)
```
**Why**: later tests (assembly, verifier, service, toolkit, agent, CLI, e2e) share these without a `conftest.py`, keeping every task parallel-safe.

### `packages/ai-parrot-tools/tests/procedures/test_retrieval.py` (CREATE)
See Test Specification below — write it verbatim as the starting point and complete the FILL IN bodies.

### FILL IN checklist
- [ ] `retrieval.py::_TRIGGERS` — final es/en phrases and order; bounded by test_classify_triggers_fail_closed
- [ ] `ProcedureRetrieval.authorize` — optional `AuthorizationChecker` consultation; can only deny (AC9/AC10)
- [ ] `resolve_equipment` / `resolve_procedure` — ambiguity ⇒ `Clarification`; bounded by G1
- [ ] `plan` — bind extraction per pattern; bounded by TASK-3701 query_template bind names
- [ ] `execute` — in-force `ManualVersion` selection; bounded by G7
- [ ] `fallback_lookup` — section projection; bounded by G5
- [ ] `_validate_projection` — required keys per pattern; bounded by TASK-3701 RETURN shapes
- [ ] `_doubles.py::FakeCatalog.search`, `make_card`/`make_step` — bounded by TASK-3699/3700/3702 models

---

## Acceptance Criteria

- [ ] Missing tenant (`""`), mismatched tenant, unauthenticated, no read role ⇒ `AuthorizationDenied`; `curator_only` requires `manual_curator` (AC9).
- [ ] `READ_ROLES == {TECHNICIAN_ROLE, DOMAIN_CURATOR_ROLE}` from TASK-3701.
- [ ] Unknown phrasing ⇒ `plan` returns `Clarification`; es and en triggers map to the same pattern.
- [ ] `aql_for` refuses any pattern outside `PATTERNS`, refuses `lookup`, and reads only the ontology's `query_template`.
- [ ] `execute_graph` authorizes before the traversal call (a denied context makes **zero** `execute_traversal` calls).
- [ ] `fallback_lookup` calls `PageIndexToolkit.search` with `use_llm_walk=False` and is gated.
- [ ] No module in `parrot_tools/procedures/` imports from `parrot.knowledge.ontology` package root (AC17).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/procedures` and `black --check` pass.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_retrieval.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_retrieval.py
import pytest

from parrot_tools.procedures.retrieval import (
    READ_ROLES, AuthorizationDenied, Clarification, ProcedureRetrieval, classify,
)
from parrot.knowledge.manuals.domain import CURATOR_ROLE, TECHNICIAN_ROLE

from ._doubles import FakeCatalog, FakeGraphStore, FakeOntology, FakePageIndex, FakePattern, make_context


def _retrieval(**kw):
    return ProcedureRetrieval(catalog=kw.pop("catalog", FakeCatalog()), graph_store=kw.pop("graph", FakeGraphStore()),
                              tenant_context=None, ontology=kw.pop("ontology", FakeOntology()), authorization=None, **kw)


class TestAuthorizeTightenedTenantGate:
    def test_authorize_tightened_tenant_gate(self):
        r = _retrieval()
        r.authorize(make_context())
        for ctx in (make_context(tenant_id=""), make_context(tenant_id="t2"), make_context(roles=()),
                    make_context(authenticated=False)):
            with pytest.raises(AuthorizationDenied):
                r.authorize(ctx)

    def test_curator_only(self):
        r = _retrieval()
        with pytest.raises(AuthorizationDenied):
            r.authorize(make_context(), curator_only=True)
        r.authorize(make_context(roles=("manual_curator",)), curator_only=True)

    def test_read_roles_match_domain(self):
        assert READ_ROLES == frozenset({TECHNICIAN_ROLE, CURATOR_ROLE})


class TestClassify:
    def test_classify_triggers_fail_closed(self):
        assert classify("¿Cómo ensamblo el modelo X?") == "procedure_steps"
        assert classify("How do I assemble model X?") == "procedure_steps"
        assert classify("¿Qué necesito antes de empezar?") == "procedure_prerequisites"
        assert classify("tell me a joke") is None

    async def test_plan_unknown_is_clarification(self):
        assert isinstance(await _retrieval().plan("tell me a joke", make_context()), Clarification)


class TestGraph:
    def test_aql_for_allowlist(self):
        r = _retrieval(ontology=FakeOntology({"procedure_steps": FakePattern("FOR s IN step RETURN s")}))
        assert r.aql_for("procedure_steps").startswith("FOR")
        for bad in ("lookup", "drop_everything"):
            with pytest.raises(AuthorizationDenied):
                r.aql_for(bad)

    async def test_execute_graph_denies_before_traversal(self):
        graph = FakeGraphStore()
        r = _retrieval(graph=graph)
        # FILL IN: build a PatternPlan; call execute_graph with make_context(tenant_id="") and assert graph.calls == []
        ...

    async def test_fallback_lookup_is_llm_free_and_gated(self):
        pi = FakePageIndex([{"node_id": "n1", "title": "Assembly", "page": 3}])
        r = _retrieval(pageindex=pi)
        result = await r.fallback_lookup("torque for bolt", "m1", make_context())
        assert result.pattern == "lookup" and pi.calls[0]["use_llm_walk"] is False
        with pytest.raises(AuthorizationDenied):
            await r.fallback_lookup("q", "m1", make_context(roles=()))
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3720
- Feature: training-agent
- Implementation SHA: bee063ebb124f7c073c639dc455887463f539203
- Closed at (UTC): 2026-09-25T16:16:08+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 295.99s · Tokens: n/a |
| supplementary_test_evidence | 8 passed, 0 failed (scoped direct pytest over ai-parrot-tools/tests/procedures/) |
