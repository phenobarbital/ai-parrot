---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: `/sdd-spec` Intake Mode — Interview-Driven Spec Creation

**Date**: 2026-09-19
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Today a spec is well grounded only when a brainstorm (`/sdd-brainstorm`) or a
proposal (`/sdd-proposal`) was written first. `/sdd-spec` then carries that
document forward (§2a–§2c). Without such a document, `/sdd-spec` falls back to a
thin path. It takes the free-form notes after `--` as the Problem Statement seed,
runs one batch of "genuinely missing" questions (§3), and scans the codebase
(§4). It never collects the feature's identity in a structured way: which
project it concerns, why it matters, or whether a Jira ticket exists or should
be created. It also never runs the deep, confidence-graded research that
`/sdd-proposal` does.

The workaround costs two commands and a throwaway artifact:
`/sdd-brainstorm` (a doc with an options analysis the user may not need) and
then `/sdd-spec`. For a feature whose direction the author already knows, the
options analysis is ceremony. What they need is a **structured interview →
grounded research → adaptive Q&A → spec**, all in one run.

**Who is affected**: developers and the tech lead who author SDD specs
interactively. The unattended lanes (`sdd-planner`, `sdd-research`, dev-loop)
must **not** change behavior.

## Constraints & Requirements

- **Surface**: a *mode* of the existing `/sdd-spec` command, not a new command
  (user decision, Round 1).
- **Trigger**: automatic when no `<slug>.brainstorm.md` / `<slug>.proposal.md`
  exists **and** no `--` notes were given. `--interview` forces it,
  `--no-interview` suppresses it (Round 2).
- **Unattended lanes are untouched**: intake is interactive only. Every
  subagent that invokes `/sdd-spec` must pass `--no-interview` explicitly
  (Round 2; see Impact: `sdd-research` today matches the auto-trigger
  condition exactly).
- **Fixed intake questions** (from the request): feature name/slug, related
  project(s), overview (free text), problem being solved, Jira (existing key |
  create one | none), why it matters.
- **Adaptive rounds**: min 2, max 4, gap-driven. Anything unresolved after
  round 4 goes to spec §8 as `[ ]` (Round 3).
- **Ordering**: fixed intake → research → adaptive rounds informed by the
  findings (like `/sdd-proposal` Phase 5 targeted Q&A) → spec (Round 3).
- **Research depth**: `--research full|light|none`, **default `full`**. `full`
  dispatches a research subagent that runs `/sdd-proposal`'s
  plan → iterate → synthesize machinery; `light` = today's §4 scan; `none` = no
  research (the Codebase Contract is still built in §4, see Edge Cases)
  (Round 2).
- **Persistence**: the intake transcript, research plan, findings and synthesis
  are committed under `sdd/state/<FEAT-ID>/intake/`, next to the existing
  `design_research/` (Round 2).
- **Jira "create"**: runs `/sdd-tojira` **after** the spec is committed. An
  existing key is stamped into the spec header as `**Jira**: [KEY](url)`, the
  shape `/sdd-tojira` already recognises (`.claude/commands/sdd-tojira.md:100`)
  (Round 1).
- **Projects**: depends on FEAT-576 (`sdd-spec-changes`). The intake writes
  `projects:` / `tags:` frontmatter and draws choices from `KNOWN_PROJECTS`
  (Round 3).
- **Codex §3b** runs in intake mode over *confirmed intake answers + research
  synthesis* as the "accepted input". It stays optional and never blocking
  (Round 3).
- Output is a **spec**, never a brainstorm or a proposal document.
- Twin parity: `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md`
  must stay byte-identical modulo the one documented substitution
  (`tests/sdd_scripts/test_command_twin_parity.py`).

---

## Options Explored

### Option A: Intake front-end inside `/sdd-spec`, research delegated to a subagent

`/sdd-spec` gets a new **§1.5 Intake Mode**, entered when the trigger rule
fires. The command itself asks the fixed intake questions (one batch). After
the user confirms the answers, it reserves the FEAT-ID. Then, by `--research`
depth, it either dispatches a research subagent (`full`), runs today's §4 scan
inline (`light`), or skips (`none`). The subagent reuses `/sdd-proposal`'s prompts
(`research_plan.prompt.md`, `synthesis.prompt.md`, `finding.md`) and writes
into `sdd/state/<FEAT-ID>/intake/`. The command then runs 2–4 adaptive rounds
seeded by the synthesis's unknowns and localization. Next it runs §3b (codex)
over intake + synthesis, then the normal §2d sync, §4 contract, §5 scaffold and
§6 commit. For "create Jira" it finishes with `/sdd-tojira`.

✅ **Pros:**
- Stays inside one command, exactly as the user chose. It reuses §2d, §3b, §4,
  §5 and §6 unchanged.
- The research machinery is reused and not duplicated. Prompts and schemas are
  shared with `/sdd-proposal`.
- The subagent keeps research file dumps out of the interviewing context. The
  main thread only sees the synthesis.
- The intake record is a first-class, committed artifact (auditable, and
  resumable later).

❌ **Cons:**
- `/sdd-spec` is already 647 lines. This adds a large section, and both twins
  must be edited in lockstep.
- A research subagent run under `full` is slow (the `default` budget is 300 s
  wall time).
- The FEAT-ID must be reserved earlier than §5 in this mode, which changes a
  documented invariant.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonschema` | validate `intake.json` / `state.json` / `synthesis.json` | already used by §3b.4 |
| `codex` CLI | §3b design research | optional; `agy` banned |
| `wikitoolkit` | wiki-first research queries | free under the proposal budget rules |

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-proposal.md` §3–§5 (lines 141–282): research plan, gated
  iteration loop, synthesis and lint rules.
- `sdd/templates/research_plan.prompt.md`, `research_plan.schema.json`,
  `synthesis.prompt.md`, `finding.md`, `state.schema.json`.
- `.claude/commands/sdd-spec.md` §2d `resolve_flow()` (138), §3b codex seat
  (210–384), §4 contract (409), §5/§6 scaffold and commit (446–591).
- `scripts/sdd/reserve_ids.py` `existing_feature_id()` (line 420): an
  idempotent-by-label reservation, so an early reservation is safe to re-run.
- `.claude/commands/sdd-tojira.md`: Jira creation and the spec stamp.

---

### Option B: Intake writes an auto-accepted proposal and chains the existing carry-forward

The intake answers become an *inline source*. `/sdd-spec` internally runs the
`/sdd-proposal` pipeline, writes `sdd/proposals/<slug>.proposal.md` with
`status: accepted`, and continues through today's §2 carry-forward path as if
the user had run `/sdd-proposal` first.

✅ **Pros:**
- Almost no new logic in `/sdd-spec`: the proposal path, §3b preconditions and
  the carry-forward mapping all already work.
- The proposal doc is a human-readable record of the research.

❌ **Cons:**
- Violates the explicit requirement "a spec file will be created (not a
  brainstorm)". It emits an extra exploration document and an extra commit.
- `/sdd-proposal`'s FEAT allocation is still a `max(existing)+1` scan
  (`.claude/commands/sdd-proposal.md:79-82`), not `reserve_ids.py`. Chaining it
  would import that race into `/sdd-spec`.
- Auto-accepting a document the user never reviewed breaks the meaning of
  `status: accepted` that §3b relies on.
- The proposal's Phase 4 review gate and Phase 5 Q&A would interleave awkwardly
  with the intake rounds.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | | |

🔗 **Existing Code to Reuse:**
- The whole of `.claude/commands/sdd-proposal.md`.
- `.claude/commands/sdd-spec.md` §2a–§2c carry-forward.

---

### Option C: Python-backed intake engine (`scripts/sdd/spec_intake.py`)

A deterministic intake state machine in Python: a Pydantic `IntakeRecord`, a
question catalogue (YAML), round bookkeeping, validation (slug, Jira key regex,
projects via FEAT-576's `normalize_project`), and resume. The command becomes
a thin driver: it asks what the engine says to ask and feeds the answers back.

✅ **Pros:**
- Testable with pytest. Intake rules become code, not prose.
- Resume and round limits are enforced deterministically, not by LLM
  discipline.
- The dev-flow `IdeationNode` could reuse it later.

❌ **Cons:**
- The largest effort by far. It is a new module plus tests for what is mostly
  conversation.
- The adaptive-round questions are LLM-generated by nature. The engine can only
  bound them, not produce them.
- The engine would sit between the LLM and `AskUserQuestion`, adding friction
  to every turn.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | `IntakeRecord` model | already a core dep |
| `pyyaml` | question catalogue | already present |

🔗 **Existing Code to Reuse:**
- `parrot.knowledge.wiki.ledger.sdd_meta` (via the `scripts/sdd/sdd_meta.py` shim)
  for flow and taxonomy parsing.

---

## Recommendation

**Option A** is recommended, with one element borrowed from C: the intake
record is persisted as `sdd/state/<FEAT-ID>/intake/intake.json`, validated
against a new `sdd/templates/intake.schema.json`. This follows the same
pattern as `state.schema.json`, with no Python engine.

- It is the only option that fully satisfies "mode of `/sdd-spec`" plus
  "outputs a spec, not a brainstorm". B fails the second, and C is overkill
  for a mostly conversational flow.
- It maximises reuse. The research prompts and schemas are shared with
  `/sdd-proposal`, and §2d/§3b/§4/§5/§6 run unchanged downstream.
- The cost is a longer `/sdd-spec` and an earlier FEAT-ID reservation in intake
  mode. Both are acceptable. `reserve_ids.py` is idempotent by label, and the
  length can be contained by moving the intake procedure into a referenced
  section, or into a shared doc if the twin test allows it (see Open Questions).

---

## Feature Description

### User-Facing Behavior

```
/sdd-spec [<slug>] [--interview | --no-interview] [--research full|light|none] [--type …] [--base-branch …] [-- notes]
```

1. The user runs `/sdd-spec` (optionally with a slug) with no exploration doc
   and no notes. The command announces intake mode and the research depth.
2. **Round 0**: flow type and base branch (same as `/sdd-brainstorm`).
3. **Intake batch** (fixed questions): feature name/slug; related project(s)
   (choices from `KNOWN_PROJECTS`, free text allowed); overview (free text);
   problem being solved; Jira (existing key / create after spec / none); why it
   matters. The user sees a summary and confirms or edits it.
4. **Research** (`full` by default). A research plan is shown for approval (the
   same gate as `/sdd-proposal`, skipped with `--no-gate`), then runs in a
   subagent. The user sees a synthesis summary: localization, constraints,
   unknowns and confidence.
5. **Adaptive rounds** (2–4). The questions are built from the intake gaps plus
   the synthesis `unknowns`/hypotheses. They stop after round 2 when no
   critical gap remains.
6. The spec is written and committed. If "create Jira" was chosen,
   `/sdd-tojira <spec>` runs and stamps the key.
7. The output block reports: the spec path, FEAT-ID, research depth and
   confidence, rounds used, open questions carried to §8, and the Jira key.

### Internal Behavior

- **Trigger resolution** (§1): `interview = --interview or (not --no-interview
  and no exploration doc and no notes)`. If `--interview` is given together
  with an existing brainstorm, the command warns and uses the brainstorm (the
  carry-forward rule wins).
- **FEAT-ID reservation moves earlier in intake mode.** It happens right after
  the intake batch is confirmed and the slug is final (`reserve_ids.py --kind
  feature --label <slug>`), because `state.schema.json` requires a `feat_id`
  matching `^FEAT-[0-9]{3,}$`. §5 then finds the existing reservation through
  `existing_feature_id()` and does not reserve twice.
- **State layout**: `sdd/state/<FEAT-ID>/intake/` holds `intake.json` (Q&A
  record: fixed answers plus each adaptive round's questions and answers),
  `source.md` (the intake rendered as an inline source), `state.json`,
  `research_plan.json`, `findings/F*.md` and `synthesis.json`. It is committed
  with the spec in §6.
- **Research subagent brief**: the rendered `source.md`, the budget profile and
  `wiki_available`. It returns the `synthesis.json` path. The main thread never
  reads raw findings unless it needs to cite them in §6.
- **Spec mapping**: overview → §2 Overview seed; problem → §1 Problem Statement;
  why it matters → §1 Goals (business value); projects → frontmatter
  `projects:` (FEAT-576); synthesis `localization`/`constraints` → §6 contract
  seeds (re-verified in §4); unresolved `unknowns` → §8 `[ ]`; answered
  adaptive questions → §8 `[x]` with the answer.
- **§3b** preconditions are extended to "accepted exploration doc **or**
  confirmed intake". The brief sources map from `intake.json` and
  `synthesis.json` (problem, constraints, overview as scope, localization
  paths, open unknowns). The forbidden-content rule still holds, so the brief
  never includes any spec draft.
- **Jira**: an existing key is validated (`^[A-Z]+-\d+$`) and written into the
  header. "create" invokes `/sdd-tojira` after §6. That command commits its own
  stamp.

### Edge Cases & Error Handling

- **Non-interactive invocation** (subagents, dev-loop): these callers must pass
  `--no-interview`. As a defensive fallback, a caller that passes
  `--type`/`--base-branch` from an agent brief still triggers the rule. That is
  why the agent definitions are updated, not only the command.
- **Research failure or timeout under `full`**: degrade to `light`, record
  `state.json` `phase: failed` plus the reason, and continue. Never abort the
  spec.
- **`--research none`**: §4 still builds the Codebase Contract. `none` only skips
  the proposal-style research. A spec is never written without a verified §6.
- **Slug collision**: a spec `sdd/specs/<slug>.spec.md` already exists, so abort
  with a pointer to it. A reservation already exists for the slug, so reuse it
  (idempotent).
- **The user abandons mid-intake**: the reserved FEAT-ID stays in the ledger
  unused, and the partial `intake/` stays uncommitted in the working tree
  (see Open Questions on resume).
- **FEAT-576 not yet merged**: the project question degrades to free text,
  recorded in `intake.json` and the spec body only (not a hard failure).
- **Jira creation fails** (API down): the spec is already committed. Report the
  failure and the manual `/sdd-tojira` command.

---

## Capabilities

### New Capabilities
- `sdd-spec-intake-mode`: interview-driven spec creation inside `/sdd-spec`
  (trigger rule, fixed intake batch, adaptive rounds, intake persistence).
- `sdd-spec-research-depth`: the `--research full|light|none` flag that
  dispatches the proposal research machinery.

### Modified Capabilities
- `sdd-flow-types-and-per-spec-index` (FEAT-145) / `/sdd-spec`: the FEAT-ID
  reservation point moves in intake mode, and the §3b preconditions are
  extended.
- `sdd-spec-changes` (FEAT-576): a consumer of `KNOWN_PROJECTS` /
  `normalize_project` / `projects:` frontmatter.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.claude/commands/sdd-spec.md` | modifies | new §1.5 Intake Mode, flags, trigger rule, §3b precondition, output block |
| `.agent/workflows/sdd-spec.md` | modifies | twin, byte-identical body (parity test) |
| `.agents/skills/sdd-spec/SKILL.md` | modifies | codex-side summary of the new mode/flags |
| `.claude/agents/sdd-research.md` | modifies | pass `--no-interview` (its call at lines 75–76 matches the auto-trigger today) |
| `.claude/agents/sdd-planner.md` | modifies | pass `--no-interview` wherever it invokes `/sdd-spec` |
| `sdd/templates/intake.schema.json` | new | schema for `intake.json` |
| `sdd/templates/research_plan.prompt.md`, `synthesis.prompt.md` | depends on | reused as-is; may need an "intake" source kind |
| `sdd/templates/state.schema.json` | depends on / maybe modifies | `source.kind` may need `intake` |
| `scripts/sdd/reserve_ids.py` | depends on | early reservation; idempotent via `existing_feature_id` |
| `.claude/commands/sdd-tojira.md` | depends on | called for "create Jira" |
| FEAT-576 `parse_taxonomy` / `KNOWN_PROJECTS` | depends on | project choices and frontmatter |
| `tests/sdd_scripts/test_command_twin_parity.py` | depends on | must keep passing |
| `docs/sdd/WORKFLOW.md`, `CLAUDE.md` Typical Workflow | modifies | document the new entry point |

---

## Code Context

### User-Provided Code
None. The request was prose.

### Verified Codebase References

#### Command anchors (`.claude/commands/sdd-spec.md`, 647 lines)
- `## Usage` (line 6): current signature
  `/sdd-spec <feature-name> [--type feature|hotfix] [--base-branch <branch>] [-- free-form description and notes]`
- `### 1. Parse Input` (38): feature-name, and `--` notes as the Problem Statement seed
- `### 2. Check for Prior Exploration` (42): "If neither exists, proceed to §3."
- `#### 2d. Sync the Base Branch` (138): `resolve_flow(doc_path, type_override, base_branch_override)`
- `### 3b. Collaborative Design Research` (210). Precondition: exploration doc `accepted`
  plus `command -v codex`. Staging dir `sdd/state/.design_research/<feature-name>-${RUN_ID}`,
  because "FEAT-ID is reserved only in §5".
- `#### 3b.2` (278): brief sources — `problem_statement.txt`, `constraints_and_goals.txt`,
  `recommended_option_or_scope.txt`, `code_context_paths.txt`, `open_questions.txt`, `question.txt`
- `### 3. Ask Clarifying Questions` (386), `### 4. Research the Codebase` (409),
  `### 5. Scaffold the Spec` (446), `### 6. Commit the Spec` (553), `### 7. Output` (592)

#### Research machinery (`.claude/commands/sdd-proposal.md`)
- Step 1 FEAT allocation is `max(existing)+1` over `sdd/specs`, `sdd/proposals`, `sdd/state` (lines 79–82). It does NOT use `reserve_ids.py`.
- `--budget tight|default|loose` table (lines ~93–97); `default` = 40 files, 25 greps, 10 git, depth 2, 300 s
- Phase 1 plan: `sdd/templates/research_plan.prompt.md` → `research_plan.schema.json` (line 155)
- Phase 2 loop plus stop conditions (198–239); wiki queries are budget-free
- Phase 3 synthesis: `sdd/templates/synthesis.prompt.md` (254), with lint rules 1–5 (262–282)
- Phase 5 targeted Q&A (329)

#### Templates (`sdd/templates/`)
- `state.schema.json`: `required = [schema_version, feat_id, started_at, source, mode, phase, phases, budget, consumed]`;
  `feat_id` pattern `^FEAT-[0-9]{3,}$`; `phase` enum
  `source_resolved … synthesis_complete, review_gate, qa_pending, qa_complete, proposal_drafted, committed, failed`
- `spec.md`: §1 has `Problem Statement` / `Goals` / `Non-Goals`; §8 Open Questions; §9 Design Research Cross-Check. There is no `**Jira**` field in the template.

#### Scripts
```python
# From scripts/sdd/reserve_ids.py
def existing_feature_id(root: Path, label: str) -> tuple[str, str] | None:  # line 420
def reserve_ids(...)                                                         # line 468
# CLI: --kind {task,feature} --count N --base-branch B --label L [--max-retries 5]  (lines 629–633)
```
```python
# scripts/sdd/sdd_meta.py is a shim re-exporting from parrot.knowledge.wiki.ledger.sdd_meta:
from parrot.knowledge.wiki.ledger.sdd_meta import (
    KNOWN_BRANCHES, WORK_KIND_FLOW, WORKTREE_ROOT, FlowMeta, WorktreePlan,
    emit, parse, plan_worktree, resolve_flow,
)
```

#### Twin parity
- `tests/sdd_scripts/test_command_twin_parity.py`: `_TWINNED = ("sdd-spec", "sdd-task")`.
  The twin body must equal the original after exactly one substitution
  (`CLAUDE.md` → `AGENTS.md` on the "Worktree policy" reference line).

#### Jira stamp
- `.claude/commands/sdd-tojira.md:100` recognises a spec body line
  `**Jira**: [NAV-8036](...)`. Usage accepts a spec path or a `FEAT-<NNN>` (lines 16–21).

#### Planned by FEAT-576 (NOT yet implemented, spec only)
```python
# sdd/specs/sdd-spec-changes.spec.md §3 (planned, parrot.knowledge.wiki.ledger.sdd_meta)
KNOWN_PROJECTS: frozenset[str]
def parse_taxonomy(doc_path: Path) -> DocTaxonomy: ...
def normalize_tag(raw: str) -> str: ...
def normalize_project(raw: str) -> str: ...
```

### Does NOT Exist (Anti-Hallucination)
- ~~`/sdd-feature`~~: no such command. This feature is a mode of `/sdd-spec`, by decision.
- ~~`--interview` / `--research` flags on `/sdd-spec`~~: not present today.
- ~~`sdd/templates/intake.schema.json`~~: to be created.
- ~~`sdd/state/<FEAT>/intake/`~~: no such directory convention yet (only `design_research/`, `findings/`).
- ~~`parse_taxonomy`, `KNOWN_PROJECTS`~~: planned in FEAT-576, not yet in `sdd_meta`.
- ~~A `**Jira**:` field in `sdd/templates/spec.md`~~: only `/sdd-tojira` writes that line.
- ~~`/sdd-proposal` using `reserve_ids.py`~~: it still uses a max+1 scan.

---

## Parallelism Assessment

- **Internal parallelism**: low. Almost all changes land in `sdd-spec.md` and its
  twin, which must change together. `intake.schema.json` and the agent-definition
  `--no-interview` updates are independent small tasks.
- **Cross-feature independence**: conflicts with **FEAT-576** (also edits
  `.claude/commands/sdd-spec.md` and its twin to carry projects/tags forward),
  and with any in-flight `/sdd-spec` change. Sequence this feature after FEAT-576 merges.
- **Recommended isolation**: `per-spec`.
- **Rationale**: a single hot file pair under a byte-parity test makes
  concurrent worktrees a merge-conflict generator.

---

## Open Questions

- [x] New command or mode? — *Owner: Jesus Lara*: a mode of `/sdd-spec`.
- [x] Research depth? — *Owner: Jesus Lara*: `--research full|light|none`, default `full`.
- [x] When to create Jira? — *Owner: Jesus Lara*: after the spec is written, via `/sdd-tojira`.
- [x] Trigger? — *Owner: Jesus Lara*: auto (no exploration doc and no notes), plus `--interview` / `--no-interview`.
- [x] Persist intake? — *Owner: Jesus Lara*: `sdd/state/<FEAT-ID>/intake/`, committed.
- [x] Unattended lanes? — *Owner: Jesus Lara*: interactive only; unattended callers pass `--no-interview`.
- [x] Relation to FEAT-576? — *Owner: Jesus Lara*: depends on it; the intake writes `projects:`/`tags:`.
- [x] Codex §3b in intake mode? — *Owner: Jesus Lara*: runs over confirmed intake + research synthesis.
- [x] Adaptive rounds? — *Owner: Jesus Lara*: min 2, max 4, gap-driven.
- [x] Research ordering? — *Owner: Jesus Lara*: between the fixed intake and the adaptive rounds.
- [ ] Should the FEAT-ID be reserved right after intake confirmation (an abandoned intake burns an ID), or should research stage in an id-less dir with `state.schema.json` relaxed to allow a null `feat_id`? — *Owner: Jesus Lara*
- [ ] Should `--resume <FEAT-ID>` exist for an interrupted intake (read `intake.json` and `state.json`), or is re-running from scratch acceptable in v1? — *Owner: Jesus Lara*
- [ ] Keep the intake procedure inline in `sdd-spec.md`, or move it to a shared referenced doc (e.g. `sdd/templates/intake.procedure.md`) to limit the size of a twinned file? — *Owner: Jesus Lara*
- [ ] Should this feature also switch `/sdd-proposal`'s max+1 FEAT allocation to `reserve_ids.py` (it shares the research machinery), or leave that to a separate fix? — *Owner: Jesus Lara*
- [ ] Should the research-plan approval gate be shown in intake mode by default, or skipped (the user just answered the intake and may not want a second gate)? — *Owner: Jesus Lara*
