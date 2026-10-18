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
## 0. Origin

Inline request (es): sdd-worker / sdd-coder run tests per task, and sometimes
sdd-worker runs the whole spec's test set, but none of that reaches the PR that
`/sdd-done` opens. Request: `/sdd-done` should show a table of tests run and
passed, so reviewers have a visible metric when approving the spec.

## 1. Synthesis Summary

Test evidence exists today but is lost in three ways: `/sdd-done` deliberately
skips tests (F001). The sdd-coder evidence store keeps only outcome and exit code,
with no counts (F002). Pass counts survive only as free-text "N passed" in about
29% of Completion Notes, and their scope varies (F003). The PR body is just
"<N>/<total> tasks verified". The fix has two parts. First, structured per-task
test counts recorded during execution. Second, an authoritative feature-tier
re-run inside `/sdd-done` against the final HEAD. Both are rendered as a
Markdown table in the PR body.

### Constraints and goals
### 2.2 Constraints
- `/sdd-done` §4 currently says re-running tests "adds latency without new signal". This proposal reverses that, because the final HEAD (after merges and the §4.5 lint pass) was never tested as a whole.
- Never run a full-suite pytest by hand; use `select_tests --tier feature`.
- Both twins (`.claude/commands` + `.agents/skills`) must change together.
- E2E evidence (§4.6) stays a separate gate; don't merge it into this table.

### Recommended option / probable scope
## 3. Scope (single hypothesis)

1. **Structured counts at the source.** `select_tests --run` gains `--junitxml`/`--report-json <path>`. It parses passed/failed/skipped/errors/duration per suite. The sdd-coder validation path (`coder_run_validation`) persists those counts in its evidence record (`TaskCompletionEvidence.completion_facts` or a typed `TestRunSummary`). The sdd-worker fallback lane writes the same JSON next to the task.
2. **Re-run in `/sdd-done`, only for specs with ≤10 tasks** (new step between §4.5 and §5; decided deterministically from the per-spec index's task count): `select_tests --tier feature --base origin/<base> --run --report-json`. The result reflects the final HEAD.
3. **PR-body table, always built from the aggregate of every task's recorded runs**: one row per suite (test module or package) plus a **Total** row (run · passed · failed · skipped · duration). Add a collapsible per-task section built from the recorded per-task evidence. Mark rows where the evidence predates the final HEAD.
4. **Report only, never block.** Failures show up in the table (❌), and the PR is opened anyway.

Not in scope: CI changes, coverage %, E2E gate.

### Verified code anchors (paths only — open them yourself)
.claude/commands/sdd-done.md
.agents/skills/sdd-done/SKILL.md
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/summary.py
scripts/sdd/select_tests.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
