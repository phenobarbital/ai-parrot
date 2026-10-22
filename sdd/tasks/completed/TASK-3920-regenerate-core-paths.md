# TASK-3920: Re-derive `CORE_PATHS` under the direct-importer metric

**Feature**: FEAT-620 — Direct-Importer Core Detection for the Merge-Tier Gate
**Spec**: `sdd/specs/test-scope-impact-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3919
**Assigned-to**: unassigned

---

## Context

Implements spec §2 M3. Second half of `issue:7f2f3d4d7828`.

`detect_core()` escalates when `forced or fanin >= threshold`, where
`forced = path in policy.core_paths`. TASK-3919 fixes the `fanin` half.
`CORE_PATHS` is the other half, and it is larger: **724 entries**, every one
produced by the FEAT-563 S4 spike from the same saturated transitive metric
(its inline comments read `# fan-in 77 (ast)`).

Measured on `dev` at `76a7d7b22`, 96% of `CORE_PATHS` does not clear a
30-direct-importer bar:

| direct importers | entries of 724 | share |
|---|---:|---:|
| `>= 10` | 116 | 16.0% |
| `>= 20` | 42 | 5.8% |
| `>= 30` | 29 | 4.0% |
| `>= 50` | 12 | 1.7% |

The tail includes entries with **zero** direct importers —
`parrot/core/__init__.py`, `parrot/cli/__init__.py`,
`parrot/knowledge/__init__.py`, `parrot/flows/__init__.py`,
`parrot_formdesigner/__init__.py` — each unconditionally escalating every
distribution reached from it. 623 of the 724 are in `ai-parrot` alone.

Without this task TASK-3919's fix only helps modules absent from the list, and
any diff touching one of the 724 still escalates the repo.

---

## Scope

- Add `scripts/sdd/regen_core_paths.py`: builds an `ImportIndex` over the
  checkout, ranks every source module by direct-importer count, and emits the
  `CORE_PATHS` tuple literal — deterministic and byte-reproducible.
- Replace the 724-entry `CORE_PATHS` literal in `policy.py` with the generated
  tuple, each entry carrying its measured direct-importer count as a comment.
- Add a test asserting every retained entry exists on disk and has a non-zero
  direct-importer count, and that `forced` escalation still fires (AC4, AC5).

**NOT in scope**: `source_fanin` or the threshold (TASK-3919); documentation
(TASK-3921); automating drift detection in CI; `XDIST_SAFE_DISTRIBUTIONS` or
any other `policy.py` constant.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/regen_core_paths.py` | CREATE | Deterministic `CORE_PATHS` generator |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | Replace the `CORE_PATHS` literal |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_paths.py` | CREATE | AC4/AC5 guards on the regenerated list |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.impact import (  # verified: .../test_scope/impact.py
    ImportIndex,       # :111
    module_aliases,    # :40
    module_name_for,   # :25
)
from parrot.flows.dev_loop.test_scope.policy import CORE_PATHS, ScopePolicy  # verified: policy.py:12, :777
from parrot.flows.dev_loop.test_scope.impact import detect_core  # verified: impact.py:263
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py:11-12
DEFAULT_CORE_FANIN_THRESHOLD: int = 30   # set to 30 by TASK-3919 (was 50)
CORE_PATHS: tuple[str, ...] = (  # measured by FEAT-563 S4 - artifacts/logs/feat-563-core-fanin.tsv; always escalate
    "packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py",  # fan-in 77 (ast) / 2 (text)
    ...
)   # closing paren at policy.py:737

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:25
def module_name_for(path: str) -> str | None:
    """Map `packages/<dist>/src/<top>/a/b.py` to `<top>.a.b` (`__init__.py` -> package)."""

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:120
@classmethod
def build(cls, worktree: Path) -> "ImportIndex": ...
#   index.src_importers: dict[str, set[str]]   target module -> importing modules
#   index.module_dist:   dict[str, str]        module -> distribution
```

### Does NOT Exist
- ~~`scripts/sdd/regen_core_paths.py`~~ — this task creates it. There is no
  existing generator; the 724 entries were pasted by hand from the FEAT-563
  spike output.
- ~~`artifacts/logs/feat-563-core-fanin.tsv`~~ — cited by the `CORE_PATHS`
  comment, but `artifacts/` is git-ignored and the file is **not in the
  checkout**. Do not try to read or regenerate it; it is not the input here.
- ~~`ScopePolicy.escalate_foreign_dists`~~ — FEAT-618, unmerged, not on `dev`.
- ~~a `core_paths` entry format other than a repo-relative POSIX path string~~ —
  `detect_core` does `path in policy.core_paths`, an exact string match against
  the changed-file paths git reports. No globs, no `Path` objects.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/regen_core_paths.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_paths.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py#CORE_PATHS",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#ImportIndex",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#module_name_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#detect_core"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The generated list must be byte-reproducible** (AC4). Sort deterministically
  — by path, not by count — and emit a fixed number format. A regeneration that
  reorders ties makes the test meaningless.
- **Keep alias pairs together.** `parrot/tools/<x>.py` and
  `parrot_tools/<x>.py` are the same module through the `sys.meta_path`
  redirect and measure identically (both `parrot.tools.abstract` and
  `parrot_tools.abstract` show 151 direct importers). If one is retained, the
  other must be: a changed-file path can be either spelling.
- `CORE_PATHS` exists for files the AST **under**-counts — dynamic imports,
  registries, the meta_path redirect. Retaining an entry on measured evidence is
  the rule; this task does not invent a new hand-curated exception list.
- `policy.py` is stdlib-only data. The generator lives in `scripts/sdd/`, not in
  the package — `policy.py` must stay a literal, never compute itself at import.

### Threshold choice for retention
Use the same bar as `DEFAULT_CORE_FANIN_THRESHOLD` (30) so the two paths agree,
giving ~29 entries before alias pairing. Note that at this bar `CORE_PATHS`
becomes close to redundant with the fan-in path — which is the point: a forced
list should hold the *measured exceptions*, not a second copy of the metric.
Entries kept purely for the alias-pairing rule are the expected delta.

### References in Codebase
- `scripts/sdd/` — existing generators/checkers to match for CLI shape and
  `if __name__ == "__main__":` conventions (e.g. `check_task_graph.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the generator and run it to produce the new literal — *why*: the list must
   come from measurement, and committing the generator is what makes AC4 checkable.
2. Replace the `CORE_PATHS` literal in `policy.py` with the generator's output —
   *why*: this is the behaviour change; it lands in its own commit so it can be audited.
3. Add the guard test — *why*: AC4/AC5; a hand-edit of the list later would otherwise
   silently reintroduce zero-importer entries.

### `scripts/sdd/regen_core_paths.py` (CREATE)
```python
"""Regenerate `CORE_PATHS` for test_scope.policy from measured direct-importer counts.

FEAT-620. The previous 724-entry list was derived from a transitive fan-in metric
that saturated (see sdd/specs/test-scope-impact-tech-debt.spec.md). This script
re-derives it from `source_fanin`'s direct count so the list is reproducible
rather than archaeological.

Usage:
    python -m scripts.sdd.regen_core_paths --threshold 30
    python -m scripts.sdd.regen_core_paths --threshold 30 --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parrot.flows.dev_loop.test_scope.impact import ImportIndex, module_aliases, module_name_for

REPO_ROOT = Path(__file__).resolve().parents[2]


def direct_importers(index: ImportIndex, module: str) -> int:
    """Direct importer count, alias-expanded — mirrors `source_fanin`'s first element."""
    importers: set[str] = set()
    for alias in module_aliases(module):
        importers |= index.src_importers.get(alias, set())
    importers.discard(module)
    return len(importers)


def measure(root: Path, threshold: int) -> list[tuple[str, int]]:
    """Every source path at or above `threshold`, sorted by path. Alias pairs kept together."""
    index = ImportIndex.build(root)
    # FILL IN: walk `packages/*/src/**/*.py`, map each to its module via
    # module_name_for (skip None), measure, keep >= threshold -- bounded by AC4.
    # FILL IN: add the alias partner of every retained parrot/tools <-> parrot_tools
    # path even when its own count is below threshold -- bounded by the alias-pairing
    # rule in Implementation Notes.
    raise NotImplementedError


def render(rows: list[tuple[str, int]]) -> str:
    """The `CORE_PATHS = (...)` literal, one entry per line with its measured count."""
    lines = [
        "CORE_PATHS: tuple[str, ...] = (  # FEAT-620: regenerated by scripts/sdd/regen_core_paths.py",
    ]
    for path, count in rows:
        lines.append(f'    "{path}",  # direct importers: {count}')
    lines.append(")")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=int, default=30)
    parser.add_argument("--check", action="store_true", help="exit 1 if policy.py is out of date")
    args = parser.parse_args(argv)
    rows = measure(REPO_ROOT, args.threshold)
    # FILL IN: --check compares `render(rows)` against the literal currently in
    # policy.py and exits 1 on drift; otherwise print it -- bounded by AC4's
    # "rerunning it reproduces the committed tuple byte-for-byte".
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: `direct_importers` is duplicated here rather than imported
from `impact.py` on purpose — importing `source_fanin` would make the generator
agree with the implementation by construction, so a regression in `source_fanin`
would regenerate a matching-but-wrong list and the `--check` guard would stay
green. Keeping an independent copy makes the two paths cross-check each other.
`render` fixes the output format; do not make it configurable, or byte-identical
regeneration stops being a meaningful assertion.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'CORE_PATHS: tuple\[str, ...\] = (  # measured by FEAT-563 S4' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py)
# REPLACE lines 12-737 inclusive -- the whole literal from
#   `CORE_PATHS: tuple[str, ...] = (  # measured by FEAT-563 S4 - artifacts/logs/...`
#   (verified: policy.py:12)
# down to and including its closing `)` (verified: policy.py:737)
# with the exact stdout of:
#   PYTHONPATH=packages/ai-parrot/src python -m scripts.sdd.regen_core_paths --threshold 30
```
**Why**: line 738 onward (`XDIST_SAFE_DISTRIBUTIONS` and the rest) is untouched —
the replacement is bounded to the tuple. Paste the generator output verbatim; any
manual tidy-up breaks the byte-for-byte guarantee AC4 asserts.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_paths.py` (CREATE)
```python
"""Guards on the regenerated CORE_PATHS (FEAT-620, spec AC4/AC5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.impact import ImportIndex, detect_core, module_name_for
from parrot.flows.dev_loop.test_scope.policy import CORE_PATHS, ScopePolicy

REPO_ROOT = Path(__file__).resolve().parents[6]


@pytest.fixture(scope="module")
def repo_index() -> ImportIndex:
    # FILL IN: skip when REPO_ROOT is not a source workspace -- bounded by: must not
    # fail in a wheel-only install. Mirror TASK-3919's test_core_calibration fixture.
    return ImportIndex.build(REPO_ROOT)


def test_every_core_path_exists():
    """A CORE_PATHS entry naming a deleted file silently escalates nothing (AC4)."""
    missing = [p for p in CORE_PATHS if not (REPO_ROOT / p).is_file()]
    assert missing == []


def test_every_core_path_has_importers(repo_index):
    """A module nothing imports cannot be core -- the old list had several (AC4)."""
    # FILL IN: assert every CORE_PATHS entry has >= 1 direct importer, allowing the
    # documented alias-partner exception -- bounded by AC4 and the alias-pairing rule.


def test_forced_escalation_still_fires(tmp_path):
    """`forced` is independent of fan-in; only the list shrank (AC5)."""
    # FILL IN: build a tiny tree whose module has fan-in 0, pass its path in
    # core_paths with core_fanin_threshold=999, assert one hit with forced is True
    # -- bounded by AC5. test_impact.py::test_core_paths_force_escalation is the model.
```
**Why this shape**: `test_every_core_path_exists` needs no index, so it stays
fast and catches the commonest drift (a file moved or deleted). The importer
check is separated because it needs the expensive index. `test_forced_escalation_still_fires`
uses a synthetic tree, not the repo, so it still asserts the mechanism after the
list shrinks to almost nothing.

### FILL IN checklist
- [ ] `regen_core_paths.py::measure` — the walk, measurement and alias pairing;
      bounded by AC4 and the alias-pairing rule.
- [ ] `regen_core_paths.py::main` — `--check` drift comparison and the print path;
      bounded by AC4 (byte-for-byte reproduction).
- [ ] `test_core_paths.py::repo_index` — non-workspace skip; bounded by wheel-only installs.
- [ ] `test_core_paths.py::test_every_core_path_has_importers` — assertion body;
      bounded by AC4 plus the alias exception.
- [ ] `test_core_paths.py::test_forced_escalation_still_fires` — fixture and assertion;
      bounded by AC5.

---

## Acceptance Criteria

- [ ] AC4 — every retained `CORE_PATHS` entry exists on `dev` and has a non-zero
      direct-importer count; `python -m scripts.sdd.regen_core_paths --threshold 30 --check`
      exits 0 against the committed tuple.
- [ ] AC5 — a path in `core_paths` is still a core hit regardless of its fan-in.
- [ ] The zero-importer entries named in Context are gone from the list.
- [ ] `parrot/tools/<x>.py` and `parrot_tools/<x>.py` are both present or both absent.
- [ ] `policy.py` below the `CORE_PATHS` tuple is unchanged.
- [ ] No linting errors: `ruff check scripts/sdd/regen_core_paths.py packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_paths.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`

---

## Test Specification

Run with `PYTHONPATH=packages/ai-parrot/src`. The index build parses ~2700 files
(a few seconds) — use a module-scoped fixture, and do not build it in a test that
does not need it.

---

## Agent Instructions

Touch only the three files listed. Do not edit
`packages/ai-parrot/build/lib.linux-x86_64-cpython-312/...`. Do not change
`DEFAULT_CORE_FANIN_THRESHOLD` — TASK-3919 owns it; read it, do not write it.

---

## Completion Note

**Completed**: 2026-10-01 — verified.

`CORE_PATHS` went from **724 entries to 29**, regenerated by
`scripts/sdd/regen_core_paths.py` at threshold 30. Every entry now carries its
measured direct-importer count in a trailing comment. All five zero-importer
entries named in the task Context are gone.

`python -m scripts.sdd.regen_core_paths --threshold 30 --check` exits 0 against
the committed tuple — that is AC4's byte-for-byte reproduction, asserted by
running it, not by inspection.

**Alias pairing holds**: `parrot/tools/{abstract,decorators,toolkit}.py` and
`parrot_tools/{abstract,decorators,toolkit}.py` are all six present. Their
counts differ by one (151/150, 51/50, 105/104) because the alias edge is
directional in `src_importers`; both halves clear 30 independently here, so the
pairing rule did not have to rescue either. The rule and its test exception are
kept for the case where it would.

**Tests**: 28 passed, 0 failed — `test_core_paths.py`, `test_impact.py`,
`test_core_calibration.py`, `test_select.py`, `test_supervisor_ledger.py`.
`ruff check` clean on the generator, the source tree and the test tree.

**Deviation from the blueprint**: the blueprint sketched `main()` printing the
literal and a `--check` branch; the shipped script adds a `--root` argument so
the generator can be pointed at a specific checkout. That was needed to run it
safely against the worktree rather than whatever `Path.cwd()` happens to be —
see the incident note below. Behaviour at the default root is unchanged.

**Incident during implementation**: a `python - <<EOF` heredoc that located
`policy.py` via `Path.cwd()` resolved to the **main checkout** rather than this
worktree despite a `cd` into the worktree in the same compound command, and
rewrote the shared `policy.py`. The main checkout was clean beforehand and was
restored with `git checkout --` (verified: `git status --porcelain` empty, 724
entries, threshold 50, no diff against index or HEAD — nothing was lost). The
replacement was then redone using absolute paths and an explicit `--root`, with
an assertion that the write target is inside the worktree.
