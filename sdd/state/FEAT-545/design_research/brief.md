<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec §3b and piped to `codex exec … --output-schema design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders: The request asks the SDD pipeline to hand non-thinking executors explained, usable code — centred on the TASK files that `/sdd-task` produces during spec decomposition, with `/sdd-spec` contributing interface skeletons — and to add a Codex-backed "collaborative design research" step modelled on the existing Adversarial Cross-Check. The codebase confirms both halves are near-pure prose changes: the two commands (`.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`) each carry an explicit "Do NOT write implementation code" guardrail that must be reworded, while their templates (`sdd/templates/spec.md`, `sdd/templates/task.md`) already contain code fences but no slot for an *explained reference implementation*. The adversarial pattern the user wants to mirror exists as five shared rules in `.claude/agents/code-reviewer.md`, `CLAUDE.md` and `.claude/agents/sdd-secondopinion.md` (neutral brief, background session, CONFIRM/REJECT/ESCALATE, no silent concession, evidence verification), and the installed `codex` CLI (0.153.4) plus the dev-loop dispatcher in `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` prove that a thinking model, read-only sandbox and schema-validated JSON output are all available flags. Two constraints shape the design: `/sdd-spec` is also run unattended by `.claude/agents/sdd-planner.md`, so the Codex pass must be optional and non-blocking; and every command has a twin in `.agent/workflows/sdd-spec.md` that must receive the same edits. Recommendation: proceed to `/sdd-spec` after the user picks answers to four product questions (model/config, triage style, code granularity, mandatory-vs-optional), each of which has a recommended default below.

--- - **Two explicit no-code guardrails.** `sdd-spec.md:17` ("specs are design documents") and `sdd-task.md:14` ("tasks are plans, not code"). Change #1 cannot land without rewording both. *Evidence*: F001, F002
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
sdd/templates/task.md none — all resolved in the proposal Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
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
