# TASK-5006: Section renderer and check mode (M7)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5005
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. The evaluator (TASK-5005) produces a `ConsequenceReport` and a `GoverningDossier`; this task
writes them into the spec as two generated sections — `## Governing Decisions` (before §2) and `## Consequences`
(before §8) — byte-identically for identical inputs (render mode), and recomputes/compares them without writing
(check mode). Check mode is what `/sdd-spec` uses to refuse `approved` on stale or missing sections (AC10, AC15)
and what the gate script/MCP/CLI expose (TASK-5008..P14).

---

## Scope

- Create `decisions/consequences_render.py`: `render_governing`, `render_consequences`, `splice_sections`,
  `CheckResult`, `render_spec`, `check_spec`, plus the parser that reads back the persisted digests.
- Unconfigured repos (`skipped`): render a single line `decision audit not configured in this repository`
  instead of the two sections (spec §2 portability); check reports `current` for a skipped report.
- Write `test_consequences_render.py`.

**NOT in scope**: evaluation logic (TASK-5005), CLI/MCP/script surfaces (TASK-5008..P14), template edits (TASK-5011).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences_render.py` | CREATE | Deterministic Markdown + splice + check |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences_render.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import _Strict              # verified: models.py:57
from parrot.knowledge.wiki.store import estimate_tokens                 # verified: imported by decisions/operations.py:14 and codec.py:31
from parrot.knowledge.wiki.context import truncate_to_tokens            # verified: decisions/operations.py:10
# TASK-5004 / TASK-5005 (consequences.py):
from parrot.knowledge.wiki.decisions.consequences import (
    ConsequenceReport, ConsequenceService, GoverningDossier, GENERATED_HEADINGS, EXIT_CODES,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py:48 — pattern: text body + JSON tail that is never truncated
def _dossier_result(dossier: DecisionDossier, budget_tokens: int) -> OperationResult:
    tail = json.dumps(dossier.model_dump(mode="json"))
    text_budget = budget_tokens - estimate_tokens(tail)
    ...  body, body_truncated = truncate_to_tokens(render_dossier_text(dossier), text_budget)

# TASK-5005: ConsequenceService.evaluate(spec_path, *, mode="preview") -> ConsequenceReport
#           ConsequenceService.governing(spec_path, *, budget_tokens=3000) -> GoverningDossier
#           ConsequenceService.root: Path
# TASK-5004: GENERATED_HEADINGS = ("## Governing Decisions", "## Consequences"); ConsequenceReport fields
#   status, exit_code, input_digest, evaluation_digest, snapshot, findings, diagnostics, coverage
```

Template positions (verified at HEAD in `sdd/templates/spec.md`): `## 2. Architectural Design` (line 52),
`## 8. Open Questions` (line 327). Real specs use the same `## 2.` / `## 8.` numbering.

### Does NOT Exist
- ~~`render.render_governing` / `render.pack_dossier` for gate output~~ — `pack_dossier` (render.py:109) omits records; the governing section must enumerate omissions instead (AC14).
- ~~`ConsequenceReport.rendered_at` / any timestamp field~~ — rendering is timestamp-free (AC10).
- ~~a write in `check_spec`~~ — check mode is read-only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences_render.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences_render.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#_Strict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py#_dossier_result"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Byte stability: stable ordering (entries by `decision_id`, findings by `(kind, fingerprint)`), no timestamps,
  `\n` newlines, trailing newline exactly once per section (AC10, spec §4 `test_render_byte_identical`).
- Each section's first line after the heading is a machine-readable header:
  `<!-- decision-audit: input_digest=<..> evaluation_digest=<..> rules_version=<n> status=<s> -->`.
- `## Consequences` ends with a fenced ```json block holding `report.model_dump(mode="json")` — the shortened
  Markdown above it may abbreviate messages but must list every finding (spec M7: "never drops a finding").
- `## Governing Decisions` is always rendered when configured; an empty plane renders an explicit
  "No eligible decisions govern subsystems: <list>" line (AC14). Missing fields print `not recorded`.
  When `budget_tokens` forces omission, list the omitted ids explicitly under "Omitted (budget)" (AC14).
- Splice positions: governing section inserted immediately before the first `^## 2\.` heading; consequences
  section immediately before the first `^## 8\.` heading; if a generated section already exists, replace it in place.
- Async functions read/write the spec via `asyncio.to_thread`.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module from the block below — *why*: names/signatures are fixed by spec §3 M7 and consumed by P12–P14.
2. Fill the two renderers — *why*: they carry the AC14 presentation rules.
3. Fill `splice_sections` and `_read_header` — *why*: idempotent splice is what makes render twice == render once.
4. Write tests; run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences_render.py` (CREATE)
```python
"""Deterministic Markdown for the generated spec sections (FEAT-784 Module 7)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Literal

from parrot.knowledge.wiki.decisions.consequences import (
    ConsequenceReport,
    ConsequenceService,
    GoverningDossier,
)
from parrot.knowledge.wiki.decisions.models import _Strict
from parrot.knowledge.wiki.store import estimate_tokens

GOVERNING_HEADING = "## Governing Decisions"
CONSEQUENCES_HEADING = "## Consequences"
NOT_CONFIGURED_LINE = "_decision audit not configured in this repository_"
_HEADER_RE = re.compile(r"<!-- decision-audit: input_digest=(\S+) evaluation_digest=(\S+) rules_version=(\d+) status=(\S+) -->")


class CheckResult(_Strict):
    """Outcome of a read-only check."""

    status: Literal["current", "stale", "missing"]
    report: ConsequenceReport


def _header(report: ConsequenceReport) -> str:
    rules = report.snapshot.rules_version if report.snapshot is not None else 0
    return (
        f"<!-- decision-audit: input_digest={report.input_digest} evaluation_digest={report.evaluation_digest} "
        f"rules_version={rules} status={report.status} -->"
    )


def render_governing(dossier: GoverningDossier, *, budget_tokens: int, report: ConsequenceReport) -> str:
    """``## Governing Decisions`` — complete set, budget applies to presentation only (G1, AC14)."""
    lines = [GOVERNING_HEADING, "", _header(report), ""]
    # FILL IN: empty_plane ⇒ one line naming dossier.searched_subsystems; else one entry per GoverningEntry in
    #   decision_id order: id@revision, title, statement, normative, about, targets, rationale, consequences,
    #   supersedes, freshness — "" ⇒ "not recorded". Stop adding entries when estimate_tokens(running text)
    #   would exceed budget_tokens and list the remaining ids under "Omitted (budget):" — bounded by AC14.
    return "\n".join(lines).rstrip("\n") + "\n"


def render_consequences(report: ConsequenceReport) -> str:
    """``## Consequences`` — status line, every finding, diagnostics, JSON tail."""
    lines = [CONSEQUENCES_HEADING, "", _header(report), "", f"Audit status: `{report.status}` (exit {report.exit_code})", ""]
    # FILL IN: bullet per finding (kind, BLOCKING/advisory, waived_by, participants id@rev, scope, message),
    #   then diagnostics (code, path, message), then coverage summary — never drop a finding (spec M7).
    #   Keep the "Audit status:" wording — a line starting "**Status**:" would collide with the spec's own
    #   status marker that /sdd-spec and canonicalize_spec (TASK-5004) look for.
    lines += ["```json", json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2), "```"]
    return "\n".join(lines) + "\n"


def splice_sections(text: str, governing_md: str, consequences_md: str) -> str:
    """Replace or insert both sections at fixed positions (before §2, before §8). Idempotent."""
    # FILL IN: remove existing GOVERNING/CONSEQUENCES sections (heading through line before next `^## ` or EOF);
    #   insert governing_md + blank line before first r"^## 2\." and consequences_md + blank line before first
    #   r"^## 8\."; if an anchor heading is missing, append the section at EOF. splice(splice(x)) == splice(x).
    raise NotImplementedError


def _read_header(text: str, heading: str) -> tuple[str, str] | None:
    """(input_digest, evaluation_digest) persisted under ``heading``, or None when the section is absent."""
    # FILL IN: locate the section, match _HEADER_RE on its first non-blank line after the heading.
    raise NotImplementedError


async def render_spec(service: ConsequenceService, spec_path: Path, *, budget_tokens: int) -> ConsequenceReport:
    """Evaluate, render and splice; writes the spec only when bytes change."""
    report = await service.evaluate(spec_path)
    path = service.root / spec_path
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    if report.status == "skipped":
        # FILL IN: ensure exactly one NOT_CONFIGURED_LINE (placed before `## 2.`), no generated sections.
        new_text = text
    else:
        dossier = await service.governing(spec_path, budget_tokens=budget_tokens)
        new_text = splice_sections(text, render_governing(dossier, budget_tokens=budget_tokens, report=report), render_consequences(report))
    if new_text != text:
        await asyncio.to_thread(path.write_text, new_text, encoding="utf-8")
    return report


async def check_spec(service: ConsequenceService, spec_path: Path) -> CheckResult:
    """Recompute and compare digests and content. Never writes."""
    report = await service.evaluate(spec_path)
    if report.status == "skipped":
        return CheckResult(status="current", report=report)
    text = await asyncio.to_thread((service.root / spec_path).read_text, encoding="utf-8")
    persisted = (_read_header(text, GOVERNING_HEADING), _read_header(text, CONSEQUENCES_HEADING))
    if None in persisted:
        return CheckResult(status="missing", report=report)
    # FILL IN: stale when either persisted (input, evaluation) pair != (report.input_digest, report.evaluation_digest)
    #   OR the persisted consequences body != render_consequences(report) — bounded by AC10.
    return CheckResult(status="current", report=report)
```
**Why this shape**: signatures are spec §3 M7 verbatim except `render_governing` gains a keyword-only `report`
so both sections carry the same digest header (check compares both). `render_spec` writes only on change so a
second render is a no-op on disk (byte-identical, AC10). `check_spec` short-circuits `skipped` to `current` —
portability: an unconfigured repo is never stale (AC19).

### FILL IN checklist
- [ ] `render_governing` — entries, "not recorded", budget omissions; bounded by AC14
- [ ] `render_consequences` — findings/diagnostics/coverage; keep "Audit status:" wording; bounded by spec M7, TASK-5004 canonicalization
- [ ] `splice_sections` — idempotent replace/insert; bounded by AC10
- [ ] `_read_header` — header parse
- [ ] `render_spec` skipped path — single not-configured line; bounded by spec §2 portability
- [ ] `check_spec` stale comparison; bounded by AC10

---

## Acceptance Criteria

- [ ] Two renders of identical inputs produce identical file bytes; the second render does not touch the file (AC10).
- [ ] Check reports `stale` after a new eligible record / changed source bytes; `missing` when a section is absent (AC10).
- [ ] Governing section always present when configured, explicit empty line with searched subsystems (AC14).
- [ ] Rendering the sections never changes `report.input_digest` on re-evaluation (relies on TASK-5004 canonicalization).
- [ ] `check_spec` never writes (assert file mtime/bytes unchanged).
- [ ] `ruff check` clean.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences_render.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences_render.py
import pytest
from parrot.knowledge.wiki.decisions.consequences import ConsequenceReport
from parrot.knowledge.wiki.decisions.consequences_render import (
    check_spec, render_consequences, render_spec, splice_sections,
)

SPEC = "# X\n\n## 1. Motivation\n\n## 2. Architectural Design\n\n## 8. Open Questions\n"

def test_splice_idempotent():
    once = splice_sections(SPEC, "## Governing Decisions\n\nG\n", "## Consequences\n\nC\n")
    assert splice_sections(once, "## Governing Decisions\n\nG\n", "## Consequences\n\nC\n") == once
    assert once.index("## Governing Decisions") < once.index("## 2.") and once.index("## Consequences") < once.index("## 8.")

def test_render_consequences_lists_every_finding(): ...   # FILL IN
async def test_render_byte_identical(tmp_path): ...       # FILL IN — fake ConsequenceService returning fixed report/dossier
async def test_check_detects_stale_and_missing(tmp_path): ...  # FILL IN — change fake report digest ⇒ stale; strip section ⇒ missing
async def test_check_never_writes(tmp_path): ...          # FILL IN
async def test_skipped_renders_single_line(tmp_path): ... # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §3 Module 7, AC10, AC14, AC19.
3. Confirm TASK-5005 is `done`; read its delivered `ConsequenceService` API.
4. Verify the Codebase Contract; update first on drift.
5. Implement from the blueprint; resolve every `FILL IN` within its bound.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5006 sdd-decision-audit verified`.

---

## Completion Note

Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 193s · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation (chunk 6): 232 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported. No review fixes.
