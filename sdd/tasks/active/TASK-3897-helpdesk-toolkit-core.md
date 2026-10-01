# TASK-3897: `OdooHelpdeskToolkit` core — constructor, known models, resolvers, reference data, ticket reads

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3892, TASK-3895, TASK-3896
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5** plus the constructor half of **Module 2** (G1, G3 read tools, G4, G6, AC2,
AC3, AC5, AC6, AC7, AC13, AC21). This task creates `parrot_tools/odoo/helpdesk.py`; TASK-3898–3901 append
their tool sections to the same class. Decisions that are NOT renegotiable: prefix stays `odoo` and every
inherited tool is exposed (owner decision, design research S3/S4 rejected); credentials come only from
`ODOO_HELPDESK_*` (S2); `list_models` is overridden because the base iterates a module constant (S1);
`confirming_tools` is the union with the base set (S10); name resolution uses `search_read`, never
`name_search` (S5); stage roles are read from `res.company` (spec §8 resolved, AC21).

---

## Scope

- Create `helpdesk.py` with `_HELPDESK_KNOWN_MODELS` and class `OdooHelpdeskToolkit(OdooToolkit)`:
  constructor (config isolation), `confirming_tools`, field constants, `_REF_MODELS`, `_resolve_ref`, `_resolve_refs`,
  `_stage_map`, `_company_stage_config`, `_load_ticket`, `_extra_rows`, `_ticket_url`, `list_models` override,
  six `list_helpdesk_*` reference tools, `get_ticket`, `search_tickets`, `list_my_tickets`, `get_ticket_history`,
  `get_ticket_messages`, `get_ticket_extra_fields`.
- Export the class from `parrot_tools/odoo/__init__.py`.
- Create `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` with the fixture helpers and this task's tests.

**NOT in scope**: writes/assignment (TASK-3898), transitions (TASK-3899), SLA (TASK-3900), stats/wizards/timer (TASK-3901), docs (TASK-3902).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` | CREATE | toolkit class, core + read tools |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py` | MODIFY | export `OdooHelpdeskToolkit` |
| `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` | CREATE | fixtures + core/read tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from typing import Any, Literal, Optional
from parrot.conf import (ODOO_HELPDESK_APIKEY, ODOO_HELPDESK_DATABASE, ODOO_HELPDESK_PASSWORD, ODOO_HELPDESK_TIMEOUT,
                         ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_VERIFY_SSL)                  # TASK-3892
from parrot.interfaces.odoointerface import OdooConfig, OdooError                        # verified: odoointerface.py:55 / :35 region (toolkit.py:39-45 imports them)
from parrot.tools.decorators import requires_permission, tool_schema                     # verified: decorators.py:9 / :39
from parrot_tools.odoo.toolkit import OdooToolkit, _DEFAULT_KNOWN_MODELS                 # verified: toolkit.py:172 / :149
from parrot_tools.odoo.transport.base import AbstractOdooTransport                       # verified: transport/base.py:11
from parrot_tools.odoo.transport.detect import Protocol                                  # verified: detect.py:29
from parrot_tools.odoo.models.envelopes import FieldSelectionMetadata, ModelInfo, ModelOperations, ModelsResult   # verified: envelopes.py:14/36/27/44
from parrot_tools.odoo.models.helpdesk_entities import HelpdeskMessage, HelpdeskStageInfo, HelpdeskTicket        # TASK-3893
from parrot_tools.odoo.models.helpdesk_envelopes import (HelpdeskReferenceItem, HelpdeskReferenceResult, TicketExtraFieldsResult,
    TicketHistoryResult, TicketListResult, TicketMessagesResult, TicketResult)                                    # TASK-3895
from parrot_tools.odoo.models.helpdesk_inputs import (GetTicketExtraFieldsInput, GetTicketHistoryInput, GetTicketInput,
    GetTicketMessagesInput, ListMyTicketsInput, ListReferenceInput, SearchTicketsInput)                          # TASK-3894
from parrot_tools.odoo.helpdesk_normalize import normalize_ticket                                                # TASK-3896
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py  (verified at b3141f286)
_DEFAULT_KNOWN_MODELS: tuple[tuple[str, str], ...]                     # line 149-160
class OdooToolkit(AbstractToolkit):                                     # line 172
    tool_prefix = "odoo"                                                # line 191
    confirming_tools: frozenset = frozenset({...3 shell names...})      # line 194-200
    def __init__(self, url=None, database=None, username=None, password=None, timeout=None, verify_ssl=None,
                 protocol: Protocol = "auto", transport=None, **kwargs) -> None                # line 202
        self.config = OdooConfig(url=url or ODOO_URL or "", database=database or ODOO_DATABASE or "", ...)   # line 230-235 ← `or` fallback: REBUILD self.config after super()
        self._transport, self._auth_lock, self._fields_cache, self.logger                                     # line 238-241
    async def _ensure_transport(self) -> AbstractOdooTransport          # line 245  (sets/returns transport with .uid)
    async def _execute(self, model, method, args=None, kwargs=None) -> Any   # line 283
    @staticmethod
    def _record_url(base_url: str, model: str, record_id: int) -> str   # line 294
    async def _read_one(self, model, record_id, fields=None) -> dict    # line 299
    async def _get_fields_metadata(self, model) -> dict                 # line 312
    async def list_models(self) -> ModelsResult                         # line 373-390 — loop: for tech_name, label in _DEFAULT_KNOWN_MODELS: check_access_rights(op, raise_exception=False) → ModelInfo(model, name, operations=ModelOperations(...))
    async def search_records(...)                                       # line 406 — SearchResult + FieldSelectionMetadata construction pattern

# packages/ai-parrot/src/parrot/interfaces/odoointerface.py
class OdooConfig(BaseModel): url: str; database: str; username: str; password: str; timeout: int = 30; verify_ssl: bool = True   # line 55-72 ("" is a valid database)

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit: confirming_tools matched on the UNPREFIXED method name   # line 694-699; get_tools() line 494

# packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py  (38 lines)
from .toolkit import (OdooAuthenticationError, OdooConnectionError, OdooError, OdooRPCError, OdooToolkit,)   # lines 22-28; `    OdooToolkit,` = line 27
__all__ = ["OdooToolkit", ...]                                          # lines 30-38; `    "OdooToolkit",` = line 31

# packages/ai-parrot/tests/test_odoo_toolkit.py — pattern to COPY into the new test module (tests/ is a package but do not import across test modules)
def _fake_transport(uid: int = 1) -> MagicMock                          # line 57-80: MagicMock with .config=OdooConfig(...), .uid, .name, .authenticate/.execute_kw/.version/.close = AsyncMock
def _make_toolkit(transport=None) -> OdooToolkit                        # line 83: OdooToolkit(url=..., database="testdb", username="admin", password="secret", timeout=30, transport=transport)

# Live-verified Odoo facts used here (spec §6): helpdesk.stages fields name/sequence/sh_next_stage/is_done_button_visible/is_cancel_button_visible;
#   res.company fields new_stage_id/reopen_stage_id/done_stage_id/cancel_stage_id/close_stage_id/sh_staff_replied_stage_id/sh_customer_replied_stage_id;
#   sh.helpdesk.ticket.extra_fields fields ticket_id/field_name/name/value; sh.helpdesk.ticket.stage.info fields stage_task_id/stage_name/date_in/date_out/date_in_by/date_out_by/day_diff/time_diff/total_time_diff;
#   mail.message search domain [("model","=","sh.helpdesk.ticket"),("res_id","=",id)] with fields message_type/subtype_id/date/author_id/body.
```

### Does NOT Exist
- ~~`OdooToolkit.known_models`~~ / ~~`self._DEFAULT_KNOWN_MODELS`~~ — module constant; override `list_models` instead (S1).
- ~~`ODOO_HELPDESK_USERNAME`~~ — the conf key is `ODOO_HELPDESK_USER`.
- ~~`name_search` in resolvers~~ — forbidden by S5/AC13; use `search_read`.
- ~~`helpdesk.stages.fold` / `is_close`~~ — not on the instance.
- ~~`exclude_tools` / `tool_prefix = "odoo_hd"`~~ — rejected by the owner; do not set either.
- ~~`from tests.test_odoo_toolkit import _fake_transport`~~ — copy the helper; do not import across test modules.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit.__init__",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._read_one",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit.list_models",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#_DEFAULT_KNOWN_MODELS",
    "sym:packages/ai-parrot/src/parrot/tools/decorators.py#tool_schema",
    "sym:packages/ai-parrot/src/parrot/tools/decorators.py#requires_permission"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every public `async def` becomes a tool: keep helpers underscore-prefixed; every tool has a docstring + `@tool_schema`.
- All Odoo I/O via `self._execute`; never `web_save`, never a raw aiohttp call.
- Resolver: int → as is; str → exact `(field, "=", value)` then `(field, "ilike", value)`; 0 → `ValueError(f"No {kind} named {value!r}")`; >1 → `ValueError` listing `name (id)`; cache hits in `self._ref_cache[(model, value)]`. `user` kind: try `login =` exact before `name =`.
- `_company_stage_config` does exactly two RPCs once (`res.users.read([uid], ["company_id"])`, `res.company.read([cid], [...7 role fields...])`) and caches `self._stage_roles`.
- `only_open`: exclude `close` + `cancel` role ids; if both `None`, exclude the last stage of the `sh_next_stage` chain (AC21).
- `black` 120, `ruff` clean, Google docstrings, `self.logger`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, `_HELPDESK_KNOWN_MODELS` and the class skeleton with the constructor — *why*: AC2/AC3 hinge on rebuilding `self.config` after `super().__init__`.
2. Add the private helpers (`_resolve_ref`, `_stage_map`, `_company_stage_config`, `_extra_rows`, `_load_ticket`, `_ticket_url`) — *why*: every later task calls them by these exact names.
3. Add `list_models` and the six reference tools — *why*: S1 and G6 (names, never ids).
4. Add the six ticket-read tools — *why*: they are the read surface TASK-3898+ read back through.
5. Export from `odoo/__init__.py`; create the test module with the fixture helpers and this task's tests.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` (CREATE — header, constants, constructor)
```python
"""OdooHelpdeskToolkit — helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` on top of :class:`OdooToolkit`.

Every public ``async def`` is auto-registered as an ``odoo_<name>`` tool (prefix inherited). All Odoo I/O goes
through :meth:`OdooToolkit._execute`. Credentials come ONLY from ``ODOO_HELPDESK_*`` (never ``ODOO_*``).
An agent loads either ``OdooToolkit`` or ``OdooHelpdeskToolkit`` (a superset) — never both (name collision).
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from parrot.conf import (
    ODOO_HELPDESK_APIKEY, ODOO_HELPDESK_DATABASE, ODOO_HELPDESK_PASSWORD, ODOO_HELPDESK_TIMEOUT,
    ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_VERIFY_SSL,
)
from parrot.interfaces.odoointerface import OdooConfig, OdooError
from parrot.tools.decorators import requires_permission, tool_schema
from parrot_tools.odoo.helpdesk_normalize import normalize_ticket
from parrot_tools.odoo.models.envelopes import FieldSelectionMetadata, ModelInfo, ModelOperations, ModelsResult
from parrot_tools.odoo.models.helpdesk_entities import HelpdeskMessage, HelpdeskStageInfo, HelpdeskTicket
from parrot_tools.odoo.models.helpdesk_envelopes import (
    HelpdeskReferenceItem, HelpdeskReferenceResult, TicketExtraFieldsResult, TicketHistoryResult,
    TicketListResult, TicketMessagesResult, TicketResult,
)
from parrot_tools.odoo.models.helpdesk_inputs import (
    GetTicketExtraFieldsInput, GetTicketHistoryInput, GetTicketInput, GetTicketMessagesInput,
    ListMyTicketsInput, ListReferenceInput, SearchTicketsInput,
)
from parrot_tools.odoo.toolkit import OdooToolkit, _DEFAULT_KNOWN_MODELS
from parrot_tools.odoo.transport.base import AbstractOdooTransport
from parrot_tools.odoo.transport.detect import Protocol

TICKET_MODEL = "sh.helpdesk.ticket"

_HELPDESK_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("sh.helpdesk.ticket", "Helpdesk Ticket"), ("sh.helpdesk.team", "Helpdesk Team"), ("helpdesk.stages", "Helpdesk Stage"),
    ("helpdesk.category", "Helpdesk Category"), ("helpdesk.subcategory", "Helpdesk Subcategory"), ("helpdesk.priority", "Helpdesk Priority"),
    ("helpdesk.sub.type", "Helpdesk Subject"), ("helpdesk.tags", "Helpdesk Tag"), ("sh.helpdesk.ticket.type", "Helpdesk Ticket Type"),
    ("sh.helpdesk.sla", "Helpdesk SLA Policy"), ("sh.helpdesk.sla.status", "Helpdesk SLA Status"),
    ("sh.helpdesk.ticket.stage.info", "Helpdesk Stage History"), ("sh.ticket.alarm", "Helpdesk Ticket Alarm"),
)

_STAGE_ROLE_FIELDS = ("new_stage_id", "reopen_stage_id", "done_stage_id", "cancel_stage_id", "close_stage_id",
                      "sh_staff_replied_stage_id", "sh_customer_replied_stage_id")


class OdooHelpdeskToolkit(OdooToolkit):
    """Helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` (Odoo 19) on top of :class:`OdooToolkit`."""

    confirming_tools: frozenset = OdooToolkit.confirming_tools | frozenset({"cancel_ticket", "merge_tickets", "mass_update_tickets"})

    _TICKET_LIST_FIELDS = ["id", "name", "email_subject", "stage_id", "state", "priority", "team_id", "user_id", "sh_user_ids",
                           "category_id", "sub_category_id", "ticket_type", "partner_id", "create_date", "close_date", "sh_sla_deadline"]
    # FILL IN: _TICKET_DEFAULT_FIELDS — the ~45 wire fields declared on HelpdeskTicket (TASK-3893), superset of _TICKET_LIST_FIELDS — spec §3 M5
    _REF_MODELS: dict[str, tuple[str, str]] = {
        "stage": ("helpdesk.stages", "name"), "team": ("sh.helpdesk.team", "name"), "category": ("helpdesk.category", "name"),
        "sub_category": ("helpdesk.subcategory", "name"), "priority": ("helpdesk.priority", "name"),
        "ticket_type": ("sh.helpdesk.ticket.type", "name"), "tag": ("helpdesk.tags", "name"), "user": ("res.users", "name"),
        "sla": ("sh.helpdesk.sla", "name"),
    }

    def __init__(self, url: str | None = None, database: str | None = None, username: str | None = None,
                 password: str | None = None, timeout: int | None = None, verify_ssl: bool | None = None,
                 protocol: Protocol = "auto", transport: AbstractOdooTransport | None = None, **kwargs: Any) -> None:
        """Resolve each value from the argument, else ``ODOO_HELPDESK_*`` — never ``ODOO_*`` (spec §3 M2)."""
        resolved = OdooConfig(
            url=url if url is not None else (ODOO_HELPDESK_URL or ""),
            database=database if database is not None else (ODOO_HELPDESK_DATABASE or ""),
            username=username if username is not None else (ODOO_HELPDESK_USER or ""),
            password=password if password is not None else (ODOO_HELPDESK_APIKEY or ODOO_HELPDESK_PASSWORD or ""),
            timeout=timeout if timeout is not None else ODOO_HELPDESK_TIMEOUT,
            verify_ssl=verify_ssl if verify_ssl is not None else ODOO_HELPDESK_VERIFY_SSL,
        )
        super().__init__(url=resolved.url, database=resolved.database, username=resolved.username, password=resolved.password,
                         timeout=resolved.timeout, verify_ssl=resolved.verify_ssl, protocol=protocol, transport=transport, **kwargs)
        self.config = resolved  # base __init__ applied `value or ODOO_*`; an empty database must stay empty (AC3)
        self._ref_cache: dict[tuple[str, str], int] = {}
        self._stages_cache: dict[int, dict[str, Any]] | None = None
        self._stage_roles: dict[str, int | None] | None = None
        self.logger = logging.getLogger(__name__)
```
**Why this shape**: the base constructor cannot be told "keep an empty database" (toolkit.py:230-235 uses `or`), so the subclass builds the `OdooConfig` itself and re-assigns `self.config` after `super().__init__` — the only way to satisfy AC3 without editing `toolkit.py`. `confirming_tools` is a union because the base matches unprefixed method names (S10).

### `…/helpdesk.py` (CREATE — private helpers, same class)
```python
    # ── Private helpers (never exposed as tools) ────────────────────────────
    async def _resolve_ref(self, kind: str, value: int | str) -> int:
        """Return an id for *value*: ints pass through; names resolve via search_read (exact, then unique ilike).

        Raises:
            ValueError: unknown ``kind``, no match, or several matches (candidates listed as ``name (id)``).
        """
        if isinstance(value, int):
            return value
        model, field = self._REF_MODELS[kind]  # KeyError → programming error; FILL IN: raise ValueError(f"unknown ref kind {kind!r}")
        key = (model, value)
        if key in self._ref_cache:
            return self._ref_cache[key]
        # FILL IN: for user kind try [("login","=",value)] first; then [(field,"=",value)]; then [(field,"ilike",value)];
        #   each via self._execute(model, "search_read", [domain], {"fields": ["id", field], "limit": 5});
        #   exactly one hit → cache + return; 0 → ValueError(f"No {kind} named {value!r}"); >1 → ValueError listing f"{r[field]} ({r['id']})" — AC13
        raise NotImplementedError

    async def _resolve_refs(self, kind: str, values: list[int | str]) -> list[int]:
        return [await self._resolve_ref(kind, v) for v in values]

    async def _stage_map(self) -> dict[int, dict[str, Any]]:
        """``{stage_id: {"name", "sequence", "sh_next_stage", "is_done_button_visible", "is_cancel_button_visible"}}`` (cached)."""
        if self._stages_cache is None:
            rows = await self._execute("helpdesk.stages", "search_read", [[]], {"fields": ["name", "sequence", "sh_next_stage",
                                       "is_done_button_visible", "is_cancel_button_visible"], "order": "sequence, id"})
            self._stages_cache = {int(r["id"]): r for r in rows or []}
        return self._stages_cache

    async def _company_stage_config(self) -> dict[str, int | None]:
        """Stage roles from ``res.company`` for the connected user's company (cached): new/reopen/done/cancel/close/staff_replied/customer_replied."""
        if self._stage_roles is None:
            transport = await self._ensure_transport()
            user = await self._execute("res.users", "read", [[transport.uid]], {"fields": ["company_id"]})
            # FILL IN: cid = user[0]["company_id"][0] when set, else 1; company = res.company.read([[cid]], {"fields": list(_STAGE_ROLE_FIELDS)});
            #   roles = {short: id or None} where short strips "_stage_id"/"sh_"/"_stage_id" → keys new/reopen/done/cancel/close/staff_replied/customer_replied — AC21
            self._stage_roles = {}
        return self._stage_roles

    async def _closed_stage_ids(self) -> list[int]:
        """Ids excluded by ``only_open``: company close + cancel roles; fallback = last stage of the sh_next_stage chain."""
        roles = await self._company_stage_config()
        ids = [i for i in (roles.get("close"), roles.get("cancel")) if i]
        if ids:
            return ids
        stages = await self._stage_map()
        return [sid for sid, row in stages.items() if not row.get("sh_next_stage")]

    async def _extra_rows(self, ticket_id: int) -> list[dict[str, Any]]:
        return await self._execute("sh.helpdesk.ticket.extra_fields", "search_read", [[("ticket_id", "=", ticket_id)]],
                                   {"fields": ["field_name", "name", "value"], "limit": 500}) or []

    async def _load_ticket(self, ticket_id: int, include_extra: bool = True) -> HelpdeskTicket:
        """Read one ticket with ``_TICKET_DEFAULT_FIELDS`` and normalise it (raises OdooError-derived when missing)."""
        record = await self._read_one(TICKET_MODEL, ticket_id, self._TICKET_DEFAULT_FIELDS)
        if not record:
            raise ValueError(f"Ticket {ticket_id} not found")
        extra = await self._extra_rows(ticket_id) if include_extra else None
        return normalize_ticket(record, extra, await self._stage_map(), await self._company_stage_config())

    def _ticket_url(self, ticket_id: int) -> str:
        return self._record_url(self.config.url, TICKET_MODEL, ticket_id)
```
**Why**: names and contracts fixed by spec §3 M5; `_closed_stage_ids` isolates the AC21 rule so `search_tickets`, `list_my_tickets` and TASK-3901's `ticket_stats` share it.

### `…/helpdesk.py` (CREATE — list_models, reference tools, ticket reads, same class)
```python
    # ── Discovery ───────────────────────────────────────────────────────────
    async def list_models(self) -> ModelsResult:
        """List helpdesk + core models with the connected user's ACLs (overrides the base module-constant loop)."""
        # FILL IN: same loop as OdooToolkit.list_models (toolkit.py:373-390) over _HELPDESK_KNOWN_MODELS + _DEFAULT_KNOWN_MODELS — AC6
        raise NotImplementedError

    async def _reference(self, model: str, fields: list[str], limit: int, order: str = "id") -> HelpdeskReferenceResult:
        rows = await self._execute(model, "search_read", [[]], {"fields": ["id", "name", *fields], "limit": limit, "order": order}) or []
        items = [HelpdeskReferenceItem(id=int(r["id"]), name=str(r.get("name") or ""), extra={k: r.get(k) for k in fields}) for r in rows]
        return HelpdeskReferenceResult(kind=model, items=items, total=len(items))

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_stages(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk stages ordered by sequence; ``extra`` carries sh_next_stage and the done/cancel button flags."""
        return await self._reference("helpdesk.stages", ["sequence", "sh_next_stage", "is_done_button_visible", "is_cancel_button_visible"], limit, "sequence, id")

    # FILL IN: list_helpdesk_teams (sh.helpdesk.team: team_head, team_members), list_helpdesk_categories (helpdesk.category: team_id;
    #   extra["subcategories"] from helpdesk.subcategory grouped by parent_category_id), list_helpdesk_priorities (sequence, color, order "sequence, id"),
    #   list_ticket_types (sh.helpdesk.ticket.type: sla_count), list_helpdesk_tags (helpdesk.tags: color) — each @tool_schema(ListReferenceInput) with a docstring

    # ── Ticket reads ────────────────────────────────────────────────────────
    @tool_schema(GetTicketInput)
    async def get_ticket(self, ticket_id: int, include_extra_fields: bool = True, include_history: bool = False) -> TicketResult:
        """Read one helpdesk ticket with its lifecycle block, TROC extra fields and (optionally) stage history."""
        ticket = await self._load_ticket(ticket_id, include_extra=include_extra_fields)
        # FILL IN: when include_history, attach the stage.info lines under ticket.lifecycle? NO — return them via get_ticket_history;
        #   here only set a `history_count` in TicketResult? NO — spec fixes TicketResult(ticket, url, model): ignore include_history beyond
        #   loading nothing extra, and document in the docstring that history is fetched by get_ticket_history — bounded by spec §2 envelope shape
        return TicketResult(ticket=ticket, url=self._ticket_url(ticket_id))

    @tool_schema(SearchTicketsInput)
    async def search_tickets(self, query: Optional[str] = None, stage: Optional[int | str] = None, team: Optional[int | str] = None,
                             assignee: Optional[int | str] = None, category: Optional[int | str] = None, priority: Optional[int | str] = None,
                             ticket_type: Optional[int | str] = None, partner_id: Optional[int] = None, created_after: Optional[str] = None,
                             created_before: Optional[str] = None, only_open: bool = False, domain: Optional[list[Any]] = None,
                             fields: Optional[list[str]] = None, limit: int = 50, offset: int = 0, order: str = "id desc") -> TicketListResult:
        """Search helpdesk tickets by text, stage/team/assignee/category/priority/type (id or name), customer, dates; ``only_open`` excludes the company's close and cancel stages."""
        clauses: list[Any] = []
        # FILL IN: query → ["|", "|", ("name","ilike",q), ("email_subject","ilike",q), ("email","ilike",q)]; each ref → ("<field>", "=", await self._resolve_ref(kind, value))
        #   (stage→stage_id, team→team_id, assignee→user_id via kind "user", category→category_id, priority→priority, ticket_type→ticket_type);
        #   partner_id → ("partner_id","=",id); created_after/before → ("create_date", ">=" / "<=", value); only_open → ("stage_id","not in", await self._closed_stage_ids());
        #   extra domain appended as-is (AND) — AC21
        use_fields = fields or self._TICKET_LIST_FIELDS
        records = await self._execute(TICKET_MODEL, "search_read", [clauses], {"fields": use_fields, "limit": limit, "offset": offset, "order": order}) or []
        total = int(await self._execute(TICKET_MODEL, "search_count", [clauses]) or 0)
        stages, roles = await self._stage_map(), await self._company_stage_config()
        tickets = [normalize_ticket(r, None, stages, roles) for r in records]
        return TicketListResult(tickets=tickets, total=total, limit=limit, offset=offset, fields=use_fields,
                                metadata=FieldSelectionMetadata(fields_returned=len(use_fields), field_selection_method="requested" if fields else "auto"))

    # FILL IN: list_my_tickets(only_open=True, limit=50) → domain ["|", ("user_id","=",uid), ("sh_user_ids","in",[uid])] (+ only_open) reusing the
    #   search_read/search_count/normalise steps above; get_ticket_history → sh.helpdesk.ticket.stage.info search_read [("stage_task_id","=",id)]
    #   order "date_in, id" → TicketHistoryResult(lines=[HelpdeskStageInfo...]); get_ticket_messages(limit=20, include_notifications=False) →
    #   mail.message search_read [("model","=",TICKET_MODEL),("res_id","=",id)] (+ ("message_type","!=","notification") unless included),
    #   fields message_type/subtype_id/date/author_id/body, order "id desc" → HelpdeskMessage(is_internal = subtype name == "Note");
    #   get_ticket_extra_fields → _extra_rows + extra_fields_to_dict (import it) → TicketExtraFieldsResult(fields, labels, count)
```
**Why**: `search_tickets` is written out because its domain assembly is the AC21/AC13 contract; the remaining reads follow the same three-call pattern. `get_ticket`'s `include_history` flag is kept for schema compatibility but the envelope shape is fixed by spec §2 — document, do not extend.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    OdooToolkit,' packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py)
# AFTER the closing `)` of the `from .toolkit import (` block (last entry `    OdooToolkit,` is line 27) — insert:
from .helpdesk import OdooHelpdeskToolkit

# occurrences: 1 (verified: grep -c '    "OdooToolkit",' packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py)
# AFTER — insert below `    "OdooToolkit",` (verified: odoo/__init__.py:31):
    "OdooHelpdeskToolkit",
```
**Why**: spec §6 Edit Sites; `from .helpdesk import` must come after `.toolkit` (helpdesk imports toolkit).

### `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` (CREATE)
```python
"""Unit tests for OdooHelpdeskToolkit (AsyncMock transport, no network). Later tasks append sections."""
from __future__ import annotations

import sys, types
from unittest.mock import AsyncMock, MagicMock

import pytest

# FILL IN: copy the parrot.utils stub block from packages/ai-parrot/tests/test_odoo_toolkit.py:19-30 verbatim (keeps imports light)

from parrot.interfaces.odoointerface import OdooConfig  # noqa: E402
from parrot_tools.odoo import OdooHelpdeskToolkit, OdooToolkit  # noqa: E402
from parrot_tools.odoo.models.helpdesk_envelopes import HelpdeskReferenceResult, TicketListResult, TicketResult  # noqa: E402

ROLES_ROW = [{"id": 1, "new_stage_id": [4, "New"], "reopen_stage_id": [22, "Open"], "done_stage_id": False, "cancel_stage_id": False,
              "close_stage_id": [21, "Closed"], "sh_staff_replied_stage_id": [22, "Open"], "sh_customer_replied_stage_id": False}]
STAGES_ROWS = [{"id": 4, "name": "New", "sequence": 0, "sh_next_stage": [22, "Open"], "is_done_button_visible": False, "is_cancel_button_visible": False},
               {"id": 22, "name": "Open", "sequence": 1, "sh_next_stage": [21, "Closed"], "is_done_button_visible": False, "is_cancel_button_visible": False},
               {"id": 21, "name": "Closed", "sequence": 4, "sh_next_stage": False, "is_done_button_visible": False, "is_cancel_button_visible": False}]


def _fake_transport(uid: int = 2241) -> MagicMock:
    # FILL IN: same body as test_odoo_toolkit.py:57-80 (config=OdooConfig(...), uid, name="json2", AsyncMock authenticate/execute_kw/version/close)
    ...


def _make_helpdesk_toolkit(transport: MagicMock | None = None) -> OdooHelpdeskToolkit:
    return OdooHelpdeskToolkit(url="https://odoo.example.com", database="", username="hd", password="key", timeout=30,
                               transport=transport or _fake_transport())


def test_init_uses_helpdesk_keys_not_generic_odoo_keys(monkeypatch):
    import parrot_tools.odoo.helpdesk as hd
    monkeypatch.setattr(hd, "ODOO_HELPDESK_URL", "https://hd.example.com"); monkeypatch.setattr(hd, "ODOO_HELPDESK_USER", "hd-user")
    monkeypatch.setattr(hd, "ODOO_HELPDESK_APIKEY", "hd-key"); monkeypatch.setattr(hd, "ODOO_HELPDESK_DATABASE", "")
    import parrot_tools.odoo.toolkit as base
    monkeypatch.setattr(base, "ODOO_URL", "https://generic.example.com"); monkeypatch.setattr(base, "ODOO_DATABASE", "prod")
    tk = OdooHelpdeskToolkit()
    assert (tk.config.url, tk.config.username, tk.config.password, tk.config.database) == ("https://hd.example.com", "hd-user", "hd-key", "")


# FILL IN: test_init_keeps_empty_database_when_generic_database_is_set (explicit database="" + base ODOO_DATABASE="prod" → ""),
#   test_init_prefers_apikey_over_password, test_init_explicit_args_win, test_confirming_tools_is_union_with_base,
#   test_get_tools_registers_helpdesk_and_inherited_tools (names include "odoo_get_ticket" and "odoo_search_records"; tk.tool_prefix == "odoo"),
#   test_list_models_includes_helpdesk_models (execute_kw returns True → "sh.helpdesk.ticket" in models),
#   test_resolve_ref_exact_ilike_ambiguous_missing (side_effect sequences; ValueError messages), test_company_stage_config_is_cached (two RPCs once),
#   test_only_open_uses_company_close_and_cancel_stages / _falls_back_to_last_stage, test_search_tickets_builds_domain_and_uses_list_fields
#   (assert the ("stage_id","not in",[21]) clause and the search_read kwargs), test_get_ticket_loads_extra_fields_and_lifecycle
#   (read → extra rows → normalised: ticket.extra_fields, lifecycle.role == "new") — each asserting exact execute_kw tuples
```
**Why**: same AsyncMock discipline as `test_odoo_toolkit.py`; `ROLES_ROW`/`STAGES_ROWS` are the live staging values so the AC21 tests mirror reality.

### FILL IN checklist
- [ ] `_TICKET_DEFAULT_FIELDS`; bounded by `HelpdeskTicket` wire fields
- [ ] `_resolve_ref` search sequence + errors; bounded by AC13
- [ ] `_company_stage_config` company read + role mapping; bounded by AC21
- [ ] `list_models` loop; bounded by AC6
- [ ] five remaining reference tools; bounded by spec §3 M5 list
- [ ] `search_tickets` clause assembly; bounded by AC21/AC13
- [ ] `list_my_tickets`, `get_ticket_history`, `get_ticket_messages`, `get_ticket_extra_fields`; bounded by spec §2 envelopes
- [ ] test module: stub block, `_fake_transport`, the listed tests

---

## Acceptance Criteria

- [ ] AC2, AC3 (spec): config isolation incl. empty database.
- [ ] AC5: `get_tools()` names are `odoo_*` for helpdesk **and** inherited tools; `tool_prefix == "odoo"`.
- [ ] AC6, AC7, AC13, AC21 (spec).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py -q`
- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q` — base toolkit untouched

Run with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the blueprint test list (13 tests).

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 Overview rules 3–5, §3 M2/M5, §6, §7).
3. **Check dependencies** — TASK-3892, TASK-3895, TASK-3896 `done`.
4. **Verify the Codebase Contract** — re-run both `grep -c` on `odoo/__init__.py`; confirm `_DEFAULT_KNOWN_MODELS` and `list_models` lines in `toolkit.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; remove every `raise NotImplementedError`.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the three listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3897 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note** (state how `only_open` behaved against the test roles), then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
