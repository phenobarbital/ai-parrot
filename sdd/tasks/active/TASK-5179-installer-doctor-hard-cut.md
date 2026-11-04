# TASK-5179: Installer and doctor hard cut, resolved-root ignore rule

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5174
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and AC5-AC7. `parrot sdd install` and `parrot doctor` are where the hard cut
becomes visible: with worktrees still registered under `.claude/worktrees/` both refuse and print
the migration recipe from TASK-5174. The managed `.gitignore` block and doctor's `sdd: worktrees
ignored` check must classify the RESOLVED root identically: an in-repository root gets an anchored
literal ignore rule and a repository-relative probe; an external root gets neither (informational pass);
a root equal to the primary checkout itself is a configuration error.

Note: FEAT-804 (installer-portability-gaps) also edits `sdd/installer.py` and `self_/doctor.py`
(different functions); whichever feature merges second rebases.

---

## Scope

- `installer.py`: replace the fixed `GITIGNORE_BLOCK` worktrees line with a block rendered for
  `worktree_root(root)` (new `gitignore_block(root) -> str`); keep every other managed rule; escape
  gitignore metacharacters; omit the rule for an external root; raise `SddConfigError` (a `ValueError`,
  CLI exit 1) when the resolved root equals `root`. Update `_install_gitignore` and the docstring at line 943.
- `install_sdd_integration`: first statement (before `load_sdd_config`, dry-run included) refuses
  with `LegacyWorktreesError` when `legacy_worktrees(root)` is non-empty; message = header line +
  recipe, or header + the `ValueError` collision diagnostic when the recipe cannot be generated.
- `doctor._check_sdd_git`: resolved-root `sdd: worktrees ignored` (in-repo probe / external informational /
  repo-root failure) and new `sdd: legacy worktrees` check with the recipe (or diagnostic) as `fix`.
- Tests in `test_installer.py` and `test_doctor_sdd.py` (fixture `.gitignore` updated).

**NOT in scope**: running the recipe (never); `ensure` refusal (TASK-5176); docs (TASK-5180..5182).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | rendered ignore block, legacy refusal |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | resolved-root probe, legacy check |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | ignore-rule and refusal tests |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | MODIFY | fixture + legacy/custom-root tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.config import load_sdd_config  # TASK-4299                 # verified: sdd/installer.py:1111 (function-local import)
from parrot.sdd.config import (LEGACY_WORKTREE_ROOT, LegacyWorktreesError, SddConfigError,
                               legacy_migration_recipe, legacy_worktrees, worktree_root)   # TASK-5174 (SddConfigError: config.py:15)
from parrot.sdd.installer import GITIGNORE_BEGIN, install_sdd_integration, uninstall_sdd_integration   # used by tests/sdd/test_installer.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
GITIGNORE_BEGIN = "# >>> parrot sdd (managed) >>>"                        # line 47
GITIGNORE_END = "# <<< parrot sdd (managed) <<<"                          # line 48
GITIGNORE_BLOCK = (...)                                                   # lines 49-61; worktrees line at 51
def _install_gitignore(root: Path) -> str:                                # line 808 — calls _upsert_marker_block(text, GITIGNORE_BLOCK, GITIGNORE_BEGIN, GITIGNORE_END)
def worktree_test_isolation(root: Path, test_command: str | None) -> str | None:   # line 942 — docstring names .claude/worktrees (line 943)
def install_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False, portable=False,
                            base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True,
                            sdd_coder=True) -> list[str]                  # line 1064
    from parrot.sdd.config import load_sdd_config  # TASK-4299             # line 1111
    config = load_sdd_config(root)                                        # line 1113
            actions.append(_install_gitignore(root))                      # line 1138
# packages/ai-parrot/src/parrot/sdd/cli.py — install command wraps the call in
#   except (ValueError, RuntimeError) as exc: raise click.ClickException(str(exc))   # line 134 → stderr, exit 1

# packages/ai-parrot/src/parrot/self_/doctor.py
class DoctorCheck(BaseModel): name: str; ok: bool; detail: str = ""; fix: str = ""; informational: bool = False   # lines 40-47
def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]      # line 195
def _check_sdd_git(root: Path, branch: str) -> list[DoctorCheck]          # line 338; worktrees check lines 356-360

# packages/ai-parrot/tests/sdd/test_installer.py
def empty_repo(tmp_path: Path) -> Path                                    # fixture, line 31
def _ignored(repo: Path, rel: str) -> bool                               # line 488
def test_gitignore_block_ignores_worktrees_and_parrot_state(empty_repo)   # line 492 — asserts .claude/worktrees ignored (line 497)
def test_reinstall_upgrades_an_old_gitignore_block(empty_repo)            # line 549 — old block literal at line 552 (keep: it models an OLD block)

# packages/ai-parrot/tests/self_/test_doctor_sdd.py
def ready_repo(tmp_path, monkeypatch) -> Path                             # fixture line 27; writes ".claude/worktrees/\n" to .gitignore at line 44
def test_each_missing_prerequisite_fails_its_check_with_a_fix(...)        # line 82 — "sdd: worktrees ignored" case (keep passing)
```

### Does NOT Exist
- ~~`DoctorCheck.severity`~~ — only `ok` / `informational`.
- ~~`installer.LEGACY_WORKTREES_NOTE`~~ — the refusal is an exception, not a log line.
- ~~an absolute path inside `.gitignore`~~ — never written; external roots get no rule.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/self_/doctor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor_sdd.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_gitignore",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_sdd_git",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#DoctorCheck"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Classification (shared by installer and doctor — put ONE helper in `installer.py`, e.g.
  `worktree_root_scope(root) -> tuple[Literal["inside", "external", "repo-root"], str | None]`, returning the
  repo-relative POSIX path when inside): compare `worktree_root(root).resolve()` with `root.resolve()` so
  `../` overrides and symlinks classify the same as absolute paths (spec §3 M4).
- Ignore rule: `/<escaped repo-relative path>/`. Escape `\`, `*`, `?`, `[`, `!` (leading), `#` (leading) and
  trailing spaces with a backslash so the rule matches the literal directory.
- The `.parrot/` rule stays in the block: it covers the default root already, but the anchored worktree
  rule is still rendered (spec: "add /<repo-relative-resolved-root>/ for an in-repository root").
- Refusal ordering: legacy check is the very first statement of `install_sdd_integration`, before the
  `load_sdd_config` import, so `--dry-run` refuses too and nothing is written (AC5).
- Recipe-generation `ValueError` must not escape as a different exception: catch it and embed its
  message so the refusal is always `LegacyWorktreesError` (installer) / a failing check (doctor).
- Doctor external root: `ok=True, informational=True, detail="external worktree root; outside repository tracking scope"`, no `check-ignore` call.

---

## Implementation Blueprint

### Steps (in order)
1. Split `GITIGNORE_BLOCK` into the fixed rules + a renderer that inserts the worktree rule — *why*: AC7, the block must follow overrides.
2. Add the shared scope helper; use it in `_install_gitignore` and in doctor — *why*: identical classification (spec §2 Hard cut).
3. Add the legacy refusal at the top of `install_sdd_integration` — *why*: AC5.
4. Rewrite the doctor worktree check and add `sdd: legacy worktrees` — *why*: AC6, AC7.
5. Update tests; run validation.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"# SDD feature worktrees (parrot sdd worktree ensure)\\n.claude/worktrees/\\n"' ...installer.py)
# REPLACE line 51 inside GITIGNORE_BLOCK with a placeholder-free split: keep GITIGNORE_BLOCK as the block WITHOUT
# the worktrees rule (delete line 51), and add:
_WORKTREE_IGNORE_COMMENT = "# SDD feature worktrees (parrot sdd worktree ensure)"


def worktree_root_scope(root: Path) -> tuple[str, str | None]:
    """Classify ``worktree_root(root)``: ``("inside", rel)``, ``("external", None)`` or ``("repo-root", None)``.

    Canonical paths are compared, so relative ``../`` overrides and symlinks classify like absolute paths.
    """
    from parrot.sdd.config import worktree_root

    resolved, repo = worktree_root(root).resolve(), Path(root).resolve()
    # FILL IN: equal → ("repo-root", None); relative_to(repo) succeeds → ("inside", rel.as_posix()); else ("external", None)


def _gitignore_literal(rel: str) -> str:
    """Escape gitignore metacharacters so ``/<rel>/`` matches only the literal directory."""
    # FILL IN: backslash-escape \ * ? [ and a leading ! or #, and trailing spaces — bounded by test_gitignore_block_resolved_root


def gitignore_block(root: Path) -> str:
    """The managed block for ``root``: the fixed rules plus the resolved in-repository worktree rule.

    Raises:
        SddConfigError: the resolved worktree root is the repository itself.
    """
    from parrot.sdd.config import SddConfigError

    scope, rel = worktree_root_scope(root)
    if scope == "repo-root":
        raise SddConfigError("WORKTREE_BASE_PATH resolves to the repository root itself; point it at a subdirectory")
    if scope == "external":
        return GITIGNORE_BLOCK
    rule = f"{_WORKTREE_IGNORE_COMMENT}\n/{_gitignore_literal(rel)}/\n"
    return GITIGNORE_BLOCK.replace(f"{GITIGNORE_BEGIN}\n", f"{GITIGNORE_BEGIN}\n{rule}", 1)
```
```python
# _install_gitignore (line 808): use gitignore_block(root) instead of GITIGNORE_BLOCK in the _upsert_marker_block call,
# and drop "SDD worktrees" wording from its docstring in favour of "the resolved SDD worktree root (when inside the repo)".
# worktree_test_isolation docstring (line 943): "Why tests run inside a feature worktree (``<worktree root>/<feature>/``) may not ..."
```
```python
# occurrences: 1 (verified: grep -c '    from parrot.sdd.config import load_sdd_config  # TASK-4299' ...installer.py)
# BEFORE — insert above that line (verified: installer.py:1111), after the docstring; add
# "LegacyWorktreesError: worktrees are still registered under .claude/worktrees/ (nothing is written)." to the docstring's Raises:
    from parrot.sdd.config import LegacyWorktreesError, legacy_migration_recipe, legacy_worktrees

    legacy = legacy_worktrees(root)
    if legacy:
        header = "error: SDD worktrees still live under .claude/worktrees/ — move them first:"
        # FILL IN: lines = legacy_migration_recipe(root, legacy); on ValueError use
        #          [f"cannot generate a safe migration recipe: {exc}"]; raise LegacyWorktreesError("\n".join([header, *lines]))
```

### `packages/ai-parrot/src/parrot/self_/doctor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    ignored = _git(root, "check-ignore", "-q", ".claude/worktrees/x")' ...doctor.py)
# REPLACE lines 356-360 (the `ignored = ...` statement and its checks.append(...)) with:
    from parrot.sdd.config import legacy_migration_recipe, legacy_worktrees
    from parrot.sdd.installer import worktree_root_scope

    scope, rel = worktree_root_scope(root)
    # FILL IN: "repo-root" → failing "sdd: worktrees ignored" (fix: set WORKTREE_BASE_PATH to a subdirectory);
    #          "external" → ok=True, informational=True, detail="external worktree root; outside repository tracking scope";
    #          "inside"  → _git(root, "check-ignore", "-q", f"{rel}/x"); detail f"{rel}/ is|is NOT git-ignored";
    #                      fix "parrot sdd install (adds the .gitignore block)" when not ignored
    legacy = legacy_worktrees(root)
    # FILL IN: DoctorCheck(name="sdd: legacy worktrees", ok=not legacy,
    #          detail=f"{len(legacy)} worktree(s) registered under .claude/worktrees/" or "none under .claude/worktrees/",
    #          fix="\n".join(recipe) — recipe or the ValueError diagnostic, as in the installer)
    return checks
```
Update the function docstring: "Base branch on origin, ledger tracked, worktrees ignored, no legacy worktrees."
Check `parrot.self_.doctor` already imports from `parrot.sdd` lazily elsewhere (it degrades to informational when SDD modules are absent — see test line 112); keep these imports inside the function for the same reason.

### FILL IN checklist
- [ ] `worktree_root_scope`, `_gitignore_literal`; bounded by AC7.
- [ ] installer refusal message; bounded by AC5 (`git -C '<repo>' worktree repair` line present, or a diagnostic with no `mv`).
- [ ] doctor branches; bounded by AC6/AC7.
- [ ] `test_installer.py:497` → assert `.parrot/worktrees/feat-x/README.md` ignored; keep line 552's OLD literal (it models a legacy block); add `test_gitignore_block_resolved_root` (default, relative `wt dir/[x]`, absolute in-repo, external → no rule, repo-root → error; unrelated managed rules survive).
- [ ] `test_installer.py::test_install_refuses_legacy_worktrees` (real repo + `git worktree add .claude/worktrees/feat-FEAT-1-x`; dry-run and real both raise, `.gitignore`/`sdd/` untouched) and `test_install_cli_exit_1_on_legacy` (CliRunner on `parrot.sdd.cli` install → exit 1, recipe in output).
- [ ] `test_doctor_sdd.py:44` fixture writes `/.parrot/worktrees/\n`; add `test_doctor_legacy_worktrees_check` and `test_doctor_custom_root_scope` (relative + absolute in-repo pass after install; external `../outside` passes informationally without `check-ignore`; repo-root override fails).

---

## Acceptance Criteria

- [ ] Spec AC5: `parrot sdd install` (any host, `--dry-run` included) with registered legacy worktrees writes nothing, exits 1, prints the recipe (or an actionable diagnostic without runnable moves).
- [ ] Spec AC6 (doctor half): doctor reports `sdd: legacy worktrees` failing with the same recipe/diagnostic as `fix`.
- [ ] Spec AC7: anchored literal ignore rule for in-repository roots (overrides included); doctor probes the repo-relative path; external roots get no rule and no `check-ignore`; a repo-root override fails safely; unrelated managed rules preserved.
- [ ] `ruff check` clean on both source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_installer.py — append
def test_gitignore_block_resolved_root(empty_repo, monkeypatch): ...
def test_install_refuses_legacy_worktrees(tmp_path, monkeypatch): ...
def test_install_cli_exit_1_on_legacy(tmp_path, monkeypatch): ...
# packages/ai-parrot/tests/self_/test_doctor_sdd.py — append
def test_doctor_legacy_worktrees_check(ready_repo, monkeypatch): ...
def test_doctor_custom_root_scope(ready_repo, tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5174 must be `done`.
2. Verify anchors, mark `in-progress`, implement, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`. Clear `WORKTREE_BASE_PATH` in every new test.
3. Commit only the listed files; `parrot sdd task close TASK-5179 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
