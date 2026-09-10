---
id: F013
query_id: Q009
type: grep
intent: Which models execute which SDD stage, and how sdd-worker consumes a task file
executed_at: 2026-09-10T01:00:00Z
duration_ms: 700
parent_id: F002
depth: 1
---

# F013 — Executors are Sonnet by frontmatter; Haiku appears only on read-only commands and in the dev-loop catalog

## Summary

Grep for `haiku|sonnet|--model` across `.claude/agents` and `.claude/commands`: every implementing/reviewing agent (sdd-worker, sdd-planner, sdd-research, sdd-qa, code-reviewer, qa-runner, sdd-ideation, sdd-autopilot) is `model: sonnet`; `haiku` is set only on `sdd-done`, `sdd-status`, `sdd-next` (read-only commands). In Python, `claude-haiku-4-5` appears in the dev-loop model catalog (catalog.py:247, :351) as a selectable dev-agent model. sdd-worker consumes a task by reading the whole file, extracting files/classes/criteria, verifying the Codebase Contract, then implementing "EXACTLY as specified" — so richer executor-ready content in the task file is consumed directly with no code change.

## Citations

- path: `.claude/agents/sdd-worker.md`
  lines: 20
  excerpt: |
    model: sonnet

- path: `.claude/agents/sdd-worker.md`
  lines: 211-233
  symbol: Execution Loop a)–c)
  excerpt: |
    ### a) Read and Understand Task (in worktree)
    - Read the full task file.
    - Extract and print: Exact files to create / modify, Class/function names specified, Acceptance criteria
    ### b) Verify Codebase Contract (MANDATORY — Anti-Hallucination)
    ### c) Implement — EXACTLY as specified (in worktree)
    - Use ONLY the class names, method signatures, and patterns specified.

- path: `.claude/commands/sdd-done.md`
  lines: 2
  excerpt: |
    model: haiku
- path: `.claude/commands/sdd-status.md`
  lines: 2
  excerpt: |
    model: haiku
- path: `.claude/commands/sdd-next.md`
  lines: 2
  excerpt: |
    model: haiku

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py`
  lines: 247
  excerpt: |
    "claude-haiku-4-5",
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py`
  lines: 351
  excerpt: |
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",

- path: `.claude/commands/sdd-start.md`
  lines: 137-146
  symbol: Verify the Codebase Contract
  excerpt: |
    Before writing ANY code, verify every entry in the task's `## Codebase Contract`
    Use ONLY the imports and signatures from the verified Codebase Contract.
