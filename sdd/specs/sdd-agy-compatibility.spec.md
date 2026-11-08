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
    - parrot.sdd.scripts.agy_permissions
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
   - AGY's `PreToolUse` hook contract (`.agents/hooks.json`) uses camelCase envelope keys and PascalCase tool arguments: `{"toolCall": {"name": "run_command", "args": {"CommandLine": "...", "WaitMsBeforeAsync": 5000, "toolSummary": "..."}}, "workspacePaths": [...], "stepIdx": 2, ...}`; a file write arrives as `{"name": "write_file", "args": {"Path": "<abs>", "Content": "...", "Overwrite": true}}`. The payload has no `cwd` field, and AGY runs the hook process with its working directory set to the directory holding `hooks.json`. The hook must print `{"decision": "allow" | "deny" | "ask" | "force_ask" | "deny_unless_prior_grant", "reason": "...", "overwrite": {...}}` on stdout (`decision` is required; `overwrite` is a shallow top-level merge into the tool arguments). AGY passes its own environment to the hook process.
   - **Brief `agy-permission-hook` (PR #2040, open against `dev`, head `4cbc11df09`) already provides the AGY permission layer.** It adds a policy module `parrot.sdd.scripts.agy_permissions` that reuses `dangerous_actions.evaluate` and answers `deny` / `force_ask` / `ask`, never `allow`. It also adds the verb `parrot sdd hooks agy-permissions --hook`; a tracked `.agents/hooks.json` with one named hook `parrot-sdd-permissions` (matcher `run_command`) served by `sh ../scripts/sdd/agy_hook.sh`, which answers `force_ask` whenever the policy cannot run; and installer support that merges a managed `permissions.allow` list into the user's agy settings for the google host. That layer does not cover file tools, the worktree environment guard (PYTHONPATH/shared-environment rules), the launcher, the sub-agent assets, or the unattended worker.
   - **Verified hook semantics (agy 1.4.12 and 1.5.3, 2026-11-08):**

     | Hook answer | Default mode, headless (`agy -p`) | `--dangerously-skip-permissions` |
     |---|---|---|
     | `allow` (± `permissionOverrides`) | ignored; the call runs only if a `permissions.allow` rule matches, otherwise soft-denied | runs |
     | `ask` | neutral; rules decide | runs |
     | `force_ask` | prompts (soft-denied headless) even when a rule matches | **runs** |
     | `deny` | blocked: `tool call denied by pre-tool hook: <reason>`; the agent continues | blocked the same way |

     `overwrite` rewrites the executed `CommandLine` with both `allow` and `ask`, and permission rules are evaluated against the **rewritten** command (a rewrite to a command no rule covers is soft-denied). Under `--dangerously-skip-permissions`, therefore, only `deny` stops a call.
   - `--mode auto` is account-gated: on this account `agy` prints `--mode auto is not available for this account; continuing in the default mode.` and silently runs in the default mode.
2. **Sub-Agent Harness Mismatches (`sdd-worker`, `sdd-coder`, `sdd-research`, etc.)**:
   - `.agents/agents/` and `parrot/sdd/_assets/manifest.json` are missing `sdd-coder`, `code-reviewer`, and `qa-runner`.
   - `.agents/agents/sdd-worker/agent.md` (415 lines) is out of sync with `.claude/agents/sdd-worker.md` (827 lines): it lacks the FEAT-549 `parrot-sdd-coder` MCP orchestrator loop (`coder_init_run`, `coder_next_wave`, `coder_prepare_native`, `coder_record_native`, `coder_run_wave`, `coder_finalize_task`), FEAT-584 optimizations, and the FEAT-698 brief lane.
   - `.agents/agents/sdd-autopilot/agent.md` hardcodes `claude --agent ...` and `claude -p ...` shell calls instead of `agy`.
   - AGY's sub-agent tool is `invoke_subagent(TypeName, Role, Prompt, Model, Workspace)` and `manage_subagents(Action="list|kill|kill_all")`, not Claude's `Agent(...)` / `TaskStop`. Furthermore, AGY lacks a `"fork"` sub-agent type (used in `/sdd-proposal` §4.0 and `/sdd-spec` §3b; it maps to `TypeName="self"`) and restricts `Model` to the enum `'inherit' | 'flash_lite' | 'flash' | 'pro'` (the binary rejects anything else with `unsupported model: %q, must be one of 'inherit', 'flash', 'pro', 'flash_lite'`), while a native seat's model is a free string (default `"haiku"`; operators may configure `"sonnet"`, `"opus"` or a full model id).
3. **Non-Persistent Working Directory (`cd`) in `run_command` & Missing Adaptation Contract**:
   - In AGY, each `run_command` executes in a fresh bash session where `cd` and environment variables do not persist across calls. SDD skills that run `WT=$(parrot sdd worktree ensure ...); cd "$WT"` in one step and then run bare commands in subsequent steps execute on the main checkout instead of the worktree.
   - `.agents/skills/sdd-*/SKILL.md` is shared by `"hosts": ["codex", "google"]` in `manifest.json`, yet its header only references `docs/sdd/CODEX.md` (`$sdd-*` syntax) with no `docs/sdd/AGY.md` adaptation contract.
4. **Unsupported Snap Build & Dispatcher Profile Gaps**:
   - The `antigravity-cli` snap is a community wrapper ("This is not an official Google product"), and it lagged behind (1.4.12, while the official build is 1.5.3). The official Linux install is `curl -fsSL https://antigravity.google/cli/install.sh | bash`: it installs `~/.local/bin/agy` without sudo, verifies a checksum, and self-updates in the background. Under the snap's strict confinement (base `core26`), the SDD flow cannot run at all, verified 2026-11-08:
     - `.venv/bin/python -> /usr/bin/python3.12` is absent (the snap ships Python 3.14), so `parrot` and `wikitoolkit` fail with `bad interpreter`;
     - `bwrap` is missing and user namespaces are denied;
     - `ssh` exec is denied, and `~/.gitconfig` is invisible.

     The official build runs as the user, with all of these available.
   - `GoogleCodingDispatchProfile` (`parrot/flows/dev_loop/models/google_coding.py`) restricts `mode` to `Literal["accept-edits", "plan"]` (missing `"auto"`) and `effort` to `Literal["low", "medium", "high"]` (missing `"xhigh"` and `"max"` supported by `agy` and `SeatEffort`).

### Goals
- Build on PR #2040's AGY permission layer (a cross-feature dependency). Extend its single `parrot-sdd-permissions` hook with:
  - the worktree environment guard (`worktree_environment.py`: shared-environment denials, the PYTHONPATH rewrite via `overwrite`);
  - checkout containment for the file tools `write_file` and `edit_file`;
  - an **unattended mode**, in which every `force_ask` becomes `deny`, because `force_ask` does not stop a call under `--dangerously-skip-permissions`.
- Extend the installer registration from PR #2040 so the managed hook matches `run_command|write_file|edit_file`.
- Extend `parrot sdd launch worker|brief|fix` (`parrot/sdd/launch_cli.py`, `parrot/flows/dev_loop/feature_launcher.py`) with `--host (claude|google)` support. Approval depends on the mode:
  - The unattended `worker` launches `agy` with `--dangerously-skip-permissions` and `PARROT_SDD_AGY_UNATTENDED=1`, inside Bubblewrap; there, the hook's `deny` is the guard.
  - The interactive `brief`/`fix` sessions (`launch_session`) launch without that flag. PR #2040's allow-rules approve routine commands, the operator approves the rest, and the hook still denies.

  Neither passes `--mode auto` by default, and both refuse a snap-installed `agy`.
- Add missing sub-agents (`sdd-coder`, `code-reviewer`, `qa-runner`) to `.agents/agents/` and `manifest.json`, synchronize `.agents/agents/sdd-worker/agent.md` with FEAT-549/FEAT-584/FEAT-698 using AGY sub-agent primitives (`invoke_subagent`, `manage_subagents`, model mapping `haiku -> flash`, every other value -> `inherit`), and update `.agents/agents/sdd-autopilot/agent.md`.
- Create `docs/sdd/AGY.md` (the Antigravity Adaptation Contract covering tool mapping, explicit absolute worktree paths or same-command `WT` assignment, reactive background tasks, the verified hook/approval semantics, and the official non-snap install) and reference it in `.agents/skills/sdd-*/SKILL.md`.
- Align `GoogleCodingDispatchProfile` (`mode` and `effort` literals) with `agy` CLI capabilities and `SeatEffort`.

### Non-Goals (explicitly out of scope)
- Modifying Claude Code's existing `.claude/settings.json` hook format or behavior.
- Replacing the `codex` external reviewer seat in `/sdd-spec` §3b or `code-reviewer.md` (which remains explicitly bound to `codex` when configured in `sdd/config.json`).
- Re-implementing what PR #2040 delivers: the command policy, the `hooks agy-permissions` verb, the `agy_hook.sh` launcher, and the managed allow-rules.
- Supporting the community `antigravity-cli` snap.

---

## Governing Decisions

decision audit not configured in this repository

---

## 2. Architectural Design

### Overview
The compatibility layer bridges SDD's host-agnostic Python runtime and asset bundle with Antigravity CLI (`agy`) across four boundaries:
1. **AGY Hook Policy Extensions (on PR #2040)**: `agy_permissions.evaluate` remains the single entry point of the `parrot-sdd-permissions` hook. FEAT-847 extends it in three ways:
   - it adds an AGY verdict from `worktree_environment` (shared-environment denials, the PYTHONPATH rewrite returned as `overwrite`, checkout containment for `write_file`/`edit_file`), resolved against the single validated `workspacePaths` entry;
   - in unattended mode (`PARROT_SDD_AGY_UNATTENDED=1`) it maps every `force_ask` to `deny` and wraps commands in Bubblewrap;
   - it carries `overwrite` in its `Decision`.

   `deny` always wins. One hook process keeps the combination deterministic; how AGY merges decisions and `overwrite`s from several named hooks on the same event is unverified.
2. **Installer Wiring**: PR #2040's registration (`_agy_hook_entry`, `_install_agy_permissions`) widens the managed matcher from `run_command` to `run_command|write_file|edit_file` and migrates existing receipt-owned entries; the tracked `.agents/hooks.json` changes the same way.
3. **Host-Aware SDD CLI Launcher**: `parrot sdd launch worker|brief|fix` accepts `--host (claude|google)` (or `PARROT_SDD_HOST=google`).
   - The unattended worker builds `agy --agent sdd-worker --dangerously-skip-permissions -p "run <FEAT-ID>"`, with `PARROT_SDD_AGY_UNATTENDED=1` and `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`, and fails closed without Bubblewrap.
   - The interactive `brief`/`fix` sessions build `agy` with the initial prompt and without `--dangerously-skip-permissions`.
   - Both refuse an `agy` that resolves to the snap and print the official install command.
4. **Sub-Agent Assets & `docs/sdd/AGY.md` Contract**: All 12 SDD agents are shipped under `.agents/agents/<name>/agent.md` in `manifest.json`, with `sdd-worker` updated to the FEAT-549 `parrot-sdd-coder` orchestrator loop and `docs/sdd/AGY.md` defining the canonical tool/model/CWD adaptations for `.agents/skills/sdd-*/SKILL.md`.

### Component Diagram
```
.agents/hooks.json  "parrot-sdd-permissions"  matcher run_command|write_file|edit_file      (PR #2040, matcher widened here)
    └─→ sh ../scripts/sdd/agy_hook.sh ──→ agy_permissions.evaluate (PR #2040)
              ├─→ dangerous_actions.evaluate           (PR #2040: deny rules)
              ├─→ command policy → ask | force_ask     (PR #2040)
              └─→ worktree_environment AGY verdict     (FEAT-847: env guard, PYTHONPATH overwrite, file containment, bwrap wrap)
          unattended (PARROT_SDD_AGY_UNATTENDED=1): force_ask → deny, incl. agy_hook.sh "unavailable" fallback

parrot sdd install --host google ──→ hook + allow-rules (PR #2040) ├─→ .agents/agents/*/agent.md (12 agents)  └─→ .agents/skills/sdd-*/SKILL.md ──→ docs/sdd/AGY.md

parrot sdd launch worker --host google ──→ launch(host="google") ──→ agy --agent sdd-worker --dangerously-skip-permissions -p …  (bubblewrap, unattended)
parrot sdd launch brief|fix --host google ──→ launch_session(host="google") ──→ agy (interactive: rules + operator approve, hook denies)
agy resolving to /snap/… ──→ refuse, print the official install.sh command
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.scripts.worktree_environment` | extends | Adds `agy_verdict()`: the AGY-shaped environment guard (shared-environment denials, PYTHONPATH rewrite, file containment, Bubblewrap wrap in unattended mode); Claude `hook_response` unchanged |
| `parrot.sdd.scripts.agy_permissions` (PR #2040) | extends | `evaluate` merges `agy_verdict()`, handles `write_file`/`edit_file`, applies unattended `force_ask → deny`; `Decision`/`_render` gain `overwrite` |
| `scripts/sdd/agy_hook.sh` (PR #2040) | modifies | The "unavailable" fallback answers `deny` instead of `force_ask` when `PARROT_SDD_AGY_UNATTENDED=1` |
| `parrot.sdd.installer` (PR #2040 functions) | extends | `_agy_hook_entry` matcher `run_command` → `run_command\|write_file\|edit_file`; reinstall migrates receipt-owned entries |
| `parrot.sdd.launch_cli` / `feature_launcher` | extends | Adds `--host` (`claude` \| `google`) option to `worker`, `brief`, and `fix` subcommands; Google worker exports the unattended/sandbox env; snap `agy` refused |
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
def agy_verdict(
    payload: dict[str, Any], *, root: Path, backend: str, unattended: bool
) -> tuple[Literal["deny", "ask"], str, dict[str, str] | None]:
    """Return (decision, reason, overwrite) for one AGY PreToolUse payload against checkout ``root``."""
    ...

# parrot/sdd/scripts/agy_permissions.py (PR #2040) — Decision gains an optional overwrite
@dataclass(frozen=True)
class Decision:
    decision: Literal["deny", "force_ask", "ask"]
    reason: str = ""
    overwrite: dict[str, str] | None = None

UNATTENDED_ENV: str = "PARROT_SDD_AGY_UNATTENDED"
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: AGY Hook Policy Extensions | yes | Exact AGY `toolCall` schema (`run_command`, `write_file`, `edit_file`), `agy_verdict` signature, merge rule (deny wins), unattended `force_ask → deny`, `overwrite` rendering fixed | — |
| M2: Installer Matcher Extension | yes | Exact matcher string and receipt-owned migration fixed | — |
| M3: Host-Aware SDD CLI Launcher (`--host google`) | yes | Exact CLI flags (`--host`) and `agy` command builder signatures fixed | — |
| M4: `GoogleCodingDispatchProfile` Model Alignment | yes | Exact `Literal` unions for `mode` and `effort` fixed | — |
| M5: SDD Sub-Agent Assets & `docs/sdd/AGY.md` Contract | yes | Asset paths in `manifest.json`, agent frontmatter, and adaptation rules fixed | — |

### Module 1: AGY Hook Policy Extensions (`agy_permissions.py` from PR #2040 + `worktree_environment.py`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py` (PR #2040), `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`, `scripts/sdd/agy_hook.sh` (PR #2040)
- **Responsibility**:
  - Add `worktree_environment.agy_verdict()`. For `run_command` it applies the existing shared-environment denials (e.g. `uv sync`, writes into the shared `.venv`) and the PYTHONPATH rewrite, returned as `overwrite={"CommandLine": ...}`. For `write_file`/`edit_file` it applies the checkout-containment boundary below.
  - Make `agy_permissions.evaluate` merge that verdict with its own policy: `deny` beats `force_ask`, which beats `ask`; the `overwrite` is carried when the result is not `deny`.
  - Add the unattended mode.
  - Claude's `hook_response` and its stdlib-only contract stay unchanged.
- **Unattended mode** (`PARROT_SDD_AGY_UNATTENDED=1`, exported only by the Google worker launcher, M3). Under `--dangerously-skip-permissions`, `force_ask` and `ask` run and only `deny` stops a call (verified on 1.5.3), so in this mode:
  - every `force_ask` becomes `deny`, with the original reason prefixed `unattended:`. That covers PR #2040's risky-variant answers, parse failures, and the `scripts/sdd/agy_hook.sh` "unavailable" fallback; the script must read the variable itself and answer `deny` instead of `force_ask`;
  - with `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`, the command is wrapped in the existing Bubblewrap wrapper through `overwrite`, and a payload with no reachable `bwrap` is denied, never run unwrapped.

  Without the variable (interactive sessions, or `agy` started by hand), there is no Bubblewrap wrapping: permission rules evaluate the rewritten command, so a `bwrap … --` prefix would defeat PR #2040's allow-rules. A PYTHONPATH prefix is safe, since PR #2040 verified that rules ignore leading `VAR=` assignments. `docs/sdd/AGY.md` must state that only `parrot sdd launch worker --host google` is a supported unattended mode; running `agy --dangerously-skip-permissions` by hand lets `force_ask` calls through.
- **AGY hook contract details (verified against agy 1.4.12 and 1.5.3, 2026-11-08)**:
  - The working directory comes from the single validated `workspacePaths` entry. The payload has no `cwd`, and the hook process's own cwd is `.agents/`, which must never be used as the checkout.
  - `run_command` args carry extra keys (`WaitMsBeforeAsync`, `toolSummary`). `overwrite` is a shallow merge, so a rewrite sends only `{"CommandLine": ...}`.
  - `write_file` args are `Path` (absolute), `Content`, `Overwrite`. The `edit_file` argument shape was not observed. If an `edit_file` (or any matched file tool) has no target path the guard can identify, deny it.
  - `agy_permissions` never answers `allow` (PR #2040). In interactive mode, `allow` is ignored like `ask`; in unattended mode, `ask` already runs. Every invocation prints exactly one JSON object with a `decision`, and malformed payloads and guard exceptions produce `force_ask` (interactive) or `deny` (unattended).
- **Depends on**: PR #2040 merged into `dev`; existing `worktree_environment` logic
- **AGY file-write boundary**: Existing `validate_write_path()` only protects shared Python environments; it does not enforce checkout containment. Add an AGY-specific containment check without changing Claude behavior. Resolve relative file paths against the validated active checkout and canonicalize paths, including existing symlink ancestors of new files. Deny targets outside that checkout and writes into shared environments reached through checkout-local aliases. Direct file tools have no external write exceptions: Git administration, shared ledger, and coder evidence writes must use guarded commands with their existing explicit sandbox exceptions. Reject missing or ambiguous workspace context rather than silently selecting the first workspace. Malformed AGY events and guard exceptions must produce an AGY-format answer (`force_ask`, or `deny` in unattended mode).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py (adds next to hook_response, worktree_environment.py:783)
  def agy_verdict(
      payload: dict[str, Any], *, root: Path, backend: str, unattended: bool
  ) -> tuple[Literal["deny", "ask"], str, dict[str, str] | None]:
      """Return (decision, reason, overwrite) for one AGY PreToolUse payload against checkout ``root``."""

  # packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py (PR #2040; modifies Decision, evaluate, _render)
  UNATTENDED_ENV: str = "PARROT_SDD_AGY_UNATTENDED"

  @dataclass(frozen=True)
  class Decision:
      decision: Literal["deny", "force_ask", "ask"]
      reason: str = ""
      overwrite: dict[str, str] | None = None

  def evaluate(payload: dict[str, Any], *, root: Path | None) -> Decision:  # PR #2040 @4cbc11df09 agy_permissions.py:1358
      """Policy + dangerous-actions + agy_verdict; deny > force_ask > ask; unattended maps force_ask to deny."""

  def _render(decision: Decision) -> dict[str, Any]:  # PR #2040 @4cbc11df09 agy_permissions.py:1414 (return type widens for overwrite)
      """Render {'decision', 'reason'?, 'overwrite'?} for agy."""
  ```

### Module 2: Installer Matcher Extension (on PR #2040's registration)
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py` (PR #2040 functions), `.agents/hooks.json` (tracked, PR #2040)
- **Responsibility**: Widen the managed `parrot-sdd-permissions` matcher from `run_command` to `run_command|write_file|edit_file` in `_agy_hook_entry` and in the tracked `.agents/hooks.json`. Re-running `parrot sdd install --host google` must migrate an existing receipt-owned `run_command`-only entry in place. Foreign named hooks and user-edited matchers stay untouched (they are reported, not overwritten). `parrot sdd status` reports a stale matcher. PR #2040 otherwise keeps its hook command forms (tracked `sh ../scripts/sdd/agy_hook.sh` in ai-parrot, bare or baked `parrot sdd hooks agy-permissions --hook` elsewhere), its allow-rules and its `--no-agy-permissions` flag. FEAT-847 adds no vendored scripts and no second named hook.
- **Exact managed entry after this module**:
  ```json
  {"parrot-sdd-permissions": {"PreToolUse": [{"matcher": "run_command|write_file|edit_file",
                                              "hooks": [{"type": "command", "command": "<PR #2040 command form>", "timeout": 10}]}]}}
  ```
  The tracked ai-parrot file keeps its `"command": "sh ../scripts/sdd/agy_hook.sh"` and `"timeout": 20`; only the matcher changes.
- **Depends on**: Module 1, PR #2040
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/installer.py (PR #2040 @4cbc11df09 installer.py:585)
  _AGY_MATCHER: str = "run_command|write_file|edit_file"

  def _agy_hook_entry(command: str) -> dict[str, Any]:
      """Managed PreToolUse entry for the agy permission hook (matcher _AGY_MATCHER)."""
  ```

### Module 3: Host-Aware SDD CLI Launcher (`--host google`)
- **Path**: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`, `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`
- **Responsibility**: Add `--host` (`click.Choice(["claude", "google"])`, defaulting to `os.environ.get("PARROT_SDD_HOST", "claude")`) to `parrot sdd launch worker|brief|fix` and implement `launch_agy_worker` / `launch_session(..., host=...)` in `feature_launcher.py`. The unattended worker launches in tmux or foreground with `--agent sdd-worker --dangerously-skip-permissions`; the interactive `brief`/`fix` sessions launch without that flag.
- **Launcher integration contract**:
  - Add `host: Literal["claude", "google"] = "claude"` to `feature_launcher.launch()`. Propagate the selected host through foreground dispatch, tmux child arguments, and `main()` dispatch; default omitted host to Claude for compatibility. The tmux child must not unconditionally invoke `native_claude_sandbox.launch_worker()`.
  - **Approval depends on the mode.** Only the unattended Google worker (`launch()` → `launch_agy_worker`) passes `--dangerously-skip-permissions`. It also exports `PARROT_SDD_AGY_UNATTENDED=1`, so the hook's `deny` (including mapped `force_ask`, M1) is the per-call guard. Google `launch_session()` (`brief`, `fix`) must pass neither: PR #2040's allow-rules approve routine commands, the operator approves the rest, and the hook still denies. Do not pass `--mode auto` by default. It is account-gated, and an unsupported account only gets a warning before running in the default mode. `GoogleCodingDispatchProfile.mode` (M4) remains the opt-in for dispatcher seats.
  - **Snap refusal.** If the `agy` to be executed resolves (after `shutil.which` and symlink resolution) into `/snap/` or is the `snap run` wrapper, every Google launch fails before starting AGY. The error explains that the community snap cannot run the SDD flow and prints `curl -fsSL https://antigravity.google/cli/install.sh | bash`. There is no snap backend.
  - **Worker sandbox (fail-closed).** Google launches must not run Claude-specific native sandbox preflight or inherit `claude-native` backend markers. The Google worker uses the existing Bubblewrap command sandbox with `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`: the hook wraps each command through `overwrite` in unattended mode (M1). Default, `required`, `legacy` and `preferred` all select it, and `preferred` still fails closed when it is unavailable. Missing Bubblewrap, unsupported platforms and failed capability probes fail before AGY starts. Reject `--sandbox off` for the Google worker. Google `launch_session()` does not wrap commands in Bubblewrap: wrapping would defeat the rule matching of the interactive allow-rules, and an operator approves there.
  - Reject explicit Google `--sandbox-allow-domain` options and nonempty configured domain restrictions with a clear unsupported-policy error: the Bubblewrap wrapper does not enforce network isolation. Do not silently accept a Claude network policy.
  - **Hook prerequisite.** Before any Google worker, brief, or fix launch, verify that the managed `parrot-sdd-permissions` entry exists in the launch checkout's `.agents/hooks.json` with the M2 matcher, and that its command is runnable: `scripts/sdd/agy_hook.sh` exists, or the bare/baked `parrot` is resolvable. A missing or stale hook fails the launch with the `parrot sdd install --host google` hint. Preserve operator `base_env` capture before application imports and existing Git push protection; do not forward launcher-only options as AGY arguments.
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
      """Exec agy --agent sdd-worker --dangerously-skip-permissions in cwd with PARROT_SDD_AGY_UNATTENDED=1 and the bubblewrap backend (no --mode auto by default)."""

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
- **Responsibility**: Align `GoogleCodingDispatchProfile.mode` (`Literal["accept-edits", "auto", "plan"]`) and `effort` (`Literal["low", "medium", "high", "xhigh", "max"]`) with `agy --help` (1.4.12 and 1.5.3: `--mode (accept-edits, auto, plan)`, `--effort (low|medium|high|xhigh|max)`) and `parrot.flows.dev_loop.sdd_coder.models.SeatEffort`. The default stays `mode=None`. `"auto"` is a valid opt-in, but AGY only warns and falls back to the default mode on accounts without it, so nothing may assume `"auto"` took effect.
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
     - approval semantics: the verified hook-answer table from §1; `overwrite` behaviour and rule matching on the rewritten command; the worker's unattended mode (`force_ask → deny`, Bubblewrap); interactive sessions using PR #2040's rules plus operator approval; that only `parrot sdd launch worker --host google` is a supported unattended mode; and that `--mode auto` is account-gated;
     - installation: the official `curl -fsSL https://antigravity.google/cli/install.sh | bash` (`~/.local/bin/agy`, self-updating), and why the community snap is unsupported. Hook facts were verified on 1.4.12 and 1.5.3; re-run the probes in `docs/sdd/AGY.md` after an update that touches hooks or permissions.
  2. Add `.agents/agents/sdd-coder/agent.md`, `.agents/agents/code-reviewer/agent.md`, and `.agents/agents/qa-runner/agent.md` to the repository and `manifest.json` (`"hosts": ["google"]`).
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
| `test_worktree_env_agy_verdict_rewrite` | Module 1 | `agy_verdict` returns `("ask", …, {"CommandLine": <PYTHONPATH-prefixed>})` for a worktree `pytest` and denies `uv sync` / shared-`.venv` writes |
| `test_worktree_env_agy_verdict_bwrap` | Module 1 | With `unattended=True, backend="bubblewrap"` the `overwrite` wraps the command in the Bubblewrap wrapper; with no reachable `bwrap` it denies; with `unattended=False` it never wraps |
| `test_agy_permissions_merge_and_overwrite` | Module 1 | `evaluate` merges policy + `dangerous_actions` + `agy_verdict` (deny > force_ask > ask) and `_render` emits `overwrite` only for non-deny results |
| `test_agy_permissions_unattended_force_ask_is_deny` | Module 1 | With `PARROT_SDD_AGY_UNATTENDED=1`, risky variants, parse failures and malformed payloads answer `deny` (reason prefixed `unattended:`); without it they stay `force_ask` |
| `test_agy_permissions_file_tools` | Module 1 | `write_file` (`Path`/`Content`/`Overwrite`) inside the checkout → `ask`; outside / traversal / symlink escape / shared env → `deny`; `edit_file` with no identifiable target → `deny` |
| `test_agy_hook_sh_unattended_fallback` | Module 1 | `sh scripts/sdd/agy_hook.sh` with a missing policy module answers `force_ask`, and `deny` when `PARROT_SDD_AGY_UNATTENDED=1` |
| `test_installer_agy_matcher_widened` | Module 2 | `parrot sdd install --host google` writes matcher `run_command\|write_file\|edit_file`, migrates a receipt-owned `run_command`-only entry, leaves foreign named hooks and user-edited matchers untouched, and `status` reports a stale matcher |
| `test_launch_cli_google_host` | Module 3 | `parrot sdd launch worker --host google` dispatches `agy` with `--dangerously-skip-permissions`, `PARROT_SDD_AGY_UNATTENDED=1` and the bubblewrap backend; `brief`/`fix --host google` dispatch it with none of them; neither passes `--mode auto` by default |
| `test_google_coding_profile_auto_and_xhigh` | Module 4 | Verifies `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort="xhigh"` / `"max"` |
| `test_manifest_includes_all_google_agents` | Module 5 | Verifies `manifest.json` ships `sdd-coder`, `code-reviewer`, and `qa-runner` for host `google` and passes `parrot sdd status` |

### Integration Tests
| Test | Description |
|---|---|
| `test_sdd_install_google_roundtrip` | End-to-end `install_sdd_integration(root, hosts=("google",))` and `uninstall_sdd_integration` in a tmp git repo verifying `.agents/hooks.json` (widened matcher), `.agents/agents/`, and `.agents/skills/` |

### Required Regression Cases
- In `test_worktree_environment.py`, cover allowed checkout-local writes, relative traversal, absolute external paths, symlink escapes (including new files below symlinked parents), shared-environment aliases, and missing/multiple workspace roots for `agy_verdict`. Assert that Claude `hook_response` output is unchanged.
- In `test_agy_permissions.py`, exercise the hook `main` error path and assert one AGY-format object (`force_ask`, or `deny` in unattended mode), never Claude output or `{}`.
- In `test_sdd_launch.py`, cover Google foreground and tmux child host propagation, environment-selected host, unchanged default Claude dispatch, and `brief`/`fix` option placement. Verify that the Google worker skips Claude preflight, exports the unattended and bubblewrap environment, and refuses missing or stale hooks, failed sandbox probes, `--sandbox off`, and unsupported explicit/configured network restrictions before executing AGY. Verify that Google `launch_session()` exports neither variable. With `agy` resolution mocked to `/snap/bin/agy` (or a symlink into `/snap/`), every Google launch refuses and prints the official install command.
- In `test_installer.py`, verify Google installations include the AGY contract and updated skill headers, Codex headers retain their adaptation contract, and packaged skill copies match repository assets. Validate representative worktree command examples in two fresh shell processes, with the second receiving no `WT` or activation state from the first.

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- packages/ai-parrot/tests/sdd/test_agy_permissions.py
- packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
- packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
- packages/ai-parrot/tests/sdd/test_agy_agents.py
- packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py
- packages/ai-parrot/tests/sdd/test_agy_compat_docs.py
- tests/sdd_scripts/test_check_asset_sync.py
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

- [ ] PR #2040 is merged into `dev` before the FEAT-847 worktree is created, and the Codebase Contract anchors marked "PR #2040" are re-verified on `origin/dev`.
- [ ] The `parrot-sdd-permissions` hook (`agy_permissions.evaluate`) applies the `worktree_environment` AGY verdict (shared-environment denials, PYTHONPATH `overwrite`, file containment), always prints one object with `decision` (`deny` | `force_ask` | `ask`, plus `overwrite` for rewrites), and leaves Claude Code `PreToolUse` behaviour and tests unchanged.
- [ ] With `PARROT_SDD_AGY_UNATTENDED=1`, no path (policy, parse failure, malformed payload, `agy_hook.sh` fallback) answers `force_ask`; each answers `deny`. In that mode with the bubblewrap backend, commands are wrapped through `overwrite`, or denied when `bwrap` is unreachable.
- [ ] `parrot sdd install --host google` writes the managed matcher `run_command|write_file|edit_file`, migrates a receipt-owned `run_command`-only entry, and the tracked `.agents/hooks.json` carries the same matcher.
- [ ] `parrot sdd launch worker --host google` launches `agy` with `--dangerously-skip-permissions`, `PARROT_SDD_AGY_UNATTENDED=1` and the bubblewrap backend; `brief`/`fix --host google` launch it with none of them; neither passes `--mode auto` by default; every Google launch refuses an `agy` that resolves into `/snap/` and prints the official install command.
- [ ] `.agents/agents/` and `parrot/sdd/_assets/manifest.json` include `sdd-coder`, `code-reviewer`, and `qa-runner`, and `.agents/agents/sdd-worker/agent.md` includes the FEAT-549 `parrot-sdd-coder` orchestrator loop adapted for AGY (`invoke_subagent`, `manage_subagents`, model mapping `haiku -> flash`, everything else `-> inherit`).
- [ ] `docs/sdd/AGY.md` exists and documents the Antigravity Adaptation Contract (tool mapping, explicit absolute worktree paths or same-command `WT` assignment, `subagent_type: "fork"` -> `TypeName="self"` only, model mapping, the verified hook/approval semantics, the supported unattended mode, and the official non-snap install).
- [ ] `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort` values `"xhigh"` and `"max"`.
- [ ] All unit tests in the Validation Contract pass (`pytest`) and `ruff check` reports 0 errors.
- [ ] AGY direct file writes are limited to the validated active checkout, reject traversal/symlink/shared-environment escapes, and deny malformed or ambiguous workspace input in AGY format; existing Claude behavior is unchanged.
- [ ] Google foreground, tmux, brief, and fix paths propagate the selected host. The Google worker applies the fail-closed Bubblewrap policy, and unsupported sandbox/network settings and missing or stale hook prerequisites fail before AGY starts.
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
# --- Available only after PR #2040 merges (verified on origin/fix-agy-permission-hook-agy-permission-hook @ 4cbc11df09; NOT on dev @ 34a31c1199) ---
from parrot.sdd.scripts.agy_permissions import Decision, evaluate, _render, main  # PR #2040: agy_permissions.py:119, 1358, 1414, 1421
from parrot.sdd.installer import (  # PR #2040: installer.py:498, 511, 528, 585, 693, 747, 791
    AGY_HOOK_LINE,
    agy_hook_command,
    agy_settings_paths,
    _agy_hook_entry,
    _install_agy_permissions,
    _remove_agy_permissions,
    _agy_permissions_report,
)
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

# packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py — PR #2040 @4cbc11df09 (not on dev yet)
@dataclass(frozen=True)
class Decision:  # line 119
    decision: Literal["deny", "force_ask", "ask"]  # line 122
    reason: str = ""
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Decision:  # line 1358
def _render(decision: Decision) -> dict[str, str]:  # line 1414
def main(argv: Sequence[str] | None = None) -> None:  # line 1421

# packages/ai-parrot/src/parrot/sdd/installer.py — PR #2040 @4cbc11df09 (not on dev yet)
AGY_HOOK_LINE = "parrot sdd hooks agy-permissions --hook"  # line 498
def _agy_hook_entry(command: str) -> dict[str, Any]:  # line 585 — matcher "run_command", timeout 10
def _install_agy_permissions(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:  # line 693

# scripts/sdd/agy_hook.sh — PR #2040: unavailable() prints {"decision": "force_ask", ...}; runs the main checkout's .venv python with PYTHONPATH=<checkout>/packages/ai-parrot/src

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
| `agy_verdict` | `worktree_environment` internals used by `hook_response` | shared guard helpers | `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:783` |
| `agy_verdict` merge, unattended mapping, `overwrite` | `agy_permissions.evaluate` / `_render` / `main` | direct call | PR #2040 `agy_permissions.py:1358, 1414, 1421` |
| unattended fallback | `scripts/sdd/agy_hook.sh` `unavailable()` | env check | PR #2040 `scripts/sdd/agy_hook.sh` |
| widened matcher | `installer._agy_hook_entry` / `_install_agy_permissions` | managed entry | PR #2040 `installer.py:585, 693` |
| `launch_agy_worker` / `host` param | `launch_cli.worker`, `brief`, `fix` | Click `--host` option | `packages/ai-parrot/src/parrot/sdd/launch_cli.py:17, 64` |

### Does NOT Exist (Anti-Hallucination)
- ~~`Agent(subagent_type="fork")` in AGY~~ — AGY does not have a `"fork"` sub-agent type; use `invoke_subagent(TypeName="self", ...)`.
- ~~Frontmatter `hooks:` in `.agents/agents/*/agent.md`~~ — AGY does not support per-agent frontmatter hooks; hooks must live in `.agents/hooks.json` or `.agents/plugins/<plugin>/hooks.json`.
- ~~`Model="haiku"` or `Model="sonnet"` in AGY `invoke_subagent`~~ — AGY's `invoke_subagent` `Model` parameter only accepts `'inherit' | 'flash_lite' | 'flash' | 'pro'`.
- ~~`invoke_subagent(TypeName="research")` as a built-in~~ — no built-in `research` type exists in agy 1.4.12; `sdd-research` is a side-effecting project agent, not a fork substitute.
- ~~A `cwd` field in the AGY `PreToolUse` payload~~ — the envelope carries `workspacePaths`; the hook process cwd is the directory holding `hooks.json`.
- ~~Hook `{"decision": "allow"}` as an approval~~ — ignored without a matching `permissions.allow` rule (verified headless on 1.4.12/1.5.3; interactive by PR #2040).
- ~~`force_ask` as a block under `--dangerously-skip-permissions`~~ — verified to run on 1.5.3; only `deny` blocks there.
- ~~A snap backend / snap support~~ — the community snap cannot run `parrot`, `wikitoolkit`, `bwrap` or `ssh`; Google launches refuse it.
- ~~A second SDD named hook or vendored `.agents/hooks/*.py`~~ — FEAT-847 extends PR #2040's single `parrot-sdd-permissions` hook.
- ~~`agy_permissions` on `dev` today~~ — it exists only on the PR #2040 branch until that PR merges.

### Edit Sites (Blueprint Anchors)
<!-- Verified against: 34a31c1199 -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:` | `worktree_environment.py:783` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py` | MODIFY | `def evaluate(payload: dict[str, Any], *, root: Path \| None) -> Decision:` | PR #2040 @4cbc11df09 `agy_permissions.py:1358` (re-verify after merge) | 1 |
| `scripts/sdd/agy_hook.sh` | MODIFY | `unavailable() {` | PR #2040 @4cbc11df09 (re-verify after merge) | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def _agy_hook_entry(command: str) -> dict[str, Any]:` | PR #2040 @4cbc11df09 `installer.py:585` (re-verify after merge) | 1 |
| `.agents/hooks.json` | MODIFY | `"matcher": "run_command",` | PR #2040 @4cbc11df09 `.agents/hooks.json:5` (re-verify after merge) | 1 |
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
| `docs/sdd/AGY.md` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/agy-compatibility.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Zero third-party imports in hook scripts**: `worktree_environment.py` and `dangerous_actions.py` must remain stdlib-only so they can run under `python -S` or any host interpreter without importing `parrot` (which triggers `navconfig` `.env` loading). `agy_verdict` lives in `worktree_environment.py` and obeys the same rule; `agy_permissions` (PR #2040) imports it from the sibling module like it imports `dangerous_actions`.
- **Keep packaged `_assets` in sync with repo-root assets**: Every change to `.agents/agents/*` or `docs/sdd/AGY.md` listed in `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` must be mirrored in `packages/ai-parrot/src/parrot/sdd/_assets/` so `classify_entry` and `test_installer.py` pass byte-identity checks.
- **Official install only**: `docs/sdd/AGY.md` and the wiki page document `curl -fsSL https://antigravity.google/cli/install.sh | bash` (`~/.local/bin/agy`, self-updating, config at `~/.gemini/antigravity-cli/settings.json`) and state that the community snap is unsupported, with the reasons from §1.

### Known Risks / Gotchas
- **AGY `PreToolUse` `overwrite` field**: Modified tool arguments are returned under `"overwrite": {"CommandLine": "..."}` (shallow merge), NOT `"updatedInput"`. Verified to apply with both `allow` and `ask`, and permission rules then match the rewritten command.
- **Hook `allow` ≠ approval; `force_ask` ≠ block under skip-permissions**: see the §1 table. Never document a hook `allow` as the way to make AGY unattended, and never rely on `force_ask` to stop the unattended worker.
- **Self-updating binary**: the official `agy` updates itself in the background, so the hook contract may change under a running setup. The facts here were verified on 1.4.12 and 1.5.3. The 1.5.2 changelog already changed `--dangerously-skip-permissions`, which now blocks system-denylist commands and, for Enterprise-managed accounts, out-of-workspace access in headless runs.
- **Unverified edges**: the `edit_file` argument shape (M1 denies an `edit_file` with no identifiable target), and how AGY combines several named hooks on one event (avoided by keeping one SDD hook).
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
  - `M2 (Installer Matcher Extension)` → `M1 (AGY Hook Policy Extensions)` because widening the matcher sends file-tool payloads that only M1 handles.
  - `M5 (SDD Sub-Agent Assets & docs/sdd/AGY.md)` → `M1`, `M2`, `M3` because the asset bundle and documentation codify the hooks and launcher flags from `M1`–`M3`.
  - `M1`, `M3`, and `M4` have no dependencies on each other and can run concurrently in Wave 1. M3's unattended env contract (`PARROT_SDD_AGY_UNATTENDED`, `PARROT_SDD_SANDBOX_BACKEND`) is fixed in this spec, so it does not wait for M1.
- **Shared files**: `packages/ai-parrot/src/parrot/sdd/installer.py` (touched only by M2) and `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` (touched only by M5).
- **Exclusive resources**: None.
- **Cross-feature dependencies**: **PR #2040** (`fix-agy-permission-hook-agy-permission-hook`, brief `agy-permission-hook`) must be merged into `dev` before the FEAT-847 worktree is created from `origin/dev`. M1 and M2 modify files that exist only on that branch today.

---

## Consequences

decision audit not configured in this repository

---

## 8. Open Questions

> **Evidence for the resolutions (2026-11-08).**
> - agy 1.4.12, the community snap: the hooks documentation embedded in the binary, `agy --help`, `agy agents`, `snap run --shell antigravity-cli` probes.
> - agy 1.5.3, the official `~/.local/bin/agy`: `agy -p --effort low` runs in a throwaway workspace (`~/snap/antigravity-cli/common/hook-probe-feat847/`) whose logging hook captured the real `PreToolUse` payloads; the CLI log (`Print mode: soft-denying tool confirmation …`); the agy transcript (`tool call denied by pre-tool hook: …`); `agy changelog`.
> - The operator ran the two `--dangerously-skip-permissions` probes, because Claude Code's auto mode refuses that flag.
> - PR #2040's brief: its interactive-mode matrix and the rule-matching findings.

- [x] Should the AGY hook answer `{"decision": "allow"}` on safe commands? — *Resolved (revised 2026-11-08)*: No answer from a hook approves anything:
  - `allow` is ignored without a matching `permissions.allow` rule (headless 1.4.12/1.5.3; interactive per PR #2040);
  - PR #2040's policy answers `ask` (neutral) for passing calls, and FEAT-847 keeps that.

  Approval depends on the mode. The unattended `worker` uses `--dangerously-skip-permissions`, with `deny` as the guard. The interactive `brief`/`fix` sessions use PR #2040's allow-rules plus operator approval, and the hook still denies (M3).
- [x] **Do `PreToolUse` hooks run, and can they deny, under `--dangerously-skip-permissions`?** — *Resolved (operator probe, agy 1.5.3)*: Yes. The hook received both calls, `deny` blocked `ls -1` (`tool call denied by pre-tool hook: …`), and `allow` let `uname -s` run. A second probe showed that `ask` **and `force_ask`** also run under that flag, so the worker's unattended mode maps `force_ask` to `deny` (M1).
- [x] How does the launcher tell the hook it is unattended? — *Resolved*: Through the environment variable `PARROT_SDD_AGY_UNATTENDED=1`. AGY passes its environment to hook processes (verified: a variable set on `agy -p` was visible in the hook). Hand-started `agy` sessions do not set it, and `docs/sdd/AGY.md` says that only `parrot sdd launch worker --host google` is a supported unattended mode.
- [x] Can the hook rewrite commands (PYTHONPATH prefix, Bubblewrap wrapper)? — *Resolved*: `overwrite` applies with both `allow` and `ask`, and permission rules are evaluated against the rewritten command. The PYTHONPATH prefix is therefore safe in every mode, because rules ignore leading `VAR=`, while the Bubblewrap wrapper is applied only in unattended mode, where rules do not apply (M1, M3).
- [x] How should native seat model names map to AGY's `invoke_subagent` `Model` enum? — *Resolved*: `haiku` -> `flash`; every other value (`sonnet`, `opus`, full model ids, unknown strings) -> `inherit`. `pro` and `flash_lite` are never selected automatically, which follows AGY's guidance to use `inherit` unless the user explicitly requests a tier. The earlier "(or `pro` for escalation)" clause is dropped.
- [x] What does `subagent_type: "fork"` map to? — *Resolved*: `TypeName="self"` only. `"research"` is not a built-in AGY type, and the project's `sdd-research` agent has side effects (Jira, specs, worktrees).
- [x] Is the `antigravity-cli` snap supported? — *Resolved (revised)*: No. It is a community wrapper, and under its strict confinement `parrot` and `wikitoolkit` fail (`bad interpreter`), with no `bwrap` and no `ssh`. Every Google launch refuses it and prints the official `install.sh` command. This supersedes the earlier `--sandbox snap` backend and the vendored `python3 -S` hooks, which assumed the snap had to work and were dropped (M3).
- [x] How does FEAT-847 relate to PR #2040 (brief `agy-permission-hook`)? — *Resolved*: FEAT-847 builds on it as a cross-feature dependency. It extends the single `parrot-sdd-permissions` hook and its installer registration instead of adding a second named hook or vendored scripts (M1, M2).
- [x] Does `launch` pass `--mode auto`? — *Resolved*: Not by default. It is account-gated, and on this account AGY prints `--mode auto is not available for this account` and runs in the default mode. `GoogleCodingDispatchProfile.mode="auto"` stays a valid opt-in (M4).

No open questions remain. The unverified edges (the `edit_file` argument shape, multi-hook combination) are handled by design in M1 and listed under Known Risks.

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
  - `wiki/sdd-tooling/sdd/agy-compatibility.md` — create: Architecture and operator guide for running SDD workflows and sub-agents in Google Antigravity CLI (`agy`), including `.agents/hooks.json`, the unattended mode, `docs/sdd/AGY.md`, the official install, and why the community snap is unsupported.
- **API modules**:
  - `parrot.sdd.scripts.worktree_environment`
  - `parrot.sdd.scripts.agy_permissions`
  - `parrot.sdd.installer`
  - `parrot.sdd.launch_cli`
  - `parrot.flows.dev_loop.feature_launcher`
  - `parrot.flows.dev_loop.models.google_coding`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.3 | 2026-11-08 | Claude (decisions: Jesus Lara) | Resolve all open questions with probes on agy 1.4.12 (snap) and 1.5.3 (official). Approval depends on the mode (a hook `allow` approves nothing); hooks deny under `--dangerously-skip-permissions`, where `force_ask` runs, so unattended mode maps `force_ask → deny`; `overwrite` verified, and rules match the rewritten command. The snap is unsupported. FEAT-847 builds on PR #2040 (single hook, matcher widened; no vendored scripts). `fork -> self` only; `haiku -> flash`, everything else `-> inherit`; no default `--mode auto` |
| 0.2 | 2026-11-08 | Codex | Apply specification review: explicit AGY write containment, launcher host/sandbox propagation, self-contained worktree commands and shared skill scope, corrected validation targets and regression coverage |
| 0.1 | 2026-11-08 | Jesus Lara | Initial specification for SDD Antigravity CLI (AGY) operational compatibility |
