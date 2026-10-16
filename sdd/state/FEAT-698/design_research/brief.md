<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
The full SDD pipeline (/sdd-brainstorm -> /sdd-spec -> /sdd-task) is sized for features. A hotfix — e.g. repairing a GitHub code-scanning alert — does not need three documents and two id reservations; it needs direct research, a short Q&A for the genuinely open decisions, one actionable document, and a worktree based on the right branch.

Today that need is partially served by /sdd-spec --type hotfix (FEAT-466): no FEAT/TASK id reservation, identity = Jira key or slug, worktree hotfix-<KEY>-<slug> from origin/main, /sdd-task normally skipped. But it is still spec-shaped (interview-first, feature-document template) rather than research-first, and /sdd-done refuses to open the PR against main, leaving a manual step.

A new command, /sdd-brief, must replace /sdd-spec --type hotfix with a purpose-built flow: research-first intake from several source kinds (including the work ledger), bounded Q&A, a single fused spec+task document (the "brief"), and a worktree whose base branch drives everything downstream. The dev-loop autonomous hotfix lane (the sdd-research agent and dev_loop hotfix code paths) migrates to this flow in the same feature — /sdd-spec --type hotfix is removed outright.

### Constraints and goals
Goals:
- One command from "here is a bug/alert/issue" to "worktree ready with an actionable brief inside it".
- Research-first: fetch the source artifact (gh api for code-scanning alerts), locate the code via the repo knowledge graph (symbol lookup, blast radius), pull ledger context for touched files, establish root cause BEFORE asking the user anything.
- Bounded Q&A: only decisions research could not settle, hard cap ~5 questions, --no-interview skips and records assumptions.
- A single brief document an implementer (human, sdd-worker, or sdd-coder) can execute without reading anything else.
- Optional task split using local ids HOTFIX-<KEY>-1..N — no reserve_ids.py calls.

Base-branch resolution (binding decisions):
- Ledger-sourced briefs are ALWAYS based on dev — never main; --base-branch main combined with a ledger source is refused.
- All other sources (code-scanning alert, GitHub issue, Jira, free text, file) default to main, with --base-branch available for exceptions (dev, staging).
- /sdd-done opens the PR itself in every flow, targeting the flow's base_branch (main for a hotfix brief, dev for regular features). Direct merge into main stays forbidden (--merge refused; the merge of the main PR is the only human act).

Constraints:
- Worktree rules unchanged: always under .claude/worktrees/, created from origin/<base_branch> via scripts.sdd.ensure_worktree, never HEAD; git worktree add -b X <path> origin/main auto-sets upstream so the command must run branch --unset-upstream immediately.
- The brief is committed INSIDE the worktree, never in the shared main checkout; it rides in the fix PR.
- FlowMeta (parrot.knowledge.wiki.ledger.sdd_meta) ships in the wikitoolkit wheel and must stay untouched — briefs bypass FlowMeta/resolve_flow entirely and use their own light frontmatter (kind: brief) parsed at command level.
- No new id kinds in sdd/tasks/.id_ledger.json; no FEAT/TASK reservation on the brief path.
- Identity when there is no Jira ticket: the slug (or the ledger id for ledger sources) is the KEY.

Anti-goals (failure even if it works):
- Any path by which the brief flow pushes to or merges into main directly.
- Writing or committing the brief in the shared main checkout.
- A quick flow that silently skips research and produces a guess-shaped brief.
- Reintroducing FEAT/TASK id reservation on the hotfix path.

### Recommended option / probable scope
CLI: /sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]

Source auto-detection: code-scanning URL/number (gh api), GitHub issue/PR URL, Jira key, work-ledger issue id (wikitoolkit ledger show + plan-fix, then ledger claim; always base dev), free text or file path (default base main).

Phases: 1) Research (fetch source artifact, locate code, root cause with file:line evidence); 2) bounded Q&A (<=5 questions, skippable); 3) worktree creation from origin/<base> (hotfix-<KEY>-<slug> for main, fix-<id>-<slug> for dev/ledger); 4) brief document written inside the worktree; 5) handoff instructions.

The brief: sdd/briefs/<slug>.brief.md with frontmatter (kind: brief, slug, base_branch, source, jira_issue_key, ledger_issue, created). Body: Problem, Root cause, Research findings, Decisions/Assumptions, Fix plan, Validation commands.

Task materialization: /sdd-brief materializes STANDARD task files (the sdd/templates/task.md shape: Codebase Contract, Acceptance Criteria, Validation Commands) under sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-N-<task-slug>.md inside the worktree — one for the single-task case, several when --split. A per-brief index at sdd/briefs/<slug>.index.json reuses the per-spec index schema (feature_id: null, tasks[].file pointing at the materialized task files). It deliberately does NOT live in sdd/tasks/index/ so repo-wide task tooling and CI never ingest HOTFIX-* ids, and a merged hotfix syncing main->dev cannot pollute the feature board. Task closure flips index status and fills the Completion Note in place — no active/->completed/ move.

Downstream unchanged: sdd-worker's planner and the parrot-sdd-coder MCP chunker/fidelity-gate consume the same task-file shape as today, zero Python changes in the coder pipeline.

Changes to existing commands: /sdd-spec removes --type hotfix; /sdd-done resolves briefs by slug/KEY via worktree scan, verifies via the per-brief index + brief Validation Commands, opens the PR itself against base_branch (main included), keeps refusing --merge into main, prints the ledger close command next to the PR link (closing only when the fix is confirmed merged); policy docs (CLAUDE.md, sdd-done.md, docs/sdd/WORKFLOW.md) change wording from "never opens a PR against main" to "never merges into main; opens the PR".

Dev-loop autonomous lane migration (in scope, hard cut): sdd-research prompt twins (.claude/agents/sdd-research.md AND packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md) replace the literal "/sdd-spec <slug> --type hotfix --base-branch main --no-interview" invocation with the /sdd-brief equivalent; dev_loop/nodes/development.py hotfix code paths (built on "hotfix => no per-spec index, feat_id == ''") are re-pointed at the per-brief index + materialized task files; dev_loop Pydantic contracts keep shape where possible, learning the brief's base_branch where hotfix=>main is hardcoded; final sweep removes every reference to --type hotfix; dev-loop hotfix-mode tests move to the brief shape in the same change.

### Verified code anchors (paths only — open them yourself)
.claude/commands/sdd-spec.md
.claude/commands/sdd-done.md
.claude/commands/sdd-task.md
.claude/commands/sdd-fix.md
.claude/commands/sdd-start.md
.claude/agents/sdd-research.md
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md
packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
scripts/sdd/sdd_meta.py
scripts/sdd/ensure_worktree.py
scripts/sdd/reserve_ids.py
sdd/templates/task.md
sdd/templates/spec.md
.claude/rules/worktree-management.md
docs/sdd/WORKFLOW.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
