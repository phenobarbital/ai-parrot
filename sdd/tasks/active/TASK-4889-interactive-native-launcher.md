# TASK-4889: Interactive launch — native launcher behind launch_worker.sh

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4885, TASK-4887
**Assigned-to**: unassigned

---

## Context

Spec §3 M3, §2 policies 2, 5, 6, 7, 9. `scripts/sdd/launch_worker.sh` is the only supported
interactive entry point. It must hand argument handling to a stdlib launcher in
`native_claude_sandbox.py` that validates the policy, refuses overrides, sets the native backend
environment and `exec`s the `claude` found on PATH with the compiled settings as ONE JSON argument.
Today's behavior (default `--model sonnet`, `--setting-sources project,local`, refusing the `user`
source, forwarding safe arguments) must be preserved.

---

## Scope

- Add `launch_worker(argv)` and `main()` (subcommand `launch-worker`) plus an
  `if __name__ == "__main__": main()` guard to `native_claude_sandbox.py`.
- Parse repeatable `--sandbox-allow-domain HOST` / `--sandbox-allow-domain=HOST`; reject caller
  `--settings`, `--add-dir`, an `--agent` other than `sdd-worker`, a `user` setting source, and
  equivalent aliases (split and `=` forms).
- Check host prerequisites (`claude`, `bwrap`, `socat` on PATH) → exit 1 with a clear message.
- Allocate a session cache dir under the scratch root (`PARROT_SDD_CACHE_DIR`), first removing
  stale dirs this launcher owns whose recorded PID is dead; set `PARROT_SDD_SANDBOX_BACKEND=claude-native`.
- Replace the shell script's argument loop/exec with a call to the launcher via the active interpreter.
- Update `tests/sdd/test_launch_worker.py`: existing tests run from a fake linked worktree, plus new cases.

**NOT in scope**: dispatcher (TASK-4888), live probes (TASK-4890), docs (TASK-4892). No network
probe or model call while compiling policy.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | `launch_worker`, `main`, `__main__` guard |
| `scripts/sdd/launch_worker.sh` | MODIFY | Delegate to the stdlib launcher |
| `tests/sdd/test_launch_worker.py` | MODIFY | Linked-worktree cwd + native launcher cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# native_claude_sandbox.py (TASK-4885) already has: os, Path, re, shlex, Any, Sequence, `_we`
import shutil   # add
import sys      # add
import uuid     # add (cache dir name)
```

### Existing Signatures to Use
```python
# From TASK-4885 (native_claude_sandbox.py):
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]: ...
BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"; BACKEND_NATIVE = "claude-native"; CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"
# worktree_environment.claude_scratch_root() -> Path      # :211

# scripts/sdd/launch_worker.sh (56 lines)
#   :1-22  header comment (usage, defaults, exit code 2)
#   set -euo pipefail                                     # :24 (anchor, 1 occurrence)
#   :26-46 argument loop refusing `user` sources
#   cmd=(claude --agent sdd-worker)                       # :48 (anchor, 1 occurrence)
#   :49-56 defaults + `exec "${cmd[@]}" "$@"`

# tests/sdd/test_launch_worker.py
REPO_ROOT = Path(__file__).resolve().parents[2]           # :17
LAUNCH_WORKER_SH = REPO_ROOT / "scripts" / "sdd" / "launch_worker.sh"   # :18
def fake_claude_path(tmp_path: Path) -> str:              # :22 fixture — stub prints argv one per line
def _run(path: str, *args: str) -> subprocess.CompletedProcess[str]:   # :32 (no cwd today)
def test_defaults_exclude_user_source(fake_claude_path: str) -> None:  # :42 (anchor, 1 occurrence)
def test_forwards_extra_args_and_keeps_caller_model(fake_claude_path: str) -> None:  # :52
```

### Does NOT Exist
- ~~`launch_worker`, `main` in `native_claude_sandbox.py`~~ — added by this task.
- ~~`--sandbox-allow-domain` in the current script~~ — new.
- ~~a `--no-sandbox` / `--legacy` launcher flag~~ — never add an unsandboxed escape (spec non-goals).
- ~~`cli_path` pinning~~ — the launcher uses PATH `claude`; the dispatcher keeps the bundled CLI (policy 9).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "scripts/sdd/launch_worker.sh", "action": "MODIFY"},
    {"path": "tests/sdd/test_launch_worker.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#claude_scratch_root"
  ]
}
```

---

## Implementation Notes

- Exit codes: 2 invalid input / rejected option / invalid cwd or domain; 1 missing prerequisite.
  Errors go to stderr, name the option or prerequisite, never print environment values.
- The agent frontmatter of `sdd-worker` also installs the same hook; with the backend env set,
  both instances take the native branch and produce the same rewrite. Leave the frontmatter alone.
- `os.execvpe` replaces the process, so the launcher cannot clean up after Claude exits; stale-dir
  cleanup on the next launch (PID recorded in an `owner.pid` file inside the dir) is the bound.
- Pass `--settings` as a single argv element containing the JSON — no shell interpolation, no file.

---

## Implementation Blueprint

### Steps (in order)
1. Add `launch_worker`/`main` to the module — *why*: one stdlib compiler for both paths (G4).
2. Shrink the shell script to an exec of the launcher — *why*: argument boundaries survive only in argv, not in shell re-parsing.
3. Update tests to run with `cwd=` a fake linked worktree and stub `bwrap`/`socat` — *why*: policy 2 refuses the primary checkout the tests run from today.

### `native_claude_sandbox.py` (MODIFY — append at end of file)
```python
_REJECTED_OPTIONS = ("--settings", "--add-dir")
_DEFAULT_MODEL = "sonnet"


def launch_worker(argv: Sequence[str]) -> int:
    """Launch sdd-worker with strict settings; return 2 for invalid input, 1 for unavailable host."""
    domains: list[str] = []
    forwarded: list[str] = []
    has_model = has_sources = False
    # FILL IN: walk argv preserving element boundaries; consume --sandbox-allow-domain[=]HOST into
    # `domains`; reject _REJECTED_OPTIONS and --agent values other than "sdd-worker" (split and "="
    # forms); reject a --setting-sources value whose comma list contains "user"; note --model and
    # --setting-sources presence; audit `claude --help` for aliases of these options and reject them
    # too — bounded by spec policy 7; on rejection print to stderr and return 2
    try:
        settings = native_sandbox_settings(Path.cwd(), allowed_domains=domains)
    except ValueError as exc:
        print(f"launch_worker: {exc}", file=sys.stderr)
        return 2
    missing = [name for name in ("claude", "bwrap", "socat") if shutil.which(name) is None]
    if missing:
        print(f"launch_worker: missing host prerequisite(s): {', '.join(missing)}", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env[BACKEND_ENV] = BACKEND_NATIVE
    # FILL IN: remove stale owned dirs under claude_scratch_root()/"parrot-sdd-cache" (owner.pid of a
    # dead process), create a new uuid dir with owner.pid = os.getpid(), env[CACHE_DIR_ENV] = it
    # — bounded by spec policy 5 (clean only owned cache directories)
    command = [shutil.which("claude") or "claude", "--agent", "sdd-worker"]
    if not has_sources:
        command += ["--setting-sources", "project,local"]
    if not has_model:
        command += ["--model", _DEFAULT_MODEL]
    command += ["--settings", json.dumps(settings), *forwarded]
    os.execvpe(command[0], command, env)
    return 1  # unreachable unless exec fails, which raises


def main() -> None:
    """Serve the launch-worker subcommand, forwarding the child exit status."""
    if len(sys.argv) < 2 or sys.argv[1] != "launch-worker":
        print("usage: native_claude_sandbox.py launch-worker [args...]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(launch_worker(sys.argv[2:]))


if __name__ == "__main__":
    main()
```
**Why**: the launcher is the module's only CLI, so `print` to stderr is the diagnostic channel
here (no logger is configured in an exec'ing launcher). Add `import json` with the other imports.
Conventions ban `print` for application logging; ruff does not enforce it (`ruff.toml` select has
no `T20`), so keep `print(..., file=sys.stderr)` confined to this CLI surface and say so in the
Completion Note.

### `scripts/sdd/launch_worker.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -cxF 'set -euo pipefail' scripts/sdd/launch_worker.sh) — :24
# KEEP lines 1-24 (update the header comment: add --sandbox-allow-domain HOST, exit 1 = missing
# prerequisite, and that the native Claude sandbox — FEAT-768 — now enforces isolation);
# REPLACE everything after `set -euo pipefail` (:26-56) with:

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="$(command -v python3 || true)"
if [[ -z "$python_bin" ]]; then
  echo "launch_worker.sh: python3 is required (activate the repository venv)" >&2
  exit 1
fi
exec "$python_bin" "$repo_root/packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py" \
  launch-worker "$@"
```
**Why**: running the module as a script keeps it stdlib-only (its sibling import of
`worktree_environment` resolves via `sys.path[0]`); `"$@"` preserves argument boundaries.

### `tests/sdd/test_launch_worker.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF 'def test_defaults_exclude_user_source(fake_claude_path: str) -> None:' tests/sdd/test_launch_worker.py) — :42
# FILL IN: add `bwrap`/`socat` stubs to the fake bin dir; give `_run` a `cwd` parameter and a
# fake linked worktree fixture (same layout as TASK-4886's conftest fixture — this file is outside
# packages/ai-parrot/tests, so define it locally); make the stub also print
# PARROT_SDD_SANDBOX_BACKEND so tests can assert it; keep the two existing tests' assertions
```

### FILL IN checklist
- [ ] argv walk + rejections (split/`=` forms, aliases); bounded by policy 7
- [ ] stale owned cache cleanup + new dir; bounded by policy 5
- [ ] tests

---

## Acceptance Criteria

- [ ] Defaults preserved: `--agent sdd-worker`, `--setting-sources project,local`, `--model sonnet`; caller `--model opus` kept once; `--verbose` and args with spaces forwarded intact.
- [ ] Exactly one `--settings` argument whose JSON has the strict sandbox object; repeated `--sandbox-allow-domain` hosts appear normalized in `allowedDomains`.
- [ ] `--settings`, `--settings=…`, `--add-dir`, `--agent other`, `--agent=other`, `--setting-sources user,project` → exit 2, `claude` never runs.
- [ ] Primary-checkout or non-repo cwd → exit 2; missing `bwrap`/`socat`/`claude` → exit 1.
- [ ] Child env has `PARROT_SDD_SANDBOX_BACKEND=claude-native` and a cache dir under the scratch root.
- [ ] `bash -n scripts/sdd/launch_worker.sh` passes; `ruff check` clean on the module and test.

---

## Validation Commands

- `pytest tests/sdd/test_launch_worker.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

---

## Test Specification

```python
def test_defaults_exclude_user_source(fake_claude_path: str, linked_cwd: Path) -> None: ...   # updated
def test_forwards_extra_args_and_keeps_caller_model(fake_claude_path: str, linked_cwd: Path) -> None: ...  # updated
def test_settings_is_one_strict_json_argument(fake_claude_path: str, linked_cwd: Path) -> None: ...
def test_allow_domain_repeatable_and_normalized(fake_claude_path: str, linked_cwd: Path) -> None: ...
@pytest.mark.parametrize("args", [["--settings", "{}"], ["--settings={}"], ["--add-dir", "/"], ["--agent", "x"], ["--agent=x"], ["--setting-sources", "user,project"]])
def test_policy_overrides_rejected(fake_claude_path: str, linked_cwd: Path, args: list[str]) -> None: ...
def test_primary_checkout_refused(fake_claude_path: str, tmp_path: Path) -> None: ...
def test_missing_prerequisite_exits_1(tmp_path: Path, linked_cwd: Path) -> None: ...
def test_backend_env_set_for_child(fake_claude_path: str, linked_cwd: Path) -> None: ...
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4885 and TASK-4887 are `done`.
2. Verify anchors (`set -euo pipefail` :24, test :42), mark in progress.
3. Implement; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4889 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
