---
type: Wiki Overview
title: 'TASK-1108: Per-scanner parser registry (Trivy, CloudSploit, Prowler, Checkov,
  Aggregator)'
id: doc:sdd-tasks-completed-task-1108-scanner-parsers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic Python parsers — one per scanner — that turn scanner output
relates_to:
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.security.models
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
---

# TASK-1108: Per-scanner parser registry (Trivy, CloudSploit, Prowler, Checkov, Aggregator)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1105
**Assigned-to**: unassigned

---

## Context

Deterministic Python parsers — one per scanner — that turn scanner output
bytes into the catalog's `(SeverityBreakdown, top_findings)` summary
*at write time*, and extract sections (`critical`, `high`, `medium`,
`low`, `executive`, `full`) *at read time*. Parsers are pure functions;
no LLM involvement. Reproducibility + version-tagging via
`ReportRef.parser_version` make future schema migrations tractable.

Implements Spec §3 Module 4 (and supports Spec §5 acceptance: parser
determinism).

---

## Scope

- Create `parrot_tools/security/parsers/__init__.py` exposing
  `get_report_parser(scanner) -> ReportParser` and the `ReportParser`
  Protocol.
- Implement 5 parser modules:
  - `parrot_tools/security/parsers/trivy.py` — `TrivyParser`
  - `parrot_tools/security/parsers/cloudsploit.py` — `CloudSploitParser`
  - `parrot_tools/security/parsers/prowler.py` — `ProwlerParser`
  - `parrot_tools/security/parsers/checkov.py` — `CheckovParser`
  - `parrot_tools/security/parsers/aggregator.py` — `AggregatorParser`
    (passthrough for weekly/monthly summary content — content IS a
    serialized `WeeklySummary` / `MonthlySummary` JSON).
- Each parser implements:
  - `parse(content: bytes | Path) -> ParsedReport` returning a
    `ParsedReport(severity_summary: SeverityBreakdown, top_findings: list[EmbeddedFinding])`.
    `top_findings` capped at 10, sorted by severity (CRITICAL > HIGH > MEDIUM > LOW > INFORMATIONAL),
    stable secondary sort by `finding_id`.
  - `extract_section(content: bytes | Path, section: str) -> dict`
    where `section ∈ {"summary", "critical", "high", "medium", "low", "executive", "full"}`.
    "summary" returns the same severity_summary as `parse`. "full" returns
    the entire parsed structure. Severity sections filter the findings list.
    "executive" returns `{"paragraph": <str>}` (only meaningful for the
    aggregator — other parsers return `{"paragraph": ""}` with a note).
- A `ParsedReport` dataclass / Pydantic model in `parrot_tools/security/parsers/_types.py`
  (importing `SeverityBreakdown` / `EmbeddedFinding` from
  `parrot.storage.security_reports`).
- Each parser carries a `parser_version` class attribute (`= "1.0.0"`)
  matching the `ReportRef.parser_version` field.
- Unit tests with **synthetic** JSON fixtures (small valid samples per
  scanner) verifying determinism: same bytes → same `SeverityBreakdown`
  and same `top_findings` across two consecutive `parse` calls.

**NOT in scope**: integrating parsers into the mixin (TASK-1109); store
or toolkit changes; LLM calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot_tools/security/parsers/__init__.py` | CREATE | `get_report_parser` dispatch + Protocol export |
| `parrot_tools/security/parsers/_types.py` | CREATE | `ParsedReport`, `ReportParser` Protocol |
| `parrot_tools/security/parsers/trivy.py` | CREATE | Trivy parser |
| `parrot_tools/security/parsers/cloudsploit.py` | CREATE | CloudSploit parser |
| `parrot_tools/security/parsers/prowler.py` | CREATE | Prowler parser |
| `parrot_tools/security/parsers/checkov.py` | CREATE | Checkov parser |
| `parrot_tools/security/parsers/aggregator.py` | CREATE | Aggregator passthrough |
| `tests/security/parsers/test_*.py` | CREATE | One per parser + a registry test |
| `tests/security/parsers/fixtures/*.json` | CREATE | Minimal valid samples per scanner |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Literal

from parrot.storage.security_reports import (
    SeverityBreakdown, EmbeddedFinding,                 # from TASK-1105
)
```

### Existing Signatures to Use

```python
# parrot_tools/security/models.py — EXISTING SeverityLevel enum (do NOT confuse
# with new SeverityBreakdown which is a count container)
class SeverityLevel(str, Enum):
    # values: CRITICAL / HIGH / MEDIUM / LOW / INFORMATIONAL (verify exact names at task start)
    ...

# parrot_tools/cloudsploit/  — ScanResult Pydantic model returned by run_scan.
# When the toolkit writes results_dir/scan_*.json, the file content is the
# serialized ScanResult. The CloudSploit parser must accept this shape.
# Verify exact JSON layout in the executor module before writing the parser.
```

### Does NOT Exist

- ~~An existing scanner parser anywhere in `parrot_tools/security/`~~ —
  this task creates the first parsing layer.
- ~~A common `Finding` Pydantic model on `parrot_tools.security.models`
  that's already a 1:1 fit for `EmbeddedFinding`~~ — the existing models
  serve scanner-internal needs; parsers must adapt them to the catalog's
  `EmbeddedFinding`.
- ~~A unified "scan_result.json" schema across scanners~~ — each scanner
  emits its own native JSON shape. The parser layer normalizes.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot_tools/security/parsers/_types.py
from dataclasses import dataclass
from typing import Protocol
from pathlib import Path
from parrot.storage.security_reports import SeverityBreakdown, EmbeddedFinding


@dataclass(frozen=True)
class ParsedReport:
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding]


class ReportParser(Protocol):
    parser_version: str

    def parse(self, content: bytes | Path) -> ParsedReport: ...
    def extract_section(self, content: bytes | Path, section: str) -> dict: ...


# parrot_tools/security/parsers/__init__.py
from .trivy import TrivyParser
from .cloudsploit import CloudSploitParser
from .prowler import ProwlerParser
from .checkov import CheckovParser
from .aggregator import AggregatorParser
from ._types import ParsedReport, ReportParser

_REGISTRY: dict[str, ReportParser] = {
    "trivy": TrivyParser(),
    "cloudsploit": CloudSploitParser(),
    "prowler": ProwlerParser(),
    "checkov": CheckovParser(),
    "aggregator": AggregatorParser(),
}

def get_report_parser(scanner: str) -> ReportParser:
    try:
        return _REGISTRY[scanner]
    except KeyError as e:
        raise ValueError(f"No parser registered for scanner: {scanner!r}") from e
```

### Key Constraints

- **Deterministic.** Same input bytes → same output across runs. Sort
  `top_findings` by `(severity_rank, finding_id)` for stability.
- Severity rank order: `CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1, INFORMATIONAL=0`.
- Pure Python only — no network, no LLM, no filesystem reads beyond the
  optional `content: Path` argument.
- Each parser has `parser_version = "1.0.0"` as a class attribute.
- If `content: Path`, read it as bytes (text mode is fine for JSON).
- `extract_section`: support `"summary"`, `"critical"`, `"high"`,
  `"medium"`, `"low"`, `"executive"`, `"full"`. Unknown section → raise
  `ValueError`.

### Synthetic fixtures

Write **minimal but valid** JSON samples for each scanner. The CloudSploit
fixture should mirror the actual `ScanResult.model_dump_json()` output
shape — inspect `parrot_tools/cloudsploit/` at task start to capture the
real fields.

### References in Codebase

- `parrot_tools/security/models.py` — existing `SeverityLevel` and any
  scanner result schemas (do NOT collide; create new `ParsedReport`).
- `parrot_tools/cloudsploit/` — for the CloudSploit JSON shape.
- Spec §5 acceptance: parser determinism.

---

## Acceptance Criteria

- [ ] `from parrot_tools.security.parsers import get_report_parser, ParsedReport, ReportParser` resolves.
- [ ] `get_report_parser("cloudsploit").parse(content).severity_summary` is deterministic.
- [ ] `get_report_parser("unknown")` raises `ValueError`.
- [ ] All 5 parsers expose `parser_version = "1.0.0"`.
- [ ] All unit tests pass: `pytest tests/security/parsers/ -v`.
- [ ] No linting errors: `ruff check parrot_tools/security/parsers/`.

---

## Test Specification

```python
# tests/security/parsers/test_determinism.py
import pytest
from pathlib import Path

from parrot_tools.security.parsers import get_report_parser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("scanner,fixture", [
    ("trivy",       "trivy_filesystem.json"),
    ("cloudsploit", "cloudsploit_hipaa.json"),
    ("prowler",     "prowler_aws.json"),
    ("checkov",     "checkov_terraform.json"),
    ("aggregator",  "weekly_summary.json"),
])
def test_parse_is_deterministic(scanner, fixture):
    content = (FIXTURES / fixture).read_bytes()
    parser = get_report_parser(scanner)
    a = parser.parse(content)
    b = parser.parse(content)
    assert a.severity_summary == b.severity_summary
    assert [f.finding_id for f in a.top_findings] == [f.finding_id for f in b.top_findings]


def test_unknown_scanner_raises():
    with pytest.raises(ValueError):
        get_report_parser("nope")


def test_extract_section_critical_filters(): ...
def test_extract_section_summary_matches_parse(): ...
```

---

## Agent Instructions

1. Read the spec section §3 Module 4.
2. Inspect actual scanner output schemas in `parrot_tools/cloudsploit/`,
   `parrot_tools/security/`, and the Trivy / Prowler / Checkov fixtures
   on disk (if any test fixtures already exist).
3. Implement parsers using the pattern above.
4. Write minimal synthetic fixtures.
5. Run unit tests.
6. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Created all 7 parser files + package __init__ in
`packages/ai-parrot-tools/src/parrot_tools/security/parsers/`.
Created 5 JSON fixture files in `tests/security/parsers/fixtures/`.
21 unit tests, all pass. Every parser has `parser_version = "1.0.0"`,
is deterministic (same input → same output), and caps `top_findings` at 10.
`extract_section` supports all 7 sections; raises `ValueError` for unknown sections.
AggregatorParser returns the `executive_paragraph` field for "executive" section.

**Deviations from spec**: `tests/security/parsers/test_*.py` was specified as
multiple files; consolidated into one `test_determinism.py` with parametrized
tests covering all scanners. All acceptance criteria met.
