# TASK-4070: Spike S5: SDD asset assumption audit scanner (parrot.sdd.audit)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0 defines spike **S5**, an SDD portability dry-run that produces the
assumption inventory for the markdown rewrite. Spec §3 Module 6 says it is "partial"
because "markdown rewrite needs spike S5's assumption inventory". Spec §9 S9 (CONFIRM)
adds: "Audit installed commands for shell/jq/non-Windows assumptions; installer reports
unavailable tooling". That part is folded into S5 here and into M6's install-time report.

This task turns S5 into a **reusable, stdlib-only scanner**, `parrot.sdd.audit`, instead
of a one-off grep. Three consumers use it:

1. **This task** runs it over the SDD markdown/hook assets and commits the inventory to
   `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`.
2. **TASK-4089** (markdown rewrite) uses the report's "Helper reference map" as its
   rewrite list. Every `scripts/sdd/<name>` / `scripts.sdd.<name>` becomes
   `python -m parrot.sdd.scripts.<name>`.
3. **TASK-4091** (`parrot sdd install`) imports `scan_paths` + `missing_tools` at install
   time to warn about tooling the target machine lacks (`jq`, `gh`, `tmux`, …).

The task also creates the `parrot.sdd` package root (`__init__.py`, docstring only) that
TASK-4085/4088 build `parrot.sdd.scripts` under, and the `packages/ai-parrot/tests/sdd/`
test package (brief: `tests/sdd/` ownership belongs to this task).

**Pre-seeded reference map.** Verified 2026-10-05 with
`grep -oE 'scripts[./]sdd[./][a-z_]+'` over each file. The generated report must reproduce
it (it is the scanner's acceptance oracle):

| Asset | Helpers referenced |
|---|---|
| `.claude/commands/sdd-done.md` | check_task_state, close_task, heal_orphans, sdd_meta, select_tests |
| `.claude/commands/sdd-fix.md` | ensure_worktree, reserve_ids |
| `.claude/commands/sdd-insight.md` | insight (invoked as `python3 scripts/sdd/insight.py`, lines 51/85) |
| `.claude/commands/sdd-next.md`, `sdd-status.md` | doc_taxonomy, worktree_status |
| `.claude/commands/sdd-spec.md` | reserve_ids, sdd_meta |
| `.claude/commands/sdd-start.md` | close_task, ensure_worktree, finalize_task, sdd_meta |
| `.claude/commands/sdd-task.md` | check_task_graph, reserve_ids, sdd_meta |
| `.claude/commands/sdd-brainstorm.md`, `sdd-proposal.md`, `sdd-tojira.md` | sdd_meta *(not in the original brief map — found by the verification grep)* |
| `.claude/commands/sdd-codereview.md`, `sdd-explain.md`, `sdd-fromjira.md` | none |
| `sdd/WORKFLOW.md` | backfill_taxonomy, check_id_collisions, close_task, doc_taxonomy, ensure_worktree, id_ledger, install_hooks, migrate_index, reserve_ids |

External-tool sample (files containing the token, same asset set): `jq` 9, `gh` 34,
`tmux` 1, `codex` 9, `git-lfs` 0, `source .venv` 3, `.venv/bin` 4, `uv run` 3, `/tmp/` 2,
`packages/ai-parrot` 8, `.claude/worktrees` 9. Example: `sdd-done.md:172` uses
`TASK_FILES=$(jq -r '.tasks[].file' …)`.

---

## Scope

- Create the `parrot.sdd` package root. `__init__.py` holds a module docstring only and
  **no imports**, so `python -m parrot.sdd.scripts.<x>` and `python -m parrot.sdd.audit`
  stay as light as `import parrot` (stdlib + `parrot.version`).
- Implement `parrot/sdd/audit.py`. It is **stdlib-only** and contains:
  - the frozen dataclass `AssumptionFinding`;
  - `scan_text`, `scan_paths`, `missing_tools` and `main`;
  - six finding kinds: `repo-script`, `venv-path`, `uv-run`, `external-tool`,
    `posix-shell`, `monorepo-path`;
  - a markdown report renderer that includes a per-asset "Helper reference map" and a
    "Rewrite list".
- Generate and commit `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` by running the
  scanner over the asset set listed below.
- Create the `packages/ai-parrot/tests/sdd/` package (`__init__.py`) and
  `test_audit.py`.

**NOT in scope**:
- Rewriting any markdown (TASK-4089).
- Moving any `scripts/sdd/*` helper (TASK-4085/4086/4087/4088).
- `parrot sdd install` and its warnings (TASK-4091). This task only exposes the
  functions that task calls.
- `parrot/sdd/cli.py`, `installer.py`, `scripts/`, `_assets/` (other M6 tasks).
- `pyproject.toml` package-data. `[tool.setuptools.packages.find] include = ["parrot*"]`
  (`packages/ai-parrot/pyproject.toml:951-954`) already picks up the new `parrot.sdd`
  package.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/__init__.py` | CREATE | Package root; docstring only, no imports |
| `packages/ai-parrot/src/parrot/sdd/audit.py` | CREATE | Stdlib-only assumption scanner + markdown report CLI |
| `packages/ai-parrot/tests/sdd/__init__.py` | CREATE | Test package marker (repo convention) |
| `packages/ai-parrot/tests/sdd/test_audit.py` | CREATE | Unit tests for the scanner |
| `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` | CREATE | Generated S5 inventory (output of `python -m parrot.sdd.audit`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only — this module must never import parrot.* or a third-party package
import argparse, re, shutil, sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml:951-954 — package discovery already covers parrot.sdd
# [tool.setuptools.packages.find] where = ["src"]; include = ["parrot*"]; namespaces = true

# Importing `parrot` is cheap: verified 2026-10-05 that `import parrot` loads only
# ['parrot', 'parrot.version'].

# Asset set to scan (all verified to exist 2026-10-05):
#   .claude/commands/sdd-*.md   (14 files: brainstorm, codereview, done, explain, fix, fromjira,
#                                insight, next, proposal, spec, start, status, task, tojira)
#   .claude/agents/sdd-*.md     (9 files: autopilot, coder, feedback, ideation, planner, qa,
#                                research, secondopinion, worker)
#   .claude/rules/*.md          (codebase-conventions.md, worktree-management.md)
#   .claude/hooks/sdd-worker-format.sh
#   sdd/templates/*             (13 files: brainstorm.md, design_research.prompt.md,
#                                design_research.schema.json, finding.md, intake.procedure.md,
#                                intake.schema.json, proposal.md, research_plan.prompt.md,
#                                research_plan.schema.json, spec.md, state.schema.json,
#                                synthesis.prompt.md, task.md)
#   sdd/WORKFLOW.md

# Verified sample references (line numbers):
#   .claude/commands/sdd-insight.md:51,85   python3 scripts/sdd/insight.py \
#   .claude/commands/sdd-done.md:172        TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");
#   .claude/commands/sdd-done.md:227-228    E2E_STATUS=$(echo "$E2E_JSON" | jq -r '.status // "MISSING"')
#   .claude/hooks/sdd-worker-format.sh:1    #!/usr/bin/env bash
```

### Does NOT Exist
- ~~`parrot.sdd` package~~ — created by this task (spec §6 "Does NOT Exist").
- ~~`packages/ai-parrot/tests/sdd/`~~ — created by this task. Note that the repo-root
  `tests/sdd/` (e.g. `tests/sdd/test_close_task_ledger.py`) is a DIFFERENT directory,
  has no `__init__.py`, and is not touched here.
- ~~`sdd/state/FEAT-633/spikes/`~~ — only `sdd/state/FEAT-633/design_research` exists
  today; create the `spikes/` dir (other spike tasks add sibling reports).
- ~~`parrot.sdd.scripts`~~ — TASK-4085 creates it; do NOT create it here.
- ~~`parrot.sdd.installer` / `parrot.sdd.cli`~~ — later M6 tasks.
- ~~a `jq`/`gh` Python binding~~ — tool presence is checked only with `shutil.which`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/audit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_audit.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# Stdlib-only, light-import precedent: the launcher (spec §3 M1) and
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/ (imported by path, never via
# `import parrot`) — keep audit.py importable with zero parrot/third-party modules loaded.
```

### Key Constraints
- **Stdlib only.** TASK-4091 imports this module from the installer, and the
  `parrot.sdd` package must stay cheap. Add no `logging.basicConfig`. Write CLI output
  with `sys.stdout.write`, never `print()`; diagnostics go to `sys.stderr.write`.
- The scanner is **line-based and deterministic**. Sort findings by
  `(path, line, kind)`. Each line can yield one finding per kind, never duplicates of the
  same kind.
- `path` in a finding is the string the caller passed, made repo-relative where
  possible. The committed report must contain **no absolute paths**, because it is
  committed and must be byte-stable across machines.
- `missing_tools` depends on the machine. The committed report includes it in a clearly
  labelled section whose header names the host OS, but the S5 conclusion must not depend
  on it.
- 120 columns, Google docstrings, strict type hints.

### References in Codebase
- `.claude/commands/sdd-*.md`, `sdd/WORKFLOW.md` — scan targets (see contract).
- `scripts/sdd/` — the helper names the `repo-script` kind resolves (`close_task.sh`,
  `heal_orphans.sh`, `*.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `packages/ai-parrot/src/parrot/sdd/__init__.py` with only a docstring. *Why*:
   `python -m parrot.sdd.*` must not pay for imports, and TASK-4085 nests `scripts/`
   under it.
2. Write `audit.py`: dataclass, regex table, `scan_text`, `scan_paths`, `missing_tools`,
   `render_report`, `main`. *Why*: these names are fixed for TASK-4089/4091.
3. Write `tests/sdd/__init__.py` (empty) and `test_audit.py`, then make them pass.
   *Why*: the repo convention requires test packages.
4. From the worktree root, run
   `PYTHONPATH=packages/ai-parrot/src python -m parrot.sdd.audit --root . --output sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`,
   then hand-append the "Conclusions" section. *Why*: the report is the S5 deliverable
   and drives TASK-4089/4091.
5. Diff the report's Helper reference map against the pre-seeded map in Context. Any
   mismatch is a scanner bug: fix the scanner, not the table. *Why*: the map is the
   acceptance oracle.

### `packages/ai-parrot/src/parrot/sdd/__init__.py` (CREATE)
```python
"""SDD (Spec-Driven Development) flow support shipped inside ai-parrot (FEAT-633).

Subpackages/modules: ``audit`` (asset assumption scanner), ``scripts`` (helpers invocable as
``python -m parrot.sdd.scripts.<name>``). Intentionally import-free: keep this file docstring-only.
"""
```

### `packages/ai-parrot/src/parrot/sdd/audit.py` (CREATE)
```python
"""Scan SDD markdown/hook assets for assumptions that break outside the ai-parrot monorepo (FEAT-633 S5).

Usage:
    python -m parrot.sdd.audit [PATH ...] [--root DIR] [--output FILE]

Stdlib-only by contract: imported by ``parrot sdd install`` (TASK-4091) to warn about missing tooling.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

KINDS: tuple[str, ...] = ("repo-script", "venv-path", "uv-run", "external-tool", "posix-shell", "monorepo-path")
EXTERNAL_TOOLS: tuple[str, ...] = ("jq", "gh", "tmux", "codex", "git-lfs", "agy", "black", "pylint")
DEFAULT_GLOBS: tuple[str, ...] = (
    ".claude/commands/sdd-*.md",
    ".claude/agents/sdd-*.md",
    ".claude/rules/*.md",
    ".claude/hooks/sdd-worker-format.sh",
    "sdd/templates/*",
    "sdd/WORKFLOW.md",
)
REPO_SCRIPT_RE = re.compile(r"scripts[./]sdd[./](?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\.py|\.sh)?")
# Command position only (line start, backtick, `$(`, pipe, `&&`, `;`) so prose like "ask codex for…" never matches.
EXTERNAL_TOOL_RE = re.compile(
    r"(?:^\s*|`|\$\(|\|\s*|&&\s*|;\s*)(?P<tool>" + "|".join(map(re.escape, EXTERNAL_TOOLS)) + r")\s+[-\w'\"./]"
)
# FILL IN: final regexes for the four remaining kinds — bounded by the kind definitions below and test_audit.py
#   venv-path:     .venv/bin, `source .venv/bin/activate`
#   uv-run:        `uv run`
#   posix-shell:   `source ` at command position, `$(...)`, `/tmp/`, heredocs, `set -euo pipefail`, `#!/usr/bin/env bash`
#   monorepo-path: `packages/ai-parrot...`, `.claude/worktrees/`
_KIND_PATTERNS: dict[str, re.Pattern[str]] = {"repo-script": REPO_SCRIPT_RE, "external-tool": EXTERNAL_TOOL_RE}


@dataclass(frozen=True)
class AssumptionFinding:
    """One line of an asset that encodes a non-portable assumption."""

    path: str
    line: int
    kind: str
    snippet: str


def scan_text(text: str, path: str) -> list[AssumptionFinding]:
    """Scan ``text`` line by line; at most one finding per (line, kind); snippet = stripped line, max 160 chars."""
    findings: list[AssumptionFinding] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        for kind in KINDS:
            pattern = _KIND_PATTERNS.get(kind)
            if pattern is not None and pattern.search(raw):
                findings.append(AssumptionFinding(path, lineno, kind, raw.strip()[:160]))
    return findings


def scan_paths(paths: Iterable[Path]) -> list[AssumptionFinding]:
    """Read each existing file as UTF-8 (errors="replace") and return all findings sorted by (path, line, kind)."""
    # FILL IN: skip directories/missing files silently; path string = as given (posix) — bounded by "no absolute paths"
    raise NotImplementedError


def missing_tools(findings: Sequence[AssumptionFinding]) -> list[str]:
    """Sorted unique external tools named by ``external-tool`` findings that ``shutil.which`` cannot find."""
    names = {m.group("tool") for f in findings if f.kind == "external-tool" for m in EXTERNAL_TOOL_RE.finditer(f.snippet)}
    return sorted(name for name in names if shutil.which(name) is None)


def helper_map(findings: Sequence[AssumptionFinding]) -> dict[str, list[str]]:
    """Map each path to the sorted unique ``scripts/sdd`` helper names it references (repo-script findings)."""
    # FILL IN: group REPO_SCRIPT_RE names per path — bounded by the pre-seeded reference map (Context)
    raise NotImplementedError


def render_report(findings: Sequence[AssumptionFinding], *, scanned: Sequence[str]) -> str:
    """Markdown: summary counts per kind, Helper reference map, Rewrite list, findings per file, Missing tools."""
    # FILL IN: section order/headings as in the S5 report block below — bounded by byte-stable output (no abs paths)
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: scan PATHs (default: DEFAULT_GLOBS under --root) and write the report. 0 ok, 2 nothing to scan."""
    parser = argparse.ArgumentParser(prog="python -m parrot.sdd.audit", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    # FILL IN: expand DEFAULT_GLOBS relative to --root (sorted), relativize paths to --root, scan, render,
    #          write to --output or sys.stdout; sys.stderr.write + return 2 when no file matched — bounded by AC-3
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: names and signatures are fixed by this task's brief and consumed by
TASK-4089/4091. Keep `_KIND_PATTERNS` covering all six `KINDS`; the FILL IN adds the four
missing entries. `missing_tools` re-derives tool names from snippets because the
dataclass fields are fixed (no extra `tool` field).

### `packages/ai-parrot/tests/sdd/__init__.py` (CREATE)
```python
```
(Empty file, which is the repo convention for test packages.)

### `packages/ai-parrot/tests/sdd/test_audit.py` (CREATE)
See **Test Specification** below. That block is the starting file.

### `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` (CREATE)
```markdown
# S5 — SDD asset assumption inventory (FEAT-633)

> Generated by `python -m parrot.sdd.audit --root . --output sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`
> on <commit sha> — regenerate, never hand-edit sections above "Conclusions".

## Summary
| Kind | Findings | Files |
|---|---|---|
<generated rows, one per kind>

## Helper reference map
| Asset | Helpers |
|---|---|
<generated rows — must match the TASK-4070 Context table>

## Rewrite list (drives TASK-4089)
<generated: `scripts/sdd/<name>` / `scripts.sdd.<name>` → `python -m parrot.sdd.scripts.<name>`>

## Findings by file
<generated: ### <path> then `L<n> [kind] snippet` bullets>

## Missing tools on the generating host (<os>)
<generated>

## Conclusions
<hand-written: (1) helpers not in the 18-module move list, if any; (2) external tools TASK-4091 must
warn about; (3) POSIX-only constructs that cannot be made portable and must be documented as POSIX-first>
```
**Why**: S5's deliverable (spec §3 M0) is a committed report. The angle-bracket lines
are generator output, not literal text.

### FILL IN checklist
- [ ] `audit.py::_KIND_PATTERNS`: regexes for `venv-path`, `uv-run`, `posix-shell`,
  `monorepo-path`. Bounded by the kind definitions and `test_audit.py`. `EXTERNAL_TOOL_RE`
  is fixed: it matches command position only, so prose mentions of "codex" never count.
- [ ] `audit.py::scan_paths`: file reading and sorting. Bounded by "no absolute paths".
- [ ] `audit.py::helper_map`: bounded by the pre-seeded reference map.
- [ ] `audit.py::render_report`: section layout per the S5 block. Bounded by byte-stable
  output.
- [ ] `audit.py::main`: glob expansion and exit codes. Bounded by AC-3.
- [ ] The S5 report's "Conclusions": hand-written, three bullets as outlined.

---

## Acceptance Criteria

- [ ] AC-1: `import parrot.sdd.audit` loads no third-party module and no `parrot.*`
  module other than `parrot`, `parrot.version`, `parrot.sdd`, `parrot.sdd.audit`
  (enforced by a test).
- [ ] AC-2: `scan_text` emits each of the six kinds on a representative line and emits
  nothing on a plain prose line.
- [ ] AC-3: `python -m parrot.sdd.audit --root <empty dir>` exits 2. Over the repo it
  exits 0 and the report contains no absolute path.
- [ ] AC-4: The Helper reference map generated over the real assets matches the Context
  table. At minimum, `sdd-spec.md` maps to {reserve_ids, sdd_meta} and `sdd-done.md` to
  {check_task_state, close_task, heal_orphans, sdd_meta, select_tests}.
- [ ] AC-5: `missing_tools` returns only tools `shutil.which` cannot resolve (tested with
  monkeypatch).
- [ ] AC-6: `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` is committed, generated by
  the scanner, and has a filled "Conclusions" section.
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd packages/ai-parrot/tests/sdd` is clean.
- [ ] Supports spec §5 bullet "`parrot sdd install` deploys the flow … every helper
  referenced by installed markdown resolves as `python -m parrot.sdd.scripts.<name>`"
  (the inventory side).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_audit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_audit.py
"""Tests for parrot.sdd.audit (FEAT-633 spike S5)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd import audit
from parrot.sdd.audit import AssumptionFinding, missing_tools, scan_paths, scan_text

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("python -m scripts.sdd.reserve_ids --kind task", "repo-script"),
        ("scripts/sdd/close_task.sh TASK-1 slug verified", "repo-script"),
        ("source .venv/bin/activate", "venv-path"),
        ("uv run --no-sync pytest", "uv-run"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "external-tool"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "posix-shell"),
        ("cd .claude/worktrees/feat-FEAT-1-x", "monorepo-path"),
    ],
)
def test_scan_text_kinds(line: str, kind: str) -> None:
    assert kind in {f.kind for f in scan_text(line, "x.md")}


def test_scan_text_prose_is_clean() -> None:
    assert scan_text("Ask codex for a second opinion about the design.", "x.md") == []


def test_missing_tools_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit.shutil, "which", lambda name: None if name == "jq" else f"/usr/bin/{name}")
    findings = [AssumptionFinding("a.md", 1, "external-tool", "jq -r .x f && gh pr view")]
    assert missing_tools(findings) == ["jq"]


def test_import_is_stdlib_only() -> None:
    code = "import sys, parrot.sdd.audit; print(sorted(m for m in sys.modules if m.startswith('parrot')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['parrot', 'parrot.sdd', 'parrot.sdd.audit', 'parrot.version']"


def test_real_assets_reference_map() -> None:
    findings = scan_paths([REPO_ROOT / ".claude/commands/sdd-spec.md"])
    names = {m.group("name") for f in findings if f.kind == "repo-script" for m in audit.REPO_SCRIPT_RE.finditer(f.snippet)}
    assert {"reserve_ids", "sdd_meta"} <= names


def test_main_empty_root_exits_2(tmp_path: Path) -> None:
    assert audit.main(["--root", str(tmp_path)]) == 2


def test_main_report_has_no_absolute_paths(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    assert audit.main(["--root", str(REPO_ROOT), "--output", str(out)]) == 0
    assert str(REPO_ROOT) not in out.read_text(encoding="utf-8")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`.
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/parrot-installer.json`.
4. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
5. **Update status** in `sdd/tasks/index/parrot-installer.json` to `"in-progress"` (set
   `started_at`) and commit only that index file.
6. **Implement**. Start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
7. **Verify** that all acceptance criteria are met by running the Validation Commands.
8. **Commit the code**. Stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4070 parrot-installer verified`.
   It moves this file to `sdd/tasks/completed/` and marks it `"done"` in the index. Never
   move or copy the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
