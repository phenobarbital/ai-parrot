# TASK-4010: LintRunner: check → fix → re-check → route → audit

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half): the orchestrator every adapter (toolkit, CLI, MCP) calls.

---

## Scope

- Implement `LintRunner.__init__/run/exit_code` in `lint/runner.py`.
- Rule selection: `options.rules` matches a rule's `rule_id` OR `pack`; `options.skip` removes; `pack == 'llm'` only when `options.llm`.
- Refuse `--fix` (report-only + `schema-mismatch` error finding) when `await store.get_meta('schema_version')` differs from `SCHEMA_VERSION`.
- With `fix`, call `rule.fix()` for each fixable finding, `ctx.invalidate()`, re-run only the rules that fixed something.
- Accept an optional `router` callable (TASK-4018 provides `FindingRouter`); runner never imports routing directly.
- Log `LINT` / `LINT_FIX` via `WikiBookkeeper.log_operation` when `root`+`config` are given.
- Write unit tests with fake rules.

**NOT in scope**: Concrete rules; `default_rules()` (TASK-4019); routing internals (TASK-4018).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/runner.py` | CREATE | LintRunner |
| `packages/ai-parrot/tests/knowledge/lint/test_runner.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.wiki.store import BaseWikiStore, SCHEMA_VERSION  # verified: wiki/store.py:525, :50
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper  # verified: wiki/bookkeeper.py:47 (__init__), :175 log_operation
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                              # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # :544
    async def add_edges(self, edges: list[tuple]) -> int: ...          # :547  (src, dst, rel, provenance)
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :565
    async def list_pages(self, category=None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...  # :568
    async def dump_pages(self) -> list[dict[str, Any]]: ...            # :590  keys: concept_id,node_id,title,category,summary,body,source_id,token_count,created_at,updated_at,content_hash
    async def dump_edges(self) -> list[dict[str, Any]]: ...            # :593  keys: src,dst,rel
    async def orphan_sources(self) -> list[str]: ...                   # :600
    async def broken_edges(self) -> list[dict[str, Any]]: ...          # :603  keys: src,dst,rel
    async def missing_bodies(self) -> list[str]: ...                   # :606
# BaseWikiStore.get_meta / set_meta — concrete defaults on the base (wiki/store.py, after :610) — FILL IN: confirm exact signature with grep before use
# wiki/bookkeeper.py:175
def log_operation(self, wiki_dir: Path, operation: str, details: str, timestamp: Optional[str] = None) -> None
```

### Does NOT Exist
- ~~`wikitoolkit lint` command~~ / ~~`wiki_lint` MCP tool~~ — created by TASK-4020
- ~~`parrot.knowledge.lint.packs.default_rules`~~ — added by TASK-4019; runner must import it lazily inside `run()` only when `rules is None`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/runner.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_runner.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper.log_operation"
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
1. Implement selection, then check loop, then fix loop, then counts — *why*: fix loop needs the selected rule map.
2. Import `default_rules` lazily inside `run()` — *why*: it is created by TASK-4019, after this task.
3. Catch exceptions per rule and convert them to an `error` finding `rule-crashed` — *why*: one broken rule must not hide the rest (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/lint/runner.py` (CREATE)
```python
"""LintRunner — orchestrates one lint run (FEAT-625)."""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import SEVERITY_RANK, Finding, FixResult, LintOptions, LintReport, Severity
from parrot.knowledge.lint.rule import LintRule, make_fingerprint
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.store import SCHEMA_VERSION, BaseWikiStore

Router = Callable[[LintReport, LintOptions], Awaitable[dict[str, int]]]


class LintRunner:
    """Run lint rules over a wiki store and optionally apply safe fixes."""

    def __init__(
        self,
        store: BaseWikiStore,
        *,
        root: Path | None = None,
        config: Any | None = None,
        rules: Sequence[LintRule] | None = None,
        router: Router | None = None,
    ) -> None:
        self.store = store
        self.root = root
        self.config = config
        self._rules = list(rules) if rules is not None else None
        self._router = router
        self.logger = logging.getLogger(__name__)

    def _select(self, options: LintOptions) -> list[LintRule]:
        """Apply rules/skip/llm selection."""
        if self._rules is None:
            from parrot.knowledge.lint.packs import default_rules  # created by TASK-4019

            pool = default_rules(options)
        else:
            pool = list(self._rules)
        # FILL IN: filter by options.rules (rule_id or pack), options.skip, and drop pack=="llm" unless options.llm
        raise NotImplementedError

    async def _schema_ok(self) -> bool:
        """True when the plane's stored schema version equals SCHEMA_VERSION."""
        # FILL IN: compare store meta 'schema_version' to SCHEMA_VERSION; missing meta => True (fresh planes have empty meta — known gotcha)
        raise NotImplementedError

    async def run(self, options: LintOptions) -> LintReport:
        """Check → (fix → invalidate → re-check) → route → log LINT."""
        started = time.monotonic()
        ctx = LintContext(self.store, root=self.root, config=self.config, options=options)
        rules = self._select(options)
        report = LintReport(
            wiki_name=str(getattr(self.config, "wiki_name", "") or ""),
            backend=type(self.store).__name__,
            rules_run=[r.rule_id for r in rules],
            started_at=datetime.now(tz=UTC).isoformat(),
        )
        # FILL IN: run checks (per-rule try/except -> rule-crashed error finding via make_fingerprint);
        #          if options.fix and not await self._schema_ok(): add schema-mismatch error, skip fixes (spec §7);
        #          else apply fixes, collect FixResult, ctx.invalidate(), re-check only rules that fixed something;
        #          compute report.counts by severity; await self._router(report, options) when set -> report.routing
        report.duration_ms = int((time.monotonic() - started) * 1000)
        self._audit("LINT", f"{len(report.findings)} findings, {len(report.fixed)} fixed")
        return report

    def _audit(self, operation: str, details: str) -> None:
        """Append to the wiki log.md when root+config are known (best-effort)."""
        if self.root is None or self.config is None:
            return
        # FILL IN: resolve the wiki dir the same way cli.py remember/note do, then WikiBookkeeper().log_operation(...)
        #          wrap in try/except and self.logger.warning on failure — audit must never fail the run

    @staticmethod
    def exit_code(report: LintReport, fail_on: Severity | None) -> int:
        """0 when no finding is at or above ``fail_on``, else 1."""
        if fail_on is None:
            return 0
        threshold = SEVERITY_RANK[fail_on]
        return int(any(SEVERITY_RANK[f.severity] >= threshold for f in report.findings))
```

**Why this shape**: Runner owns ordering and the safe-fix contract (spec G3/AC2): fixes only via rule.fix(), schema mismatch refuses fixes, re-check confirms. Routing is injected so the runner stays importable without the ledger.

### FILL IN checklist
- [ ] `_select` filtering
- [ ] `_schema_ok` meta comparison (empty meta ⇒ ok)
- [ ] `run` check/fix/re-check/route loop
- [ ] `_audit` wiki dir resolution

---

## Acceptance Criteria

- [ ] Fixed findings move from `findings` to `fixed`
- [ ] Fix refused on schema mismatch (no store writes)
- [ ] `exit_code` honours error/warning/None
- [ ] A crashing rule yields `rule-crashed` and other rules still run
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_runner.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_runner.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_runner.py
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport
from parrot.knowledge.lint.runner import LintRunner


class FakeRule:
    rule_id, pack, default_severity = "fake", "test", "warning"
    # FILL IN: check() returns one fixable finding until fix() flips a flag


async def test_runner_fix_then_recheck(tmp_path): ...
async def test_runner_refuses_fix_on_schema_mismatch(tmp_path): ...
def test_exit_code_fail_on():
    r = LintReport(findings=[Finding(rule_id="x", severity="warning", message="m", fingerprint="f")])
    assert LintRunner.exit_code(r, "error") == 0 and LintRunner.exit_code(r, "warning") == 1
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4010 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
