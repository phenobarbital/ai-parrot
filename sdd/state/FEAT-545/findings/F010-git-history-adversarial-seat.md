---
id: F010
query_id: Q010
type: git_log
intent: Recent history of spec/task commands, templates, reviewer agent, and the Codex seat
executed_at: 2026-09-10T01:00:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F010 — 8 commits in 90 days on the target files; the codex seat has churned (codex → agy-first → agy banned)

## Summary

The spec/task commands and templates changed 8 times in 90 days, all by the repo owner; the dominant themes are id-allocation safety (FEAT-387, 1be04d299 / 5507f2eef), flow-type plumbing (df74cebc7) and adversarial-reviewer policy (12290ef68 → 25c61d4dc agy-first → f32cb899e agy removed). Separately, dbd2cd740 (2026-09-03) removed `model: gpt-5.5` from the sdd-secondopinion agent because a Claude Code subagent cannot be pointed at an OpenAI model from its frontmatter — the Codex model must be selected on the codex CLI invocation, never on the Claude agent. `sdd/templates/spec.md` and `task.md` themselves have no commits in the window (stable targets).

## Citations

- path: `.claude/commands/sdd-spec.md`
  lines: 0
  symbol: git log --since=90.days
  excerpt: |
    1be04d299 2026-09-01 sdd: one feature id per slug — refuse a duplicate reservation
    f32cb899e 2026-09-01 chore: remove agy as an adversarial code-review option
    9e1ad0e3a 2026-08-29 fix(sdd): reserve_ids no longer destroys or publishes local commits
    df74cebc7 2026-08-27 feat(dev-loop-run-fidelity): TASK-2507 — SDD doc plumbing
    25c61d4dc 2026-08-21 chore: migrate adversarial review from codex to agy-first with codex fallback
    5507f2eef 2026-07-28 TASK-1966 — wire /sdd-task and /sdd-spec to reserve_ids.py
    0809cf395 2026-07-27 refactor(sdd): make commands/agents project-agnostic + code-review step
    12290ef68 2026-07-27 adversarial codex review in code-reviewer agent

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 0
  symbol: dbd2cd740
  excerpt: |
    fix(dev-loop): drop the unusable `model: gpt-5.5` from sdd-secondopinion
    A Claude Code subagent cannot be pointed at an OpenAI model from its frontmatter ...
    The adversarial seat's real model comes from CodexAdversarialReviewProfile.model
    ... and is passed to the codex CLI.
    Both twins are edited identically to keep the byte-parity that test_subagent_parity.py enforces.

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
  lines: 0
  symbol: FEAT-375 commits
  excerpt: |
    59ccb2e71 2026-07-26 TASK-1900 — sdd-secondopinion neutral subagent brief
    d7a8332da 2026-07-26 TASK-1902 — codex-adversarial + parallel review dispatchers
    df9f21053 2026-07-28 fix: prevent codex adversarial reviewer retry-spiral in read-only sandbox
