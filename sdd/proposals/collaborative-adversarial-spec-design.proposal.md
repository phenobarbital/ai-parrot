---
id: FEAT-564
title: Collaborative adversarial spec design — executor-ready reference code in specs/tasks + a Codex design-research pass before the spec is written
slug: collaborative-adversarial-spec-design
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-10
  summary_oneline: Make /sdd-spec emit executor-ready code+explanations and add a Codex collaborative design-research pass before spec creation
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-564/
created: 2026-09-10
updated: 2026-09-10
---

# FEAT-564 — Collaborative adversarial spec design

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-564/`](../state/FEAT-564/)
> **ID note**: FEAT-564 is PROVISIONAL (`max(existing)+1`, the /sdd-proposal convention). `/sdd-spec` will reserve the authoritative number via `reserve_ids.py` (ledger `next_feature_id` is 542 today); this document's id is then rewritten.

---

## 0. Origin

The original request, preserved verbatim at `sdd/state/FEAT-564/source.md`.

> current "sdd-spec" command is using for converting a brainstorm or proposal into a full featured spec-driven development document, but because we are using thinking models for spec design but non-thinking models (as haiku) to take the "orders" and write the decided code into the expected files, I'm proposing here two changes over the "sdd-spec" command:
>
> 1. requesting to the thinking model (fable, Opus) to add more usable code + explanations on spec (and over each "TASK-" file created) to reduced the effort of non-thinking models during the execution of each task.
> 2. collaborative improvement-research: exactly like Adversarial Code Review we implemented on code-reviewer (using Codex), using Codex (but a thinking model like gpt 5.6-luna), Codex will receive the "accepted" proposal definition and will suggest ideas how to do the job, those proposed ideas will be incorporated during "spec creation" to enrich the ideas.

**Initial signals** (extracted, not interpreted):
- Verbs: "add more usable code + explanations", "suggest ideas", "incorporated during spec creation" → enrichment of an existing command, not a bug.
- Named entities: `/sdd-spec`, `TASK-*` files, `code-reviewer`, Codex, "gpt 5.6-luna", Haiku, Fable/Opus.
- Two independent deliverables: (1) richer spec/task content for non-thinking executors; (2) a Codex design-research pass over the *accepted* exploration doc.
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

The request asks `/sdd-spec` (and by extension `/sdd-task`) to stop being design-only documents and to hand non-thinking executors explained, usable reference code, and to add a Codex-backed "collaborative design research" step modelled on the existing Adversarial Cross-Check. The codebase confirms both halves are near-pure prose changes: the two commands (`.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`) each carry an explicit "Do NOT write implementation code" guardrail that must be reworded, while their templates (`sdd/templates/spec.md`, `sdd/templates/task.md`) already contain code fences but no slot for an *explained reference implementation*. The adversarial pattern the user wants to mirror exists as five shared rules in `.claude/agents/code-reviewer.md`, `CLAUDE.md` and `.claude/agents/sdd-secondopinion.md` (neutral brief, background session, CONFIRM/REJECT/ESCALATE, no silent concession, evidence verification), and the installed `codex` CLI (0.153.4) plus the dev-loop dispatcher in `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` prove that a thinking model, read-only sandbox and schema-validated JSON output are all available flags. Two constraints shape the design: `/sdd-spec` is also run unattended by `.claude/agents/sdd-planner.md`, so the Codex pass must be optional and non-blocking; and every command has a twin in `.agent/workflows/sdd-spec.md` that must receive the same edits. Recommendation: proceed to `/sdd-spec` after the user picks answers to four product questions (model/config, triage style, code granularity, mandatory-vs-optional), each of which has a recommended default below.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-564/findings/`. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `.claude/commands/sdd-spec.md` | Guardrails / §2c→§4 seam / §5 | 15-31, 121-133, 230-252, 254-345 | command to change: drop the no-code guardrail, insert the design-research phase between §2c and §4, render the new sections | F001 |
| 2 | `.claude/commands/sdd-task.md` | Guardrails / §3 / §4 | 10-15, 96-112, 114-159 | command to change: drop the no-code guardrail, require a Reference Implementation per task | F002 |
| 3 | `sdd/templates/spec.md` | §3 Module Breakdown / §7 | 72-86, 162-179 | template to extend: per-module reference skeleton + explanation; new Design Research Cross-Check section | F003 |
| 4 | `sdd/templates/task.md` | Implementation Notes / Pattern to Follow | 73-94 | template to extend: executor-ready starting point + per-block explanation + fill-in list | F004 |
| 5 | `.claude/agents/code-reviewer.md` | Adversarial Cross-Check | 119-194 | pattern source (five rules, agy ban, report table) | F006 |
| 6 | `.claude/agents/sdd-secondopinion.md` | neutral brief definition | 35-76 | pattern source: what a neutral brief is and is not | F008 |
| 7 | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | `CodexCodeDispatcher._build_command` | 240-282 | flag precedent: `--model`, `--sandbox`, `--output-schema`, `-o` | F007 |
| 8 | `.agent/workflows/sdd-spec.md`, `.agent/workflows/sdd-task.md` | twins | whole file | must mirror every body edit | F011 |
| 9 | `.claude/agents/sdd-planner.md` | steps 2-3, Failure handling | 45-53, 93-99 | unattended caller → the new phase must degrade gracefully | F012 |
| 10 | `CLAUDE.md` | Adversarial Second Opinion | 124-175 | policy home to extend to design research | F006 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched |
|--------|------|---------|---------|
| `41187b8e6` | 2026-09-06 | infra for sdd-* in antigravity | `.agent/workflows/sdd-*.md` twins created |
| `dbd2cd740` | 2026-09-03 | fix(dev-loop): drop the unusable `model: gpt-5.5` from sdd-secondopinion | agent + `_subagent_data` twin |
| `1be04d299` | 2026-09-01 | sdd: one feature id per slug — refuse a duplicate reservation | `sdd-spec.md` |
| `f32cb899e` | 2026-09-01 | chore: remove agy as an adversarial code-review option | `code-reviewer.md`, `sdd-codereview.md`, `CLAUDE.md` |
| `25c61d4dc` | 2026-08-21 | chore: migrate adversarial review from codex to agy-first with codex fallback | same files |

`sdd/templates/spec.md` and `task.md` have no commits in the last 90 days (stable targets). *Evidence*: F010, F011

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **Design-research phase in `/sdd-spec` (new §3b)**, between the §2c carry-forward summary and §4 codebase research. It builds a *neutral brief* from the accepted brainstorm/proposal only (Problem Statement, Constraints, Recommended Option, Code Context, unresolved questions) — never Claude's draft — runs `codex` in the background with an explicit thinking model, receives a schema-validated JSON list of suggestions, triages each `CONFIRM` / `REJECT` / `ESCALATE`, folds CONFIRMed ideas into §2 / §3 / §7 while drafting, and records the triage table in the spec.
- **Two new templates**: `sdd/templates/design_research.prompt.md` (brief + question) and `sdd/templates/design_research.schema.json` (suggestion: `id`, `kind ∈ {architecture, api, testing, risk, alternative}`, `title`, `rationale`, `affected_paths`, `risk`).
- **Spec §9 "Design Research Cross-Check"**: triage table (`Suggestion | Disposition | Reason`) + pointer to the raw transcript at `sdd/state/<FEAT-ID>/design_research/`, mirroring the code-reviewer's "Adversarial Cross-Check" block.
- **Reference Implementation blocks**: per module in spec §3 (signature-level skeleton, docstrings, one "why" paragraph per block, `verified: path:line` anchors) and a "Reference Implementation (starting point)" section in every task file (executor-ready skeleton, per-block explanation, explicit *fill-in* list).
- **Explain-for-executor rule** in both commands: every non-trivial decision is restated as an imperative instruction plus its reason, so a non-thinking executor never has to infer intent.

Illustrative invocation shape (prose command, mirrors the dispatcher's trusted flags — F007/F009):

```bash
codex exec --sandbox read-only -m "$SDD_DESIGN_RESEARCH_MODEL" \
  -c model_reasoning_effort=high \
  --output-schema sdd/templates/design_research.schema.json \
  -o "sdd/state/$FEAT_ID/design_research/codex.json" - \
  < "sdd/state/$FEAT_ID/design_research/brief.md"
```

### What Changes

- **`.claude/commands/sdd-spec.md`::Guardrails:17** — replace "Do NOT write implementation code" with: reference implementations are *required* at skeleton level (signatures, docstrings, explained blocks) with verified-at anchors; complete modules remain out of scope. *Evidence*: F001
- **`.claude/commands/sdd-spec.md`::new §3b, §5, §7** — insert the design-research phase; render §9 and per-module reference code; report disposition counts in the §7 output. *Evidence*: F001, F006
- **`.claude/commands/sdd-task.md`::Guardrails:14, §3, §4** — same guardrail rewrite; require the Reference Implementation section per task, derived from the spec's §3 skeletons and re-verified. *Evidence*: F002, F004
- **`sdd/templates/spec.md`::§3, new §9** — add the Reference Implementation sub-block and the Design Research Cross-Check section. *Evidence*: F003
- **`sdd/templates/task.md`::Implementation Notes** — add "Reference Implementation (starting point)". *Evidence*: F004
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

- **Spec/task bloat and code drift** — skeletons go stale before implementation. *Mitigation*: skeleton-level only, verified-at anchors, and sdd-worker's existing contract re-verification. *Evidence*: F005, F013
- **Unattended planner blocks on Codex** (absent binary, auth, timeout, bad model). *Mitigation*: `command -v codex` detection, 10-minute cap, on any failure write "no external design research" into §9 and continue — the review policy's fallback. *Evidence*: F012, F006
- **Codex hallucinates paths/symbols** that leak into the Codebase Contract. *Mitigation*: every CONFIRMed suggestion is re-verified by read/grep before entering §2/§6; otherwise REJECT with reason. *Evidence*: F006, F008
- **Requested model "gpt 5.6-luna" may not exist** for codex-cli 0.153.4. *Mitigation*: model is a config value with a verified default; one-shot validation at spec time, fallback to the operator's config model. *Evidence*: F009, F010
- **Twin drift** between `.claude/commands` and `.agent/workflows`. *Mitigation*: edit both in the same task; consider a command parity check like `test_subagent_parity.py`. *Evidence*: F011
- **Ratification instead of research** if the brief carries Claude's design. *Mitigation*: brief built from the accepted exploration doc only; the pass runs *before* §4/§5 drafting. *Evidence*: F008

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `/sdd-spec` forbids implementation code (line 17) and has no external-model step | F001 | high | direct read; grep "codex" empty in file |
| C2 | `/sdd-task` forbids code (line 14) yet names Sonnet/Haiku hallucination as the contract's rationale (line 111) | F002 | high | direct read |
| C3 | Both templates carry code fences but no explained reference-implementation slot | F003, F004 | high | direct read |
| C4 | Code density is author-dependent (0–384 lines) and ~0 in the newest task | F005 | high | measured |
| C5 | The adversarial pattern is prose policy in three files with five transferable rules | F006 | high | direct read |
| C6 | codex-cli 0.153.4 supports stdin, `-m`, `-c`, `--output-schema`, `-o`; JSON output already used by the dev-loop | F009, F007 | high | `--help` + source |
| C7 | Codex model must be chosen on the CLI invocation, not in a Claude agent | F010 | high | commit `dbd2cd740` |
| C8 | `/sdd-spec` runs unattended via `sdd-planner`; a blocking gate breaks planning | F012 | high | planner steps + failure handling |
| C9 | `artifacts/` is gitignored; `sdd/state/<FEAT-ID>/` is the tracked location | F015 | high | `.gitignore:283` |
| C10 | Command edits must be mirrored into `.agent/workflows` twins | F011 | high | 6-line diff; commit `41187b8e6` |
| C11 | `sdd-worker` consumes richer task files without change | F013 | high | execution loop |
| C12 | "gpt 5.6-luna" is a valid model for the installed CLI | — | low | not verified; operator uses `gpt-6-astra`, dev-loop default `gpt-5.5` |
| C13 | Placing the Codex pass between §2c and §4 prevents ratification and feeds both design and contract | F001, F008 | medium | inferred from phase order (see U2) |
| C14 | Skeleton-level reference code is the right granularity | F005, F013 | medium | inferred; user may want more (see U3) |

Distribution: **11** high, **2** medium, **1** low. Overall **medium**: localization is high, but the *how* rests on four unresolved product choices and one unverified model name.

---

## 5. Open Questions

### Resolved (during proposal phase)

*(none — unattended run; answers below are recommended defaults, not decisions)*

### Unresolved (resolve before `/sdd-spec`)

- [ ] **U1 — Which Codex model/reasoning for the design-research seat, and where is it configured?** — *Owner*: jlara
  *Blocks*: C12
  *Plausible answers*: a) new key `SDD_DESIGN_RESEARCH_MODEL` with a verified default + `-c model_reasoning_effort=high` **(recommended)** · b) reuse `DEV_LOOP_ADVERSARIAL_MODEL` (`gpt-5.5` today) · c) no `-m`: inherit `~/.codex/config.toml` (`gpt-6-astra`/high today)
- [ ] **U2 — How do Codex's suggestions enter the spec?** — *Owner*: jlara
  *Blocks*: C13
  *Plausible answers*: a) explicit §9 triage table, CONFIRMed items folded into §2/§3/§7, raw transcript under `sdd/state/<FEAT-ID>/design_research/` **(recommended — mirrors code review)** · b) silent merge, transcript only in state · c) verbatim appendix, no triage
- [ ] **U3 — How much code is "usable code + explanations"?** — *Owner*: jlara
  *Blocks*: C14
  *Plausible answers*: a) skeleton-level per module/task: signatures, docstrings, explained blocks, fill-in list, verified-at anchors **(recommended)** · b) near-complete reference implementation per task · c) skeletons in the spec, near-complete code only in task files
- [ ] **U4 — Is the Codex pass mandatory or optional?** — *Owner*: jlara
  *Blocks*: C8
  *Plausible answers*: a) optional, non-blocking, "no external design research" note in §9 **(recommended — required by the unattended planner)** · b) mandatory interactively, optional under `sdd-planner` · c) always mandatory

---

## 6. Recommended Next Step

**`/sdd-spec collaborative-adversarial-spec-design`** — *Rationale*: localization is high-confidence (two commands, two templates, two twins, one policy section), the reusable pattern is fully documented in-repo, and the four unknowns are product choices with recommended defaults that can be confirmed at spec time. No architectural fork warrants a brainstorm.

Suggested task shape for `/sdd-task` (single worktree, sequential): (1) templates + schema/prompt files; (2) `/sdd-spec` command edits + twin; (3) `/sdd-task` command edits + twin; (4) `CLAUDE.md` policy + a dry run of the Codex pass on this very proposal as the acceptance test.

### Alternatives

- **`/sdd-brainstorm`** — only if you want to compare *where* the Codex pass runs (spec time vs. also per task at `/sdd-task`, or as a Python `DesignResearchDispatcher` in the dev-loop). Not recommended: the prose path is sufficient and the dev-loop is out of scope.
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-564/state.json` |
| Source (raw) | `sdd/state/FEAT-564/source.md` |
| Research plan | `sdd/state/FEAT-564/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-564/findings/F001-*.md` … `F016-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-564/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 16 / 40
- Grep calls: 14 / 25
- Git calls: 3 / 10
- Wiki calls: 2 (free)
- Depth reached: 1 / 2
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (change request against an existing command; no defect language).

**Gates**: plan gate and Q&A gate skipped (unattended session); recorded in `state.json`.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara (Claude Fable 5.1 session) |
