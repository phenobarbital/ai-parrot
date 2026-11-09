# TASK-5453: Run the launcher trust gate's git call in the C locale

**Feature**: FEAT-862 — Launcher Trust Gate Reads git Errors in the C Locale
**Spec**: `sdd/specs/launcher-test-launcher-core-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:91d60a249533`
**Discovered-from**: `issue:a0b7a0210abc`

---

## Context

`_project_venv_trusted` (`packages/ai-parrot/src/parrot/launcher.py:213`) accepts a non-zero `git ls-files` exit only
when stderr contains `b"not a git repository"`. git localizes that message (`es_ES`: `fatal: no es un repositorio git
…`), so on a non-English machine the gate fails closed and `resolve_venv` refuses a valid project `.venv`. Six
launcher tests fail locally under a Spanish locale; all pass with `LC_ALL=C`. Implements spec §2 A + B, Module 1.

---

## Scope

- Build the `git ls-files` child environment from `os.environ` without `LANGUAGE` and with `LC_ALL=C`, and pass it as
  `env=` to the existing `subprocess.run` call in `_project_venv_trusted`.
- Add one sentence to the gate's docstring saying the git call runs in the C locale and why.
- Add `test_trust_gate_reads_git_errors_in_c_locale` to `test_launcher_core.py` (spec §4).

**NOT in scope**: changing the stderr check itself, the ownership checks, the tracked-file rule, other git-output
parsers in the codebase, or the fixtures of the existing launcher tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | C-locale env for the trust gate's git call + docstring |
| `packages/ai-parrot/tests/launcher/test_launcher_core.py` | MODIFY | `import subprocess` + regression test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `bf0f377114`.

### Verified Imports
```python
import os  # verified: launcher.py:8 (module level)
import subprocess  # verified: launcher.py:221 — local import inside _project_venv_trusted
from parrot import launcher  # verified: test_launcher_core.py:8
from .conftest import make_venv  # verified: test_launcher_core.py:9; conftest.py:10
import pytest  # verified: test_launcher_core.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/launcher.py
def _project_venv_trusted(venv: Path, script: str) -> bool  # :213; local `import subprocess` :221
#   tracked = subprocess.run(                                              # :232
#       ["git", "-C", str(work_tree), "ls-files", "-z", "--", venv.name],  # :233
#       capture_output=True, check=False, timeout=5,                       # :234
#   )
#   return b"not a git repository" in tracked.stderr.lower()               # :238
def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]  # :244
# packages/ai-parrot/tests/launcher/conftest.py
def make_venv(path: Path, *scripts: str) -> Path  # :10
# packages/ai-parrot/tests/launcher/test_launcher_core.py
def _reset_warnings(monkeypatch)  # :12, autouse — resets launcher._WARNED before each test
def test_loop_guard_is_consumed_not_inherited(tmp_path, monkeypatch)  # :219, last test; uses launcher.os.environ
```

### Does NOT Exist
- No `env=` argument on the gate's `subprocess.run` call today.
- No other git subprocess in `launcher.py` (`:328` is `subprocess.Popen` of the resolved target script).
- No `import subprocess` / `import os` in `test_launcher_core.py` (the file reaches `os` as `launcher.os`).
- `repository_paths` (`launcher.py:62`) never runs git — it reads `.git` directly, so faking `subprocess.run` for
  `ls-files` affects nothing else in `resolve_venv`.
- `packages/ai-parrot/build/` holds a stale copy of `launcher.py`; it is a build artifact — do not edit it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/launcher/test_launcher_core.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/launcher.py#_project_venv_trusted",
    "sym:packages/ai-parrot/src/parrot/launcher.py#resolve_venv",
    "sym:packages/ai-parrot/tests/launcher/conftest.py#make_venv"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Never mutate `os.environ`; build a new dict.
- Keep `capture_output=True, check=False, timeout=5` and the stderr check unchanged.
- The fake in the test intercepts only the `ls-files` call and delegates every other command to the real
  `subprocess.run`.
- Tests run in the worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against
  the main checkout).

### References in Codebase
- `test_locally_created_untracked_project_venv_is_trusted` (`test_launcher_core.py:211`) — same assertion shape.

---

## Implementation Blueprint

### Steps (in order)
1. Edit the docstring of `_project_venv_trusted` — so the reason for the env is recorded where the call lives.
2. Build `git_env` right before `tracked = subprocess.run(` and pass `env=git_env` — because git's message language
   follows `LC_ALL` > `LC_MESSAGES` > `LANG`, and `LANGUAGE` is dropped so a gettext that honours it under `C`
   still prints English.
3. Add `import subprocess` to the test file and append the regression test.
4. Run the Validation Commands, once as is and once with `LANG=es_ES.UTF-8 LANGUAGE=es`.

### `packages/ai-parrot/src/parrot/launcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'ignored/untracked, a committed one arrives with the clone. Fails closed when the repo cannot be queried.' packages/ai-parrot/src/parrot/launcher.py)
# AFTER — insert below `    ignored/untracked, a committed one arrives with the clone. Fails closed when the repo cannot be queried.` (verified: launcher.py:219)
    The ``git`` call runs with ``LC_ALL=C`` and without ``LANGUAGE``: git localizes its messages, and the fallback
    below matches the English "not a git repository".
```
```python
# occurrences: 1 (verified: grep -c '        tracked = subprocess.run(' packages/ai-parrot/src/parrot/launcher.py)
# REPLACE lines 232-235 (`tracked = subprocess.run(` … closing `)`) with:
        git_env = {key: value for key, value in os.environ.items() if key != "LANGUAGE"}
        git_env["LC_ALL"] = "C"
        tracked = subprocess.run(
            ["git", "-C", str(work_tree), "ls-files", "-z", "--", venv.name],
            capture_output=True, check=False, timeout=5, env=git_env,
        )
```
**Why**: spec §2 A. `os.environ` as the base keeps `PATH`, `HOME` and `GIT_*` exactly as the call inherits them today;
only the message language changes.

### `packages/ai-parrot/tests/launcher/test_launcher_core.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from pathlib import Path' packages/ai-parrot/tests/launcher/test_launcher_core.py)
# BEFORE — insert above `from pathlib import Path` (verified: test_launcher_core.py:4)
import subprocess
```
```python
# AFTER — append at end of file, after test_loop_guard_is_consumed_not_inherited (verified: test_launcher_core.py:219-223)


def test_trust_gate_reads_git_errors_in_c_locale(tmp_path, monkeypatch):
    """git localizes "not a git repository"; the gate runs it with LC_ALL=C (issue:91d60a249533, issue:a0b7a0210abc)."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    make_venv(home / "venv", "wikitoolkit")
    (proj / ".git").mkdir(parents=True)  # a .git entry git rejects as a repository
    make_venv(proj / ".venv", "wikitoolkit")
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    monkeypatch.setenv("LANGUAGE", "es")
    real_run = subprocess.run
    calls: list[dict[str, str]] = []

    def fake_run(cmd, *args, **kwargs):
        if "ls-files" not in cmd:
            return real_run(cmd, *args, **kwargs)
        child_env = kwargs.get("env") or dict(launcher.os.environ)
        calls.append(child_env)
        # FILL IN: choose stderr like git does — English "fatal: not a git repository (or any of the parent
        # directories): .git\n" when child_env["LC_ALL"] is "C", else the Spanish
        # "fatal: no es un repositorio git (ni ninguno de los directorios superiores): .git\n" (bytes) — bounded by AC-2
        return subprocess.CompletedProcess(cmd, 128, b"", stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    env = {"PARROT_HOME": str(home)}
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj) == (proj / ".venv", "project")
    assert calls and calls[0]["LC_ALL"] == "C" and "LANGUAGE" not in calls[0]
```
**Why**: spec §2 B. The fake reproduces git's localization, so the test fails on `dev` on every machine whatever
locales are installed. `launcher.os.environ` is the same `os.environ` the gate reads.

### FILL IN checklist
- [ ] `test_launcher_core.py::fake_run` — stderr choice by `LC_ALL`; bounded by AC-2

---

## Acceptance Criteria

- [ ] AC-1: `_project_venv_trusted` passes `env=` built from `os.environ` with `LC_ALL=C` and without `LANGUAGE`;
      nothing else in the gate changes behaviour.
- [ ] AC-2: `test_trust_gate_reads_git_errors_in_c_locale` fails without the launcher change and passes with it.
- [ ] AC-3: both Validation Commands pass, also with `LANG=es_ES.UTF-8 LANGUAGE=es` (38 existing + 1 new).
- [ ] AC-4: `test_committed_project_venv_is_never_executed` still passes.
- [ ] AC-5: `ruff check packages/ai-parrot/src/parrot/launcher.py packages/ai-parrot/tests/launcher/test_launcher_core.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/launcher/test_launcher_core.py -q`
- `pytest packages/ai-parrot/tests/launcher/test_launcher_reexec.py -q`

---

## Test Specification

See the blueprint's test block: one new test, `test_trust_gate_reads_git_errors_in_c_locale`. The existing
`test_resolve_order_and_validity`, `test_worktree_prefers_local_then_main` and the four reexec tests are the
locale-dependent evidence and stay unchanged.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug launcher-test-launcher-core-fixes --feature-id FEAT-862`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/launcher-test-launcher-core-fixes.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks and complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (also under the Spanish locale)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5453 launcher-test-launcher-core-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
