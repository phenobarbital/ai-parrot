# TASK-3784: QuerysourceToolkit tenant plumbing + describe via build_variables + MultiQS dispatch

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3782, TASK-3783
**Assigned-to**: unassigned

---

## Context

With TASK-3783 the catalog can resolve `(tenant, slug)`; the FEAT-558 tools still call `get_allowed(slug)` without a
tenant at **three** sites (`toolkit.py:165` describe, `:208` execute, `:361` run_multiquery) plus the nested
pipeline checks (`:270`, `:347`). Spec §7 gotcha: "all must gain `tenant=` or MultiQuery pipelines silently
resolve against `public`". This task threads `tenant` through `list_slugs` / `describe_slug` / `execute_slug` /
`run_multiquery`, makes `describe_slug` report `required` / `accepts_keywords` exactly as QuerySource's
`build_variables` does (AC6), and dispatches `MultiQS` (not `QS`) when the record is a MultiQuery (AC5: tenant
MultiQuery is supported by the `querysource>=5.1.1` floor — **no runtime version gate**).

Implements spec §3 Module 7 (toolkit signatures half). The new `build_linked_surface` tool is TASK-3785.

---

## Scope

- `list_slugs(..., tenant: str | None = None)` → `self._catalog.list(..., tenant=tenant)`.
- `describe_slug(slug, dry_run=False, tenant: str | None = None)`:
  `get_allowed(slug, tenant=tenant)`; `placeholders_detail` from
  `_qs.get_describe().build_variables(rec.query_raw, rec.conditions, rec.cond_definition)` (each `DescribeVariable`
  `.model_dump()`-ed into `PlaceholderInfo(name, type, default, required, accepts_keywords)`);
  `variables_supported` from its result; dry-run `QS(slug=…, tenant=tenant)`.
- `execute_slug(..., tenant: str | None = None)`: `get_allowed(slug, tenant=tenant)`;
  `QS(slug=slug, conditions=conditions, tenant=tenant)`; when `rec.is_multiquery` →
  `MultiQS(slug=slug, conditions=conditions, tenant=tenant)` normalised to ONE frame (`'result'`, else the single
  frame — S4 precedent `results.py:77-79`).
- `run_multiquery(pipeline=None, slug=None, conditions=None, tenant: str | None = None)`: tenant on the top-level
  `get_allowed`, on `_assert_pipeline_slugs_allowed` / `_policy_check` child checks, and on `MultiQS(...)`.
- Tests.

**NOT in scope**: the `build_linked_surface` tool, the module docstring tool list (TASK-3785); `reject_variable_values`
enforcement on `execute_slug` (FEAT-558 `@variables` stay valid for plain execution — only the linked wire rejects
them, TASK-3785); `QSPrincipal` on the toolkit lane (spec Non-Goal: stays trusted-service behind `programs` +
`forced_conditions`); any version gate (`supports_tenant_multiquery` is never built, AC5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | tenant kwarg on 4 tools + helpers; describe via build_variables; MultiQS dispatch |
| `packages/ai-parrot-tools/tests/querysource/test_toolkit_tenant.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource import _qs                                   # toolkit.py:18
from parrot_tools.querysource.models import PlaceholderInfo, SlugDetail   # toolkit.py:42-54 (PlaceholderInfo L50)
from parrot_tools.querysource.results import frame_to_result, multi_to_result   # toolkit.py:55
from parrot_tools.querysource.toolkit import QuerysourceToolkit           # toolkit.py:58
# TASK-3782: PlaceholderInfo.required / .accepts_keywords, SlugDetail.variables_supported, _qs.get_describe()
# TASK-3783: SlugCatalog.get_allowed(slug, *, tenant=None), SlugCatalog.list(..., tenant=None)
# querysource 5.1.1 (via _qs only): describe.build_variables(query_raw, conditions, cond_definition) -> dict
#   {'variables': list[DescribeVariable] | None, 'variables_supported': bool, 'structural_placeholders', 'warnings'
#    [, 'variables_error']}   (queries/describe.py:108-175; JSON dialect → variables None, supported False L116-118)
#   DescribeVariable(frozen): name, type, raw_type, default, required, source, accepts_keywords   (describe.py:41-51)
# QS(slug='', conditions=None, request=None, loop=None, *, tenant=None, definition=None, principal=None, residual=None)  qs.py:56-68
# MultiQS(..., *, tenant=None, definition=None, principal=None)                                   multi/__init__.py:106-121
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                                          # L58
    async def list_slugs(self, search: str | None = None, program: str | None = None, limit: int = 50
                         ) -> list[SlugSummary]:                                    # L152-158 (catalog.list L157)
    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:  # L160-188
        # rec = await self._catalog.get_allowed(slug)  L165
        # PlaceholderInfo(name=n, type=rec.cond_definition.get(n), default=rec.conditions.get(n)) L168-171
        # qs = _qs.get_qs()(slug=slug) L182; dry_run L184; close L187
    async def execute_slug(self, slug, placeholders=None, filter=None, fields=None, ordering=None, grouping=None,
                           limit=None, offset=None, refresh=False) -> ExecutionResult:  # L190-243
        # get_allowed L208; validate_placeholders L210; validate_filter L211; build_conditions L212-223;
        # qs = _qs.get_qs()(slug=slug, conditions=conditions) L226; query(output_format="pandas") L228; close L240
    async def _policy_check(self, pipeline: dict[str, Any]) -> PipelineValidation:  # L263; get_allowed(slug) L270
    async def _assert_pipeline_slugs_allowed(self, pipeline: dict[str, Any]) -> None:  # L340; get_allowed L347
    async def run_multiquery(self, pipeline=None, slug=None, conditions=None) -> MultiQueryResult:  # L349-384
        # get_allowed L361; _qs.get_multiqs()(slug=slug, conditions=…) L365; inline MultiQS(query=…) L369-371
    async def validate_pipeline(self, pipeline) -> PipelineValidation:  # L311 (calls _policy_check — keep tenant=None)
    async def save_multiquery(...)                                        # L386 (public-only, unchanged)
# results.py: frame_to_result(frame, *, slug, max_rows, applied, rejected, started); multi_to_result(result, *, max_rows, started)
# SlugRecord.is_multiquery property (catalog.py:57-60) — pipeline parsed from query_raw JSON
```

### Does NOT Exist
- ~~`describe_slug(tenant=)`, `execute_slug(tenant=)`, `list_slugs(tenant=)`, `run_multiquery(tenant=)`~~ — net-new here.
- ~~`supports_tenant_multiquery`, `TenantMultiQueryUnsupportedError`~~ — NEVER built (AC5).
- ~~`QS.get_definition()`~~ — does not exist (only `BaseProvider.get_definition()`).
- ~~`principal=` on toolkit calls~~ — out of scope (agent-tool lane stays trusted-service).
- ~~`DescribeVariable.to_placeholder()`~~ — map fields by hand via `.model_dump()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_toolkit_tenant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.list_slugs",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.describe_slug",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.execute_slug",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.run_multiquery",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit._policy_check",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit._assert_pipeline_slugs_allowed",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/models.py#PlaceholderInfo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/results.py#frame_to_result"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Tool docstrings are the LLM-facing description: every new `tenant` parameter must be explained in the
  docstring ("QuerySource tenant store schema; omit for public/legacy slugs. Routing, not security.").
- Pass `tenant=tenant` to `QS`/`MultiQS` **always** (even `None`) — tests assert the kwarg; `resolve(None)` falls
  back to public silently, so the kwarg's presence is the audit trail.
- `validate_pipeline` (public LLM tool) keeps calling `_policy_check(pipeline)` with the default `tenant=None`.
- `describe_slug` keeps every existing `SlugDetail` field; only `placeholders_detail` construction and
  `variables_supported` change.
- AC6 wording: `required` / `accepts_keywords` "exactly as QuerySource's `build_variables` does (static `required`,
  `IMPLICIT_DEFAULTS`, `or raw_type is None`)" — copy them from the `DescribeVariable`, never recompute when
  `variables` is present.

### References in Codebase
- `toolkit.py:190-243` execute_slug; `results.py` `multi_to_result` for frame-dict handling.
- `packages/ai-parrot-tools/tests/querysource/test_execute_slug.py` (`fake_qs` FakeQS pattern) and
  `test_multiquery_tools.py` (`fake_mq` FakeMultiQS pattern) — copy locally, do not cross-import fixtures that
  pull unrelated patches.

---

## Implementation Blueprint

### Steps (in order)
1. `list_slugs`: add `tenant` and forward it — *why*: spec M7 skeleton.
2. `describe_slug`: add `tenant`, forward it to `get_allowed` and the dry-run `QS`; rebuild `placeholders_detail`
   from `build_variables` — *why*: AC6 exact parity with QuerySource describe semantics.
3. `execute_slug`: add `tenant`; forward to `get_allowed` and `QS`; add the MultiQS branch — *why*: AC4/AC5.
4. `_policy_check` / `_assert_pipeline_slugs_allowed` / `run_multiquery`: add keyword `tenant` and thread it — *why*:
   the spec gotcha on the three `get_allowed` sites.
5. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY)

**Block A — list_slugs**
```python
# occurrences: 1 (verified: grep -c '    async def list_slugs(' packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py)
# REPLACE list_slugs (verified: toolkit.py:152-158) with:
    async def list_slugs(
        self, search: str | None = None, program: str | None = None, limit: int = 50, tenant: str | None = None
    ) -> list[SlugSummary]:
        """List query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug or description.
        `tenant` selects a QuerySource tenant store (its schema name); omit it for public/legacy slugs."""
        await self._open()
        records = await self._catalog.list(
            search=search, program=program, limit=max(1, min(int(limit), 500)), tenant=tenant
        )
        return [self._summary(r) for r in records]
```

**Block B — describe_slug placeholders via build_variables**
```python
# occurrences: 1 (verified: grep -c '    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:' toolkit.py)
# CHANGE the signature (toolkit.py:160) to:
    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail:
# append to its docstring: "`tenant` selects a QuerySource tenant store; each placeholder reports `required` and
#   `accepts_keywords` (UDF keywords such as TODAY/YESTERDAY are valid values when true)."
# occurrences: 3 (verified: grep -c '        rec = await self._catalog.get_allowed(slug)' toolkit.py) — disambiguated
# by context; the describe site is the one directly followed by `detail = SlugDetail(` (toolkit.py:165-166):
#         await self._open()
#         rec = await self._catalog.get_allowed(slug)
#         detail = SlugDetail(
# REPLACE those lines through `placeholders_detail=[...],` (L164-171) with:
        await self._open()
        rec = await self._catalog.get_allowed(slug, tenant=tenant)
        placeholders_detail, variables_supported = self._placeholders_detail(rec)
        detail = SlugDetail(
            **self._summary(rec).model_dump(),
            placeholders_detail=placeholders_detail,
            variables_supported=variables_supported,
# and in the dry-run branch (toolkit.py:182) change `_qs.get_qs()(slug=slug)` to `_qs.get_qs()(slug=slug, tenant=tenant)`.

# NEW helper — insert directly above `async def get_dialect_reference` (verified: toolkit.py:146, occurrences: 1)
    def _placeholders_detail(self, rec: SlugRecord) -> tuple[list[PlaceholderInfo], bool]:
        """PlaceholderInfo list + variables_supported, from querysource build_variables (describe.py:108)."""
        out = _qs.get_describe().build_variables(rec.query_raw, rec.conditions, rec.cond_definition)
        variables = out.get("variables")
        supported = bool(out.get("variables_supported", False))
        if variables is None:
            # FILL IN: JSON-dialect / MultiQuery (supported False) and parse-error (variables_error) cases — keep the
            # legacy FEAT-558 list (name/type/default from rec.placeholder_names) with required=False and
            # accepts_keywords = (type in describe.KEYWORD_TYPES or type is None); return (list, supported) —
            # bounded by AC6 and backward compatibility of qs_describe_slug for MultiQuery slugs
            raise NotImplementedError
        return [
            PlaceholderInfo(**{k: v for k, v in var.model_dump().items() if k in PlaceholderInfo.model_fields})
            for var in variables
        ], supported
```
**Why**: the helper keeps the three-line field mapping in one place and TASK-3785 reuses `describe_slug`'s output;
`PlaceholderInfo.model_fields` filtering drops `raw_type`/`source` without inventing a mapping.

**Block C — execute_slug tenant + MultiQS dispatch**
```python
# occurrences: 1 (verified: grep -c '    async def execute_slug(' toolkit.py)
# add `tenant: str | None = None,` after `refresh: bool = False,` (toolkit.py:200); docstring gains the tenant sentence.
# execute site of the 3-occurrence anchor — disambiguate by its trailing comment (toolkit.py:208):
#         rec = await self._catalog.get_allowed(slug)  # tenant check first (spec §2)
# → becomes:
        rec = await self._catalog.get_allowed(slug, tenant=tenant)  # tenant check first (spec §2)
# REPLACE `qs = _qs.get_qs()(slug=slug, conditions=conditions)  # qs.py:42` (toolkit.py:226, occurrences: 1) and the
# try/except/finally that follows (L227-243) with:
        exc_mod = _qs.get_exceptions()
        if rec.is_multiquery:
            return await self._execute_multi(
                slug, conditions=conditions, tenant=tenant, rejected=rejected, started=started, exc_mod=exc_mod
            )
        qs = _qs.get_qs()(slug=slug, conditions=conditions, tenant=tenant)  # qs.py:56-68
        # … existing try / except DataNotFound / SlugNotFound / QueryException / finally close / frame_to_result
        #   (toolkit.py:227-243) kept verbatim …

    async def _execute_multi(
        self, slug: str, *, conditions: dict[str, Any], tenant: str | None, rejected: list[str], started: float,
        exc_mod: Any,
    ) -> ExecutionResult:
        """Run a stored MultiQuery slug through MultiQS(tenant=) and normalise its output to ONE frame (S4)."""
        mq = _qs.get_multiqs()(slug=slug, conditions=dict(conditions), tenant=tenant)  # multi/__init__.py:106-121
        try:
            result, _options = await asyncio.wait_for(mq.query(), timeout=self.multiquery_timeout)
        except exc_mod.DataNotFound:
            return frame_to_result(None, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected,
                                   started=started)
        except asyncio.TimeoutError as exc:
            raise QuerysourceToolkitError(f"multiquery timed out after {self.multiquery_timeout}s") from exc
        except exc_mod.QueryException as exc:
            raise QuerysourceToolkitError(str(exc)) from exc
        # FILL IN: frame = result if DataFrame; dict → result["result"] if present else the single value when
        # len == 1, else raise QuerysourceToolkitError naming the frames (use qs_run_multiquery for many) —
        # bounded by spec S4 ('result', else the single frame; results.py:77-79 precedent)
        raise NotImplementedError
```
**Why**: the QS path stays verbatim (existing tests); MultiQuery gets its own helper so AC5 ("tenant MultiQuery
executes through MultiQS(tenant=)") is testable without touching the single-query branch.

**Block D — run_multiquery + child checks**
```python
# occurrences: 1 each (verified: grep -c for '    async def _policy_check(self, pipeline: dict[str, Any]) -> PipelineValidation:',
#   '    async def _assert_pipeline_slugs_allowed(self, pipeline: dict[str, Any]) -> None:', '    async def run_multiquery(')
# _policy_check (L263): signature → `async def _policy_check(self, pipeline: dict[str, Any], *, tenant: str | None = None)`;
#   L270 `await self._catalog.get_allowed(slug)` → `await self._catalog.get_allowed(slug, tenant=tenant)`
# _assert_pipeline_slugs_allowed (L340): add `*, tenant: str | None = None`; L347 → get_allowed(referenced_slug, tenant=tenant)
# run_multiquery (L349-351): add `tenant: str | None = None` as the last parameter + docstring sentence;
#   run_multiquery site of the 3-occurrence anchor is the one inside `if slug is not None:` (toolkit.py:360-361):
#         if slug is not None:
#             rec = await self._catalog.get_allowed(slug)
#   → `rec = await self._catalog.get_allowed(slug, tenant=tenant)`; pass `tenant=tenant` to both
#   `_assert_pipeline_slugs_allowed(...)` and `_policy_check(...)` calls inside run_multiquery, and to both
#   `_qs.get_multiqs()(...)` constructions (L365 and L369-371).
# FILL IN: nothing else — save_multiquery/validate_pipeline stay public (tenant None) — bounded by spec M7 scope
```

### `packages/ai-parrot-tools/tests/querysource/test_toolkit_tenant.py` (CREATE)
```python
"""FEAT-598 TASK-3784 — tenant plumbing, describe via build_variables, MultiQS dispatch."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit


@pytest.fixture
def fake_engines(patched_qs, monkeypatch):
    """FakeQS / FakeMultiQS recording constructor kwargs (patterns: test_execute_slug.py, test_multiquery_tools.py)."""
    state: dict = {"qs": None, "mq": None}
    # FILL IN: FakeQS(**kw) records state["qs"]=kw, query() → (DataFrame, None), close(); FakeMultiQS(**kw) records
    # state["mq"]=kw, query() → ({"result": DataFrame}, {}); monkeypatch _qs.QS / _qs.MultiQS / _qs.get_exceptions
    raise NotImplementedError


async def test_execute_slug_passes_tenant(fake_engines, monkeypatch):
    # FILL IN: patch tk._catalog.get_allowed (after _open) to assert tenant == "acme" and return the epson record;
    # execute_slug(..., tenant="acme") → fake_engines["qs"]["tenant"] == "acme"
    raise NotImplementedError


async def test_execute_slug_multiquery_dispatches_multiqs(fake_engines):
    # FILL IN: a record with is_multiquery True (pokemon_all_fso_odoo_new) → MultiQS (not QS) with tenant kwarg,
    # one normalised frame in the ExecutionResult — bounded by AC5 / S4
    raise NotImplementedError


async def test_placeholder_info_required_accepts_keywords(patched_qs, fake_rows):
    pytest.importorskip("querysource.queries.describe")
    # FILL IN: a SQL row with {firstdate} {store_id} and cond_definition {"store_id": "integer"}, no stored conditions:
    # firstdate.required is False (IMPLICIT_DEFAULTS) and accepts_keywords True (untyped); store_id.required True,
    # accepts_keywords False — bounded by AC6 / spec test test_placeholder_info_required_accepts_keywords
    raise NotImplementedError


async def test_describe_json_dialect_not_supported(patched_qs):
    pytest.importorskip("querysource.queries.describe")
    # FILL IN: MultiQuery slug → variables_supported False, legacy placeholder list kept
    raise NotImplementedError


async def test_run_multiquery_tenant_threads_all_sites(fake_engines):
    # FILL IN: stored multiquery slug + tenant="acme": every get_allowed call (top-level + children) received
    # tenant="acme" and MultiQS kwargs carry tenant="acme" — bounded by spec §7 "all three get_allowed sites"
    raise NotImplementedError


async def test_list_slugs_forwards_tenant(patched_qs, monkeypatch):
    # FILL IN: monkeypatch SlugCatalog.list to capture tenant; list_slugs(tenant="acme") forwards it
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `_placeholders_detail` fallback when `variables is None`; bounded by AC6 + backward compat.
- [ ] `_execute_multi` frame normalisation; bounded by S4.
- [ ] Block D threading (mechanical).
- [ ] All test bodies + `fake_engines` fixture.

---

## Acceptance Criteria

- [ ] `describe_slug` reports `required` / `accepts_keywords` exactly as `build_variables` (AC6).
- [ ] `execute_slug(tenant="acme")` constructs `QS(..., tenant="acme")`; a MultiQuery record dispatches
      `MultiQS(..., tenant="acme")` (AC4, AC5) — no version gate anywhere.
- [ ] Every `get_allowed` call site in `toolkit.py` passes `tenant=` (grep shows none without it except
      `validate_pipeline`'s default path).
- [ ] Existing `test_execute_slug.py`, `test_multiquery_tools.py`, `test_toolkit_core.py` pass unchanged.
- [ ] `ruff check` / `black --check` clean.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_tenant.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_execute_slug.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3784
- Feature: a2ui-linked-surfaces
- Implementation SHA: 2eb39f07f1416496d39a95a101374dd64e76d56f
- Closed at (UTC): 2026-09-26T02:05:11+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: 82 pre-existing failures unrelated to this task's diff, spanning unrelated test files (bots/prompts, chrome_runner env/network, porygon_identity_migration, rag/vector_context_integration, voicebot, infographic_toolkit_a2ui_wiring pydantic model_rebuild). Verified WORSE (88 failed) on clean origin/dev with the identical test selection -- confirmed pre-existing test-suite instability, not a regression. Plus known pre-existing formdesigner/embeddings/collection-error signatures. See issue:181bd0c01bb4. |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: 267.8s - Tokens: n/a |
