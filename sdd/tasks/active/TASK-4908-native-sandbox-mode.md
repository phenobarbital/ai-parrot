# TASK-4908: Sandbox mode (required | preferred | off) with declared degraded launch

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4888, TASK-4889, TASK-4892
**Assigned-to**: unassigned

---

## Context

Spec §4 policy 10 "Sandbox mode (transition policy)", AC3 (amended) and AC13. TASK-4888 made the native
sandbox unconditionally mandatory for the `sdd-worker`/`sdd-coder` seats. The SDD flow runs in many
consumer repositories (FEAT-633 simplifies their installation); their developers cannot all harden
hosts at once (Ubuntu ≥23.10 needs an AppArmor profile for `bwrap`). The operator decided: default
stays `required`; a repository or developer may opt into `preferred` (declared degraded launch when the
native sandbox cannot start) or `off` (ephemeral CI). Degradation is never silent.

---

## Scope

- `native_claude_sandbox.py` (stdlib only — the hook imports it as a script sibling):
  - `MODE_ENV = "PARROT_SDD_SANDBOX_MODE"`, `DEGRADED_ENV = "PARROT_SDD_SANDBOX_DEGRADED"`,
    `SANDBOX_MODES = ("required", "preferred", "off")`.
  - `resolve_sandbox_mode(repo_root: Path) -> str`: `MODE_ENV` (stripped, lower-cased) → `[tool.parrot.sdd]
    sandbox` in `repo_root / "pyproject.toml"` (parse with `tomllib`; missing file/table/key → default) →
    `"required"`. Any other value raises `ValueError` naming the offending source.
  - `native_sandbox_available() -> tuple[bool, str]`: `shutil.which` for `claude`, `bwrap`, `socat` (missing
    → `(False, "missing prerequisite(s): …")`), then `subprocess.run([bwrap, "--unshare-user",
    "--unshare-pid", "--ro-bind", "/", "/", "true"], capture_output=True, text=True, timeout=10)`; nonzero or
    timeout → `(False, <first stderr line or "bwrap probe timed out">)`; else `(True, "")`.
  - `native_sandbox_settings(cwd, *, allowed_domains=(), include_sandbox: bool = True)`: when
    `include_sandbox` is False the returned object has **no** `sandbox` key and the same `hooks` block.
  - `plan_native_launch(cwd: Path, *, allowed_domains=()) -> tuple[str, bool, str, dict]` returning
    `(mode, degraded, reason, settings)`: `required` + unavailable → raise `RuntimeError(reason)`;
    `preferred` + unavailable → `(mode, True, reason, settings without sandbox)`; `off` → `(mode, True,
    "sandbox mode off", settings without sandbox)` with no probe; otherwise `(mode, False, "", strict settings)`.
  - `launch_worker`: use `plan_native_launch`; `ValueError` (bad mode) → exit 2; `RuntimeError` → print
    `launch_worker: native sandbox unavailable (<reason>); mode=required refuses to start` to stderr, exit 1;
    degraded → print `launch_worker: WARNING native sandbox unavailable (<reason>); mode=<mode> launches
    DEGRADED (hook only, no OS write boundary)` to stderr and set `DEGRADED_ENV=1` in the child env.
    Keep the existing prerequisite exit 1 for `claude` missing on every mode.
- `dispatchers/claude.py` `_resolve_run_options`, sandboxed branch: call `plan_native_launch(Path(cwd),
  allowed_domains=profile.sandbox_allowed_domains)`; `ValueError`/`RuntimeError` →
  `DispatchExecutionError(f"Native sandbox refused cwd {cwd!r}: {exc}")` (keep the existing message for
  root errors); degraded → `self.logger.warning("native sandbox DEGRADED for %s (mode=%s): %s", profile.subagent,
  mode, reason)` and `env[DEGRADED_ENV] = "1"`. Record the resolved mode and probe outcome in the dispatch
  labels/telemetry the dispatcher already emits for the sandboxed branch (add `sandbox_mode` and
  `sandbox_degraded` to the existing `DispatchLabels`/event payload if a free-form field exists; otherwise
  log them — do not invent a new event type).
- `worktree_environment.py` `hook_response`: in `claude-native` mode, when `DEGRADED_ENV == "1"`, prepend
  `echo '[sdd] degraded sandbox: no OS write boundary' >&2;` to the rewritten Bash command once per call
  (same `updatedInput` path). No other behaviour change.
- `docs/dev_loop/claude-native-sandbox.md`: new section "Sandbox mode" (table of modes, resolution order,
  `pyproject` snippet, exact warning lines, what degraded does and does not protect), and adjust
  "Failure handling and rollback" (rollback now also = set `required`).
- Tests: `tests/sdd/test_launch_worker.py` (mode resolution via env and via a `pyproject.toml` in the
  fake linked cwd's repo root; `required` + failing bwrap stub → exit 1 with reason; `preferred` + failing
  stub → exit 0 equivalent through the fake claude, settings JSON without `sandbox`, `PARROT_SDD_SANDBOX_DEGRADED=1`
  in child env, warning on stderr; `off` → no probe call; invalid mode → exit 2);
  `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (`resolve_sandbox_mode`
  precedence and errors, `native_sandbox_settings(include_sandbox=False)` shape, `plan_native_launch`
  with `native_sandbox_available` monkeypatched); `test_dispatcher.py` (`TestSandboxedSettingSources`:
  degraded dispatch has no `sandbox` key, sets the env marker, logs a warning; `required` raises
  `DispatchExecutionError`); `test_worktree_environment.py` (degraded banner prepended only when the marker is set).

**NOT in scope**: changing the default away from `required`; any automatic host remediation; the
MCP (nova/codex) seats; the live harness (it qualifies `required` only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | mode resolution, availability probe, `include_sandbox`, `plan_native_launch`, launcher wiring |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | sandboxed branch uses `plan_native_launch`; degraded warning + env marker + labels |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | degraded banner in native-mode Bash rewrite |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | "Sandbox mode" section, failure/rollback update |
| `tests/sdd/test_launch_worker.py` | MODIFY | launcher mode tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | resolution / settings / plan tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | degraded and required dispatch tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | degraded banner test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# native_claude_sandbox.py (stdlib only; already imports os, re, shlex, shutil, sys, json, uuid, ipaddress, pathlib.Path)
import subprocess
import tomllib            # stdlib ≥3.11; the repo runs 3.12
# dispatchers/claude.py already has:
from parrot.flows.dev_loop import native_claude_sandbox, worktree_environment
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError   # line 55 of the import block
```

### Existing Signatures to Use
```text
native_claude_sandbox.py
  BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"; BACKEND_NATIVE = "claude-native"; CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"   (lines 24-27)
  def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]        (line 165)
  def _parse_launch_arguments(argv) -> tuple[list[str], list[str], bool, bool]                              (line 329)
  def _allocate_session_cache() -> Path                                                                      (line 415)
  def launch_worker(argv: Sequence[str]) -> int   # exit 2 on ValueError, 1 on missing claude/bwrap/socat; os.execvpe(claude ...)  (line 441)
  _native_roots(cwd) -> (root, git_dir, primary)  # root is the linked worktree; the repo root for pyproject is `root`
dispatchers/claude.py
  _SANDBOXED_SUBAGENTS = frozenset({"sdd-worker", "sdd-coder"})                                             (line 94)
  self.logger = logging.getLogger(__name__)                                                                  (line 167)
  def _resolve_run_options(self, profile: ClaudeCodeDispatchProfile, cwd: str) -> ClaudeAgentRunOptions     (line 578)
    sandboxed branch (line 646-659): settings = native_claude_sandbox.native_sandbox_settings(Path(cwd), allowed_domains=profile.sandbox_allowed_domains)
      except ValueError as exc: raise DispatchExecutionError(f"Native sandbox refused cwd {cwd!r}: {exc}") from exc
      extra_args = {"settings": json.dumps(settings)}; env[BACKEND_ENV] = BACKEND_NATIVE; env[CACHE_DIR_ENV] = str(cache_dir)
worktree_environment.py
  def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]
    native Bash path: env = native.native_command_environment(task_cwd); wrapped = ["env", *(f"{k}={v}" ...), *shell]
native_artifacts.py (pattern to copy for pyproject parsing, do not import it from the stdlib-only module):
  tomllib.load(handle).get("tool", {}).get("parrot", {}).get("worktree")                                     (line 117)
tests
  tests/sdd/test_launch_worker.py: fixtures fake_claude_path(tmp_path) -> str (PATH with claude/bwrap/socat stubs), linked_cwd(tmp_path) -> Path;
    helper _run(path, cwd, *args) -> CompletedProcess (runs /bin/bash scripts/sdd/launch_worker.sh); existing test_missing_prerequisite_exits_1, test_backend_env_set_for_child
  packages/ai-parrot/tests/flows/dev_loop/conftest.py: fixture linked_worktree(tmp_path, monkeypatch) -> Path  (line 141)
  packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py: fixture dispatcher(monkeypatch) (line 109); class TestSandboxedSettingSources (line 766)
docs/dev_loop/claude-native-sandbox.md: section "## Failure handling and rollback" (line 90)
```

### Does NOT Exist
- ~~a `PARROT_SDD_SANDBOX_MODE` / `[tool.parrot.sdd]` reader anywhere~~ — create it in `native_claude_sandbox.py` only.
- ~~`conf.CLAUDE_CODE_SANDBOX_MODE` or any `parrot.conf` setting for this~~ — the hook cannot import `parrot.conf`; env + pyproject are the only sources.
- ~~an `allowUnsandboxedCommands`/`excludedCommands` based "degraded" setting~~ — degraded means *no* `sandbox` block, never a loosened one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "docs/dev_loop/claude-native-sandbox.md", "action": "MODIFY"},
    {"path": "tests/sdd/test_launch_worker.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#native_sandbox_settings",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#_parse_launch_arguments",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#hook_response"
  ]
}
```

---

## Implementation Notes

- Probe only once per launch/dispatch; never from the hook (hook calls must stay cheap).
- `pyproject.toml` location: the linked worktree root returned by `_native_roots` (each worktree carries the
  repo's `pyproject.toml`). Missing file → default silently; malformed TOML → `ValueError`.
- Keep `launch_worker`'s existing `missing host prerequisite(s)` exit 1 for `claude` on every mode; for
  `off`, `bwrap`/`socat` are not required.
- The degraded banner must go through the same `updatedInput` rewrite path (never a bare deny).
- Do not touch the live harness or the qualification report.

---

## Acceptance Criteria

- [ ] `resolve_sandbox_mode`: env beats pyproject beats default; invalid values raise with the source named.
- [ ] `required` + unavailable: launcher exit 1 with the probe reason on stderr; dispatcher raises `DispatchExecutionError`.
- [ ] `preferred` + unavailable and `off`: settings carry hooks and no `sandbox` key; child env has `PARROT_SDD_SANDBOX_BACKEND=claude-native` and `PARROT_SDD_SANDBOX_DEGRADED=1`; launcher warning line on stderr; dispatcher warning logged with mode and reason.
- [ ] `preferred` + available: identical to `required` + available (strict settings, no marker).
- [ ] Hook in native mode prepends the degraded banner only when the marker is set.
- [ ] Docs describe modes, resolution order, warnings and the degraded guarantees.
- [ ] `ruff check` clean on changed Python files; all Validation Commands green.

---

## Validation Commands

- `pytest tests/sdd/test_launch_worker.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q`

---

## Test Specification

Unit tests only (no live LLM): stub `bwrap` scripts in the launcher PATH fixture exit 0/1 to drive the probe;
`monkeypatch.setattr(native_claude_sandbox, "native_sandbox_available", lambda: (False, "probe"))` for the
dispatcher and plan tests; `caplog` for the dispatcher warning.

---

## Agent Instructions

1. Work only in the sub-worktree you are given; commit only the files in the table.
2. Verify every Codebase Contract entry before editing; stop and report if one is stale.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
