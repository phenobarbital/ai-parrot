# TASK-3779: QuerySlugSource tenant/principal/MultiQS/close + to_qs_principal

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The Python executor (TASK-3780) fetches every linked source through
`QuerySlugSource`. Today that class cannot route a QuerySource **tenant**, cannot carry a
FEAT-150 **principal** (in-process slug PBAC), never dispatches **MultiQS**, and never
**closes** its `QS` instance (`query_slug.py:151-162`). This task adds all four as
keyword-only, backwards-compatible arguments, plus the `PermissionContext → QSPrincipal`
mapper `to_qs_principal` that FEAT-150 prescribed as the ai-parrot follow-up (spec §8,
resolved 2026-09-25). Implements S4 (one normalised MultiQuery frame), S8 (close in
`finally`), AC4 (tenant routed explicitly), AC17, AC18 (principal passed through).

---

## Scope

- Add keyword-only `tenant`, `is_multiquery`, `multi_output`, `principal`, `definition` to
  `QuerySlugSource.__init__` (all default to today's behaviour).
- Forward `tenant=` / `principal=` / `definition=` to `QS(...)` in BOTH `prefetch_schema`
  (L110) and `fetch` (L151); never pass `residual=`.
- When `is_multiquery`, `fetch` dispatches `MultiQS(slug=, conditions=, tenant=, principal=,
  definition=)` via a new lazy slot `_get_multiqs()` (mirror of `_get_qs()`), and normalises
  its `DataFrame | dict[str, DataFrame]` output to ONE frame: the frame named `multi_output`,
  else `"result"`, else the single frame (S4, `parrot_tools/querysource/results.py:77-79`
  precedent). An empty/missing result → empty `pd.DataFrame()`.
- `fetch` closes the `QS`/`MultiQS` instance in a `finally` (S8).
- When QuerySource returns an `error` that is an exception instance, raise the existing
  `RuntimeError` **`from error`** so TASK-3780's `map_query_error` can walk `__cause__`.
- `cache_key` gains `:t=<tenant>` when `tenant` is set; the principal is NEVER part of the key.
- Add module-level `to_qs_principal(pctx, *, channel="ui_surfaces") -> QSPrincipal`.
- Write unit tests with a fake `QS`/`MultiQS` (monkeypatch the lazy slots).

**NOT in scope**: `MultiQuerySlugSource` (N independent slugs — unchanged; the spec's
"N descriptors + `union`" decision replaces it for linked surfaces); the executor
(TASK-3780); any QuerySource-side change; `AuthorizingDataSource` (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` | MODIFY | tenant/principal/definition/multiquery kwargs, `_get_multiqs`, close in finally, `to_qs_principal`, tenant-aware `cache_key` |
| `packages/ai-parrot/tests/tools/test_query_slug_tenant.py` | CREATE | unit tests (fake QS / MultiQS) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, MultiQuerySlugSource  # query_slug.py:36,165
from parrot.tools.dataset_manager.sources.base import DataSource   # imported in query_slug.py:16 as `from .base import DataSource`
from parrot._imports import lazy_import                            # query_slug.py:17
from parrot.auth.permission import PermissionContext, UserSession, build_principal_context  # permission.py:81,21,166
# querysource 5.1.1 (installed; ../querysource tag 5.1.1) — import LAZILY only (optional extra "db"):
from querysource.queries.qs import QS                 # qs.py:50
from querysource.queries.multi import MultiQS         # multi/__init__.py:100
from querysource.auth.principal import QSPrincipal    # auth/principal.py:21 (frozen dataclass)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
QS = None                                             # L20 — module-level patch slot
def _get_qs():                                        # L23-33 lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
class QuerySlugSource(DataSource):                    # L36
    def __init__(self, slug: str, prefetch_schema_enabled: bool = True,
                 permanent_filter: Optional[Dict[str, Any]] = None) -> None   # L51-56
    @property cache_key -> str                        # L67-80: "qs:{slug}" or "qs:{slug}:f={md5[:8]}"
    async def prefetch_schema(self) -> Dict[str, str] # L93; conditions = {"querylimit": 1, **permanent_filter} L109; qs_cls(slug=self.slug, conditions=conditions) L110
    async def fetch(self, **params) -> pd.DataFrame   # L122; force_refresh pop L139-141; merged = {**params, **permanent_filter} L143;
                                                      # qy = qs_cls(slug=self.slug, conditions=merged) L151; df, error = await qy.query(output_format='pandas') L152;
                                                      # error → RuntimeError L154-155; non-DataFrame → RuntimeError L157-160
class MultiQuerySlugSource(DataSource):               # L165 (untouched)

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True) class UserSession:            # L21: user_id: str, tenant_id: str, roles: frozenset[str], metadata: dict (L46-49)
@dataclass class PermissionContext:                   # L81: session, request_id, channel, trace_context, extra (L123-127)
    user_id / tenant_id / roles properties            # L129-142
def to_eval_context(context) -> EvalContext:          # L208 — MAPPING PRECEDENT: username=session.user_id,
    # groups=list(metadata.get("groups", [])), roles=list(session.roles), programs=list(metadata.get("programs", []))  L228-237

# querysource 5.1.1 (/home/jesuslara/proyectos/querysource)
class QS(BaseQuery):                                  # queries/qs.py:50
    def __init__(self, slug='', conditions=None, request=None, loop=None, *, tenant=None,
                 definition=None, principal=None, residual=None, **kwargs)   # qs.py:56-68
    async def query(self, output_format=None)          # qs.py:457 -> (result, error)
    async def close(self)                              # qs.py:628
    # principal ⇒ enforce_principal(SLUG, slug, "slug:execute") BEFORE store resolution (qs.py:224-231);
    # TenantError in {query_not_found, tenant_not_available} with principal → QueryAccessDenied (qs.py:47, 246-250)
class MultiQS(BaseQuery):                             # queries/multi/__init__.py:100
    def __init__(self, slug=None, queries=None, files=None, query=None, conditions=None, request=None,
                 loop=None, user_session=None, *, tenant=None, definition=None, principal=None, **kwargs)  # :106-121
    async def query(self)                              # :277 -> (result, options); result is DataFrame | dict[str, DataFrame]
    async def close(self)                              # inherited from queries/base.py:113 (BaseQuery)
@dataclass(frozen=True) class QSPrincipal:            # auth/principal.py:21
    user_id: str; username: str | None = None; groups: tuple = (); roles: tuple = (); programs: tuple = ()
    superuser: bool = False; tenant_id: str | None = None; channel: str = "library"; authz_backend: str | None = None
    # __post_init__: ValueError when user_id blank; sequences normalised to tuple[str]

# packages/ai-parrot-tools/src/parrot_tools/querysource/results.py:77-79 — S4 precedent:
#   frames = result if isinstance(result, dict) else {"result": result}
```

### Does NOT Exist
- ~~`QuerySlugSource(tenant=…)`, `principal=`, `definition=`, `is_multiquery=`, `multi_output=`~~ — added by this task.
- ~~`_get_multiqs` in `query_slug.py`~~ — added by this task (the toolkit's `parrot_tools.querysource._qs.get_multiqs` is a DIFFERENT module; core must not import `parrot_tools`).
- ~~`to_qs_principal`~~ — added by this task.
- ~~`QS.close()` called in `QuerySlugSource.fetch`~~ — never today (S8).
- ~~`PermissionContext.groups` / `.programs` / `.username` / `.superuser`~~ — not attributes; read `pctx.session.metadata` (to_eval_context precedent).
- ~~`MultiQS.query(output_format=...)`~~ — MultiQS.query() takes no arguments and returns `(result, options)`.
- ~~`QS(residual=…)` usage~~ — exists upstream but MUST NOT be passed (spec non-goal).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_query_slug_tenant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource.fetch",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource.prefetch_schema",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource.cache_key",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#_get_qs",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#to_eval_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every new argument is **keyword-only** and defaults to today's behaviour — the existing
  DatasetManager call sites and `test_authorizing_data_source.py`/`test_rls_injection.py` must
  keep passing untouched (AC11).
- querysource stays a **lazy** import (extra `db`) — `to_qs_principal` imports `QSPrincipal`
  inside the function, like `_get_qs()` does.
- `tenant_id` on the principal is informational only (logs); it never selects a store — the
  descriptor's `tenant` does (AC4). Do not derive `tenant` from `pctx`.
- `resolve(None)` silently falls back to `public.queries` (spec §7 gotcha): the tests MUST assert
  the `tenant=` kwarg is actually passed.
- `self.logger` for logging; Google docstrings; 120-col lines.

### References in Codebase
- `parrot_tools/querysource/toolkit.py:226-240` — `qs.close()` in `finally` precedent.
- `parrot_tools/querysource/results.py:77-79` — MultiQuery single-frame normalisation precedent.
- `parrot/auth/permission.py:228-237` — PermissionContext → PBAC userinfo mapping precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Add `MultiQS = None` + `_get_multiqs()` right below `_get_qs()` — *why*: tests monkeypatch the lazy slot exactly like `_get_qs` (spec §4 `fake_qs` fixture patches both).
2. Extend `__init__` with the keyword-only block and store the values — *why*: executor (TASK-3780) constructs one source per descriptor entry.
3. Make `cache_key` tenant-aware — *why*: DatasetManager caches would collide across tenants (spec §7).
4. Build a private `_qs_kwargs()` helper returning `{"tenant":…, "principal":…, "definition":…}` with `None` values dropped — *why*: a QuerySource build < 5.1.1 must not receive unknown kwargs when nobody uses the feature, and both call sites stay identical.
5. Rewrite `fetch` around a `try/finally` that closes the instance; dispatch MultiQS when `is_multiquery` — *why*: S8 / S4.
6. Pass `_qs_kwargs()` in `prefetch_schema`; return `{}` for `is_multiquery` sources — *why*: a MultiQuery pipeline run for a 1-row schema probe is too costly and schema is taken from the real fetch.
7. Add `to_qs_principal` at module bottom — *why*: FEAT-150 follow-up; one mapper reused by every owner-context lane.
8. Write the tests.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` (MODIFY) — lazy MultiQS slot
```python
# occurrences: 1 (verified: grep -c 'class QuerySlugSource(DataSource):' packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py)
# BEFORE — insert immediately above `class QuerySlugSource(DataSource):` (verified: query_slug.py:36)
MultiQS = None  # type: ignore[assignment,misc]


def _get_multiqs():
    """Lazily import MultiQS from querysource. Returns None if not installed."""
    global MultiQS
    if MultiQS is not None:
        return MultiQS
    try:
        _mq_mod = lazy_import("querysource.queries.multi", package_name="querysource", extra="db")
        MultiQS = _mq_mod.MultiQS
        return MultiQS
    except ImportError:
        return None
```

### `query_slug.py` (MODIFY) — constructor + cache_key
```python
# occurrences: 1 (verified: grep -c '        permanent_filter: Optional\[Dict\[str, Any\]\] = None,' query_slug.py)
# REPLACE the __init__ signature/body at query_slug.py:51-60 (anchor `        permanent_filter: Optional[Dict[str, Any]] = None,` L55)
    def __init__(
        self,
        slug: str,
        prefetch_schema_enabled: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        *,
        tenant: Optional[str] = None,
        is_multiquery: bool = False,
        multi_output: Optional[str] = None,
        principal: Optional["QSPrincipal"] = None,
        definition: Optional["LoadedDefinition"] = None,
    ) -> None:
        self.slug = slug
        self.prefetch_schema_enabled = prefetch_schema_enabled
        self._permanent_filter: Dict[str, Any] = permanent_filter or {}
        self.tenant = tenant
        self.is_multiquery = is_multiquery
        self.multi_output = multi_output
        self._principal = principal
        self._definition = definition
        self.logger = logging.getLogger(__name__)

    def _qs_kwargs(self) -> Dict[str, Any]:
        """Keyword-only QS/MultiQS kwargs (tenant/principal/definition); None values are omitted."""
        kwargs = {"tenant": self.tenant, "principal": self._principal, "definition": self._definition}
        return {k: v for k, v in kwargs.items() if v is not None}

# cache_key (L67-80): after computing `base` (and the optional ":f=" suffix), append f":t={self.tenant}" when tenant is set.
# FILL IN: exact placement of the ":t=" segment — bounded by: key differs per tenant, identical with/without principal
#          (test_query_slug_cache_key_tenant), and unchanged ("qs:{slug}" / "qs:{slug}:f=…") when tenant is None (AC11).
```
Also add under `if TYPE_CHECKING:` (the name is already imported at L12):
```python
if TYPE_CHECKING:  # pragma: no cover
    from querysource.auth.principal import QSPrincipal
    from querysource.tenants import LoadedDefinition
```
**Why this shape**: keyword-only arguments keep every positional caller intact; `_qs_kwargs()` is the single place both QS call sites read from, so prefetch and fetch can never diverge on tenant (the `resolve(None)` → public fallback is silent).

### `query_slug.py` (MODIFY) — fetch
```python
# occurrences: 2 (verified: grep -c 'qs_cls(slug=self.slug' query_slug.py) — disambiguated: this block replaces the FETCH site,
#   context:   qs_cls = _get_qs()                       (L145)
#              ...
#              qy = qs_cls(slug=self.slug, conditions=merged)   (L151)
#              df, error = await qy.query(output_format='pandas')  (L152)
# REPLACE query_slug.py:145-162 (from `qs_cls = _get_qs()` inside fetch through `return df`)
        if self.is_multiquery:
            qs_cls = _get_multiqs()
        else:
            qs_cls = _get_qs()
        if qs_cls is None:
            raise RuntimeError(
                "querysource package is required for QuerySlugSource. "
                "Install it with: pip install querysource"
            )
        qy = qs_cls(slug=self.slug, conditions=merged, **self._qs_kwargs())
        try:
            if self.is_multiquery:
                result, _options = await qy.query()
                df = self._select_multi_frame(result)
                error = None
            else:
                df, error = await qy.query(output_format='pandas')
        finally:
            try:
                await qy.close()
            except Exception as exc:  # noqa: BLE001 — close must never mask the query outcome
                self.logger.debug("QS close failed for slug '%s': %s", self.slug, exc)

        if error:
            if isinstance(error, BaseException):
                raise RuntimeError(f"QuerySource slug '{self.slug}' failed: {error}") from error
            raise RuntimeError(f"QuerySource slug '{self.slug}' failed: {error}")

        if not isinstance(df, pd.DataFrame):
            raise RuntimeError(f"QuerySource slug '{self.slug}' did not return a DataFrame")
        return df

    def _select_multi_frame(self, result: Any) -> pd.DataFrame:
        """Normalise MultiQS output to ONE frame: multi_output, else 'result', else the single frame (S4)."""
        # FILL IN: selection — bounded by S4 / results.py:77-79: dict → frames[multi_output] (KeyError →
        #          RuntimeError naming the available frame names), else frames["result"], else the only frame when
        #          len == 1, else RuntimeError; a bare DataFrame is returned as-is; None / empty → pd.DataFrame()
        #          (test_multiquery_empty_frame expects rows: [] downstream, not an error).
        raise NotImplementedError
```
**Why**: QuerySource exceptions (`QueryAccessDenied`, `TenantError`) raised by `query()` propagate unchanged; returned-error exceptions are chained via `from error` so TASK-3780's `map_query_error` can find them on `__cause__`. `close()` runs even on failure (S8).

### `query_slug.py` (MODIFY) — prefetch_schema
```python
# occurrences: 2 (verified: grep -c 'qs_cls(slug=self.slug' query_slug.py) — disambiguated: PREFETCH site,
#   context:   conditions = {"querylimit": 1, **self._permanent_filter}   (L109)
#              qy = qs_cls(slug=self.slug, conditions=conditions)         (L110)
# 1) at the top of prefetch_schema, after `if not self.prefetch_schema_enabled: return {}` add:
        if self.is_multiquery:
            return {}  # schema comes from the real fetch; a MultiQuery probe is too costly
# 2) replace L110 with:
            qy = qs_cls(slug=self.slug, conditions=conditions, **self._qs_kwargs())
# FILL IN: close `qy` in a finally inside the existing try (same swallow-and-debug-log rule as fetch) — bounded by S8.
```

### `query_slug.py` (MODIFY) — to_qs_principal (append at module end)
```python
# occurrences: 1 (verified: grep -c '        return pd.concat(frames, ignore_index=True)' query_slug.py)
# AFTER — append below `        return pd.concat(frames, ignore_index=True)` (verified: query_slug.py:284, last line)


def to_qs_principal(pctx: "PermissionContext", *, channel: str = "ui_surfaces") -> "QSPrincipal":
    """Map a parrot ``PermissionContext`` to a QuerySource ``QSPrincipal`` (FEAT-150).

    Mirrors ``parrot.auth.permission.to_eval_context``: identity from the session, ``groups``/``programs``/
    ``superuser`` from ``session.metadata``. ``tenant_id`` is informational only — it never selects a
    QuerySource store (the descriptor's ``tenant`` does, spec AC4).

    Args:
        pctx: The acting user's permission context (the surface OWNER on ui_surfaces lanes).
        channel: Log-only channel label carried by the principal.

    Returns:
        A frozen ``QSPrincipal``.

    Raises:
        ImportError: When querysource is not installed.
        ValueError: When the context carries a blank user id (QSPrincipal.__post_init__).
    """
    from querysource.auth.principal import QSPrincipal  # lazy: optional extra "db"

    session = pctx.session
    metadata = session.metadata or {}
    return QSPrincipal(
        user_id=session.user_id,
        username=metadata.get("username") or session.user_id,
        groups=tuple(metadata.get("groups", ())),
        roles=tuple(sorted(session.roles)),
        programs=tuple(metadata.get("programs", ())),
        superuser=bool(metadata.get("superuser", False)),
        tenant_id=session.tenant_id,
        channel=channel,
    )
```
Add `"PermissionContext"` to the `TYPE_CHECKING` block: `from parrot.auth.permission import PermissionContext`.

### `packages/ai-parrot/tests/tools/test_query_slug_tenant.py` (CREATE)
```python
"""FEAT-598 M6 — QuerySlugSource tenant/principal/MultiQS pass-through (spec §4)."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.dataset_manager.sources import query_slug as qsmod
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, to_qs_principal

pytestmark = pytest.mark.asyncio


class _FakeQuery:
    """Records constructor kwargs; returns a canned frame; counts close()."""

    instances: list["_FakeQuery"] = []

    def __init__(self, slug="", conditions=None, **kwargs):
        self.slug, self.conditions, self.kwargs, self.closed = slug, conditions, kwargs, False
        type(self).instances.append(self)

    async def query(self, output_format=None):
        # FILL IN: QS returns (frame, None); MultiQS (no output_format) returns (result, options) — bounded by the
        #          Existing Signatures above; make the canned result configurable per test.
        raise NotImplementedError

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_qs(monkeypatch):
    _FakeQuery.instances = []
    monkeypatch.setattr(qsmod, "_get_qs", lambda: _FakeQuery)
    monkeypatch.setattr(qsmod, "_get_multiqs", lambda: _FakeQuery)
    return _FakeQuery


async def test_fetch_passes_tenant(fake_qs):
    # FILL IN: tenant="acme" → kwargs["tenant"] == "acme"; tenant None → "tenant" not in kwargs
    ...


async def test_query_slug_source_closes_qs(fake_qs):
    # FILL IN: close() awaited on success AND when query() raises (S8)
    ...


async def test_multiquery_output_selection(fake_qs): ...      # FILL IN: multi_output picks the named frame (S4)
async def test_multiquery_single_frame(fake_qs): ...          # FILL IN: "result" key / single-frame fallback
async def test_multiquery_empty_frame(fake_qs): ...           # FILL IN: None/empty result → empty DataFrame
async def test_query_slug_source_cache_key_tenant(): ...      # FILL IN: differs per tenant; same with/without principal
async def test_returned_error_is_chained(fake_qs): ...        # FILL IN: error=Exception → RuntimeError.__cause__ is it


def test_to_qs_principal_mapping():
    # FILL IN: PermissionContext(UserSession(user_id, tenant_id, roles, metadata={groups, programs})) →
    #          QSPrincipal field-for-field; channel == "ui_surfaces"; tenant_id copied but informational
    ...
```

### FILL IN checklist
- [ ] `cache_key` — `:t=` placement; bounded by unchanged keys when tenant is None (AC11).
- [ ] `_select_multi_frame` — selection/empty rules; bounded by S4.
- [ ] `prefetch_schema` — close in finally; bounded by S8.
- [ ] tests — every function body; bounded by spec §4 rows for M6.

---

## Acceptance Criteria

- [ ] `QuerySlugSource(slug)` with no new kwargs behaves exactly as before (existing auth/dataset tests green).
- [ ] `tenant=`/`principal=`/`definition=` reach `QS(...)` at BOTH call sites; `residual=` never passed.
- [ ] `is_multiquery=True` dispatches `MultiQS` and returns one frame per S4.
- [ ] `QS`/`MultiQS.close()` awaited in `finally` on success and failure (AC17).
- [ ] `cache_key` includes the tenant; principal never in the key.
- [ ] `to_qs_principal` maps field-for-field, `channel='ui_surfaces'` default (AC18).
- [ ] `ruff check` clean on the modified file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_query_slug_tenant.py -q`
- `pytest packages/ai-parrot/tests/auth/test_authorizing_data_source.py -q`
- `pytest packages/ai-parrot/tests/tools/test_dataset_new_sources_integration.py -q`

---

## Test Specification

See the CREATE block above; spec §4 rows: `test_query_slug_source_closes_qs`, `test_multiquery_output_selection`,
`test_multiquery_single_frame`, `test_multiquery_empty_frame`, `test_to_qs_principal_mapping`,
`test_query_slug_source_cache_key_tenant`, plus tenant pass-through.

---

## Agent Instructions

1. Read the spec §3 Module 6 and §7 gotchas.
2. No dependencies.
3. Verify the Codebase Contract (re-grep anchors; re-read qs.py/multi signatures in the installed querysource).
4. Update the per-spec index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands (worktree: prefix `PYTHONPATH=packages/ai-parrot/src`).
7. Move this file to `sdd/tasks/completed/`, update the index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
