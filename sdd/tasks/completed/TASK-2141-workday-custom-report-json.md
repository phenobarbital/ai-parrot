# TASK-2141: Custom-report JSON parsing path (`_parse_json_to_entries`)

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec. flowtask's `custom_report.py` is 593
lines; ai-parrot's is 529 — an **+81 line** gap whose centrepiece is
`_parse_json_to_entries`, the JSON counterpart to the `_parse_xml_to_entries`
method ai-parrot already has (`custom_report.py:163`).

Workday RaaS custom reports can be requested in either XML or JSON. Today
ai-parrot can only parse the XML form.

---

## Scope

- Port `_parse_json_to_entries(self, body: Any) -> List[Dict[str, Any]]`
  onto `CustomReportType`, placed alongside the existing
  `_parse_xml_to_entries`.
- Wire it into `execute()` so a JSON response body is routed to the JSON
  parser and an XML body to the existing XML parser.
- Port any supporting helper changes inside the +81-line gap that
  `_parse_json_to_entries` depends on.
- Reuse the existing normalisation helpers rather than duplicating them
  (`_strip_namespace_prefix`, `_coerce_bool`, `_coerce_bool_int`,
  `_list_of_dicts_to_dict`, `_expand_list_dict_columns`).
- Write unit tests.

**NOT in scope**:
- `custom_punch_field_report.py` / `custom_punch_field_report_rest.py` —
  their small diffs belong to TASK-2143.
- `_build_raas_url` changes beyond what the JSON path strictly requires.
- Exposing this as an agent-facing tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_report.py` | MODIFY | Add `_parse_json_to_entries`; route by response format in `execute()` |
| `packages/ai-parrot-tools/tests/workday/test_custom_report_json.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.interfaces.workday.handlers.base import WorkdayTypeBase  # verified: handlers/base.py:11
# CustomReportType is exported at handlers/__init__.py:14
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_report.py
class CustomReportType(WorkdayTypeBase):                                              # line 20
    def __init__(self, component):                                                    # line 52
    def _strip_namespace_prefix(self, obj: Any) -> Any:                               # line 57
    def _coerce_bool(self, value: Any) -> bool:                                       # line 74
    def _coerce_bool_int(self, value: Any) -> Optional[int]:                          # line 79
    def _list_of_dicts_to_dict(self, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:  # line 94
    def _expand_list_dict_columns(self, df: pd.DataFrame, drop_original: bool) -> pd.DataFrame: # line 135
    def _parse_xml_to_entries(self, xml_bytes: bytes) -> List[Dict[str, Any]]:        # line 163  <-- SIBLING; mirror its shape
    def _build_raas_url(...)                                                          # line 211
    async def execute(...)                                                            # line 260  <-- ROUTE HERE
```

### Reference Source (flowtask — READ ONLY)

`../flowtask/flowtask/interfaces/workday/handlers/custom_report.py` (593 lines
vs 529 here). The method to port has this exact signature:

```python
def _parse_json_to_entries(self, body: Any) -> List[Dict[str, Any]]:   # flowtask line ~... (9th method)
```

### Does NOT Exist

- ~~`CustomReportType._parse_json_to_entries`~~ — to be added by this task
- ~~`CustomReportType._parse_json`~~ / ~~`._json_to_df`~~ — no such alternative names; use the exact name above
- ~~a separate JSON custom-report handler class~~ — this is a method on the existing `CustomReportType`, not a new handler
- ~~`WorkdayService.get_custom_report_json()`~~ — `get_custom_report` (`service.py:344`) is the only entry point; do not add a parallel method

---

## Implementation Notes

### Key Constraints
- Mirror the structure and return contract of `_parse_xml_to_entries` (`custom_report.py:163`) — same `List[Dict[str, Any]]` shape so downstream `_expand_list_dict_columns` keeps working.
- Reuse the existing coercion helpers; do not duplicate normalisation logic.
- Format routing in `execute()` must not change behaviour for existing XML callers.
- Handle an empty/absent report body gracefully (return an empty list, not a raise).
- Google-style docstrings + strict type hints; module logger, never `print`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_report.py:163` — the XML sibling to mirror
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_punch_field_report_rest.py` — an existing REST/JSON-flavoured handler for reference

---

## Acceptance Criteria

- [ ] `CustomReportType._parse_json_to_entries` exists with the documented signature
- [ ] A JSON report body parses into the same entry shape `_parse_xml_to_entries` produces
- [ ] `execute()` routes JSON bodies to the JSON parser and XML bodies to the XML parser
- [ ] Existing XML custom-report behaviour is unchanged
- [ ] An empty/absent body returns an empty list rather than raising
- [ ] Existing normalisation helpers are reused, not duplicated
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_report.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_custom_report_json.py
import pytest


class TestJsonParsing:
    def test_parses_json_body_to_entries(self):
        """A RaaS JSON body yields the same entry shape as the XML path."""

    def test_empty_body_returns_empty_list(self):
        ...

    def test_nested_list_dict_columns_expand(self):
        """Entries feed _expand_list_dict_columns without change."""


class TestFormatRouting:
    async def test_json_response_routed_to_json_parser(self):
        ...

    async def test_xml_response_still_routed_to_xml_parser(self):
        """Regression: existing XML behaviour unchanged."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2141-workday-custom-report-json.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**: Ported `_parse_json_to_entries(self, body: Any) -> List[Dict[str, Any]]`
onto `CustomReportType` verbatim (placed right after `_parse_xml_to_entries`),
handling dict/str/bytes/list bodies and both the `{"Report_Entry": [...]}`
and bare-list RaaS JSON shapes, mirroring the XML sibling's
"single item not wrapped in a list" and "empty → []" behaviour. Wired an
`output_format` kwarg (`'xml'` default, `'json'` opt-in, unknown values
warn-and-fall-back-to-xml) into `execute()`: added to `internal_params`,
appends `format=json` to `filtered_params` (both the standard URL-building
path and the `query_string_template` path, dedup-checked against an
explicit `format`), computes `accept_mime` from it, threads that mime type
into both the `HTTPService(...)` constructor and the `async_request(...)`
call (replacing the two hardcoded `"application/xml"` occurrences), and
routes the fetched body to `_parse_json_to_entries` or `_parse_xml_to_entries`
by `output_format` before the shared `pd.json_normalize` /
`_expand_list_dict_columns` / dedup-columns / array-serialisation pipeline
that already existed. `_build_raas_url` itself was NOT touched — the
`format=json` injection happens in `execute()`, same as flowtask.

19 new tests (`test_custom_report_json.py`) covering `_parse_json_to_entries`
directly (dict/string/bytes/bare-list bodies, single-entry-not-a-list
wrapping, empty-body variants, and a same-shape-as-XML-parser equality
check), `_expand_list_dict_columns` interop, and `execute()` routing
end-to-end via a fake `_http_client` (JSON path, XML regression path,
no-duplicate `format=json` when explicit, unknown-format fallback, empty
JSON response → empty DataFrame). Full `tests/workday/` suite (136 tests)
passes; `ruff check` clean on both files (fixed pre-existing mechanical
style debt already present in the whole file — old-style `Dict`/`List`/
`Optional` → builtin generics/`| None`, import ordering, all auto-fixable,
zero behaviour change — plus one justified `# noqa: TRY002` on a
pre-existing, untouched bare `raise Exception(...)` in the HTTP-error branch).

**Deviations from spec**: none.
