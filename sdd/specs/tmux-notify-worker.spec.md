---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd, tmux, notifications, worker]
---

# Feature Specification: tmux worker completion notifications

**Feature ID**: FEAT-793
**Date**: 2026-11-03
**Author**: Jesus Lara (request), Codex (specification)
**Status**: draft
**Target version**: Next release

## 1. Motivation & Business Requirements

### Problem Statement

Workers launched with `parrot sdd launch worker FEAT-* --tmux` run in a separate
terminal session. Operators need a desktop notification when the worker finishes
so they do not have to repeatedly inspect its pane.

### Goals

- Notify the operator through the host's `notify-send` command.
- Identify the feature and completion outcome in the notification.
- Keep notification delivery optional at runtime: unavailable desktop services must
  not break worker execution or alter its exit status.
- Preserve the launcher environment isolation and sandbox policy.
- Fire after the SDD completion sequence, while the Claude Code CLI remains open.

### Non-Goals (explicitly out of scope)

- Installing desktop services or Python dependencies.
- Remote desktop forwarding, messaging integrations, or global tmux configuration.
- Notifications for `launch brief`, `launch fix`, or non-tmux workers.
- Process-exit notifications, partial-task notifications, failure alerts, or interpreting
  ordinary assistant pauses as completion.

## 2. Architectural Design

### Overview

Enable a launch-scoped completion receipt and a host-side Claude Code `Stop` hook
only for newly launched tmux feature workers. Keep the existing direct exec and
`remain-on-exit failed` behavior. No tmux exit hook or process watcher is involved.
`notify-send` runs on the tmux host, outside the worker's Bash sandbox.

Completion means the worker has finished its feature task loop, settled its children,
performed its existing review/deferred-finding handling, and successfully pushed the
feature branch. Immediately before its final summary, the worker explicitly records
completion. The following Stop event consumes that receipt and attempts one desktop
notification. This is a notification of worker completion, not merge approval or
successful `/sdd-done` closeout.

Claude Code Stop is a response boundary, not a process-exit event. Do not rely on
`agent_type` being present in its payload, parse final prose, or treat every Stop as
completion. See the [official Stop contract](https://code.claude.com/docs/en/hooks#stop).

### Launch and delivery contract

1. `feature_launcher.launch` clears inherited `PARROT_SDD_NOTIFY_*` values in its
   child environment. Only the new-tmux branch populates `PARROT_SDD_NOTIFY_FEATURE`,
   `PARROT_SDD_NOTIFY_SLUG`, and `PARROT_SDD_NOTIFY_DESKTOP` (JSON snapshot).
   Desktop keys are allowlisted: `PATH`, `HOME`, `DISPLAY`, `WAYLAND_DISPLAY`,
   `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`. Capture only `base_env` values;
   missing keys stay absent. Existing `_tmux_environment` carries these prefixed
   assignments even when the tmux server predates this launch.
2. After allocating its existing session cache, `native_claude_sandbox.launch_worker`
   configures notifications only with valid feature metadata and a tmux pane
   environment. Save `notify-context.json` in that cache, and append one command
   Stop hook to the compiled settings, preserving all existing hooks and policy.
   Export absolute `PARROT_SDD_NOTIFY_PYTHON` and `PARROT_SDD_NOTIFY_HELPER` paths.
   Resolve the helper relative to the installed module, never a monorepo path.
3. The worker's feature-level Completion instructions call
   `"$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete`
   only when these variables are present and after successful push. Task-scoped
   workers must not call it. Failure to record is logged, never retried by widening
   sandbox permissions, and does not invalidate completed SDD work.
4. `--complete` validates the launch context, feature index identity, nonempty tasks
   with every `status == "done"`, and current worktree root. It records launch UUID,
   feature ID, worktree, and current Git HEAD in `notify-complete.json` by atomic
   replacement. Repeated recording cannot reset the delivery claim. The worker's
   explicit invocation attests that review and push occurred; this helper is not a
   replacement review or remote-push verification gate.
5. The Stop hook invokes the same installed script with `--hook --cache <absolute>`.
   It accepts bounded JSON input (64 KiB), requires `hook_event_name == "Stop"`,
   and validates context/receipt UUID, feature, worktree and HEAD. Nonempty
   `background_tasks` or `session_crons`, when supplied by the CLI, defer delivery.
   Missing newer optional fields do not suppress a valid explicit receipt. Never
   register SubagentStop: child completion must not consume the parent receipt.
6. Atomically create `notify-attempted` exclusively before sending. One launch gets
   at most one delivery attempt, including overlapping hooks. Invoke `notify-send`
   with an argument list, `shell=False`, a three-second subprocess timeout, normal
   urgency, and app name `AI-Parrot SDD`. Title: `SDD work completed: <FEAT-ID>`.
   Body: `<slug>\n<worktree>\nClaude Code remains open.` Escape markup in body
   values; never include transcripts, credentials or command output.
7. Hook timeout is five seconds. All invalid-input, missing-executable, unavailable
   D-Bus, timeout and filesystem failures produce at most a concise logger warning
   and exit 0 with empty stdout. No blocking decision, continuation request, retries,
   terminal control sequences, network delivery, or platform installation.

### Component Diagram

```text
new tmux launch -> launch context + existing session cache + Stop hook
SDD tasks -> review -> successful push -> explicit completion receipt -> summary
Stop hook -> validate receipt -> atomic attempt claim -> host notify-send
Claude Code remains interactive throughout notification delivery
```

### Data Models

Three small, versioned JSON documents (schema version 1) use strict stdlib decoding
and field/type validation, consistent with the `python -S` launcher boundary.
Context fields: `schema_version`, `launch_id` (cache UUID), `feature_id`, `slug`,
`worktree`, `index` (contained relative path), `desktop_env` (allowlisted mapping).
Derive `index` as `sdd/tasks/index/<slug>.json` and verify its `feature_id` before
accepting it; never accept a path from hook input.
Receipt fields: `schema_version`, `launch_id`, `feature_id`, `worktree`, `head`.
The third JSON document is the incoming Claude hook payload. No new Pydantic model
is imported into this stdlib-only execution path. Context/receipt files are mode
0600 within the existing 0700 session cache and follow its existing cleanup lifecycle.
Reject symlink state files and index paths escaping the worktree. This is advisory
completion signaling, not a security attestation against a malicious worker.

### Integration Points and New Public Interfaces

No user-facing CLI flag or tmux configuration change. Notifications are automatic
for new tmux feature launches with a usable host notification service. Reattach
does not retrofit old sessions or resend a notification. The new helper's internal
CLI modes are `--complete` and `--hook --cache PATH`; their contracts are fixed below.

## 3. Module Breakdown

### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not |
|---|---|---|---|
| M1 Receipt and notifier | yes | Stdlib helper, versioned files, atomic claim, bounded delivery, interfaces below | — |
| M2 Launcher wiring | yes | Prefixed environment, existing cache, additive Stop hook, no public signature changes | — |
| M3 Worker protocol and docs | yes | Receipt after successful push, before summary, feature-only; identical shipped twin | — |

### Module 1: Completion receipt and host notifier

**Create:** `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` and
`packages/ai-parrot/tests/sdd/test_worker_notification.py`.

```python
def configure_notification(
    cache: Path, *, worktree: Path, env: Mapping[str, str]
) -> str | None:
    """Write validated launch context; return a shell-quoted Stop hook command, or None on failure."""

def record_completion(env: Mapping[str, str]) -> bool:
    """Atomically record eligible feature completion in the existing session cache."""

def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
    """Attempt one notification for a valid receipt; never raise operational errors to Claude."""

def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch complete/hook mode; return 0 on success, skipped work, or notification failure."""
```

Use `PARROT_SDD_CACHE_DIR` for the complete mode's cache. Delivery uses only the
captured desktop mapping, not a merged `os.environ`. Resolve `notify-send` against
that captured PATH (platform default search path if PATH was absent). Hook command
construction uses `shlex.join` and invokes this script under `sys.executable -S`.
The helper imports no `parrot` modules and never interprets metadata as commands.

### Module 2: Tmux launch and compiled settings

**Modify:** `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`,
`packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`,
`packages/ai-parrot/tests/sdd/test_sdd_launch.py`, and
`packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py`.
Depends on M1's `configure_notification`.

```python
# Existing launch signature is reproduced in §6; keep it unchanged.
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:366
# verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:726
def launch_worker(
    argv: Sequence[str], *, cwd: Path | None = None,
    initial_prompt: str | None = None, base_env: Mapping[str, str] | None = None,
) -> int:
    """Launch the worker; add notification context/hooks only for a marked tmux feature session."""
```

Load the new sibling helper by file path in the stdlib script path, following the
existing compatibility shim pattern. Configure after `_allocate_session_cache`
and before serializing settings. Notification setup failures must leave the worker
launch viable. Do not change `_await_worker_start` or sandbox socket permissions.

### Module 3: Completion instructions and operator documentation

**Modify:** `.claude/agents/sdd-worker.md`, its byte-identical packaged twin
`packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`, and
`docs/dev_loop/claude-native-sandbox.md`.
Depends on M1's complete mode and M2's exported variables.

**Interface skeleton (instruction protocol):** between successful Completion step 2
and step 3, invoke the quoted `--complete` command above, only in feature scope.
Do not create a receipt for failed pushes, blocked tasks, unfinished review, child
completion, interrupts or task-scoped JSON briefs. No Python public API is added.
Document automatic best-effort delivery, same-host desktop requirement, once per
launch behavior, and that CLI/pane remain open. Existing installations must update
their managed worker asset to obtain the completion instruction.

## 4. Test Specification

### Unit Tests

| Case | Expected behavior |
|---|---|
| Valid completed feature and explicit receipt | Exactly one notification attempt; CLI need not exit |
| Ordinary Stop, all tasks done but no receipt, partial task, blocked task | No notification |
| Wrong feature/root/UUID/HEAD, empty tasks, malformed/oversized JSON, symlink | Ignore safely |
| Concurrent or repeated Stop and repeated complete command | At most one attempt per launch |
| Background work reported in Stop | Defer without consuming claim |
| Missing notify-send, unavailable D-Bus, nonzero return, timeout | Exit 0, bounded wait, no loop |
| Shell metacharacters, markup, spaces in paths and slug | Literal safe argv and escaped body |
| Non-tmux launch or inherited notification variables | No notification setup |
| New pane on an existing tmux server | Uses current captured desktop values, no loaded `.env` values |
| Setup alongside existing hooks, all sandbox modes | Additive settings; sandbox policies unchanged |
| Reattach to live or dead session | No new context or duplicate notification |

### Integration Tests

Run the installed helper under `python -S` with a temporary feature index and a
fake `notify-send` executable recording argv. Record completion and feed Stop while
a fixture CLI process remains alive; verify one call and unchanged process lifetime.
No real Claude API or desktop is required. Repeat with a stale receipt and fresh
launch UUID. Launcher tests inspect actual compiled settings and environment via
the existing exec/subprocess seams. Test the source and shipped worker instructions
for placement after push and exclusion from task-scoped completion.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_worker_notification.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
markers: none

The first operand is created by M1; the other operands already exist. Also run
`python scripts/sdd/check_asset_sync.py --check` from the activated environment.
Store logs under `artifacts/logs/`. A real desktop smoke check is optional and must
not replace deterministic tests.

## 5. Acceptance Criteria

- [ ] A launched tmux worker sends one completion notification after its SDD work
  finishes, without closing Claude Code or waiting for process exit.
- [ ] Notification identifies feature and worktree; ordinary pauses, child results,
  partial progress and failed pushes do not announce completion.
- [ ] Repeated Stop events and reattach do not duplicate delivery.
- [ ] Missing desktop services and helper failures never block or fail the worker.
- [ ] Existing startup detection, failed-pane retention and sandbox policy remain intact.
- [ ] Captured desktop environment works with an existing tmux server and excludes
  project-loaded secrets; shell and markup input tests pass.
- [ ] Both source and installed worker instructions emit the explicit receipt only
  after the existing feature completion sequence.
- [ ] Validation contract, asset parity and documentation checks pass.

## 6. Codebase Contract

Verified against base commit `2de4a3b977791e2068078206b8cd549754b9baee`
(the FEAT-793 reservation commit; launcher code unchanged from the prior check).

### Verified Imports

```python
from parrot.flows.dev_loop import feature_launcher as launcher
# verified: packages/ai-parrot/tests/sdd/test_sdd_launch.py:15
```

### Existing Class Signatures

All source references below use
`packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`.

```python
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:29
@dataclass(frozen=True)
class FeatureRef:
    feature_id: str
    slug: str
    spec: str
    index: str

# verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:366
def launch(
    key: str,
    *,
    tmux: bool,
    detach: bool,
    sandbox: str | None,
    allowed_domains: Sequence[str],
    no_upstream: bool,
    claude_args: Sequence[str],
    base_env: Mapping[str, str] | None = None,
) -> int:
    """Prepare and launch or attach to the worker for one feature."""

# verified: packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:481
def main(argv: Sequence[str] | None = None) -> int:
    """Parse the tmux child mode and launch Claude from its prepared worktree."""
```

### Integration Points

| Component | Existing behavior | Verified at |
|---|---|---|
| CLI dispatch | Captures environment before importing flows and invokes `feature_launcher.launch` | `packages/ai-parrot/src/parrot/sdd/launch_cli.py:40` |
| Existing session | Attaches or returns a detach hint before provisioning another worker | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:393` |
| New pane | Runs launcher script under `python -S` with explicit worktree | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:419` |
| Exit retention | Sets window `remain-on-exit failed` in the creation command queue | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:439` |
| Startup observation | Polls pane death or transition away from a Python process | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:318` |
| Environment | Explicit tmux assignments currently include `PARROT_SDD_*`, `PATH`, `VIRTUAL_ENV` | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:357` |

### Does NOT Exist (Anti-Hallucination)

- The launcher has no `notify-send` invocation or `pane-died` / `pane-exited` hook.
- There is no worker-completion callback in `launch()`; returning from detached
  launch reports startup, not SDD completion.
- `notify-send` is an external host command, not a tmux subcommand.

### Additional Verified Anchors

| Contract | Verified at |
|---|---|
| Native implementation lives in packaged SDD scripts; flow module is a stdlib-compatible shim | `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py:1` |
| Compiled settings already contain PreToolUse hooks | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:385` |
| Cache allocation creates a UUID directory with owner PID and cleans dead owners | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:700` |
| Launch writes CACHE_DIR_ENV before settings serialization and exec | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:788` |
| Feature completion pushes before summary | `.claude/agents/sdd-worker.md:708` |
| Shipped twin has identical push/summary sequence | `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:708` |
| Existing completed index uses task status done | `sdd/tasks/index/composite-datasets.json:17` |
| Worker asset is already shipped; no manifest entry needed | `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json:341` |

### Edit Sites (Blueprint Anchors)

Counts verified with `grep -Fc`; CREATE rows have no existing anchor.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_worker_notification.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `def launch(` | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:366` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `def launch_worker(` | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:726` | 1 |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | `def test_tmux_new_session_carries_environment_and_detaches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` | `packages/ai-parrot/tests/sdd/test_sdd_launch.py:142` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | `def test_launch_worker_uses_requested_cwd_and_final_prompt(` | `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py:330` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | `3. **Print summary:**` | `.claude/agents/sdd-worker.md:713` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | `3. **Print summary:**` | `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:713` | 1 |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | `## Supported launch paths` | `docs/dev_loop/claude-native-sandbox.md:24` | 1 |

## 7. Implementation Notes & Constraints

### Patterns to Follow

Keep script execution stdlib-only; Python functions require type hints and Google-style
docstrings. Use a module logger for new diagnostics. Preserve literal argv boundaries
and all existing security settings. The existing post-worker formatter hook is independent;
do not depend on its ordering or use it as a completion detector.

### Known Risks / Gotchas

- Completion is explicitly signaled by the worker protocol. If the agent omits that
  instruction, no success notification occurs; never infer success from silence.
- A Stop hook may run alongside a formatter that changes HEAD. A stale receipt safely
  suppresses delivery; it must not imply those extra edits were reviewed or pushed.
- Desktop delivery is best effort, local to the host; SSH, headless Linux, macOS and
  WSL without a notification service may produce no popup. No fallback platform is added.
- Claim-before-send guarantees at-most-once attempts, not guaranteed delivery. A crash
  between claim and send loses the popup; preventing duplicate alerts takes priority.
- Native scripts can run without `parrot` importability. Verify `python -S` rather than
  assuming package imports work in that child.

### External Dependencies

| Dependency | Version | Reason |
|---|---|---|
| Python stdlib | Existing project runtime | Receipt, atomic filesystem operations, subprocess |
| Claude Code Stop hook | Installed CLI; qualify against documented Stop schema | Turn-boundary delivery |
| Host `notify-send` | Optional installed executable | Desktop notification; never installed by this feature |
| tmux | Existing launcher prerequisite | Worker hosting only |

## Worktree Strategy

Isolation: **per-spec**, one FEAT-793 feature worktree with task sub-worktrees.
Graph: M2 → M1 (`configure_notification`); M3 → M1/M2 (complete command and exported
environment). No shared modified files between modules. No new lockfiles, migrations,
extension builds or shared runtime resources. Cross-feature dependencies: none.
Do not regenerate unrelated installed assets; synchronize only the declared worker twin.

## 8. Open Questions

- [x] Trigger — resolved by Jesus Lara: "clarification is when SDD work completes
  while the Claude Code CLI remains open".
- No unresolved product-design blockers. Target version remains the next release.

## 9. Design Research Cross-Check

Status: skipped (direct request with notes; no accepted brainstorm/proposal or
completed intake, so the optional independent research precondition is absent).

### Decision-audit validation status

Governing-decision retrieval first returned `SNAPSHOT_UNSTABLE`; bounded retries
timed out. Consequence rendering also timed out after 45 seconds (exit 124).
The read-only consequence check must pass before approval; this document remains
**draft** and does not claim governing-decision compliance. Re-run
`wikitoolkit spec governing sdd/specs/tmux-notify-worker.spec.md`, then
`parrot sdd spec consequences sdd/specs/tmux-notify-worker.spec.md --render` and
the same consequence command without `--render` once the audit service responds.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-03 | Codex | Completion receipt and Stop delivery design; user trigger clarification incorporated |
