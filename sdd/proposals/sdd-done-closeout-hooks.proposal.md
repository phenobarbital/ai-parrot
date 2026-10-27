---
id: FEAT-764
id_status: provisional   # not reserved; /sdd-spec reserves via reserve_ids.py
title: Configurable closeout hooks for /sdd-done (event → subscribed actions)
type: feature
mode: enrichment
status: review
base_branch: dev
source: inline
confidence: medium
research_state: sdd/state/FEAT-764/
projects: [sdd, e2e]
tags: [sdd-done, hooks, e2e, closeout, notifications, portability]
---

# Proposal: `/sdd-done` closeout hooks

## 0. Origin

The question: can `/sdd-done` run more tests, and other operations, after its
final checks and before it opens the PR? The user named these use cases:

- E2E runs in consumer repos such as `navigator-frontend-next` (TS + Svelte):
  parrot-browsing plus a pre-built plan, with screenshots and screencasts as evidence.
- Side effects such as closing a Jira ticket or sending a Telegram or push notification.

`/sdd-done` is generic: the SDD installer puts it into each repo. So the
configuration must live in the repo, either in a section of `CLAUDE.md` or in a
file under `.parrot/`. The model is an **event** that **methods** subscribe to.

## 1. Synthesis Summary

Yes, this is feasible. Most of the pieces already exist:

- `/sdd-done` already has a fixed pipeline: E2E gate (4.6), test report (4.7),
  verification report (5), push (8), PR or merge (9.2), Jira (10) and cleanup (11). [F001]
- `.parrot/test_runners.toml` is already the per-repo extension point for test
  runners. It has a `[extensions] kind = "module:Class"` slot that the vendored
  kernels also read. [F002]
- E2E has a code-enforced gate script plus exploratory `e2e-*` subagents.
  Screencasts are coming in FEAT-762. [F003]
- The workflow ships to other repos through the FEAT-633 installer. [F004]

What's missing is a declarative **lifecycle-hook registry** and **one
code-enforced dispatcher** that `/sdd-done` calls at named points. Jira, the
only side effect that exists today, is hardcoded at Step 10.

## 2. Codebase Findings

### 2.1 Localization
| Path | Role | Evidence |
|---|---|---|
| `.claude/commands/sdd-done.md` §4.6–§11 (+ twin `.agents/skills/sdd-done/SKILL.md`) | where the hook points go | F001 |
| `.parrot/test_runners.toml` | precedent for config format and location (TOML in `.parrot/`) | F002 |
| `scripts/sdd/check_e2e_closeout.py` | precedent for "the gate is code, the exit code is the contract" | F003 |
| `parrot/knowledge/wiki/claude_code/assets.py` | installer asset list (a new script or template must ship here) | F004 |

### 2.2 Constraints
- The hook logic should be **code, not prose**. Following FEAT-703, the
  dispatcher is a script and the exit code is the contract. Instructions alone
  can't reliably enforce an LLM-driven command.
- Both twins (Claude and Codex) must call the same script.
- A blocking hook must never be bypassable by a generic `--force`. This mirrors
  the rule for the E2E gate (AC9).
- Exploratory `e2e-*` runs never count as gate evidence (FEAT-581 M8). Agent
  hooks can attach artifacts but can't satisfy a gate unless they produce
  `parrot e2e verify` evidence.
- Secrets (Telegram token, Jira credentials) come only from the environment or
  navconfig, never from the config file.

## 3. Scope / Hypothesis

**New config: `.parrot/sdd_hooks.toml`.** I prefer this over a `CLAUDE.md`
section. A script can parse it deterministically, both hosts can use it, and it
matches `test_runners.toml`.

```toml
[[hooks.pre_pr]]                # after Step 5/6 confirm, before Step 8 push
name = "frontend-e2e"
kind = "agent"                  # command | agent | builtin
agent = "e2e-ui-tester"
prompt = "Run plan e2e/plans/checkout.yaml against FEAT {feat_id}; save screencast"
blocking = true                 # failure aborts closeout (not --force-able)
timeout_s = 1200
artifacts = "sdd/state/{feat_id}/e2e-artifacts/**"   # attached/linked in PR body

[[hooks.pre_pr]]
name = "playwright"
kind = "command"
run = "pnpm exec playwright test --reporter=json"
blocking = true

[[hooks.post_pr]]               # after Step 9.2 (PR URL known)
name = "jira"
kind = "builtin"
builtin = "jira.transition"     # replaces/absorbs --resolve-jira
with = { status = "In Review" }

[[hooks.post_pr]]
name = "notify"
kind = "builtin"
builtin = "telegram.send"       # or push.send / shell
blocking = false                # side effects never block
```

**Events** (initial set): `pre_pr` (gating tests), `post_pr` (side effects,
with `{pr_url}` available), and `on_failure` (notify on abort). `post_cleanup`
is optional.

**Dispatcher:** `scripts/sdd/run_closeout_hooks.py --event <e> --feat-id ...`.

- Runs `command` and `builtin` hooks directly.
- Each hook receives a JSON context: feat_id, spec, branch, worktree, pr_url,
  and a test-report path.
- Writes `sdd/state/<FEAT>/hooks/<event>.json` and exits non-zero only when a
  blocking hook fails.
- Also writes an artifact manifest for the PR body (`## Evidence`).
- **`agent` hooks can't run inside a Python script.** The dispatcher prints a
  dispatch plan, the host command launches the subagent, and the host then
  records the result with `--record`. This is the same split as the
  sdd-coder native seat.

Out of scope: a general event bus. FEAT-710 / navigator-eventbus could become
a later `builtin = "eventbus.emit"` target.

## 4. Confidence Map
- ✓ [high] The insertion points and the `.parrot/` config precedent exist (F001, F002).
- ✓ [high] Both twins and the installer must be updated (F001, F004).
- ◐ [medium] The record-back protocol for agent hooks is workable but adds a round trip.
- ✓ [high] Artifacts go to /tmp, never committed (U3).

## 5. Open Questions (resolved 2026-10-28)
- [x] U1: Config lives ONLY in `.parrot/sdd_hooks.toml` (more control); no CLAUDE.md section.
- [x] U2: Hard cut: remove `--resolve-jira`; Jira becomes an opt-in `post_pr` builtin (`jira.transition`) that checks whether the spec has a linked Jira key and skips with a note if not.
- [x] U3: Artifacts are NEVER committed. They are written under `/tmp` (e.g. `/tmp/claude-<uid>/sdd-hooks/<FEAT>/`), the same way Claude/Codex handle other artifacts today, and their paths/URLs are listed in the PR `## Evidence` section and the Step 12 output. Keeping them is the operator's job.
- [x] U4: `pre_pr` hooks DO run under `--dry-run` (side-effect `post_pr` hooks do not).
- [x] U5: `/sdd-brief` hotfix closeouts are out of scope → follow-up.

## 6. Recommended Next Step
`/sdd-spec FEAT-764` All unknowns are resolved.

## 7. Research Audit
State: `sdd/state/FEAT-764/` (findings F001–F004). Tight budget: sequential, not truncated.
