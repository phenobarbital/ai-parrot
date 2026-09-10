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
The request asks the SDD pipeline to hand non-thinking executors explained, usable code — centred on the TASK files that `/sdd-task` produces during spec decomposition, with `/sdd-spec` contributing interface skeletons — and to add a Codex-backed "collaborative design research" step modelled on the existing Adversarial Cross-Check. The codebase confirms both halves are near-pure prose changes: the two commands (`.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`) each carry an explicit "Do NOT write implementation code" guardrail that must be reworded, while their templates (`sdd/templates/spec.md`, `sdd/templates/task.md`) already contain code fences but no slot for an *explained reference implementation*. The adversarial pattern the user wants to mirror exists as five shared rules in `.claude/agents/code-reviewer.md`, `CLAUDE.md` and `.claude/agents/sdd-secondopinion.md` (neutral brief, background session, CONFIRM/REJECT/ESCALATE, no silent concession, evidence verification), and the installed `codex` CLI (0.153.4) plus the dev-loop dispatcher in `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` prove that a thinking model, read-only sandbox and schema-validated JSON output are all available flags. Two constraints shape the design: `/sdd-spec` is also run unattended by `.claude/agents/sdd-planner.md`, so the Codex pass must be optional and non-blocking; and every command has a twin in `.agent/workflows/sdd-spec.md` that must receive the same edits. Recommendation: proceed to `/sdd-spec` after the user picks answers to four product questions (model/config, triage style, code granularity, mandatory-vs-optional), each of which has a recommended default below.

---

### Constraints and goals
- **Two explicit no-code guardrails.** `sdd-spec.md:17` ("specs are design documents") and `sdd-task.md:14` ("tasks are plans, not code"). Change #1 cannot land without rewording both. *Evidence*: F001, F002
- **The premise is already accepted, the mechanism is missing.** `sdd-task.md:111` states the implementing agent "(often Sonnet or Haiku) WILL hallucinate if not given explicit, verified code anchors". The Codebase Contract is the current answer; explained reference code is the next step. *Evidence*: F002, F013
- **Code density is author-dependent today.** Six newest specs carry 0–384 fenced lines; the newest task file carries 1. The change must make explained code a *structured, required* deliverable, not merely allowed. *Evidence*: F005
- **The Codex model is a CLI-invocation decision.** Commit `dbd2cd740` removed `model: gpt-5.5` from a Claude agent because a Claude Code subagent cannot select an OpenAI model; the seat's model is passed as `--model` to `codex`. *Evidence*: F010, F007
- **codex-cli 0.153.4 has everything needed.** Prompt from stdin (`-`), `-m`, `-c model_reasoning_effort=…`, `--sandbox read-only`, `--output-schema`, `-o`. The dev-loop already relies on `--output-schema` for JSON. *Evidence*: F009, F007
- **Do not depend on operator config.** The operator's `~/.codex/config.toml` currently says `gpt-6-astra` / `high`; the dispatcher passes `--ignore-user-config`. A command that wants a thinking model must pass `-m` and reasoning effort explicitly. *Evidence*: F009
- **`artifacts/` is gitignored** (`.gitignore:283`). Codex transcripts must live under `sdd/state/<FEAT-ID>/` to be auditable and visible to worktrees. *Evidence*: F015
- **Unattended execution.** `sdd-planner` (Sonnet) runs `/sdd-spec` then `/sdd-task` and aborts on any non-zero step. The Codex phase must be optional and non-blocking. *Evidence*: F012
- **Twins.** `.agent/workflows/sdd-spec.md` and `sdd-task.md` differ from `.claude/commands/` by 6 lines each (frontmatter + one reference line). *Evidence*: F011
- **Executors need no change.** `sdd-worker` reads the full task file, verifies the contract, and implements "EXACTLY as specified". *Evidence*: F013
- **"Accepted" is well-defined.** Brainstorm `Status: accepted`; proposal `status: accepted` only on explicit user accept; spec gate is `approved`. The brief to Codex is the accepted exploration doc, including its Code Context. *Evidence*: F014

### Recommended option / probable scope
### What's New

- **Design-research phase in `/sdd-spec` (new §3b)**, between the §2c carry-forward summary and §4 codebase research. It builds a *neutral brief* from the accepted brainstorm/proposal only (Problem Statement, Constraints, Recommended Option, Code Context, unresolved questions) — never Claude's draft — runs `codex` in the background with an explicit thinking model, receives a schema-validated JSON list of suggestions, triages each `CONFIRM` / `REJECT` / `ESCALATE`, folds CONFIRMed ideas into §2 / §3 / §7 while drafting, and records the triage table in the spec.
- **Two new templates**: `sdd/templates/design_research.prompt.md` (brief + question) and `sdd/templates/design_research.schema.json` (suggestion: `id`, `kind ∈ {architecture, api, testing, risk, alternative}`, `title`, `rationale`, `affected_paths`, `risk`).
- **Spec §9 "Design Research Cross-Check"**: triage table (`Suggestion | Disposition | Reason`) + pointer to the raw transcript at `sdd/state/<FEAT-ID>/design_research/`, mirroring the code-reviewer's "Adversarial Cross-Check" block.
- **Implementation Blueprint per TASK file (the centre of change #1, lives in `/sdd-task`)**: during spec decomposition the thinking model writes, for every task, an ordered list of steps and, for every file the task creates or modifies, a code block the executor can write to disk nearly verbatim — imports, class/function bodies for the mechanical parts, docstrings, logger calls — followed by a short explanation of *why* each block exists and an explicit `FILL IN` list for the judgement calls left to the executor. This is *not* the full implementation: business-logic branches, edge-case handling and test bodies stay as annotated stubs. The spec (§3) keeps only interface-level skeletons (signatures + docstrings) so the blueprint is derived once, at task time, against a freshly re-verified Codebase Contract.
- **Explain-for-executor rule** in `/sdd-task` (and, for the interface skeletons, `/sdd-spec`): every non-trivial decision is restated as an imperative instruction plus its reason, so a non-thinking executor (Haiku) never has to infer intent — it reads the blueprint, writes the declared code to the declared paths, and fills the marked gaps.

Illustrative invocation shape (prose command, mirrors the dispatcher's trusted flags — F007/F009):

```bash
codex exec --sandbox read-only -m "$SDD_DESIGN_RESEARCH_MODEL" \
  -c model_reasoning_effort=high \
  --output-schema sdd/templates/design_research.schema.json \
  -o "sdd/state/$FEAT_ID/design_research/codex.json" - \
  < "sdd/state/$FEAT_ID/design_research/brief.md"
```

### What Changes

- **`.claude/commands/sdd-task.md`::Guardrails:14, §3, §4** — replace "tasks are plans, not code" with: every task MUST carry an Implementation Blueprint (per-file code blocks + explanations + `FILL IN` list) derived from the spec's interface skeletons and re-verified against the codebase; full implementations remain out of scope. *Evidence*: F002, F004
- **`.claude/commands/sdd-spec.md`::new §3b, §5, §7** — insert the design-research phase; render §9 and per-module reference code; report disposition counts in the §7 output. *Evidence*: F001, F006
- **`.claude/commands/sdd-spec.md`::Guardrails:17** — relax "Do NOT write implementation code" to: interface-level skeletons (signatures, docstrings, `verified: path:line` anchors) are required per module; bodies belong to the task blueprints. *Evidence*: F001
- **`sdd/templates/task.md`::Implementation Notes** — add the "Implementation Blueprint" section (Steps → per-file code blocks → Why → `FILL IN`). *Evidence*: F004
- **`sdd/templates/spec.md`::§3, new §9** — add an Interface Skeleton sub-block per module and the Design Research Cross-Check section. *Evidence*: F003
- **`.agent/workflows/sdd-spec.md`, `.agent/workflows/sdd-task.md`** — mirror every body edit. *Evidence*: F011
- **`CLAUDE.md`::Adversarial Second Opinion (124-175)** — name design research as a second use of the codex seat; point at the new templates. *Evidence*: F006

### What's Untouched (Non-Goals)

- `packages/ai-parrot/src/parrot/flows/dev_loop/**` — Python Codex dispatchers, profiles and conf keys. `/sdd-spec` uses the prose `codex` CLI path; F007 is precedent, not a dependency.
- `.claude/agents/code-reviewer.md`, `code-review.md`, `sdd-secondopinion.md` — the code-review seat is unchanged.
- `.claude/agents/sdd-worker.md`, `/sdd-start` — consume richer task files as-is (F013).
- `scripts/sdd/reserve_ids.py`, the id ledger — no allocation change.
- `/sdd-brainstorm`, `/sdd-proposal` — they do not call Codex; the pass runs at spec time over their accepted output.

### Patterns to Follow

- Neutral brief = artifact + requirements + question; withhold the primary's reasoning and draft. *Evidence*: F008, F006
- Advisory triage `CONFIRM` / `REJECT` / `ESCALATE` with a per-finding reason; never silently concede or drop. *Evidence*: F006
- Verify every path/symbol the external model cites before adopting it; unverifiable ⇒ not a finding. *Evidence*: F006
- `--output-schema` + `-o`, read-only sandbox, explicit `-m` and reasoning effort. *Evidence*: F007, F009
- Persist research under `sdd/state/<FEAT-ID>/` and commit it with the document (as `/sdd-proposal` does). *Evidence*: F015
- Every code reference carries a `verified: path:line` anchor. *Evidence*: F001, F003

### Integration Risks

- **Task bloat and code drift** — blueprints go stale before implementation. *Mitigation*: blueprints are written at task time (the last step before the worktree exists), carry verified-at anchors, leave judgement calls as `FILL IN`, and sdd-worker's contract re-verification still runs. *Evidence*: F005, F013
- **Unattended planner blocks on Codex** (absent binary, auth, timeout, bad model). *Mitigation*: `command -v codex` detection, 10-minute cap, on any failure write "no external design research" into §9 and continue — the review policy's fallback. *Evidence*: F012, F006
- **Codex hallucinates paths/symbols** that leak into the Codebase Contract. *Mitigation*: every CONFIRMed suggestion is re-verified by read/grep before entering §2/§6; otherwise REJECT with reason. *Evidence*: F006, F008
- **Model drift** — `gpt-5.6-luna` is verified today (F017) but CLI/model catalogs change. *Mitigation*: the model is a config value (`SDD_DESIGN_RESEARCH_MODEL`, default `gpt-5.6-luna`) with the same one-shot probe at spec time; on failure the pass is skipped with a note (U4). *Evidence*: F009, F010, F017
- **Twin drift** between `.claude/commands` and `.agent/workflows`. *Mitigation*: edit both in the same task; consider a command parity check like `test_subagent_parity.py`. *Evidence*: F011
- **Ratification instead of research** if the brief carries Claude's design. *Mitigation*: brief built from the accepted exploration doc only; the pass runs *before* §4/§5 drafting. *Evidence*: F008

---

### Verified code anchors (paths only — open them yourself)
.agent/workflows/sdd-spec.md
.agent/workflows/sdd-task.md
.claude/agents/code-reviewer.md
.claude/agents/sdd-planner.md
.claude/agents/sdd-secondopinion.md
.claude/commands/sdd-spec.md
.claude/commands/sdd-task.md
CLAUDE.md
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py
sdd/templates/spec.md
sdd/templates/task.md

### Questions still open in the exploration document
none — all resolved in the proposal

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
