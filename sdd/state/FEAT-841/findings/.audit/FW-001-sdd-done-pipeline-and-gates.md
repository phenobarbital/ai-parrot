---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: how /sdd-done verifies a feature and what blocks the merge today (precedent for a code-enforced refusal)."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1200
parent_id: null
depth: 1
---

# FW-001 — /sdd-done is a fixed 12-step pipeline; its only code-enforced refusals are the E2E gate (4.6), closeout hooks (4.8/9.3) and ledger blockers (9, --merge only)

## Summary

Wiki top hits: `file:.agents/skills/sdd-done/SKILL.md` (1.00) and the shipped twin `file:packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` (0.87) of `.claude/commands/sdd-done.md` (Q008 page + Q013 related: the asset page has only a `contains` edge; the live command was pinned by one grep of headings). The command runs **on the host, on base_branch, never inside the sdd-worker sandbox**; it looks into the worktree for evidence. Steps: 1 base-branch · 2 resolve feature · 3 locate worktree · 4 evidence · 4.5 lint · **4.6 E2E gate (code, FEAT-703, never force-able)** · 4.6b docs · 4.7 test report · **4.8 closeout hooks pre_pr (FEAT-764)** · 5 report · 6 confirm · 7 stamp index · 8 push · **9 merge blockers (only with --merge; exit code of `wikitoolkit ledger blockers`; --force bypasses)** · 9.1 deliver ledger events via outbox · 9.2 PR/merge · 9.3 hooks post_pr · 11 cleanup. A verdict guard would be a new code-enforced step between 4.8 and 7 (before any mutation), modelled on 4.6 — not on 9, which is prose, force-able and runs only on --merge.

## Citations

- path: `.claude/commands/sdd-done.md`
  lines: 237-289
  symbol: `### 4.6. Verify E2E Evidence (FEAT-581)`
  excerpt: |
    GATE_JSON=$(parrot sdd tests e2e-closeout \
        --spec "<spec-path>" --feat-id "$FEAT_ID" --worktree "$WORKTREE_PATH")
    GATE_EXIT=$?
- path: `.claude/commands/sdd-done.md`
  lines: 568-600
  symbol: `### 9. Check Merge Blockers (FEAT-566)`
  excerpt: |
    if [[ "$MERGE_FLAG" == "--merge" ]]; then
        BLOCKERS_OUTPUT=$(wikitoolkit ledger blockers "$FEAT_ID" 2>&1)
        BLOCKERS_EXIT=$?
        if [[ $BLOCKERS_EXIT -ne 0 ]]; then
            if [[ "$FORCE_FLAG" != "--force" ]]; then
                write_hook_context "merge blocked by critical ledger issues"
                parrot sdd closeout run --event on_failure --context "$HOOKS_DIR/context.json" --root "$WORKTREE_PATH" || true
                exit 1
- path: `.claude/commands/sdd-done.md`
  lines: 602-632
  symbol: `### 9.1. Deliver Ledger Events (FEAT-758)`
  excerpt: |
    wikitoolkit ledger outbox prepare --repo-root "<worktree-path>"
    wikitoolkit ledger outbox integrate --repo-root "<worktree-path>"
    # Pending delivery does NOT undo the code PR; it blocks Step 11 cleanup only.
- path: `.claude/commands/sdd-done.md`
  lines: 33-51
  symbol: `## Guardrails`
  excerpt: |
    **Required E2E evidence (FEAT-581) is checked in Step 4.6, before any
    stamp/push/PR/merge/cleanup.** --force bypasses per-task partial/missing
    evidence (Step 6) and ledger merge blockers (Step 9) — it never bypasses
    a required E2E gate (spec AC9).
- path: `.claude/commands/sdd-done.md`
  lines: 444-506
  symbol: `### 7. Close & Stamp Verification (on feature branch)`
- path: `.claude/commands/sdd-done.md`
  lines: 540-567
  symbol: `### 8. Push the Feature Branch`
- path: `.agents/skills/sdd-done/SKILL.md`
  lines: 1-1
  symbol: `SDD Done (Codex twin)`
  wiki_page_id: file:.agents/skills/sdd-done/SKILL.md
  score: 1.00
- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md`
  lines: 1-1
  symbol: `/sdd-done shipped asset twin`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md
  score: 0.87

## Notes

Three twins must change together: `.claude/commands/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md` and the shipped asset under `packages/ai-parrot/src/parrot/sdd/_assets/` (`.agent/workflows/sdd-done.md` is also indexed). The house rule (FEAT-703, FEAT-764) is that an un-bypassable gate takes no force parameter at all. `/sdd-done` can also run from inside the worktree (IN_WORKTREE=1), PR flow only. [cross-lane: type=read, intent=codebase lane Q016 should cite Step 6 "Confirm" and Step 7 stamping lines exactly; a verdict guard must sit before Step 7.]
