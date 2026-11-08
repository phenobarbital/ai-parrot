---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, agy, google-coding, hooks, subagents, dev-loop]
docs:
  policy: required
  pages:
    - wiki/sdd-tooling/sdd/agy-compatibility.md
  api_modules:
    - parrot.sdd.scripts.worktree_environment
    - parrot.sdd.scripts.dangerous_actions
    - parrot.sdd.installer
    - parrot.sdd.launch_cli
    - parrot.flows.dev_loop.feature_launcher
    - parrot.flows.dev_loop.models.google_coding
---

# Feature Specification: SDD Antigravity CLI (AGY) Operational Compatibility

**Feature ID**: FEAT-847
**Date**: 2026-11-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.25.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement
The AI-Parrot Spec-Driven Development (SDD) workflow currently achieves full operational autonomy on **Claude Code** and **OpenAI Codex**, but fails to run unattended or dispatch sub-agents reliably on **Google Antigravity CLI (`agy`)**:

1. **Interactive Confirmation Prompts on Every Command**:
   - `parrot sdd launch worker|brief|fix` (`parrot/sdd/launch_cli.py`, `parrot/flows/dev_loop/feature_launcher.py`) hardcodes `claude --setting-sources project,local` and has no `--host google` (`agy`) support (`--dangerously-skip-permissions`, `--mode auto`, `--sandbox`).
   - AGY's `PreToolUse` hook contract (`.agents/hooks.json`) uses tool names `run_command|write_file|edit_file`, camelCase input (`{"toolCall": {"name": "run_command", "args": {"CommandLine": "..."}}, "workspacePaths": [...]}`), and expects `{"decision": "allow" | "deny" | "ask" | "force_ask", "reason": "...", "overwrite": {"CommandLine": "..."}}` on stdout. Crucially, returning `{"decision": "allow"}` in an AGY `PreToolUse` hook auto-approves safe commands in interactive sessions without prompting the user per command. Currently, `worktree_environment.py` and `dangerous_actions.py` only parse Claude Code's `{"tool_name": "Bash", "tool_input": {"command": "..."}}` format and emit `{"hookSpecificOutput": ...}`, and `parrot/sdd/installer.py` only registers hooks in `.claude/settings.json` when `"claude" in hosts`.
2. **Sub-Agent Harness Mismatches (`sdd-worker`, `sdd-coder`, `sdd-research`, etc.)**:
   - `.agents/agents/` and `parrot/sdd/_assets/manifest.json` are missing `sdd-coder`, `code-reviewer`, and `qa-runner`.
   - `.agents/agents/sdd-worker/agent.md` (415 lines) is out of sync with `.claude/agents/sdd-worker.md` (827 lines): it lacks the FEAT-549 `parrot-sdd-coder` MCP orchestrator loop (`coder_init_run`, `coder_next_wave`, `coder_prepare_native`, `coder_record_native`, `coder_run_wave`, `coder_finalize_task`), FEAT-584 optimizations, and the FEAT-698 brief lane.
   - `.agents/agents/sdd-autopilot/agent.md` hardcodes `claude --agent ...` and `claude -p ...` shell calls instead of `agy`.
   - AGY's sub-agent tool is `invoke_subagent(TypeName, Role, Prompt, Model, Workspace)` and `manage_subagents(Action="list|kill|kill_all")`, not Claude's `Agent(...)` / `TaskStop`. Furthermore, AGY lacks a `"fork"` sub-agent type (used in `/sdd-proposal` §4.0 and `/sdd-spec` §3b; must map to `TypeName="self"` or `"research"`) and restricts `Model` to the enum `'inherit' | 'flash_lite' | 'flash' | 'pro'` (rejecting Claude model names `'haiku'` / `'sonnet'` returned by `coder_prepare_native`).
3. **Non-Persistent Working Directory (`cd`) in `run_command` & Missing Adaptation Contract**:
   - In AGY, each `run_command` executes in a fresh bash session where `cd` and environment variables do not persist across calls. SDD skills that run `WT=$(parrot sdd worktree ensure ...); cd "$WT"` in one step and then run bare commands in subsequent steps execute on the main checkout instead of the worktree.
   - `.agents/skills/sdd-*/SKILL.md` is shared by `"hosts": ["codex", "google"]` in `manifest.json`, yet its header only references `docs/sdd/CODEX.md` (`$sdd-*` syntax) with no `docs/sdd/AGY.md` adaptation contract.
4. **Snap Confinement & Dispatcher Profile Gaps**:
   - On Linux when `antigravity-cli` is installed as a Snap (`SNAP=/snap/antigravity-cli/...`), `$HOME` is remapped to `$SNAP_USER_COMMON` (`$SNAP_REAL_HOME` holds the host home) and `.venv/bin/python -> /usr/bin/python3.12` breaks inside the Snap mount namespace where Python lives at `$SNAP/usr/bin/python3`.
   - `GoogleCodingDispatchProfile` (`parrot/flows/dev_loop/models/google_coding.py`) restricts `mode` to `Literal["accept-edits", "plan"]` (missing `"auto"`) and `effort` to `Literal["low", "medium", "high"]` (missing `"xhigh"` and `"max"` supported by `agy` and `SeatEffort`).

### Goals
- Support dual-protocol (`claude` and `agy`) `PreToolUse` payloads and responses in `worktree_environment.py` and `dangerous_actions.py`, returning `{"decision": "allow"}` for safe/sandboxed commands in AGY to eliminate per-command confirmation prompts.
- Extend `parrot sdd install --host google` (`parrot/sdd/installer.py`) to install and manage `.agents/hooks.json` with `worktree-environment` and `dangerous-actions` guards.
- Extend `parrot sdd launch worker|brief|fix` (`parrot/sdd/launch_cli.py`, `parrot/flows/dev_loop/feature_launcher.py`) with `--host (claude|google)` support so `agy` workers and interactive sessions launch with `--dangerously-skip-permissions` and `--mode auto`.
- Add missing sub-agents (`sdd-coder`, `code-reviewer`, `qa-runner`) to `.agents/agents/` and `manifest.json`, synchronize `.agents/agents/sdd-worker/agent.md` with FEAT-549/FEAT-584/FEAT-698 using AGY sub-agent primitives (`invoke_subagent`, `manage_subagents`, model mapping `haiku -> flash`, `sonnet -> inherit`), and update `.agents/agents/sdd-autopilot/agent.md`.
- Create `docs/sdd/AGY.md` (the Antigravity Adaptation Contract covering tool mapping, per-command `cd "$WT" &&` discipline, reactive background tasks, and Snap interpreter resolution) and reference it in `.agents/skills/sdd-*/SKILL.md`.
- Align `GoogleCodingDispatchProfile` (`mode` and `effort` literals) with `agy` CLI capabilities and `SeatEffort`.

### Non-Goals (explicitly out of scope)
- Modifying Claude Code's existing `.claude/settings.json` hook format or behavior.
- Replacing the `codex` external reviewer seat in `/sdd-spec` §3b or `code-reviewer.md` (which remains explicitly bound to `codex` when configured in `sdd/config.json`).

---

## Governing Decisions

decision audit not configured in this repository

---

## 2. Architectural Design

### Overview
The compatibility layer bridges SDD's host-agnostic Python runtime and asset bundle with Antigravity CLI (`agy`) across four boundaries:
1. **Dual-Protocol PreToolUse Hooks**: `worktree_environment.py` and `dangerous_actions.py` inspect the incoming JSON payload on `stdin`. When `"toolCall"` is present (AGY protocol), they normalize `(tool_name, tool_input, cwd)` from `toolCall.name`, `toolCall.args`, and `workspacePaths[0]`, run the existing deterministic guards/wrappers, and serialize the response in AGY format (`{"decision": "allow" | "deny", "reason": ..., "overwrite": {"CommandLine": ...}}`).
2. **Installer & `.agents/hooks.json` Wiring**: `parrot/sdd/installer.py` registers `.agents/hooks.json` when `"google"` is among the target hosts, wiring both `dangerous-actions` and `worktree-environment` under `matcher: "run_command|write_file|edit_file"`.
3. **Host-Aware SDD CLI Launcher**: `parrot sdd launch worker|brief|fix` accepts `--host (claude|google)` (or `PARROT_SDD_HOST=google`), building an `agy` command line (`agy --agent sdd-worker --dangerously-skip-permissions --mode auto -p "run <FEAT-ID>"` or interactive session) when targeting Google.
4. **Sub-Agent Assets & `docs/sdd/AGY.md` Contract**: All 12 SDD agents are shipped under `.agents/agents/<name>/agent.md` in `manifest.json`, with `sdd-worker` updated to the FEAT-549 `parrot-sdd-coder` orchestrator loop and `docs/sdd/AGY.md` defining the canonical tool/model/CWD adaptations for `.agents/skills/sdd-*/SKILL.md`.

### Component Diagram
```
parrot sdd install --host google ──→ .agents/hooks.json ──→ worktree_environment.py (AGY protocol)
                                 ├─→ .agents/agents/*/agent.md (12 agents incl. sdd-coder, code-reviewer, qa-runner)
                                 └─→ .agents/skills/sdd-*/SKILL.md ──→ docs/sdd/AGY.md

parrot sdd launch worker --host google ──→ feature_launcher.py ──→ agy --agent sdd-worker --dangerously-skip-permissions --mode auto
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.scripts.worktree_environment` | extends | Adds AGY `toolCall` input parsing and `decision`/`overwrite` output rendering in `hook_response` |
| `parrot.sdd.scripts.dangerous_actions` | extends | Adds AGY `toolCall` evaluation in `evaluate` and `{"decision": "allow" \| "deny"}` rendering in `_render` |
| `parrot.sdd.installer` | extends | Installs/removes `.agents/hooks.json` for host `google` alongside `.claude/settings.json` for `claude` |
| `parrot.sdd.launch_cli` / `feature_launcher` | extends | Adds `--host` (`claude` \| `google`) option to `worker`, `brief`, and `fix` subcommands |
| `parrot.flows.dev_loop.models.google_coding` | modifies | Expands `GoogleCodingDispatchProfile.mode` (`"auto"`) and `effort` (`"xhigh"`, `"max"`) |

### Data Models
```python
class GoogleCodingDispatchProfile(BaseModel):
    mode: Optional[Literal["accept-edits", "auto", "plan"]] = Field(default=None)
    effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(default="high")
```

### New Public Interfaces
```python
# parrot/sdd/scripts/worktree_environment.py
def is_agy_payload(payload: dict[str, Any]) -> bool:
    """Return True when payload follows the Antigravity PreToolUse protojson contract."""
    ...

# parrot/sdd/scripts/dangerous_actions.py
def render_agy(verdict: Verdict) -> dict[str, Any]:
    """Render Verdict as an Antigravity PreToolUse response object."""
    ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Dual-Protocol Hook Scripts | yes | Exact AGY `toolCall` schema (`run_command`, `write_file`, `edit_file`) and `decision`/`overwrite` output dict fixed | — |
| M2: SDD Installer `.agents/hooks.json` Support | yes | Exact `.agents/hooks.json` structure and `plan_install`/`plan_uninstall` actions fixed | — |
| M3: Host-Aware SDD CLI Launcher (`--host google`) | yes | Exact CLI flags (`--host`) and `agy` command builder signatures fixed | — |
| M4: `GoogleCodingDispatchProfile` Model Alignment | yes | Exact `Literal` unions for `mode` and `effort` fixed | — |
| M5: SDD Sub-Agent Assets & `docs/sdd/AGY.md` Contract | yes | Asset paths in `manifest.json`, agent frontmatter, and adaptation rules fixed | — |

### Module 1: Dual-Protocol Hook Scripts (`worktree_environment.py` & `dangerous_actions.py`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`, `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py`
- **Responsibility**: Detect AGY `PreToolUse` payloads (`"toolCall"` key with `name` in `{"run_command", "write_file", "edit_file"}` and `args` containing `CommandLine` or `Path`), apply the existing worktree sandbox/PYTHONPATH rewrite and dangerous-actions rules, and emit AGY-compliant JSON (`{"decision": "allow" | "deny", "reason": ..., "overwrite": {"CommandLine": ...}}`).
- **Depends on**: Existing `worktree_environment` and `dangerous_actions` logic
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py (modifies worktree_environment.py:783)
  def is_agy_payload(payload: dict[str, Any]) -> bool:
      """Return True when payload is an Antigravity PreToolUse hook event (carries a dict 'toolCall')."""

  def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:  # verified: packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:783
      """Apply guards and file checks for Claude Code or Antigravity (AGY) PreToolUse payloads."""

  # packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py (modifies dangerous_actions.py:403)
  def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict:  # verified: packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:403
      """Pure decision for one PreToolUse payload (supports both Claude tool_name/tool_input and AGY toolCall)."""

  def _render_agy(verdict: Verdict) -> dict[str, Any]:
      """Render a Verdict into Antigravity's PreToolUse stdout JSON contract ({'decision': 'allow'|'deny', ...})."""
  ```

### Module 2: SDD Installer `.agents/hooks.json` Support
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py`
- **Responsibility**: When `"google"` is included in `hosts` during `parrot sdd install` (and `dangerous_guard=True`), register/update `.agents/hooks.json` with the `dangerous-actions` and `worktree-environment` `PreToolUse` hooks matching `run_command|write_file|edit_file`, and clean them up on `parrot sdd uninstall --host google`.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/installer.py (modifies installer.py:396, 523, 709)
  AGY_HOOKS_PATH: Path = Path(".agents/hooks.json")
  _AGY_DANGEROUS_MATCHER: str = "run_command|write_file|edit_file"

  def _install_agy_hooks(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
      """Merge SDD PreToolUse guard entries into <root>/.agents/hooks.json (foreign hook groups untouched)."""

  def _remove_agy_hooks(root: Path, receipt: dict[str, Any]) -> list[str]:
      """Remove SDD-managed PreToolUse guard entries from <root>/.agents/hooks.json."""
  ```

### Module 3: Host-Aware SDD CLI Launcher (`--host google`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`, `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`
- **Responsibility**: Add `--host` (`click.Choice(["claude", "google"])`, defaulting to `os.environ.get("PARROT_SDD_HOST", "claude")`) to `parrot sdd launch worker|brief|fix` and implement `launch_agy_worker` / `launch_session(..., host=...)` in `feature_launcher.py` so `agy` can be launched in tmux or foreground with `--agent sdd-worker --dangerously-skip-permissions --mode auto`.
- **Depends on**: None
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py (modifies feature_launcher.py:518, 642)
  def launch_agy_worker(
      agy_args: Sequence[str],
      *,
      cwd: Path,
      initial_prompt: str,
      base_env: Mapping[str, str] | None = None,
  ) -> int:
      """Exec Antigravity CLI (agy) with --agent sdd-worker --dangerously-skip-permissions --mode auto in cwd."""

  def launch_session(  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:642
      initial_prompt: str,
      *,
      cwd: Path,
      claude_args: Sequence[str] = (),
      base_env: Mapping[str, str] | None = None,
      host: Literal["claude", "google"] = "claude",
  ) -> int:
      """Open an interactive Claude or Antigravity (agy) session in cwd with initial_prompt."""
  ```

### Module 4: `GoogleCodingDispatchProfile` Model Alignment
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py`
- **Responsibility**: Align `GoogleCodingDispatchProfile.mode` (`Literal["accept-edits", "auto", "plan"]`) and `effort` (`Literal["low", "medium", "high", "xhigh", "max"]`) with `agy --help` and `parrot.flows.dev_loop.sdd_coder.models.SeatEffort`.
- **Depends on**: None
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py (modifies google_coding.py:44)
  class GoogleCodingDispatchProfile(BaseModel):  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py:44
      mode: Optional[Literal["accept-edits", "auto", "plan"]] = Field(default=None)
      effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(default="high")
  ```

### Module 5: SDD Sub-Agent Assets & `docs/sdd/AGY.md` Adaptation Contract
- **Path**: `docs/sdd/AGY.md`, `.agents/agents/sdd-coder/agent.md`, `.agents/agents/code-reviewer/agent.md`, `.agents/agents/qa-runner/agent.md`, `.agents/agents/sdd-worker/agent.md`, `.agents/agents/sdd-autopilot/agent.md`, `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` (and mirrored packaged assets under `packages/ai-parrot/src/parrot/sdd/_assets/`)
- **Responsibility**:
  1. Author `docs/sdd/AGY.md` specifying the **Antigravity Adaptation Contract** (tool mapping `Bash -> run_command`, `Agent -> invoke_subagent`, `TaskStop -> manage_subagents(Action="kill")`, `subagent_type: "fork" -> TypeName="self"|"research"`, model mapping `haiku -> flash`, `sonnet -> inherit`, non-persistent `cd "$WT" &&` per command, reactive background tasks, and Snap interpreter resolution).
  2. Add `.agents/agents/sdd-coder/agent.md`, `.agents/agents/code-reviewer/agent.md`, and `.agents/agents/qa-runner/agent.md` to the repository and `manifest.json` (`"hosts": ["google"]`).
  3. Synchronize `.agents/agents/sdd-worker/agent.md` with `.claude/agents/sdd-worker.md` (FEAT-549 `parrot-sdd-coder` orchestrator loop, FEAT-584, FEAT-698 brief lane) adapted for AGY primitives.
  4. Update `.agents/agents/sdd-autopilot/agent.md` to invoke `agy` instead of `claude`.
- **Depends on**: Modules 1, 2, 3
- **Interface Skeleton**:
  ```markdown
  <!-- docs/sdd/AGY.md (new) -->
  # SDD in Google Antigravity CLI (AGY)
  ## Antigravity Adaptation Contract
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_worktree_env_agy_payload_rewrite` | Module 1 | Verifies `hook_response` rewrites `run_command` `CommandLine` via `overwrite` and returns `decision: "allow"` on AGY payloads |
| `test_worktree_env_agy_payload_deny` | Module 1 | Verifies `hook_response` returns `decision: "deny"` when `uv sync` or out-of-worktree write is attempted in AGY format |
| `test_dangerous_actions_agy_allow_and_deny` | Module 1 | Verifies `dangerous_actions.py` returns `{"decision": "allow"}` for safe commands and `{"decision": "deny", "reason": ...}` for destructive commands on AGY payloads |
| `test_installer_google_hooks_json` | Module 2 | Verifies `parrot sdd install --host google` creates/updates `.agents/hooks.json` and `uninstall` removes managed entries |
| `test_launch_cli_google_host` | Module 3 | Verifies `parrot sdd launch worker|brief|fix --host google` dispatches `agy` with `--dangerously-skip-permissions --mode auto` |
| `test_google_coding_profile_auto_and_xhigh` | Module 4 | Verifies `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort="xhigh"` / `"max"` |
| `test_manifest_includes_all_google_agents` | Module 5 | Verifies `manifest.json` ships `sdd-coder`, `code-reviewer`, and `qa-runner` for host `google` and passes `parrot sdd status` |

### Integration Tests
| Test | Description |
|---|---|
| `test_sdd_install_google_roundtrip` | End-to-end `install_sdd_integration(root, hosts=("google",))` and `uninstall_sdd_integration` in a tmp git repo verifying `.agents/hooks.json`, `.agents/agents/`, and `.agents/skills/` |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/sdd/test_worktree_environment.py
- packages/ai-parrot/tests/unit/sdd/test_dangerous_actions.py
- packages/ai-parrot/tests/unit/sdd/test_installer.py
- packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def agy_bash_payload(tmp_path: Path) -> dict[str, Any]:
    return {
        "conversationId": "conv-123",
        "stepIdx": 1,
        "workspacePaths": [str(tmp_path)],
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "pytest packages/ai-parrot/tests/ -q"},
        },
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `worktree_environment.py --hook` and `dangerous_actions.py --hook` accept AGY `PreToolUse` payloads (`toolCall`) and return `{"decision": "allow" | "deny", ...}` without breaking existing Claude Code `PreToolUse` tests.
- [ ] `parrot sdd install --host google` writes `.agents/hooks.json` with `worktree-environment` and `dangerous-actions` guards matching `run_command|write_file|edit_file`.
- [ ] `parrot sdd launch worker|brief|fix --host google` launches `agy` with `--dangerously-skip-permissions` and `--mode auto`.
- [ ] `.agents/agents/` and `parrot/sdd/_assets/manifest.json` include `sdd-coder`, `code-reviewer`, and `qa-runner`, and `.agents/agents/sdd-worker/agent.md` includes the FEAT-549 `parrot-sdd-coder` orchestrator loop adapted for AGY (`invoke_subagent`, `manage_subagents`, model enum mapping).
- [ ] `docs/sdd/AGY.md` exists and documents the Antigravity Adaptation Contract (tool mapping, non-persistent `cd "$WT" &&` per command, `subagent_type: "fork"` -> `TypeName="self"|"research"`, and Snap environment resolution).
- [ ] `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort` values `"xhigh"` and `"max"`.
- [ ] All unit tests in the Validation Contract pass (`pytest`) and `ruff check` reports 0 errors.
- [ ] Documentation page declared in §10 exists under `wiki/` (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot.sdd.scripts.worktree_environment import hook_response, validate_write_path  # verified: packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:783
from parrot.sdd.scripts.dangerous_actions import Verdict, evaluate, find_root  # verified: packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:403
from parrot.sdd.installer import (  # verified: packages/ai-parrot/src/parrot/sdd/installer.py:160, 396, 523
    DANGEROUS_HOOK_LINE,
    GUARD_HOOK_LINE,
    PlannedAction,
    install_sdd_integration,
    plan_install,
    plan_uninstall,
    uninstall_sdd_integration,
)
from parrot.flows.dev_loop.feature_launcher import launch, launch_session  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:518, 642
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py:44
from parrot.flows.dev_loop.sdd_coder.models import SeatEffort  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:22
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:  # line 783
def main(argv: Sequence[str] | None = None) -> None:  # line 833

# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict:  # line 403
def _render(verdict: Verdict) -> dict[str, Any]:  # line 422
def main(argv: Sequence[str] | None = None) -> None:  # line 436

# packages/ai-parrot/src/parrot/sdd/installer.py
def dangerous_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:  # line 366
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:  # line 396
def _remove_dangerous_guard(root: Path, receipt: dict[str, Any]) -> list[str]:  # line 437
def plan_install(
    root: Path,
    hosts: Sequence[str],
    *,
    keep_edits: bool = False,
    hook: str = GUARD_HOOK_LINE,
    base_branch: str | None = None,
    dangerous_guard: bool = True,
    sdd_coder: bool = True,
) -> list[PlannedAction]:  # line 523

# packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py
class GoogleCodingDispatchProfile(BaseModel):  # line 44
    binary_path: str = Field(default="agy")  # line 53
    model: Optional[str] = Field(default=None)  # line 57
    mode: Optional[Literal["accept-edits", "plan"]] = Field(default=None)  # line 61
    effort: Literal["low", "medium", "high"] = Field(default="high")  # line 65
    skip_permissions: bool = Field(default=True)  # line 69
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `is_agy_payload` / AGY branch in `hook_response` | `worktree_environment.hook_response` | payload inspection | `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:783` |
| `_render_agy` / AGY branch in `evaluate` | `dangerous_actions.evaluate` & `main` | payload inspection | `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:403` |
| `_install_agy_hooks` / `_remove_agy_hooks` | `installer.install_sdd_integration` & `uninstall_sdd_integration` | `PlannedAction` execution | `packages/ai-parrot/src/parrot/sdd/installer.py:568, 745` |
| `launch_agy_worker` / `host` param | `launch_cli.worker`, `brief`, `fix` | Click `--host` option | `packages/ai-parrot/src/parrot/sdd/launch_cli.py:17, 64` |

### Does NOT Exist (Anti-Hallucination)
- ~~`Agent(subagent_type="fork")` in AGY~~ — AGY does not have a `"fork"` sub-agent type; use `invoke_subagent(TypeName="self" | "research", ...)`.
- ~~Frontmatter `hooks:` in `.agents/agents/*/agent.md`~~ — AGY does not support per-agent frontmatter hooks; hooks must live in `.agents/hooks.json` or `.agents/plugins/<plugin>/hooks.json`.
- ~~`Model="haiku"` or `Model="sonnet"` in AGY `invoke_subagent`~~ — AGY's `invoke_subagent` `Model` parameter only accepts `'inherit' | 'flash_lite' | 'flash' | 'pro'`.

### Edit Sites (Blueprint Anchors)
<!-- Verified against: 34a31c1199 -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:` | `worktree_environment.py:783` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `def evaluate(payload: dict[str, Any], *, root: Path \| None) -> Verdict:` | `dangerous_actions.py:403` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool \| None) -> list[str]:` | `installer.py:396` | 1 |
| `packages/ai-parrot/src/parrot/sdd/launch_cli.py` | MODIFY | `@launch.command("worker", context_settings={"ignore_unknown_options": True})` | `launch_cli.py:17` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `def launch_session(` | `feature_launcher.py:642` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py` | MODIFY | `class GoogleCodingDispatchProfile(BaseModel):` | `google_coding.py:44` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | MODIFY | `"target": ".agents/agents/sdd-worker/agent.md",` | `manifest.json:66` | 1 |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | `# SDD Worker — Autonomous Feature Implementation Agent` | `agent.md:9` | 1 |
| `.agents/agents/sdd-autopilot/agent.md` | MODIFY | `# SDD Autopilot — Autonomous Spec-to-PR Pipeline Orchestrator` | `agent.md:9` | 1 |
| `.agents/agents/sdd-coder/agent.md` | CREATE | — | — | — |
| `.agents/agents/code-reviewer/agent.md` | CREATE | — | — | — |
| `.agents/agents/qa-runner/agent.md` | CREATE | — | — | — |
| `docs/sdd/AGY.md` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/agy-compatibility.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Zero third-party imports in hook scripts**: `worktree_environment.py` and `dangerous_actions.py` must remain stdlib-only so they can run under `python -S` or any host interpreter without importing `parrot` (which triggers `navconfig` `.env` loading).
- **Keep packaged `_assets` in sync with repo-root assets**: Every change to `.agents/agents/*` or `docs/sdd/AGY.md` listed in `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` must be mirrored in `packages/ai-parrot/src/parrot/sdd/_assets/` so `classify_entry` and `test_installer.py` pass byte-identity checks.
- **Snap Confinement Awareness**: Document in `docs/sdd/AGY.md` how `antigravity-cli` Snap installations remap `HOME` to `$SNAP_USER_COMMON` (keeping the host home in `$SNAP_REAL_HOME`) and provide `$SNAP/usr/bin/python3` when `.venv/bin/python` symlinks to a host `/usr/bin/python3.x` absent inside the Snap mount namespace.

### Known Risks / Gotchas
- **AGY `PreToolUse` `overwrite` field**: In AGY's `hooks.json` specification, modified tool arguments are returned under `"overwrite": {"CommandLine": "..."}` alongside `"decision": "allow"`, NOT `"updatedInput"`.
- **Non-persistent `cd` in `run_command`**: Every multi-step shell snippet in `.agents/agents/sdd-worker/agent.md`, `.agents/agents/sdd-coder/agent.md`, and `docs/sdd/AGY.md` must explicitly prefix worktree commands with `cd "$WT" &&` or `git -C "$WT"`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| None | — | Uses stdlib, `click`, and `pydantic` already present in `ai-parrot` |

---

## Worktree Strategy

- **Isolation**: Single feature worktree (`feat-sdd-agy-compatibility`) with per-task sub-worktrees managed by `sdd-coder`.
- **Module dependency graph**:
  - `M2 (SDD Installer .agents/hooks.json)` → `M1 (Dual-Protocol Hook Scripts)` because `M2` wires the hook commands defined/verified in `M1`.
  - `M5 (SDD Sub-Agent Assets & docs/sdd/AGY.md)` → `M1`, `M2`, `M3` because the asset bundle and documentation codify the hooks and launcher flags from `M1`–`M3`.
  - `M1`, `M3`, and `M4` have no dependencies on each other and can run concurrently in Wave 1.
- **Shared files**: `packages/ai-parrot/src/parrot/sdd/installer.py` (touched only by M2) and `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` (touched only by M5).
- **Exclusive resources**: None.
- **Cross-feature dependencies**: None.

---

## Consequences

decision audit not configured in this repository

---

## 8. Open Questions

- [x] Should `dangerous_actions.py` return `{"decision": "allow"}` on safe commands when invoked by AGY? — *Resolved*: Yes, because in AGY `{"decision": "allow"}` from a `PreToolUse` hook bypasses the per-command interactive confirmation prompt for safe commands while still denying destructive commands.
- [x] How should `coder_prepare_native` model names (`haiku`, `sonnet`) map to AGY's `invoke_subagent` `Model` enum? — *Resolved*: Map `haiku` -> `flash` and `sonnet` -> `inherit` (or `pro` for escalation).

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (no prior exploration doc; direct architectural review session)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/agy-compatibility.md` — create: Architecture and operator guide for running SDD workflows and sub-agents in Google Antigravity CLI (`agy`), including `.agents/hooks.json`, `docs/sdd/AGY.md`, and Snap confinement troubleshooting.
- **API modules**:
  - `parrot.sdd.scripts.worktree_environment`
  - `parrot.sdd.scripts.dangerous_actions`
  - `parrot.sdd.installer`
  - `parrot.sdd.launch_cli`
  - `parrot.flows.dev_loop.feature_launcher`
  - `parrot.flows.dev_loop.models.google_coding`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-08 | Jesus Lara | Initial specification for SDD Antigravity CLI (AGY) operational compatibility |
