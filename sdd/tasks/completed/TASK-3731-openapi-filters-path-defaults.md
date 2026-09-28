# TASK-3731: OpenAPIToolkit: operation filters, tag recording, max_tools and path_defaults

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1**, first half (the cookie-session half is TASK-3732). Hooba's OpenAPI
document has 970 operations; FEAT-602 exposes a bounded, default-deny subset, and the
account id (`{accountId}`) must be injected by the toolkit, never supplied by the LLM
(design research S2, S4). Today `OpenAPIToolkit` generates one tool per operation with
no filtering, does not record tags, and exposes every path parameter as a required
schema field (`openapitoolkit.py:366-446, 500-603, 812-837`).

This task adds, backward compatibly: keyword-only `path_defaults`, `include_tags`,
`exclude_paths`, `exclude_methods`, `operation_filter`, `max_tools`; `operation['tags']`;
filter application inside `_parse_operations`; `path_defaults` hidden from the schema
and always winning in `_build_operation_url`. With every new argument left at its
default, generated tools, names and schemas are byte-identical to today (AC-4).

---

## Scope

- Add `Callable`, `Sequence` to the `typing` import.
- Add keyword-only constructor params `path_defaults`, `include_tags`, `exclude_paths`, `exclude_methods`, `operation_filter`, `max_tools`; store them before `_parse_operations()` runs.
- Add `_keep_operation(method, path, tags) -> bool` applying, in order: include_tags (first tag), exclude_methods, exclude_paths (`re.search` on the raw path), operation_filter.
- In `_parse_operations`, skip operations `_keep_operation` rejects and record `'tags'` on each kept operation.
- After `_parse_operations()`, raise `ValueError` when `max_tools` is set and exceeded (message names both counts).
- In `_create_pydantic_schema`, do not add a field for a path parameter whose name is in `path_defaults`.
- In `_build_operation_url`, substitute `path_defaults` first; a caller value for a defaulted name is ignored and logged at WARNING.
- Write `packages/ai-parrot/tests/tools/test_openapi_filters.py`.

**NOT in scope**: cookie auth, `login_hook`, `extra_headers`, retries (TASK-3732); anything Hooba-specific.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | typing import, ctor params, `_keep_operation`, filters in `_parse_operations`, schema + URL path defaults |
| `packages/ai-parrot/tests/tools/test_openapi_filters.py` | CREATE | unit tests for filters, tags, max_tools, path_defaults |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.tools.openapitoolkit import OpenAPIToolkit   # verified: packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py:15
# inside openapitoolkit.py (already present):
from typing import Dict, List, Any, Optional, Union      # verified: openapitoolkit.py:22 — this task adds Callable, Sequence
import re                                                # verified: openapitoolkit.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/openapitoolkit.py
class OpenAPIToolkit(AbstractToolkit):                                        # line 45
    def __init__(self, spec, service, base_url=None, api_key=None, auth_type: str = "bearer",
                 auth_header="Authorization", api_key_location="header", api_key_name="api_key",
                 credentials=None, use_proxy=False, timeout=30, debug=False, **kwargs)   # lines 62-77
    # line 161-162:  "# Parse operations from spec" / "self.operations = self._parse_operations()"
    # line 165:      "self.is_single_operation = len(self.operations) == 1"
    def _parse_operations(self) -> List[Dict[str, Any]]                       # lines 366-446
    #   loop: for path, path_item in self.spec.get('paths', {}).items(): for method in [...]:  (lines 380-383)
    #   line 386: "operation_spec = path_item[method]"
    #   operations.append({... 'description': operation_spec.get('description', ''), })   (lines 436-444)
    def _create_pydantic_schema(self, operation) -> type[BaseModel]            # lines 500-603
    #   lines 515-522: "# Add path parameters (always required)" / for param in operation['parameters'].get('path', []): ...
    def _create_method_name(self, operation) -> str                            # lines 672-693 — names unchanged by this task
    def _build_operation_url(self, operation, params) -> str                   # lines 812-837
    #   lines 829-834: "# Substitute path parameters" loop; line 836 "# Combine with base URL"
```

### Does NOT Exist
- ~~`operation["tags"]`~~ — not recorded today; this task adds it.
- ~~`OpenAPIToolkit(include_tags=..., exclude_paths=..., operation_filter=..., max_tools=..., path_defaults=...)`~~ — none exist yet.
- ~~`_keep_operation`~~ — new in this task.
- ~~`auth_type="cookie"`~~, ~~`login_hook`~~, ~~`extra_headers`~~ — TASK-3732, do not add here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/openapitoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_openapi_filters.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._parse_operations",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._create_pydantic_schema",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._build_operation_url",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._create_method_name"
  ]
}
```

---

## Implementation Notes

- Filter order is fixed by the spec (M1 skeleton): include_tags → exclude_methods → exclude_paths → operation_filter.
  `include_tags` checks the operation's **first** tag only (Hooba tags every operation with exactly one).
- `exclude_methods` compares upper-case; normalise the stored tuple with `.upper()`.
- `operation_filter` receives `(METHOD_UPPER, raw_path)` — the raw OpenAPI path with braces (`/accounts/{accountId}/invoices`).
- `path_defaults` precedence (S4): defaults are substituted FIRST; a caller-supplied value for a defaulted name is dropped with
  `self.logger.warning("Ignoring caller value for defaulted path parameter %s", name)` — never log the value itself.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Extend the `typing` import — *why*: the new params are typed `Callable`/`Sequence`.
2. Add the keyword-only params to `__init__` and store them before `_parse_operations()` — *why*: `_parse_operations` and `_create_pydantic_schema` read them.
3. Add `_keep_operation` and call it in `_parse_operations`; record tags — *why*: filtering must happen before tool generation so filtered operations never become tools.
4. Enforce `max_tools` right after parsing — *why*: a construction-time guard (spec §7 tool budget).
5. Skip defaulted path params in the schema; substitute defaults first in the URL — *why*: S4, the LLM can never see or override `accountId`.
6. Write the tests; run the two pre-existing OpenAPI suites unchanged — *why*: AC-4 backward compatibility.

### `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` (MODIFY)
```python
# (a) occurrences: 1 (verified: grep -c 'from typing import Dict, List, Any, Optional, Union' openapitoolkit.py)
# REPLACE line 22:
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

# (b) occurrences: 2 for '**kwargs' → disambiguated with context (verified: openapitoolkit.py:75-77)
# REPLACE the signature tail
#         debug: bool = False,
#         **kwargs
#     ):
# WITH:
        debug: bool = False,
        *,
        path_defaults: Optional[Dict[str, Any]] = None,
        include_tags: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
        exclude_methods: Optional[Sequence[str]] = None,
        operation_filter: Optional[Callable[[str, str], bool]] = None,
        max_tools: Optional[int] = None,
        **kwargs
    ):
# and document the six params in the Args: section of the docstring.

# (c) occurrences: 1 (verified: grep -c '        # Parse operations from spec' openapitoolkit.py) — line 161
# BEFORE — insert above `        # Parse operations from spec`:
        # Operation filters and path defaults (FEAT-602) — read by _parse_operations,
        # _create_pydantic_schema and _build_operation_url.
        self._path_defaults: Dict[str, Any] = dict(path_defaults or {})
        self._include_tags = frozenset(include_tags) if include_tags else None
        self._exclude_paths = [re.compile(p) for p in (exclude_paths or ())]
        self._exclude_methods = frozenset(m.upper() for m in (exclude_methods or ()))
        self._operation_filter = operation_filter

# (d) occurrences: 1 (verified: grep -c 'self.is_single_operation = len(self.operations) == 1' openapitoolkit.py) — line 165
# BEFORE — insert above `        # OPTIMIZATION 3: Detect if this is a single-operation spec`:
        if max_tools is not None and len(self.operations) > max_tools:
            raise ValueError(
                f"OpenAPIToolkit '{service}': {len(self.operations)} operations exceed max_tools={max_tools}"
            )

# (e) occurrences: 1 (verified: grep -c '                operation_spec = path_item\[method\]' openapitoolkit.py) — line 386
# AFTER — insert below `                operation_spec = path_item[method]`:
                tags = list(operation_spec.get('tags') or [])
                if not self._keep_operation(method.upper(), path, tags):
                    continue

# (f) occurrences: 1 (verified: grep -c "'description': operation_spec.get('description', '')," openapitoolkit.py) — line 443
# AFTER — insert below that line (still inside the operations.append({...}) dict):
                    'tags': tags,

# (g) new method — insert directly above `    def _normalize_path_for_method_name(` (occurrences: 1):
    def _keep_operation(self, method: str, path: str, tags: List[str]) -> bool:
        """Return True when an operation survives the configured filters.

        Order: include_tags (first tag) → exclude_methods → exclude_paths → operation_filter.

        Args:
            method: Upper-case HTTP method.
            path: Raw OpenAPI path, braces included.
            tags: The operation's tags as declared in the spec.

        Returns:
            True to generate a tool for this operation.
        """
        # FILL IN: apply the four filters in the fixed order; include_tags uses tags[0] (no tags → rejected
        #          when include_tags is set); exclude_paths uses pattern.search(path) — bounded by AC-3
        raise NotImplementedError

# (h) occurrences: 2 for the path-param loop → disambiguated with the preceding comment (verified: openapitoolkit.py:515-516)
# REPLACE
#         # Add path parameters (always required)
#         for param in operation['parameters'].get('path', []):
# WITH:
        # Add path parameters (always required) — except toolkit-supplied defaults (FEAT-602)
        for param in operation['parameters'].get('path', []):
            if param['name'] in self._path_defaults:
                continue

# (i) occurrences: 1 (verified: grep -c '        # Substitute path parameters' openapitoolkit.py) — line 829
# BEFORE — insert above `        # Substitute path parameters`:
        # Toolkit-supplied path defaults win over caller values (FEAT-602, S4)
        for name, value in self._path_defaults.items():
            if name in params:
                self.logger.warning("Ignoring caller value for defaulted path parameter %s", name)
            path = path.replace(f"{{{name}}}", str(value))
```
**Why this shape**: every change is additive and guarded by the new keyword-only arguments, so the
existing bearer/apikey/basic users and `tests/test_openapi*.py` see identical behaviour (AC-4). Filtering in
`_parse_operations` (not after tool generation) is what keeps `max_tools` honest. The URL-substitution loop
at (i) runs before the existing loop, so the existing loop finds no `{accountId}` placeholder left to fill.

### `packages/ai-parrot/tests/tools/test_openapi_filters.py` (CREATE)
```python
"""FEAT-602 TASK-3731 — OpenAPIToolkit operation filters, tags, max_tools, path_defaults."""
import logging

import pytest

from parrot.tools.openapitoolkit import OpenAPIToolkit


def _spec() -> dict:
    """Small inline spec: two tags, GET/POST/DELETE, one {accountId} path."""
    # FILL IN: an OpenAPI 3.0 dict with servers=[{"url": "https://api.test"}] and operations:
    #   GET  /accounts/{accountId}/invoices        tags [Invoice]
    #   POST /accounts/{accountId}/invoices        tags [Invoice]
    #   POST /accounts/{accountId}/invoices/{invoiceId}:issue  tags [Invoice]
    #   DELETE /accounts/{accountId}/invoices/{invoiceId}      tags [Invoice]
    #   GET  /accounts/{accountId}/contacts        tags [Contact]
    raise NotImplementedError


def test_defaults_generate_every_operation_unchanged():
    """No new args → same operation count and names as before."""
    # FILL IN


def test_include_tags_first_tag_only():
    # FILL IN


def test_exclude_methods_and_paths():
    # FILL IN: exclude_methods=("DELETE",), exclude_paths=(r":issue$",)


def test_operation_filter_receives_upper_method_and_raw_path():
    # FILL IN: record calls; assert ("GET", "/accounts/{accountId}/contacts") seen; returning False drops it


def test_tags_recorded_on_operations():
    # FILL IN


def test_max_tools_exceeded_raises():
    with pytest.raises(ValueError, match="max_tools"):
        OpenAPIToolkit(spec=_spec(), service="t", max_tools=1)


def test_path_defaults_hidden_from_schema():
    # FILL IN: "accountId" not in the generated tool's _args_schema.model_fields


def test_path_defaults_override_caller_value(caplog):
    # FILL IN: _build_operation_url(op, {"accountId": 1}) with path_defaults={"accountId": 23549}
    #          → URL contains 23549, WARNING logged, "1" never logged
```

### FILL IN checklist
- [ ] `openapitoolkit.py::OpenAPIToolkit._keep_operation` — fixed filter order; bounded by AC-3
- [ ] `test_openapi_filters.py::_spec` and every test body — bounded by AC-2, AC-3, AC-4

---

## Acceptance Criteria

- [ ] AC-2 (spec): `path_defaults` parameters are absent from every generated tool schema and substituted into the URL; a caller value never overrides them.
- [ ] AC-3 (spec, filter half): `include_tags`, `exclude_paths`, `exclude_methods`, `operation_filter`, `max_tools` filter generation; overflow raises `ValueError`.
- [ ] AC-4 (spec): `packages/ai-parrot/tests/test_openapi_toolkit.py` and `packages/ai-parrot/tests/test_openapi.py` pass unchanged.
- [ ] `ruff check` and `black --check` clean on the touched file.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot/tests/tools/test_openapi_filters.py -q`
- `pytest packages/ai-parrot/tests/test_openapi_toolkit.py -q`
- `pytest packages/ai-parrot/tests/test_openapi.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_defaults_generate_every_operation_unchanged` | backward compatibility |
| `test_include_tags_first_tag_only` | only `Invoice` ops survive `include_tags=("Invoice",)` |
| `test_exclude_methods_and_paths` | DELETE and `:issue` dropped |
| `test_operation_filter_receives_upper_method_and_raw_path` | callable contract |
| `test_tags_recorded_on_operations` | `operation['tags']` present |
| `test_max_tools_exceeded_raises` | `ValueError` naming both counts |
| `test_path_defaults_hidden_from_schema` | no `accountId` field |
| `test_path_defaults_override_caller_value` | default wins, WARNING, value not logged |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3731
- Feature: hooba-toolkit
- Implementation SHA: ef067d53dbe25b4945748e70f975dd7fd1780d6b
- Closed at (UTC): 2026-09-25T17:13:05+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 2 |
| fix_commits | 0 |
| merge_tier_engine_outcome | failed (workspace-wide import-impact sweep hit ~90 pre-existing unrelated failures/collection-errors across ai-parrot-client-google/grok, ai-parrot-embeddings, ai-parrot-integrations, ai-parrot-loaders, ai-parrot-pipelines, parrot-formdesigner, ai-parrot/tests collection errors in unrelated modules alpaca/zoom/shell_tool/cmc_fear_greed/coingecko/notification/aiohttp-symbols) |
| orchestrator_targeted_verification | packages/ai-parrot/tests/tools/test_openapi_filters.py: 8/8 passed (worktree). packages/ai-parrot/tests/test_openapi.py + test_openapi_toolkit.py: 11 failed/43 passed IDENTICAL on worktree and on unmodified origin/dev baseline (pre-existing prance-library drift, not caused by this task). packages/ai-parrot/tests/tools/: 53 failed both on worktree (2109 passed) and on dev baseline (2101 passed) -- the +8 delta is exactly this task's new tests; zero regressions attributable to this diff. |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 200.3s · Tokens: n/a |
| verification_method | Ran pytest directly (PYTHONPATH override) with the two compiled Cython extensions (parrot.utils.types, parrot.utils.parsers.toml) temporarily copied in from the identical-source main checkout (types.pyx/toml.pyx diffed byte-identical) since worktrees have no compiled .so per project's known limitation; removed both temp .so copies afterward (never committed, git status clean). |
