# S5 — SDD asset assumption inventory (FEAT-633)

Scanned 89 file(s).

## Summary

| Kind | Findings | Files |
|---|---|---|
| repo-script | 205 | 52 |
| venv-path | 10 | 6 |
| uv-run | 3 | 3 |
| external-tool | 93 | 33 |
| posix-shell | 234 | 36 |
| monorepo-path | 101 | 31 |
| org-data | 120 | 15 |
| claude-md-ref | 15 | 14 |
| branch-literal | 105 | 43 |

## Helper reference map

| Asset | Helpers |
|---|---|
| `.agent/agents/sdd-autopilot/agent.md` | select_tests |
| `.agent/agents/sdd-ideation/agent.md` | sdd_meta |
| `.agent/agents/sdd-research/agent.md` | ensure_worktree |
| `.agent/agents/sdd-worker/agent.md` | close_task, ensure_worktree, finalize_task, sdd_meta, select_tests |
| `.agent/workflows/sdd-brainstorm.md` | sdd_meta |
| `.agent/workflows/sdd-brief.md` | brief_meta, check_task_graph, ensure_worktree |
| `.agent/workflows/sdd-done.md` | check_task_state, close_resolved_issues, close_task, heal_orphans, sdd_meta, select_tests, test_report |
| `.agent/workflows/sdd-fix.md` | ensure_worktree, reserve_ids |
| `.agent/workflows/sdd-insight.md` — not shipped (C22) | insight |
| `.agent/workflows/sdd-next.md` | doc_taxonomy, worktree_status |
| `.agent/workflows/sdd-proposal.md` | sdd_meta |
| `.agent/workflows/sdd-spec.md` | reserve_ids, sdd_meta, spec_tools |
| `.agent/workflows/sdd-start.md` | close_task, ensure_worktree, finalize_task, sdd_meta |
| `.agent/workflows/sdd-status.md` | doc_taxonomy, worktree_status |
| `.agent/workflows/sdd-task.md` | cache_test_contract, check_task_graph, reserve_ids, sdd_meta |
| `.agent/workflows/sdd-tojira.md` | sdd_meta |
| `.agents/agents/sdd-ideation/agent.md` | sdd_meta |
| `.agents/agents/sdd-research/agent.md` | ensure_worktree |
| `.agents/agents/sdd-worker/agent.md` | close_task, ensure_worktree, sdd_meta |
| `.agents/skills/sdd-brainstorm/SKILL.md` | sdd_meta |
| `.agents/skills/sdd-brief/SKILL.md` | ensure_worktree |
| `.agents/skills/sdd-done/SKILL.md` | check_e2e_closeout, close_resolved_issues, close_task, heal_orphans, sdd_meta, select_tests, test_report |
| `.agents/skills/sdd-fix/SKILL.md` | ensure_worktree, reserve_ids |
| `.agents/skills/sdd-fromjira/SKILL.md` | sdd_meta |
| `.agents/skills/sdd-insight/SKILL.md` — not shipped (C22) | insight |
| `.agents/skills/sdd-next/SKILL.md` | doc_taxonomy, worktree_status |
| `.agents/skills/sdd-proposal/SKILL.md` | sdd_meta |
| `.agents/skills/sdd-spec/SKILL.md` | reserve_ids, sdd_meta |
| `.agents/skills/sdd-start/SKILL.md` | ensure_worktree, finalize_task |
| `.agents/skills/sdd-status/SKILL.md` | doc_taxonomy, worktree_status |
| `.agents/skills/sdd-task/SKILL.md` | cache_test_contract, check_task_graph, reserve_ids, sdd_meta |
| `.claude/agents/sdd-autopilot.md` | ensure_worktree, select_tests |
| `.claude/agents/sdd-ideation.md` | sdd_meta |
| `.claude/agents/sdd-planner.md` | ensure_worktree, sdd_meta |
| `.claude/agents/sdd-research.md` | ensure_worktree |
| `.claude/agents/sdd-worker.md` | close_task, ensure_worktree, finalize_task, review_checkpoint, sdd_meta, select_tests |
| `.claude/commands/sdd-brainstorm.md` | sdd_meta |
| `.claude/commands/sdd-brief.md` | brief_meta, check_task_graph, ensure_worktree |
| `.claude/commands/sdd-done.md` | check_e2e_closeout, check_task_state, close_resolved_issues, close_task, heal_orphans, sdd_meta, select_tests, test_report |
| `.claude/commands/sdd-fix.md` | ensure_worktree, reserve_ids |
| `.claude/commands/sdd-insight.md` — not shipped (C22) | insight |
| `.claude/commands/sdd-next.md` | doc_taxonomy, worktree_status |
| `.claude/commands/sdd-proposal.md` | sdd_meta |
| `.claude/commands/sdd-spec.md` | reserve_ids, sdd_meta, spec_tools |
| `.claude/commands/sdd-start.md` | close_task, ensure_worktree, finalize_task, sdd_meta |
| `.claude/commands/sdd-status.md` | doc_taxonomy, worktree_status |
| `.claude/commands/sdd-task.md` | cache_test_contract, check_task_graph, reserve_ids, sdd_meta |
| `.claude/commands/sdd-tojira.md` | sdd_meta |
| `.claude/rules/worktree-management.md` | ensure_worktree, sdd_meta |
| `sdd/WORKFLOW.md` | backfill_taxonomy, check_id_collisions, close_task, doc_taxonomy, ensure_worktree, id_ledger, install_hooks, migrate_index, reserve_ids |
| `sdd/templates/intake.procedure.md` | reserve_ids |
| `sdd/templates/task.md` | close_task, ensure_worktree |

## Rewrite list (drives TASK-4089)

- `scripts/sdd/backfill_taxonomy` / `scripts.sdd.backfill_taxonomy` → `parrot sdd run backfill_taxonomy`
- `scripts/sdd/brief_meta` / `scripts.sdd.brief_meta` → `parrot sdd run brief_meta`
- `scripts/sdd/cache_test_contract` / `scripts.sdd.cache_test_contract` → `parrot sdd run cache_test_contract`
- `scripts/sdd/check_e2e_closeout` / `scripts.sdd.check_e2e_closeout` → `parrot sdd run check_e2e_closeout`
- `scripts/sdd/check_id_collisions` / `scripts.sdd.check_id_collisions` → `parrot sdd run check_id_collisions`
- `scripts/sdd/check_task_graph` / `scripts.sdd.check_task_graph` → `parrot sdd run check_task_graph`
- `scripts/sdd/check_task_state` / `scripts.sdd.check_task_state` → `parrot sdd run check_task_state`
- `scripts/sdd/close_resolved_issues` / `scripts.sdd.close_resolved_issues` → `parrot sdd run close_resolved_issues`
- `scripts/sdd/close_task` / `scripts.sdd.close_task` → `parrot sdd run close_task`
- `scripts/sdd/doc_taxonomy` / `scripts.sdd.doc_taxonomy` → `parrot sdd run doc_taxonomy`
- `scripts/sdd/ensure_worktree` / `scripts.sdd.ensure_worktree` → `parrot sdd run ensure_worktree`
- `scripts/sdd/finalize_task` / `scripts.sdd.finalize_task` → `parrot sdd run finalize_task`
- `scripts/sdd/heal_orphans` / `scripts.sdd.heal_orphans` → `parrot sdd run heal_orphans`
- `scripts/sdd/id_ledger` / `scripts.sdd.id_ledger` → `parrot sdd run id_ledger`
- `scripts/sdd/insight` / `scripts.sdd.insight` → `parrot sdd run insight`
- `scripts/sdd/install_hooks` / `scripts.sdd.install_hooks` → `parrot sdd run install_hooks`
- `scripts/sdd/migrate_index` / `scripts.sdd.migrate_index` → `parrot sdd run migrate_index`
- `scripts/sdd/reserve_ids` / `scripts.sdd.reserve_ids` → `parrot sdd run reserve_ids`
- `scripts/sdd/review_checkpoint` / `scripts.sdd.review_checkpoint` → `parrot sdd run review_checkpoint`
- `scripts/sdd/sdd_meta` / `scripts.sdd.sdd_meta` → `parrot sdd run sdd_meta`
- `scripts/sdd/select_tests` / `scripts.sdd.select_tests` → `parrot sdd run select_tests`
- `scripts/sdd/spec_tools` / `scripts.sdd.spec_tools` → `parrot sdd run spec_tools`
- `scripts/sdd/test_report` / `scripts.sdd.test_report` → `parrot sdd run test_report`
- `scripts/sdd/worktree_status` / `scripts.sdd.worktree_status` → `parrot sdd run worktree_status`

## Findings by file

### .agent/agents/sdd-autopilot/agent.md

- L100 [org-data] `/sdd-fromjira NAV-8036`
- L101 [org-data] `/sdd-fromjira NAV-8036 --auto-approve    # skip manual spec approval (risky)`
- L102 [org-data] `/sdd-fromjira NAV-8036 --complexity=fix  # hint: simple fix, minimal Q&A`
- L113 [external-tool] `| jq '{`
- L263 [monorepo-path] `.claude/worktrees/feat-<FEAT-ID>-<slug> HEAD`
- L269 [org-data] `✅ /sdd-fromjira complete for NAV-8036`
- L271 [org-data] `Jira: NAV-8036 — "Add OAuth 2.0 support for JiraToolkit"`
- L274 [monorepo-path] `Worktree: .claude/worktrees/feat-071-jira-oauth`
- L279 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L283 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L326 [posix-shell] `WORKTREE_DIR=$(pwd)`
- L327 [posix-shell] `REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$WORKTREE_DIR")`
- L359 [posix-shell] `VERDICT=$(grep -oP '(?<=verdict:\s)(APPROVED|NEEDS_CHANGES)' .autopilot/review-report.md)`
- L362 [posix-shell] `echo "✅ Code review passed (iteration $((REVIEW_ITERATION + 1)))"`
- L366 [posix-shell] `echo "⚠️ Code review: NEEDS_CHANGES (iteration $((REVIEW_ITERATION + 1)))"`
- L375 [posix-shell] `REVIEW_ITERATION=$((REVIEW_ITERATION + 1))`
- L397 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L414 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L428 [external-tool] `PR_URL=$(gh pr create \`
- L428 [posix-shell] `PR_URL=$(gh pr create \`
- L429 [branch-literal] `--base dev \`
- L430 [posix-shell] `--head "$(git branch --show-current)" \`
- L431 [posix-shell] `--title "feat($FEAT_ID): $(cat sdd/specs/*.spec.md | head -1 | sed 's/# //')" \`
- L441 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=jira:\s)\S+' sdd/specs/*.spec.md || echo "")`
- L459 [posix-shell] `║  Jira review: $([ -n "$JIRA_KEY" ] && echo "✅" || echo "⏭ skipped") ║`
- L488 [org-data] `"jira_key": "NAV-8036",`
- L574 [external-tool] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L574 [posix-shell] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L574 [repo-script] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L575 [posix-shell] `--base origin/<base_branch> $(printf -- '--task-file %s ' $TASK_FILES) --run` — the feature`
- L670 [monorepo-path] `- `from parrot_tools.toolkit import AbstractToolkit` — packages/ai-parrot-tools/src/parrot_tools/toolkit.py:15`
- L671 [monorepo-path] `- `from parrot.tools.manager import ToolManager` — packages/ai-parrot/src/parrot/tools/manager.py:1`
- L709 [org-data] `/sdd-fromjira NAV-8036`
- L712 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L722 [org-data] `/sdd-fromjira NAV-8036`
- L725 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L731 [org-data] `/pr-review <PR_URL> NAV-8036`
- L737 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L738 [external-tool] `tmux new -s feat-071 \`

### .agent/agents/sdd-ideation/agent.md

- L141 [branch-literal] `# - type: feature  (default)  → base_branch: dev (or any non-main branch)`
- L144 [branch-literal] `base_branch: dev`
- L153 [repo-script] ``KNOWN_PROJECTS` vocabulary in `scripts/sdd/sdd_meta.py`; when resuming an`

### .agent/agents/sdd-planner/agent.md

- L35 [monorepo-path] `4. **Create the worktree** at ``.claude/worktrees/feat-<id>-<slug>/```
- L37 [monorepo-path] ```git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> HEAD```
- L63 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",`

### .agent/agents/sdd-research/agent.md

- L49 [branch-literal] `/sdd-spec <slug> --type feature --base-branch dev --no-interview        # kind == "enhancement" | "new_feature"`
- L61 [repo-script] `python -m scripts.sdd.ensure_worktree --json \`
- L89 [org-data] `"jira_issue_key": "OPS-1234",`
- L93 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",`
- L103 [org-data] `"jira_issue_key": "OPS-1234",`
- L107 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",`

### .agent/agents/sdd-worker/agent.md

- L101 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L101 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L102 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L103 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L105 [posix-shell] `if [ "$(git rev-parse --absolute-git-dir)" != "$(cd "$(git rev-parse --git-common-dir)" && pwd)" ]; then`
- L127 [branch-literal] `spec declares `type: feature, base_branch: main`, abort with:`
- L149 [external-tool] `INDEX=$(jq -r --arg q "<query>" '`
- L149 [posix-shell] `INDEX=$(jq -r --arg q "<query>" '`
- L175 [external-tool] `jq --arg id "HOTFIX-<KEY>-<N>" --arg now "$NOW" \`
- L200 [posix-shell] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L200 [repo-script] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L212 [repo-script] `come from `scripts.sdd.sdd_meta.plan_worktree`.`
- L235 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L237 [external-tool] `jq --arg now "$NOW" '(.tasks[] | select(.status == "pending") | .status) = "in-progress" |`
- L289 [repo-script] `- Run the task's `## Validation Commands`, then `python -m scripts.sdd.select_tests --tier merge --base origin/<base_branch> --index sdd/tasks/index/<feature-sl`
- L308 [repo-script] `python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.`
- L320 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L326 [repo-script] `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`
- L360 [claude-md-ref] `and follow the project's conventions (from CLAUDE.md)?`
- L417 [monorepo-path] `Worktree: .claude/worktrees/<worktree-name>`
- L451 [monorepo-path] ``packages/ai-parrot/tests/flows/dev_loop/test_qa.py`). `DevelopmentNode``

### .agent/workflows/sdd-brainstorm.md

- L74 [branch-literal] `- `type: hotfix` REQUIRES `base_branch: main`.`
- L75 [branch-literal] `- `type: feature` with `base_branch: main` is NOT allowed — use `staging` or `dev`.`
- L87 [branch-literal] `base_branch: dev | staging   # for type=feature (defaults to dev)`
- L92 [branch-literal] `If the user does not answer, default to `type: feature, base_branch: dev`.`
- L211 [monorepo-path] `(`packages/<dist>/…` → `<dist>`; `packages/ai-parrot-server/ui/` → `admin-ui`;`
- L215 [repo-script] `is `KNOWN_PROJECTS` in `scripts/sdd/sdd_meta.py`; an unknown value is allowed`

### .agent/workflows/sdd-brief.md

- L14 [branch-literal] `/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]`
- L22 [repo-script] ``python -m scripts.sdd.ensure_worktree`.`
- L44 [external-tool] `| Code-scanning alert | `cs:<n>` or a GitHub `/security/code-scanning/<n>` URL | `gh api repos/{owner}/{repo}/code-scanning/alerts/<n>` |`
- L45 [external-tool] `| GitHub issue | issue URL or `owner/repo#<n>` | `gh issue view <n> --repo <owner>/<repo> --json number,title,body,labels,state,url` |`
- L46 [external-tool] `| GitHub pull request | PR URL or `owner/repo!<n>` | `gh pr view <n> --repo <owner>/<repo> --json number,title,body,files,state,url` |`
- L59 [branch-literal] ``--base-branch main`, stop with this exact message:`
- L62 [branch-literal] `⚠️  Ledger-sourced briefs always base on dev; --base-branch main is refused.`
- L68 [posix-shell] `source title or text.`
- L136 [repo-script] `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`
- L155 [repo-script] ``scripts.sdd.brief_meta.write_brief_index`, then validate its graph:`
- L158 [repo-script] `python -m scripts.sdd.check_task_graph <wt>/sdd/briefs/<slug>.index.json`

### .agent/workflows/sdd-codereview.md

- L110 [external-tool] `codex commands:`
- L113 [external-tool] `codex exec review --uncommitted`
- L116 [branch-literal] `codex exec review --base dev`
- L116 [external-tool] `codex exec review --base dev`
- L119 [external-tool] `codex exec review --commit <sha>`
- L122 [external-tool] `codex exec --sandbox read-only -o artifacts/reviews/<task>-codex.txt \`
- L126 [external-tool] `codex exec resume --last "<neutral follow-up question>"`

### .agent/workflows/sdd-done.md

- L42 [external-tool] `> For hotfixes, this command pushes the hotfix branch and prints a `gh pr create`
- L43 [branch-literal] `> --base main` snippet. After the user merges the PR, the `.github/workflows/sync-down.yml``
- L68 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L68 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L69 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L70 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L71 [posix-shell] `CURRENT_BRANCH=$(git branch --show-current)`
- L80 [monorepo-path] `If currently inside a worktree (path contains `.claude/worktrees/`), abort:`
- L139 [external-tool] `if grep -q '^\[tool\.black\]' "$WT/pyproject.toml"; then (cd "$WT" && black -q "${PY[@]}"); fi`
- L149 [external-tool] ``except Exception`), run `TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");`
- L149 [posix-shell] ``except Exception`), run `TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");`
- L150 [repo-script] `python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT" \`
- L152 [posix-shell] `$(printf -- '--task-file %s ' $TASK_FILES) --run` before committing.`
- L165 [posix-shell] `TEST_REPORT_MD="${SDD_TEST_REPORT_DIR:-/tmp/claude-$(id -u)/sdd-tests}/FEAT-<ID>/pr-tests.md"`
- L166 [posix-shell] `mkdir -p "$(dirname "$TEST_REPORT_MD")"`
- L170 [posix-shell] `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")`
- L170 [repo-script] `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")`
- L177 [repo-script] `timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> \`
- L178 [posix-shell] `--worktree "$WT" --index "$IDX" $(printf -- '--task-file %s ' <every task file of the index>) \`
- L190 [repo-script] `python -m scripts.sdd.test_report render --index "$IDX" --worktree "$WT" --out "$TEST_REPORT_MD"`
- L204 [monorepo-path] `Worktree: .claude/worktrees/feat-<ID>-<slug>`
- L255 [repo-script] `> `scripts/sdd/close_task.sh` — **inside the worktree, on the feature branch**.`
- L261 [monorepo-path] `WORKTREE_PATH=".claude/worktrees/feat-<FEAT-ID>-<slug>"`
- L263 [posix-shell] `NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L268 [external-tool] `STATUS=$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .status' "$WORKTREE_PATH/$INDEX")`
- L268 [posix-shell] `STATUS=$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .status' "$WORKTREE_PATH/$INDEX")`
- L276 [repo-script] `(cd "$WORKTREE_PATH" && scripts/sdd/close_task.sh "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION")`
- L279 [external-tool] `jq --arg id "$TASK_ID" '(.tasks[] | select(.id == $id) | .status) = "done-with-issues"' \`
- L283 [external-tool] `jq --arg id "$TASK_ID" --arg ver "$VERIFICATION" '`
- L291 [repo-script] `(cd "$WORKTREE_PATH" && scripts/sdd/heal_orphans.sh "$FEATURE_SLUG")`
- L294 [external-tool] `jq --arg now "$NOW" '`
- L326 [repo-script] `(cd "$WORKTREE_PATH" && python -m scripts.sdd.close_resolved_issues \`
- L354 [posix-shell] `BLOCKERS_OUTPUT=$(wikitoolkit ledger blockers "$FEAT_ID" 2>&1)`
- L392 [monorepo-path] `TEMP_WORKTREE=".claude/worktrees/_ledger-snapshot-$$"`
- L407 [posix-shell] `EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)`
- L408 [posix-shell] `LOG_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export-log 2>&1)`
- L409 [posix-shell] `ROTATE_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger rotate-log --older-than-days 30 2>&1)`
- L428 [posix-shell] `ATTEMPT=$((ATTEMPT + 1))`
- L450 [posix-shell] `cat <<EOF`
- L456 [branch-literal] `gh pr create --base main --head feat-<FEAT-ID>-<slug> \\`
- L456 [external-tool] `gh pr create --base main --head feat-<FEAT-ID>-<slug> \\`
- L481 [external-tool] `gh pr create \`
- L485 [posix-shell] `--body "$(cat <<EOF`
- L494 [posix-shell] `$(cat "$TEST_REPORT_MD")`
- L506 [external-tool] `gh pr create --base <BASE_BRANCH> --head feat-<FEAT-ID>-<slug> \`
- L531 [repo-script] `> the feature branch in Step 7, and CI's `scripts/sdd/check_task_state.py``
- L535 [repo-script] `scripts/sdd/heal_orphans.sh <feature-slug>`
- L563 [branch-literal] `**Pre-flight (run once):** verify the hotfix landed on `origin/main`:`
- L566 [branch-literal] `if ! git merge-base --is-ancestor "feat-<FEAT-ID>-<slug>" origin/main; then`
- L567 [branch-literal] `echo "⚠️  feat-<FEAT-ID>-<slug> is not yet an ancestor of origin/main."`
- L575 [branch-literal] `git checkout staging`
- L579 [branch-literal] `git push origin staging`
- L585 [posix-shell] `cat <<EOF`
- L589 [branch-literal] `git checkout staging`
- L593 [branch-literal] `git push origin staging`
- L602 [branch-literal] `git checkout dev`
- L606 [branch-literal] `git push origin dev`
- L612 [posix-shell] `cat <<EOF`
- L616 [branch-literal] `git checkout dev`
- L620 [branch-literal] `git push origin dev`
- L628 [branch-literal] `git checkout main`
- L648 [org-data] `# Look for "**Jira**: [NAV-8036](...)" or a "jira:" metadata field in the spec`
- L649 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=\*\*Jira\*\*: \[)[A-Z]+-\d+' sdd/specs/<feature>.spec.md)`
- L652 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=\| Key \| )[A-Z]+-\d+' sdd/proposals/<key>-*.brainstorm.md)`
- L664 [posix-shell] `eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L682 [posix-shell] `TRANSITIONS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \`
- L684 [external-tool] `echo "$TRANSITIONS" | jq '.transitions[] | {id, name}'`
- L694 [external-tool] `TRANSITION_ID=$(echo "$TRANSITIONS" | jq -r '`
- L694 [posix-shell] `TRANSITION_ID=$(echo "$TRANSITIONS" | jq -r '`
- L735 [posix-shell] `SUBTASKS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \`
- L737 [external-tool] `| jq -r '.fields.subtasks[].key')`
- L747 [monorepo-path] `git worktree remove .claude/worktrees/feat-<FEAT-ID>-<slug>`
- L777 [monorepo-path] `Worktree removed: .claude/worktrees/feat-<ID>-<slug>`
- L792 [monorepo-path] `Worktree removed: .claude/worktrees/feat-<ID>-<slug>`
- L804 [org-data] `Jira: NAV-8036 → Done ✅`
- L815 [org-data] `{if --resolve-jira} Jira NAV-8036 → Done ✅ {end if}`
- L822 [repo-script] `- Frontmatter parser: `scripts/sdd/sdd_meta.py``

### .agent/workflows/sdd-explain.md

- L23 [claude-md-ref] `Use these as *search starting points*. The codebase is the only authority — verify every claim against what you read. Read CLAUDE.md and any CONTEXT.md files to`

### .agent/workflows/sdd-fix.md

- L40 [branch-literal] `- **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev``
- L41 [branch-literal] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L41 [external-tool] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L44 [branch-literal] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L44 [repo-script] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L46 [repo-script] ``python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `/sdd-done <FEAT-ID>` closes it out, including the issues its verified `

### .agent/workflows/sdd-fromjira.md

- L17 [org-data] `/sdd-fromjira NAV-8036`
- L18 [org-data] `/sdd-fromjira NAV-8036 --complexity=fix       # minimal Q&A, straight to brainstorm`
- L19 [org-data] `/sdd-fromjira NAV-8036 --skip-qa              # use Jira description as-is (rare)`
- L44 [org-data] `jira_get_issue(issue_key="NAV-8036")`
- L50 [org-data] `#   JIRA_INSTANCE  — e.g. https://trocglobal.atlassian.net/`
- L55 [posix-shell] `#   eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L100 [external-tool] `AC=$(echo "$JIRA_RESPONSE" | jq -r ".fields.$FIELD // empty")`
- L100 [posix-shell] `AC=$(echo "$JIRA_RESPONSE" | jq -r ".fields.$FIELD // empty")`
- L132 [org-data] `📋 Jira Ticket: NAV-8036`
- L271 [branch-literal] `base_branch: dev`
- L274 [org-data] `jira: NAV-8036`
- L283 [branch-literal] `Validation rule: `type: hotfix` REQUIRES `base_branch: main`. The user`

### .agent/workflows/sdd-insight.md

- L9 [repo-script] `1. **Measure (deterministic).** `scripts/sdd/insight.py` parses Claude Code transcripts,`
- L20 [posix-shell] `> **Always activate the venv first** (project rule): `source .venv/bin/activate`.`
- L20 [venv-path] `> **Always activate the venv first** (project rule): `source .venv/bin/activate`.`
- L39 [posix-shell] `source .venv/bin/activate`
- L39 [venv-path] `source .venv/bin/activate`
- L48 [repo-script] `python3 scripts/sdd/insight.py \`
- L82 [repo-script] `python3 scripts/sdd/insight.py \`

### .agent/workflows/sdd-next.md

- L31 [external-tool] `TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)`
- L31 [posix-shell] `TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)`
- L39 [posix-shell] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L39 [repo-script] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L40 [external-tool] `TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/inde`
- L40 [posix-shell] `TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/inde`
- L52 [posix-shell] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")`
- L52 [repo-script] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")`
- L101 [monorepo-path] `git worktree add -b feat-008-mcp-security .claude/worktrees/feat-008-mcp-security HEAD`
- L102 [monorepo-path] `cd .claude/worktrees/feat-008-mcp-security`
- L110 [monorepo-path] `git worktree add -b task-042-prowler .claude/worktrees/task-042-prowler HEAD`
- L111 [monorepo-path] `→ cd .claude/worktrees/task-042-prowler && /sdd-start TASK-042`
- L113 [monorepo-path] `git worktree add -b task-043-trivy .claude/worktrees/task-043-trivy HEAD`
- L114 [monorepo-path] `→ cd .claude/worktrees/task-043-trivy && /sdd-start TASK-043`

### .agent/workflows/sdd-proposal.md

- L29 [org-data] `/sdd-proposal NAV-8421                          # Jira key`
- L32 [org-data] `/sdd-proposal NAV-8421 --mode=investigation     # force mode`
- L33 [org-data] `/sdd-proposal NAV-8421 --mode=enrichment`
- L34 [org-data] `/sdd-proposal NAV-8421 --no-gate                # skip user gates (autopilot mode)`
- L36 [org-data] `/sdd-proposal NAV-8421 --budget=loose           # tight | default | loose`
- L37 [org-data] `/sdd-proposal NAV-8421 --no-parallel`
- L59 [posix-shell] `REPO_ROOT=$(pwd)`
- L530 [repo-script] ``scripts/sdd/sdd_meta.py`, unknown values warn); `tags`: 2–6 kebab-case keywords.`

### .agent/workflows/sdd-spec.md

- L30 [repo-script] `reserved via `scripts/sdd/reserve_ids.py` (FEAT-387) — a git-native`
- L169 [repo-script] ``scripts.sdd.sdd_meta.resolve_flow()` — explicit `--type`/`--base-branch``
- L177 [posix-shell] `META=$(python -c "`
- L179 [repo-script] `from scripts.sdd.sdd_meta import resolve_flow`
- L186 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L187 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L208 [branch-literal] `(FEAT-187). Use `base_branch: staging` when applying stabilization fixes to a`
- L260 [claude-md-ref] `> ban and same reason as for code review (`CLAUDE.md`, "Adversarial Second`
- L265 [posix-shell] `REPO_ROOT="$(pwd)"                                   # /sdd-spec always runs from the repo root (§2d)`
- L267 [posix-shell] `RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"`
- L272 [external-tool] `# stdin MUST be redirected: without a TTY `codex exec` prints "Reading additional`
- L281 [posix-shell] `PROBE_TEXT="$(cat "$DR/probe.txt" 2>/dev/null | tr -d '[:space:]')"`
- L285 [external-tool] `CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"`
- L285 [posix-shell] `CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"`
- L286 [repo-script] `python -m scripts.sdd.spec_tools init-run "$DR" --model "$MODEL" --codex-version "$CODEX_VERSION" --probe-file "$DR/probe.txt"`
- L312 [repo-script] `python -m scripts.sdd.spec_tools render-brief "$DR" || SKIP_REASON="brief rendering failed"`
- L324 [posix-shell] `STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L332 [posix-shell] `ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L334 [repo-script] `python -m scripts.sdd.spec_tools stamp-run "$DR" --started-at "$STARTED_AT" --ended-at "$ENDED_AT" --exit-code "$rc"`
- L346 [repo-script] `python -m scripts.sdd.spec_tools validate-suggestions "$DR" || SKIP_REASON="suggestions.json failed schema validation"`
- L353 [repo-script] `python -m scripts.sdd.spec_tools check-path "<path>" --root "$REPO_ROOT" \`
- L458 [branch-literal] `base_branch: dev     # or: staging (release freeze)`
- L469 [repo-script] `in `scripts/sdd/sdd_meta.py` (unknown values warn).`
- L483 [posix-shell] `EXISTING=$(python -m scripts.sdd.spec_tools existing-feature-id "<feature-name>")`
- L483 [repo-script] `EXISTING=$(python -m scripts.sdd.spec_tools existing-feature-id "<feature-name>")`
- L491 [posix-shell] `FEAT_ID=$(python -m scripts.sdd.reserve_ids --kind feature --count 1 \`
- L491 [repo-script] `FEAT_ID=$(python -m scripts.sdd.reserve_ids --kind feature --count 1 \`
- L527 [repo-script] ``tags` (FEAT-576) — `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; print(parse_taxonomy(Path('<spec>')))"``
- L617 [repo-script] `python -m scripts.sdd.spec_tools commit-intake "$STAGE/intake.json" --feat-id "$FEAT_ID"`
- L653 [monorepo-path] `.claude/worktrees/feat-<FEAT-ID>-<feature-name> HEAD`

### .agent/workflows/sdd-start.md

- L32 [posix-shell] `[[ "$(basename "$f")" == "_orphans.json" ]] && continue`
- L65 [posix-shell] `WT=$(python -m scripts.sdd.ensure_worktree \`
- L65 [repo-script] `WT=$(python -m scripts.sdd.ensure_worktree \`
- L75 [branch-literal] `from `origin/main`.`
- L94 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L96 [external-tool] `jq --arg id "<TASK-NNN>" --arg now "$NOW" '`
- L121 [posix-shell] `python3 - "<TASK-NNN>" "<feature-slug>" <<'PYEOF' || true`
- L243 [repo-script] `python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.`
- L255 [repo-script] `> `scripts/sdd/close_task.sh` does the move with `git mv` and HARD-VERIFIES that`
- L261 [repo-script] `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`
- L294 [repo-script] `- Frontmatter parser: `scripts/sdd/sdd_meta.py``

### .agent/workflows/sdd-status.md

- L32 [external-tool] `ALL=$(jq -s '.' sdd/tasks/index/*.json)`
- L32 [posix-shell] `ALL=$(jq -s '.' sdd/tasks/index/*.json)`
- L44 [posix-shell] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L44 [repo-script] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L45 [external-tool] `ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)`
- L45 [posix-shell] `ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)`
- L57 [posix-shell] `FEATURES=$(python -m scripts.sdd.worktree_status --reconcile --json 2>/dev/null || echo "[]")`
- L57 [repo-script] `FEATURES=$(python -m scripts.sdd.worktree_status --reconcile --json 2>/dev/null || echo "[]")`
- L58 [posix-shell] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")   # health, for §5`
- L58 [repo-script] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")   # health, for §5`
- L210 [repo-script] `- Worktree reconciliation: `scripts/sdd/worktree_status.py` (`--reconcile`)`

### .agent/workflows/sdd-task.md

- L31 [repo-script] ``scripts/sdd/check_task_graph.py` on the index before committing (§4b).`
- L32 [repo-script] `- **`TASK-<NNN>` numbers are reserved via `scripts/sdd/reserve_ids.py``
- L51 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L51 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L52 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L53 [posix-shell] `BASE=$(echo "$META" | awk '{print $2}')`
- L84 [branch-literal] `(FEAT-187). Use `base_branch: staging` when decomposing stabilization fixes for a`
- L253 [posix-shell] `TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> \`
- L253 [repo-script] `TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> \`
- L375 [posix-shell] `mkdir -p "$(dirname "$INDEX")"`
- L408 [repo-script] `python -m scripts.sdd.cache_test_contract --spec <spec-path> --index sdd/tasks/index/<feature-slug>.json`
- L430 [monorepo-path] `- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q``
- L448 [monorepo-path] ``"sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig"`).`
- L461 [monorepo-path] `"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",`
- L474 [repo-script] `python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature-slug>.json`

### .agent/workflows/sdd-tojira.md

- L17 [org-data] `/sdd-tojira sdd/specs/jira-oauth.spec.md --ticket NAV-8036   # link to existing ticket`
- L21 [org-data] `/sdd-tojira FEAT-071 --ticket NAV-8036 --with-subtasks       # full combo`
- L61 [org-data] `#   JIRA_INSTANCE  — e.g. https://trocglobal.atlassian.net/`
- L66 [posix-shell] `#   eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L95 [org-data] `User passed --ticket NAV-8036`
- L96 [org-data] `→ MODE = UPDATE, JIRA_KEY = NAV-8036`
- L99 [org-data] `Spec frontmatter contains `jira: NAV-8036``
- L100 [org-data] `OR spec body contains `**Jira**: [NAV-8036](...)``
- L101 [org-data] `→ MODE = UPDATE, JIRA_KEY = NAV-8036`
- L106 [org-data] `⚠️  Existing ticket found: NAV-8036 — "[FEAT-071] jira-oauth"`
- L127 [org-data] `Mode: UPDATE existing NAV-8036  |  CREATE new ticket`
- L145 [repo-script] `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; t = parse_taxonomy(Path('<spec>')); print(' '.join(sorted(set(t.projects +`
- L179 [external-tool] `TOTAL_SECONDS=$(jq '[.tasks[] |`
- L179 [posix-shell] `TOTAL_SECONDS=$(jq '[.tasks[] |`
- L222 [external-tool] `Extract the created ticket key: `JIRA_KEY=$(echo "$RESPONSE" | jq -r '.key')``
- L222 [posix-shell] `Extract the created ticket key: `JIRA_KEY=$(echo "$RESPONSE" | jq -r '.key')``
- L234 [org-data] `issue_key="NAV-8036",`
- L282 [org-data] `⚠️  NAV-8036 already has 2 subtasks:`
- L283 [org-data] `NAV-8037 — [TASK-001] OAuth callback handler`
- L284 [org-data] `NAV-8038 — [TASK-002] CredentialResolver abstraction`
- L344 [org-data] `**Jira**: [NAV-8036](https://trocglobal.atlassian.net/browse/NAV-8036)`
- L348 [org-data] `Or in YAML frontmatter: add `jira: NAV-8036`.`
- L359 [org-data] `"jira_key": "NAV-8037",`
- L360 [org-data] `"jira_parent": "NAV-8036"`
- L385 [org-data] `✅ Spec exported to Jira: NAV-8036 (created)`
- L386 [org-data] `https://trocglobal.atlassian.net/browse/NAV-8036`
- L393 [org-data] `NAV-8037 — [TASK-001] OAuth callback handler [S/4h]`
- L394 [org-data] `NAV-8038 — [TASK-002] CredentialResolver abstraction [M/8h]`
- L395 [org-data] `NAV-8039 — [TASK-003] JiraToolkit OAuth integration [M/8h]`
- L396 [org-data] `NAV-8040 — [TASK-004] Redis token storage [S/4h]`
- L408 [org-data] `✅ Spec synced to Jira: NAV-8036 (updated)`
- L409 [org-data] `https://trocglobal.atlassian.net/browse/NAV-8036`
- L434 [org-data] `jira_link_issues(inward="NAV-8036", outward="NAV-8037", link_type="is parent of")`

### .agents/agents/sdd-autopilot/agent.md

- L100 [org-data] `/sdd-fromjira NAV-8036`
- L101 [org-data] `/sdd-fromjira NAV-8036 --auto-approve    # skip manual spec approval (risky)`
- L102 [org-data] `/sdd-fromjira NAV-8036 --complexity=fix  # hint: simple fix, minimal Q&A`
- L113 [external-tool] `| jq '{`
- L263 [monorepo-path] `.claude/worktrees/feat-<FEAT-ID>-<slug> HEAD`
- L269 [org-data] `✅ /sdd-fromjira complete for NAV-8036`
- L271 [org-data] `Jira: NAV-8036 — "Add OAuth 2.0 support for JiraToolkit"`
- L274 [monorepo-path] `Worktree: .claude/worktrees/feat-071-jira-oauth`
- L279 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L283 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L326 [posix-shell] `WORKTREE_DIR=$(pwd)`
- L327 [posix-shell] `REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$WORKTREE_DIR")`
- L359 [posix-shell] `VERDICT=$(grep -oP '(?<=verdict:\s)(APPROVED|NEEDS_CHANGES)' .autopilot/review-report.md)`
- L362 [posix-shell] `echo "✅ Code review passed (iteration $((REVIEW_ITERATION + 1)))"`
- L366 [posix-shell] `echo "⚠️ Code review: NEEDS_CHANGES (iteration $((REVIEW_ITERATION + 1)))"`
- L375 [posix-shell] `REVIEW_ITERATION=$((REVIEW_ITERATION + 1))`
- L397 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L414 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L428 [external-tool] `PR_URL=$(gh pr create \`
- L428 [posix-shell] `PR_URL=$(gh pr create \`
- L429 [branch-literal] `--base dev \`
- L430 [posix-shell] `--head "$(git branch --show-current)" \`
- L431 [posix-shell] `--title "feat($FEAT_ID): $(cat sdd/specs/*.spec.md | head -1 | sed 's/# //')" \`
- L441 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=jira:\s)\S+' sdd/specs/*.spec.md || echo "")`
- L459 [posix-shell] `║  Jira review: $([ -n "$JIRA_KEY" ] && echo "✅" || echo "⏭ skipped") ║`
- L488 [org-data] `"jira_key": "NAV-8036",`
- L669 [monorepo-path] `- `from parrot_tools.toolkit import AbstractToolkit` — packages/ai-parrot-tools/src/parrot_tools/toolkit.py:15`
- L670 [monorepo-path] `- `from parrot.tools.manager import ToolManager` — packages/ai-parrot/src/parrot/tools/manager.py:1`
- L708 [org-data] `/sdd-fromjira NAV-8036`
- L711 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L721 [org-data] `/sdd-fromjira NAV-8036`
- L724 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L730 [org-data] `/pr-review <PR_URL> NAV-8036`
- L736 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L737 [external-tool] `tmux new -s feat-071 \`

### .agents/agents/sdd-ideation/agent.md

- L141 [branch-literal] `# - type: feature  (default)  → base_branch: dev (or any non-main branch)`
- L144 [branch-literal] `base_branch: dev`
- L153 [repo-script] ``KNOWN_PROJECTS` vocabulary in `scripts/sdd/sdd_meta.py`; when resuming an`

### .agents/agents/sdd-planner/agent.md

- L35 [monorepo-path] `4. **Create the worktree** at ``.claude/worktrees/feat-<id>-<slug>/```
- L37 [monorepo-path] ```git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> HEAD```
- L63 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",`

### .agents/agents/sdd-research/agent.md

- L49 [branch-literal] `/sdd-spec <slug> --type feature --base-branch dev --no-interview        # kind == "enhancement" | "new_feature"`
- L61 [repo-script] `python -m scripts.sdd.ensure_worktree --json \`
- L89 [org-data] `"jira_issue_key": "OPS-1234",`
- L93 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",`
- L103 [org-data] `"jira_issue_key": "OPS-1234",`
- L107 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",`

### .agents/agents/sdd-worker/agent.md

- L101 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L101 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L102 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L103 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L105 [posix-shell] `if [ "$(git rev-parse --absolute-git-dir)" != "$(cd "$(git rev-parse --git-common-dir)" && pwd)" ]; then`
- L127 [branch-literal] `spec declares `type: feature, base_branch: main`, abort with:`
- L149 [external-tool] `INDEX=$(jq -r --arg q "<query>" '`
- L149 [posix-shell] `INDEX=$(jq -r --arg q "<query>" '`
- L180 [posix-shell] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L180 [repo-script] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L192 [repo-script] `come from `scripts.sdd.sdd_meta.plan_worktree`.`
- L215 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L217 [external-tool] `jq --arg now "$NOW" '(.tasks[] | select(.status == "pending") | .status) = "in-progress" |`
- L288 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L294 [repo-script] `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`
- L328 [claude-md-ref] `and follow the project's conventions (from CLAUDE.md)?`
- L365 [monorepo-path] `Worktree: .claude/worktrees/<worktree-name>`
- L399 [monorepo-path] ``packages/ai-parrot/tests/flows/dev_loop/test_qa.py`). `DevelopmentNode``

### .agents/skills/sdd-brainstorm/SKILL.md

- L43 [repo-script] ``scripts/sdd/sdd_meta.py`; unknown values warn) and `tags` (2–6 kebab-case keywords) — FEAT-576.`
- L54 [branch-literal] `Defaults when unanswered: `type: feature`, `base_branch: dev`.`
- L58 [branch-literal] `- `type: hotfix` requires `base_branch: main`.`
- L59 [branch-literal] `- `type: feature` with `base_branch: main` is invalid. Stop and explain that`

### .agents/skills/sdd-brief/SKILL.md

- L15 [branch-literal] `Codex invocation: `$sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]`.`
- L25 [repo-script] `- Provision the worktree only through `python -m scripts.sdd.ensure_worktree`.`
- L32 [external-tool] `2. **Detect and fetch** the source: `cs:<n>` code-scanning alert (`gh api repos/{owner}/{repo}/code-scanning/alerts/<n>`; refuse when `dismissed` or `fixed`), G`
- L33 [branch-literal] `3. **Resolve base and identity.** Ledger sources base on dev; if `--base-branch main` was supplied stop with: `⚠️  Ledger-sourced briefs always base on dev; --b`
- L39 [repo-script] `9. **Provision**: `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`; capture `<wt>`.`
- L40 [repo-script] `10. **Write artifacts inside `<wt>`**: `sdd/briefs/<slug>.brief.md` from `sdd/templates/brief.md` (with `ledger_issue` for ledger sources), task files `sdd/brie`

### .agents/skills/sdd-codereview/SKILL.md

- L64 [external-tool] `- Run external reviewer (`codex exec review`) or spawn a dedicated read-only subagent.`

### .agents/skills/sdd-done/SKILL.md

- L94 [repo-script] `selector from `scripts.sdd.select_tests` with this feature's task files`
- L100 [repo-script] `- run `python -m scripts.sdd.check_e2e_closeout --spec <spec-path>`
- L117 [repo-script] ``scripts/sdd/check_e2e_closeout.py`, not here — the exit code is the`
- L131 [repo-script] ``python -m scripts.sdd.test_report decide-rerun --index sdd/tasks/index/<feature-slug>.json`;`
- L133 [posix-shell] ``timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree <wt> --index <idx> $(printf -- '--task-file %s ' <e`
- L133 [repo-script] ``timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree <wt> --index <idx> $(printf -- '--task-file %s ' <e`
- L134 [repo-script] `then `python -m scripts.sdd.test_report render --index <idx> --worktree <wt> --out "$TEST_REPORT_MD"``
- L147 [repo-script] ``scripts/sdd/close_task.sh <TASK-ID> <feature-slug> <verification>` inside`
- L155 [repo-script] `- run `scripts/sdd/heal_orphans.sh <feature-slug>` inside the worktree`
- L162 [repo-script] `- run `python -m scripts.sdd.close_resolved_issues --worktree <worktree>`
- L206 [external-tool] `- Without `--merge` (every flow, `main` included), run `gh pr create --base <base_branch> --head <branch>`; the PR body includes the`
- L207 [posix-shell] `rendered `## Tests` section (`$(cat "$TEST_REPORT_MD")`) after `<N>/<total> tasks verified.`.`
- L210 [repo-script] ``scripts/sdd/heal_orphans.sh <feature-slug>`, commit any staged orphan`
- L214 [branch-literal] `- verify feature branch is ancestor of `origin/main``
- L243 [monorepo-path] `Worktree removed: .claude/worktrees/<name>`
- L252 [repo-script] `- `scripts/sdd/sdd_meta.py``
- L253 [repo-script] `- `scripts/sdd/heal_orphans.sh``

### .agents/skills/sdd-fix/SKILL.md

- L41 [branch-literal] `- **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev``
- L42 [branch-literal] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L42 [external-tool] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L45 [branch-literal] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L45 [repo-script] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L47 [repo-script] ``python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `$sdd-done <FEAT-ID>` closes it out, including the issues its verified `

### .agents/skills/sdd-fromjira/SKILL.md

- L30 [branch-literal] `- Set flow type in frontmatter: `type: feature, base_branch: dev` (or `hotfix`/`main` for bug tickets).`
- L32 [repo-script] ``scripts/sdd/sdd_meta.py`; unknown values warn) and `tags` (2–6 kebab-case keywords) — FEAT-576.`

### .agents/skills/sdd-insight/SKILL.md

- L22 [repo-script] `Execute `scripts/sdd/insight.py` to produce a two-layer analytical report:`
- L29 [posix-shell] `- Always run within the virtual environment (`source .venv/bin/activate`).`
- L29 [venv-path] `- Always run within the virtual environment (`source .venv/bin/activate`).`
- L43 [posix-shell] `source .venv/bin/activate`
- L43 [venv-path] `source .venv/bin/activate`
- L45 [posix-shell] `insight_run_dir=$(mktemp -d artifacts/sdd-insight.XXXXXX)`
- L46 [repo-script] `python3 scripts/sdd/insight.py --evidence "$insight_run_dir/evidence.json" --sdd-dir sdd --no-open --quiet -o "$insight_run_dir/report.html" "${insight_args[@]}`
- L55 [repo-script] `python3 scripts/sdd/insight.py --analysis "$insight_run_dir/analysis.json" --analysis-evidence "$insight_run_dir/evidence.json" --sdd-dir sdd -o "$insight_run_d`
- L66 [repo-script] `- `scripts/sdd/insight.py``

### .agents/skills/sdd-next/SKILL.md

- L34 [repo-script] `- Optional `--project` / `--tag` (FEAT-576): get matching spec paths from `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only ...` and keep only indexe`
- L37 [repo-script] `- Additionally run `python -m scripts.sdd.worktree_status --json` for task-level progress and `ready_for_done` flags.`

### .agents/skills/sdd-proposal/SKILL.md

- L30 [posix-shell] `source -> research plan -> budgeted research -> synthesis -> review gate -> targeted Q&A -> proposal`
- L43 [repo-script] ``scripts/sdd/sdd_meta.py`; unknown values warn) and `tags` (2–6 kebab-case keywords) — FEAT-576.`

### .agents/skills/sdd-spec/SKILL.md

- L70 [repo-script] `4. Resolve flow metadata with `scripts.sdd.sdd_meta.resolve_flow()`:`
- L73 [branch-literal] `- default is `type: feature`, `base_branch: dev``
- L79 [monorepo-path] `- refuse if inside `.claude/worktrees/``
- L113 [repo-script] ``python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch <base_branch> --label <feature-slug>`.`
- L173 [repo-script] `- `scripts/sdd/sdd_meta.py``
- L174 [repo-script] `- `scripts/sdd/reserve_ids.py``

### .agents/skills/sdd-start/SKILL.md

- L34 [repo-script] `- Use `scripts.sdd.finalize_task`; do not hand-copy active tasks to completed.`
- L44 [repo-script] `python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.`
- L58 [repo-script] `- run `python -m scripts.sdd.ensure_worktree --slug <feature-slug> --feature-id <FEAT-ID> --spec <spec-path> --index sdd/tasks/index/<feature-slug>.json``
- L133 [monorepo-path] ``packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py``
- L137 [repo-script] `- run `python -m scripts.sdd.finalize_task --evidence <path> --worktree <path> --expected-head <full HEAD SHA>``
- L162 [repo-script] `- `scripts/sdd/finalize_task.py``
- L163 [repo-script] `- `scripts/sdd/ensure_worktree.py``

### .agents/skills/sdd-status/SKILL.md

- L35 [repo-script] `- Optional `--project` / `--tag` (FEAT-576): get matching spec paths from `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only ...` and keep only indexe`
- L37 [repo-script] `- Run `python -m scripts.sdd.worktree_status --reconcile --json` — it merges each per-spec index on this branch with its worktree's index and returns one `Recon`
- L41 [repo-script] `- Run `python -m scripts.sdd.worktree_status --json` too for the health data the worktree panel (step 6) needs.`
- L63 [repo-script] `- `scripts/sdd/worktree_status.py` (FEAT-582) — `--reconcile` for the board, `--json` for the health panel`

### .agents/skills/sdd-task/SKILL.md

- L36 [monorepo-path] `- Must run from the main repo, not inside `.claude/worktrees/`.`
- L45 [repo-script] `1. Read spec frontmatter with `scripts.sdd.sdd_meta.parse()`:`
- L53 [monorepo-path] `- refuse if inside `.claude/worktrees/``
- L110 [repo-script] ``python -m scripts.sdd.cache_test_contract --spec <spec> --index <index>` (never hand-write `test_contract`). It accepts the flat`
- L144 [monorepo-path] ``"sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig"`).`
- L157 [monorepo-path] `"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",`
- L167 [repo-script] ``python -m scripts.sdd.reserve_ids --kind task --count <N> --base-branch <base_branch> --label <feature-slug>`.`
- L199 [repo-script] `- run `python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature-slug>.json``
- L239 [repo-script] `- `scripts/sdd/sdd_meta.py``
- L240 [repo-script] `- `scripts/sdd/reserve_ids.py``
- L241 [repo-script] `- `scripts/sdd/check_task_graph.py``

### .claude/agents/sdd-autopilot.md

- L91 [org-data] `/sdd-fromjira NAV-8036`
- L92 [org-data] `/sdd-fromjira NAV-8036 --auto-approve    # skip manual spec approval (risky)`
- L93 [org-data] `/sdd-fromjira NAV-8036 --complexity=fix  # hint: simple fix, minimal Q&A`
- L104 [external-tool] `| jq '{`
- L253 [repo-script] `python -m scripts.sdd.ensure_worktree --json \`
- L262 [org-data] `✅ /sdd-fromjira complete for NAV-8036`
- L264 [org-data] `Jira: NAV-8036 — "Add OAuth 2.0 support for JiraToolkit"`
- L267 [monorepo-path] `Worktree: .claude/worktrees/feat-071-jira-oauth`
- L272 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L276 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L319 [posix-shell] `WORKTREE_DIR=$(pwd)`
- L320 [posix-shell] `REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$WORKTREE_DIR")`
- L352 [posix-shell] `VERDICT=$(grep -oP '(?<=verdict:\s)(APPROVED|NEEDS_CHANGES)' .autopilot/review-report.md)`
- L355 [posix-shell] `echo "✅ Code review passed (iteration $((REVIEW_ITERATION + 1)))"`
- L359 [posix-shell] `echo "⚠️ Code review: NEEDS_CHANGES (iteration $((REVIEW_ITERATION + 1)))"`
- L368 [posix-shell] `REVIEW_ITERATION=$((REVIEW_ITERATION + 1))`
- L390 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L407 [posix-shell] `QA_VERDICT=$(grep -oP '(?<=verdict:\s)(PASS|FAIL)' .autopilot/qa-report.md)`
- L421 [external-tool] `PR_URL=$(gh pr create \`
- L421 [posix-shell] `PR_URL=$(gh pr create \`
- L422 [branch-literal] `--base dev \`
- L423 [posix-shell] `--head "$(git branch --show-current)" \`
- L424 [posix-shell] `--title "feat($FEAT_ID): $(cat sdd/specs/*.spec.md | head -1 | sed 's/# //')" \`
- L434 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=jira:\s)\S+' sdd/specs/*.spec.md || echo "")`
- L452 [posix-shell] `║  Jira review: $([ -n "$JIRA_KEY" ] && echo "✅" || echo "⏭ skipped") ║`
- L481 [org-data] `"jira_key": "NAV-8036",`
- L567 [external-tool] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L567 [posix-shell] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L567 [repo-script] `a. `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json); python -m scripts.sdd.select_tests --tier feature`
- L568 [posix-shell] `--base origin/<base_branch> $(printf -- '--task-file %s ' $TASK_FILES) --run` — the feature`
- L663 [monorepo-path] `- `from parrot_tools.toolkit import AbstractToolkit` — packages/ai-parrot-tools/src/parrot_tools/toolkit.py:15`
- L664 [monorepo-path] `- `from parrot.tools.manager import ToolManager` — packages/ai-parrot/src/parrot/tools/manager.py:1`
- L702 [org-data] `/sdd-fromjira NAV-8036`
- L705 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L715 [org-data] `/sdd-fromjira NAV-8036`
- L718 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L724 [org-data] `/pr-review <PR_URL> NAV-8036`
- L730 [monorepo-path] `cd .claude/worktrees/feat-071-jira-oauth`
- L731 [external-tool] `tmux new -s feat-071 \`

### .claude/agents/sdd-coder.md

- L9 [monorepo-path] `Context: sdd-worker prepared .claude/worktrees/feat-FEAT-549-x--pool/TASK-3115-a1 for TASK-3115.`
- L21 [monorepo-path] `command: 'python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook || exit 2'`
- L39 [uv-run] `- Run installed tools directly, or use `uv run --no-sync`. To edit declared dependencies`

### .claude/agents/sdd-ideation.md

- L179 [branch-literal] `# - type: feature  (default)  → base_branch: dev (or any non-main branch)`
- L194 [repo-script] ``KNOWN_PROJECTS` vocabulary in `scripts/sdd/sdd_meta.py`; when resuming an`

### .claude/agents/sdd-planner.md

- L57 [repo-script] `python -m scripts.sdd.ensure_worktree --json \`
- L73 [repo-script] `- The worktree name is whatever ``scripts.sdd.sdd_meta.plan_worktree```
- L88 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",`

### .claude/agents/sdd-research.md

- L9 [monorepo-path] `.claude/worktrees/feat-FEAT-<NNN>-<slug>/ (feature) or`
- L10 [monorepo-path] `.claude/worktrees/hotfix-<JIRA-KEY>-<slug>/ (hotfix, no id reserved).`
- L67 [branch-literal] `/sdd-spec <slug> --type feature --base-branch dev --no-interview        # kind == "enhancement" | "new_feature"`
- L79 [repo-script] `python -m scripts.sdd.ensure_worktree --json \`
- L106 [org-data] `"jira_issue_key": "OPS-1234",`
- L110 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",`
- L119 [org-data] `"jira_issue_key": "OPS-1234",`
- L124 [monorepo-path] `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",`

### .claude/agents/sdd-worker.md

- L32 [monorepo-path] `command: 'python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook || exit 2'`
- L52 [uv-run] `- Run installed tools directly, or use `uv run --no-sync`. To edit declared dependencies`
- L65 [monorepo-path] `- The primary checkout's `.claude/worktrees/` and `.parrot/ledger/` are the only writable`
- L152 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L152 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L153 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L154 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L156 [posix-shell] `if [ "$(git rev-parse --absolute-git-dir)" != "$(cd "$(git rev-parse --git-common-dir)" && pwd)" ]; then`
- L178 [branch-literal] `spec declares `type: feature, base_branch: main`, abort with:`
- L200 [external-tool] `INDEX=$(jq -r --arg q "<query>" '`
- L200 [posix-shell] `INDEX=$(jq -r --arg q "<query>" '`
- L226 [external-tool] `jq --arg id "HOTFIX-<KEY>-<N>" --arg now "$NOW" \`
- L251 [posix-shell] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L251 [repo-script] `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \`
- L263 [repo-script] `come from `scripts.sdd.sdd_meta.plan_worktree`.`
- L286 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L288 [external-tool] `jq --arg now "$NOW" '(.tasks[] | select(.status == "pending") | .status) = "in-progress" |`
- L382 [external-tool] ``TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json)`, then`
- L382 [posix-shell] ``TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json)`, then`
- L395 [repo-script] ``python -m scripts.sdd.finalize_task --evidence <path> --worktree <this worktree> --expected-head <post-merge HEAD>`.`
- L557 [repo-script] `python -m scripts.sdd.select_tests --tier merge --base origin/<base_branch> --index sdd/tasks/index/<feature-slug>.json`
- L580 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L586 [repo-script] `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`
- L608 [repo-script] ``python -m scripts.sdd.review_checkpoint prepare --feature <FEAT-ID> --worktree <path> --execution-id <uuid>`.`
- L627 [repo-script] ``python -m scripts.sdd.review_checkpoint validate --feature <FEAT-ID> --worktree <path> --execution-id <uuid>`
- L650 [claude-md-ref] `and follow the project's conventions (from CLAUDE.md)?`
- L726 [monorepo-path] `Worktree: .claude/worktrees/<worktree-name>`
- L733 [monorepo-path] `administration under the primary checkout's .claude/worktrees/ — or`
- L763 [monorepo-path] ``packages/ai-parrot/tests/flows/dev_loop/test_qa.py`). `DevelopmentNode``

### .claude/commands/sdd-brainstorm.md

- L74 [branch-literal] `- `type: hotfix` REQUIRES `base_branch: main`.`
- L75 [branch-literal] `- `type: feature` with `base_branch: main` is NOT allowed — use `staging` or `dev`.`
- L87 [branch-literal] `base_branch: dev | staging   # for type=feature (defaults to dev)`
- L92 [branch-literal] `If the user does not answer, default to `type: feature, base_branch: dev`.`
- L211 [monorepo-path] `(`packages/<dist>/…` → `<dist>`; `packages/ai-parrot-server/ui/` → `admin-ui`;`
- L215 [repo-script] `is `KNOWN_PROJECTS` in `scripts/sdd/sdd_meta.py`; an unknown value is allowed`
- L281 [claude-md-ref] `- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`

### .claude/commands/sdd-brief.md

- L10 [branch-literal] `/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]`
- L18 [repo-script] ``python -m scripts.sdd.ensure_worktree`.`
- L40 [external-tool] `| Code-scanning alert | `cs:<n>` or a GitHub `/security/code-scanning/<n>` URL | `gh api repos/{owner}/{repo}/code-scanning/alerts/<n>` |`
- L41 [external-tool] `| GitHub issue | issue URL or `owner/repo#<n>` | `gh issue view <n> --repo <owner>/<repo> --json number,title,body,labels,state,url` |`
- L42 [external-tool] `| GitHub pull request | PR URL or `owner/repo!<n>` | `gh pr view <n> --repo <owner>/<repo> --json number,title,body,files,state,url` |`
- L55 [branch-literal] ``--base-branch main`, stop with this exact message:`
- L58 [branch-literal] `⚠️  Ledger-sourced briefs always base on dev; --base-branch main is refused.`
- L64 [posix-shell] `source title or text.`
- L132 [repo-script] `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`
- L151 [repo-script] ``scripts.sdd.brief_meta.write_brief_index`, then validate its graph:`
- L154 [repo-script] `python -m scripts.sdd.check_task_graph <wt>/sdd/briefs/<slug>.index.json`

### .claude/commands/sdd-codereview.md

- L116 [external-tool] `codex commands:`
- L119 [external-tool] `codex exec review --uncommitted`
- L122 [branch-literal] `codex exec review --base dev`
- L122 [external-tool] `codex exec review --base dev`
- L125 [external-tool] `codex exec review --commit <sha>`
- L128 [external-tool] `codex exec --sandbox read-only -o artifacts/reviews/<task>-codex.txt \`
- L132 [external-tool] `codex exec resume --last "<neutral follow-up question>"`

### .claude/commands/sdd-done.md

- L71 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L71 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L72 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L73 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L74 [posix-shell] `CURRENT_BRANCH=$(git branch --show-current)`
- L79 [posix-shell] `MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)`
- L82 [posix-shell] `if [[ "$(git rev-parse --path-format=absolute --git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ]]; then`
- L174 [external-tool] `if grep -q '^\[tool\.black\]' "$WT/pyproject.toml"; then (cd "$WT" && black -q "${PY[@]}"); fi`
- L184 [external-tool] ``except Exception`), run `TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");`
- L184 [posix-shell] ``except Exception`), run `TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");`
- L185 [repo-script] `python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT" \`
- L187 [posix-shell] `$(printf -- '--task-file %s ' $TASK_FILES) --run` before committing.`
- L206 [posix-shell] `GATE_JSON=$(python -m scripts.sdd.check_e2e_closeout \`
- L206 [repo-script] `GATE_JSON=$(python -m scripts.sdd.check_e2e_closeout \`
- L238 [repo-script] `in `scripts/sdd/check_e2e_closeout.py` and is proven by`
- L252 [posix-shell] `TEST_REPORT_MD="${SDD_TEST_REPORT_DIR:-/tmp/claude-$(id -u)/sdd-tests}/FEAT-<ID>/pr-tests.md"`
- L253 [posix-shell] `mkdir -p "$(dirname "$TEST_REPORT_MD")"`
- L257 [posix-shell] `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")`
- L257 [repo-script] `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")`
- L264 [repo-script] `timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> \`
- L265 [posix-shell] `--worktree "$WT" --index "$IDX" $(printf -- '--task-file %s ' <every task file of the index>) \`
- L277 [repo-script] `python -m scripts.sdd.test_report render --index "$IDX" --worktree "$WT" --out "$TEST_REPORT_MD"`
- L291 [monorepo-path] `Worktree: .claude/worktrees/feat-<ID>-<slug>`
- L343 [repo-script] `> `scripts/sdd/close_task.sh` — **inside the worktree, on the feature branch**.`
- L351 [posix-shell] `NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L356 [external-tool] `STATUS=$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .status' "$WORKTREE_PATH/$INDEX")`
- L356 [posix-shell] `STATUS=$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .status' "$WORKTREE_PATH/$INDEX")`
- L364 [repo-script] `(cd "$WORKTREE_PATH" && scripts/sdd/close_task.sh "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION")`
- L367 [external-tool] `jq --arg id "$TASK_ID" '(.tasks[] | select(.id == $id) | .status) = "done-with-issues"' \`
- L371 [external-tool] `jq --arg id "$TASK_ID" --arg ver "$VERIFICATION" '`
- L379 [repo-script] `(cd "$WORKTREE_PATH" && scripts/sdd/heal_orphans.sh "$FEATURE_SLUG")`
- L382 [external-tool] `jq --arg now "$NOW" '`
- L414 [repo-script] `(cd "$WORKTREE_PATH" && python -m scripts.sdd.close_resolved_issues \`
- L451 [posix-shell] `BLOCKERS_OUTPUT=$(wikitoolkit ledger blockers "$FEAT_ID" 2>&1)`
- L507 [posix-shell] `EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)`
- L508 [posix-shell] `LOG_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export-log 2>&1)`
- L509 [posix-shell] `ROTATE_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger rotate-log --older-than-days 30 2>&1)`
- L528 [posix-shell] `ATTEMPT=$((ATTEMPT + 1))`
- L558 [external-tool] `gh pr create \`
- L562 [posix-shell] `--body "$(cat <<EOF`
- L571 [posix-shell] `$(cat "$TEST_REPORT_MD")`
- L584 [external-tool] `gh pr create --base "$BASE_BRANCH" --head "$BRANCH" \`
- L610 [posix-shell] `cat <<EOF`
- L636 [repo-script] `> the feature branch in Step 7, and CI's `scripts/sdd/check_task_state.py``
- L640 [repo-script] `scripts/sdd/heal_orphans.sh <feature-slug>`
- L660 [branch-literal] `staging` / `git checkout dev` and merges in the current checkout. Inside a`
- L680 [branch-literal] `**Pre-flight (run once):** verify the hotfix landed on `origin/main`:`
- L683 [branch-literal] `if ! git merge-base --is-ancestor "feat-<FEAT-ID>-<slug>" origin/main; then`
- L684 [branch-literal] `echo "⚠️  feat-<FEAT-ID>-<slug> is not yet an ancestor of origin/main."`
- L692 [branch-literal] `git checkout staging`
- L696 [branch-literal] `git push origin staging`
- L702 [posix-shell] `cat <<EOF`
- L706 [branch-literal] `git checkout staging`
- L710 [branch-literal] `git push origin staging`
- L719 [branch-literal] `git checkout dev`
- L723 [branch-literal] `git push origin dev`
- L729 [posix-shell] `cat <<EOF`
- L733 [branch-literal] `git checkout dev`
- L737 [branch-literal] `git push origin dev`
- L745 [branch-literal] `git checkout main`
- L765 [org-data] `# Look for "**Jira**: [NAV-8036](...)" or a "jira:" metadata field in the spec`
- L766 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=\*\*Jira\*\*: \[)[A-Z]+-\d+' sdd/specs/<feature>.spec.md)`
- L769 [posix-shell] `JIRA_KEY=$(grep -oP '(?<=\| Key \| )[A-Z]+-\d+' sdd/proposals/<key>-*.brainstorm.md)`
- L781 [posix-shell] `eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L799 [posix-shell] `TRANSITIONS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \`
- L801 [external-tool] `echo "$TRANSITIONS" | jq '.transitions[] | {id, name}'`
- L811 [external-tool] `TRANSITION_ID=$(echo "$TRANSITIONS" | jq -r '`
- L811 [posix-shell] `TRANSITION_ID=$(echo "$TRANSITIONS" | jq -r '`
- L852 [posix-shell] `SUBTASKS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \`
- L854 [external-tool] `| jq -r '.fields.subtasks[].key')`
- L900 [monorepo-path] `Worktree removed: .claude/worktrees/feat-<ID>-<slug>`
- L916 [monorepo-path] `Worktree removed: .claude/worktrees/feat-<ID>-<slug>`
- L928 [org-data] `Jira: NAV-8036 → Done ✅`
- L939 [org-data] `{if --resolve-jira} Jira NAV-8036 → Done ✅ {end if}`
- L946 [repo-script] `- Frontmatter parser: `scripts/sdd/sdd_meta.py``

### .claude/commands/sdd-explain.md

- L25 [claude-md-ref] `Use these as *search starting points*. The codebase is the only authority — verify every claim against what you read. Read CLAUDE.md and any CONTEXT.md files to`

### .claude/commands/sdd-fix.md

- L36 [branch-literal] `- **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev``
- L37 [branch-literal] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L37 [external-tool] `edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.`
- L40 [branch-literal] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L40 [repo-script] `otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author`
- L42 [repo-script] ``python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `/sdd-done <FEAT-ID>` closes it out, including the issues its verified `

### .claude/commands/sdd-fromjira.md

- L17 [org-data] `/sdd-fromjira NAV-8036`
- L18 [org-data] `/sdd-fromjira NAV-8036 --complexity=fix       # minimal Q&A, straight to brainstorm`
- L19 [org-data] `/sdd-fromjira NAV-8036 --skip-qa              # use Jira description as-is (rare)`
- L44 [org-data] `jira_get_issue(issue_key="NAV-8036")`
- L50 [org-data] `#   JIRA_INSTANCE  — e.g. https://trocglobal.atlassian.net/`
- L55 [posix-shell] `#   eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L100 [external-tool] `AC=$(echo "$JIRA_RESPONSE" | jq -r ".fields.$FIELD // empty")`
- L100 [posix-shell] `AC=$(echo "$JIRA_RESPONSE" | jq -r ".fields.$FIELD // empty")`
- L132 [org-data] `📋 Jira Ticket: NAV-8036`
- L271 [branch-literal] `base_branch: dev`
- L274 [org-data] `jira: NAV-8036`
- L283 [branch-literal] `Validation rule: `type: hotfix` REQUIRES `base_branch: main`. The user`
- L352 [claude-md-ref] `- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`

### .claude/commands/sdd-insight.md

- L12 [repo-script] `1. **Measure (deterministic).** `scripts/sdd/insight.py` parses Claude Code transcripts,`
- L23 [posix-shell] `> **Always activate the venv first** (project rule): `source .venv/bin/activate`.`
- L23 [venv-path] `> **Always activate the venv first** (project rule): `source .venv/bin/activate`.`
- L42 [posix-shell] `source .venv/bin/activate`
- L42 [venv-path] `source .venv/bin/activate`
- L51 [repo-script] `python3 scripts/sdd/insight.py \`
- L85 [repo-script] `python3 scripts/sdd/insight.py \`

### .claude/commands/sdd-next.md

- L31 [external-tool] `TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)`
- L31 [posix-shell] `TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)`
- L39 [posix-shell] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L39 [repo-script] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L40 [external-tool] `TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/inde`
- L40 [posix-shell] `TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/inde`
- L52 [posix-shell] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")`
- L52 [repo-script] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")`
- L101 [monorepo-path] `git worktree add -b feat-008-mcp-security .claude/worktrees/feat-008-mcp-security HEAD`
- L102 [monorepo-path] `cd .claude/worktrees/feat-008-mcp-security`
- L110 [monorepo-path] `git worktree add -b task-042-prowler .claude/worktrees/task-042-prowler HEAD`
- L111 [monorepo-path] `→ cd .claude/worktrees/task-042-prowler && /sdd-start TASK-042`
- L113 [monorepo-path] `git worktree add -b task-043-trivy .claude/worktrees/task-043-trivy HEAD`
- L114 [monorepo-path] `→ cd .claude/worktrees/task-043-trivy && /sdd-start TASK-043`
- L155 [claude-md-ref] `- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`

### .claude/commands/sdd-proposal.md

- L29 [org-data] `/sdd-proposal NAV-8421                          # Jira key`
- L32 [org-data] `/sdd-proposal NAV-8421 --mode=investigation     # force mode`
- L33 [org-data] `/sdd-proposal NAV-8421 --mode=enrichment`
- L34 [org-data] `/sdd-proposal NAV-8421 --no-gate                # skip user gates (autopilot mode)`
- L36 [org-data] `/sdd-proposal NAV-8421 --budget=loose           # tight | default | loose`
- L37 [org-data] `/sdd-proposal NAV-8421 --no-parallel`
- L59 [posix-shell] `REPO_ROOT=$(pwd)`
- L530 [repo-script] ``scripts/sdd/sdd_meta.py`, unknown values warn); `tags`: 2–6 kebab-case keywords.`
- L670 [claude-md-ref] `- Worktree policy:          `CLAUDE.md` (section "Worktree Policy")`

### .claude/commands/sdd-spec.md

- L26 [repo-script] `reserved via `scripts/sdd/reserve_ids.py` (FEAT-387) — a git-native`
- L165 [repo-script] ``scripts.sdd.sdd_meta.resolve_flow()` — explicit `--type`/`--base-branch``
- L173 [posix-shell] `META=$(python -c "`
- L175 [repo-script] `from scripts.sdd.sdd_meta import resolve_flow`
- L182 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L183 [posix-shell] `BASE_BRANCH=$(echo "$META" | awk '{print $2}')`
- L204 [branch-literal] `(FEAT-187). Use `base_branch: staging` when applying stabilization fixes to a`
- L256 [claude-md-ref] `> ban and same reason as for code review (`CLAUDE.md`, "Adversarial Second`
- L261 [posix-shell] `REPO_ROOT="$(pwd)"                                   # /sdd-spec always runs from the repo root (§2d)`
- L263 [posix-shell] `RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"`
- L268 [external-tool] `# stdin MUST be redirected: without a TTY `codex exec` prints "Reading additional`
- L277 [posix-shell] `PROBE_TEXT="$(cat "$DR/probe.txt" 2>/dev/null | tr -d '[:space:]')"`
- L281 [external-tool] `CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"`
- L281 [posix-shell] `CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"`
- L282 [repo-script] `python -m scripts.sdd.spec_tools init-run "$DR" --model "$MODEL" --codex-version "$CODEX_VERSION" --probe-file "$DR/probe.txt"`
- L308 [repo-script] `python -m scripts.sdd.spec_tools render-brief "$DR" || SKIP_REASON="brief rendering failed"`
- L320 [posix-shell] `STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L328 [posix-shell] `ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`
- L330 [repo-script] `python -m scripts.sdd.spec_tools stamp-run "$DR" --started-at "$STARTED_AT" --ended-at "$ENDED_AT" --exit-code "$rc"`
- L342 [repo-script] `python -m scripts.sdd.spec_tools validate-suggestions "$DR" || SKIP_REASON="suggestions.json failed schema validation"`
- L349 [repo-script] `python -m scripts.sdd.spec_tools check-path "<path>" --root "$REPO_ROOT" \`
- L454 [branch-literal] `base_branch: dev     # or: staging (release freeze)`
- L465 [repo-script] `in `scripts/sdd/sdd_meta.py` (unknown values warn).`
- L479 [posix-shell] `EXISTING=$(python -m scripts.sdd.spec_tools existing-feature-id "<feature-name>")`
- L479 [repo-script] `EXISTING=$(python -m scripts.sdd.spec_tools existing-feature-id "<feature-name>")`
- L487 [posix-shell] `FEAT_ID=$(python -m scripts.sdd.reserve_ids --kind feature --count 1 \`
- L487 [repo-script] `FEAT_ID=$(python -m scripts.sdd.reserve_ids --kind feature --count 1 \`
- L523 [repo-script] ``tags` (FEAT-576) — `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; print(parse_taxonomy(Path('<spec>')))"``
- L613 [repo-script] `python -m scripts.sdd.spec_tools commit-intake "$STAGE/intake.json" --feat-id "$FEAT_ID"`
- L649 [monorepo-path] `.claude/worktrees/feat-<FEAT-ID>-<feature-name> HEAD`
- L661 [claude-md-ref] `- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`

### .claude/commands/sdd-start.md

- L35 [posix-shell] `[[ "$(basename "$f")" == "_orphans.json" ]] && continue`
- L68 [posix-shell] `WT=$(python -m scripts.sdd.ensure_worktree \`
- L68 [repo-script] `WT=$(python -m scripts.sdd.ensure_worktree \`
- L78 [branch-literal] `from `origin/main`.`
- L97 [posix-shell] `NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`
- L99 [external-tool] `jq --arg id "<TASK-NNN>" --arg now "$NOW" '`
- L124 [posix-shell] `python3 - "<TASK-NNN>" "<feature-slug>" <<'PYEOF' || true`
- L270 [repo-script] `python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.`
- L282 [repo-script] `> `scripts/sdd/close_task.sh` does the move with `git mv` and HARD-VERIFIES that`
- L288 [repo-script] `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`
- L321 [repo-script] `- Frontmatter parser: `scripts/sdd/sdd_meta.py``

### .claude/commands/sdd-status.md

- L32 [external-tool] `ALL=$(jq -s '.' sdd/tasks/index/*.json)`
- L32 [posix-shell] `ALL=$(jq -s '.' sdd/tasks/index/*.json)`
- L44 [posix-shell] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L44 [repo-script] `SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)`
- L45 [external-tool] `ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)`
- L45 [posix-shell] `ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)`
- L57 [posix-shell] `FEATURES=$(python -m scripts.sdd.worktree_status --reconcile --json 2>/dev/null || echo "[]")`
- L57 [repo-script] `FEATURES=$(python -m scripts.sdd.worktree_status --reconcile --json 2>/dev/null || echo "[]")`
- L58 [posix-shell] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")   # health, for §5`
- L58 [repo-script] `WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")   # health, for §5`
- L210 [repo-script] `- Worktree reconciliation: `scripts/sdd/worktree_status.py` (`--reconcile`)`

### .claude/commands/sdd-task.md

- L35 [repo-script] ``scripts/sdd/check_task_graph.py` on the index before committing (§4b).`
- L36 [repo-script] `- **`TASK-<NNN>` numbers are reserved via `scripts/sdd/reserve_ids.py``
- L55 [posix-shell] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L55 [repo-script] `META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")`
- L56 [posix-shell] `TYPE=$(echo "$META" | awk '{print $1}')`
- L57 [posix-shell] `BASE=$(echo "$META" | awk '{print $2}')`
- L65 [claude-md-ref] `(sub-features extend a parent feature branch — see `CLAUDE.md`).`
- L88 [branch-literal] `(FEAT-187). Use `base_branch: staging` when decomposing stabilization fixes for a`
- L257 [posix-shell] `TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> \`
- L257 [repo-script] `TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> \`
- L379 [posix-shell] `mkdir -p "$(dirname "$INDEX")"`
- L412 [repo-script] `python -m scripts.sdd.cache_test_contract --spec <spec-path> --index sdd/tasks/index/<feature-slug>.json`
- L434 [monorepo-path] `- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q``
- L452 [monorepo-path] ``"sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig"`).`
- L465 [monorepo-path] `"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",`
- L478 [repo-script] `python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature-slug>.json`

### .claude/commands/sdd-tojira.md

- L17 [org-data] `/sdd-tojira sdd/specs/jira-oauth.spec.md --ticket NAV-8036   # link to existing ticket`
- L21 [org-data] `/sdd-tojira FEAT-071 --ticket NAV-8036 --with-subtasks       # full combo`
- L61 [org-data] `#   JIRA_INSTANCE  — e.g. https://trocglobal.atlassian.net/`
- L66 [posix-shell] `#   eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"`
- L95 [org-data] `User passed --ticket NAV-8036`
- L96 [org-data] `→ MODE = UPDATE, JIRA_KEY = NAV-8036`
- L99 [org-data] `Spec frontmatter contains `jira: NAV-8036``
- L100 [org-data] `OR spec body contains `**Jira**: [NAV-8036](...)``
- L101 [org-data] `→ MODE = UPDATE, JIRA_KEY = NAV-8036`
- L106 [org-data] `⚠️  Existing ticket found: NAV-8036 — "[FEAT-071] jira-oauth"`
- L127 [org-data] `Mode: UPDATE existing NAV-8036  |  CREATE new ticket`
- L145 [repo-script] `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; t = parse_taxonomy(Path('<spec>')); print(' '.join(sorted(set(t.projects +`
- L179 [external-tool] `TOTAL_SECONDS=$(jq '[.tasks[] |`
- L179 [posix-shell] `TOTAL_SECONDS=$(jq '[.tasks[] |`
- L222 [external-tool] `Extract the created ticket key: `JIRA_KEY=$(echo "$RESPONSE" | jq -r '.key')``
- L222 [posix-shell] `Extract the created ticket key: `JIRA_KEY=$(echo "$RESPONSE" | jq -r '.key')``
- L234 [org-data] `issue_key="NAV-8036",`
- L282 [org-data] `⚠️  NAV-8036 already has 2 subtasks:`
- L283 [org-data] `NAV-8037 — [TASK-001] OAuth callback handler`
- L284 [org-data] `NAV-8038 — [TASK-002] CredentialResolver abstraction`
- L344 [org-data] `**Jira**: [NAV-8036](https://trocglobal.atlassian.net/browse/NAV-8036)`
- L348 [org-data] `Or in YAML frontmatter: add `jira: NAV-8036`.`
- L359 [org-data] `"jira_key": "NAV-8037",`
- L360 [org-data] `"jira_parent": "NAV-8036"`
- L385 [org-data] `✅ Spec exported to Jira: NAV-8036 (created)`
- L386 [org-data] `https://trocglobal.atlassian.net/browse/NAV-8036`
- L393 [org-data] `NAV-8037 — [TASK-001] OAuth callback handler [S/4h]`
- L394 [org-data] `NAV-8038 — [TASK-002] CredentialResolver abstraction [M/8h]`
- L395 [org-data] `NAV-8039 — [TASK-003] JiraToolkit OAuth integration [M/8h]`
- L396 [org-data] `NAV-8040 — [TASK-004] Redis token storage [S/4h]`
- L408 [org-data] `✅ Spec synced to Jira: NAV-8036 (updated)`
- L409 [org-data] `https://trocglobal.atlassian.net/browse/NAV-8036`
- L434 [org-data] `jira_link_issues(inward="NAV-8036", outward="NAV-8037", link_type="is parent of")`
- L447 [claude-md-ref] `- Auto-commit rule: `CLAUDE.md` (section "SDD Auto-Commit Rule")`

### .claude/hooks/sdd-worker-format.sh

- L1 [posix-shell] `#!/usr/bin/env bash`
- L17 [posix-shell] `set -uo pipefail`
- L19 [posix-shell] `INPUT=$(cat)`
- L23 [external-tool] `AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')`
- L23 [posix-shell] `AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')`
- L24 [external-tool] `CWD=$(echo "$INPUT" | jq -r '.cwd // empty')`
- L24 [posix-shell] `CWD=$(echo "$INPUT" | jq -r '.cwd // empty')`
- L35 [posix-shell] `GIT_DIR=$(git rev-parse --git-dir)`
- L42 [posix-shell] `BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)`
- L52 [branch-literal] `# base for feature flows; fall back to the merge-base with origin/dev, and to`
- L54 [branch-literal] `BASE=$(git merge-base HEAD origin/dev 2>/dev/null \`
- L54 [posix-shell] `BASE=$(git merge-base HEAD origin/dev 2>/dev/null \`
- L57 [posix-shell] `CHANGED=$(git diff --name-only --diff-filter=ACMR "$BASE"...HEAD 2>/dev/null)`
- L59 [posix-shell] `CHANGED=$(git diff --name-only --diff-filter=ACMR HEAD~1 2>/dev/null)`
- L61 [posix-shell] `UNCOMMITTED=$(git status --porcelain | awk '{print $NF}')`
- L76 [venv-path] `for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \`
- L77 [posix-shell] `"$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin"; do`
- L77 [venv-path] `"$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin"; do`
- L79 [posix-shell] `VENV_BIN=$(cd "$candidate" && pwd)`
- L88 [posix-shell] `BLACK_OUT=$("$BLACK" --quiet "${FILES[@]}" 2>&1)`
- L110 [posix-shell] `SHA=$(git rev-parse --short HEAD)`
- L134 [posix-shell] `PYLINT_OUT=$(timeout 150 "$PYLINT" "${RC_ARG[@]}" --jobs=4 --score=y \`
- L142 [posix-shell] `SCORE=$(echo "$PYLINT_OUT" | grep -oE 'rated at [-0-9.]+' | tail -1 | awk '{print $3}')`
- L143 [posix-shell] `ERRORS=$(echo "$PYLINT_OUT" | grep -cE '^[^ ]+:[0-9]+:[0-9]+: E[0-9]{4}')`
- L144 [posix-shell] `WARNS=$(echo "$PYLINT_OUT" | grep -cE '^[^ ]+:[0-9]+:[0-9]+: [WC][0-9]{4}')`
- L157 [external-tool] `jq -cn --arg msg "sdd-worker post-run format: ${SUMMARY} ${PYLINT_SUMMARY}" \`

### .claude/rules/codebase-conventions.md

- L32 [monorepo-path] `- Core source root: `packages/ai-parrot/src/parrot/`. Satellite packages merge into the same `parrot.*` namespace (PEP 420).`
- L33 [monorepo-path] `- Concrete tools live in `packages/ai-parrot-tools/src/parrot_tools/` (`import parrot_tools.<x>`); only base machinery stays in `parrot/tools/`.`
- L35 [monorepo-path] `- Admin UI (Svelte 5 + Vite): `packages/ai-parrot-server/ui/`.`
- L38 [posix-shell] `- **Interactive shell** (humans, Claude Code, codex, agy): `source .venv/bin/activate` first; then `uv add` / `uv pip`, `pytest`, `ruff check`, `black`. Never r`
- L38 [venv-path] `- **Interactive shell** (humans, Claude Code, codex, agy): `source .venv/bin/activate` first; then `uv add` / `uv pip`, `pytest`, `ruff check`, `black`. Never r`

### .claude/rules/worktree-management.md

- L10 [claude-md-ref] `targeting `main`) lives in `CLAUDE.md` § Git Configuration — this file is the`
- L15 [monorepo-path] `- Always under `.claude/worktrees/` (git-ignored). Never `.worktrees/`, never a global directory.`
- L16 [repo-script] `- Names come from `scripts.sdd.sdd_meta.plan_worktree`, never invented:`
- L24 [posix-shell] `source .venv/bin/activate`
- L24 [venv-path] `source .venv/bin/activate`
- L25 [branch-literal] `python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN>   # feature → origin/dev`
- L25 [repo-script] `python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN>   # feature → origin/dev`
- L26 [branch-literal] `python -m scripts.sdd.ensure_worktree --slug <slug> --jira-key <JIRA-KEY>     # hotfix  → origin/main`
- L26 [repo-script] `python -m scripts.sdd.ensure_worktree --slug <slug> --jira-key <JIRA-KEY>     # hotfix  → origin/main`
- L27 [branch-literal] `python -m scripts.sdd.ensure_worktree --slug <slug> --brief-key <KEY> --base-branch main|dev   # /sdd-brief → hotfix-<KEY>-<slug> / fix-<KEY>-<slug>`
- L27 [repo-script] `python -m scripts.sdd.ensure_worktree --slug <slug> --brief-key <KEY> --base-branch main|dev   # /sdd-brief → hotfix-<KEY>-<slug> / fix-<KEY>-<slug>`
- L52 [monorepo-path] `- The shared `.venv` is editable-installed against the **main checkout**, so a bare `pytest` inside a worktree imports the wrong branch. Prefix with `PYTHONPATH`
- L53 [uv-run] `- Shared environments are read/execute-only for worktree agents. Use installed tools directly or `uv run --no-sync`; `uv add --no-sync` may update scoped depend`
- L54 [monorepo-path] `- SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's `.claude/worktre`
- L54 [posix-shell] `- SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's `.claude/worktre`
- L61 [external-tool] `- Ad-hoc lane: `gh pr create --base <base_branch> --head <branch> --title "..." --body "..."` — never against `main` for a feature. If `gh` is missing or unauth`
- L67 [monorepo-path] `git worktree remove .claude/worktrees/<name>`
- L73 [monorepo-path] ``.claude/worktrees/` that `git worktree list` no longer knows about —`

### sdd/WORKFLOW.md

- L36 [repo-script] ``FEAT-<NNN>` via `scripts/sdd/reserve_ids.py` (not for hotfixes).`
- L52 [repo-script] `creates/reuses the feature worktree via `python -m scripts.sdd.ensure_worktree`,`
- L54 [repo-script] `with `scripts/sdd/close_task.sh`, which moves the file to`
- L108 [branch-literal] `base_branch: dev     # for feature: dev or staging; for hotfix: must be "main"`
- L148 [repo-script] `python -m scripts.sdd.doc_taxonomy [--root .] [--kind spec|brainstorm|proposal|all] \`
- L170 [repo-script] `python -m scripts.sdd.backfill_taxonomy [--root .] [--kind spec|brainstorm|proposal|all] \`
- L192 [branch-literal] `git checkout dev`
- L196 [branch-literal] `git checkout -B staging origin/dev`
- L200 [branch-literal] `git checkout staging`
- L202 [branch-literal] `git push origin staging`
- L213 [branch-literal] ``type: feature, base_branch: staging`.`
- L237 [repo-script] `> split into per-spec files by `scripts/sdd/migrate_index.py`. The original`
- L300 [repo-script] `- **`scripts/sdd/id_ledger.py`** — the `IdLedger` Pydantic model plus`
- L303 [repo-script] `- **`scripts/sdd/reserve_ids.py`** — the allocator `/sdd-task` and`
- L306 [repo-script] `python -m scripts.sdd.reserve_ids --kind task --count 8 \`
- L307 [branch-literal] `--base-branch dev --label <feature-slug>`
- L327 [repo-script] `- **`scripts/sdd/check_id_collisions.py`** — an independent, read-only`
- L376 [repo-script] `python -m scripts.sdd.install_hooks`
- L431 [repo-script] `4. **Update the index** — close tasks with `scripts/sdd/close_task.sh` (per-spec index), never the legacy monolith`

### sdd/templates/brainstorm.md

- L3 [branch-literal] `# - type: feature  (default)  → base_branch: dev (or any non-main branch)`
- L6 [branch-literal] `base_branch: dev`

### sdd/templates/design_research.prompt.md

- L3 [external-tool] `Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema`

### sdd/templates/intake.procedure.md

- L32 [posix-shell] `RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"`
- L85 [branch-literal] `1. **Flow type and base branch**: `type: feature | hotfix`, `base_branch: dev | main | staging``
- L87 [branch-literal] `- If `type: hotfix`, enforce `base_branch: main``
- L328 [repo-script] `Reserve the FEAT-ID as usual via `scripts/sdd/reserve_ids.py`. Write the reserved ID to `intake.json.feat_id`.`

### sdd/templates/proposal.md

- L11 [org-data] `jira_url: https://trocglobal.atlassian.net/browse/NAV-XXXX | null`
- L15 [branch-literal] `base_branch: dev`

### sdd/templates/spec.md

- L3 [branch-literal] `# - type: feature  (default)  → base_branch: dev (or any non-main branch)`
- L6 [branch-literal] `base_branch: dev`
- L171 [monorepo-path] `>       cwd: packages/ai-parrot-server/ui`

### sdd/templates/synthesis.prompt.md

- L85 [posix-shell] `source contains negation ("no genera", "doesn't work", "fails", "broken").`
- L165 [posix-shell] `source is too vague even after research`

### sdd/templates/task.md

- L280 [monorepo-path] `- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q``
- L329 [repo-script] `(`python -m scripts.sdd.ensure_worktree --slug <feature-slug> --feature-id FEAT-<NNN>`)`
- L344 [repo-script] `9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified``

## Missing tools on the generating host (linux)

- `black`

## Conclusions

> Generated on the FEAT-633 branch (behind `origin/dev`): a few twin rows differ from the Context oracle only
> because this branch lacks later dev commits (e.g. `.agents/skills/sdd-brief/SKILL.md` shows only `ensure_worktree`,
> `.agent/workflows/sdd-done.md` lacks `check_e2e_closeout`, `sdd-contract-probe` assets are absent). Regenerate from
> a worktree based on current `origin/dev` before TASK-4089 consumes the map.

1. **Helpers beyond the TASK-4085–4088 + TASK-4508 move list**: `insight` (only referenced by the not-shipped
   `/sdd-insight`, C22), `install_hooks`, `migrate_index`, `backfill_taxonomy`, `id_ledger`, `check_id_collisions`
   (all referenced only by `sdd/WORKFLOW.md`, which TASK-4089 rewrites). `review_checkpoint`, `spec_tools`,
   `worktree_status`, `doc_taxonomy` must be confirmed in the move lists when 4085–4088 land.
2. **External tools TASK-4091 must warn about** (`missing_tools`): `jq`, `gh`, `tmux`, `codex`, plus `black`/`pylint`
   where referenced; the install report should list whichever of them `shutil.which` cannot resolve.
3. **POSIX-only constructs** (`$(...)`, heredocs, `/tmp/`, `source`, `set -euo pipefail`, shell `jq` pipelines) are
   pervasive in the command/agent markdown; they cannot be made portable mechanically and must be documented as
   POSIX-first (Windows via WSL/Git Bash) unless TASK-4089 replaces them with `parrot sdd run <helper>` calls.
4. **C11a publication-safety lines TASK-4089 must rewrite**: every `org-data` finding (real Atlassian host / `NAV-<n>`
   keys) → `https://your-org.atlassian.net` and `PROJ-123`; every `claude-md-ref` finding → no `CLAUDE.md`
   references; every `branch-literal` finding → branch names read from `sdd/config.json` (TASK-4299) instead of
   literals. TASK-4090 gates CI with `--fail-on org-data,claude-md-ref,branch-literal`.
