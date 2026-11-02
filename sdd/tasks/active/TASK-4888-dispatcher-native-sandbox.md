# TASK-4888: Programmatic launch — dispatcher injects strict native settings

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4885, TASK-4886, TASK-4887
**Assigned-to**: unassigned

---

## Context

Spec §3 M2, §2 policies 2, 5, 6, 7, 9. `ClaudeCodeDispatcher` must give the two sandboxed
profiles (`sdd-worker`, `sdd-coder`) the strict native `--settings` compiled by TASK-4885 and
the child environment that selects TASK-4887's native hook branch. Everything else about the
dispatch (auth env, MCP, model, setting sources, non-SDD profiles) stays as it is. The dispatcher
keeps the SDK-bundled CLI — no `cli_path` override (policy 9; the two executables are qualified
separately in TASK-4891).

---

## Scope

- Add `sandbox_allowed_domains: List[str]` (empty default, validated with
  `validate_allowed_domains`) to `ClaudeCodeDispatchProfile`.
- In `_resolve_run_options`, for `_SANDBOXED_SUBAGENTS`: build `extra_args["settings"]` from
  `native_sandbox_settings(Path(cwd), allowed_domains=profile.sandbox_allowed_domains)`; convert
  its `ValueError` (primary checkout, non-repo cwd, bad domain) into `DispatchExecutionError` —
  `allow_project_root_cwd` never waives this for sandboxed profiles (policy 2).
- Build the env as a **copy** of `_resolve_dispatch_env()` plus `PARROT_SDD_SANDBOX_BACKEND=claude-native`
  (overriding any inherited value) and a per-dispatch `PARROT_SDD_CACHE_DIR` under the Claude
  scratch root; never mutate `self._cached_dispatch_env`.
- Remove that per-dispatch cache directory in `dispatch()`'s `finally:` (owned dir only).
- Tests in `test_models.py` and `test_dispatcher.py`, including final SDK argv inspection.

**NOT in scope**: `clients/base.py`, the anthropic satellite (`claude_agent.py`), the interactive
launcher (TASK-4889), docs. Non-sandboxed profiles must produce identical run options.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py` | MODIFY | `sandbox_allowed_domains` field + validator |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Native settings/env for sandboxed seats; cache cleanup |
| `packages/ai-parrot/tests/flows/dev_loop/test_models.py` | MODIFY | Field default/validation tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | Native settings/env/argv tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field                                  # models/claude.py:7
from pydantic import field_validator                                   # pydantic v2 (add to the same import line)
from parrot.flows.dev_loop import worktree_environment                 # dispatchers/claude.py:66
from parrot.flows.dev_loop import native_claude_sandbox                # NEW module from TASK-4885
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile     # models/__init__.py:64
# dispatchers/claude.py already imports: json, os, Path, shlex, sys (:33-38); DispatchExecutionError (:55)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py
class ClaudeCodeDispatchProfile(BaseModel):                            # :10 (anchor, 1 occurrence)
    setting_sources: List[Literal["user", "project", "local"]] = ...   # :32
    allow_project_root_cwd: bool = Field(...)                          # :46
    model: str = "claude-sonnet-4-6"                                   # :79 (2 occurrences in file! :79 and :110)
    mcp_servers: Optional[Dict[str, Any]] = Field(...)                 # :80

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
_SANDBOXED_SUBAGENTS = frozenset({"sdd-worker", "sdd-coder"})           # :94
async def dispatch(self, ...):                                         # :214
    run_options = self._resolve_run_options(profile, cwd)              # :302
    finally:                                                           # :513 (resets 4 ContextVars)
def _enforce_cwd_under_worktree_base(self, cwd, profile=None) -> None: # :523
def _resolve_run_options(self, profile, cwd) -> ClaudeAgentRunOptions: # :562 (anchor, 1 occurrence)
    extra_args: Optional[Dict[str, Optional[str]]] = None              # :628 (1 occurrence)
    if profile.subagent in _SANDBOXED_SUBAGENTS:                        # :629 — current hook-only settings :629-647
    env=self._resolve_dispatch_env() or None,                          # :659 (1 occurrence)
def _effective_setting_sources(self, profile) -> Optional[List[str]]:  # :670 (UNCHANGED)
def _resolve_dispatch_env(self) -> Dict[str, str]:                     # :741 (cached on self._cached_dispatch_env)

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py (read-only)
class ClaudeAgentRunOptions(BaseModel):                                # :85
    env: Optional[Dict[str, str]]                                      # :158
    extra_args: Optional[Dict[str, Optional[str]]]                     # :195
    cli_path: Optional[str]                                            # :130 — leave unset (policy 9)

# From TASK-4885 (native_claude_sandbox.py):
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]: ...
def validate_allowed_domains(domains: Sequence[str]) -> list[str]: ...
BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"; BACKEND_NATIVE = "claude-native"; CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"
# worktree_environment.claude_scratch_root() -> Path   # :211
```

### Does NOT Exist
- ~~`ClaudeCodeDispatchProfile.sandbox_allowed_domains`~~ — added by this task.
- ~~`ClaudeCodeDispatchProfile.sandbox_backend`~~ / a profile switch to turn native off — native is mandatory for sandboxed seats; there is no opt-out field.
- ~~`ClaudeAgentRunOptions.settings`~~ — settings travel only in `extra_args["settings"]`.
- ~~`parrot/clients/anthropic/claude_agent.py` under core~~ — the client is in the satellite package; do not modify it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py#ClaudeCodeDispatchProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_dispatch_env",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._effective_setting_sources",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher.dispatch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#claude_scratch_root"
  ]
}
```

---

## Implementation Notes

- Rollout consequence: after this task, sandboxed dispatches on a host whose strict sandbox cannot
  start fail closed (`failIfUnavailable`). That is intended (AC3); the feature only merges to `dev`
  after TASK-4891 qualifies a host. Do not add a fallback.
- Pure policy compilation is allowed in `_resolve_run_options` (no subprocess/network there).
- Cache-dir removal is blocking I/O: run `shutil.rmtree` via `asyncio.to_thread` and only for a path
  that is inside `claude_scratch_root() / "parrot-sdd-cache"` (never follow symlinks out).

---

## Implementation Blueprint

### Steps (in order)
1. Add the profile field + validator — *why*: invalid domains must fail at profile construction.
2. Replace the hook-only settings block with the compiled native settings — *why*: G1/G2.
3. Build the copied env with backend + cache dir — *why*: the hook branch selector (TASK-4887) and policy 5; the cached auth dict is shared across concurrent dispatches.
4. Clean the owned cache dir in `dispatch()`'s `finally:`.
5. Tests, including final SDK argv (`_build_command`) like `test_cli_argv_excludes_user_source`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py` (MODIFY)
```python
# occurrences: 2 for '    model: str = "claude-sonnet-4-6"' (verified: :79 and :110) — disambiguate:
# INSERT immediately ABOVE these two lines inside ClaudeCodeDispatchProfile (verified :79-80):
#     model: str = "claude-sonnet-4-6"
#     mcp_servers: Optional[Dict[str, Any]] = Field(
    sandbox_allowed_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Exact DNS hostnames the FEAT-768 native sandbox lets sandboxed seats "
            "(sdd-worker/sdd-coder) reach from Bash. Empty by default: no egress. "
            "URLs, wildcards, ports and IP literals are rejected."
        ),
    )

    @field_validator("sandbox_allowed_domains")
    @classmethod
    def _validate_sandbox_domains(cls, value: List[str]) -> List[str]:
        """Normalize and validate exact hostnames (spec policy 6)."""
        from parrot.flows.dev_loop.native_claude_sandbox import validate_allowed_domains

        return validate_allowed_domains(value)
```
**Why**: Pydantic surfaces the `ValueError` as a `ValidationError`; the lazy import keeps
`models` free of a module-scope dependency on the hook module. Change `from pydantic import
BaseModel, Field` (:7) to `from pydantic import BaseModel, Field, field_validator`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF '        extra_args: Optional[Dict[str, Optional[str]]] = None' dispatchers/claude.py) — :628
# REPLACE the `if profile.subagent in _SANDBOXED_SUBAGENTS:` block that follows it (:629-647) with:
        env: Optional[Dict[str, str]] = self._resolve_dispatch_env() or None
        if profile.subagent in _SANDBOXED_SUBAGENTS:
            # FEAT-768: the native Claude sandbox is the enforcement boundary; the retained
            # hook (guard → RTK → bounded shell) rides in the same settings object.
            try:
                settings = native_claude_sandbox.native_sandbox_settings(
                    Path(cwd), allowed_domains=profile.sandbox_allowed_domains
                )
            except ValueError as exc:
                raise DispatchExecutionError(f"Native sandbox refused cwd {cwd!r}: {exc}") from exc
            extra_args = {"settings": json.dumps(settings)}
            env = dict(env or {})  # copy: never mutate the cached auth overrides
            env[native_claude_sandbox.BACKEND_ENV] = native_claude_sandbox.BACKEND_NATIVE
            # FILL IN: env[CACHE_DIR_ENV] = str(claude_scratch_root()/"parrot-sdd-cache"/<uuid4 hex>)
            # — bounded by policy 5 (per-dispatch, under the scratch root, created lazily by tools)
```
**Why**: `ValueError` → `DispatchExecutionError` keeps the dispatcher's error contract. Add
`from parrot.flows.dev_loop import native_claude_sandbox` next to the `worktree_environment`
import (:66); drop `shlex`/`sys`/`worktree_environment` imports only if they become unused
(ruff will tell you; `worktree_environment` is still needed for `claude_scratch_root`).

```python
# occurrences: 1 (verified: grep -cxF '            env=self._resolve_dispatch_env() or None,' dispatchers/claude.py) — :659
# REPLACE that line with:
            env=env,
```

```python
# dispatch() finally: (verified: dispatchers/claude.py:513, the `finally:` followed by
# `_SESSION_HOST_CTX.reset(_host_token)` — quote both lines to disambiguate other `finally:` blocks)
# FILL IN: remove run_options.env[CACHE_DIR_ENV] when run_options was created and the path is inside
# claude_scratch_root()/"parrot-sdd-cache"; await asyncio.to_thread(shutil.rmtree, path, True);
# initialise `run_options = None` before the try that contains :302 — bounded by policy 5
```

### Tests (MODIFY `test_models.py` after `class TestDispatchProfile:` :130; `test_dispatcher.py` new class at end)
```python
# FILL IN: tests from Test Specification; sandboxed cases use the `linked_worktree` fixture (TASK-4886)
```

### FILL IN checklist
- [ ] per-dispatch cache dir value; bounded by policy 5
- [ ] owned-dir cleanup in `finally:`; bounded by policy 5 and "no blocking I/O in async"
- [ ] tests

---

## Acceptance Criteria

- [ ] `ClaudeCodeDispatchProfile().sandbox_allowed_domains == []`; bad domains raise `ValidationError`; good ones normalize.
- [ ] Both `sdd-worker` and `sdd-coder` (linked worktree cwd) get `extra_args["settings"]` with the strict `sandbox` object and the retained hook; env has `PARROT_SDD_SANDBOX_BACKEND=claude-native` even when the parent env sets another value.
- [ ] Sandboxed profile at the primary checkout raises `DispatchExecutionError`, also with `allow_project_root_cwd=True`.
- [ ] `_resolve_dispatch_env()`'s cached dict is unchanged after resolving two sandboxed profiles; two resolutions get different cache dirs.
- [ ] Non-sandboxed profiles (`sdd-qa`, `sdd-planner`, `None`) produce the same options as before (no settings, same env).
- [ ] `setting_sources` behavior unchanged (`TestSandboxedSettingSources` passes).
- [ ] Final SDK argv (via `SubprocessCLITransport._build_command`) contains `--settings` with the strict JSON; skips via `importorskip` are not counted as passing evidence (note it in the Completion Note if skipped).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

```python
class TestNativeSandboxDispatch:
    @pytest.mark.parametrize("subagent", ["sdd-worker", "sdd-coder"])
    def test_sandboxed_profile_gets_strict_settings(self, dispatcher, linked_worktree, subagent): ...
    def test_backend_env_overrides_inherited_value(self, dispatcher, linked_worktree, monkeypatch): ...
    def test_cached_auth_env_not_mutated(self, dispatcher, linked_worktree, monkeypatch): ...
    def test_primary_checkout_refused_even_with_waiver(self, dispatcher, tmp_path, monkeypatch): ...
    def test_non_sandboxed_profiles_unchanged(self, dispatcher, _patch_worktree_base): ...
    def test_final_cli_argv_carries_settings(self, dispatcher, linked_worktree): ...
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4885/4886/4887 are `done`.
2. Verify anchors (:7, :79-80 in models; :302, :513, :628, :659 in dispatcher), mark in progress.
3. Implement; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-anthropic/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4888 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
