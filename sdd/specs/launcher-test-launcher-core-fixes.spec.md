---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [launcher, testing, ledger-fix]
docs:
  policy: none
---

# Feature Specification: Launcher Trust Gate Reads git Errors in the C Locale

**Feature ID**: FEAT-862
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:88be2347)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:91d60a249533`, `issue:a0b7a0210abc`

> Ledger-driven fix. Drains the `/sdd-fix` group `fixgroup:d1d0751c21b5` (`issue:91d60a249533`, minor bug) and, after
> research showed the same root cause, the separately planned `fixgroup:374de6e4add3` (`issue:a0b7a0210abc`, minor
> bug), claimed by the same actor. No brainstorm or proposal: the issue bodies are the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`_project_venv_trusted` (`packages/ai-parrot/src/parrot/launcher.py:213`) runs
`git -C <work_tree> ls-files -z -- .venv`. When git exits non-zero it accepts the venv only if the lowercased stderr
contains `b"not a git repository"` (`launcher.py:238`) — the case of a `.git` entry that git itself rejects as a
repository. git localizes that message. With `LANG=es_ES.UTF-8` / `LANGUAGE=es` (git 2.43.0), an empty `.git`
directory yields:

```
fatal: no es un repositorio git (ni ninguno de los directorios superiores): .git
```

The match fails, the gate fails closed, `resolve_venv` warns `project venv … is tracked by git or not owned by you`
and falls through to the next candidate. A valid, locally created project `.venv` is refused on every non-English
machine whose project `.git` git does not accept.

Observed on `dev` @ `c75c07db6c`, Spanish locale: 6 of 38 launcher tests fail —
`test_launcher_core.py::test_resolve_order_and_validity`, `::test_worktree_prefers_local_then_main`, and
`test_launcher_reexec.py::test_managed_reexecs_into_project`, `::test_linked_worktree_local_then_main`,
`::test_leading_project_flag_is_stripped`, `::test_managed_to_project_reexec_stdio`. With `LC_ALL=C` all 38 pass.
CI runs in an English locale, which is why only local runs fail.

### Goals
- The trust gate's `git ls-files` call runs with `LC_ALL=C` and without `LANGUAGE`, so its stderr is English
  whatever the caller's locale, and the existing `b"not a git repository"` check is deterministic.
- All 38 tests under `packages/ai-parrot/tests/launcher/` pass under a Spanish locale.
- A regression test proves the gate gets an English message even when the caller's environment is localized,
  without depending on which locales the test machine has installed.

### Non-Goals (explicitly out of scope)
- Replacing the stderr text match with another detection method (exit code 128 is shared with other fatal errors,
  such as dubious ownership, which must stay fail-closed).
- Changing which venvs are trusted: ownership checks, the tracked-file check and the "no `.git` → trusted" rule stay
  as they are.
- Other places in the codebase that parse git output.
- `test_resolve_order_and_validity` and the reexec tests: their fixtures are correct and stay unchanged.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:220ca21c832f618307fe587455d73c608619c94abe400f30dbd4242545c31094 evaluation_digest=sha256:4c9dde5dfa2c04c6fb2fb9cc044f368b0ae73a9f0edd2d20d20445fc60fa0582 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One edit in `launcher.py`, one new test.

**A. `_project_venv_trusted`.** Before the `git ls-files` call, build the child environment from `os.environ`, drop
`LANGUAGE` and set `LC_ALL=C`; pass it as `env=` to `subprocess.run`. Why both: `LC_ALL` outranks `LC_MESSAGES` and
`LANG`, and GNU gettext ignores `LANGUAGE` once the locale is `C`. Dropping `LANGUAGE` as well keeps the result
English with a gettext that does not apply that rule. Using `os.environ` as the base keeps every other variable
(`PATH`, `HOME`, `GIT_*`) exactly as the call inherits it today. The docstring states that the call runs in the C
locale and why.

`ls-files -z` prints raw bytes and the gate only tests whether stdout is empty, so the C locale's `LC_CTYPE` changes
nothing for non-ASCII paths.

**B. Regression test.** `test_trust_gate_reads_git_errors_in_c_locale` sets a localized environment
(`LC_ALL=es_ES.UTF-8`, `LANGUAGE=es`), builds a project with an empty `.git` directory and a valid `.venv`, and
replaces `subprocess.run` with a fake for the `ls-files` call. The fake behaves as git does: exit 128 with the English
message when the child environment's `LC_ALL` is `C`, with the Spanish message otherwise. `resolve_venv` must return
`(proj/.venv, "project")`, and the fake must have been called. It fails on `dev` on every machine, whatever locales are
installed.

### Integration Points
| Existing component | Interaction |
|---|---|
| `resolve_venv` → `_project_venv_trusted` | unchanged call; the gate now gives the same answer in every locale |
| `_resolved_target` / re-exec path | unchanged; the four reexec tests pass once the gate is fixed |

## 3. Module Breakdown

### Module 1: C-locale git call in the trust gate
- **Path**: `packages/ai-parrot/src/parrot/launcher.py`
- **Responsibility**: A above.
- **Interface Skeleton**:
```python
def _project_venv_trusted(venv: Path, script: str) -> bool:  # verified: launcher.py:213 (signature unchanged)
    """(existing docstring) + the ``git ls-files`` call runs with ``LC_ALL=C`` and without ``LANGUAGE``, because the
    "not a git repository" check below matches git's English message."""
```
- **Tests**: `packages/ai-parrot/tests/launcher/test_launcher_core.py` (new case, §4).

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1 | no | three-line change; implemented in the `/sdd-fix` session |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_trust_gate_reads_git_errors_in_c_locale` | 1 | localized caller env + empty `.git` + valid `.venv`; a fake `ls-files` answers in Spanish unless `LC_ALL=C`; `resolve_venv` returns the project venv; fails on `dev` |
| `test_resolve_order_and_validity`, `test_worktree_prefers_local_then_main` | 1 | existing; pass under a Spanish locale after the fix |
| `test_committed_project_venv_is_never_executed` | 1 | existing; a tracked venv is still refused |

### Integration Tests
| Test | Description |
|---|---|
| `test_launcher_reexec.py` | the four re-exec tests pass under a Spanish locale; the rest are unchanged |

### Validation Contract

tests:
- packages/ai-parrot/tests/launcher/test_launcher_core.py
- packages/ai-parrot/tests/launcher/test_launcher_reexec.py
markers: none

## 5. Acceptance Criteria
- [ ] `_project_venv_trusted` passes `env=` to its `git ls-files` call, built from `os.environ` with `LC_ALL=C` and
      without `LANGUAGE`; no other line of the gate changes behaviour.
- [ ] `test_trust_gate_reads_git_errors_in_c_locale` exists, fails without the fix and passes with it.
- [ ] `pytest packages/ai-parrot/tests/launcher/` passes with `LANG=es_ES.UTF-8 LANGUAGE=es` (38 existing + 1 new).
- [ ] `test_committed_project_venv_is_never_executed` still passes (a tracked venv is refused).
- [ ] `ruff check` is clean on the changed files; the Validation Contract passes.

## 6. Codebase Contract

Verified against `origin/dev` @ `c75c07db6c`.

### Verified Imports
```python
import os  # verified: launcher.py module-level (os.environ, os.getuid, os.lstat already used in the gate)
import subprocess  # verified: launcher.py:221 — local import inside _project_venv_trusted
from parrot import launcher  # verified: test_launcher_core.py:8
from .conftest import make_venv  # verified: test_launcher_core.py:9; conftest.py:10
import pytest  # verified: test_launcher_core.py:6
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/launcher.py
def repository_paths(cwd: Path) -> tuple[Path, Path | None]  # :62 — reads .git directly, never runs git
def _project_venv_trusted(venv: Path, script: str) -> bool  # :213; local `import subprocess` :221
#   tracked = subprocess.run(["git", "-C", str(work_tree), "ls-files", "-z", "--", venv.name],  # :232-233
#       capture_output=True, check=False, timeout=5,)  # :234
#   return b"not a git repository" in tracked.stderr.lower()  # :238
def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]  # :244
# packages/ai-parrot/tests/launcher/conftest.py
def make_venv(path: Path, *scripts: str) -> Path  # :10
# packages/ai-parrot/tests/launcher/test_launcher_core.py
def _reset_warnings(monkeypatch)  # :12, autouse — resets launcher._WARNED
def test_loop_guard_is_consumed_not_inherited(tmp_path, monkeypatch)  # :219, last test in the file
```

### Does NOT Exist
- No `env=` argument on the gate's `subprocess.run` call; the child inherits the caller's locale.
- No other `subprocess` call to git in `launcher.py` (`:328` is the `Popen` of the resolved target script).
- No second source copy of `_project_venv_trusted` (`packages/ai-parrot/build/` is a stale build artifact, not
  source).
- No `import subprocess` or `import os` in `test_launcher_core.py`.

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | `    ignored/untracked, a committed one arrives with the clone. Fails closed when the repo cannot be queried.` | 219 | 1 | MODIFY (docstring sentence after) |
| same | `        tracked = subprocess.run(` | 232 | 1 | MODIFY (env built before) |
| same | `            capture_output=True, check=False, timeout=5,` | 234 | 1 | MODIFY (add `env=`) |
| `packages/ai-parrot/tests/launcher/test_launcher_core.py` | `from pathlib import Path` | 4 | 1 | MODIFY (add `import subprocess` before) |
| same | end of file (after `test_loop_guard_is_consumed_not_inherited`) | 223 | 1 | MODIFY |

## 7. Implementation Notes & Constraints
- Build the child env with a comprehension over `os.environ` (no mutation of `os.environ`).
- Keep the stderr check as is; only the locale of the message changes.
- The fake in the regression test must intercept only the `ls-files` call and delegate any other command to the
  real `subprocess.run`.
- Run the tests in the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- Ledger linkage: `issue:91d60a249533`, `issue:a0b7a0210abc`.

### Known Risks / Gotchas
- A machine without the `C` locale does not exist on POSIX (`C`/`POSIX` is always built in), so `LC_ALL=C` never
  fails.
- On Windows the gate skips the ownership checks but runs the same `ls-files` call; setting `LC_ALL` and dropping
  `LANGUAGE` in the child environment is harmless there.

## Worktree Strategy
One feature worktree, one module, one task. No shared files, no exclusive resources, no cross-feature dependency.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:220ca21c832f618307fe587455d73c608619c94abe400f30dbd4242545c31094 evaluation_digest=sha256:4c9dde5dfa2c04c6fb2fb9cc044f368b0ae73a9f0edd2d20d20445fc60fa0582 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/launcher-test-launcher-core-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: launcher, ledger-fix, testing
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "launcher",
      "ledger-fix",
      "testing"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/launcher-test-launcher-core-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:4c9dde5dfa2c04c6fb2fb9cc044f368b0ae73a9f0edd2d20d20445fc60fa0582",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:220ca21c832f618307fe587455d73c608619c94abe400f30dbd4242545c31094",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions
- [x] Fix the fixture or the check (`issue:91d60a249533` left both open)? — *Resolved in /sdd-fix research*: the check.
      The fixture's empty `.git` is a valid case; the gate misreads git's localized error.
- [x] Set `LANG=C` as well? — *Resolved*: no; `LC_ALL` outranks `LANG`, so `LC_ALL=C` plus dropping `LANGUAGE` is
      enough.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
None: no wiki page documents the launcher trust gate. The gate's docstring records the C-locale call.

## Revision History
| Date | Change |
|---|---|
| 2026-11-10 | Initial spec from `/sdd-fix` groups `fixgroup:d1d0751c21b5` + `fixgroup:374de6e4add3` |
