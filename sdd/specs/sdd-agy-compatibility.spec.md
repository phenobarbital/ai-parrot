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
   - `parrot sdd launch worker|brief|fix` (`parrot/sdd/launch_cli.py`, `parrot/flows/dev_loop/feature_launcher.py`) hardcodes `claude --setting-sources project,local` and has no `--host google` (`agy`) support (`--dangerously-skip-permissions`, `--mode`, `--sandbox`).
   - AGY's `PreToolUse` hook contract (`.agents/hooks.json`) uses camelCase envelope keys and PascalCase tool arguments: `{"toolCall": {"name": "run_command", "args": {"CommandLine": "...", "WaitMsBeforeAsync": 5000, "toolSummary": "..."}}, "workspacePaths": [...], "stepIdx": 2, ...}`; a file write arrives as `{"name": "write_file", "args": {"Path": "<abs>", "Content": "...", "Overwrite": true}}`. The payload has no `cwd` field, and AGY runs the hook process with its working directory set to the directory holding `hooks.json`. The hook must print `{"decision": "allow" | "deny" | "ask" | "force_ask" | "deny_unless_prior_grant", "reason": "...", "overwrite": {...}}` on stdout (`decision` is required; `overwrite` is a shallow top-level merge into the tool arguments). Currently, `worktree_environment.py` and `dangerous_actions.py` only parse Claude Code's `{"tool_name": "Bash", "tool_input": {"command": "..."}}` format and emit `{"hookSpecificOutput": ...}` (on an AGY payload, `dangerous_actions.py --hook` prints `{}` today, with no `decision`), and `parrot/sdd/installer.py` only registers hooks in `.claude/settings.json` when `"claude" in hosts`.
   - **A hook `allow` is not an approval in headless mode (verified 2026-11-08, agy 1.4.12).** In print mode (`agy -p`), a `PreToolUse` hook that returned `{"decision": "allow"}` (and also `allow` plus `permissionOverrides`) did not approve `write_file` or a `run_command` outside `permissions.allow`: AGY's `tool_confirmation_manager` still requested confirmation and soft-denied it ("a tool required the "command" permission that headless mode cannot prompt for"). Unattended runs therefore need `--dangerously-skip-permissions` or settings allow-rules; hooks can only add `deny`/`overwrite` on top.
   - `--mode auto` is account-gated: on this account `agy` prints `--mode auto is not available for this account; continuing in the default mode.` and silently runs in the default mode.
2. **Sub-Agent Harness Mismatches (`sdd-worker`, `sdd-coder`, `sdd-research`, etc.)**:
   - `.agents/agents/` and `parrot/sdd/_assets/manifest.json` are missing `sdd-coder`, `code-reviewer`, and `qa-runner`.
   - `.agents/agents/sdd-worker/agent.md` (415 lines) is out of sync with `.claude/agents/sdd-worker.md` (827 lines): it lacks the FEAT-549 `parrot-sdd-coder` MCP orchestrator loop (`coder_init_run`, `coder_next_wave`, `coder_prepare_native`, `coder_record_native`, `coder_run_wave`, `coder_finalize_task`), FEAT-584 optimizations, and the FEAT-698 brief lane.
   - `.agents/agents/sdd-autopilot/agent.md` hardcodes `claude --agent ...` and `claude -p ...` shell calls instead of `agy`.
   - AGY's sub-agent tool is `invoke_subagent(TypeName, Role, Prompt, Model, Workspace)` and `manage_subagents(Action="list|kill|kill_all")`, not Claude's `Agent(...)` / `TaskStop`. Furthermore, AGY lacks a `"fork"` sub-agent type (used in `/sdd-proposal` §4.0 and `/sdd-spec` §3b; it maps to `TypeName="self"`) and restricts `Model` to the enum `'inherit' | 'flash_lite' | 'flash' | 'pro'` (the binary rejects anything else with `unsupported model: %q, must be one of 'inherit', 'flash', 'pro', 'flash_lite'`), while a native seat's model is a free string (default `"haiku"`; operators may configure `"sonnet"`, `"opus"` or a full model id).
3. **Non-Persistent Working Directory (`cd`) in `run_command` & Missing Adaptation Contract**:
   - In AGY, each `run_command` executes in a fresh bash session where `cd` and environment variables do not persist across calls. SDD skills that run `WT=$(parrot sdd worktree ensure ...); cd "$WT"` in one step and then run bare commands in subsequent steps execute on the main checkout instead of the worktree.
   - `.agents/skills/sdd-*/SKILL.md` is shared by `"hosts": ["codex", "google"]` in `manifest.json`, yet its header only references `docs/sdd/CODEX.md` (`$sdd-*` syntax) with no `docs/sdd/AGY.md` adaptation contract.
4. **Snap Confinement & Dispatcher Profile Gaps**:
   - On Linux when `antigravity-cli` is installed as a Snap (`SNAP=/snap/antigravity-cli/...`, strict confinement, base `core26`), `$HOME` is remapped to `$SNAP_USER_COMMON` (`$SNAP_REAL_HOME` holds the host home) and `.venv/bin/python -> /usr/bin/python3.12` breaks inside the Snap mount namespace, where Python is `$SNAP/usr/bin/python3` (Python 3.14). Verified inside the snap on 2026-11-08: `bwrap` is absent, user namespaces are denied (`unshare` is refused), the `parrot` CLI is not on `PATH`, `ssh` exec is denied and `~/.gitconfig` is invisible. The existing Bubblewrap sandbox and the existing `parrot sdd …` hook commands therefore cannot run under a snap-installed `agy`, while `python3 -S <stdlib-only script>` can.
   - `GoogleCodingDispatchProfile` (`parrot/flows/dev_loop/models/google_coding.py`) restricts `mode` to `Literal["accept-edits", "plan"]` (missing `"auto"`) and `effort` to `Literal["low", "medium", "high"]` (missing `"xhigh"` and `"max"` supported by `agy` and `SeatEffort`).

### Goals
- Support dual-protocol (`claude` and `agy`) `PreToolUse` payloads and responses in `worktree_environment.py` and `dangerous_actions.py`. In AGY the hooks are a **guard**: they always emit a `decision`, deny unsafe calls and rewrite commands via `overwrite`. They emit `allow` for calls that pass, but nothing relies on that `allow` to remove confirmation prompts.
- Extend `parrot sdd install --host google` (`parrot/sdd/installer.py`) to install and manage `.agents/hooks.json` plus stdlib-only hook scripts vendored under `.agents/hooks/`, wiring the `worktree-environment` and `dangerous-actions` guards with snap-safe `python3 -S hooks/<script>.py --hook` commands.
- Extend `parrot sdd launch worker|brief|fix` (`parrot/sdd/launch_cli.py`, `parrot/flows/dev_loop/feature_launcher.py`) with `--host (claude|google)` support. Approval depends on the mode: the unattended `worker` launches `agy` with `--dangerously-skip-permissions`, with the hooks as its guard. The interactive `brief`/`fix` sessions (`launch_session`) launch without it, so the operator approves each tool call and the hooks still deny. Neither passes `--mode auto` by default.
- Add missing sub-agents (`sdd-coder`, `code-reviewer`, `qa-runner`) to `.agents/agents/` and `manifest.json`, synchronize `.agents/agents/sdd-worker/agent.md` with FEAT-549/FEAT-584/FEAT-698 using AGY sub-agent primitives (`invoke_subagent`, `manage_subagents`, model mapping `haiku -> flash`, every other value -> `inherit`), and update `.agents/agents/sdd-autopilot/agent.md`.
- Create `docs/sdd/AGY.md` (the Antigravity Adaptation Contract covering tool mapping, explicit absolute worktree paths or same-command `WT` assignment, reactive background tasks, and Snap interpreter resolution) and reference it in `.agents/skills/sdd-*/SKILL.md`.
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
1. **Dual-Protocol PreToolUse Hooks**: `worktree_environment.py` and `dangerous_actions.py` inspect the incoming JSON payload on `stdin`. When `"toolCall"` is present (AGY protocol), they normalize `(tool_name, tool_input, cwd)` from `toolCall.name`, `toolCall.args`, and a single validated checkout in `workspacePaths` (deny missing or ambiguous context), run the deterministic guards/wrappers plus AGY-specific file-write containment checks, and serialize the response in AGY format (`{"decision": "allow" | "deny", "reason": ..., "overwrite": {"CommandLine": ...}}`). Every AGY invocation prints a `decision`, including on malformed input and guard exceptions (`deny`).
2. **Installer & `.agents/hooks.json` Wiring**: `parrot/sdd/installer.py` registers `.agents/hooks.json` when `"google"` is among the target hosts, wiring both `dangerous-actions` and `worktree-environment` under `matcher: "run_command|write_file|edit_file"`. Each one runs as `python3 -S hooks/<script>.py --hook` against a stdlib-only copy vendored under `.agents/hooks/`. Because AGY runs hooks with cwd = `.agents/`, the relative command works in every worktree and inside the snap, and `hooks.json` holds no machine-specific paths and is committed.
3. **Host-Aware SDD CLI Launcher**: `parrot sdd launch worker|brief|fix` accepts `--host (claude|google)` (or `PARROT_SDD_HOST=google`). The unattended worker builds `agy --agent sdd-worker --dangerously-skip-permissions -p "run <FEAT-ID>"`. The interactive `brief`/`fix` sessions build `agy` with the initial prompt and without `--dangerously-skip-permissions`. Sandbox selection is fail-closed: Bubblewrap for a non-snap `agy`, or the explicit opt-in `--sandbox snap` backend for a snap-installed `agy`.
4. **Sub-Agent Assets & `docs/sdd/AGY.md` Contract**: All 12 SDD agents are shipped under `.agents/agents/<name>/agent.md` in `manifest.json`, with `sdd-worker` updated to the FEAT-549 `parrot-sdd-coder` orchestrator loop and `docs/sdd/AGY.md` defining the canonical tool/model/CWD adaptations for `.agents/skills/sdd-*/SKILL.md`.

### Component Diagram
```
parrot sdd install --host google ──→ .agents/hooks.json ──→ python3 -S hooks/{worktree_environment,dangerous_actions}.py --hook (AGY protocol)
                                 ├─→ .agents/hooks/*.py (vendored stdlib-only copies of parrot/sdd/scripts/*)
                                 ├─→ .agents/agents/*/agent.md (12 agents incl. sdd-coder, code-reviewer, qa-runner)
                                 └─→ .agents/skills/sdd-*/SKILL.md ──→ docs/sdd/AGY.md

parrot sdd launch worker --host google ──→ feature_launcher.launch(host="google") ──→ agy --agent sdd-worker --dangerously-skip-permissions -p …
parrot sdd launch brief|fix --host google ──→ feature_launcher.launch_session(host="google") ──→ agy (interactive, operator approves)
                    sandbox: bubblewrap (non-snap agy) | snap (explicit opt-in, snap agy) | otherwise refuse
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.scripts.worktree_environment` | extends | Adds AGY `toolCall` input parsing and `decision`/`overwrite` output rendering in `hook_response` |
| `parrot.sdd.scripts.dangerous_actions` | extends | Adds AGY `toolCall` evaluation in `evaluate` and `{"decision": "allow" \| "deny"}` rendering in `_render` |
| `parrot.sdd.installer` | extends | Installs/removes `.agents/hooks.json` and the vendored `.agents/hooks/*.py` scripts for host `google` alongside `.claude/settings.json` for `claude` |
| `parrot.sdd.launch_cli` / `feature_launcher` | extends | Adds `--host` (`claude` \| `google`) option to `worker`, `brief`, and `fix` subcommands, and a `snap` value for `--sandbox` (Google only) |
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
| M2: SDD Installer `.agents/hooks.json` Support | yes | Exact `.agents/hooks.json` entries, vendored `.agents/hooks/*.py` assets, and `plan_install`/`plan_uninstall` actions fixed | — |
| M3: Host-Aware SDD CLI Launcher (`--host google`) | yes | Exact CLI flags (`--host`) and `agy` command builder signatures fixed | — |
| M4: `GoogleCodingDispatchProfile` Model Alignment | yes | Exact `Literal` unions for `mode` and `effort` fixed | — |
| M5: SDD Sub-Agent Assets & `docs/sdd/AGY.md` Contract | yes | Asset paths in `manifest.json`, agent frontmatter, and adaptation rules fixed | — |

### Module 1: Dual-Protocol Hook Scripts (`worktree_environment.py` & `dangerous_actions.py`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`, `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py`
- **Responsibility**: Detect AGY `PreToolUse` payloads (`"toolCall"` key with `name` in `{"run_command", "write_file", "edit_file"}` and `args` containing `CommandLine` or `Path`), apply the existing worktree sandbox/PYTHONPATH rewrite and dangerous-actions rules, and emit AGY-compliant JSON (`{"decision": "allow" | "deny", "reason": ..., "overwrite": {"CommandLine": ...}}`).
- **AGY hook contract details (verified against agy 1.4.12 on 2026-11-08)**:
  - The working directory comes from the single validated `workspacePaths` entry. The payload has no `cwd`, and the hook process's own cwd is `.agents/`, which must never be used as the checkout.
  - `run_command` args carry extra keys (`WaitMsBeforeAsync`, `toolSummary`). `overwrite` is a shallow merge, so a rewrite sends only `{"CommandLine": ...}` and leaves the other keys untouched.
  - `write_file` args are `Path` (absolute), `Content`, `Overwrite`. The `edit_file` argument shape was not observed. If an `edit_file` (or any matched file tool) has no target path the guard can identify, deny it.
  - Every AGY invocation prints exactly one JSON object with a `decision`. Today `dangerous_actions.py --hook` prints `{}` for an AGY payload; that is a defect this module removes. `allow` is emitted for passing calls but is not an approval in headless mode (see §1), so no AGY code path or document may present it as one.
  - Both scripts must run as `python3 -S <script> --hook` from the vendored `.agents/hooks/` copy (M2), on Python 3.12–3.14, without importing `parrot`. The existing lazy `parrot.sdd.config` imports already fall back on `ImportError`. From `.agents/hooks/`, the `test_scope` kernel (`_KERNEL_PARENT`) is unreachable, so the existing fail-open path of the test-scope check applies (it is a cost guard, not a safety guard). Neither the `native_claude_sandbox` import nor any other import may raise out of the AGY path.
- **Depends on**: Existing `worktree_environment` and `dangerous_actions` logic
- **AGY file-write boundary**: Existing `validate_write_path()` only protects shared Python environments; it does not enforce checkout containment. Add an AGY-specific containment check without changing Claude behavior. Resolve relative file paths against the validated active checkout and canonicalize paths, including existing symlink ancestors of new files. Deny targets outside that checkout and writes into shared environments reached through checkout-local aliases. Direct file tools have no external write exceptions: Git administration, shared ledger, and coder evidence writes must use guarded commands with their existing explicit sandbox exceptions. Reject missing or ambiguous workspace context rather than silently selecting the first workspace. Malformed AGY events and guard exceptions must produce AGY-format denials.
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
- **Responsibility**: When `"google"` is included in `hosts` during `parrot sdd install` (and `dangerous_guard=True`), vendor the two stdlib-only hook scripts into `.agents/hooks/`, register/update `.agents/hooks.json` with the `dangerous-actions` and `worktree-environment` `PreToolUse` hooks matching `run_command|write_file|edit_file`, and clean both up on `parrot sdd uninstall --host google`.
- **Vendored hook scripts**: `.agents/hooks/dangerous_actions.py` and `.agents/hooks/worktree_environment.py` are byte-identical copies of `parrot/sdd/scripts/dangerous_actions.py` and `parrot/sdd/scripts/worktree_environment.py`. They are registered in `manifest.json` (`"hosts": ["google"]`) and mirrored under `_assets/`, so `classify_entry` drift detection and the byte-identity tests cover them. The bare/baked `portable` choice used for Claude hooks does not apply: `parrot sdd …` and `.venv/bin/parrot` cannot run inside a snap-installed `agy`, and the relative command needs no machine path. `.agents/hooks.json` and `.agents/hooks/` are committed, so every worktree created from `origin/<base_branch>` carries the guard.
- **Exact `.agents/hooks.json` entries** (merged next to foreign named hooks, never replacing them):
  ```json
  {
    "parrot-sdd-dangerous-actions": {
      "PreToolUse": [{"matcher": "run_command|write_file|edit_file",
                      "hooks": [{"type": "command", "command": "python3 -S hooks/dangerous_actions.py --hook", "timeout": 10}]}]
    },
    "parrot-sdd-worktree-environment": {
      "PreToolUse": [{"matcher": "run_command|write_file|edit_file",
                      "hooks": [{"type": "command", "command": "python3 -S hooks/worktree_environment.py --hook", "timeout": 10}]}]
    }
  }
  ```
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/installer.py (modifies installer.py:396, 523, 709)
  AGY_HOOKS_PATH: Path = Path(".agents/hooks.json")
  AGY_HOOK_SCRIPTS_DIR: Path = Path(".agents/hooks")
  _AGY_DANGEROUS_MATCHER: str = "run_command|write_file|edit_file"

  def _install_agy_hooks(root: Path, receipt: dict[str, Any]) -> list[str]:
      """Merge the two SDD named hooks into <root>/.agents/hooks.json (foreign named hooks untouched)."""

  def _remove_agy_hooks(root: Path, receipt: dict[str, Any]) -> list[str]:
      """Remove SDD-managed PreToolUse guard entries from <root>/.agents/hooks.json."""
  ```

### Module 3: Host-Aware SDD CLI Launcher (`--host google`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`, `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`
- **Responsibility**: Add `--host` (`click.Choice(["claude", "google"])`, defaulting to `os.environ.get("PARROT_SDD_HOST", "claude")`) to `parrot sdd launch worker|brief|fix` and implement `launch_agy_worker` / `launch_session(..., host=...)` in `feature_launcher.py`. The unattended worker launches in tmux or foreground with `--agent sdd-worker --dangerously-skip-permissions`; the interactive `brief`/`fix` sessions launch without that flag.
- **Launcher integration contract**:
  - Add `host: Literal["claude", "google"] = "claude"` to `feature_launcher.launch()`. Propagate the selected host through foreground dispatch, tmux child arguments, and `main()` dispatch; default omitted host to Claude for compatibility. The tmux child must not unconditionally invoke `native_claude_sandbox.launch_worker()`.
  - **Approval depends on the mode.** Only the unattended Google worker (`launch()` → `launch_agy_worker`) passes `--dangerously-skip-permissions`; there, the AGY hooks are the only per-call guard (`deny`/`overwrite`). Google `launch_session()` (`brief`, `fix`) must not pass it: the operator approves tool calls and the hooks still deny. Do not pass `--mode auto` by default. It is account-gated, and an unsupported account only gets a warning before running in the default mode. `GoogleCodingDispatchProfile.mode` (M4) remains the opt-in for dispatcher seats.
  - Google launches must not run Claude-specific native sandbox preflight or inherit `claude-native` backend markers. The sandbox backend is selected fail-closed:
    - **`bubblewrap`** (default; `required`/`legacy`/`preferred`): for a non-snap `agy`, use the existing Bubblewrap command sandbox with `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`. Missing Bubblewrap, unsupported platforms and failed capability probes fail before AGY starts. When `agy` resolves to a snap (`/snap/bin/agy` or a `snap run` wrapper), Bubblewrap cannot run inside the snap, so refuse with an error that names `--sandbox snap`.
    - **`snap`** (new, explicit opt-in, Google only): accepted only when `agy` resolves to a strictly confined snap. Set `PARROT_SDD_SANDBOX_BACKEND=snap`. The AGY hooks then apply their command-level guards without the Bubblewrap wrapper. Print a warning before starting AGY: strict confinement hides top-level dotfiles in `$HOME` (`~/.ssh`, `~/.gitconfig`) and denies `ssh`, but it does **not** make the shared `.venv` or the primary checkout read-only, so only the hooks guard those against `run_command`. `--sandbox snap` with `--host claude`, or with a non-snap `agy`, is a usage error.
    - Reject `--sandbox off` for every Google launch. Never silently launch unsandboxed. In the hook, an AGY event under `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` with no reachable `bwrap` is denied, not run unwrapped.
  - Reject explicit Google `--sandbox-allow-domain` options and nonempty configured domain restrictions with a clear unsupported-policy error: neither the Bubblewrap wrapper nor the snap (`network` plug) enforces network isolation. Do not silently accept a Claude network policy.
  - Under the `snap` backend, forward the operator's Git identity into the AGY environment (`GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`/`GIT_COMMITTER_NAME`/`GIT_COMMITTER_EMAIL` read from the host `git config` before launch), because the snap cannot read `~/.gitconfig` and worker commits would otherwise carry a host-derived identity.
  - Before any Google worker, brief, or fix launch, verify that the managed AGY hooks are installed in the launch checkout (`.agents/hooks.json` entries plus the vendored `.agents/hooks/*.py`) and runnable by the interpreter AGY will use. For a snap `agy` that is the snap's `python3`. Apply the same backend selection to Google `launch_session()`. Preserve operator `base_env` capture before application imports and existing Git push protection; do not forward launcher-only options as AGY arguments.
  - Define and test CLI option placement for `brief` and `fix`, which currently use passthrough parsing: `--host` must be consumed before source/prompt arguments, while remaining skill arguments retain their existing meaning.
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
      """Exec Antigravity CLI (agy) with --agent sdd-worker --dangerously-skip-permissions in cwd (no --mode auto by default)."""

  def launch_session(  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:642
      initial_prompt: str,
      *,
      cwd: Path,
      claude_args: Sequence[str] = (),
      base_env: Mapping[str, str] | None = None,
      host: Literal["claude", "google"] = "claude",
  ) -> int:
      """Open an interactive Claude or Antigravity (agy) session in cwd with initial_prompt (agy: never --dangerously-skip-permissions)."""
  ```

### Module 4: `GoogleCodingDispatchProfile` Model Alignment
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py`
- **Responsibility**: Align `GoogleCodingDispatchProfile.mode` (`Literal["accept-edits", "auto", "plan"]`) and `effort` (`Literal["low", "medium", "high", "xhigh", "max"]`) with `agy --help` (1.4.12: `--mode (accept-edits, auto, plan)`, `--effort (low|medium|high|xhigh|max)`) and `parrot.flows.dev_loop.sdd_coder.models.SeatEffort`. The default stays `mode=None`. `"auto"` is a valid opt-in, but AGY only warns and falls back to the default mode on accounts without it, so nothing may assume `"auto"` took effect.
- **Depends on**: None
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py (modifies google_coding.py:44)
  class GoogleCodingDispatchProfile(BaseModel):  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py:44
      mode: Optional[Literal["accept-edits", "auto", "plan"]] = Field(default=None)
      effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(default="high")
  ```

### Module 5: SDD Sub-Agent Assets & `docs/sdd/AGY.md` Adaptation Contract
- **Path**: `.agents/skills/sdd-*/SKILL.md`, `docs/sdd/AGY.md`, `.agents/agents/sdd-coder/agent.md`, `.agents/agents/code-reviewer/agent.md`, `.agents/agents/qa-runner/agent.md`, `.agents/agents/sdd-worker/agent.md`, `.agents/agents/sdd-autopilot/agent.md`, `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` (and mirrored packaged assets under `packages/ai-parrot/src/parrot/sdd/_assets/`)
- **Responsibility**:
  1. Author `docs/sdd/AGY.md` specifying the **Antigravity Adaptation Contract**:
     - tool mapping `Bash -> run_command`, `Agent -> invoke_subagent`, `TaskStop -> manage_subagents(Action="kill")`;
     - `subagent_type: "fork" -> TypeName="self"`, and only `"self"`. `"research"` is not an AGY built-in type, and the project's `sdd-research` agent (FEAT-129) creates Jira tickets, specs and worktrees, so it must never stand in for a fork;
     - model mapping `haiku -> flash`; every other native seat model (`sonnet`, `opus`, full model ids, unknown strings) `-> inherit`; never select `pro` or `flash_lite` automatically, which matches AGY's own `invoke_subagent` guidance to use `inherit` unless the user explicitly asks for a tier;
     - explicit absolute worktree paths or same-command `WT` assignment, and reactive background tasks;
     - approval semantics: a hook `allow` is not an approval in headless mode; the worker relies on `--dangerously-skip-permissions` plus the hook guard, and interactive sessions rely on operator approval; `--mode auto` is account-gated;
     - Snap facts: interpreter resolution (`$SNAP/usr/bin/python3`, Python 3.14), no `bwrap`, denied user namespaces, `ssh` denied (HTTPS git only), `~/.gitconfig` invisible, and the `--sandbox snap` opt-in with what it does not protect.
  2. Add `.agents/agents/sdd-coder/agent.md`, `.agents/agents/code-reviewer/agent.md`, and `.agents/agents/qa-runner/agent.md` to the repository and `manifest.json` (`"hosts": ["google"]`). The vendored `.agents/hooks/*.py` manifest entries belong to M2.
  3. Synchronize `.agents/agents/sdd-worker/agent.md` with `.claude/agents/sdd-worker.md` (FEAT-549 `parrot-sdd-coder` orchestrator loop, FEAT-584, FEAT-698 brief lane) adapted for AGY primitives.
  4. Update `.agents/agents/sdd-autopilot/agent.md` to invoke `agy` instead of `claude`.
  5. Update every shared `.agents/skills/sdd-*/SKILL.md` header to select `docs/sdd/AGY.md` on Google and retain `docs/sdd/CODEX.md` on Codex. Mirror all changed skill assets and register/package `docs/sdd/AGY.md` for Google installations.
  6. Every AGY worktree command must contain the resolved absolute checkout path, or assign `WT` to that path within the same invocation before `cd "$WT" && ...` / `git -C "$WT" ...`. Never rely on a previous invocation's variable assignment, export, activation, or working directory. Use the resolved worktree path as the subagent `Workspace` as well.
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
| `test_dangerous_actions_agy_allow_and_deny` | Module 1 | Verifies `dangerous_actions.py` returns `{"decision": "allow"}` for safe commands and `{"decision": "deny", "reason": ...}` for destructive commands on AGY payloads, and never prints an object without `decision` |
| `test_agy_hooks_run_standalone` | Module 1 | Copies both scripts into a tmp `.agents/hooks/`, runs `python3 -S hooks/<script>.py --hook` with cwd = `.agents/` and an environment where `parrot` is not importable (cleared `PYTHONPATH`), and asserts AGY-format decisions for `run_command`, `write_file` (`Path`/`Content`/`Overwrite`) and an `edit_file` with no identifiable target (denied) |
| `test_installer_google_hooks_json` | Module 2 | Verifies `parrot sdd install --host google` writes the exact named-hook entries and the vendored `.agents/hooks/*.py` (byte-identical to `parrot/sdd/scripts/`), preserves foreign named hooks, and `uninstall` removes only the managed entries and scripts |
| `test_launch_cli_google_host` | Module 3 | Verifies `parrot sdd launch worker --host google` dispatches `agy` with `--dangerously-skip-permissions`, `brief`/`fix --host google` dispatch it without that flag, and neither passes `--mode auto` by default |
| `test_google_coding_profile_auto_and_xhigh` | Module 4 | Verifies `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort="xhigh"` / `"max"` |
| `test_manifest_includes_all_google_agents` | Module 5 | Verifies `manifest.json` ships `sdd-coder`, `code-reviewer`, and `qa-runner` for host `google` and passes `parrot sdd status` |

### Integration Tests
| Test | Description |
|---|---|
| `test_sdd_install_google_roundtrip` | End-to-end `install_sdd_integration(root, hosts=("google",))` and `uninstall_sdd_integration` in a tmp git repo verifying `.agents/hooks.json`, `.agents/agents/`, and `.agents/skills/` |

### Required Regression Cases
- In `test_worktree_environment.py`, cover allowed checkout-local writes, relative traversal, absolute external paths, symlink escapes (including new files below symlinked parents), shared-environment aliases, and missing/multiple workspace roots. Exercise the hook subprocess error path and assert AGY-format denial, not Claude output.
- In `test_sdd_launch.py`, cover Google foreground and tmux child host propagation, environment-selected host, unchanged default Claude dispatch, and `brief`/`fix` option placement. Verify Google skips Claude preflight, selects Bubblewrap for a non-snap `agy`, and refuses missing hooks, failed sandbox probes, `--sandbox off`, and unsupported explicit/configured network restrictions before executing AGY. For a snap `agy` (resolution mocked to `/snap/bin/agy`): the default backend refuses and names `--sandbox snap`; `--sandbox snap` sets `PARROT_SDD_SANDBOX_BACKEND=snap`, prints the not-protected warning and forwards the host Git identity; `--sandbox snap` with a non-snap `agy` or `--host claude` is a usage error.
- In `test_installer.py`, verify Google installations include the AGY contract and updated skill headers, Codex headers retain their adaptation contract, and packaged skill copies match repository assets. Validate representative worktree command examples in two fresh shell processes, with the second receiving no `WT` or activation state from the first.

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- packages/ai-parrot/tests/sdd/test_dangerous_actions.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
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

- [ ] `worktree_environment.py --hook` and `dangerous_actions.py --hook` accept AGY `PreToolUse` payloads (`toolCall`) and always return one object with `decision` (`"allow"` | `"deny"`, plus `overwrite` for rewrites), without breaking existing Claude Code `PreToolUse` tests.
- [ ] `parrot sdd install --host google` writes the exact `.agents/hooks.json` named-hook entries (`python3 -S hooks/<script>.py --hook`, matcher `run_command|write_file|edit_file`) and the vendored, byte-identical `.agents/hooks/*.py`, and both scripts run standalone under `python3 -S` without `parrot` importable.
- [ ] `parrot sdd launch worker --host google` launches `agy` with `--dangerously-skip-permissions`; `brief`/`fix --host google` launch it without that flag; neither passes `--mode auto` by default.
- [ ] `.agents/agents/` and `parrot/sdd/_assets/manifest.json` include `sdd-coder`, `code-reviewer`, and `qa-runner`, and `.agents/agents/sdd-worker/agent.md` includes the FEAT-549 `parrot-sdd-coder` orchestrator loop adapted for AGY (`invoke_subagent`, `manage_subagents`, model mapping `haiku -> flash`, everything else `-> inherit`).
- [ ] `docs/sdd/AGY.md` exists and documents the Antigravity Adaptation Contract (tool mapping, explicit absolute worktree paths or same-command `WT` assignment, `subagent_type: "fork"` -> `TypeName="self"` only, model mapping, approval semantics, and Snap environment facts including the `--sandbox snap` limits).
- [ ] `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort` values `"xhigh"` and `"max"`.
- [ ] All unit tests in the Validation Contract pass (`pytest`) and `ruff check` reports 0 errors.
- [ ] AGY direct file writes are limited to the validated active checkout, reject traversal/symlink/shared-environment escapes, and deny malformed or ambiguous workspace input in AGY format; existing Claude behavior is unchanged.
- [ ] Google foreground, tmux, brief, and fix paths propagate the selected host and apply the documented fail-closed sandbox policy (Bubblewrap for a non-snap `agy`, explicit `--sandbox snap` for a snap `agy`, refusal otherwise). Unsupported sandbox/network settings and missing hook prerequisites fail before AGY starts.
- [ ] Before the worker path ships, the §8 open question (do `PreToolUse` hooks run and deny under `--dangerously-skip-permissions`?) is answered by the documented probe, and the result is recorded in `docs/sdd/AGY.md`. If hooks do not run under that flag, the unattended Google worker must refuse to launch.
- [ ] Shared SDD skill headers select the correct host contract, installed Google assets include `docs/sdd/AGY.md`, and all AGY worktree examples work across fresh shell invocations without inherited `WT`, activation, or CWD state.
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
- ~~`Agent(subagent_type="fork")` in AGY~~ — AGY does not have a `"fork"` sub-agent type; use `invoke_subagent(TypeName="self", ...)`.
- ~~Frontmatter `hooks:` in `.agents/agents/*/agent.md`~~ — AGY does not support per-agent frontmatter hooks; hooks must live in `.agents/hooks.json` or `.agents/plugins/<plugin>/hooks.json`.
- ~~`Model="haiku"` or `Model="sonnet"` in AGY `invoke_subagent`~~ — AGY's `invoke_subagent` `Model` parameter only accepts `'inherit' | 'flash_lite' | 'flash' | 'pro'`.
- ~~`invoke_subagent(TypeName="research")` as a built-in~~ — no built-in `research` type exists in agy 1.4.12; `sdd-research` is a side-effecting project agent, not a fork substitute.
- ~~A `cwd` field in the AGY `PreToolUse` payload~~ — the envelope carries `workspacePaths`; the hook process cwd is the directory holding `hooks.json`.
- ~~Hook `{"decision": "allow"}` as an approval in headless mode~~ — verified not to bypass `tool_confirmation_manager` in `agy -p`.
- ~~`bwrap`, user namespaces, `parrot`, or the `.venv` interpreter inside the `antigravity-cli` snap~~ — all absent or denied under strict confinement.

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
| `.agents/skills/sdd-*/SKILL.md` and mirrored packaged skills | MODIFY | Host-specific adaptation-contract headers | M5: inspect each header before editing | multiple |
| `.agents/hooks.json` | CREATE | — | — | — |
| `.agents/hooks/dangerous_actions.py` | CREATE | byte-identical copy of `parrot/sdd/scripts/dangerous_actions.py` (+ `_assets` mirror) | — | — |
| `.agents/hooks/worktree_environment.py` | CREATE | byte-identical copy of `parrot/sdd/scripts/worktree_environment.py` (+ `_assets` mirror) | — | — |
| `docs/sdd/AGY.md` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/agy-compatibility.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Zero third-party imports in hook scripts**: `worktree_environment.py` and `dangerous_actions.py` must remain stdlib-only so they can run under `python -S` or any host interpreter without importing `parrot` (which triggers `navconfig` `.env` loading).
- **Keep packaged `_assets` in sync with repo-root assets**: Every change to `.agents/agents/*`, `.agents/hooks/*` or `docs/sdd/AGY.md` listed in `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` must be mirrored in `packages/ai-parrot/src/parrot/sdd/_assets/` so `classify_entry` and `test_installer.py` pass byte-identity checks. Each hook script then exists three times (`parrot/sdd/scripts/`, `.agents/hooks/`, `_assets/`). Any later edit to `parrot/sdd/scripts/{dangerous_actions,worktree_environment}.py` must re-sync the two copies, and a byte-identity test must enforce it.
- **Snap Confinement Awareness**: Document in `docs/sdd/AGY.md` how `antigravity-cli` Snap installations remap `HOME` to `$SNAP_USER_COMMON` (keeping the host home in `$SNAP_REAL_HOME`) and provide `$SNAP/usr/bin/python3` (Python 3.14 on `core26`) when `.venv/bin/python` symlinks to a host `/usr/bin/python3.x` absent inside the Snap mount namespace.

### Known Risks / Gotchas
- **AGY `PreToolUse` `overwrite` field**: In AGY's `hooks.json` specification, modified tool arguments are returned under `"overwrite": {"CommandLine": "..."}` alongside `"decision": "allow"`, NOT `"updatedInput"`.
- **Hook `allow` ≠ approval**: In `agy -p`, the hook decision runs, but `tool_confirmation_manager` still soft-denies any tool that lacks a permission (verified for `write_file` and `run_command`, including with `permissionOverrides`). Never document a hook `allow` as the way to make AGY unattended.
- **Snap Git identity and transport**: inside the snap, `~/.gitconfig` is invisible (commits get a host-derived author unless `GIT_AUTHOR_*`/`GIT_COMMITTER_*` are forwarded) and `ssh` exec is denied, so `git@github.com:` remotes fail and only HTTPS git works. The worker never pushes, but any AGY-run step that does (`parrot sdd ids reserve`) fails under the snap.
- **Automating AGY from Claude Code**: Claude Code's auto-mode classifier refuses to run `agy --dangerously-skip-permissions` ("Create Unsafe Agents"). Probes or orchestration that launch the unattended AGY worker from a Claude session need an explicit operator permission rule or must be run by the operator.
- **Non-persistent `cd` in `run_command`**: Every multi-step shell snippet in `.agents/agents/sdd-worker/agent.md`, `.agents/agents/sdd-coder/agent.md`, and `docs/sdd/AGY.md` must use an explicit resolved absolute worktree path or assign `WT` in that same command before `cd "$WT" &&` or `git -C "$WT"`. A prefix referencing a variable from a previous shell is invalid. Apply this rule to the shared SDD skills and their packaged copies too.

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
- **Shared files**: `packages/ai-parrot/src/parrot/sdd/installer.py` (touched only by M2) and `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` (touched by M2 for the vendored `.agents/hooks/*` entries and by M5 for agents/skills/`AGY.md`; M5 depends on M2, so the edits are sequential).
- **Exclusive resources**: None.
- **Cross-feature dependencies**: None.

---

## Consequences

decision audit not configured in this repository

---

## 8. Open Questions

> Evidence for the 2026-11-08 resolutions: agy 1.4.12 (`antigravity-cli` snap rev 24, base `core26`). Sources: the hooks documentation embedded in the binary; `agy --help`; `agy agents`; `snap run --shell antigravity-cli` probes; and three `agy -p --effort low` runs in a throwaway workspace whose logging hook captured the real `PreToolUse` payloads (`agy` CLI log: `Monitor agy_tool_safety …`, `Print mode: soft-denying tool confirmation "WriteFile"/"RunCommand"`).

- [x] Should `dangerous_actions.py` return `{"decision": "allow"}` on safe commands when invoked by AGY? — *Resolved (revised 2026-11-08)*: It emits `allow` for passing calls, because `decision` is required and `allow` is the correct verdict. The original rationale was wrong for headless mode: a hook `allow` (alone or with `permissionOverrides`) did **not** bypass AGY's confirmation for `write_file` or `run_command` in `agy -p`. Approval therefore depends on the mode. The unattended `worker` uses `--dangerously-skip-permissions` with the hooks as its deny/overwrite guard; the interactive `brief`/`fix` sessions run without that flag, so the operator approves and the hooks still deny (M3).
- [x] How should native seat model names map to AGY's `invoke_subagent` `Model` enum? — *Resolved*: `haiku` -> `flash`; every other value (`sonnet`, `opus`, full model ids, unknown strings) -> `inherit`. `pro` and `flash_lite` are never selected automatically, which follows AGY's guidance to use `inherit` unless the user explicitly requests a tier. The earlier "(or `pro` for escalation)" clause is dropped.
- [x] What does `subagent_type: "fork"` map to? — *Resolved*: `TypeName="self"` only. `"research"` is not a built-in AGY type, and the project's `sdd-research` agent has side effects (Jira, specs, worktrees).
- [x] Which sandbox applies to a snap-installed `agy`, given there is no `bwrap` and user namespaces are denied? — *Resolved*: The default stays fail-closed. A snap `agy` is accepted only through the explicit `--sandbox snap` backend, which treats strict confinement as the sandbox, warns what it leaves unprotected (shared `.venv`, primary checkout), and forwards the host Git identity (M3).
- [x] How are AGY hooks invoked when `parrot`/`.venv` cannot run inside the snap? — *Resolved*: The installer vendors byte-identical stdlib-only copies into `.agents/hooks/`, and the committed `.agents/hooks.json` runs `python3 -S hooks/<script>.py --hook` (relative to `.agents/`, the hook cwd), which works in every worktree and inside the snap (M2).
- [x] Does `launch` pass `--mode auto`? — *Resolved*: Not by default. It is account-gated, and on this account AGY prints `--mode auto is not available for this account` and runs in the default mode. `GoogleCodingDispatchProfile.mode="auto"` stays a valid opt-in (M4).
- [ ] **Do `PreToolUse` hooks still run, and can they deny, under `--dangerously-skip-permissions`?** — *Open, blocking for the unattended Google worker.* The worker's only per-call guard depends on it. It was not probed in the 2026-11-08 session because Claude Code's auto-mode classifier refused to launch `agy --dangerously-skip-permissions`. The operator runs this probe: in a throwaway workspace with an `.agents/hooks.json` whose `PreToolUse` hook (matcher `""`) logs stdin and denies any `run_command` starting with `ls`, run `agy -p "run the shell command: ls -1, then report whether it was blocked" --dangerously-skip-permissions --effort low`. If the hook logged the call and `ls` was blocked, the design holds. Otherwise the Google worker must refuse to launch until an alternative is specified (see §5).

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
| 0.3 | 2026-11-08 | Claude (decisions: Jesus Lara) | Resolve open questions against agy 1.4.12 probes: hook `allow` is not a headless approval (mode-dependent approval), `fork -> self` only, `haiku -> flash` / rest `-> inherit`, opt-in `--sandbox snap` backend, vendored `.agents/hooks/*.py` run via `python3 -S`, no default `--mode auto`; verified payload shape (`write_file` `Path`/`Content`/`Overwrite`, no `cwd`); one open blocking question (hooks under `--dangerously-skip-permissions`) |
| 0.2 | 2026-11-08 | Codex | Apply specification review: explicit AGY write containment, launcher host/sandbox propagation, self-contained worktree commands and shared skill scope, corrected validation targets and regression coverage |
| 0.1 | 2026-11-08 | Jesus Lara | Initial specification for SDD Antigravity CLI (AGY) operational compatibility |
