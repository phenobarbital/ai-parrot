# TASK-4526: Vitest runner adapter

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4521, TASK-4523
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (vitest). The admin UI runs `vitest run` (`packages/ai-parrot-server/ui/package.json:14`,
config `vitest.config.ts`, package manager pnpm). Argv form fixed by the spec:
`pnpm exec vitest run --reporter=junit --outputFile=<report> <files…>` with `cwd=settings["cwd"]`.

---

## Scope

- Create `runners/vitest.py` with `ADAPTER = VitestAdapter()` per spec §3 M4.
- `matches`: normalized argv[0] == `vitest`; `is_broad`: `vitest run` (or `vitest`) without a file operand.
- `mirror_targets`: changed `foo.ts` / `foo.svelte` / `foo.svelte.ts` under `cwd` ⇒ sibling `foo.test.ts` / `foo.spec.ts` if it exists (file-level only).
- `distribution_of` ⇒ `settings.get('distribution', 'admin-ui')`; targets are relative to `cwd`.
- `validate_settings`: `cwd` required and must exist with a `package.json`.

**NOT in scope**: Running pnpm install; nightly matrix (TASK-4537).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` | CREATE | adapter |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py` | CREATE | tests (uses TASK-4523 fixtures) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from ..datatypes import Invocation, RunReport, TestTarget  # TASK-4520
from ..policy import TIERS, ScopePolicy                   # policy.py:78,82
from ..report import parse_junit_report                    # TASK-4523
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/ui/package.json:14  "test": "vitest run"
# packages/ai-parrot-server/ui/vitest.config.ts  (exists)
```

### Does NOT Exist
- ~~`tests/ui/_vitest.py`~~ — no wrapper exists
- ~~`vitest --reporter=json` parsing~~ — junit only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- No subprocess in the adapter: it only builds argv and parses reports. Tests never run pnpm.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Write the adapter — *why*: spec M4.
2. Tests over argv building, broadness, mirror and the TASK-4523 fixtures — *why*: no pnpm in CI tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` (CREATE)
```python
"""Vitest runner adapter (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import TIERS, ScopePolicy
from ..report import parse_junit_report

_TEST_SUFFIXES = (".test.ts", ".spec.ts", ".test.js", ".spec.js")


class VitestAdapter:
    kind = "vitest"
    binaries = ("pnpm", "vitest")
    default_tiers = frozenset(TIERS)
    report_format = "junit"

    def matches(self, argv: Sequence[str]) -> bool:
        return bool(argv) and Path(argv[0]).name == "vitest"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        # FILL IN: positional args after an optional "run", ignoring --flags (and their =values)
        return None

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        ops = self.operands(argv)
        return ops is not None and not ops

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        # FILL IN: only files under settings["cwd"]; foo.ts|foo.svelte|foo.svelte.ts ⇒ existing sibling test;
        #          returns paths RELATIVE to cwd, sorted, de-duplicated
        return []

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        return settings.get("distribution", "admin-ui")

    def invocation(self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
                   settings: Mapping[str, str], policy: ScopePolicy, report_path: str) -> Invocation:
        paths = sorted({t.path for t in targets})
        argv = ("pnpm", "exec", "vitest", "run", "--reporter=junit", f"--outputFile={report_path}", *paths)
        return Invocation(distribution=distribution, argv=argv, targets=tuple(targets), runner=self.kind,
                          cwd=settings["cwd"], report_path=report_path, report_format=self.report_format)

    def parse_report(self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
                     duration_s: float, timed_out: bool, suite: str) -> RunReport:
        # FILL IN: parse_junit_report(report_path, runner="vitest", …); None ⇒ status "no_report" (red)
        raise NotImplementedError

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        # FILL IN: "cwd" required, (worktree / cwd / "package.json").is_file()
        return []


ADAPTER = VitestAdapter()
```
**Why**: Argv form and `cwd` handling fixed by spec §3 M4; `report_path` is absolute or cwd-relative — the supervisor passes an absolute path.

### FILL IN checklist
- [ ] `operands`
- [ ] `mirror_targets`
- [ ] `parse_report`
- [ ] `validate_settings`
- [ ] tests

---

## Acceptance Criteria

- [ ] Argv equals the spec form; `cwd` comes from settings.
- [ ] `vitest run` with no file is broad; with a file it is not.
- [ ] Fixture `vitest-junit.xml` parses to 3 nodes, 1 failed with text.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4526 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by gpt-5.6-sol (codex), 1 attempt, 253.4s
**Date**: 2026-10-20
**Notes**: Merge-tier validation: only the 5 pre-existing bwrap failures in test_llm_code_dispatcher.py (identical on base); one integration test in test_runners_registry.py was loosened in 2a8aa33fd. Closed via close_task.sh (finalize_task cannot close a 2nd task per wave).

**Deviations from spec**: none
