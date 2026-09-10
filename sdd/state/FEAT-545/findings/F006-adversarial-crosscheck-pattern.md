---
id: F006
query_id: Q007
type: read
intent: code-reviewer agent + sdd-codereview + CLAUDE.md: the Adversarial Cross-Check pattern the request wants to mirror
executed_at: 2026-09-10T01:00:00Z
duration_ms: 1100
parent_id: null
depth: 0
---

# F006 — The Adversarial Cross-Check is prose policy in three places, with five reusable rules

## Summary

The pattern the source calls "Adversarial Code Review we implemented on code-reviewer (using Codex)" lives as prose in `.claude/agents/code-reviewer.md` §Adversarial Cross-Check (119-194), `.claude/commands/sdd-codereview.md` §4 (64-120) and `CLAUDE.md` §Adversarial Second Opinion (124-175). All three share the same five rules: (1) neutral brief only — never feed the reviewer your reasoning; (2) background session, 30 s–2 min, never per-edit or from hooks; (3) advisory output triaged CONFIRM / REJECT / ESCALATE; (4) never silently concede or drop; (5) verify the reviewer's evidence, treat unverifiable claims as no finding. They also share the agy ban and the `codex exec --sandbox read-only -o <file> "<brief>"` invocation for design opinions. A design-research phase can reuse these rules verbatim — only the *brief contents* and the *question* change.

## Citations

- path: `.claude/agents/code-reviewer.md`
  lines: 134-150
  symbol: Adversarial Cross-Check → Key Rules
  excerpt: |
    - **Never feed the reviewer your reasoning or draft review.** Give it only
      the diff/commit, the requirement/acceptance criteria, and a neutral review question.
    - **Run the reviewer as a background agent session** — each call takes 30 seconds to 2 minutes.
    - **Treat reviewer output as advisory.** ... CONFIRM / REJECT / ESCALATE
    - **Verify the reviewer's evidence.**

- path: `.claude/agents/code-reviewer.md`
  lines: 159-177
  symbol: codex commands
  excerpt: |
    # Design opinion or cross-check with output file
    codex exec --sandbox read-only -o artifacts/reviews/<task>-codex.txt \
      "<neutral brief: task context, acceptance criteria, changed files, question>"
    # Follow-up in the same Codex session
    codex exec resume --last "<neutral follow-up question>"

- path: `.claude/agents/code-reviewer.md`
  lines: 185-194
  symbol: Reporting Cross-Check Results
  excerpt: |
    ## Adversarial Cross-Check
    | Finding | Disposition | Reason |
    | <Reviewer finding> | CONFIRM / REJECT / ESCALATE | <why> |

- path: `.claude/agents/code-reviewer.md`
  lines: 125-132
  symbol: agy ban
  excerpt: |
    > **`agy` (Google Gemini / Antigravity) MUST NOT be used as a reviewer.**
    > ... with no external reviewer available, say so and rely on a Claude subagent.

- path: `.claude/commands/sdd-codereview.md`
  lines: 64-120
  symbol: §4 Run Adversarial Cross-Check
  excerpt: |
    Use an external CLI agent as an independent second-opinion reviewer. The
    reviewer is **`codex` (OpenAI)**.

- path: `CLAUDE.md`
  lines: 124-175
  symbol: Adversarial Second Opinion
  excerpt: |
    ### Adversarial Second Opinion
    - Never feed the reviewer your reasoning, justification, or preferred conclusion.
    codex exec --sandbox read-only -o <scratch-file> "<neutral brief>"

- path: `.claude/agents/code-review.md`
  lines: 20-61
  symbol: second-opinion tool rules (third copy)
