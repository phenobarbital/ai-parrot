# TASK-4459: Scope the engine formatter to the task's changed lines

**Feature**: FEAT-702 — Scope the engine formatter to the task's changed lines
**Spec**: `sdd/specs/fixgroup-370ac5dae9cc.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:fcd15f183e74

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:370ac5dae9cc; also addresses
`issue:2681d395f3ad`). `run_lint_pass` formats whole files
(`lint.py:151,153`), so a task touching an unclean base file commits a
whole-file reformat under `style(...): engine lint autofix` (590-line diff
for a 26-line change in FEAT-614). Implements spec §3 M1.

---

## Scope

- `lint.py`: `parse_unified_hunks`, `changed_line_ranges`, `_format_files`;
  `run_lint_pass(..., diff_base: Optional[str] = None)`.
- `models.py`: `LintConfig.format_scope`.
- `engine.py`: pass `diff_base=diff_base` at the merge-boundary call.
- Tests per spec §4.

**NOT in scope**: `ruff check --fix` scoping; `/sdd-done` lint pass;
fidelity/banned-import gates; `LintReport` fields.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` | MODIFY | hunk parsing + scoped formatting |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `format_scope` on `LintConfig` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `diff_base=` kwarg at `:2720` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py` | MODIFY | 4 new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.procs import run_bounded  # verified: lint.py:21
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, LintReport  # verified: lint.py:22
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: test_lint.py:10
from parrot.flows.dev_loop.sdd_coder.lint import detect_formatter, resolve_bin, run_lint_pass  # verified: test_lint.py:11
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, RosterConfig, RosterSeat  # verified: test_lint.py:12
```

### Existing Signatures to Use
```python
# lint.py
async def _run(argv: List[str], cwd: str) -> Tuple[int, str, str]  # :29 — rc 127 on OSError, 124 on timeout
def resolve_bin(name: str) -> Optional[str]  # :37
def detect_formatter(cwd: str, configured: str) -> str  # :66 → "black" | "ruff" | "none"
async def run_lint_pass(cwd: str, changed: List[str], *, config: LintConfig, commit_message: str) -> LintReport  # :119
# lint.py:146-153 (the block to replace):
#     if config.autofix:
#         await _run([ruff, "check", "--fix", "--exit-zero", "--quiet", *py_files], cwd)
#         if formatter == "black":
#             black = resolve_bin("black")
#             if black is None:
#                 tool_errors.append("black not found")
#             else:
#                 await _run([black, "--quiet", *py_files], cwd)
#         elif formatter == "ruff":
#             await _run([ruff, "format", "--quiet", *py_files], cwd)
# models.py:172 LintFormatter = Literal["auto", "black", "ruff", "none"]; LintConfig :175-191
# engine.py:2690 diff_base = await _consolidate_diff_base(ctx.feature_branch, branch, cwd=ctx.worktree)
# engine.py:2720-2725 lint_report = await run_lint_pass(path, changed, config=self.roster.lint, commit_message=f"style({ctx.feature}): {task.task_id} — engine lint autofix")
# conftest.py:114 git_sandbox_feature → (worktree, feature_branch, base_path, index_path); tasks TASK-0001..0005 with "## Files to Create / Modify" pointing at pkg/t<N>.py
# test_lint.py:34 _RUFF_CFG = '[lint]\nselect = ["F401", "E9", "F63", "F7", "F82"]\n[format]\nquote-style = "double"\n'
```

### Does NOT Exist
- ~~`ruff check --fix --range`~~; ~~`black --line-ranges` spanning files~~;
  ~~`LintReport.skipped_files`~~.
- ~~`import re` in lint.py~~ — add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py#run_lint_pass",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#LintConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.merge"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ranges are computed AFTER `ruff check --fix`, against the working tree
  (`git diff -U0 --no-color <diff_base> -- <path>`), so ruff's own edits
  are included in what gets formatted.
- `--- /dev/null` in that diff means the task added the file → whole-file.
- `[]` ranges (file listed as changed but no post-image lines, e.g. pure
  deletion) → skip the formatter for that file.
- ruff: one `--range a-b` call per hunk, iterate `reversed(ranges)`;
  black: one call with every `--line-ranges a-b`.
- Any non-zero `git diff` → fall back to whole-file for that file and append
  `f"line ranges unavailable for {path}: {err}"` to `tool_errors`.
- Never raise; never block (keep today's contract).

---

## Implementation Blueprint

### Steps (in order)
1. `models.py`: add `format_scope`.
2. `lint.py`: `import re`; `_HUNK_RE`; `parse_unified_hunks`; `changed_line_ranges`; `_format_files`; thread `diff_base`.
3. `engine.py`: pass `diff_base=diff_base`.
4. Tests, validation, `ruff check --fix` on the four files.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'error_select: List\[str\] = Field' models.py) — AFTER that line add:
    format_scope: Literal["changed-lines", "file"] = "changed-lines"
# and document it in the LintConfig docstring Attributes:
#   format_scope: ``changed-lines`` formats only the task's changed hunks (black ``--line-ranges`` /
#       ``ruff format --range``) so an unclean base file is not reformatted wholesale; ``file`` restores
#       whole-file formatting. Files the task added are always formatted whole.
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` (MODIFY)
```python
# imports: add `import re` (stdlib block, verified: lint.py:12-19)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def parse_unified_hunks(diff_text: str) -> List[Tuple[int, int]]:
    """Post-image ``(start, end)`` line ranges (1-based, inclusive) of every hunk in a ``-U0`` diff.

    Pure deletions (``+N,0``) are skipped: there is nothing to format.
    """
    ranges: List[Tuple[int, int]] = []
    for match in _HUNK_RE.finditer(diff_text):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count == 0:
            continue
        ranges.append((start, start + count - 1))
    return ranges


async def changed_line_ranges(cwd: str, diff_base: str, path: str) -> Tuple[Optional[List[Tuple[int, int]]], str]:
    """``(ranges, error)`` for ``path`` against ``diff_base`` in the working tree.

    ``ranges`` is ``None`` when the file has no base version (added by the task) or git failed —
    callers format the whole file then; ``error`` is non-empty only on the git failure.
    """
    rc, out, err = await _run(["git", "diff", "-U0", "--no-color", diff_base, "--", path], cwd)
    if rc != 0:
        return None, f"line ranges unavailable for {path}: {err.strip() or f'git exit {rc}'}"
    if re.search(r"^--- /dev/null", out, re.MULTILINE):
        return None, ""
    return parse_unified_hunks(out), ""


async def _format_files(
    formatter: str, tool: str, cwd: str, py_files: List[str], *, diff_base: Optional[str], scope: str
) -> List[str]:
    """Run the formatter over ``py_files``; whole-file or changed-lines per ``scope``. Returns tool-error notes."""
    if scope == "file" or diff_base is None:
        if formatter == "black":
            await _run([tool, "--quiet", *py_files], cwd)
        else:
            await _run([tool, "format", "--quiet", *py_files], cwd)
        return []
    notes: List[str] = []
    for path in py_files:
        ranges, error = await changed_line_ranges(cwd, diff_base, path)
        if error:
            notes.append(error)
        if ranges is None:
            argv = [tool, "--quiet", path] if formatter == "black" else [tool, "format", "--quiet", path]
            await _run(argv, cwd)
            continue
        if not ranges:
            continue
        if formatter == "black":
            flags = [flag for start, end in ranges for flag in ("--line-ranges", f"{start}-{end}")]
            await _run([tool, "--quiet", *flags, path], cwd)
        else:
            for start, end in reversed(ranges):
                await _run([tool, "format", "--quiet", "--range", f"{start}-{end}", path], cwd)
    return notes

# run_lint_pass signature (occurrences: 1):
async def run_lint_pass(
    cwd: str, changed: List[str], *, config: LintConfig, commit_message: str, diff_base: Optional[str] = None
) -> LintReport:
    # docstring Args: add
    #   diff_base: Merge-base commit the branch is compared against; enables ``LintConfig.format_scope``
    #       ``"changed-lines"``. ``None`` (or ``scope == "file"``) formats whole files as before.
    # REPLACE lines 148-153 (the black/ruff branches after the ruff --fix call) with:
        if formatter == "black":
            black = resolve_bin("black")
            if black is None:
                tool_errors.append("black not found")
            else:
                tool_errors += await _format_files("black", black, cwd, py_files, diff_base=diff_base, scope=config.format_scope)
        elif formatter == "ruff":
            tool_errors += await _format_files("ruff", ruff, cwd, py_files, diff_base=diff_base, scope=config.format_scope)
```
Module docstring: mention that the formatter is scoped to the task's changed
lines by default (FEAT-702).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'lint_report = await run_lint_pass(' engine.py) — add the kwarg:
        lint_report = await run_lint_pass(
            path,
            changed,
            config=self.roster.lint,
            commit_message=f"style({ctx.feature}): {task.task_id} — engine lint autofix",
            diff_base=diff_base,
        )
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py` (MODIFY)
```python
# AFTER test_merge_with_autofix_disabled_leaves_branch_untouched (verified: :93-109) — add:

def test_parse_unified_hunks():
    from parrot.flows.dev_loop.sdd_coder.lint import parse_unified_hunks
    diff = "@@ -1,0 +2,3 @@\n+a\n+b\n+c\n@@ -5 +5 @@\n-x\n+y\n@@ -7,2 +7,0 @@\n-p\n-q\n"
    assert parse_unified_hunks(diff) == [(2, 4), (5, 5)]
    assert parse_unified_hunks("") == []


async def _feature_file_with_unclean_base(git_sandbox_feature, engine_cfg, task_id, filename):
    """Commit an unclean base file on the feature branch; the task appends one unclean line."""
    ...  # helper: _write_and_commit(worktree, "ruff.toml", _RUFF_CFG, ...); _write_and_commit(worktree, filename, "y = {'b':2}\n", "base");
         # engine.prepare_native(...); append "x = {'a':1}\n" in the attempt worktree + commit; return engine


async def test_merge_formats_only_changed_lines(git_sandbox_feature, noop_probe):
    # LintConfig() default → after merge: file == "y = {'b':2}\nx = {\"a\": 1}\n"; lint commit present; tree clean


async def test_merge_format_scope_file_reformats_whole_file(git_sandbox_feature, noop_probe):
    # LintConfig(format_scope="file") → file == 'y = {"b": 2}\nx = {"a": 1}\n'


@pytest.mark.skipif(resolve_bin("black") is None, reason="black not installed")
async def test_black_formats_only_changed_lines(tmp_path):
    # tmp git repo with pyproject [tool.black] line-length=120; base commit "y = {'b':2}\n"; branch commit appends "x = {'a':1}\n";
    # run_lint_pass(str(repo), ["t.py"], config=LintConfig(), commit_message="style", diff_base="<base sha>")
    # → "y = {'b':2}\nx = {\"a\": 1}\n" and report.fixed_files == ["t.py"]
```
Use task ids/files the sandbox index already declares (TASK-0001 → `pkg/t1.py`,
TASK-0002 → `pkg/t2.py`, …); the base file must be committed on the
**feature** branch before `prepare_native` so the attempt branch sees it.

---

## Acceptance Criteria

- [ ] AC1–AC5 of the spec.
- [ ] All existing `test_lint.py` tests stay green.
- [ ] No linting errors on the four files.

---

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py -q -p no:cacheprovider -o addopts=""`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine.py -q -p no:cacheprovider -o addopts="" -k "merge"` (merge-path regression)

---

## Test Specification

See blueprint and spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-370ac5dae9cc --feature-id FEAT-702`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-370ac5dae9cc.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the four listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4459 fixgroup-370ac5dae9cc verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: agent:sdd-fix (Claude Code session)
**Date**: 2026-10-18
**Notes**: run_lint_pass gained diff_base (engine.merge passes its merge base) and
LintConfig.format_scope ("changed-lines" default, "file" = previous behaviour).
parse_unified_hunks/changed_line_ranges derive post-image hunks from
`git diff -U0 <base> -- <file>` after ruff --fix; black gets every hunk as
--line-ranges in one call, ruff format gets one --range per hunk bottom-up
(ruff's A-B is A:1-B:1, so the inclusive hunk is passed as start-(end+1)).
Added files and git failures fall back to whole-file formatting (failure noted
in tool_error). 11 tests in test_lint.py pass (6 new: hunk parser, ruff
changed-lines via engine.merge, scope=file via engine.merge, black
changed-lines, unusable diff_base fallback, added file); 88 merge-path tests
(test_engine_plan_merge/dispatch, native_observations, integration_chunk) pass.

**Deviations from spec**: the two engine.merge sandbox tests add a sixth
MODIFY-shaped task (TASK-0006 on pkg/base.py) to the sandbox index inside the
test instead of reusing TASK-0002/0003 — the planner routes a CREATE task whose
target already exists away from the native seat. conftest.py untouched.

