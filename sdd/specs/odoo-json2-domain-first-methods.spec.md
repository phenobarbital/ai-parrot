---
type: feature
base_branch: dev
projects: [ai-parrot-tools, ai-parrot]
tags: [odoo, json2, transport, aggregate-records, ledger-fix]
---

# Feature Specification: Odoo JSON-2 — map domain-first ORM methods (`read_group` family)

**Feature ID**: FEAT-614
**Date**: 2026-09-30
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next `ai-parrot-tools` patch release
**Ledger**: resolves `issue:c32c408ded92` (minor · bug · discovered by `agent:odoo_hd`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`OdooToolkit.aggregate_records` (the `odoo_aggregate_records` LLM tool) fails
against every Odoo 19 instance reached through the External JSON-2 transport.
Observed live on `pokemon.helpdesk.staging` (Odoo 19.0, `json2` transport) when
the helpdesk agent called the tool on `sh.helpdesk.ticket`; recorded in the work
ledger as `issue:c32c408ded92` and reproduced again on 2026-09-30.

The toolkit issues the legacy-shaped call
`self._execute(model, "formatted_read_group", [domain], kwargs)`
(`toolkit.py:1058`; the Odoo 16–18 branch does the same with `"read_group"` at
`:1073`). `Json2Transport._build_body` (`json2.py:90-162`) knows how to map the
positional arguments of `search`/`search_read`/`search_count`/`read`/`create`/
`write`/`unlink`/`fields_get`/`check_access_rights`/`load`, but has **no mapping
for the `read_group` family**. The call therefore falls into the generic tail of
`_build_body`, where two distinct failures occur depending on the domain:

| Domain passed by the toolkit | What `_build_body` does today | Result seen by the LLM |
|---|---|---|
| `[]` (the default — `domain or []`) | `_looks_like_ids([])` is `True` (`all()` over an empty list), so the domain is sent as `ids: []` and **no `domain` key** reaches Odoo | HTTP 422 `missing a required argument: domain` |
| non-empty, e.g. `[("stage_id.name", "=", "New")]` | not ids, one positional arg → `OdooRPCError("JSON-2 transport cannot map positional args for method 'formatted_read_group'")` | client-side `OdooRPCError` before any request |

A second, independent defect on the same path was found while verifying the fix
against the Odoo 19 source: the Odoo 19 branch of `aggregate_records` always sends
`"lazy": lazy` (`toolkit.py:1048`), but Odoo 19's
`formatted_read_group(domain, groupby=(), aggregates=(), having=(), offset=0,
limit=None, order=None)` has **no `lazy` parameter** (verified in
`odoo/odoo@19.0 addons/web/models/models.py:802-811`). Because JSON-2 forwards
the body as keyword arguments, that call would be rejected with an unexpected-
argument error even once the domain is mapped. `read_group` (Odoo ≤ 18, and still
present-but-deprecated in 19) does accept `lazy`.

### Goals

- G1. `Json2Transport.execute_kw(model, "formatted_read_group", [domain], kwargs)`
  and the same with `"read_group"` produce a JSON-2 body whose `domain` key is
  `args[0]` — for an empty domain as much as for a non-empty one — merged with
  `kwargs`, exactly like the existing `search_read` mapping.
- G2. The mapping is declared once for the whole *domain-first* method family
  (`search`, `search_read`, `search_count`, `read_group`, `formatted_read_group`,
  `web_read_group`, `formatted_read_grouping_sets`) so the next domain-first
  method does not need a fresh branch.
- G3. On Odoo 19+, `aggregate_records` no longer sends `lazy` to
  `formatted_read_group`; the Odoo 16–18 `read_group` call is unchanged.
- G4. Unit coverage for both fixes in the existing test modules, runnable without
  network.
- G5. Ledger issue `c32c408ded92` is claimed at `/sdd-start` and closed by
  `/sdd-done` with `--resolved-by spec:FEAT-614`.

### Non-Goals (explicitly out of scope)

- Changing `_looks_like_ids` so that an empty list is no longer treated as ids.
  It is what lets `read`/`write`/`unlink` keep their current behaviour, and the
  explicit domain-first mapping removes the trap for every method the toolkit
  actually calls. Recorded as a resolved question in §8.
- Normalising the differing result shapes of `read_group` (`<field>_count`,
  `__domain`) and `formatted_read_group` (`__count`, `__extra_domain`) inside
  `AggregateResult`. The envelope returns Odoo's groups verbatim today and keeps
  doing so.
- Switching Odoo 18 to `formatted_read_group` (it is not present in Odoo 18's
  `odoo/models.py`; the `>= 19` threshold stays).
- Touching the XML-RPC / JSON-RPC transports — `execute_kw` there is positional
  by nature and already works.
- Any change to `parrot/interfaces/odoointerface.py` or `parrot/clients/base.py`.

---

## 2. Architectural Design

### Overview

Two surgical changes, no new files:

1. **Transport (M1)** — `json2.py` gains a module-level constant
   `_DOMAIN_FIRST_METHODS: frozenset[str]` listing the ORM methods whose first
   positional argument is a search domain. The existing
   `if method in {"search", "search_read", "search_count"}:` branch in
   `_build_body` becomes `if method in _DOMAIN_FIRST_METHODS:` with its body
   unchanged (reject >1 positional, `body.setdefault("domain", args[0] if args
   else [])`). Because this branch precedes the generic `_looks_like_ids` tail,
   the empty-domain → `ids: []` misroute disappears for the whole family.
2. **Toolkit (M2)** — in `aggregate_records`, the Odoo 19+ branch stops putting
   `"lazy"` into `kwargs`. When the caller asked for `lazy=True` on Odoo 19+, the
   toolkit logs at `debug` level that the flag is ignored because
   `formatted_read_group` does not support it. The docstring and the
   `AggregateRecordsInput.lazy` field description say so, so the LLM-facing
   schema is honest. The Odoo 16–18 `read_group` branch keeps sending `lazy`.

Nothing changes for callers: `aggregate_records`' signature, `AggregateResult`,
the `AbstractOdooTransport` contract and every other `_build_body` branch stay
byte-identical in behaviour.

### Component Diagram

```
OdooToolkit.aggregate_records            (toolkit.py:994)
   │  Odoo ≥ 19: _execute(model, "formatted_read_group", [domain], {groupby, aggregates?, limit?, offset?, order?})
   │  Odoo ≤ 18: _execute(model, "read_group",           [domain], {groupby, fields, lazy, limit?, offset?, orderby?})
   ▼
OdooToolkit._execute                     (toolkit.py:283)  → transport.execute_kw(model, method, args, kwargs)
   ▼
Json2Transport.execute_kw                (json2.py:172)
   ▼
Json2Transport._build_body               (json2.py:90)
   ├─ method ∈ _DOMAIN_FIRST_METHODS  → body = {**kwargs, "domain": args[0] or []}     ◄── M1 (new membership)
   ├─ read / create / write / unlink / fields_get / check_access_rights / load  (unchanged)
   └─ generic ids tail / raise                                                  (unchanged, no longer reached by read_group family)
   ▼
POST /json/2/<model>/<method>  body → Odoo dispatches method(**body)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `Json2Transport._build_body` | modifies | one branch condition + one new constant |
| `OdooToolkit.aggregate_records` | modifies | Odoo 19+ kwargs construction + docstring |
| `AggregateRecordsInput.lazy` | modifies (description only) | documents "ignored on Odoo 19+" |
| `JsonRpcTransport` / `XmlRpcTransport` | untouched | positional `execute_kw`, already correct |
| `AbstractOdooTransport.execute_kw` | uses | contract unchanged |

### Data Models

No new models. `AggregateResult` (`envelopes.py:174`) and `AggregateRecordsInput`
(`inputs.py:259`) keep their fields; only the `lazy` description string changes.

### New Public Interfaces

None. `_DOMAIN_FIRST_METHODS` is module-private (underscore) inside
`parrot_tools.odoo.transport.json2`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: JSON-2 domain-first mapping | yes | constant name, membership set, branch body, error text and test names fixed below | — |
| M2: `aggregate_records` Odoo 19 kwargs | yes | drop `lazy` on 19+, `self.logger.debug` message, docstring + Field description text fixed below | — |

M1 and M2 share no file and neither imports a symbol the other adds; they may be
implemented and merged in either order or concurrently.

### Module 1: JSON-2 domain-first mapping
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  (+ tests in `packages/ai-parrot/tests/test_odoo_json2_transport.py`)
- **Responsibility**: route every domain-first ORM method through the existing
  `domain` mapping in `_build_body`.
- **Depends on**: nothing new.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py
  # (modifies json2.py:31 — insert AFTER def _looks_like_ids, BEFORE class Json2Transport)

  #: ORM methods whose first positional ``execute_kw`` argument is a search domain.
  #: ``_build_body`` maps ``args[0]`` of these to the JSON-2 ``domain`` key.
  _DOMAIN_FIRST_METHODS: frozenset[str] = frozenset({
      "search",
      "search_read",
      "search_count",
      "read_group",
      "formatted_read_group",
      "web_read_group",
      "formatted_read_grouping_sets",
  })

  # (modifies json2.py:99) — the branch condition only; its 4-line body is unchanged
  class Json2Transport(AbstractOdooTransport):           # verified: json2.py:38
      @staticmethod
      def _build_body(method: str, args: list[Any] | None, kwargs: dict[str, Any] | None) -> dict[str, Any]:  # verified: json2.py:90
          """Translate legacy ``execute_kw`` args into JSON-2 named arguments.

          Domain-first methods (``_DOMAIN_FIRST_METHODS``) map ``args[0]`` — an
          empty list when absent — to ``body["domain"]``; more than one positional
          argument raises ``OdooRPCError`` exactly as ``search_read`` does today.
          """
  ```
- **Tests to add** (same module, after `test_execute_kw_unsupported_positional_args_raise_rpc_error`, `test_odoo_json2_transport.py:141`):

  | Test | Asserts |
  |---|---|
  | `test_execute_kw_formatted_read_group_maps_domain_and_kwargs` | URL `/json/2/sh.helpdesk.ticket/formatted_read_group`; body `== {"domain": [("stage_id.name", "=", "New")], "groupby": ["team_id"], "aggregates": ["id:count"]}` |
  | `test_execute_kw_read_group_maps_domain_and_kwargs` | body `== {"domain": [...], "groupby": ["state"], "fields": ["state", "amount_total:sum"], "lazy": False}` |
  | `test_execute_kw_domain_first_empty_domain_is_sent_as_domain_not_ids` | for `formatted_read_group` with `[[]]`: body has `"domain": []` and **no** `"ids"` key |
  | `test_execute_kw_domain_first_rejects_extra_positional_args` | `execute_kw(model, "read_group", [[], ["f"], ["g"]])` raises `OdooRPCError`; `session.post` not called |

### Module 2: `aggregate_records` — Odoo 19+ kwargs
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`,
  `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py`
  (+ tests in `packages/ai-parrot/tests/test_odoo_toolkit.py`)
- **Responsibility**: send only arguments `formatted_read_group` accepts.
- **Depends on**: nothing new (independent of M1).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py  (modifies toolkit.py:994-1058)
  class OdooToolkit(AbstractToolkit):                                     # verified: toolkit.py:172
      @tool_schema(AggregateRecordsInput)                                 # verified: toolkit.py:993
      async def aggregate_records(                                        # verified: toolkit.py:994 — signature UNCHANGED
          self, model: str, group_by: list[str], measures: Optional[list[str]] = None,
          domain: Optional[list[Any]] = None, lazy: bool = False,
          limit: Optional[int] = None, offset: int = 0, order: Optional[str] = None,
      ) -> AggregateResult:
          """Group and aggregate records server-side using read_group (Odoo 16-18)
          or formatted_read_group (Odoo 19+).

          ...existing Args block, with ``lazy`` amended to:
              lazy: When True, only the first group_by level is resolved.
                  Honoured on Odoo 16-18 (``read_group``) only; Odoo 19+
                  ``formatted_read_group`` has no lazy mode and the flag is
                  ignored (a debug log line records that).
          """
      # Odoo 19+ branch: kwargs = {"groupby": group_by} (+ aggregates/limit/offset/order as today) — NO "lazy".
      # If lazy is True on that branch: self.logger.debug(
      #     "aggregate_records: lazy=True ignored — formatted_read_group (Odoo %s) has no lazy mode", odoo_version)

  # packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py  (modifies inputs.py:279-282)
  class AggregateRecordsInput(_OdooBaseInput):                            # verified: inputs.py:259
      lazy: bool = Field(
          default=False,
          description="Use lazy grouping (only first group_by level resolved). Odoo 16-18 only; ignored on Odoo 19+.",
      )
  ```
- **Tests to add / amend** (`test_odoo_toolkit.py`, Phase 1 Aggregate Records block):

  | Test | Asserts |
  |---|---|
  | amend `test_aggregate_records_calls_formatted_read_group_for_odoo_19` (`:700`) | `transport.execute_kw.await_args.args == ("sale.order", "formatted_read_group", [[]], {"groupby": ["state"]})` — i.e. `lazy` absent, domain `[]` positional |
  | `test_aggregate_records_odoo_19_ignores_lazy_flag` | call with `lazy=True`, version `19.0`: kwargs passed to `execute_kw` contain no `"lazy"` key |
  | `test_aggregate_records_odoo_17_still_sends_lazy` | version `17.0`, `lazy=True`: kwargs `["lazy"] is True` and method is `"read_group"` |

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_execute_kw_formatted_read_group_maps_domain_and_kwargs` | M1 | non-empty domain → `domain` key, kwargs merged, URL correct |
| `test_execute_kw_read_group_maps_domain_and_kwargs` | M1 | same for legacy `read_group` incl. `lazy` passthrough |
| `test_execute_kw_domain_first_empty_domain_is_sent_as_domain_not_ids` | M1 | regression for the ledger's exact 422 (`[]` misrouted to `ids`) |
| `test_execute_kw_domain_first_rejects_extra_positional_args` | M1 | >1 positional still raises `OdooRPCError`, no request sent |
| `test_execute_kw_search_read_maps_to_json2_named_body` (existing, `:80`) | M1 | must keep passing — search family behaviour unchanged |
| `test_execute_kw_unsupported_positional_args_raise_rpc_error` (existing, `:141`) | M1 | must keep passing — generic tail unchanged |
| `test_aggregate_records_calls_formatted_read_group_for_odoo_19` (amended) | M2 | exact args/kwargs on Odoo 19+, no `lazy` |
| `test_aggregate_records_odoo_19_ignores_lazy_flag` | M2 | `lazy=True` dropped on 19+ |
| `test_aggregate_records_odoo_17_still_sends_lazy` | M2 | 16–18 path unchanged |
| `test_aggregate_records_calls_read_group_for_odoo_16_18` (existing, `:674`) | M2 | must keep passing |
| `test_aggregate_records_allows_empty_group_by_global_aggregation` (existing, `:723`) | M2 | must keep passing |

### Integration Tests
| Test | Description |
|---|---|
| Manual, not gated: `odoo_aggregate_records` on `sh.helpdesk.ticket` via the `odoo_hd` agent against `pokemon.helpdesk.staging` (Odoo 19, json2) with `group_by=["stage_id"]`, `measures=["id:count"]` | Returns `AggregateResult.count > 0`; no 422. Requires the staging credentials from the environment — never committed. Record the outcome in the Completion Note. |

### Test Data / Fixtures
```python
# test_odoo_json2_transport.py — reuse the existing helpers verbatim
_config()                          # verified: test_odoo_json2_transport.py:35
_mock_aiohttp_response(body, status=200)   # verified: test_odoo_json2_transport.py:47
# pattern: with patch("aiohttp.ClientSession", return_value=session): ...   # verified: :84

# test_odoo_toolkit.py — reuse
_fake_transport(uid=1)             # verified: test_odoo_toolkit.py:58 (transport.version / execute_kw are AsyncMock)
_make_toolkit(transport)           # verified: test_odoo_toolkit.py:84
transport.version.return_value = {"server_serie": "19.0", "server_version": "19.0"}   # verified: :703
```

No E2E surface (FEAT-581): the `e2e` frontmatter key and the E2E Scenarios
subsection are intentionally omitted.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `Json2Transport._build_body("formatted_read_group", [D], K)` returns `{**K, "domain": D}` for `D = []` and for a non-empty `D`; never emits an `ids` key for this method.
- [ ] AC2. Same as AC1 for `"read_group"`, `"web_read_group"` and `"formatted_read_grouping_sets"` (the set in G2), with >1 positional argument raising `OdooRPCError` before any HTTP call.
- [ ] AC3. The existing `search`/`search_read`/`search_count` mapping is byte-for-byte unchanged in behaviour (existing tests at `test_odoo_json2_transport.py:80-146` pass unmodified).
- [ ] AC4. On Odoo ≥ 19, `aggregate_records` calls `execute_kw(model, "formatted_read_group", [domain], kwargs)` with `"lazy" not in kwargs`, whatever the `lazy` argument; `lazy=True` produces one `self.logger.debug` line.
- [ ] AC5. On Odoo ≤ 18, `aggregate_records` still calls `read_group` with `kwargs["lazy"] == lazy` and `kwargs["fields"]` as today.
- [ ] AC6. `AggregateRecordsInput.lazy.description` and the `aggregate_records` docstring state that `lazy` is ignored on Odoo 19+.
- [ ] AC7. `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot/tests/test_odoo_json2_transport.py packages/ai-parrot/tests/test_odoo_toolkit.py -q` passes, including the seven new/amended tests in §4.
- [ ] AC8. `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` is clean.
- [ ] AC9. No public signature changes: `aggregate_records`, `execute_kw`, `AggregateResult`, `AggregateRecordsInput` field set.
- [ ] AC10. Ledger: `issue:c32c408ded92` claimed at `/sdd-start` and closed by `/sdd-done FEAT-614` with `--resolved-by spec:FEAT-614`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `b6c6a9fd8` (dev, 2026-09-30). `/sdd-task` re-runs every `grep -c`.

### Verified Imports
```python
from parrot.interfaces.odoointerface import OdooRPCError            # verified: odoointerface.py:35 (class OdooRPCError(OdooError))
from parrot.interfaces.odoointerface import OdooConfig, OdooAuthenticationError, OdooConnectionError, _validate_model_name  # verified: json2.py:20-26 (already imported there)
from parrot_tools.odoo.transport.json2 import Json2Transport          # verified: transport/__init__.py:5 re-exports; tests import it at test_odoo_json2_transport.py:32
from parrot_tools.odoo.transport.base import AbstractOdooTransport    # verified: transport/base.py:11
from parrot_tools.odoo.models.envelopes import AggregateResult        # verified: envelopes.py:174; imported in toolkit.py:50-78 block
from parrot_tools.odoo.models.inputs import AggregateRecordsInput     # verified: inputs.py:259; imported in toolkit.py:90-124 block
from parrot.tools.decorators import tool_schema                       # verified: toolkit.py:46
from pydantic import BaseModel, Field                                 # Field used at inputs.py:279
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py
def _looks_like_ids(value: Any) -> bool:                                  # line 31 — returns True for int, or list where ALL items are int (so [] → True)
class Json2Transport(AbstractOdooTransport):                              # line 38
    name: str = "json2"                                                   # line 41
    @staticmethod
    def _build_body(method: str, args: list[Any] | None, kwargs: dict[str, Any] | None) -> dict[str, Any]:  # line 89-94
        # line 99:  if method in {"search", "search_read", "search_count"}:
        # line 100: if len(args) > 1: raise OdooRPCError(f"JSON-2 transport cannot map positional args for method {method!r}.")
        # line 102: body.setdefault("domain", args[0] if args else [])
        # line 152: if len(args) == 1 and _looks_like_ids(args[0]):  → body.setdefault("ids", args[0])   (generic tail)
        # line 159: raise OdooRPCError("JSON-2 transport cannot map positional args for method ... Add an explicit JSON-2 argument mapping or use the legacy jsonrpc protocol.")
    async def execute_kw(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:  # line 172-180 → self._build_body then self._request_json2
    async def _request_json2(self, model: str, method: str, body: dict[str, Any] | None = None) -> Any:  # line 66 — POST {url}/json/2/{model}/{method}, json=body

# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                                       # line 172
    self.logger = logging.getLogger(__name__)                             # line 241
    async def _execute(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:  # line 283 → transport.execute_kw
    async def _get_odoo_major_version(self) -> int | None:                # line 982 (server_info().server_serie → int major, None on failure)
    @tool_schema(AggregateRecordsInput)                                   # line 993
    async def aggregate_records(self, model, group_by, measures=None, domain=None, lazy=False, limit=None, offset=0, order=None) -> AggregateResult:  # line 994
        # line 1041: odoo_version = await self._get_odoo_major_version()
        # line 1042: use_formatted = odoo_version is not None and odoo_version >= 19
        # line 1046-1049: kwargs: dict[str, Any] = {"groupby": group_by, "lazy": lazy}     ← Odoo 19 branch (M2 removes "lazy")
        # line 1058: groups = await self._execute(model, "formatted_read_group", [domain], kwargs)
        # line 1062-1066: kwargs = {"groupby": group_by, "fields": list(group_by) + measure_fields, "lazy": lazy}   ← Odoo ≤18 branch (unchanged)
        # line 1073: groups = await self._execute(model, "read_group", [domain], kwargs)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
class AggregateRecordsInput(_OdooBaseInput):                              # line 259
    lazy: bool = Field(default=False, description="Use lazy grouping (only first group_by level resolved)")  # lines 279-282

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py
class AggregateResult(BaseModel):                                         # line 174 — groups, model, group_by, measures, count
```

### Upstream Odoo signatures (verified 2026-09-30 from odoo/odoo GitHub, read-only)
```python
# odoo/odoo@19.0 addons/web/models/models.py:802-811
def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None) -> list[dict]
# odoo/odoo@19.0 odoo/orm/models.py:2754-2755  (@api.deprecated "Since 19.0, read_group is deprecated ... use formatted_read_group")
def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True)
# odoo/odoo@18.0 odoo/models.py:2819 — read_group with the same signature; formatted_read_group NOT defined in that file
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_DOMAIN_FIRST_METHODS` | `Json2Transport._build_body` branch | `if method in _DOMAIN_FIRST_METHODS:` | `json2.py:99` |
| M2 kwargs change | `OdooToolkit._execute` → `transport.execute_kw` | unchanged call shape `[domain], kwargs` | `toolkit.py:1058`, `:283` |
| new transport tests | `session.post.call_args.kwargs["json"]` | existing mock pattern | `test_odoo_json2_transport.py:95-96` |
| new toolkit tests | `transport.execute_kw.await_args` / `.call_args_list` | AsyncMock on `_fake_transport` | `test_odoo_toolkit.py:72`, `:718` |

### Does NOT Exist (Anti-Hallucination)
- ~~`Json2Transport._DOMAIN_FIRST_METHODS`~~ — not a class attribute; M1 adds it as a **module-level** constant.
- ~~`Json2Transport.read_group()` / `.formatted_read_group()`~~ — no per-method helpers; everything goes through `execute_kw` → `_build_body`.
- ~~`OdooToolkit._read_group_kwargs()` / `_build_aggregate_kwargs()`~~ — no such helpers; do not introduce one, edit the two branches in place.
- ~~`odoo.formatted_read_group(..., lazy=...)`~~ — Odoo 19's method has no `lazy` parameter.
- ~~`formatted_read_group` in Odoo 18~~ — not defined in `odoo/models.py` on 18.0; keep the `>= 19` switch.
- ~~`tests/` at repo root, `packages/ai-parrot-tools/tests/test_odoo_*.py`~~ — the Odoo tests live in `packages/ai-parrot/tests/` (only `test_odoo_shell.py` is under `ai-parrot-tools/tests`).
- ~~`wikitoolkit ledger show`~~ — no such subcommand; inspect via `ledger context <path>` or `ledger ready --json`.

### Edit Sites (Blueprint Anchors)

Verified against: `b6c6a9fd8`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | MODIFY (insert constant after this function) | `def _looks_like_ids(value: Any) -> bool:` | `json2.py:31` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | MODIFY (replace condition) | `        if method in {"search", "search_read", "search_count"}:` | `json2.py:99` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY (docstring, `lazy` bullet) | `        or formatted_read_group (Odoo 19+).` | `toolkit.py:1006` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY (remove `"lazy": lazy,` from the Odoo 19 dict only) | `            kwargs: dict[str, Any] = {` / `                "groupby": group_by,` / `                "lazy": lazy,` (`"lazy": lazy,` alone occurs twice — :1048 is the Odoo 19 dict to edit, :1065 is the Odoo ≤18 dict to keep) | `toolkit.py:1046-1049` | 2 (ambiguous — use the 3-line context) |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY (debug log inserted just before) | `            groups = await self._execute(model, "formatted_read_group", [domain], kwargs)` | `toolkit.py:1058` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | MODIFY (description string) | `        description="Use lazy grouping (only first group_by level resolved)",` | `inputs.py:281` | 1 |
| `packages/ai-parrot/tests/test_odoo_json2_transport.py` | MODIFY (append tests after) | `async def test_execute_kw_unsupported_positional_args_raise_rpc_error():` | `test_odoo_json2_transport.py:141` | 1 |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY (amend test) | `async def test_aggregate_records_calls_formatted_read_group_for_odoo_19():` | `test_odoo_toolkit.py:700` | 1 |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY (insert new tests before) | `async def test_aggregate_records_rejects_invalid_aggregator():` | `test_odoo_toolkit.py:753` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep `_build_body` a `@staticmethod` returning a fresh dict; keep `setdefault` so an explicit `kwargs["domain"]` still wins over the positional one (existing behaviour for `search_read`).
- Error text for the >1-positional case stays the existing f-string
  `"JSON-2 transport cannot map positional args for method {method!r}."` — tests assert only on the exception type.
- Logging via `self.logger.debug(...)` with `%s` formatting (no f-strings in log calls), no `print`.
- Tests use the same aiohttp-session mock (`_mock_aiohttp_response`) and `patch("aiohttp.ClientSession", ...)` pattern as the neighbouring tests; no network, no new fixtures files.
- Run tests with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src` from a worktree (the shared venv is editable-installed against the main checkout).
- `black` line length 120; `ruff check` must stay clean (TID251 import bans apply).

### Known Risks / Gotchas
- **`_looks_like_ids([])` is `True`.** Any *other* method that reaches the generic tail with a single empty-list positional will still be sent as `ids: []`. This spec fixes the domain-first family explicitly and leaves the helper alone (Non-Goals); if a future toolkit method passes a domain positionally, add it to `_DOMAIN_FIRST_METHODS` rather than special-casing.
- **Result-shape drift between `read_group` and `formatted_read_group`** (`__count`/`__extra_domain` vs `<field>_count`/`__domain`). Unchanged by this spec; the LLM already sees raw Odoo groups. Do not "normalise" as part of this fix.
- **`having`** is accepted by `formatted_read_group` but not exposed by `aggregate_records`; not added here.
- **Odoo 19 `read_group` is deprecated but present**, so an Odoo 19 instance reached through XML-RPC/JSON-RPC that still hits the `>= 19` branch is unaffected by this spec (it uses `formatted_read_group` too, positionally).
- **Live verification needs staging credentials** (`ODOO_*` env vars for `pokemon.helpdesk.staging`, see the `odoo_hd` agent notes). Never commit them; the integration check in §4 is manual and recorded in the Completion Note, not a CI gate.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | no new dependencies |

---

## 8. Open Questions

- [x] Should `_looks_like_ids` stop treating `[]` as ids so unknown domain-first methods fail loudly instead of sending `ids: []`? — *Resolved in spec*: no; out of scope (Non-Goals). The explicit `_DOMAIN_FIRST_METHODS` mapping covers every method the toolkit calls and the helper's current semantics keep `read`/`write`/`unlink` untouched.
- [x] Does Odoo 19 `formatted_read_group` accept `lazy`? — *Resolved from upstream source*: no (`addons/web/models/models.py:802-811`); M2 drops it and documents the flag as Odoo 16–18 only.
- [x] Should the mapping set include `web_read_group` / `formatted_read_grouping_sets` even though the toolkit does not call them yet? — *Resolved in spec*: yes, they are domain-first with the same shape and cost nothing; AC2 covers them.
- [x] Should `aggregate_records` expose `having` for Odoo 19+ in a follow-up? — *Owner: Jesus Lara* (non-blocking; not part of this fix).: yes, expose having.

---

## 9. Design Research Cross-Check

> Model: — · Status: **skipped** (no accepted exploration document: the spec was seeded directly from ledger `issue:c32c408ded92` and the `--` notes; §3b's precondition is an accepted brainstorm/proposal) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-614-odoo-json2-domain-first-methods` from `origin/dev`; the `sdd-coder` engine gives each task its own sub-worktree inside it. (With only two independent tasks this could also run as a single-task branch — `/sdd-task` decides.)
- **Module dependency graph**: none. M1 (`json2.py` + transport tests) and M2 (`toolkit.py`, `inputs.py` + toolkit tests) share no file and neither imports a symbol the other adds → expected to run concurrently.
- **Shared files**: none across modules.
- **Exclusive resources**: none (no extension rebuild, lockfile or migration).
- **Cross-feature dependencies**: none. Note that FEAT-612 (`refactor-planogram-compliance`) is active on `dev` but touches no Odoo file.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Jesus Lara / Claude | Initial draft from ledger issue c32c408ded92; Odoo 19 `lazy` incompatibility added after upstream verification |
