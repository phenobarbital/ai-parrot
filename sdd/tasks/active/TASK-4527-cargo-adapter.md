# TASK-4527: Cargo runner adapter with stable libtest text parser

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4521
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (cargo); brainstorm Q5: stable libtest text only. No `Cargo.toml` exists in this repo — the
adapter is for sibling repos and is tested against text fixtures.

---

## Scope

- Create `runners/cargo.py` (`ADAPTER = CargoAdapter()`) and `parse_libtest(stdout, …) -> RunReport`.
- Argv: `cargo test -p <crate> [filters…] -- --test-threads=1`, `cwd='.'`, stdout-parsed (`report_format='libtest'`).
- Parser: `test <name> ... ok|FAILED|ignored` lines ⇒ nodes `cargo:<crate>::<name>`; `---- <name> stdout ----` blocks under `failures:` ⇒ `failure_text`; non-zero exit with no test lines ⇒ status `unavailable` (compile error).
- Create fixtures `libtest-ok.txt`, `libtest-failed.txt`, `libtest-compile-error.txt`.

**NOT in scope**: nextest/junit (Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/cargo.py` | CREATE | adapter + parser |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-ok.txt` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-failed.txt` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-compile-error.txt` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_cargo.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from ..datatypes import Invocation, RunReport, TestTarget  # TASK-4520
from ..policy import TIERS, ScopePolicy
```

### Existing Signatures to Use
```python
# none existing — new module
```

### Does NOT Exist
- ~~`Cargo.toml` in this repo~~ — none
- ~~`cargo test --message-format json` for test results~~ — not stable for tests; text only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/cargo.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-ok.txt",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-failed.txt",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/libtest-compile-error.txt",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_cargo.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `is_broad` is always False (a crate is the unit). `mirror_targets` returns [] (no file mapping for Rust in v1).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Fixtures — *why*: parser is the risk.
2. Adapter + parser — *why*: spec M4.
3. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/cargo.py` (CREATE)
```python
"""Cargo runner adapter: stable libtest text output (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import TIERS, ScopePolicy

_RESULT_RE = re.compile(r"^test (?P<name>\S+) \.\.\. (?P<status>ok|FAILED|ignored)\s*$", re.M)
_FAILURE_BLOCK_RE = re.compile(r"^---- (?P<name>\S+) stdout ----$", re.M)


def parse_libtest(stdout: str, *, crate: str, exit_code: int, suite: str, duration_s: float, timed_out: bool) -> RunReport:
    """libtest text ⇒ RunReport. Non-zero exit with no result lines ⇒ status "unavailable"."""
    # FILL IN: nodes (f"cargo:{crate}::{name}", passed|failed|skipped); failure_text from the blocks between
    #          one `---- x stdout ----` header and the next header / `failures:` list; counts; status
    raise NotImplementedError


class CargoAdapter:
    kind = "cargo"
    binaries = ("cargo",)
    default_tiers = frozenset(TIERS)
    report_format = "libtest"

    def matches(self, argv: Sequence[str]) -> bool:
        return len(argv) >= 2 and Path(argv[0]).name == "cargo" and argv[1] == "test"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        # FILL IN: positional filters after `test`, before `--`, skipping -p/--package <crate>
        return None

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        return False

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        return []

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        return settings["crate"]

    def invocation(self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
                   settings: Mapping[str, str], policy: ScopePolicy, report_path: str) -> Invocation:
        filters = sorted({t.path for t in targets if t.path})
        argv = ("cargo", "test", "-p", settings["crate"], *filters, "--", "--test-threads=1")
        return Invocation(distribution=distribution, argv=argv, targets=tuple(targets), runner=self.kind,
                          report_format=self.report_format)

    def parse_report(self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
                     duration_s: float, timed_out: bool, suite: str) -> RunReport:
        return parse_libtest(stdout, crate=suite.split(":", 1)[-1], exit_code=exit_code, suite=suite,
                             duration_s=duration_s, timed_out=timed_out)

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        # FILL IN: "crate" required; (worktree / crate / "Cargo.toml").is_file() when crate looks like a path,
        #          otherwise accept a package name
        return []


ADAPTER = CargoAdapter()
```
**Why**: Node id prefix `cargo:<crate>::` keeps ids unique across crates.

### FILL IN checklist
- [ ] `parse_libtest`
- [ ] `operands`
- [ ] `validate_settings`
- [ ] three fixtures
- [ ] tests

---

## Acceptance Criteria

- [ ] ok fixture ⇒ status passed with N nodes.
- [ ] failed fixture ⇒ failure_text per failing test.
- [ ] compile-error fixture (exit 101, no result lines) ⇒ status `unavailable`.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_cargo.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4527 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
