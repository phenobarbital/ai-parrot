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
The /sdd-proposal research phase (Phase 2) runs as a sequential loop: each query in the research plan executes one at a time, checking budget limits after each step. For the loose budget profile (100 files, 60 greps, 20 git calls, depth 3), this can take up to 15 minutes of wall-clock time — most of it blocked waiting for tool responses.

The three dominant query types (codebase exploration, git history, wiki queries) are independent: a grep for symbol references does not depend on a git log for authorship, and neither depends on a wikitoolkit query for architectural context. Running them in parallel would cut wall-clock time roughly by a factor of 3, limited only by the slowest lane.

### Constraints and goals
- Must preserve the existing budget profiles (tight, default, loose) — no breaking changes to the --budget flag semantics.
- tight profile (15 files, 120s) stays sequential — fork overhead is not justified at this scale.
- The twin-file structure (.claude/commands/sdd-proposal.md + .agents/skills/sdd-proposal/SKILL.md) must be updated consistently.
- The finding file format (sdd/templates/finding.md) is unchanged.
- State schema (sdd/templates/state.schema.json) additions must be backwards-compatible (new optional fields only).
- Single-agent fallback must work automatically when the Agent tool is unavailable.
- Wiki queries remain budget-free.
- Token cost increase should be bounded — per-lane budget at ~60% of profile limits.
- Merged findings must feed the existing Phase 3 synthesis input format unchanged.

### Recommended option / probable scope
Option A: Fork-per-Lane with Shared Findings Directory

Each of 3 research lanes runs as a Claude Code fork (subagent_type: "fork"). Forks inherit the full conversation context (including the resolved source and approved research plan). Each fork writes findings to the existing ${STATE_DIR}/findings/ directory using lane-prefixed IDs:
- Codebase lane: FC-001, FC-002, ... — handles grep, glob, read, tree queries.
- Git lane: FG-001, FG-002, ... — handles git_log queries.
- Wiki lane: FW-001, FW-002, ... — handles wiki_query, wiki_page, wiki_related queries.

The main agent waits for all 3 forks to complete, then runs a dedup pass: scans all findings, groups by file path, and merges overlapping citations into consolidated F001...F<NNN> findings for synthesis.

Per-lane budget allocation:
- Codebase: 60% files_read, 80% grep_calls, 0 git_calls
- Git: 20% files_read, 0 grep_calls, 100% git_calls
- Wiki: 20% files_read, 20% grep_calls, 0 git_calls
- Wall-clock per lane: 0.7 * profile.wall_seconds

### Verified code anchors (paths only — open them yourself)
.claude/commands/sdd-proposal.md
.agents/skills/sdd-proposal/SKILL.md
sdd/templates/state.schema.json
sdd/templates/finding.md

### Questions still open in the exploration document
- Should cross-lane recursive follow-ups be supported in a future iteration?
- Should the dedup merge preserve both findings verbatim when the file-path match has different symbols?
- Should --budget=custom support user-specified per-lane limits?
- What is the measured prompt-cache hit rate for forks of /sdd-proposal?

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
