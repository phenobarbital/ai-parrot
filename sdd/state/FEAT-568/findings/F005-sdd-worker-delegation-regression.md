# F005 — FEAT-549's rewrite of `sdd-worker.md` silently dropped FEAT-543's Delegation step

**Query**: Q007/Q009 (test_sdd_contracts.py, git history of sdd-worker.md)
**Confidence**: high

## Evidence

- `packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py`
  (TASK-3090, FEAT-543) asserts, among other things, that
  `.claude/agents/sdd-worker.md` (`WORKER` constant) contains:
  - `test_sdd_worker_has_the_delegated_step_and_checklist_line`: the literal
    heading `### b2) Delegated implementation`, the checklist line `□
    Delegated patch hunks were all reviewed before writer_apply?`, and that
    it sits between `### b) Verify Codebase Contract` and `### c)
    Implement`.
  - `test_documents_state_that_sdd_files_are_never_delegated[worker]`:
    `"never edited by the writer"` or `"never delegated"`.
  - `test_documents_forbid_substituting_another_coder[worker]`: `"never
    silently invokes another coder"`.
  - `test_review_happens_before_apply[sdd-worker]`: `writer_generate` before
    `source_read` before `writer_apply`, plus "not fully read"/"fully read"
    and "never runs tests".
- CI evidence (`test-tool-optimizations`, Python 3.11, this run): exactly
  these 4 parametrized cases fail — `[sdd-worker]`/`[worker]` only. The
  `[claude-command]` (`.claude/commands/sdd-start.md`) and `[codex-skill]`
  (`.agents/skills/sdd-start/SKILL.md`) variants of the SAME assertions
  **pass** — 418 passed / 4 failed overall.
- `git log --oneline -- .claude/agents/sdd-worker.md`: commit `461b74c2e`
  (`feat(tool-optimizations): TASK-3090 …`) added the `### b2) Delegated
  implementation` section (25 lines) between step b) and step c), plus the
  checklist line, on 2026-09-10.
- `git show 26de90a91 -- .claude/agents/sdd-worker.md` (`feat(sdd-worker-
  subagents): TASK-3124 — sdd-worker.md Orchestrator Loop`, the commit that
  introduced today's Orchestrator Loop / Fallback: Sequential Loop
  structure): the diff **removes** the entire `### b2) Delegated
  implementation` block (`-### b2) Delegated implementation ...`) without
  adding it back anywhere else in the file.
- Current `.claude/agents/sdd-worker.md`: `grep -n "writer_generate|
  writer_apply|source_read|never silently invokes another coder|never
  edited by the writer|Delegation Contract|never delegated"` → **zero
  matches**. The capability described by FEAT-543/TASK-3090 (delegate patch
  *drafting* to a cheaper `parrot-targeted-writer` MCP tool, but always
  review every hunk and never let SDD-state files or tests be touched by
  it) is completely absent from the autonomous worker today.
- The underlying feature is very much alive, not superseded: `parrot_tools`
  ships a real, tested `TargetedWriterToolkit`
  (`packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py`, ~30
  tests), `benchmarks/tool_optimizations/` measures it, and
  `.claude/commands/sdd-start.md` + `.agents/skills/sdd-start/SKILL.md`
  still fully document it. FEAT-549's Orchestrator Loop dispatches whole
  separate `sdd-coder` sub-agents per *task*; FEAT-543's delegation is a
  narrower, complementary optimization *within* one task's own
  implementation step — the two are not mutually exclusive, and the
  Fallback: Sequential Loop's lettered steps (a→h) are structurally
  identical to where b2 used to sit.

## Conclusion

This is a **documentation regression**, not a stale/invalid test: the test
enforces a real behavioral contract (review-before-apply ordering, never
delegate SDD-state edits, never silently substitute another coder) that the
sibling host docs still honor. The correct fix is to reinsert the `### b2)
Delegated implementation` section (and its checklist line) into
`.claude/agents/sdd-worker.md`'s "Fallback: Sequential Loop", between steps
b) and c), content-equivalent to what TASK-3090 originally added — updating
any step-number cross-references to match the current heading structure.
Zero test weakening; this restores dropped capability.

## Correction (implementation pass, 2026-09-16)

The conclusion above is right — this was a documentation regression, and the
section is now restored on `dev`. Two facts the original evidence pass missed,
recorded so the next reader does not re-derive them:

1. **TASK-3124 did not merely drop the section; it asserted the drop.**
   `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py`
   (added by that same commit, `26de90a91`) asserts `"### b2)"`,
   `"writer_apply"`, `"parrot-targeted-writer"` and `"Delegation Contract"` are
   ABSENT from the prompt body, and `test_worker_prompt_has_orchestrator_loop`
   asserts the same for `"writer_generate"`. A verbatim restore alone turns the
   4 `test-tool-optimizations` failures into 5 `test-core` failures. The
   restoration therefore also narrowed those absence assertions from the whole
   body to the `## Orchestrator Loop (FEAT-549)` section — which is what they
   are really about: the dispatch path uses `sdd-coder` seats, never the writer
   route, while the Fallback loop (where the agent implements a task itself) is
   exactly where `### b2)` belongs. `test_sdd_contracts.py` was not modified.

2. **The prompt is dual-sourced.** `.claude/agents/sdd-worker.md` must stay
   byte-identical to `packages/ai-parrot/src/parrot/flows/dev_loop/
   _subagent_data/sdd-worker.md` (`test_subagent_parity.py`, FEAT-377), so the
   section was restored in both copies.

See `sdd/specs/ci-test-failures-root-cause-remediation.spec.md` §3 Module 4,
"Correction (implementation pass)".
