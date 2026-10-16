# Design Research Triage — sdd-brief-hotfix-flow

Model: gpt-5.6-luna · 9 suggestions · all affected paths verified to exist
inside the repo (`test -e`), key claims spot-checked in source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Add a brief-specific worktree plan (architecture) | CONFIRM | `plan_worktree` only accepts FEAT ids / Jira keys (sdd_meta.py:336-390, verified); a dev-based ledger brief is unrepresentable. New command-layer helper `scripts/sdd/brief_meta.py` builds the `WorktreePlan` directly, `FlowMeta` untouched. Naming inconsistency resolved: worktree branch is `fix-<id>-<slug>` (a worktree dir basename cannot carry `/`); the fast-lane's `fix/<id>-<slug>` branches remain a distinct, worktree-less namespace. | §2 Overview, §3 M2, §7 |
| S2 | No null feature_id through the coder pipeline (architecture) | CONFIRM | Verified: `checkpoint.py:462-466` raises on empty `feature_id`; `ExecutionPoolView.feature_id` has `min_length=1` (models.py:473,505). The per-brief index header carries `feature_id: "BRIEF-<KEY>"` — non-empty, never matching `^FEAT-\d+$`, so no id-ledger collision and no board ingestion. | §2 Data Models, §3 M2, §6 |
| S3 | Explicit brief index path in ResearchOutput (api) | CONFIRM | Verified: `_find_feature_slug` scans only `sdd/tasks/index/` and `feat_id == ""` returns None (development.py:1309-1342), silently degrading a split brief to single-agent. `ResearchOutput` gains optional `index_path`; `_build_scheduler` resolves it before the feat_id scan. | §3 M5 |
| S4 | /sdd-done as separate brief state machine (architecture) | CONFIRM | Matches the brief-resolution design; made explicit — a dedicated brief lane (resolve → verify via per-brief index + Validation Commands → PR), never conditionals threaded through the feature path. | §3 M3 |
| S5 | Main-target PR creation fail-closed (risk) | CONFIRM | sdd-done.md:553-571 currently prints a snippet and exits 0, and hardcodes `feat-<FEAT-ID>-<slug>`. New behavior: `gh pr create --base "$BASE_BRANCH" --head "$BRANCH"`, print URL, retain worktree/branch on failure, reject `--merge` for main BEFORE any push. | §3 M3, §5 |
| S6 | Unset + verify upstream right after worktree creation (risk) | CONFIRM | Verified: `_create_worktree` (ensure_worktree.py:189-201) never unsets the auto-upstream; the hazard is documented in .claude/rules/worktree-management.md but unenforced. `ensure()` gains the unset + an `@{upstream}`-absent assertion. | §3 M2, §5 |
| S7 | Ledger claims as a transaction (risk) | CONFIRM | Claim at research start, claim persisted in brief frontmatter (`ledger_issue`), release on abort at every pre-worktree phase, close only after merge confirmation — otherwise print the exact close command. | §3 M1, §7 |
| S8 | Replace empty-feat hotfix tests with brief-shape coverage (testing) | CONFIRM | test_empty_feat_id.py / test_flow_type_override.py / test_research_base_branch.py encode the old behavior; §4 enumerates their migration plus new brief-index discovery and PR-policy tests. | §4 |
| S9 | Non-negotiable minimum for --research light (risk) | CONFIRM | Light mode must still record a fetched source, a root-cause statement, and ≥1 verified `path:line` anchor; the command refuses worktree creation when any is absent. | §3 M1, §5 |

Summary: **9** confirmed · **0** rejected · **0** escalated.
