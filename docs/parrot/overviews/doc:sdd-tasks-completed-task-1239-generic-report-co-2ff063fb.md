---
type: Wiki Overview
title: 'TASK-1239: GenericReportComparator + Package Init'
id: doc:sdd-tasks-completed-task-1239-generic-report-comparator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Spec Module 2 (Generic Report Comparator) and Module
  3
relates_to:
- concept: mod:parrot_tools.cloudsploit.comparator
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.parser
  rel: mentions
- concept: mod:parrot_tools.s3
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
---

# TASK-1239: GenericReportComparator + Package Init

**Feature**: FEAT-184 — Agnostic S3 Report Reader Toolkit
**Spec**: `sdd/specs/agenttool-s3-readreports.spec.md`
**Status**: [x] done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements Spec Module 2 (Generic Report Comparator) and Module 3
(Package Init). It creates the `parrot_tools/s3/` package and the
`GenericReportComparator` class — the foundational diff engine that the
`S3ReportReaderToolkit` (TASK-1240) will use for its `compare_reports` tool.

The comparator provides two modes: a generic structural JSON diff (always
available) and optional parser-dispatch for scanner-aware comparison when
the scanner name is known (e.g., CloudSploit-specific diff via
`ScanComparator`).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py` with
  initial exports (just `GenericReportComparator` for now — `S3ReportReaderToolkit`
  added in TASK-1240).
- Create `packages/ai-parrot-tools/src/parrot_tools/s3/comparator.py` with
  `GenericReportComparator`.

**GenericReportComparator** must implement:

1. `__init__(self, max_changes: int = 50)` — configurable cap on the number
   of changes returned to keep LLM output manageable.

2. `compare(self, baseline: dict | bytes, current: dict | bytes, *, scanner: str | None = None) -> dict`
   - If inputs are `bytes`, decode as JSON (`json.loads`).
   - If `scanner` is known and registered in the parser registry: attempt
     parser-specific comparison:
     - For `"cloudsploit"`: parse both via `ScanResultParser().parse()` into
       `ScanResult`, then delegate to `ScanComparator().compare()`, and
       convert the `ComparisonReport` to a dict.
     - For other known scanners: fall back to `_structural_diff()` (parser
       dispatch for non-CloudSploit scanners is deferred).
   - Otherwise: fall back to `_structural_diff()`.
   - Cap `changes` list at `max_changes`.
   - Return dict with structure:
     ```python
     {
         "baseline_source": str,  # "provided" or identifier
         "current_source": str,
         "scanner": str | None,
         "comparison_mode": "generic" | "parser_dispatch",
         "summary": {
             "keys_added": int,
             "keys_removed": int,
             "keys_changed": int,
             "findings_new": int,        # only with parser_dispatch
             "findings_resolved": int,   # only with parser_dispatch
             "severity_changes": int,    # only with parser_dispatch
         },
         "changes": list[dict],  # capped at max_changes
         "truncated": bool,      # True if changes were capped
     }
     ```

3. `_structural_diff(self, baseline: dict, current: dict) -> dict`
   - Walk both dicts recursively.
   - Track: keys added, keys removed, keys changed (with path, old, new values).
   - For arrays: count elements added/removed by length comparison; do NOT
     attempt element-level identity matching (that's the parser-dispatch job).
   - Use dotted-path notation for nested keys (e.g., `"summary.total_findings"`).

4. `_dispatch_to_parser(self, baseline: bytes, current: bytes, scanner: str) -> dict | None`
   - Try-except around the parser dispatch. Return `None` on any failure
     (caller falls back to generic diff).
   - Only `"cloudsploit"` has a dedicated comparator today.

**NOT in scope**:
- The toolkit itself (TASK-1240).
- Tests (TASK-1241).
- Registry entry in `TOOL_REGISTRY` (TASK-1240).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py` | CREATE | Package init with `GenericReportComparator` export |
| `packages/ai-parrot-tools/src/parrot_tools/s3/comparator.py` | CREATE | `GenericReportComparator` implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# CloudSploit comparator — for parser dispatch
from parrot_tools.cloudsploit.comparator import ScanComparator  # verified: comparator.py:5

# CloudSploit parser — to parse bytes into ScanResult before comparing
from parrot_tools.cloudsploit.parser import ScanResultParser  # verified: parser.py:16

# CloudSploit models — for type hints
from parrot_tools.cloudsploit.models import ScanResult, ComparisonReport  # verified: models.py:70, 216

# Parser registry — to check if scanner is known
from parrot_tools.security.parsers import get_report_parser  # verified: parsers/__init__.py:31
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/comparator.py
class ScanComparator:  # line 5
    def compare(self, baseline: ScanResult, current: ScanResult) -> ComparisonReport:  # line 8

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/parser.py
class ScanResultParser:  # line 16
    def parse(self, raw_json: str, timestamp: Optional[datetime] = None) -> ScanResult:  # line 31
    # NOTE: parse() takes a STRING, not bytes. Decode bytes before calling.

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py
class ScanResult(BaseModel):  # line 70
    findings: list[ScanFinding]
    summary: ScanSummary
    raw_json: Optional[Union[dict, list]] = None
    collection_data: Optional[dict] = None

class ScanFinding(BaseModel):  # line 39
    plugin: str
    region: str
    resource: Optional[str]
    status: SeverityLevel
    # (other fields exist — read file for full list)

class ComparisonReport(BaseModel):  # line 216
    new_findings: list[ScanFinding]
    resolved_findings: list[ScanFinding]
    unchanged_findings: list[ScanFinding]
    severity_changed: list[dict]
    baseline_timestamp: Optional[datetime]
    current_timestamp: Optional[datetime]

# packages/ai-parrot-tools/src/parrot_tools/security/parsers/__init__.py
_REGISTRY: dict[str, ReportParser] = {  # line 22
    "trivy": TrivyParser(),
    "cloudsploit": CloudSploitParser(),
    "prowler": ProwlerParser(),
    "checkov": CheckovParser(),
    "aggregator": AggregatorParser(),
}
def get_report_parser(scanner: str) -> ReportParser:  # line 31
```

### Does NOT Exist

- ~~`ScanResultParser().parse(content: bytes)`~~ — `parse()` takes a `str`, not `bytes`. Decode first.
- ~~`ScanComparator().compare(dict, dict)`~~ — takes `ScanResult` objects, not raw dicts.
- ~~`get_report_parser(scanner).compare()`~~ — parsers have `parse()` and `extract_section()`, NOT `compare()`.
- ~~`parrot_tools.s3`~~ — package does not exist yet; this task creates it.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow ScanComparator pattern (comparator.py:5-71):
# - Plain class (no ABC, no toolkit)
# - Methods are synchronous (no async needed for in-memory diff)
# - Return Pydantic model or plain dict
class GenericReportComparator:
    def __init__(self, max_changes: int = 50) -> None:
        self._max_changes = max_changes

    def compare(self, baseline, current, *, scanner=None) -> dict:
        ...
```

### Key Constraints

- Keep it synchronous — all diffing is in-memory, no I/O.
- Use `json.loads()` to decode `bytes` inputs.
- Catch ALL exceptions in `_dispatch_to_parser` and return `None` on failure.
- Use dotted-path notation for nested key paths in generic diff output.
- Cap `changes` list at `max_changes` and set `truncated: True` when capped.
- Log a warning via `logging.getLogger(__name__)` when parser dispatch fails.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py` exists and exports `GenericReportComparator`
- [ ] `GenericReportComparator.compare()` handles both `dict` and `bytes` inputs
- [ ] `_structural_diff()` produces keys_added/removed/changed with dotted paths
- [ ] Parser dispatch works for `scanner="cloudsploit"` via `ScanComparator`
- [ ] Parser dispatch falls back gracefully on unknown scanners
- [ ] `changes` list capped at `max_changes` with `truncated` flag
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/s3/`
- [ ] Import works: `from parrot_tools.s3 import GenericReportComparator`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-19
**Notes**: Implemented GenericReportComparator with full structural diff (_structural_diff/_walk) and CloudSploit parser dispatch (_dispatch_to_parser). caps changes at max_changes with truncated flag. All acceptance criteria met.

**Deviations from spec**: none
