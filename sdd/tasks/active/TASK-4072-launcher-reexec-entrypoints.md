# TASK-4072: Launcher re-exec + console-script wrappers + [project.scripts] repoint

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4071, TASK-4068
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (execution half). TASK-4071 created `parrot/launcher.py` with the pure
resolution functions. This task adds the re-exec primitive and the three console-script
wrappers, and repoints `[project.scripts]` so `parrot`, `wikitoolkit` and `bookstore` enter
through the launcher.

Key decisions (spec §3 M1, codex S1):
- **Resolution happens BEFORE importing any target.** `parrot.cli` pulls Click and
  `bookstore.cli` imports its config at module load; the wrappers must decide (and possibly
  re-exec) first and import the real entry only on the final interpreter.
- **Non-managed fast path** (spec §5 AC1): when `sys.prefix` is not under `$PARROT_HOME/venv`,
  or the loop guard is set, the wrapper does one cheap check and calls the real entry —
  byte-for-byte today's behaviour. The `wikitoolkit claude-hook` fast path
  (`wiki/entry.py`, FEAT-595) is preserved because the wrapper calls `entry.main` unchanged —
  also after a re-exec (the re-exec'ed project script is itself a launcher wrapper that sees
  the loop guard and goes straight to `entry.main`).
- POSIX re-exec is `os.execv`; Windows is a child process with inherited stdio, exit-code
  propagation and Ctrl-C/termination forwarding (bounded by spike S2 — validated by the
  windows leg of TASK-4068's install-matrix workflow).
- Loop guard env var `PARROT_LAUNCHER_RESOLVED` (`LOOP_GUARD_ENV`).

Also ships spike **S4** (launcher overhead) method + report (spec §5 AC3, §7 "Hook latency budget").

---

## Scope

- Add `reexec`, `main_parrot`, `main_wikitoolkit`, `main_bookstore` (+ private dispatch helper)
  to `parrot/launcher.py`, after TASK-4071's `resolve_venv`.
- Repoint the three `[project.scripts]` entries to `parrot.launcher:main_*`; leave
  `parrot-graphindex` untouched.
- Add the subprocess state-machine tests and the stdlib-only import test.
- Write the S4 overhead report (method + budget + results table).

**NOT in scope**: changing TASK-4071's resolution functions (fix them there if broken);
consolidating `parrot_home()` copies (TASK-4073); bootstrap shims (TASK-4074/4075); host
emitters (TASK-4081+); the Option D Rust launcher (spec non-goal unless S2 fails).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | Add `reexec`, `main_parrot`, `main_wikitoolkit`, `main_bookstore` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Repoint parrot/wikitoolkit/bookstore scripts to `parrot.launcher:main_*` |
| `packages/ai-parrot/tests/launcher/test_launcher_reexec.py` | CREATE | Subprocess state machine + managed→project stdio round-trip |
| `packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py` | CREATE | Import of `parrot.launcher` loads no third-party / extra parrot module |
| `sdd/state/FEAT-633/spikes/S4-launcher-overhead.md` | CREATE | Spike S4 method, budget, results |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Inside parrot/launcher.py — stdlib only, plus the TASK-4071 symbols in the same module:
#   parrot_home, is_managed, find_project_root, script_path, resolve_venv, LOOP_GUARD_ENV  (created by TASK-4071)
# Real entries, imported LAZILY inside the wrappers only (never at module top):
from parrot.cli import cli                                  # verified: packages/ai-parrot/src/parrot/cli/__init__.py:103-104 (@click.group(cls=LazyGroup) def cli)
from parrot.knowledge.wiki.entry import main               # verified: packages/ai-parrot/src/parrot/knowledge/wiki/entry.py:21
from parrot.knowledge.bookstore.cli import main            # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:609
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml:199-207
# [project.scripts]                                                   # line 199
# parrot = "parrot.cli:cli"                                           # line 200
# parrot-graphindex = "parrot.knowledge.graphindex.cli:main"          # line 202 — DO NOT TOUCH
# wikitoolkit = "parrot.knowledge.wiki.entry:main"                    # line 204
# bookstore = "parrot.knowledge.bookstore.cli:main"                   # line 206

# packages/ai-parrot/src/parrot/knowledge/wiki/entry.py
HOOK_ARGV = ["claude-hook"]                                           # line 18
def main() -> None:                                                   # line 21 — `sys.argv[1:] == HOOK_ARGV` → hook runtime + sys.exit;
                                                                      #   else imports parrot.knowledge.wiki.cli.main (lines 23-28)
# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
def main() -> None:                                                   # line 609 — calls bookstore() click group (line 611)
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                         # line 19
def cli(): ...                                                        # line 104 (decorated @click.group(cls=LazyGroup), line 103)

# packages/ai-parrot/src/parrot/__init__.py — imports os, logging, pathlib.Path, pkgutil.extend_path and
#   .version only (lines 6-19) ⇒ importing parrot.launcher legitimately loads `parrot` and `parrot.version`.

# TASK-4071 (dependency) creates in packages/ai-parrot/src/parrot/launcher.py:
#   LOOP_GUARD_ENV = "PARROT_LAUNCHER_RESOLVED"
#   def parrot_home(env=None) -> Path; def is_managed(prefix=None, *, env=None) -> bool
#   def find_project_root(argv, env, cwd) -> Path | None   (honours --project ONLY in leading position)
#   def script_path(venv, name, *, os_name=None) -> Path
#   def resolve_venv(script, *, argv, env, cwd) -> tuple[Path, str]   # rule in {'PARROT_VENV','project','VIRTUAL_ENV','managed'}
```

### Does NOT Exist
- ~~`parrot.launcher.reexec` / `main_parrot` / `main_wikitoolkit` / `main_bookstore`~~ — added here.
- ~~regenerated console scripts in the shared `.venv`~~ — editing `[project.scripts]` does NOT rewrite
  `.venv/bin/wikitoolkit`; tests must call `parrot.launcher.main_*` via `sys.executable -c`, never the
  installed console scripts.
- ~~a global `--project` option on parrot/wikitoolkit/bookstore~~ — the launcher's leading `--project`
  must be stripped before dispatch or Click will reject it.
- ~~`parrot.knowledge.graphindex.cli` behind the launcher~~ — out of scope; stays a direct entry.
- ~~any Windows job-object / ctypes helper in the repo~~ — none exists; S2 decides whether one is needed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/launcher/test_launcher_reexec.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S4-launcher-overhead.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/entry.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/entry.py#HOOK_ARGV",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#main",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`wiki/entry.py` (FEAT-595) is the model: module-level imports are `sys` only; the heavy import
happens inside the function after the cheap decision.

### Key Constraints
- **Never import a target at module top** in `launcher.py`.
- Wrapper return: real entries return `None` or raise `SystemExit` (Click standalone mode);
  wrappers return `int` (`0` when the entry returns `None`) and let `SystemExit` propagate.
- `reexec` sets `LOOP_GUARD_ENV=1` in the child environment, flushes `sys.stdout`/`sys.stderr`
  first, and writes nothing to stdout (spec §5 AC4).
- POSIX: `os.execv(str(target), argv)` after setting `os.environ[LOOP_GUARD_ENV] = "1"` (execv
  inherits `os.environ`). No return.
- Windows: `subprocess` is imported lazily inside the Windows branch only (keeps POSIX import
  set minimal). Inherit stdio (no pipes), ignore SIGINT in the parent while waiting (the child,
  same console, gets the Ctrl-C itself), return the child's exit code; terminate the child if the
  parent dies — FILL IN per spike S2 evidence.
- `--project`: if TASK-4071's leading-position `--project` was consumed, strip it (both
  `--project p` and `--project=p` forms) from the argv passed to the target, both on re-exec and
  on direct dispatch.
- A failure while resolving (OSError, missing cwd) must fall back to running in place, never crash.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/entry.py` — fast-path pattern
- `sdd/state/FEAT-633/spikes/S1-install-matrix.md` (TASK-4068) — windows leg = S2 validation vehicle

---

## Implementation Blueprint

### Steps (in order)
1. Add `_strip_project`, `_resolved_target`, `reexec`, `_dispatch` and the three `main_*` to `launcher.py` — *why*: resolution must precede target import.
2. Repoint the three `[project.scripts]` lines — *why*: installs pick up the launcher (the shared venv will not; tests avoid it).
3. Write `test_launcher_stdlib_only.py` — *why*: enforces the forever-rule (spec §5 AC3).
4. Write `test_launcher_reexec.py` — *why*: subprocess-level state machine (codex S3) + stdio integrity.
5. Measure and write S4 — *why*: AC3 latency evidence.

### `packages/ai-parrot/src/parrot/launcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def resolve_venv(' packages/ai-parrot/src/parrot/launcher.py — after TASK-4071)
# AFTER — append below the end of `def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]:`
#   (created by TASK-4071; the file does not exist at task-writing time, so this anchor is TASK-4071's blueprint symbol)
# Add to the module's stdlib imports if missing: `from collections.abc import Callable`, `from typing import Any`.

def _strip_project(argv: list[str]) -> list[str]:
    """Remove a LEADING ``--project p`` / ``--project=p`` (launcher-only option)."""
    if argv[:1] == ["--project"]:
        return argv[2:]
    if argv and argv[0].startswith("--project="):
        return argv[1:]
    return argv


def _resolved_target(script: str, argv: list[str]) -> Path | None:
    """Return the script to re-exec into, or None to run in this interpreter."""
    if os.environ.get(LOOP_GUARD_ENV) or not is_managed():
        return None
    try:
        venv, rule = resolve_venv(script, argv=argv, env=os.environ, cwd=Path.cwd())
    except OSError:
        return None
    return None if rule == "managed" else script_path(venv, script)


def reexec(target: Path, argv: list[str]) -> int:
    """Run ``target`` with ``argv`` (argv[0] included) under the loop guard.

    POSIX: ``os.execv`` (never returns). Windows: child process with inherited stdio;
    returns its exit code (spike S2).
    """
    os.environ[LOOP_GUARD_ENV] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name != "nt":
        os.execv(str(target), argv)
    # FILL IN: Windows — lazy `import subprocess, signal`; Popen([str(target), *argv[1:]]) with inherited
    #   stdio; SIGINT ignored in the parent while waiting; child terminated if the parent is torn down
    #   (job object via ctypes only if S2 shows orphans); return proc.returncode
    #   — bounded by spike S2 / TASK-4068 windows leg, spec §5 AC4 (no stdout bytes)
    raise NotImplementedError


def _dispatch(script: str, load_entry: Callable[[], Callable[[], Any]]) -> int:
    """Shared wrapper body: decide → maybe re-exec → else import and call the real entry."""
    argv = _strip_project(sys.argv[1:])
    target = _resolved_target(script, sys.argv[1:])
    if target is not None:
        return reexec(target, [str(target), *argv])
    sys.argv[1:] = argv
    result = load_entry()()
    return result if isinstance(result, int) else 0


def main_parrot() -> int:
    """``parrot`` console script (real entry ``parrot.cli:cli``)."""
    def load() -> Callable[[], Any]:
        from parrot.cli import cli
        return cli
    return _dispatch("parrot", load)


def main_wikitoolkit() -> int:
    """``wikitoolkit`` console script (``parrot.knowledge.wiki.entry:main``; keeps the claude-hook fast path)."""
    def load() -> Callable[[], Any]:
        from parrot.knowledge.wiki.entry import main
        return main
    return _dispatch("wikitoolkit", load)


def main_bookstore() -> int:
    """``bookstore`` console script (``parrot.knowledge.bookstore.cli:main``)."""
    def load() -> Callable[[], Any]:
        from parrot.knowledge.bookstore.cli import main
        return main
    return _dispatch("bookstore", load)
```
**Why**: one `_dispatch` keeps the three wrappers identical except the lazy import; the non-managed
path costs one env lookup + two `realpath` calls before today's call. Loop guard is set in the
parent's `os.environ` so `execv` inherits it.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^parrot = "parrot.cli:cli"' packages/ai-parrot/pyproject.toml)
# REPLACE — `parrot = "parrot.cli:cli"` (verified: packages/ai-parrot/pyproject.toml:200)
parrot = "parrot.launcher:main_parrot"

# occurrences: 1 (verified: grep -c '^wikitoolkit = "parrot.knowledge.wiki.entry:main"' packages/ai-parrot/pyproject.toml)
# REPLACE — `wikitoolkit = "parrot.knowledge.wiki.entry:main"` (verified: packages/ai-parrot/pyproject.toml:204)
wikitoolkit = "parrot.launcher:main_wikitoolkit"

# occurrences: 1 (verified: grep -c '^bookstore = "parrot.knowledge.bookstore.cli:main"' packages/ai-parrot/pyproject.toml)
# REPLACE — `bookstore = "parrot.knowledge.bookstore.cli:main"` (verified: packages/ai-parrot/pyproject.toml:206)
bookstore = "parrot.launcher:main_bookstore"

# UNCHANGED: `parrot-graphindex = "parrot.knowledge.graphindex.cli:main"` (pyproject.toml:202) and the comment lines 201/203/205/207.
```
**Why**: spec §2 Integration Points ("three entries repointed to `parrot.launcher` wrappers").
Keep the existing comment lines; optionally append "(fronted by parrot.launcher, FEAT-633)" to them.

### `packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py` (CREATE)
```python
"""parrot.launcher must import only the stdlib (spec §3 M1 hard rule, §5 AC3)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

ALLOWED_PARROT = {"parrot", "parrot.version", "parrot.launcher"}
PROBE = (
    "import sys, json\n"
    "before = set(sys.modules)\n"
    "import parrot.launcher\n"
    "print(json.dumps(sorted(set(sys.modules) - before)))\n"
)


def test_launcher_stdlib_only():
    out = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                         env=dict(os.environ), check=True, timeout=60).stdout
    loaded = json.loads(out)
    parrot_mods = {m for m in loaded if m == "parrot" or m.startswith("parrot.")}
    assert parrot_mods <= ALLOWED_PARROT, parrot_mods - ALLOWED_PARROT
    foreign = {m.split(".")[0] for m in loaded} - set(sys.stdlib_module_names) - {"parrot"}
    # FILL IN: allow-list only interpreter-private names that are stdlib in practice (e.g. "_distutils_hack"
    #   injected by a .pth would already be in `before`); keep this assertion strict — bounded by AC-3
    assert not foreign, foreign
```

### `packages/ai-parrot/tests/launcher/test_launcher_reexec.py` (CREATE)
```python
"""Subprocess state machine for parrot.launcher re-exec (spec §4 integration rows)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX execv path; Windows covered by the install matrix")
STUB = "#!{py}\nimport json, os, sys\nprint(json.dumps({{'venv': {name!r}, 'argv': sys.argv[1:], 'guard': os.environ.get('PARROT_LAUNCHER_RESOLVED')}}))\n"


def fake_venv(path: Path, name: str, *scripts: str) -> Path:
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for script in scripts:
        stub = path / "bin" / script
        stub.write_text(STUB.format(py=sys.executable, name=name), encoding="utf-8")
        stub.chmod(0o755)
    return path


@pytest.fixture
def fake_managed_home(tmp_path: Path) -> Path:
    """PARROT_HOME whose venv/ symlinks to the running interpreter's prefix ⇒ is_managed() is True."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "venv").symlink_to(sys.prefix, target_is_directory=True)
    return home


#: Resolution inputs inherited from the developer's shell/Claude session would hijack the matrix.
SCRUB = ("PARROT_LAUNCHER_RESOLVED", "PARROT_VENV", "PARROT_PROJECT", "CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_HOME")


def run_wrapper(func: str, args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    code = f"import sys; from parrot.launcher import {func}; sys.argv[0] = 'x'; sys.exit({func}())"
    base = {k: v for k, v in os.environ.items() if k not in SCRUB}
    return subprocess.run([sys.executable, "-c", code, *args], cwd=cwd, env={**base, **env},
                          capture_output=True, text=True, timeout=120, check=False)


def test_managed_reexecs_into_project(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "wikitoolkit")
    env = {"PARROT_HOME": str(fake_managed_home)}
    res = run_wrapper("main_wikitoolkit", ["status", "--x"], cwd=proj, env=env)
    payload = json.loads(res.stdout)
    assert payload == {"venv": "project", "argv": ["status", "--x"], "guard": "1"}


# FILL IN: matrix rows (codex S3) — PARROT_VENV wins; project venv missing the script ⇒ warning on
#   stderr once + falls to VIRTUAL_ENV stub; linked worktree (.git file) ⇒ worktree .venv then main
#   checkout; leading `--project <p>` from an unrelated cwd ⇒ that project, and stripped from argv;
#   loop guard preset ⇒ no re-exec (runs in place: use `main_bookstore` with `--help`, assert rc 0
#   and no stub JSON); not managed (PARROT_HOME elsewhere) ⇒ in place; no candidate ⇒ in place
#   — bounded by spec §4 test_launcher_state_machine_subprocess


def test_managed_to_project_reexec_stdio(fake_managed_home, tmp_path):
    """JSON-RPC initialize round-trip survives the re-exec; launcher writes nothing to stdout."""
    # FILL IN: project stub for `wikitoolkit` that reads one stdin line and answers a JSON-RPC
    #   initialize response; drive it through run_wrapper("main_wikitoolkit", ["mcp"], ...) with
    #   input=; assert stdout is exactly one JSON line with id 1, diagnostics only on stderr
    #   — bounded by spec §5 AC4
    raise NotImplementedError
```

### `sdd/state/FEAT-633/spikes/S4-launcher-overhead.md` (CREATE)
```markdown
# Spike S4 — launcher overhead (FEAT-633)

## Budget (spec §5 AC3, §7)
- Non-managed venv: `wikitoolkit claude-hook` latency unchanged **within noise** (target: median delta ≤ 5 ms).
- Managed → project re-exec: **tens of ms** total added (target: ≤ 50 ms median).

## Method
1. Baseline (old entry): `python -c "import sys; sys.argv=['wikitoolkit','claude-hook']; from parrot.knowledge.wiki.entry import main; main()" < hook.json`
2. Launcher, non-managed: same with `from parrot.launcher import main_wikitoolkit; main_wikitoolkit()`.
3. Launcher, managed → project: fake managed home (symlinked `venv`) + project `.venv` whose `wikitoolkit`
   is the real console script; time the full chain.
4. Run each ≥ 30 times (`hyperfine --warmup 3 -N` if available, else a `time.perf_counter` loop around
   `subprocess.run`); `hook.json` = a minimal PreToolUse payload. Also record `python -X importtime -c "import parrot.launcher"`.

## Results (fill)
| Case | Median (ms) | p95 (ms) | Δ vs baseline | Within budget? |
|---|---|---|---|---|
| Baseline entry.main | | | — | — |
| Launcher, non-managed | | | | |
| Launcher, managed→project | | | | |

## Verdict
<!-- pass | fail, machine, Python version, date -->
```

### FILL IN checklist
- [ ] `launcher.py::reexec` Windows branch — child process semantics; bounded by spike S2 / TASK-4068 windows leg
- [ ] `test_launcher_stdlib_only.py` — keep strict; only allow names provably preloaded by the interpreter
- [ ] `test_launcher_reexec.py` — remaining state-machine rows + stdio round-trip; bounded by spec §4
- [ ] S4 report — measured numbers

---

## Acceptance Criteria

- [ ] AC-1 (spec §5 AC1): with a non-managed `sys.prefix`, each `main_*` calls the real entry with unchanged argv and no output change (`test_launcher_reexec.py` "not managed" row).
- [ ] AC-2 (spec §5 AC2): from the managed venv the subprocess matrix lands on PARROT_VENV / project (worktree first, then main checkout) / VIRTUAL_ENV / in-place exactly per the order; the re-exec'ed process sees `PARROT_LAUNCHER_RESOLVED=1` and does not re-exec again.
- [ ] AC-3 (spec §5 AC3): `test_launcher_stdlib_only` passes — only `parrot`, `parrot.version`, `parrot.launcher` and stdlib modules are loaded; S4 report filled with numbers within budget.
- [ ] AC-4 (spec §5 AC4): the stdio round-trip test proves stdout carries only the JSON-RPC response; diagnostics on stderr.
- [ ] `[project.scripts]` maps `parrot`/`wikitoolkit`/`bookstore` to `parrot.launcher:main_parrot|main_wikitoolkit|main_bookstore`; `parrot-graphindex` unchanged.
- [ ] A leading `--project` is consumed by the launcher and never reaches the target CLI.
- [ ] `ruff check packages/ai-parrot/src/parrot/launcher.py packages/ai-parrot/tests/launcher/` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/launcher/test_launcher_reexec.py -q`
- `pytest packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py -q`

(Regression on the resolution half lives in TASK-4071's `test_launcher_core.py`; run it
too once TASK-4071 is done, but it is not this task's validation contract.)

---

## Test Specification

The two test-file blueprint blocks above are the scaffold. Fake managed home = `PARROT_HOME`
whose `venv` symlinks to `sys.prefix` (so `is_managed()` is genuinely true in the subprocess —
this also covers the "symlinked interpreter" row); project/explicit/VIRTUAL_ENV venvs are
`pyvenv.cfg` + executable Python stubs printing JSON. Wrappers are invoked as
`sys.executable -c "from parrot.launcher import main_…"` because the shared venv's console
scripts are not regenerated by the pyproject change.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4072 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
