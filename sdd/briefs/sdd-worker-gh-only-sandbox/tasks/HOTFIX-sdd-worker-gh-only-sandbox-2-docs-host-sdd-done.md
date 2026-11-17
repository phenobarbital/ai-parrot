# HOTFIX-sdd-worker-gh-only-sandbox-2: Document gh-only GitHub access and host-side /sdd-done

**Feature**: sdd-worker-gh-only-sandbox — GitHub only through `gh`, config-driven allowed domains
**Spec**: `sdd/briefs/sdd-worker-gh-only-sandbox.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-sdd-worker-gh-only-sandbox-1
**Assigned-to**: unassigned

---

## Context

After task 1 the sandboxed sdd-worker can use `gh` (`api.github.com` + host-resolved `GH_TOKEN`)
but can never `git push` (needs `github.com`/SSH, blocked by design). The operator explicitly wants
it documented that **`/sdd-done` must run on the host, outside the sdd-worker session** — before
FEAT-633 it was run from inside the worker. Today the instructions still say the opposite
(`.claude/agents/sdd-worker.md:64`, `:713` `git push origin HEAD`, `:752` "it may run from inside
this worktree").

## Scope

- `docs/dev_loop/claude-native-sandbox.md`:
  - **Network** (around line 131-140): default no egress; `[tool.parrot.sdd]`
    `sandbox_allowed_domains` / `gh_token` read from the primary checkout only (and why: the worktree
    pyproject is session-writable); union with `--sandbox-allow-domain`; `--no-gh-token`.
    Policy: GitHub only through `gh` via `api.github.com`; `github.com`, git-over-HTTPS and SSH stay
    blocked. Replace the line "HTTPS Git and `gh` need `github.com` and `api.github.com`" accordingly.
    Explain `GH_TOKEN`: gh's keyring is a D-Bus Unix socket, blocked by `allowAllUnixSockets: false`,
    so the launcher runs `gh auth token` on the host; missing token → WARNING, launch continues.
    Warn that the token is visible to the agent with gh's full scopes (every repo the account can
    reach) — operators who want less should log `gh` in with a narrower token or pass `--no-gh-token`.
  - **Git inside a native session** (line 140+): the session commits but never pushes; push, PR and
    cleanup happen through `/sdd-done` **run on the host** (a normal shell / Claude session in the
    primary checkout or worktree, not the sandboxed sdd-worker). Note that pre-FEAT-633 practice of
    running `/sdd-done` inside the worker no longer works. Drop the "session pushes with
    `git push origin <branch>`" step.
  - Add the probe gotcha: manual reproduction needs the launcher env
    (`PARROT_SDD_SANDBOX_BACKEND=claude-native`), otherwise the hook's nested bwrap fails with
    `No permissions to create new namespace`.
- sdd-worker instructions — `.claude/agents/sdd-worker.md` and
  `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (identical edits; the two
  differ only in the hook command path, keep that):
  - line ~64: `.claude/worktrees/` stays writable for worktree administration, but do not claim
    `/sdd-done` runs from here.
  - "Push the feature branch" step (~line 711-714): replace with "Do NOT push — the sandbox has no
    route to github.com; `/sdd-done` on the host pushes." Keep the step numbering coherent.
  - summary "Next:" block (~line 751-754): "Run /sdd-done FEAT-<ID> **from the host** (outside this
    sdd-worker session) — it pushes, opens the PR and cleans up."
  - Add one line: `gh` (api.github.com) is available for read/PR-comment operations; never try
    `git push`, SSH, or ask to widen the sandbox.
- Codex twins `.codex/agents/sdd-worker.toml` and `_assets/codex/agents/sdd-worker.toml`
  (identical edits): "Push:" section (~line 141-143) → no push; operator runs `$sdd-done` on the host.
  Also adjust the `description` ("…runs adversarial review before pushing.").
- sdd-done command/skill, all six copies (`.claude/commands/sdd-done.md`,
  `.agents/skills/sdd-done/SKILL.md`, `.agent/workflows/sdd-done.md` and their `_assets/…` twins):
  add a short note near the top: run on the host, not from inside a sandboxed sdd-worker session
  (push needs github.com). Keep each twin pair byte-identical where it already is.
- `CLAUDE.md` "Autonomous Agent (`sdd-worker`)" section and `docs/sdd/WORKFLOW.md` step 10: one
  sentence each — the worker commits but does not push; run `/sdd-done` from the host.

**NOT in scope**: code changes (task 1); installer asset-sync logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | Network + Git sections |
| `.claude/agents/sdd-worker.md` | MODIFY | no push; host-side /sdd-done; gh allowed |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | twin |
| `.codex/agents/sdd-worker.toml` | MODIFY | no push |
| `packages/ai-parrot/src/parrot/sdd/_assets/codex/agents/sdd-worker.toml` | MODIFY | twin |
| `.claude/commands/sdd-done.md` | MODIFY | host-only note |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` | MODIFY | twin |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | host-only note |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md` | MODIFY | twin |
| `.agent/workflows/sdd-done.md` | MODIFY | host-only note |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md` | MODIFY | twin |
| `CLAUDE.md` | MODIFY | Autonomous Agent sentence |
| `docs/sdd/WORKFLOW.md` | MODIFY | step 10 sentence |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev, 2026-11-03)
```
.claude/agents/sdd-worker.md:64    exceptions outside your worktree: the first exists so `/sdd-done` can run from here
.claude/agents/sdd-worker.md:713   git push origin HEAD
.claude/agents/sdd-worker.md:752   - Run /sdd-done FEAT-<ID> for verification, PR, and cleanup
.codex/agents/sdd-worker.toml:141  Push:
docs/dev_loop/claude-native-sandbox.md:137  - HTTPS Git and `gh` need `github.com` and `api.github.com`. Raw SSH is not supported in v1.
docs/dev_loop/claude-native-sandbox.md:142  1. The **host** sets the upstream before launch (...)
docs/sdd/WORKFLOW.md:92            10. **Finish the feature** with `/sdd-done FEAT-<NNN>`
```

### Does NOT Exist
- No `parrot sdd run …` or `devloop launch-worker` spellings may be introduced
  (`tests/sdd/test_no_repo_script_refs.py` forbids them).

---

## Acceptance Criteria

- [ ] Every sdd-worker copy tells the worker not to push and to hand off `/sdd-done` to the host.
- [ ] Every sdd-done copy says it runs on the host, not inside a sandboxed sdd-worker.
- [ ] The sandbox doc describes the config keys, gh-only policy, GH_TOKEN/keyring reason, token-scope warning.
- [ ] Twin pairs stay identical except the pre-existing hook-path difference in sdd-worker.md.
- [ ] `test_no_repo_script_refs.py` and installer tests pass.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

## Agent Instructions

Read the brief first. Documentation and instruction text only; commit only the listed files.

## Completion Note

Implemented by the sdd-worker itself (sequential fallback; `coder_plan` could not route `HOTFIX-…` task ids,
see task 1). All 13 listed files edited, nothing else touched. Twin pairs received identical edits (the
sdd-worker.md pair still differs only in the pre-existing hook path). Choices beyond the task text:
`.agent/workflows/sdd-done.md` already said "NOT inside a worktree", so it got an added host-only paragraph
rather than a replacement; the Codex `Push:` section now says "Do not run sdd-done yourself" unconditionally.
Validation: `test_installer.py` + `test_no_repo_script_refs.py`: 76 passed, 1 failed —
`test_no_c29_findings_in_shipped_files` flags `.claude/agents/sdd-worker.md:335` (bare `python -c` uuid guidance),
a line this task did not touch; pre-existing on dev. Filed as `issue:6480940ab36a`, not fixed (out of scope).

