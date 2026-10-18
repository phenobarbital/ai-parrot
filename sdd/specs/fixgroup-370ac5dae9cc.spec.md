---
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, lint, formatter, minimal-diff, ledger-fix]
---

# Feature Specification: Scope the engine formatter to the task's changed lines

**Feature ID**: FEAT-702
**Date**: 2026-10-18
**Author**: Claude (agent:sdd-fix)
**Status**: approved
**Target version**: 0.30.x

---

## 1. Motivation & Business Requirements

> Ledger-driven fix (`/sdd-fix`, fixgroup:370ac5dae9cc). Resolves
> `issue:fcd15f183e74` (major, tech_debt) — "sdd-coder engine lint autofix
> reformats whole files, inflating task diffs". Same defect as
> `issue:2681d395f3ad` (minor, FEAT-575 review), which this feature also
> addresses.

### Problem Statement

`run_lint_pass` (`sdd_coder/lint.py:119`) runs `ruff check --fix` and then
the repo formatter over every changed `.py` file **as a whole**
(`black --quiet *py_files`, `lint.py:151`; `ruff format --quiet *py_files`,
`:153`) and commits the result as `style(<feature>): TASK-<n> — engine lint
autofix`. When a pre-existing file is not formatter-clean at its base, a
26-line functional change becomes a ~590-line diff (FEAT-614
`odoo/toolkit.py`; FEAT-575 `crew/handler.py`, 231 lines for 10). That
violates the minimal-diff rule, hides the real change from review, and
raises conflict risk against in-flight work on the same files.

### Goals
- G1: the engine formats only the lines the task branch changed (plus any
  line `ruff --fix` just changed), using `black --line-ranges` /
  `ruff format --range` — never the untouched remainder of a file.
- G2: new files (no base version) are still formatted whole.
- G3: the behaviour is configurable (`LintConfig.format_scope`,
  default `"changed-lines"`, `"file"` restores today's behaviour) and
  never blocking: any failure to compute ranges falls back to whole-file
  formatting with a `tool_error` note, exactly like today's error path.

### Non-Goals (explicitly out of scope)
- `ruff check --fix` stays whole-file: its fixes are rule-scoped, not
  layout-scoped, and ruff has no line-range option for `check`.
- No change to the `/sdd-done` full lint pass, to fidelity/banned-import
  gates, or to the commit message.
- No retroactive clean-up of already-reformatted files.

---

## 2. Architectural Design

### Overview

`run_lint_pass` gains a keyword `diff_base: Optional[str]` (the merge-base
`engine.merge` already computes as `diff_base`, `engine.py:2690`). After
`ruff check --fix`, for each changed `.py` file the pass asks git for the
changed hunks against `diff_base` (`git diff -U0 <diff_base> -- <path>`,
working tree included so ruff's own fixes count) and formats:

- **black**: one invocation per file with one `--line-ranges START-END`
  per added/modified hunk (black supports repeated `--line-ranges`).
- **ruff**: one `ruff format --range START-END` invocation per hunk,
  processed bottom-up so earlier line numbers stay valid.
- **no base version** (file added by the task, or `git diff` fails /
  `diff_base` is `None`) or `format_scope == "file"`: whole-file, as today.

Everything after the formatter step (status → add → commit → findings) is
untouched.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `run_lint_pass` (`lint.py:119`) | modified | new `diff_base` kwarg, scoped formatting |
| `SddCoderEngine.merge` lint call (`engine.py:2720`) | modified | passes `diff_base=diff_base` |
| `LintConfig` (`models.py:175`) | modified | `format_scope: Literal["changed-lines", "file"] = "changed-lines"` |
| `LintReport` (`models.py:194`) | unchanged | `tool_error` carries range-computation fallbacks |

### New Public Interfaces

```python
# lint.py
def parse_unified_hunks(diff_text: str) -> List[Tuple[int, int]]:
    """``(start, end)`` 1-based inclusive post-image ranges from ``git diff -U0`` output; pure deletions skipped."""

async def changed_line_ranges(cwd: str, diff_base: str, path: str) -> Optional[List[Tuple[int, int]]]:
    """Post-image hunks of ``path`` against ``diff_base``; ``None`` when the file has no base version or git fails."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: line-scoped formatter (lint.py + models.py + engine.py + tests) | yes | exact skeletons below | — |

### Module 1: Line-scoped formatter
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py`
- **Interface Skeleton**:
  ```python
  _HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)

  def parse_unified_hunks(diff_text: str) -> List[Tuple[int, int]]:
      ranges = []
      for m in _HUNK_RE.finditer(diff_text):
          start, count = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
          if count == 0:            # pure deletion: nothing to format
              continue
          ranges.append((start, start + count - 1))
      return ranges

  async def changed_line_ranges(cwd, diff_base, path):
      rc, out, _err = await _run(["git", "diff", "-U0", "--no-color", diff_base, "--", path], cwd)
      if rc != 0:
          return None
      if re.search(r"^--- /dev/null", out, re.M):   # added by the task → whole file
          return None
      return parse_unified_hunks(out)

  async def _format_files(formatter, bin_path, cwd, py_files, *, diff_base, scope) -> List[str]:
      """Run the formatter; returns tool-error notes (empty when clean)."""
      # scope == "file" or diff_base is None → today's whole-file call
      # else per file: ranges = await changed_line_ranges(...); None → whole file for that file;
      #   [] → skip the file; black → [bin, "--quiet", *chain(["--line-ranges", f"{a}-{b}"] ...), path]
      #   ruff  → for (a, b) in reversed(ranges): [bin, "format", "--quiet", "--range", f"{a}-{b}", path]
  ```
  `run_lint_pass(cwd, changed, *, config, commit_message, diff_base: Optional[str] = None)`
  replaces lines 150-153 with `tool_errors += await _format_files(...)`.
- **models.py**: `format_scope: Literal["changed-lines", "file"] = "changed-lines"`
  on `LintConfig` with a docstring attribute entry.
- **engine.py:2720**: add `diff_base=diff_base,` to the call.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_unified_hunks` | M1 | `@@ -1,0 +2,3 @@` → `[(2, 4)]`; `@@ -5 +5 @@` → `[(5, 5)]`; `@@ -7,2 +7,0 @@` → `[]`; multiple hunks preserved in order |
| `test_merge_formats_only_changed_lines` | M1 | sandbox with `ruff.toml` formatter; feature branch commits `pkg/t9.py` containing an unformatted line `y = {'b':2}`; the task branch appends `x = {'a':1}`; after `engine.merge` the new line is `x = {"a": 1}` and the old line is **still** `y = {'b':2}`; lint commit exists |
| `test_merge_format_scope_file_reformats_whole_file` | M1 | same setup with `LintConfig(format_scope="file")` → both lines formatted (today's behaviour preserved behind the switch) |
| `test_new_file_is_formatted_whole` | M1 | task adds a new unformatted file → fully formatted (existing `test_merge_autofixes_formats_and_commits` already covers this; keep it green) |
| `test_black_line_ranges_argv` (skip if black missing) | M1 | `run_lint_pass` in a tmp git repo with `[tool.black]`, base file with two unformatted statements, task changes one → only that statement reformatted |

### Integration Tests
`pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py -q`
green; `test_engine*.py` unaffected (lint call signature is keyword-only).

---

## 5. Acceptance Criteria

- [ ] AC1: a task branch touching N lines of a formatter-unclean base file
      produces a lint commit that changes only those lines (plus ruff
      fixes), for both `black` and `ruff` formatters.
- [ ] AC2: files added by the task are formatted whole.
- [ ] AC3: `LintConfig(format_scope="file")` reproduces the previous
      whole-file behaviour.
- [ ] AC4: a `git diff` failure degrades to whole-file formatting and is
      recorded in `LintReport.tool_error` — never raises, never blocks.
- [ ] AC5: `engine.merge` passes its `diff_base` to the lint pass (covered
      by the sandbox tests, which go through `merge`).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.procs import run_bounded  # verified: lint.py:21
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, LintReport  # verified: lint.py:22
from parrot.flows.dev_loop.sdd_coder.lint import detect_formatter, resolve_bin, run_lint_pass  # verified: test_lint.py:11
```

### Existing Signatures
```python
# lint.py
async def _run(argv: List[str], cwd: str) -> Tuple[int, str, str]  # :29
async def run_lint_pass(cwd: str, changed: List[str], *, config: LintConfig, commit_message: str) -> LintReport  # :119
# models.py
class LintConfig(BaseModel): autofix: bool = True; formatter: LintFormatter = "auto"; error_select: List[str]  # :175-191
# engine.py (inside merge consolidation)
diff_base = await _consolidate_diff_base(ctx.feature_branch, branch, cwd=ctx.worktree)  # :2690
lint_report = await run_lint_pass(path, changed, config=self.roster.lint, commit_message=...)  # :2720
# tests
git_sandbox_feature  # conftest.py:114 → (worktree, feature_branch, base_path, index_path); ruff formatter via _RUFF_CFG (test_lint.py:34)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`ruff check --fix --range`~~ — no such option; only `ruff format --range`.
- ~~`black --line-ranges` on multiple files with different ranges~~ — the
  option is per invocation, so black runs once per file.
- ~~`LintReport.skipped_files`~~ — do not add report fields; use `tool_error`.

### Edit Sites (Blueprint Anchors)

Verified against: f3d22f21f

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` | MODIFY | `async def run_lint_pass(cwd: str, changed: List[str], *, config: LintConfig, commit_message: str) -> LintReport:` | `:119` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` | MODIFY | `                await _run([black, "--quiet", *py_files], cwd)` | `:151` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` | MODIFY | `            await _run([ruff, "format", "--quiet", *py_files], cwd)` | `:153` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `    error_select: List[str] = Field(default_factory=lambda: ["E9", "F63", "F7", "F82"])` | `:191` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `        lint_report = await run_lint_pass(` | `:2720` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py` | MODIFY | `async def test_merge_with_autofix_disabled_leaves_branch_untouched(git_sandbox_feature, noop_probe):` | `:93` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Compute ranges **after** `ruff check --fix` so ruff's edits are inside
  the formatted ranges; compare `diff_base` to the working tree (no second
  ref), which is exactly what `git diff -U0 <base> -- <path>` does.
- Process ruff ranges bottom-up; black gets all ranges in one call.
- `Literal` import already exists in models.py (`LintFormatter`).

### Known Risks / Gotchas
- `black --line-ranges` is available from black 24.1 (repo has 26.10.1);
  `ruff format --range` from ruff 0.4. Both are the repo's pinned tools; a
  tool that rejects the flag exits non-zero and the pass records
  `tool_error` without blocking, per today's contract.
- A hunk range that black cannot format in isolation (e.g. the middle of a
  multi-line statement) is extended by black itself to the enclosing
  statement — accepted.

### External Dependencies
None.

---

## 8. Open Questions

None.

---

## 9. Design Research Cross-Check

Status: skipped (ledger-driven; the issue itself proposed
`black --line-ranges`, and the ruff equivalent is documented).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-18 | Claude (agent:sdd-fix) | Initial spec from fixgroup:370ac5dae9cc / issue:fcd15f183e74 |
