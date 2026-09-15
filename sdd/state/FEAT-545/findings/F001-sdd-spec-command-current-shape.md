---
id: F001
query_id: Q003
type: read
intent: Current /sdd-spec command: guardrails, phases, where a research phase would slot in
executed_at: 2026-09-10T01:00:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F001 — /sdd-spec today: design-only guardrail, brainstorm carry-forward, no external seat

## Summary

`/sdd-spec` is a 431-line command with a hard guardrail that forbids implementation code in the spec (line 17). Its phases are: §1 parse → §2 carry forward brainstorm/proposal (§2a mapping table, §2b resolved-question rules, §2c summary, §2d flow/branch resolution) → §3 clarifying questions → §4 codebase research + Codebase Contract → §5 scaffold → §6 commit → §7 output. No step consults an external model; the word "codex" does not appear in the file (Q008 grep returned no match in sdd-spec.md). The natural insertion point for a collaborative design-research phase is between §2c (carry-forward summary) and §4 (codebase contract), so its output can feed both §2 Architectural Design and §6 Codebase Contract.

## Citations

- path: `.claude/commands/sdd-spec.md`
  lines: 15-31
  symbol: Guardrails
  excerpt: |
    - Always use the official template at `sdd/templates/spec.md`.
    - Do NOT write implementation code in the spec — specs are design documents.
    - If a `.brainstorm.md` exists for this feature in `sdd/proposals/`, use it as input.
    - **NEVER re-ask a question that the brainstorm already answered.**
    - **Always commit the spec file to the current branch** so worktrees can see it.

- path: `.claude/commands/sdd-spec.md`
  lines: 39-73
  symbol: §2a brainstorm→spec mapping table
  excerpt: |
    | Recommendation + Recommended Option body | §2 Architectural Design — Overview |
    | Code Context (entire section) | §6 Codebase Contract (re-verify every reference) |
    | Open Questions (see 2b) | §8 Open Questions (with resolved/unresolved state preserved) |

- path: `.claude/commands/sdd-spec.md`
  lines: 121-133
  symbol: §2c carry-forward summary
  excerpt: |
    Loaded brainstorm: sdd/proposals/<feature-name>.brainstorm.md
      Recommended Option: <X — name>
      Resolved questions carried forward (N): ...
    If K is zero, proceed directly to §4 without asking anything.

- path: `.claude/commands/sdd-spec.md`
  lines: 230-252
  symbol: §4 Research the Codebase & Build Codebase Contract
  excerpt: |
    2. **For every class/module referenced in the spec**: `read` the actual source file
       and record exact class signatures ... with file paths and line numbers.
    4. **Record what does NOT exist** ...
    5. **Include user-provided code**: ... preserve them as verified references in the contract.

- path: `.claude/commands/sdd-spec.md`
  lines: 353-377
  symbol: §6 Commit the Spec
  excerpt: |
    git reset HEAD
    git add sdd/specs/<feature-name>.spec.md
    git commit -m "sdd: add spec for FEAT-<ID> — <feature-name>"

- path: `.claude/commands/sdd-spec.md`
  lines: 424-431
  symbol: Anti-Hallucination Policy
  excerpt: |
    The `## 6. Codebase Contract` section in the spec is **mandatory** ...
    **Quality bar**: Every entry in the contract must include a file path and line number.

## Notes

The guardrail at line 17 is the direct tension point with change #1 of the source. Note §4 item 5 already admits *user-provided* code into the spec — the prohibition is on Claude authoring implementation code, not on code appearing in the document.
