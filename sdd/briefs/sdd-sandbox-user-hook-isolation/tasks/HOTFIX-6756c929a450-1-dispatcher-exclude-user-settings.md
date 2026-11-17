# HOTFIX-6756c929a450-1: Never load the user setting source in sandboxed dispatched seats

**Feature**: issue:6756c929a450 — SDD sandbox bypass: a competing PreToolUse updatedInput replaces the bwrap wrapper
**Spec**: `sdd/briefs/sdd-sandbox-user-hook-isolation.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The SDD sandbox hook wraps every Bash call in bwrap via `updatedInput`
(`worktree_environment.py:463`). Any other `PreToolUse` hook that also returns
`updatedInput` (RTK's global hook in `~/.claude/settings.json`) can replace it, because
Claude Code does not define which one wins. The dispatcher must therefore guarantee that
user-level settings never load in sandboxed seats.

Today `ClaudeCodeDispatcher._resolve_run_options` forwards
`setting_sources=list(profile.setting_sources) if profile.setting_sources else None`
(`dispatchers/claude.py:649`). An empty list becomes `None`; with `None` the SDK passes no
`--setting-sources` flag and the CLI loads its default sources, user included. A profile
can also list `"user"` explicitly (`models/claude.py:32`).

---

## Scope

- In `_resolve_run_options`, when `profile.subagent in {"sdd-worker", "sdd-coder"}` (the same
  set already gated at `dispatchers/claude.py:621` for the hook injection), compute the
  forwarded sources as `profile.setting_sources` with `"user"` removed; if the result is
  empty, use `["project"]`. The value forwarded for these subagents is never `None` and
  never contains `"user"`. Log a warning (`self.logger.warning`) when `"user"` was dropped.
- Keep behavior for every other subagent unchanged (byte-identical forwarding).
- Factor the set `{"sdd-worker", "sdd-coder"}` into one module-level constant
  (e.g. `_SANDBOXED_SUBAGENTS`) used by both the hook-injection branch and the new rule.
- Tests in `test_dispatcher.py`:
  - `sdd-worker` / `sdd-coder` with `setting_sources=[]` → forwarded `["project"]`.
  - with `["user", "project"]` → forwarded `["project"]`; with `["user"]` → `["project"]`;
    with `["project", "local"]` → unchanged.
  - non-sandboxed subagent (e.g. `sdd-qa`) with `[]` → still `None` (unchanged).
  - CLI-argv level: build the SDK command for a sandboxed profile with
    `setting_sources=[]` and assert `--setting-sources=project` is present and `user` is not
    in it. Use `claude_agent_sdk._internal.transport.subprocess_cli.SubprocessCLITransport`
    `_build_command()` if it can be constructed without spawning; otherwise assert on the
    `ClaudeAgentOptions` kwargs produced by `ClaudeAgentRunOptions` merging
    (`claude_agent.py:442`). Verify which is feasible before writing it.

**NOT in scope**:
- Interactive `claude --agent sdd-worker` launches (HOTFIX-6756c929a450-2).
- Changing `hook_response` / `worktree_environment.py`.
- The RTK rewrite inside bwrap (PR #1858).
- Changing the profile model's `Literal` or default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Enforce no-`user`, never-`None` setting sources for sandboxed subagents |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | Cases above |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile  # check the exact import used at the top of test_dispatcher.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
def _resolve_run_options(self, profile, cwd) ...        # line 554
if profile.subagent in {"sdd-worker", "sdd-coder"}:      # line 621 (hook injection)
setting_sources=list(profile.setting_sources) if profile.setting_sources else None,  # line 649

# packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py
setting_sources: List[Literal["user", "project", "local"]] = Field(default_factory=lambda: ["project"])  # line 32

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py
if merged.setting_sources is not None:                   # line 442
    kwargs["setting_sources"] = list(merged.setting_sources)

# claude_agent_sdk 0.2.168, _internal/transport/subprocess_cli.py
if effective_setting_sources is not None:                # line 729
    cmd.append(f"--setting-sources={','.join(effective_setting_sources)}")
```

Test fixtures already in `test_dispatcher.py`: `dispatcher`, `_patch_worktree_base`
(see `TestProfileResolution.test_dispatch_profile_to_run_options`, line ~132).

### Does NOT Exist
- No `_SANDBOXED_SUBAGENTS` constant yet (this task adds it).
- No existing test covering empty or `"user"` setting sources.

---

## Acceptance Criteria

- [ ] Sandboxed subagents never forward `None` or `"user"` setting sources.
- [ ] Non-sandboxed subagents forward exactly as before.
- [ ] A test proves the CLI command for a sandboxed seat carries `--setting-sources` without `user`.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -q`

## Agent Instructions

Read the brief first. Implement exactly the scope; commit code only.

## Completion Note

Verified. `_effective_setting_sources()` + `_SANDBOXED_SUBAGENTS` in `dispatchers/claude.py`:
sdd-worker/sdd-coder always forward an explicit list without `user` (empty → `["project"]`, warning
logged when `user` is dropped); other subagents unchanged. 12 new tests in `test_dispatcher.py`
(`TestSandboxedSettingSources`), including one that builds the real SDK CLI argv
(`SubprocessCLITransport._build_command()`, no process spawned) and asserts `--setting-sources=project`.
`test_dispatcher.py` + `test_models.py`: 64 passed. Ruff: 4 pre-existing B023 errors in the same file
(loop variable `usage`, present on origin/dev before this change), none from this task.
