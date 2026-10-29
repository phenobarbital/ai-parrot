---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop, docs]
tags: [sandbox, claude-code, sdd-coder, security, worktrees]
---

# Feature Specification: Native Claude sandbox for SDD execution

**Feature ID**: FEAT-768
**Date**: 2026-10-29
**Author**: Jesus Lara / Codex
**Status**: approved
**Target version**: Next release after compatibility qualification; no package version bump in this feature.
**Source**: ledger `issue:e57a19d91778`; parent `issue:6756c929a450`; user request to include the sandbox evaluation recommendations.

## 1. Motivation & Business Requirements

### Problem Statement

Claude SDD Bash isolation currently depends on a `PreToolUse` hook inserting Bubblewrap through
`updatedInput`. A competing rewrite can replace that wrapper. The parent issue recorded actual
escapes; its merged mitigation excludes user settings. That mitigation must remain, but filesystem
enforcement should no longer depend on which command rewrite wins.

The existing research, `sdd/state/6756c929a450/native-sandbox-research.md`, reports that Claude
2.1.312 applies its native sandbox to rewritten Bash commands and ignores unsandboxed retries
when configured strictly. It also reports nested Bubblewrap failure. All successful probes used
`allowAllUnixSockets:true` on an AppArmor-restricted host. They establish feasibility, not acceptance
of the strict production policy. Network, scratchpad and native child-agent inheritance were not
qualified. The report was recovered and read after syncing `dev` for this specification.

### Goals

- G1: Make Claude-hosted Bash filesystem enforcement independent of competing hook rewrites.
- G2: Use the native sandbox instead of the custom Bash Bubblewrap wrapper in supported SDD Claude
  sessions, without nesting, silent fallback or weakening host security.
- G3: Preserve shared-environment protection, test-scope checks, RTK rewriting, command backstops,
  import selection, caches, Git operations and scratchpad continuity.
- G4: Give programmatic and interactive launches one policy compiler and observable failure behavior.
- G5: Qualify the effective policy with positive and negative filesystem/network probes, including
  native `Agent` children, before adoption is considered complete.

### Non-Goals

- Replacing Bubblewrap for in-process dispatchers or changing other CLI providers.
- Full-process containment of Claude, hooks, MCP servers, plugins or LSPs; those remain trusted host
  surfaces with their existing controls. Shell isolation does not provide secret confidentiality.
- Per-task confinement beyond the existing shared worktree-administration allowance; sibling
  worktrees under that allowance remain accessible. Fidelity checks remain necessary.
- Automatically installing dependencies, changing AppArmor/sysctls, granting all Unix sockets,
  enabling nested namespaces, or exposing an unsandboxed escape option.
- Changing the provider client, authentication policy, scheduling or task-state ownership.

## 2. Architectural Design

### Overview

Add a standard-library-only `native_claude_sandbox.py` policy/launcher module beside
`worktree_environment.py`. Both `ClaudeCodeDispatcher` and the interactive worker launcher use it.
The native policy becomes mandatory on those two launch paths for `sdd-worker`/`sdd-coder` once
this feature passes its qualification gates. Other profiles keep their current behavior.

The compiled `--settings` object enables the native sandbox, requires availability, prohibits
unsandboxed retries, has no excluded commands, keeps filesystem isolation enabled, prohibits nested
user namespaces and all-socket access, and carries explicit path and domain policy. The same object
installs the retained SDD hook. Never blindly merge user-provided security settings into it.

Use `PARROT_SDD_SANDBOX_BACKEND=claude-native` in the child process environment to select the hook's
non-Bubblewrap branch. This is coordination metadata, not proof of isolation: the launcher's native
settings are the enforcement boundary. Missing metadata retains the existing Bubblewrap hook;
unknown values deny execution. The dispatcher must override an inherited conflicting value on
its sandboxed path. It must not mutate cached authentication environment dictionaries.

The supported interactive entry point is `scripts/sdd/launch_worker.sh`; direct `claude --agent`
invocation is not a qualified native launch. Existing direct launches retain the legacy wrapper,
not a runtime fallback following native failure. Do not instruct users to fix native failures by
restarting without protection. Reverting this feature is a code/deployment rollback.

### Component Diagram

```text
Claude dispatcher ─┐
                   ├─ native policy/compiler ─ --settings + child env ─ Claude runtime sandbox
worker launcher ───┘                                                    │
                                                    retained SDD hook ──┤
                                                    guard → RTK → bound │
                                                                        └─ Bash + descendants
in-process dispatcher ─ existing protected_argv ─ Bubblewrap (unchanged)
file tools ─ retained hook → existing environment check + native write-policy check
```

### Policy decisions

1. **Paths.** Resolve canonical paths using existing repository/environment helpers. Allow the
   linked checkout, common Git metadata, existing worktree-administration and ledger directories,
   and scratchpad storage. Deny writes to shared environments, RTK trust storage, Git hooks,
   common Git `config`, and per-worktree `config.worktree`/hook paths. Cover nonexistent destinations,
   symlink aliases and Git config lock/replacement attempts. A broad Git grant must not override
   these denials. Protect policy/settings and hook control files from agent file-tool modification
   in native mode; do not claim the native shell policy alone protects those tools.
2. **Root policy.** Native launches require a linked worktree with valid Git metadata. Reject a
   primary-checkout cwd even if `allow_project_root_cwd` is set for a sandboxed profile. That waiver
   remains applicable to other profiles. Never turn cwd disappearance into a new writable primary
   checkout. Existing self-removal recovery must stay within the original administration allowance;
   if runtime recovery is impossible, exit with a clear diagnostic instead of widening paths.
3. **File tools.** Keep `validate_write_path` unchanged for legacy consumers; add a native-policy
   validator for the file-tool hook covering allowed roots and denied control paths above. Check
   each target supported by Write/Edit/MultiEdit/NotebookEdit; malformed inputs deny. This is an
   application guard, not an OS sandbox or a claim of protection against hostile hook code.
4. **Command behavior.** Keep guard → RTK → bounded shell ordering and original timeout/background
   fields. Native mode omits only `protected_argv`. Preserve `UV_NO_SYNC=1`,
   `PYTHONDONTWRITEBYTECODE=1`, worktree `packages/*/src` precedence in `PYTHONPATH`, writable isolated
   cache locations, and scratchpad continuity. Compute import paths for the command's task cwd:
   the hook payload `cwd` is always the parent session's (preflight Q2), so in native mode a command
   that starts with exactly `cd <absolute path> &&` uses that path as its task cwd when it resolves
   inside the allowed roots of policy 1; any other `cd` target, a relative path or an unparseable
   prefix denies; commands without the prefix use the session cwd. The native `sdd-coder` seat
   prefixes every Bash command with `cd <its sub-worktree> &&`, because `cd` does not persist between
   child Bash calls. Keep the timeout margin and background semantics. Competing hooks
   may still replace operational rewrites; native isolation does not make those rewrites atomic.
5. **Temporary storage.** Allocate session-specific cache directories under native writable temporary
   storage; do not grant general host `/tmp` write access. Preserve the existing per-user scratchpad
   allowance. Native temporary storage is not assumed to equal Bubblewrap's per-command tmpfs:
   document residual visibility, prove caches do not write shared host locations, and clean only
   owned cache directories after the session. No cross-session secrecy claim.
6. **Network.** Default domain list is empty. Add `sandbox_allowed_domains: List[str]` to the dispatch
   profile and repeatable `--sandbox-allow-domain HOST` to the interactive launcher. Accept exact
   DNS hostnames, normalize case/deduplicate, reject URLs, wildcards, ports and IP literals. Never
   auto-learn domains from denied commands or grant wildcard egress. An operator may supply
   `github.com`/`api.github.com` for HTTPS Git/gh, or registry hosts for explicitly authorized
   task-local dependency work; redirects need explicit destinations too. No raw SSH support in v1.
   Test both allowed proxy traffic and denied direct traffic. Model/API traffic outside Bash is
   outside this policy. Unknown destinations must not cause unattended authorization prompts or
   automatic permission expansion; qualify this under the actual permission mode.
7. **Settings authority.** Keep `_effective_setting_sources` excluding `user`. Use CLI-injected
   strict settings; verify effective project/local settings cannot widen writes/domains, disable
   isolation, or add exclusions. Empty arrays are not presumed to replace inherited arrays.
   Preflight (2.1.312, relaxed sockets) found no widening even when the CLI omitted path/domain keys,
   but did not isolate why; the compiler still emits every key explicitly, and M4 repeats the matrix
   strictly on both executables.
   If the tested runtime cannot enforce the compiled boundary, refuse the configuration and block
   rollout; do not accept a weaker effective policy. The interactive launcher rejects caller
   `--settings`, `--add-dir`, security-disabling options, and alternate `--agent` values; preserve
   existing model and safe argument forwarding. Audit equivalent supported CLI aliases.
8. **Git.** Commit, diff, worktree add/remove/prune and HTTPS push must work with protected config.
   Use `git push origin <branch>` rather than `git push -u` inside native sessions. Upstream setup,
   remote changes and host Git configuration belong to the host before launch. No writable config
   exception to make setup commands work. Shared ledger writes remain an orchestrator capability;
   this feature does not authorize coder agents to write ledger state.
9. **Host qualification.** Initial supported target is Linux with a qualified Claude CLI version,
   Bubblewrap, socat and functional Unix-socket filtering. Claude 2.1.312 is the research baseline,
   not proof of a supported strict configuration. Missing dependencies, namespace/seccomp failures
   or unsupported runtime capabilities stop the native session. No automatic root action. macOS,
   WSL and native Windows are not certified by this feature.
   Qualification records the actual executable used on each path: an SDK-bundled CLI must not be
   treated as equivalent to the interactive `claude` found on PATH merely because one passed.
   Decision: the dispatcher keeps the SDK-bundled CLI (no `cli_path` override) and the launcher uses
   PATH `claude`; each is qualified separately, at its exact version. A version change of either
   (CLI update or `claude-agent-sdk` bump) invalidates that path's qualification until the live gate
   is re-run. The initial strict host is the maintainer workstation (elementary OS 8.1, Ubuntu 24.04
   base) after the operator installs an AppArmor profile permitting Claude's seccomp helper; its
   current unprofiled state is the restricted-host failure evidence.

### Integration Points

| Existing component | Integration | Contract |
|---|---|---|
| `ClaudeCodeDispatcher._resolve_run_options` | Compose native settings and environment | Preserve auth, MCP, model and non-SDD behavior |
| `scripts/sdd/launch_worker.sh` | Delegate argument preparation to the shared launcher | Preserve default worker/model and source exclusion |
| `worktree_environment.hook_response` | Select native or legacy execution path | Same denial response; native does not insert bwrap |
| Agent definitions and worktree rule | Document supported launch and Git behavior | No frontmatter claim that a child can set its own session sandbox |

### Data Models / New Public Interfaces

The sole new public profile field is `ClaudeCodeDispatchProfile.sandbox_allowed_domains`, a Pydantic
list with an empty default. Builders return JSON-compatible settings and environment mappings;
they introduce no new domain model or provider dependency. Exact function contracts are in §3.

## 3. Module Breakdown

### Delegation-eligible modules

| Module | Eligible? | Decided patterns / contracts | Why not |
|---|---|---|---|
| M1 policy and native hook | no | Stdlib helpers, explicit modes and path matrix below | Settings precedence and strict-host qualification must be proven first |
| M2 dispatcher integration | yes, after M1 | Profile field; compose settings/env without changing auth | — |
| M3 interactive launcher | yes, after M1 | Shared Python launcher behind existing shell entry point | — |
| M4 qualification and regressions | no | Required assertions and evidence format in §4 | Real runtime behavior needs investigation, not mechanical coding |
| M5 operating documentation | yes, after M4 | Approved launch, scope, host remediation, Git push contract | — |

### M1: Shared policy and retained hook

- **Paths**: create `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py`;
  modify `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py`.
- **Depends on**: existing stdlib-only repository, environment, guard, RTK and timeout helpers.
- **Responsibility**: compile the native boundary; provide per-cwd execution environment and
  file-write validation; route the hook without nesting Bubblewrap. Keep direct script invocation
  working without importing Parrot's dependency-heavy package initialization.
- **Interface Skeleton** (new unless marked):

```python
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]:
    """Build strict CLI settings including hooks; raise ValueError for invalid roots/domains."""

def native_command_environment(cwd: Path) -> dict[str, str]:
    """Return task-cwd import/cache/safety overrides without mutating os.environ."""

def validate_native_write_path(cwd: Path, path: Path) -> None:
    """Reject writes outside native allowances or into protected environment/control paths."""

def native_task_cwd(session_cwd: Path, command: str) -> Path:
    """Return the absolute `cd <path> &&` prefix target inside allowed roots, else session_cwd; raise ValueError for a disallowed or malformed prefix."""

# modifies: packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:502
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:
    """Apply guards and file checks; omit bwrap only for explicit claude-native mode; deny invalid modes."""

# modifies: packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:534
def main() -> None:
    """Read hook JSON and launcher-selected backend; emit explicit denial on failures."""
```

Use `ValueError` for invalid policy/configuration and `RuntimeError` for unavailable prerequisites.
Hook failures become `permissionDecision="deny"`, never an empty successful response. Keep
`protected_argv` and its legacy callers' policy unchanged.

### M2: Programmatic launch

- **Paths**: modify `models/claude.py` and `dispatchers/claude.py` under the same dev-loop source root.
- **Depends on**: M1 `native_sandbox_settings` and `native_command_environment`.
- **Responsibility**: mandatory strict native settings for the two sandboxed profiles, preserving
  `_effective_setting_sources`, explicit hooks and current authentication behavior. Per-dispatch
  environment must be copied, never shared/mutated across concurrent attempts.
- **Interface Skeleton**:

```python
# modifies: packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py:10
class ClaudeCodeDispatchProfile(BaseModel):
    """Existing profile plus validated exact-host native sandbox egress grants."""
    sandbox_allowed_domains: List[str] = Field(default_factory=list)

# existing signature: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:562
def _resolve_run_options(self, profile: ClaudeCodeDispatchProfile, cwd: str) -> ClaudeAgentRunOptions:
    """Compile strict native settings for sandboxed seats; retain all unrelated options."""
```

The class skeleton lists the added field only; all existing fields remain. This is not a replacement
class implementation. No changes to `clients/base.py` or the Anthropic SDK wrapper.

### M3: Interactive launch

- **Paths**: modify `scripts/sdd/launch_worker.sh`; add the launcher entry to M1's new module.
- **Depends on**: M1 settings builder; shares that file, so tasks editing it must serialize.
- **Responsibility**: use the active interpreter to invoke the stdlib launcher, preserve argument
  boundaries, reject policy overrides, and replace the process with Claude after policy validation.
  Pass generated settings as one JSON argument, not shell-expanded text or a mutable project file.
- **Interface Skeleton**:

```python
# new: packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py
def launch_worker(argv: Sequence[str]) -> int:
    """Launch sdd-worker with strict settings; return 2 for invalid input, 1 for unavailable host."""

def main() -> None:
    """Serve the launch-worker subcommand, forwarding the child exit status."""
```

CLI: `scripts/sdd/launch_worker.sh [--sandbox-allow-domain HOST]... [safe Claude arguments]`.
Default model remains `sonnet`; safe caller model overrides remain supported. Errors identify the
missing prerequisite or rejected option without printing credentials. No network probe/model call
is introduced merely by compiling policy.

### M4: Regression and qualification evidence

- **Paths**: modify existing tests listed in §6; create
  `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` and
  `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py`.
- **Depends on**: M1–M3 for execution; fixture/test design can proceed independently.
- **Interface Skeleton** (proposed tests, not existing node IDs):

```python
def test_native_settings_reject_widening_inputs(tmp_path: Path) -> None:
    """Assert malformed roots and invalid domains cannot produce a permissive launch."""

def test_native_hook_retains_operational_guards(tmp_path: Path) -> None:
    """Assert scope/RTK/backstop/environment behavior without an inserted bwrap wrapper."""

async def test_live_native_rewrite_and_child_boundary(tmp_path: Path) -> None:
    """Opt-in real Claude probe: rewritten parent/child commands cannot mutate protected canaries."""
```

### M5: Operations and agent guidance

- **Paths**: create `docs/dev_loop/claude-native-sandbox.md`; modify `.claude/agents/sdd-worker.md`,
  `.claude/agents/sdd-coder.md` and `.claude/rules/worktree-management.md`.
- **Depends on**: M4 qualification results and M3 CLI.
- **Interface Skeleton**: documentation-only contract is the exact launcher CLI above; document
  its errors, tested version/host matrix, domain configuration, supported Git sequence, residual
  trusted surfaces and rollback. Remove contradictory `push -u` guidance for native sessions.
  `sdd-coder.md` tells the native seat to prefix every Bash command with `cd <sub-worktree> &&`.

## 4. Test Specification

### Unit Tests

| Coverage | Assertions |
|---|---|
| Policy generation | Strict booleans, no exclusions/nesting/all-socket grants; canonical paths; invalid/root cwd refusal |
| Domain input | Empty default; normalization/deduplication; wildcard/URL/IP/port refusal |
| Hooks | Native omits bwrap; legacy keeps it; malformed mode/input denies; guard then RTK then timeout |
| Environment | Per-task source roots; no shared cache writes; auth map unmodified; concurrent seats do not leak paths |
| Task cwd | Leading `cd <abs> &&` inside allowed roots selects that worktree's paths; relative, outside-root, quoted-trick and malformed prefixes deny; no prefix uses session cwd |
| File tools | Shared venv aliases, Git configuration/hooks and policy files denied; task edits allowed |
| Dispatcher | Both SDD profiles inject settings and env; user sources excluded; all other profiles unchanged |
| Launcher | Existing model/argument behavior; forbidden overrides in split/equals forms; spaces safely forwarded |

### Integration Tests

Use a temporary primary Git repository, linked feature and pool worktrees, a simulated shared venv
with sentinel `.pth`, a symlink to it, a scratchpad, a fake RTK trust store and disposable Git remotes.
Canaries belong to fixtures, never the operator's real files. Positive controls establish that each
denied target would be writable without isolation. SDK argument tests inspect final argv, not only
the Pydantic options object. Missing optional SDK skips are not acceptance evidence for launch wiring.

Retain the real Bubblewrap tests proving legacy/in-process isolation and linked-worktree commits.
Add deterministic tests for native-policy assembly and OS-independent failure branches; do not
label fake CLI tests as proof of Claude's runtime enforcement.

The new deterministic file below is a declared deliverable. Do not run this contract until it exists.
The live file is deliberately excluded: it calls a provider and requires a separate bounded run.
No deterministic E2E-gate integration is introduced by this feature.

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_models.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
- tests/sdd/test_launch_worker.py
markers: none

### Live qualification gate (separate from the Validation Contract)

Run only with `PARROT_TEST_REAL_LLM=1`, an explicit request budget (maximum 8 sessions, 12 turns per
session, USD 5 total) and a 180-second per-session timeout. Use the existing `AbstractClient` path
or the actual interactive launcher under test, never direct provider SDK calls. Capture sanitized
results under `artifacts/logs/`; persist the version, host prerequisites, settings digest, exact
commands, exit statuses and canary assertions in `sdd/state/FEAT-768/native-sandbox-qualification.md`.
Do not commit raw transcripts containing credentials. Absent prerequisites yield NOT QUALIFIED,
not a pass. Exceeding budget stops and reports remaining cases.

| Scenario | Required observation |
|---|---|
| Competing rewrite | A distinct marker proves the competing rewrite ran; protected canary remains unchanged |
| Native Agent child | Child Bash runs under inherited policy with its task cwd; no nested bwrap; same denied writes |
| Filesystem matrix | Task edits and scratchpad continuity work; primary source, home, venv aliases and RTK trust store remain read-only |
| Git controls | Commits/worktree administration succeed; config, config.worktree, hooks and lock/replacement attempts fail |
| File-tool bypass | Write/Edit/NotebookEdit attempts at protected targets are rejected by retained guards |
| Settings widening | Project/local exclusions, wider paths/domains and disabling flags cannot loosen effective native policy |
| Retry/failure | `dangerouslyDisableSandbox` under bypassPermissions cannot write canaries; missing deps/blocked namespaces execute no workload |
| Egress | Explicit test destination works; unlisted destination and proxy-bypassing direct request fail without automatic grants |
| Compatibility | HTTPS push without `-u`, enabled gh operation, selected task-local dependency operation, bounded command and scratch/cache behavior work |

Run strict settings without `allowAllUnixSockets:true`; include Ubuntu 24.04-family restricted-host
failure evidence and at least one supported strict host success. Host remediation is performed by
the operator outside this feature's automated tests. Use command results and independent canary
inspection: transcript `tool_use.input` may retain the pre-rewrite command. Failure to observe an
actual competing rewrite or actual child tool call makes that scenario inconclusive.

## 5. Acceptance Criteria

- [ ] AC1: Both official launch paths enable strict native sandboxing for SDD workers/coders.
- [ ] AC2: Competing rewrite and native child probes pass with strict socket filtering; no double wrapping.
- [ ] AC3: Unavailable isolation and attempted unsandboxed retries stop execution without fallback.
- [ ] AC4: Path matrix, Git carve-outs and file-tool guards pass positive/negative tests, including aliases.
- [ ] AC5: Scope guard, RTK, timeout margins, per-cwd imports, caches and scratchpad behavior are preserved.
- [ ] AC6: Network policy enforces configured domains and rejects unlisted/direct egress without widening.
- [ ] AC7: Effective settings cannot be weakened by project/local configuration or launcher overrides.
- [ ] AC8: Necessary Git operations work with read-only configuration; documentation uses explicit push without `-u`.
- [ ] AC9: Existing in-process/Bubblewrap and non-SDD profile behavior passes the regression contract.
- [ ] AC10: Qualification report records a supported strict host, actual CLI executables/versions for both launch paths and failure-host behavior; skipped/live-unrun cases are not passes.
- [ ] AC11: Operator/agent documentation describes supported entry points, trusted surfaces, host prerequisites and safe failure handling.
- [ ] AC12: No package installation, system-security mutation, permission broadening or provider/base-client changes accompany implementation.

## 6. Codebase Contract

Verified against `b51434f7a2db9d41a17a0166d830116537f0976a` (dev plus this feature's ID reservation).
All paths below are relative to the repository root.

### Verified Imports

```python
from parrot.flows.dev_loop import worktree_environment
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:66
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile
# verified export: packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py:64
from pydantic import BaseModel, Field
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py:7
```

The stdlib hook must retain standalone imports; the package imports above describe dispatcher
integration, not permission to import all Parrot dependencies from the hook.

### Existing Class Signatures / Helpers

| Verified contract | Location |
|---|---|
| `repository_paths(cwd: Path) -> tuple[Path, Path \| None]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:54` |
| `shared_environments(cwd: Path) -> tuple[Path, ...]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:75` |
| `validate_write_path(cwd: Path, path: Path) -> None` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:96` |
| `worktree_admin_dirs(root: Path, git_dir: Path \| None) -> tuple[Path, ...]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:152` |
| `shared_ledger_dirs(root: Path, git_dir: Path \| None) -> tuple[Path, ...]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:182` |
| `claude_scratch_root() -> Path` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:211` |
| `protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:228` |
| `bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:424` |
| `rtk_rewrite(command: str) -> str \| None` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:463` |
| `ClaudeCodeDispatchProfile(BaseModel)`; `setting_sources` defaults to `["project"]` | `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py:10` and `:32` |
| `ClaudeCodeDispatcher._resolve_run_options(self, profile: ClaudeCodeDispatchProfile, cwd: str) -> ClaudeAgentRunOptions` | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:562` |
| `_effective_setting_sources(self, profile: ClaudeCodeDispatchProfile) -> Optional[List[str]]` | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:670` |
| `_resolve_dispatch_env(self) -> Dict[str, str]` caches authentication overrides | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:741` |

`ClaudeAgentRunOptions(BaseModel)` is in the satellite package:
`packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py:85`.
Existing `env` (`:158`), `setting_sources` (`:177`) and `extra_args` (`:195`) already carry this feature;
do not add a parallel transport or modify that file.

### Integration Points

| New component | Connects to | Via | Verified at |
|---|---|---|---|
| Native policy compiler | Dispatcher run options | Existing `extra_args["settings"]` JSON | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:636` |
| Native hook mode | Existing JSON hook entry | `main()` → `hook_response()` | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:534` |
| Interactive native entry | Existing worker script | Replace final Claude command assembly with shared launcher | `scripts/sdd/launch_worker.sh:48` |
| File guard | Current shared-env validation | Preserve check, add native roots/control paths | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:96` |

### Does NOT Exist (Anti-Hallucination)

- `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` and all functions proposed in it are new; do not import them before M1.
- `ClaudeCodeDispatchProfile.sandbox_allowed_domains` does not currently exist.
- An existing native sandbox attestation API, per-Agent sandbox configuration field, and native
  qualification report are not verified contracts; do not invent them.
- `packages/ai-parrot/src/parrot/clients/anthropic/claude_agent.py` does not exist; the client lives in the satellite.
- Current `validate_write_path` only protects shared environments; it does not confine all file tools.

### Edit Sites (Blueprint Anchors)

Counts are fixed-string full-line counts, verified at the base commit above. Recheck before tasking.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | `def hook_response(payload: dict[str, Any]) -> dict[str, Any]:` | `:502` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py` | MODIFY | `class ClaudeCodeDispatchProfile(BaseModel):` | `:10` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | `    def _resolve_run_options(` | `:562` | 1 |
| `scripts/sdd/launch_worker.sh` | MODIFY | `set -euo pipefail` | `:24` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | `def test_resolves_pool_and_shared_symlink(checkout: tuple[Path, Path]) -> None:` | `:57` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | `class TestProfileResolution:` | `:131` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_models.py` | MODIFY | `class TestDispatchProfile:` | `:130` | 1 |
| `tests/sdd/test_launch_worker.py` | MODIFY | `def test_defaults_exclude_user_source(fake_claude_path: str) -> None:` | `:42` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | `## Shared environment policy` | `:47` | 1 |
| `.claude/agents/sdd-coder.md` | MODIFY | `## Shared environment policy` | `:34` | 1 |
| `.claude/rules/worktree-management.md` | MODIFY | `## 4. Work inside` | `:49` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py` | CREATE | — | — | — |
| `docs/dev_loop/claude-native-sandbox.md` | CREATE | — | — | — |
| `sdd/state/FEAT-768/native-sandbox-qualification.md` | CREATE | — | — | — |
| `sdd/state/FEAT-768/native-sandbox-preflight.md` | EXISTS | preflight evidence for §8; read, do not rewrite | — | — |

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep existing dependency boundaries: stdlib-only hook/compiler and Pydantic profile. No new Python dependency.
- No synchronous process/network work in async request paths. Pure policy compilation may run in
  `_resolve_run_options`; actual async execution stays in the existing dispatcher/client flow.
- Preserve exact argument boundaries, typed functions and explicit diagnostics. Do not log credentials.
- Keep the user-settings exclusion from issue:6756c929a450 even after the race no longer removes isolation.
- Treat the original report as historical evidence; never copy its relaxed settings into production.

### Known Risks / Gotchas

- AppArmor may permit bwrap but still deny the seccomp helper. Binary presence is insufficient.
- Filesystem grants and settings arrays may merge; testing only generated JSON cannot prove enforcement.
- Native child sessions may inherit the parent working boundary instead of a task-specific one. Verify
  actual cwd/import behavior and keep the existing fidelity boundary explicit.
- `git push -u` writes configuration; remote setup must occur before native launch.
- Existing broad worktree administration and scratchpad grants are shared across the user's sessions.
- Removing a worktree mid-session can invalidate cwd. Never compensate by granting the primary checkout.
- A valid sandbox does not guarantee scope/RTK rewrite survival against another hook, nor contain the
  hooks themselves. Keep hook configuration trusted and controlled.

### External Dependencies

| Dependency | Version/status | Reason |
|---|---|---|
| Claude Code CLI | Research baseline 2.1.312; exact qualified version recorded by M4 | Native runtime behavior |
| Bubblewrap, socat, working socket filter | Host prerequisites; no auto-install | Strict Linux isolation |
| `claude-agent-sdk` | Existing `>=0.1.68`, satellite pyproject line 18 | Existing dispatch transport; no dependency change |

Official reference checked 2026-10-29: [Claude sandbox documentation](https://code.claude.com/docs/en/sandboxing).
It documents shell-only scope, Linux Bubblewrap/socat, strict retry/availability options and settings
precedence. Feature-specific policy and acceptance requirements above are our design, not upstream guarantees.

## 8. Open Questions

- [x] Replacement or stacking? Replace the custom Bash wrapper only for qualified Claude launch paths.
- [x] Unsupported host fallback? Fail closed; no socket/namespace relaxation or automatic unsandboxed retry.
- [x] Non-Claude execution? Preserve existing Bubblewrap behavior.
- [x] Network default? Empty exact-host list, operator-configured per launch/profile; HTTPS operations only in v1.
- [x] Git configuration protection? Read-only config/hooks; host owns setup, workers push without `-u`.
- [x] Which exact CLI/SDK/host combination? Target: the maintainer workstation (elementary OS 8.1 /
  Ubuntu 24.04 base, bwrap 0.9.0, socat 1.8.0.0) with an operator-installed AppArmor profile for
  Claude's seccomp helper; interactive PATH `claude` 2.1.312 and the dispatcher's SDK-bundled CLI
  2.1.301 (`claude-agent-sdk` 0.2.168), qualified separately — no `cli_path` pinning (policy 9).
  Without the profile, strict mode fails closed on this host (restricted-host evidence).
  *Remaining M4 gate:* strict runs on both executables after the profile is installed.
- [x] Does native Agent inheritance preserve task-cwd and guard behavior? Guards and sandbox: yes, on
  both executables — children inherit the boundary, the hook fires with `agent_id`, a competing
  rewrite stays sandboxed, nested bwrap fails. Task cwd: no — payload and shell start at the parent
  session cwd and `cd` does not persist. Resolved by the leading `cd <abs> &&` rule (policy 4).
  *Remaining M4 gate:* strict re-run, plus the native seat running tests in its own sub-worktree.
- [x] Can project/local settings widen the compiled bounds? Not on 2.1.312 in preflight: project
  `allowWrite`/`excludedCommands`/`allowedDomains` and local `enabled:false` had no effect, even
  with the CLI omitting those keys. No extra settings lock is needed. *Remaining M4 gate:* strict
  re-run on 2.1.312 and the first run on 2.1.301.

Evidence: `sdd/state/FEAT-768/native-sandbox-preflight.md` (relaxed sockets; not the qualification
report). The remaining gates above are qualification gates, not permission to implement weakened
substitutes.

## 9. Design Research Cross-Check

Status: skipped — direct user request with existing ledger research; no accepted brainstorm/proposal
or completed intake artifact, so the optional independent-research precondition was not met.
The original probe report and current source were reviewed; no independent review is claimed.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

## Worktree Strategy

- **Isolation**: per-spec; one feature worktree, with engine-managed task sub-worktrees.
- **Dependency graph**: M2 → M1 (settings/environment helpers); M3 → M1 (compiler); M4 execution →
  M1/M2/M3 (launch paths under test); M5 → M3/M4 (CLI and qualification). M2 and M3 are otherwise independent.
- **Shared files**: M1/M3 share `native_claude_sandbox.py`; serialize edits to that file. M4 owns test files.
- **Exclusive resources**: live qualification uses a bounded provider budget and host prerequisites;
  serialize those runs. Deterministic tests use isolated fixtures. No shared environment/lockfile rebuild.
- **Cross-feature dependencies**: issue:6756c929a450 mitigation is already present at the verified base.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-29 | Jesus Lara / Codex | Initial draft from issue:e57a19d91778 with strict adoption and compatibility gates |
| 0.2 | 2026-10-29 | Jesus Lara / Claude | Resolve §8 with preflight probes: target host + AppArmor, both CLIs qualified separately, leading-`cd` task cwd, no settings widening observed |
