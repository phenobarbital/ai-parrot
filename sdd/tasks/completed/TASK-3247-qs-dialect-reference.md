# TASK-3247: Dialect reference, condition validators and QS payload builder

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3245, TASK-3246
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (goal G1). The QuerySource conditions dialect lives in compiled Cython parsers; the spec fixed its
content from GitHub tag `4.5.11` (finding `sdd/state/FEAT-558/findings/F007-filter-dialect.md`, identical to `dev`).
This module ships that knowledge as a static `DialectReference`, validates LLM-supplied placeholders/filters
**before** QS sees them (design research S7: the parser silently drops unsafe keys/operators), assembles the
`conditions` payload deterministically with `querylimit` capped (S8), guards the querysource version (S11) and
loads the deployment's `@variables` (§8 Q2).

---

## Scope

- Implement `dialect.py`: constants (`DIALECT_VERIFIED_AGAINST`, `OPTION_KEYS`, `LIST_OPERATORS`, `DICT_OPERATORS`,
  `KEY_SUFFIX_CHARS`), `DIALECT_REFERENCE`, `validate_placeholders`, `validate_filter`, `build_conditions`,
  `check_version_compatibility`, `load_variables`.
- Unit tests for every function and for the `.pxd` surface (skipped when querysource is absent).

**NOT in scope**: calling QS (TASK-3252), catalog reads (TASK-3248), the tool method `get_dialect_reference` (TASK-3251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` | CREATE | reference + validators + builder |
| `packages/ai-parrot-tools/tests/querysource/test_dialect.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource.errors import InvalidConditionsError      # TASK-3245
from parrot_tools.querysource.models import DialectReference, FilterValue  # TASK-3246
from parrot_tools.querysource import _qs                                 # TASK-3245 (installed_version, _load for querysource.parsers)
```

### Existing Signatures to Use
```python
# Dialect facts — querysource tag 4.5.11 == dev (finding F007); .pxd shipped in the wheel: parsers/abstract.pxd:9-76
# option keys popped from conditions (abstract.pyx:156-290, 380-410):
#   hierarchy, refresh, fields, _limit, querylimit, _offset, paged, page, group_by, grouping, order_by, ordering,
#   filter_options, qry_options, where_cond, filter, distinct, add_fields, tablename, schema, database, slug, conditions(nested)
# merge order for placeholders: {**definition.conditions, **conditions, **conditions['conditions']}  (abstract.pyx:401-404)
# keys in cond_definition → placeholders; other keys → WHERE (abstract.pyx:474-527)
# WHERE grammar (sql.pyx:113-235):
COMPARISON_TOKENS = ('>=', '<=', '<>', '!=', '<', '>',)                 # sql.pyx:25  — {op: v} form
valid_operators = ('<', '>', '>=', '<=', '<>', '!=', 'IS NOT', 'IS')    # sql.pyx:96  — [op, v] form
# key identifier check: key.rstrip('|!~#@:') must be alnum/_/. (sql.pyx:130-138); list → IN (key! → NOT IN);
# str containing BETWEEN allowed unless it contains ';' '--' '/*' UNION SELECT (sql.pyx:181-189); 'null'/'!null'; '!v'; bool
# @variables: querysource/services.py:29-33  try: from settings.settings import QUERYSOURCE_FILTERS, QUERYSOURCE_VARIABLES
#             services.py:94-96  for name, fn in QUERYSOURCE_VARIABLES.items(): QS_VARIABLES[name] = self.load_library(fn)
#             querysource/parsers/__init__.py:6  QS_VARIABLES = {}
```

### Does NOT Exist
- ~~`querysource.parsers.abstract` as importable Python source~~ — only `.so` + `.pxd`; never try to introspect the parser at runtime.
- ~~`querysource.conf.QUERYSOURCE_VARIABLES`~~ — the map lives in the deploying app's `settings.settings` (optional module).
- ~~`QS_VARIABLES` populated at import~~ — it is filled only when the QuerySource aiohttp app starts; hence `load_variables()` reads settings itself.
- ~~`build_conditions(conditions=...)` free-form dict argument~~ — the whole point is typed, separate arguments.

---

## Implementation Notes

### Key Constraints
- Pure module: no I/O, no logging except in `load_variables` (use `logging.getLogger(__name__)`).
- `validate_filter` must accept every valid form listed in the grammar and reject: unsafe key chars, unknown operator in `[op, v]`/`{op: v}`, `{}` with ≠1 key, BETWEEN strings with injection markers. Return the list of rejected keys only when `strict=False`; default `strict=True` raises `InvalidConditionsError` (AC-4 in spec §5).
- `build_conditions` omits empty sections; `querylimit = min(limit or max_rows, max_rows)`; `forced` merged last.
- `load_variables()` must never raise; `settings` may not exist.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py:143` — permanent-filter precedence (`{**params, **permanent}`)
- `sdd/state/FEAT-558/findings/F007-filter-dialect.md` — full dialect digest with excerpts

---

## Implementation Blueprint

### Steps (in order)
1. Write the constants and `DIALECT_REFERENCE` (block 1) — *why*: content is fixed by F007; the LLM reads it verbatim.
2. Write the functions (block 2), completing the two `FILL IN` markers — *why*: validation runs before QS so nothing is silently dropped (S7).
3. Write tests, including `test_dialect_reference_matches_pxd` that parses the installed `parsers/abstract.pxd` (`importlib.util.find_spec("querysource")`), skipped when absent.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` (CREATE — block 1: constants)
```python
"""QuerySource conditions dialect: static reference, validators and payload builder (spec §3 M3).

Verified against querysource 4.5.11 (GitHub tag 4.5.11 == dev): parsers/abstract.pyx:156-290,380-410,474-527
and parsers/sql.pyx:25,96,113-235. The wheel ships compiled parsers, so this module is the source of truth
for the LLM — never introspect the parser at runtime.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.models import DialectReference, FilterValue

logger = logging.getLogger(__name__)

DIALECT_VERIFIED_AGAINST: str = "4.5.11"
OPTION_KEYS: frozenset[str] = frozenset({
    "fields", "querylimit", "_limit", "_offset", "paged", "page", "group_by", "grouping", "order_by", "ordering",
    "filter", "where_cond", "filter_options", "qry_options", "refresh", "hierarchy", "distinct", "add_fields",
    "tablename", "schema", "database", "slug", "conditions",
})
LIST_OPERATORS: tuple[str, ...] = ("<", ">", ">=", "<=", "<>", "!=", "IS NOT", "IS")   # sql.pyx:96
DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")                  # sql.pyx:25
KEY_SUFFIX_CHARS: str = "|!~#@:"                                                       # sql.pyx:132
_BETWEEN_FORBIDDEN: tuple[str, ...] = (";", "--", "/*", "UNION", "SELECT")            # sql.pyx:184-189

DIALECT_REFERENCE = DialectReference(
    verified_against=DIALECT_VERIFIED_AGAINST,
    option_keys={
        "fields": "list[str] — columns to project (overrides the slug's stored fields)",
        "querylimit": "int — row limit (the toolkit sets this from `limit`, capped at max_rows); alias `_limit`",
        "_offset": "int — row offset; `paged`/`page` enable page-based pagination",
        "ordering": "list[str] — ORDER BY columns, e.g. ['-created_at'] not supported: use 'col DESC'; alias `order_by`",
        "grouping": "list[str] — GROUP BY columns; alias `group_by`",
        "filter": "dict — WHERE clauses (see where_grammar); alias `where_cond`",
        "refresh": "bool — bypass the QuerySource cache for this call",
        "filter_options": "dict — extra WHERE entries merged into filter", "qry_options": "dict — provider-specific options",
        "hierarchy": "list — hierarchical filtering rules", "distinct": "bool — SELECT DISTINCT",
        "conditions": "dict — nested placeholder values; merged over the flat ones",
    },
    placeholder_rules=[
        "A slug's stored `conditions` are DEFAULT values for the placeholders in its SQL (e.g. {firstdate}); "
        "`cond_definition` declares their types.",
        "Merge order: stored defaults < your flat keys < your nested `conditions`. Your values win.",
        "Any key that is NOT an option key and NOT a declared placeholder becomes a WHERE filter — so put ad-hoc "
        "column filters in `filter`, and only declared names in `placeholders`.",
        "Values starting with '@' call a deployment variable function (see `variables`), e.g. '@today'.",
    ],
    where_grammar=[
        "col: 'v'            → col = 'v'", "col: '!v'  or  'col!': 'v'   → col != 'v'",
        "col: ['a', 'b']    → col IN ('a','b');   'col!': [...] → NOT IN",
        "col: ['>=', 10]    → col >= 10   (first item must be one of operators_list_form)",
        "col: {'>': 10}     → col > 10    (single key from operators_dict_form)",
        "col: 'BETWEEN 1 AND 5' → (col BETWEEN 1 AND 5)  — no ';', '--', '/*', UNION, SELECT",
        "col: 'null' / '!null' → IS NULL / IS NOT NULL", "col: true → col = True",
        "Keys must be identifier-safe ([A-Za-z0-9_.] after stripping suffix chars |!~#@:); "
        "the parser silently DROPS unsafe keys/operators — this toolkit rejects them up front instead.",
    ],
    operators_list_form=list(LIST_OPERATORS),
    operators_dict_form=list(DICT_OPERATORS),
    examples=[
        {"slug": "epson_field_activity", "placeholders": {"firstdate": "2026-08-09", "lastdate": "2026-08-15"}},
        {"slug": "epson_field_activity", "placeholders": {"firstdate": "@yesterday", "lastdate": "@today"},
         "filter": {"store_id": ["101", "102"]}, "fields": ["store_id", "visits"], "limit": 50},
        {"slug": "pokemon_all_fso_odoo_new", "filter": {"warehouse_alias!": "DC01", "qty": {">": 0}},
         "ordering": ["qty DESC"], "grouping": ["warehouse_alias"]},
    ],
    notes=["Unsafe keys/operators are dropped silently by the SQL parser; validate first.",
           "querylimit is always applied by the toolkit; results are bounded by max_rows."],
)
```
**Why this shape**: the reference text is the deliverable for G1 and is derived only from verified parser source;
keep `verified_against` in sync with `DIALECT_VERIFIED_AGAINST`.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` (CREATE — block 2: functions, same file)
```python
def _key_is_safe(key: str) -> bool:
    """Mirror sql.pyx:130-138: strip suffix chars, then only alnum, '_' or '.' allowed."""
    stripped = key.rstrip(KEY_SUFFIX_CHARS)
    return bool(stripped) and all(c.isalnum() or c in "_." for c in stripped)


def validate_placeholders(placeholders: dict[str, Any], allowed: set[str]) -> None:
    """Raise InvalidConditionsError for keys not in `allowed` or present in OPTION_KEYS."""
    unknown = sorted(k for k in placeholders if k not in allowed or k in OPTION_KEYS)
    if unknown:
        raise InvalidConditionsError(
            f"Unknown placeholders {unknown}; this slug declares {sorted(allowed)}. "
            "Use `filter` for ad-hoc column conditions and the typed arguments for options."
        )


def validate_filter(filter: dict[str, FilterValue], *, strict: bool = True) -> list[str]:
    """Validate WHERE entries against the grammar; return rejected keys (raise when strict)."""
    rejected: list[str] = []
    for key, value in filter.items():
        reason = None
        if not _key_is_safe(key):
            reason = "unsafe key"
        elif isinstance(value, dict):
            # FILL IN: exactly one key and it must be in DICT_OPERATORS — bounded by sql.pyx:151-159
            reason = None
        elif isinstance(value, list):
            # FILL IN: [op, v] requires op in LIST_OPERATORS (2 items); otherwise plain IN list with scalar items — sql.pyx:160-181
            reason = None
        elif isinstance(value, str) and "BETWEEN" in value.upper():
            if any(tok in value.upper() for tok in _BETWEEN_FORBIDDEN):
                reason = "unsafe BETWEEN expression"
        if reason:
            rejected.append(f"{key}: {reason}")
    if rejected and strict:
        raise InvalidConditionsError(f"Invalid filter entries: {rejected}. See qs_get_dialect_reference().")
    return rejected


def build_conditions(*, placeholders: dict[str, Any] | None, filter: dict[str, FilterValue] | None,
                     fields: list[str] | None, ordering: list[str] | None, grouping: list[str] | None,
                     limit: int | None, offset: int | None, refresh: bool, max_rows: int,
                     forced: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble the QS `conditions` payload deterministically; `forced` wins (query_slug.py:143 precedence)."""
    payload: dict[str, Any] = dict(placeholders or {})
    if filter:
        payload["filter"] = dict(filter)
    for key, val in (("fields", fields), ("ordering", ordering), ("grouping", grouping)):
        if val:
            payload[key] = list(val)
    payload["querylimit"] = min(limit or max_rows, max_rows)
    if offset:
        payload["_offset"] = int(offset)
    if refresh:
        payload["refresh"] = True
    if forced:
        payload = {**payload, **forced}
    return payload


def check_version_compatibility(installed: str) -> str | None:
    """Return a warning when installed major.minor differs from DIALECT_VERIFIED_AGAINST (S11)."""
    want = DIALECT_VERIFIED_AGAINST.split(".")[:2]
    have = str(installed).split(".")[:2]
    if have != want:
        return (f"querysource {installed} differs from the dialect reference version {DIALECT_VERIFIED_AGAINST}; "
                "the conditions reference may be inaccurate.")
    return None


def load_variables() -> dict[str, str]:
    """Return {'@name': doc} for the deployment's variable functions (services.py:29-33,94-96); never raises."""
    names: dict[str, Any] = {}
    try:
        settings = importlib.import_module("settings.settings")
        names = dict(getattr(settings, "QUERYSOURCE_VARIABLES", {}) or {})
    except Exception:  # noqa: BLE001 — optional deploying-app module
        try:
            names = dict(importlib.import_module("querysource.parsers").QS_VARIABLES)
        except Exception:  # noqa: BLE001
            return {}
    out: dict[str, str] = {}
    for name, target in names.items():
        # FILL IN: resolve dotted-path strings via importlib (module:attr or module.attr) as services.load_library does;
        #          callables are used as-is; doc = first docstring line or '' — never raise, log at debug and skip.
        out[f"@{name}"] = ""
    return out
```
**Why this shape**: signatures are the spec skeleton; `build_conditions` is fully mechanical; the two validators
carry the only judgement calls, each bounded by the cited `sql.pyx` lines.

### FILL IN checklist
- [ ] `dialect.py::validate_filter` dict form — one key ∈ `DICT_OPERATORS`; bounded by sql.pyx:151-159
- [ ] `dialect.py::validate_filter` list form — `[op, v]` vs IN list; bounded by sql.pyx:160-181
- [ ] `dialect.py::load_variables` — dotted-path resolution + docstring line; bounded by services.py:94-96 semantics; never raise

---

## Acceptance Criteria

- [ ] `DIALECT_REFERENCE.verified_against == "4.5.11"`; every key in `OPTION_KEYS` minus aliases is documented in `option_keys`; ≥3 examples, one of them `{"firstdate": "2026-08-09", "lastdate": "2026-08-15"}`.
- [ ] `build_conditions(placeholders={"a":1}, filter={"b":"x"}, fields=None, ordering=None, grouping=None, limit=500, offset=None, refresh=False, max_rows=200, forced={"b":"forced"}) == {"a":1, "filter":{"b":"forced"}... }` — precisely: `querylimit == 200` and forced key wins at top level (forced applies to the flat dict; see test).
- [ ] `validate_filter` accepts all grammar forms and raises `InvalidConditionsError` for `{"a b": 1}`, `{"x": {"LIKE": "v"}}`, `{"x": ["~", 1]}` is accepted as IN list of 2 scalars? — NO: `"~"` is not an operator so it is an IN list → accepted; `{"x": "BETWEEN 1 AND 2; DROP"}` rejected.
- [ ] `check_version_compatibility("4.6.0")` returns a warning; `"4.5.12"` returns `None`.
- [ ] `load_variables()` returns `{}` when neither `settings.settings` nor querysource is importable; names prefixed with `@`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_dialect.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_dialect.py
import importlib.util, pathlib, re, sys, types
import pytest
from parrot_tools.querysource import dialect as d
from parrot_tools.querysource.errors import InvalidConditionsError


def test_build_conditions_shape_and_cap():
    p = d.build_conditions(placeholders={"firstdate": "2026-08-09"}, filter={"store": ["1", "2"]}, fields=["a"],
                           ordering=None, grouping=None, limit=500, offset=10, refresh=True, max_rows=200, forced=None)
    assert p == {"firstdate": "2026-08-09", "filter": {"store": ["1", "2"]}, "fields": ["a"],
                 "querylimit": 200, "_offset": 10, "refresh": True}


def test_forced_precedence():
    p = d.build_conditions(placeholders={"program": "epson"}, filter=None, fields=None, ordering=None, grouping=None,
                           limit=None, offset=None, refresh=False, max_rows=50, forced={"program": "pokemon"})
    assert p["program"] == "pokemon" and p["querylimit"] == 50


def test_validate_placeholders_unknown():
    with pytest.raises(InvalidConditionsError, match="Unknown placeholders"):
        d.validate_placeholders({"firstdate": "x", "fields": ["a"]}, allowed={"firstdate", "lastdate"})


@pytest.mark.parametrize("flt", [{"a": "v"}, {"a": "!v"}, {"a!": "v"}, {"a": ["x", "y"]}, {"a": [">=", 1]},
                                 {"a": {">": 1}}, {"a": "BETWEEN 1 AND 5"}, {"a": "null"}, {"a": True}])
def test_validate_filter_accepts(flt):
    assert d.validate_filter(flt) == []


@pytest.mark.parametrize("flt", [{"a b": 1}, {"a": {"LIKE": "v"}}, {"a": {">": 1, "<": 5}},
                                 {"a": "BETWEEN 1 AND 5; DROP TABLE x"}, {"a;": 1}])
def test_validate_filter_rejects(flt):
    with pytest.raises(InvalidConditionsError):
        d.validate_filter(flt)


def test_version_guard():
    assert d.check_version_compatibility("4.6.0")
    assert d.check_version_compatibility("4.5.12") is None


def test_load_variables_from_settings(monkeypatch):
    mod = types.ModuleType("settings.settings"); mod.QUERYSOURCE_VARIABLES = {"today": "querysource.libs.functions.first_day"}
    pkg = types.ModuleType("settings"); pkg.settings = mod
    monkeypatch.setitem(sys.modules, "settings", pkg); monkeypatch.setitem(sys.modules, "settings.settings", mod)
    assert set(d.load_variables()) == {"@today"}


def test_load_variables_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "settings", None); monkeypatch.setitem(sys.modules, "settings.settings", None)
    monkeypatch.setitem(sys.modules, "querysource.parsers", None)
    assert d.load_variables() == {}


@pytest.mark.skipif(importlib.util.find_spec("querysource") is None, reason="querysource not installed")
def test_dialect_reference_matches_pxd():
    spec = importlib.util.find_spec("querysource")
    pxd = pathlib.Path(spec.submodule_search_locations[0]) / "parsers" / "abstract.pxd"
    text = pxd.read_text()
    for attr in ("filter", "filter_options", "fields", "ordering", "grouping", "querylimit", "cond_definition", "_offset"):
        assert re.search(rf"\b{re.escape(attr)}\b", text), attr
```

---

## Agent Instructions

1. Read spec §3 Module 3, §7 Risks, and finding F007.
2. Verify TASK-3245/3246 are in `sdd/tasks/completed/`; update index → `in-progress`.
3. Write both blocks into `dialect.py`, complete the three `FILL IN` markers; write tests; run `pytest` + `ruff`.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Implemented per spec §3 Module 3 blueprint; filled the three FILL IN markers: `validate_filter`
dict form (exactly one key, must be in `DICT_OPERATORS`), list form (`[op, v]` comparison vs plain IN list of
scalars), and `load_variables` dotted-path/`module:attr` resolution with first-docstring-line extraction,
never raising. `pytest packages/ai-parrot-tools/tests/querysource/ -q` — 33 passed (includes the real
`.pxd` surface test, querysource is installed). `ruff check` on the package/tests dirs — clean (fixed E702
semicolon-statements in the spec's own test snippet to satisfy the task's "ruff check clean" AC). Implemented
manually: same repo-wide `complex_model_unavailable` block as TASK-3245/3246 (empty `strong_models` policy);
user authorized continuing the fallback loop for the rest of the feature.

**Deviations from spec**: none (semicolon statements in the test spec were reformatted to satisfy the lint AC; behavior unchanged)
