---
id: FEAT-375
title: Codex CLI adversarial second-opinion agent for the dev loop
slug: codex-cli-agent
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-26
  summary_oneline: Add OpenAI codex CLI as an invocable sub-agent in parrot.flows.dev_loop for dev tasks and adversarial code review
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-375/
created: 2026-07-26
updated: 2026-07-26
---

# FEAT-375 — Codex CLI adversarial second-opinion agent for the dev loop

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-375/`](../state/FEAT-375/)

---

## 0. Origin

The original request, preserved verbatim at `sdd/state/FEAT-375/source.md`:

> On `parrot.flows.devloop` add the ability to use the `codex` CLI command
> (example usage: `codex exec --skip-git-repo-check "Reply with OK"`) as a
> sub-agent that can be invoked to run some development tasks or even
> adversarial code review. [Followed by a detailed rule set for using codex as
> a *second-opinion agent*: neutral briefs only (diff + requirement + question,
> never the caller's reasoning), advisory output triaged CONFIRM/REJECT/ESCALATE,
> `codex exec review --uncommitted|--base|--commit`, read-only sandbox for
> opinions, `codex exec resume --last` follow-ups, background execution,
> parallel Claude-subagent + codex perspective with synthesis.]

**Initial signals** (extracted, not interpreted):
- Verbs: "add the ability to use" → feature enrichment, not a bug
- Named entities: `codex` CLI, `parrot.flows.devloop` (actual package: `parrot/flows/dev_loop/`), adversarial code review, sub-agent
- Components: dev-loop flow, code review gate, sub-agent dispatch
- Acceptance criteria provided: no — but the pasted rule set functions as a behavioral contract

---

## 1. Synthesis Summary

The literal ask — invoke the `codex` CLI from the dev loop for development
tasks and code review — is **~80% already implemented**: `CodexCodeDispatcher`
orchestrates `codex exec --json` end to end (F001), codex is a selectable
development-worker backend in the `DevAgentPool` via `agent_builder.build_dispatcher`
(F003), and `CodexCodeReviewDispatcher` is registered as `"codex"` in the QA
code-review gate (F002). What does **not** exist is the *adversarial
second-opinion* semantics the source describes at length: today's codex
reviewer runs write-enabled (`sandbox="workspace-write"`) and fixes + commits
issues itself, whereas the request calls for a **read-only advisory reviewer**
fed a neutral brief whose findings the primary worker triages
CONFIRM/REJECT/ESCALATE (F002, F004). The recommended scope is additive: a new
`codex-adversarial` registry entry, a neutral second-opinion subagent brief,
profile widening (the codex profiles pin `subagent` to `Literal["sdd-worker"]`),
plus — per Q&A resolution — `codex exec review` command variants, `resume --last`
session continuation, and a parallel Claude+Codex perspective with synthesis.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-375/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | `CodexCodeDispatcher` | 936-1265 | existing `codex exec --json` orchestrator; extension point for `exec review` / `resume` variants and read-only profiles | F001, F004 |
| 2 | `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | `CodeReviewDispatcherFactory`, `CodexCodeReviewDispatcher` | 104-168 | registry where the advisory `codex-adversarial` reviewer registers alongside the write-enabled `codex` one | F002 |
| 3 | `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | `CodexCodeDispatchProfile`, `CodexCodeReviewProfile` | 540-566, 797-809 | profiles to widen: `subagent` Literal, read-only advisory constructor, triage fields | F004 |
| 4 | `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/` + `_subagent_defs.py` | `load_subagent_definition` | — | where the neutral adversarial brief (e.g. `sdd-secondopinion.md`) plugs in | F005 |
| 5 | `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | `build_dispatcher` | 143-146 | already materializes codex dev-workers for the pool (development-task half of the request) | F003 |
| 6 | `packages/ai-parrot/src/parrot/conf.py` | `DEV_LOOP_CODEREVIEW_AGENT`, `DEV_LOOP_CODEREVIEW_MODEL` | 923-932 | config surface for reviewer selection; new advisory-mode settings land here | F002 |
| 7 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | `QANode` | — | review→fix→rerun loop that will consume advisory findings for primary-worker triage | F002 |

### 2.2 Constraints Discovered

- **Worktree cwd guard.** Every codex dispatch cwd must resolve under
  `conf.WORKTREE_BASE_PATH` (`_enforce_cwd_under_worktree_base`,
  dispatcher.py:1264). *Implication*: review-by-sha/base runs still execute
  inside a worktree, never the operator's checkout. *Evidence*: F001, F004
- **Degrade-on-infra-error (FEAT-250 G4).** Review dispatchers must return
  `passed=True` + a nit finding when the CLI fails, never block the flow.
  *Implication*: the adversarial reviewer inherits this contract from
  `AbstractCodeReviewDispatcher.review()`. *Evidence*: F002
- **Subagent Literal pin.** `CodexCodeDispatchProfile.subagent` is
  `Literal["sdd-worker"]` ("v1 intentionally scoped to Development") — Codex
  cannot load any other brief today, while Claude's review profile selects
  `sdd-codereview`. *Implication*: widening this Literal (or a sibling field)
  is a prerequisite for a neutral adversarial persona. *Evidence*: F004
- **Hot subsystem — additive only.** FEAT-270/322/323 merged in the last
  cycle; FEAT-374 devloop CLI console work is in flight with uncommitted edits
  to `parrot/cli/devloop/bootstrap.py`, `parrot/cli/wizard.py`, `parrot/conf.py`.
  *Implication*: new registry entries + new brief files + profile widening,
  no dispatcher internals rework; coordinate conf.py additions with FEAT-374.
  *Evidence*: F006
- **Structured output discipline.** Codex output is enforced via
  `--output-schema` + `-o <file>` and validated into Pydantic models
  (`_validate_output_file`). *Implication*: the triage contract must be a
  Pydantic model (extend `CodeReviewVerdict` or add a sibling). *Evidence*: F001

### 2.3 Recent History (Relevant)

| Commit | Message | Relevance |
|--------|---------|-----------|
| `e5d23c782` | Merge feat-322-agent-host-protocol-session-state | dispatchers now thread `session_host` |
| `2784f6697`… | FEAT-323 DevAgentPool series (TASK-1857..1864) | codex as pooled dev worker |
| `6940c8748` | Merge feat-270-new-codereviewers | Claude/Codex/Gemini review dispatchers |
| `28d88b9eb` | fix(code-review): 10 correctness bugs in FEAT-270 gate | review gate recently hardened |
| `5982096fb` | feat: MoonshotCodeDispatcher | dispatcher-per-backend pattern still growing |

*Evidence*: F006

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`CodexAdversarialReviewDispatcher`** — registered as `"codex-adversarial"`
  in `CodeReviewDispatcherFactory`; read-only sandbox, advisory-only (no fix,
  no commit). *(U1: coexists with the write-enabled `"codex"` entry.)*
- **`sdd-secondopinion.md`** subagent brief in `_subagent_data/` — the neutral
  adversarial persona: receives diff + requirement + question only; emits
  findings without prescribing that they be auto-applied.
- **Triage contract** — advisory findings carry a disposition field; QANode's
  review→fix→rerun loop hands them to the **primary worker**, which must mark
  each CONFIRM (fix), REJECT (record reason), or ESCALATE (open a gate) —
  never silently concede or drop. *(U2 resolution.)*
- **`codex exec review` command variants** — `--uncommitted`, `--base <ref>`,
  `--commit <sha>` profile options in `_build_command`.
- **Session continuation** — `codex exec resume --last "<question>"` follow-up
  support for multi-turn adversarial exchanges.
- **Parallel perspective mode** — one Claude review dispatch + one codex
  advisory dispatch on the same neutral brief, with a synthesis step that
  reports agreements/disagreements. *(U3: all v2 items in scope.)*

### What Changes

- **`models.py`::`CodexCodeDispatchProfile`** — widen `subagent` Literal;
  add an advisory profile subclass (`sandbox="read-only"`, no-write policy),
  review-target fields (uncommitted/base/commit), resume token. *Evidence*: F004
- **`code_review.py`** — new factory registration + advisory dispatcher class.
  *Evidence*: F002
- **`dispatcher.py`::`CodexCodeDispatcher._build_command`** — branch for
  `exec review` / `exec resume` command shapes. *Evidence*: F001
- **`nodes/qa.py`::`QANode`** — feed advisory verdicts into the existing
  review→fix→rerun loop with the triage contract. *Evidence*: F002
- **`conf.py`** — accept `"codex-adversarial"` in `DEV_LOOP_CODEREVIEW_AGENT`;
  advisory-mode envs (model, parallel-perspective toggle). *Evidence*: F002, F006

### What's Untouched (Non-Goals)

- `CodexCodeDispatcher` core dispatch loop, event streaming, semaphore, guards
- The existing write-enabled `"codex"` reviewer (unchanged, still selectable)
- Image generation (`image_gen`) — no dev-loop consumer; explicitly deferred
- FEAT-374 devloop CLI console in-flight edits

### Patterns to Follow

- Factory registration decorator (`@CodeReviewDispatcherFactory.register`)
  exactly as FEAT-270's three reviewers. *Evidence*: F002
- Subagent brief as markdown data file + `load_subagent_definition`, as with
  the four existing briefs. *Evidence*: F005
- Profile-subclass-overrides-defaults (e.g. `CodexCodeReviewProfile`) for the
  advisory profile. *Evidence*: F004

### Integration Risks

- **Triage loop cost**: feeding advisory findings back to the primary worker
  adds a dispatch per review round; mitigate with the existing rerun-cap in
  QANode's loop. *Evidence*: F002
- **`codex exec review` CLI surface drift**: subcommand flags come from OpenAI's
  CLI and may change; keep the command builder table-driven and covered by
  command-shape unit tests (as `test_code_review.py` does today). *Evidence*: F001
- **conf.py merge conflict** with in-flight FEAT-374 edits. *Evidence*: F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `CodexCodeDispatcher` fully orchestrates `codex exec --json` with structured output | F001 | high | direct read of dispatcher.py:936-1265 |
| C2 | Codex is already selectable as dev-task worker (pool) and QA code reviewer | F002, F003 | high | direct read of registrations + builder branch |
| C3 | Current codex reviewer is write-enabled (fix+commit); no advisory/adversarial mode exists | F002, F004 | high | profile defaults read directly; no read-only constructor found |
| C4 | Codex path cannot load any brief other than `sdd-worker` (Literal pin) | F004 | high | direct read of models.py:548,805 |
| C5 | `codex exec review` / `resume` subcommands are unused in dev_loop | F001, F004 | medium | `_build_command` only emits `exec --json`; repo-wide grep for codex showed no other call sites, but CLI wrappers outside dev_loop weren't exhaustively read |
| C6 | New brief file + factory registration is the lowest-friction integration path | F005, F006 | medium | inferred from existing patterns and hot-subsystem constraint |

Distribution: **4** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1: Replace the write-enabled codex reviewer or coexist?** —
  *Resolved*: "Coexist: register a separate `codex-adversarial` entry in
  `CodeReviewDispatcherFactory`; `DEV_LOOP_CODEREVIEW_AGENT` selects either.
  No behavior change for existing users." *Resolves claims*: C3
- [x] **U2: Who consumes the CONFIRM/REJECT/ESCALATE triage?** —
  *Resolved*: "Primary worker fixes: QANode feeds advisory findings into the
  existing review→fix→rerun loop; the primary (Claude) worker triages each
  finding (CONFIRM: fix, REJECT: record reason, ESCALATE: gate)."
  *Resolves claims*: C2
- [x] **U3: Are the v2 items (exec review variants, resume, parallel
  perspective) in scope?** — *Resolved*: "Include everything: advisory mode +
  `codex exec review` variants + `resume --last` continuation + parallel
  Claude/Codex perspective synthesis." *Resolves claims*: C5

### Unresolved (defer to spec / implementation)

- [ ] **Where does the ESCALATE disposition land?** — *Owner*: tbd
  *Plausible answers*: a) FEAT-322 HITL gate (`SessionHost.open_gate`) ·
  b) PR comment + blocked verdict · c) both
- [ ] **Parallel-perspective synthesis executor** — *Owner*: tbd
  *Plausible answers*: a) deterministic merge in QANode · b) a third LLM
  dispatch that synthesizes the two reports

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-375`** — *Rationale*: localization is high-confidence
(C1-C4) onto a well-tested extension seam (factory registration + profile
widening + brief file); the two remaining questions are design details a spec
can pin down, not architectural forks.

### Alternatives

- **`/sdd-brainstorm FEAT-375`** — if you want to explore alternative shapes
  for the parallel-perspective synthesis (deterministic merge vs. LLM judge).
- **`/sdd-task FEAT-375`** — not recommended; U3's "include everything" makes
  this a multi-task feature.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-375/state.json` |
| Source (raw) | `sdd/state/FEAT-375/source.md` |
| Research plan | `sdd/state/FEAT-375/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-375/findings/F001-*.md` … `F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-375/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 9 / 40
- Grep calls: 6 / 25
- Git calls: 1 / 10
- Wiki queries (free): 5 queries + 2 page reads
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (feature addition to
a healthy subsystem; no failure signal in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com |
