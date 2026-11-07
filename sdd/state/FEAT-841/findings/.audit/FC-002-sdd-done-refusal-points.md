---
id: FC-002
query_id: Q016
type: read
intent: "Read /sdd-done: locate the verification step, the blocker list, --merge and the PR step — where a verdict guard would sit."
executed_at: 2026-11-07T01:20:22Z
duration_ms: 4000
parent_id: null
depth: 0
---

# FC-002 — /sdd-done refuses in four code-enforced places; --force bypasses only two

## Summary

`.claude/commands/sdd-done.md` (996 lines) has four abort points before any mutating step: (1) §4.6 E2E evidence gate (`parrot sdd tests e2e-closeout`, exit code is the contract, **never** bypassed by `--force`); (2) §4.8 `pre_pr` closeout hooks (`parrot sdd closeout run --event pre_pr`, exit 1/2 abort, exit 3 = agent hooks pending, **never** bypassed by `--force`); (3) §8 `--merge` into the hotfix base refused under every flag; (4) §9 ledger merge blockers (`wikitoolkit ledger blockers FEAT-ID`, exit≠0 → abort, **bypassable** with `--force`, and only runs under `--merge`). Every abort first writes a hook context (`write_hook_context "<reason>"`) and fires `on_failure` hooks. §7 stamps `verification` per task and the feature-level `completed_at` in the per-spec index **inside the worktree**, committed on the feature branch. The convention is stated verbatim: "the exit code is the contract" and "the gate takes no `--force` argument, so there is nothing for a generic force to bypass". The natural insertion point for an escrow verdict guard is between §4.6 and §4.8 (or as a built-in §4.8 pre_pr blocking hook), reusing `write_hook_context` + `on_failure`.

## Citations

- path: `.claude/commands/sdd-done.md`
  lines: 39-43
  symbol: null
  excerpt: |
    - **Required E2E evidence (FEAT-581) is checked in Step 4.6, before any
      stamp/push/PR/merge/cleanup.** Missing, stale, tampered, blocked or failed
      required evidence aborts the whole command. `--force` bypasses per-task
      partial/missing evidence (Step 6) and ledger merge blockers (Step 9) —
      it never bypasses a required E2E gate (spec AC9).

- path: `.claude/commands/sdd-done.md`
  lines: 250-253
  symbol: null
  excerpt: |
    GATE_JSON=$(parrot sdd tests e2e-closeout \
        --spec "<spec-path>" --feat-id "$FEAT_ID" --worktree "$WORKTREE_PATH")
    GATE_EXIT=$?

- path: `.claude/commands/sdd-done.md`
  lines: 266-279
  symbol: null
  excerpt: |
    - **`GATE_EXIT` is non-zero** — **abort the entire command now**, before
      Step 5's report is even built:
      ⚠️  Required E2E evidence is <status> for FEAT-<ID> (reason: <reason_codes>).
         This is NOT bypassed by --force: --force only overrides per-task
         partial/missing evidence (Step 6) and ledger merge blockers (Step 9),
         never a required E2E gate (spec AC9).
      Exit nonzero. `--dry-run` still shows this refusal ...
      `write_hook_context "E2E gate <status>"; parrot sdd closeout run --event on_failure --context "$HOOKS_DIR/context.json" --root "$WORKTREE_PATH" || true`

- path: `.claude/commands/sdd-done.md`
  lines: 282-286
  symbol: null
  excerpt: |
    in `parrot.sdd.scripts.check_e2e_closeout`. Do not restate or
    re-derive it here: **the exit code is the contract**, and the gate takes no
    `--force` argument, so there is nothing for a generic force to bypass.

- path: `.claude/commands/sdd-done.md`
  lines: 208-216
  symbol: `write_hook_context`
  excerpt: |
    write_hook_context() {
      HOOKS_DIR="${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/$FEAT_ID"; mkdir -p "$HOOKS_DIR"
      FEAT_ID="$FEAT_ID" BRANCH="$BRANCH" BASE_BRANCH="$BASE_BRANCH" WORKTREE_PATH="$WORKTREE_PATH" \
      SPEC_PATH="${SPEC_PATH:-sdd/specs/<feature-slug>.spec.md}" TEST_REPORT_MD="${TEST_REPORT_MD:-}" \
      GATE_JSON="${GATE_JSON:-}" PR_URL="${PR_URL:-}" MERGE_SHA="${MERGE_SHA:-}" \
      HOOK_ABORT_REASON="$1" DRY_RUN="${DRY_RUN:-}" python3 - "$HOOKS_DIR/context.json" <<'PY'

- path: `.claude/commands/sdd-done.md`
  lines: 360-371
  symbol: null
  excerpt: |
    HOOKS_OUT=$(parrot sdd closeout run --event pre_pr \
        --context "$HOOKS_DIR/context.json" --root "$WORKTREE_PATH" ${DRY_RUN:+--dry-run})
    HOOKS_EXIT=$?
    | `0` | every blocking hook passed (non-blocking failures allowed) | ... continue to §5 |
    | `3` | agent hooks pending | run the agent loop below |
    | `1` | a `blocking` pre_pr hook failed | run on_failure (below), then abort before Step 7 |
    | `2` | config or usage error (a malformed `.parrot/sdd_hooks.toml` fails closed) | run on_failure, then abort before Step 7 |

- path: `.claude/commands/sdd-done.md`
  lines: 544-549
  symbol: null
  excerpt: |
    if [[ "$BASE_BRANCH" == "$HOTFIX_BASE" && "$MERGE_FLAG" == "--merge" ]]; then
        echo "⚠️  --merge into '$HOTFIX_BASE' is refused. /sdd-done opens the PR; merging a $HOTFIX_BASE PR is the human act." >&2
        write_hook_context "--merge into $HOTFIX_BASE refused"
        parrot sdd closeout run --event on_failure --context "$HOOKS_DIR/context.json" --root "$WORKTREE_PATH" || true
        exit 1

- path: `.claude/commands/sdd-done.md`
  lines: 575-593
  symbol: null
  excerpt: |
    if [[ "$MERGE_FLAG" == "--merge" ]]; then
        BLOCKERS_OUTPUT=$(wikitoolkit ledger blockers "$FEAT_ID" 2>&1)
        BLOCKERS_EXIT=$?
        if [[ $BLOCKERS_EXIT -ne 0 ]]; then
            echo "⚠️  Merge blocked by critical unacknowledged issues:"
            echo "To acknowledge an issue: wikitoolkit ledger acknowledge <ISSUE-ID> --reason \"...\" --actor human:<name>"
            if [[ "$FORCE_FLAG" != "--force" ]]; then
                write_hook_context "merge blocked by critical ledger issues"
                exit 1

- path: `.claude/commands/sdd-done.md`
  lines: 496-504
  symbol: null
  excerpt: |
    # Stamp feature-level completed_at if all tasks are done.
    jq --arg now "$NOW" '
      if all(.tasks[]; .status == "done") then .completed_at = $now else . end
    ' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"
    # Commit on the feature branch (inside the worktree) — never on base_branch.
    git -C "$WORKTREE_PATH" add "$INDEX" sdd/tasks/completed/

- path: `.claude/commands/sdd-done.md`
  lines: 77-80
  symbol: null
  excerpt: |
    # /sdd-done runs either from the main repo or from inside the feature worktree
    # (the sdd-worker agent runs it from its own worktree). Resolve the primary
    # checkout once and address it ONLY through these variables afterwards.

## Notes

- The ledger blocker gate (§9) only runs under `--merge`; the PR flow (default) skips it entirely. An escrow guard must not copy that shape — it must run in both flows (E2E gate §4.6 is the right precedent).
- `ledger acknowledge` already requires a `human:<name>` actor to waive a critical blocker — precedent for "human override must carry an actor + reason".
- The E2E gate is implemented in `parrot.sdd.scripts.check_e2e_closeout`; the Codex twin `.agents/skills/sdd-done/SKILL.md` consumes the same validator — any escrow guard needs the same twin treatment.
- [cross-lane: type=git_log, intent=when FEAT-703 (E2E gate as code) and FEAT-764 (closeout hooks) landed in sdd-done.md]
