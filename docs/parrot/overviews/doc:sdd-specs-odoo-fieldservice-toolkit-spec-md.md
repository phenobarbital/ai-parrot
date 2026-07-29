---
type: Wiki Overview
title: 'Feature Specification: OdooFieldServiceToolkit'
id: doc:sdd-specs-odoo-fieldservice-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Field-service reps (e.g. vending/kiosk route reps) execute a daily route
  in
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
- concept: mod:parrot_tools.odoo.models.entities
  rel: mentions
- concept: mod:parrot_tools.odoo.models.inputs
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: OdooFieldServiceToolkit

**Feature ID**: FEAT-216
**Date**: 2026-06-02
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

> Source proposal: `sdd/proposals/odoo-fieldservice-toolkit.proposal.md`
> Research audit: `sdd/state/FEAT-216/`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Field-service reps (e.g. vending/kiosk route reps) execute a daily route in
Odoo built on the OCA `fieldservice` + `fieldservice_stock` stack, where Odoo
is the system of record. The generic `OdooToolkit` exposes raw CRUD over any
model, but a rep's agent needs **task-shaped, domain tools** that map to the
real route workflow: see today's orders in route sequence, load the truck,
visit kiosks, draft returns, and validate the loading pick / returns under
manager authorization. Building these on top of generic `search_records` /
`create_record` calls would push fragile Odoo domain logic into prompts.

This feature adds an `OdooFieldServiceToolkit` — a thin **enrichment** layer
of 8 purpose-built `@tool`s over the existing `OdooToolkit`, reusing its
transport, auth, RPC chokepoint, decorators, and Pydantic model layout.

### Goals

- **G1**: Expose 8 FSM domain tools: `get_today_fsos`, `get_loading_summary`,
  `get_kiosk`, `create_return_draft`, `validate_loading_pick`,
  `validate_returns`, `get_return_summary`, `complete_fso`.
- **G2**: Subclass `OdooToolkit` so the toolkit inherits all transport/auth
  plumbing and reuses `_execute` for every Odoo RPC call.
- **G3**: Add typed Pydantic models for `fsm.order` / `fsm.location` and the
  tools' inputs/result envelopes, following the existing three-module split.
- **G4**: Gate write/confirm tools with the appropriate HITL level — `rep
  confirm` via the existing `HumanInteractionManager` (`InteractionType.APPROVAL`),
  and `manager PIN` via a numeric PIN verified against Odoo.
- **G5**: Register `fsm.order` / `fsm.location` as known models so
  `list_models` and permission checks see them.

### Non-Goals (explicitly out of scope)

- No changes to the Odoo transport layer (json2/jsonrpc/xmlrpc) or
  `_ensure_transport` auth flow.
- No modification of the inherited generic CRUD / partner / sales / invoice
  tools — they are inherited as-is and remain exposed (see §8, resolved).
- No Odoo-side installation or customization of OCA modules — the
  `fieldservice` / `fieldservice_stock` modules are assumed present on the
  target instance.
- No new HITL channel rendering — the existing Telegram ✅/❌ approval UI is
  reused, not extended.
- Tool-surface narrowing via `get_tools_filtered` was considered and **rejected**
  in the proposal (resolved: subclass + expose all). It may be revisited later
  if the surface proves too broad.

---

## 2. Architectural Design

### Overview

`OdooFieldServiceToolkit(OdooToolkit)` is a subclass that adds 8 `async`
methods, each decorated with `@tool_schema(<Input>)` (and `@requires_permission`
where it writes). Because `AbstractToolkit.get_tools()` discovers tools by
runtime reflection over `async def` instance methods, the subclass
**automatically registers its new methods as tools and inherits all parent
tools** — no manual registration. All Odoo I/O routes through the inherited
`OdooToolkit._execute(model, method, args, kwargs)` chokepoint, exactly as
`confirm_sale_order` calls `self._execute("sale.order", "action_confirm", ...)`.

HITL mapping (resolved in proposal):
- **`rep confirm`** (`create_return_draft`, `complete_fso`) → request a boolean
  approval via the process-wide `HumanInteractionManager` using
  `InteractionType.APPROVAL` before performing the write.
- **`manager PIN`** (`validate_loading_pick`, `validate_returns`) → the `pin`
  argument is a real numeric secret verified against Odoo (e.g. an
  `res.users`/`hr.employee` credential check via an Odoo RPC) before the
  picking validation proceeds. The PIN must never be logged.

### Component Diagram
```
Rep Agent
   │  (tool call)
   ▼
OdooFieldServiceToolkit(OdooToolkit)
   ├── get_today_fsos / get_loading_summary / get_kiosk / get_return_summary   (read)
   ├── create_return_draft / complete_fso        ──► HumanInteractionManager (APPROVAL)
   └── validate_loading_pick / validate_returns   ──► Odoo PIN check (res.users/hr.employee)
                 │
                 ▼
        OdooToolkit._execute(model, method, args, kwargs)
                 │
                 ▼
        AbstractOdooTransport.execute_kw  (json2 / jsonrpc / xmlrpc)
                 │
                 ▼
              Odoo  (fsm.order, fsm.location, stock.picking, ...)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OdooToolkit` | extends (subclass) | inherits transport/auth, `_execute`, helpers, all parent tools |
| `OdooToolkit._execute` | uses | single RPC path for all fsm/stock calls + stage advances |
| `OdooToolkit.attach_document` | uses | optional `photo` on `create_return_draft` → `ir.attachment` |
| `AbstractToolkit.get_tools` | uses (reflection) | auto-registers the 8 new tools |
| `@tool_schema` / `@requires_permission` | uses (decorators) | per-tool schema + permission gating |
| `HumanInteractionManager` | uses | `rep confirm` via `InteractionType.APPROVAL` |
| `AbstractOdooTransport.execute_kw` | calls (indirect) | reached through `_execute`; also the PIN-check RPC |
| `_DEFAULT_KNOWN_MODELS` | extends | append `fsm.order`, `fsm.location` |

### Data Models

New Pydantic models follow the existing split under
`parrot_tools/odoo/models/` (`entities.py` / `inputs.py` / `envelopes.py`).

```python
# models/entities.py  — extend with (subset of fields; extra="allow" preserves rest)
class FsmOrder(_OdooEntity):
    name: Optional[str] = None
    stage_id: Optional[Many2one] = None
    person_id: Optional[Many2one] = None       # field rep (to confirm vs. rep_id)
    location_id: Optional[Many2one] = None      # the kiosk (fsm.location)
    date_start: Optional[str] = None
    sequence: Optional[int] = None              # ordering — exact field TBD (§8)

class FsmLocation(_OdooEntity):
    name: Optional[str] = None
    partner_id: Optional[Many2one] = None       # address source
    partner_latitude: Optional[float] = None
    partner_longitude: Optional[float] = None
    # planogram reference field — exact name TBD (§8)

# models/inputs.py  — one per tool (all subclass _OdooBaseInput, extra="ignore")
class GetTodayFsosInput(_OdooBaseInput):
    rep_id: int = Field(..., description="Odoo id of the field rep")

class GetLoadingSummaryInput(_OdooBaseInput):
    rep_id: int
    date: Optional[str] = Field(default=None, description="ISO date; defaults to today")

class GetKioskInput(_OdooBaseInput):
    location_id: int

class ReturnLine(BaseModel):
    product_id: int
    quantity: float

class CreateReturnDraftInput(_OdooBaseInput):
    order_id: int
    lines: list[ReturnLine]
    reason: str
    photo: Optional[str] = Field(default=None, description="path/URL/base64 for ir.attachment")

class ValidateLoadingPickInput(_OdooBaseInput):
    rep_id: int
    pin: str = Field(..., description="Manager PIN; verified against Odoo, never logged")

class ValidateReturnsInput(_OdooBaseInput):
    rep_id: int
    pin: str

class GetReturnSummaryInput(_OdooBaseInput):
    rep_id: int
    date: Optional[str] = None

class CompleteFsoInput(_OdooBaseInput):
    order_id: int

# models/envelopes.py  — result wrappers
class LoadingSummaryLine(BaseModel):
    product_id: int
    product_name: str
    total_qty: float

class ReturnSummaryLine(BaseModel):
    product_id: int
    product_name: str
    qty_to_return: float

class ValidationResult(BaseModel):
    ok: bool
    picking_ids: list[int] = []
    message: Optional[str] = None

class FsmStageResult(BaseModel):
    order_id: int
    stage_id: Optional[Many2one] = None
    stage_name: Optional[str] = None
```

### New Public Interfaces

```python
# parrot_tools/odoo/fieldservice.py  (new module)
from parrot_tools.odoo import OdooToolkit

class OdooFieldServiceToolkit(OdooToolkit):
    """Domain tools over OCA fieldservice + fieldservice_stock."""

    # tool_prefix inherited ("odoo"); new methods auto-register as odoo_<name>.

    @tool_schema(GetTodayFsosInput)
    async def get_today_fsos(self, rep_id: int) -> list[FsmOrder]: ...

    @tool_schema(GetLoadingSummaryInput)
    async def get_loading_summary(self, rep_id: int, date: str | None = None) -> list[LoadingSummaryLine]: ...

    @tool_schema(GetKioskInput)
    async def get_kiosk(self, location_id: int) -> FsmLocation: ...

    @requires_permission("odoo.write")
    @tool_schema(CreateReturnDraftInput)
    async def create_return_draft(self, order_id: int, lines: list[ReturnLine],
                                  reason: str, photo: str | None = None) -> StockPicking: ...  # rep confirm

    @requires_permission("odoo.write")
    @tool_schema(ValidateLoadingPickInput)
    async def validate_loading_pick(self, rep_id: int, pin: str) -> ValidationResult: ...  # manager PIN

    @requires_permission("odoo.write")
    @tool_schema(ValidateReturnsInput)
    async def validate_returns(self, rep_id: int, pin: str) -> ValidationResult: ...  # manager PIN

    @tool_schema(GetReturnSummaryInput)
    async def get_return_summary(self, rep_id: int, date: str | None = None) -> list[ReturnSummaryLine]: ...

    @requires_permission("odoo.write")
    @tool_schema(CompleteFsoInput)
    async def complete_fso(self, order_id: int) -> FsmStageResult: ...  # rep confirm
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 1: FSM Pydantic models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py`,
  `.../models/inputs.py`, `.../models/envelopes.py`, `.../models/__init__.py`
- **Responsibility**: Add `FsmOrder`, `FsmLocation` entities; the per-tool
  input schemas; `LoadingSummaryLine`, `ReturnSummaryLine`, `ValidationResult`,
  `FsmStageResult` envelopes; export them from `models/__init__.py`.
- **Depends on**: existing `_OdooEntity`, `_OdooBaseInput`, `Many2one`.

### Module 2: Known-model registration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
- **Responsibility**: Append `("fsm.order", "Field Service Order")` and
  `("fsm.location", "Field Service Location")` to `_DEFAULT_KNOWN_MODELS`.
- **Depends on**: none (single-line additions).

### Module 3: OdooFieldServiceToolkit (read tools)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/fieldservice.py` (new)
- **Responsibility**: Subclass `OdooToolkit`; implement the 4 read tools
  (`get_today_fsos`, `get_loading_summary`, `get_kiosk`, `get_return_summary`)
  via `self._execute(...)`.
- **Depends on**: Module 1, Module 2.

### Module 4: OdooFieldServiceToolkit (write + HITL tools)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/fieldservice.py`
- **Responsibility**: Implement `create_return_draft` (+ optional photo via
  `attach_document`), `complete_fso` (stage advance) — both behind `rep confirm`
  APPROVAL; and `validate_loading_pick` / `validate_returns` behind the manager
  PIN check + `stock.picking.button_validate`.
- **Depends on**: Module 3.

### Module 5: Manager-PIN verification helper
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/fieldservice.py`
  (private `async def _verify_manager_pin(self, pin: str) -> bool`)
- **Responsibility**: Verify the PIN against Odoo via an RPC (exact model/method
  TBD — see §8). Never log the PIN.
- **Depends on**: Module 4.

### Module 6: Package export
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py`
- **Responsibility**: Export `OdooFieldServiceToolkit` and add to `__all__`.
- **Depends on**: Module 3.

### Module 7: Tests
- **Path**: `packages/ai-parrot/tests/test_odoo_fieldservice_toolkit.py` (new)
- **Responsibility**: Unit tests with a fake transport (mirroring existing
  `test_odoo_toolkit.py`), covering each tool, the HITL gates, and the PIN check.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_get_today_fsos_orders_by_sequence` | M3 | returns rep's `fsm.order`s for today in route sequence |
| `test_get_loading_summary_consolidates_qty` | M3 | sums product qty across today's outbound pickings |
| `test_get_kiosk_returns_location_details` | M3 | maps `fsm.location` → name/address/coords/planogram |
| `test_get_return_summary_from_draft_pickings` | M3 | aggregates qty-to-return from draft return pickings |
| `test_create_return_draft_requires_rep_confirm` | M4 | APPROVAL requested; rejection aborts, no write |
| `test_create_return_draft_attaches_photo` | M4 | optional `photo` → `ir.attachment` via `attach_document` |
| `test_complete_fso_advances_stage` | M4 | advances `fsm.order` stage; rep-confirm gated |
| `test_validate_loading_pick_valid_pin` | M4/M5 | valid PIN → `button_validate` runs, `ok=True` |
| `test_validate_loading_pick_bad_pin_rejected` | M5 | invalid PIN → no validation, `ok=False`, PIN not logged |
| `test_validate_returns_validates_all_drafts` | M4 | validates all draft return pickings under manager PIN |
| `test_fsm_models_registered_in_list_models` | M2 | `fsm.order`/`fsm.location` appear in `list_models` |
| `test_subclass_inherits_parent_tools` | M3 | `get_tools()` includes parent CRUD tools + 8 FSM tools |

### Integration Tests
| Test | Description |
|---|---|
| `test_route_happy_path` | load → today's FSOs → kiosk → return draft → EOD validate (fake transport) |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_fsm_transport():
    # Reuse the fake/stub transport pattern from test_odoo_toolkit.py;
    # canned responses for fsm.order, fsm.location, stock.picking, res.users.
    ...

@pytest.fixture
def fs_toolkit(fake_fsm_transport):
    return OdooFieldServiceToolkit(transport=fake_fsm_transport)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OdooFieldServiceToolkit(OdooToolkit)` exists in
      `parrot_tools/odoo/fieldservice.py` and is exported from
      `parrot_tools/odoo/__init__.py` (`from parrot_tools.odoo import
      OdooFieldServiceToolkit`).
- [ ] All 8 tools are present and discoverable via `get_tools()`, prefixed
      `odoo_` (inherited `tool_prefix`).
- [ ] `get_tools()` also still returns the inherited parent CRUD/partner/sales
      tools (subclass + expose-all; resolved decision).
- [ ] `fsm.order` and `fsm.location` are present in `_DEFAULT_KNOWN_MODELS` and
      surface in `list_models`.
- [ ] All Odoo I/O goes through `self._execute(...)`; no direct SDK/transport
      calls in tool bodies, no blocking I/O.
- [ ] `create_return_draft` and `complete_fso` request a `rep confirm` APPROVAL
      via `HumanInteractionManager` and abort cleanly on rejection.
- [ ] `validate_loading_pick` and `validate_returns` verify the `pin` against
      Odoo before validating pickings; an invalid PIN returns `ok=False` and
      performs no write.
- [ ] The PIN value never appears in logs.
- [ ] New Pydantic models added per the three-module split and exported from
      `models/__init__.py`.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/test_odoo_fieldservice_toolkit.py -v`).
- [ ] No breaking changes to `OdooToolkit` or its existing tools.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against the repo on
> 2026-06-02. Implementation agents MUST use these verbatim and MUST NOT
> reference imports/attributes/methods not listed here without re-verifying.

### Verified Imports
```python
# verified: packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py:21-27
from parrot_tools.odoo import OdooToolkit

# verified: packages/ai-parrot/src/parrot/tools/decorators.py:1 (requires_permission), :29 (tool_schema)
from parrot.tools.decorators import requires_permission, tool_schema

# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:337 (get_tools), :427 (get_tools_filtered)
from parrot.tools.toolkit import AbstractToolkit

# verified: packages/ai-parrot/src/parrot/human/__init__.py:19,24,26,32
from parrot.human import (
    HumanInteractionManager, InteractionType, HumanInteraction, InteractionResult,
)
from parrot.human import get_default_human_manager  # __init__.py:73

# entity/input/envelope bases — verified in models/ (see signatures below)
from parrot_tools.odoo.models.entities import _OdooEntity, Many2one, StockPicking
from parrot_tools.odoo.models.inputs import _OdooBaseInput
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):            # line 159
    tool_prefix = "odoo"                        # line 178
    def __init__(self, url=None, database=None, username=None, password=None,
                 timeout=None, verify_ssl=None, protocol="auto",
                 transport=None, **kwargs): ...  # line 180

    async def _execute(self, model: str, method: str,
                       args: list[Any] | None = None,
                       kwargs: dict[str, Any] | None = None) -> Any:  # line 261
        # -> transport.execute_kw(model, method, args, kwargs)

    async def confirm_sale_order(self, sale_order_id: int) -> SaleOrder:  # line 772
        # pattern: await self._execute("sale.order", "action_confirm", [[sale_order_id]])

    @requires_permission("odoo.write")
    @tool_schema(AttachDocumentInput)
    async def attach_document(self, res_model: str, res_id: int, name: str,
                              source: str, mimetype: Optional[str] = None,
                              description: Optional[str] = None) -> BinaryFieldResult:  # line 906

# _DEFAULT_KNOWN_MODELS — line 136 (tuple of (tech_name, label); used at line 354 in list_models)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py
Many2one = Union[tuple[int, str], list[Any], bool, None]   # line 19
class _OdooEntity(BaseModel):                               # line 22
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    id: Optional[int]; display_name: Optional[str]
class StockPicking(_OdooEntity):                            # line 227
    name, state, partner_id, picking_type_id, location_id,
    location_dest_id, scheduled_date, date_done, origin, move_ids

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
class _OdooBaseInput(BaseModel):                            # line 19
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    tool_prefix: Optional[str] = None                       # line 242
    def get_tools(self, ...) -> list:                        # line 337  (reflection over async def)
    async def get_tools_filtered(self, ...)                  # line 427
    # discovery keeps inspect.iscoroutinefunction methods (line 413); applies prefix idempotently (383-385)

# packages/ai-parrot/src/parrot/tools/decorators.py
def requires_permission(*permissions: str)                  # line 1  (sets _required_permissions)
def tool_schema(schema: Type[BaseModel], description=None)  # line 29 (binds Pydantic input schema)

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:                              # line 51
    async def request_human_input(self, ...)                # line 283
    async def request_human_input_async(self, ...)          # line 485
# packages/ai-parrot/src/parrot/human/models.py
class InteractionType(str, Enum): ... APPROVAL = "approval" # lines 60, 66

# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/base.py
class AbstractOdooTransport(ABC):                           # line 11
    uid: int | None                                         # line 20
    async def authenticate(self) -> int                     # line 23
    async def execute_kw(self, ...)                          # line 36
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OdooFieldServiceToolkit` | `OdooToolkit` | subclass | `odoo/toolkit.py:159` |
| FSM read/write tools | `OdooToolkit._execute` | method call | `odoo/toolkit.py:261` |
| `create_return_draft(photo=...)` | `OdooToolkit.attach_document` | method call | `odoo/toolkit.py:906` |
| `validate_*` | `stock.picking` `button_validate` | `self._execute("stock.picking","button_validate",[[ids]])` | pattern per `confirm_sale_order` `odoo/toolkit.py:772` |
| `complete_fso` | `fsm.order` stage write/advance | `self._execute("fsm.order", ...)` | pattern per `odoo/toolkit.py:772` |
| rep-confirm tools | `HumanInteractionManager` | `request_human_input` + `InteractionType.APPROVAL` | `human/manager.py:283`, `human/models.py:66` |
| `_verify_manager_pin` | Odoo `res.users`/`hr.employee` | `self._execute(...)` (exact RPC TBD §8) | n/a (new) |
| FSM tools | `get_tools()` reflection | auto-register | `tools/toolkit.py:337,413` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.odoo.models.entities.FsmOrder`~~ — does NOT exist; must be created (Module 1).
- ~~`parrot_tools.odoo.models.entities.FsmLocation`~~ — does NOT exist; must be created.
- ~~`fsm.order` / `fsm.location` in `_DEFAULT_KNOWN_MODELS`~~ — NOT present; must be added (Module 2).
- ~~`OdooToolkit.get_today_fsos` / any FSM method~~ — no FSM tools exist today.
- ~~A numeric-PIN primitive / PIN verification helper anywhere in the repo~~ — does NOT exist; net-new (Module 5).
- ~~`parrot_tools.odoo.fieldservice`~~ — module does NOT exist yet; this feature creates it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Tool method shape: `@requires_permission(...)` (writes only) + `@tool_schema(<Input>)`
  + `async def`, returning a typed envelope; all RPC via `self._execute(...)`.
- Domain-toolkit subclassing precedent: `SqlToolkit(DatabaseToolkit)` and
  siblings under `packages/ai-parrot/src/parrot/bots/database/toolkits/`.
- Pydantic split: entities (`extra="allow"`), inputs (`extra="ignore"`),
  envelopes — keep new models in the matching module and export from
  `models/__init__.py`.
- Lazy I/O: do not call Odoo in `__init__`; the inherited `_pre_execute`
  authenticates on first tool call.
- Logging via `self.logger` (inherited). Never log the `pin`.
- Tests: mirror `packages/ai-parrot/tests/test_odoo_toolkit.py` and inject a
  fake transport via the `transport=` constructor arg.

### Known Risks / Gotchas
- **Wide tool surface (accepted).** Subclass + expose-all means the rep agent
  also gets all generic CRUD tools (search/create/update/delete any model).
  Mitigated by `@requires_permission` + Odoo ACLs; revisit `get_tools_filtered`
  if needed.
- **Domain field drift.** Wrong `fsm.order` ordering field or `fsm.location`
  planogram field fails *silently* as empty results — verify field names against
  the live instance (see §8).
- **PIN secret handling.** The PIN crosses the agent boundary; verify
  server-side only, never persist or log it. Consider redaction in any error
  surfaces.
- **`button_validate` side effects.** Picking validation may raise Odoo
  wizards/backorders; the tool must handle the validation return shape and
  report a clean `ValidationResult`.
- **`rep_id` semantics.** `rep_id` likely maps to `fsm.order.person_id`
  (or a related `res.users`/`hr.employee`) — confirm before building the domain
  filter (see §8).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | Reuses existing `parrot_tools.odoo` + `parrot.human` stack |

> Odoo-side: OCA `fieldservice` + `fieldservice_stock` assumed installed on the

…(truncated)…
