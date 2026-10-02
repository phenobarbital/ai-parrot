# TASK-4018: FindingRouter: ledger (dedup+cap), report files, page notes

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / AC8 — where unfixable findings go.

---

## Scope

- `render_markdown(report)`; `report.json` + `report.md` written to `options.report_dir` (default `<storage_dir>/lint/`) via `asyncio.to_thread`.
- Ledger (when `options.ledger` and a `LedgerService` is given): non-fixable warning/error findings; `kind='bug'` for error else `'tech_debt'`; `severity` major for error else minor; `discovered_from=f'lint:{rule_id}'`; body ends with `<!-- lint-fp:<fingerprint> -->`; dedup against open issues; over `ledger_cap_per_rule` → one aggregate issue per rule.
- Notes (when `options.notes`): for each subject page that exists and is not `adr:` managed, append `> **Note (<date>, lint):** <message> <!-- lint-fp:... -->` once (dedup on marker) via `store.upsert_pages` read-modify-write, mirroring `WikiNoteTool`.
- Return counts `{ledger_opened, ledger_deduped, notes_added, report_files}`.

**NOT in scope**: Choosing which findings exist (rules) or fixing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/routing.py` | CREATE | FindingRouter + render_markdown |
| `packages/ai-parrot/tests/knowledge/lint/test_routing.py` | CREATE | Tests with fake ledger |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: wiki/ledger/service.py:116 from_root, :168 open_issue, :201 ready_work
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # verified: wiki/store.py:525; WikiPageRecord ~:409
```

### Existing Signatures to Use
```python
# wiki/ledger/service.py
async def open_issue(self, title: str, body: str, kind: IssueKind = "bug", severity: str = "minor",
                     discovered_from: str = "", about: list[str] | None = None, actor: str = "agent:sdd") -> str  # :168
async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]  # :201 — FILL IN: confirm returned dicts include body (else use a title marker)
# IssueKind: bug | tech_debt | feature_gap | vulnerability
# wiki/tools.py:443-500 WikiNoteTool._execute — read-modify-write note pattern (get_page include_body=True → append → upsert_pages)
```

### Does NOT Exist
- ~~`store.add_note()`~~ — notes are body appends (see wiki/tools.py:456-457)
- ~~ledger dedup by fingerprint~~ — implemented here via body marker

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/routing.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_routing.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiNoteTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Copy the note read-modify-write shape from `WikiNoteTool._execute` (wiki/tools.py:455-500) — *why*: same managed/foreign-id guards apply.
2. Never let routing exceptions escape; log and count — *why*: report must still be returned (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/lint/routing.py` (CREATE)
```python
"""Route unfixable lint findings to the ledger, report files and page notes (FEAT-625)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.models import Finding, LintOptions, LintReport
from parrot.knowledge.wiki.store import BaseWikiStore

FP_MARKER = "<!-- lint-fp:{fp} -->"


def render_markdown(report: LintReport) -> str:
    """Human-readable report grouped by rule then severity."""
    # FILL IN: header (wiki, backend, counts, fixed), then one section per rule_id with subjects + message
    raise NotImplementedError


class FindingRouter:
    """Callable router injected into LintRunner (runner.router)."""

    def __init__(self, store: BaseWikiStore, *, report_dir: Path | None = None, ledger: Any | None = None) -> None:
        self.store = store
        self.report_dir = report_dir
        self.ledger = ledger
        self.logger = logging.getLogger(__name__)

    async def __call__(self, report: LintReport, options: LintOptions) -> dict[str, int]:
        return await self.route(report, options)

    async def route(self, report: LintReport, options: LintOptions) -> dict[str, int]:
        """Return {ledger_opened, ledger_deduped, notes_added, report_files}."""
        counts = {"ledger_opened": 0, "ledger_deduped": 0, "notes_added": 0, "report_files": 0}
        residue = [f for f in report.findings if not f.fixable and f.severity in ("warning", "error")]
        if options.ledger and self.ledger is not None:
            await self._to_ledger(residue, options, counts)
        if options.notes:
            await self._to_notes(residue, counts)
        counts["report_files"] = await self._write_reports(report, options)
        return counts

    async def _to_ledger(self, findings: list[Finding], options: LintOptions, counts: dict[str, int]) -> None:
        # FILL IN: existing markers from await self.ledger.ready_work(); group by rule_id; cap -> aggregate issue;
        #          open_issue(title=f"lint {rule_id}: ...", body=... + FP_MARKER, kind=..., severity=..., discovered_from=f"lint:{rule_id}", about=subjects, actor="agent:lint")
        raise NotImplementedError

    async def _to_notes(self, findings: list[Finding], counts: dict[str, int]) -> None:
        # FILL IN: per subject page: get_page(include_body=True); skip None / adr: / marker already present; append note; upsert_pages
        raise NotImplementedError

    async def _write_reports(self, report: LintReport, options: LintOptions) -> int:
        out = options.report_dir or self.report_dir
        if out is None:
            return 0

        def _write() -> int:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
            (Path(out) / "report.md").write_text(render_markdown(report), encoding="utf-8")
            return 2

        return await asyncio.to_thread(_write)
```

**Why this shape**: AC8: three destinations, each toggleable; dedup by fingerprint marker so re-runs are idempotent (spec §7 ledger flooding). The router is a callable so the runner (TASK-4010) can stay ignorant of ledger imports.

### FILL IN checklist
- [ ] `render_markdown`
- [ ] `_to_ledger` dedup + cap
- [ ] `_to_notes` guards

---

## Acceptance Criteria

- [ ] Second run opens no duplicate issue
- [ ] Cap aggregates
- [ ] Notes added once per fingerprint
- [ ] `--no-ledger/--no-notes` honoured
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_routing.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_routing.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_routing.py
async def test_ledger_dedup(tmp_path): ...
async def test_ledger_cap_aggregates(tmp_path): ...
async def test_notes_once(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4018 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
