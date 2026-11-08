---
id: F021
query_id: Q036
type: read
intent: "Read the sdd-done-closeout-hooks spec header: how hooks are declared, fail modes, and the extension contract."
executed_at: 2026-11-07T01:26:34Z
duration_ms: 1500
parent_id: null
depth: 0
merged_from: [FC-021]
---

# F021 — FEAT-764 (approved): .parrot/sdd_hooks.toml subscribes command/agent/builtin hooks to pre_pr/post_pr/on_failure; blocking pre_pr aborts and --force cannot bypass; both host twins call the same dispatcher

## Summary

`sdd/specs/sdd-done-closeout-hooks.spec.md` (FEAT-764, approved) defines the extension contract FC-009/FC-010 implement: G1 a per-repository declarative registry `.parrot/sdd_hooks.toml` subscribing hooks to `pre_pr`, `post_pr`, `on_failure`; G2 one code-enforced dispatcher both host twins (Claude command and Codex skill) call, "its exit code is the contract"; G3 three hook kinds (`command`, `agent` = host subagent dispatched by the host, `builtin`); G4 blocking `pre_pr` hooks abort before any stamp/push/PR and `--force` cannot bypass them; G5 artifacts never committed; absent TOML ⇒ no-op, malformed ⇒ exit 2 fail closed. Non-goal: configuring hooks via CLAUDE.md (TOML only). The integration table names exactly the two files any new /sdd-done gate must edit: `.claude/commands/sdd-done.md` and `.agents/skills/sdd-done/SKILL.md`.

## Citations

- path: `sdd/specs/sdd-done-closeout-hooks.spec.md`
  lines: 10-13
  symbol: null
  excerpt: |
    **Feature ID**: FEAT-764
    **Status**: approved

- path: `sdd/specs/sdd-done-closeout-hooks.spec.md`
  lines: 37-47
  symbol: null
  excerpt: |
    - G1. A per-repository, declarative registry, `.parrot/sdd_hooks.toml`, that
      subscribes **hooks** to named closeout **events** (`pre_pr`, `post_pr`, `on_failure`).
    - G2. One code-enforced dispatcher, `scripts/sdd/run_closeout_hooks.py`, that
      both host twins (Claude command and Codex skill) call. Its exit code is the
    - G4. `blocking` `pre_pr` hooks abort closeout before any stamp, push or PR,
      and `--force` cannot bypass them. `post_pr` / `on_failure` hooks never block.

- path: `sdd/specs/sdd-done-closeout-hooks.spec.md`
  lines: 85-87
  symbol: null
  excerpt: |
    1. It loads `.parrot/sdd_hooks.toml`. If the file is absent, it exits 0 with
       "no hooks". If the file is malformed, it exits 2 (fail closed; never a silent no-op).

- path: `sdd/specs/sdd-done-closeout-hooks.spec.md`
  lines: 92-96
  symbol: null
  excerpt: |
       - `agent`: cannot run in Python. The dispatcher marks it `pending` and puts a
         dispatch entry (agent name, rendered prompt, artifact dir) in the result
         JSON. The host launches the subagent and then records the outcome with
         `run_closeout_hooks --event <e> --record <hook-name> --status pass|fail

- path: `sdd/specs/sdd-done-closeout-hooks.spec.md`
  lines: 131-132
  symbol: null
  excerpt: |
    | `.claude/commands/sdd-done.md` | add 4.8, the post_pr step after 9.2, and on_failure wording on every abort; ... |
    | `.agents/skills/sdd-done/SKILL.md` | same, in its numbered list (steps 4.6→new 4.8, 12, 14 removed) |

## Notes

- Hooks are opt-in per repo (absent file ⇒ no-op). An escrow gate that must be enforced whenever a feature was launched with escrow enabled cannot rely solely on repo TOML; it needs a code-enforced gate like §4.6 that reads the feature's own escrow state.
