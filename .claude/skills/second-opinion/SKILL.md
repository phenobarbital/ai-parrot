---
name: second-opinion
description: Get an adversarial second opinion from the external `codex` CLI — code reviews (uncommitted, vs a base branch, or a commit), design opinions, brainstorming, research cross-checks, follow-ups, and image mockups/wireframes. Use when asked for a second opinion, an external/adversarial review, or a codex cross-check.
---

# Second opinion with `codex`

The rules for using an external reviewer live in `CLAUDE.md` § Adversarial
Second Opinion and always apply. In short: give the reviewer only the diff,
the requirement and the question (never your reasoning or preferred
conclusion); triage every substantive finding as `CONFIRM` / `REJECT` (with
reason) / `ESCALATE`; run each call as a background session; spot-check any
evidence it claims (test runs, files, symbols) before believing it.

**`agy` MUST NOT be used as a reviewer** — not even as a fallback when
`codex` is missing. With no external reviewer, say so and use a Claude
subagent instead.

## Detection

```bash
if command -v codex &>/dev/null; then REVIEWER="codex"
else echo "No external reviewer CLI found"; fi
```

## codex commands

```bash
# Reviews
codex exec review --uncommitted
codex exec review --base dev
codex exec review --commit <sha>

# Opinions, brainstorming, and cross-checks
codex exec --sandbox read-only -o <scratch-file> "<neutral brief>"

# Follow-up in the same Codex session
codex exec resume --last "<question>"

# Image generation / mockups / wireframes (codex-only)
codex exec --sandbox workspace-write -o <out.txt> \
  "Generate an image: <description>. Save as <name>.png"
```

Design research at spec time (FEAT-545) uses the same seat with its own
model and flags — see `/sdd-spec` §3b; do not improvise it from here.
