---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: `/sdd-spec` Intake Mode — Interview-Driven Spec Creation

**Feature ID**: FEAT-577
**Date**: 2026-09-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: n/a — repository SDD tooling (commands, templates, agent prompts); no package release. The `_subagent_data/` prompt edits ship with the next `ai-parrot` minor.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Today a spec is well grounded only when a brainstorm (`/sdd-brainstorm`) or a
proposal (`/sdd-proposal`) was written first. `/sdd-spec` then carries that
document forward (§2a–§2c). Without one, `/sdd-spec` falls back to a thin path.
The free-form `--` notes become the Problem Statement seed, then one batch of
"genuinely missing" questions runs (§3), then a codebase scan (§4). That path
never collects the feature's identity in a structured way: which project it
concerns, why it matters, or whether a Jira ticket exists or should be created.
It also never runs the deep, confidence-graded research that `/sdd-proposal`
does.

The workaround costs two commands and a throwaway artifact:
`/sdd-brainstorm` (an options analysis the author may not need) followed by
`/sdd-spec`. For a feature whose direction the author already knows, what they
need is a **structured interview → grounded research → adaptive Q&A → spec**
in one run.

This affects the developers and tech lead who author specs interactively. The
unattended lanes (`sdd-planner`, `sdd-research`, dev-loop) must keep their
current behavior.

### Goals
- G1. `/sdd-spec` gains an **intake mode**. It is entered automatically when no
  `<slug>.brainstorm.md` / `<slug>.proposal.md` exists **and** no `--` notes were
  given. `--interview` forces it and `--no-interview` suppresses it.
- G2. The intake asks a **fixed question batch**: flow type/base branch (Round 0);
  feature name/slug; related project(s); overview (free text); problem being
  solved; Jira (existing key | create after the spec | none); why the feature
  matters. The user confirms or edits a summary before anything else happens.
- G3. **Research runs between the fixed batch and the adaptive rounds**, at
  depth `--research full|light|none`, **default `full`**. `full` dispatches a
  research subagent that runs `/sdd-proposal`'s plan → iterate → synthesize
  machinery, reusing its prompts and schemas. `light` is today's §4 scan run
  early. `none` skips it.
- G4. **2–4 adaptive Q&A rounds**, gap-driven and seeded by intake gaps plus the
  research synthesis's `unknowns` and hypotheses. The rounds stop after round 2
  when no critical gap remains. Anything still unresolved after round 4 lands
  in spec §8 as `[ ]`.
- G5. The intake record and research artifacts are **staged id-less** under
  `sdd/state/.intake/<slug>-<RUN_ID>/` (git-ignored). The FEAT-ID is still
  reserved in §5, unchanged. §6 promotes the staging dir to
  `sdd/state/<FEAT-ID>/intake/` and commits it with the spec.
- G6. An interrupted intake is **resumable** via `--resume`. It reads the staged
  `intake.json` / `state.json` and continues from the recorded phase.
- G7. The codex **§3b design-research pass runs in intake mode** over the
  *confirmed intake answers + research synthesis*, treated as the accepted
  input. It stays optional and never blocking.
- G8. **Jira**: an existing key is validated and stamped as `**Jira**: [KEY](url)`.
  "Create" runs `/sdd-tojira <spec>` **after** the spec commit.
- G9. The intake writes `projects:` / `tags:` frontmatter using FEAT-576's
  vocabulary (`KNOWN_PROJECTS`, `normalize_project`, `normalize_tag`). When
  FEAT-576 is not importable it degrades to free text in the spec body.
- G10. The output is **always a spec**, never a brainstorm or a proposal
  document.
- G11. **Unattended lanes never interview.** Every agent prompt that invokes
  `/sdd-spec` passes `--no-interview`, in both the `.claude/agents/` and the
  `_subagent_data/` copies.
- G12. **Brainstorm hand-off.** When the research synthesis recommends
  `sdd-brainstorm` (`recommended_next_command.command`, i.e. medium confidence
  or several viable architectural paths), the intake **offers** to switch to
  `/sdd-brainstorm` instead of writing the spec. If the user accepts, no spec is
  written and no FEAT-ID is reserved. The intake answers and synthesis seed the
  brainstorm's discovery, and `intake.json` ends at `phase: handed_off`.
- G13. **Staging retention.** `sdd/state/.intake/` is git-ignored, and staged
  runs **older than 10 days are pruned during `/sdd-status`** by a small,
  tested script (`scripts/sdd/prune_intake.py`). This is the one documented
  exception to `/sdd-status`'s read-only guardrail, and it may only delete
  untracked staging directories under `sdd/state/.intake/`.

### Non-Goals (explicitly out of scope)
- A new `/sdd-feature` command. The user chose a *mode* of `/sdd-spec`; a
  standalone command was considered and rejected.
- Emitting a `.brainstorm.md` or `.proposal.md` from intake mode. Brainstorm
  Option B (chain an auto-accepted proposal) was rejected, see
  `sdd/proposals/sdd-feature-specification.brainstorm.md` Option B.
- A Python intake engine / state machine (brainstorm Option C, rejected as
  overkill). Only the persisted `intake.json` record plus its JSON Schema is
  kept from it.
- Switching `/sdd-proposal`'s `max(existing)+1` FEAT allocation to
  `reserve_ids.py`. It is left for a separate fix.
- Intake in unattended lanes (dev-loop `IdeationNode`, `sdd-planner`,
  `sdd-research`).
- Changing when the FEAT-ID is reserved. It stays in §5 for every mode.

---

## 2. Architectural Design

### Overview

Intake mode is a front-end that runs **before** the normal `/sdd-spec`
pipeline. Once it ends, the rest of the command (§2d sync, §3b codex, §4
contract, §5 scaffold/reserve, §6 commit, §7 output) runs as today. Its inputs
come from the intake record and the synthesis rather than from a brainstorm.

The full procedure lives in **one shared file**,
`sdd/templates/intake.procedure.md`. Both `/sdd-spec` twins
(`.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-spec.md`) gain only a
short **§1.5 Intake Mode** that states the trigger rule and delegates to the
procedure. This keeps the twinned files small and the byte-parity test
(`tests/sdd_scripts/test_command_twin_parity.py`) trivially satisfiable.

**Trigger rule** (§1):
```
if --resume:                                 → resume intake (G6)
elif --no-interview:                         → today's path
elif --interview:                            → intake (warn and ignore if an exploration doc exists: carry-forward wins)
elif no exploration doc and no `--` notes:   → intake
else:                                        → today's path
```
An agent that cannot ask the user anything (running as a subagent, no
interactive question tool) must behave as `--no-interview` even without the
flag. This is a defensive fallback on top of G11.

**Procedure phases** (recorded in `intake.json.phase`):

1. `started`: allocate `RUN_ID`, create `sdd/state/.intake/<slug>-<RUN_ID>/`.
   The slug may be unknown yet; if so, stage under `_pending-<RUN_ID>` and
   rename once the slug is confirmed.
2. **Round 0 + fixed batch** → `intake_confirmed`. One batch of questions. The
   project question offers `KNOWN_PROJECTS` as choices and still allows free
   text (normalized with `normalize_project`). A Jira key is validated with
   `^[A-Z][A-Z0-9]+-\d+$`. The slug is checked against `sdd/specs/<slug>.spec.md`
   (exists ⇒ abort with a pointer) and against exploration docs (exists ⇒ stop
   intake and fall back to the carry-forward path). A summary is shown and the
   user confirms or edits it.
3. **Research** → `research_running` → `research_complete` (or `research_degraded`).
   - `full`: render `source.md` (kind `intake`) from the confirmed answers, then
     run `/sdd-proposal` Phase 1 (plan, gate shown unless `--no-gate`), Phase 2
     (iteration loop, budget `--budget`, default `default`) and Phase 3
     (synthesis + lint) **in a research subagent**. It writes `state.json`
     (`feat_id: null`), `research_plan.json`, `findings/F*.md` and
     `synthesis.json` into the staging dir. The main thread reads only
     `synthesis.json`.
   - `light`: run today's §4 scan now and record the findings as
     `findings/F*.md` digests. No synthesis.
   - `none`: skip. §4 still builds the Codebase Contract later.
   - If the subagent fails or times out under `full`, degrade to `light`, record
     `research.degraded_from = "full"` and `research.failure_reason`, and
     continue. The spec is never aborted.
4. **Adaptive rounds** → `rounds_complete`. Round *k* (2 ≤ k ≤ 4) asks 3–5
   questions built from intake gaps plus the synthesis `unknowns` and competing
   hypotheses. Each question is recorded with `source: gap|synthesis`. The rounds
   stop after round 2 when no critical gap remains. After round 4 the rest go
   to §8 `[ ]`.
5. Hand-off to the normal pipeline. §2d `resolve_flow(doc_path=None,
   type_override=<Round 0 type>, base_branch_override=<Round 0 base>)` runs,
   then §3b (intake variant), §4 (seeded by synthesis `localization` /
   `constraints`, re-verified), §5 (reserve the FEAT-ID, unchanged; write
   `intake.json.feat_id`), §6 (promote plus commit) → `committed`.
6. **Jira "create"**: after §6, run `/sdd-tojira sdd/specs/<slug>.spec.md`. It
   commits its own stamp. On failure, report the error and print the manual
   command. The spec stays committed.

**Brainstorm hand-off** (G12), evaluated once research completes and before
the adaptive rounds:
- `full` research whose `synthesis.json.recommended_next_command.command ==
  "sdd-brainstorm"`: show the rationale and ask *"Research found competing
  approaches — switch to `/sdd-brainstorm` (seeded with this intake), or
  continue to the spec?"*.
  - **Switch**: set `intake.json.phase = handed_off` and stop `/sdd-spec` (no
    §2d–§6, no FEAT-ID). Tell the user to run `/sdd-brainstorm <slug> --
    intake: sdd/state/.intake/<slug>-<RUN_ID>/`. `/sdd-brainstorm` reads
    `intake.json` + `synthesis.json` from that path as discovery context: its
    Round 0 and the fixed-batch facts count as already answered, and it still
    runs its own rounds. The staging dir stays in place and is pruned under G13.
  - **Continue**: record the choice in `intake.json.research.handoff_declined =
    true` and proceed to the adaptive rounds.
- `manual-review`: print the rationale as a warning and continue. No switch is
  offered, because there is no command to hand off to.
- `sdd-spec` / `sdd-task`, `light`, `none`: no offer.

**Staging retention** (G13): `/sdd-status` gets a new first step that runs
`python -m scripts.sdd.prune_intake --older-than-days 10 --apply` and reports
the pruned dirs in one line (or stays silent when there are none). A run's age
is `now - intake.json.updated_at`, falling back to the directory mtime when
`intake.json` is missing or unreadable. `--resume` does not refresh an expired
run. Once pruned, the run is gone and the user starts again with `--interview`.

**Spec mapping from intake:**

| Intake source | Spec target |
|---|---|
| problem | §1 Problem Statement |
| why it matters | §1 Goals (business value) + Problem Statement motivation |
| overview | §2 Overview seed |
| projects / suggested tags | frontmatter `projects:` / `tags:` (FEAT-576) |
| Jira existing key | header `**Jira**: [KEY](<instance>/browse/KEY)` |
| synthesis `localization`, `constraints` | §6 Codebase Contract seeds (re-verified in §4) + §7 Known Risks |
| synthesis `unknowns` not answered in rounds | §8 `[ ]` |
| answered adaptive questions | route into the section they decide, plus §8 `[x] … — *Resolved in intake*: <answer>` |

**§3b in intake mode**: the precondition "exploration doc with status
`accepted`" is extended with "**or** `intake.json.phase ≥ rounds_complete`".
The brief sources in intake mode are:
`problem_statement.txt` ← intake problem + why it matters;
`constraints_and_goals.txt` ← synthesis `constraints` (or "none");
`recommended_option_or_scope.txt` ← intake overview + answered adaptive
questions; `code_context_paths.txt` ← synthesis `localization[].path`
(or `light` findings' paths); `open_questions.txt` ← unresolved items.
The forbidden-content rule is unchanged: nothing from the spec draft goes in.

**Resume** (`/sdd-spec <slug> --resume`, or `--resume <staging-dir>`): select
the newest `sdd/state/.intake/<slug>-*/intake.json` whose `phase` is not
`committed`, validate it against `intake.schema.json`, and continue from the
first incomplete phase. A research phase already `research_complete` is not
re-run. A `research_running` phase is resumed with `/sdd-proposal` Step R
semantics against the staged `state.json`. With no staging dir, the command
reports "nothing to resume" and suggests `--interview`. A `--resume FEAT-<NNN>`
argument is rejected with a message, because intake has no FEAT-ID until §5
(see §8, resolved question on resume).

### Component Diagram
```
/sdd-spec <slug?> [--interview|--no-interview|--resume] [--research full|light|none]
   │
   ├─ §1 trigger rule ──(today's path)──────────────────────────────┐
   │                                                                │
   └─ §1.5 Intake Mode ─→ sdd/templates/intake.procedure.md         │
        │  Round 0 + fixed batch ─→ intake.json (intake.schema.json) │
        │  research (full) ─→ research subagent                      │
        │        └─ research_plan.prompt.md / synthesis.prompt.md    │
        │           state.json (state.schema.json, feat_id: null)    │
        │  adaptive rounds (2–4) ─→ intake.json.rounds[]             │
        ▼                                                            ▼
   §2d resolve_flow → §3b codex (intake brief) → §4 contract → §5 reserve FEAT → §6 commit
                                                                     │  promote .intake/<slug>-<run> → sdd/state/<FEAT>/intake/
                                                                     └─ Jira "create" → /sdd-tojira
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-spec.md` + `.agent/workflows/sdd-spec.md` | modifies | usage/flags, §1 trigger, §1.5 pointer, §3b precondition + intake brief sources, §6 promotion of intake staging, §7 output lines, Reference |
| `.agents/skills/sdd-spec/SKILL.md` | modifies | codex-side summary of the mode and flags |
| `sdd/templates/intake.procedure.md` | new | the full procedure (single source) |
| `sdd/templates/intake.schema.json` | new | JSON Schema for `intake.json` |
| `sdd/templates/state.schema.json` | modifies | `feat_id` nullable; `source.kind` gains `intake` |
| `sdd/templates/research_plan.prompt.md`, `synthesis.prompt.md`, `finding.md` | uses (unchanged) | driven with `source.kind = intake`, `feat_id = null` |
| `.claude/commands/sdd-proposal.md` Phases 1–3 + Step R | uses (unchanged) | the research subagent follows them verbatim |
| `scripts/sdd/sdd_meta.py` → `resolve_flow` | uses | `doc_path=None` + Round 0 overrides |
| `scripts/sdd/reserve_ids.py` | uses (unchanged) | §5 reservation as today |
| FEAT-576 `KNOWN_PROJECTS`, `normalize_project`, `normalize_tag` | depends on | project choices + frontmatter; soft-fallback when absent |
| `.claude/commands/sdd-tojira.md` | uses | Jira "create" after commit |
| `.claude/agents/sdd-research.md` + `_subagent_data/sdd-research.md` | modifies | `--no-interview` on both `/sdd-spec` lines |
| `.claude/agents/sdd-planner.md` + `_subagent_data/sdd-planner.md` | modifies | `--no-interview` where it runs `/sdd-spec` |
| `.gitignore` | modifies | ignore `sdd/state/.intake/` |
| `scripts/sdd/prune_intake.py` | new | prune staged intake runs older than N days (G13) |
| `.claude/commands/sdd-status.md` + `.agent/workflows/sdd-status.md` + `.agents/skills/sdd-status/SKILL.md` | modifies | new prune step; the read-only guardrail gains the one documented exception |
| `.claude/commands/sdd-brainstorm.md` | modifies | accept an `intake:` pointer after `--` as pre-answered discovery context (G12) |
| `docs/sdd/WORKFLOW.md` | modifies | document the intake entry point |

### Data Models

`intake.json` is a plain JSON document validated by
`sdd/templates/intake.schema.json` (Draft 2020-12, the same validator
`tests/sdd_scripts/test_design_research_templates.py` uses). There is no Python
model; this is repo tooling, driven by the command prompt.

```jsonc
// sdd/state/.intake/<slug>-<RUN_ID>/intake.json   (→ sdd/state/<FEAT-ID>/intake/intake.json after §6)
{
  "schema_version": "1.0",
  "run_id": "20260919T101500Z-12345",
  "feature_slug": "my-feature",                 // null until confirmed
  "feat_id": null,                              // set in §5; pattern ^FEAT-[0-9]{3,}$ when set
  "started_at": "…", "updated_at": "…",
  "phase": "started | intake_confirmed | research_running | research_complete | research_degraded | rounds_complete | spec_drafted | committed | handed_off | failed",
  "flow": {"type": "feature | hotfix", "base_branch": "dev"},
  "research": {
    "depth": "full | light | none",
    "gate": true,
    "budget": "tight | default | loose",
    "degraded_from": null, "failure_reason": null,
    "synthesis_path": null,                     // "synthesis.json" when full succeeded
    "handoff_declined": false                   // true when the G12 offer was shown and declined
  },
  "answers": {
    "feature_name": "…",
    "projects": ["ai-parrot"],                  // normalized; free text kept when FEAT-576 absent
    "tags": [],
    "overview": "…", "problem": "…", "why_important": "…",
    "jira": {"mode": "existing | create | none", "key": null}
  },
  "rounds": [
    {"round": 1, "questions": [
      {"id": "Q1", "question": "…", "source": "gap | synthesis", "answer": "… | null"}
    ]}
  ],
  "spec_path": null,
  "errors": []
}
```

### New Public Interfaces

Command surface (both twins):
```
/sdd-spec <feature-name> [--type feature|hotfix] [--base-branch <branch>]
          [--interview | --no-interview] [--resume [<staging-dir>]]
          [--research full|light|none] [--no-gate] [--budget tight|default|loose]
          [-- free-form description and notes]
```
- `<feature-name>` becomes optional in intake mode (it is asked in the fixed batch).
- `--research`, `--no-gate` and `--budget` only take effect in intake mode. They
  are ignored, with a one-line notice, on the carry-forward path.

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: intake schema | yes | JSON Schema Draft 2020-12, fields exactly as §2 Data Models; test file layout mirrors `test_design_research_templates.py` | — |
| M2: state schema relax | yes | `feat_id` → `{"type": ["string","null"], "pattern": "^FEAT-[0-9]{3,}$"}`; `source.kind` enum + `"intake"` | — |
| M3: intake procedure | no | — | prose procedure; phrasing of rounds/brief mapping needs judgement |
| M4: `/sdd-spec` twins | no | — | edits a 647-line prompt in lockstep under a byte-parity test |
| M5: codex skill | yes | add usage line + one "Intake mode" paragraph pointing at `intake.procedure.md` | — |
| M6: unattended callers | yes | append ` --no-interview` to the exact lines listed in §6; same edit in both copies | — |
| M7: contract tests | yes | test names in §4 | — |
| M8: docs + gitignore | yes | `.gitignore` line next to 406–407; WORKFLOW.md subsection | — |
| M9: intake retention | yes | `scripts/sdd/prune_intake.py` signatures in Module 9; `/sdd-status` step text fixed in Module 9 | — |
| M10: brainstorm hand-off intake | no | — | prose change to `/sdd-brainstorm`'s discovery rules; judgement about which questions count as answered |

### Module 1: Intake record schema
- **Path**: `sdd/templates/intake.schema.json` (new), `tests/sdd_scripts/test_intake_templates.py` (new)
- **Responsibility**: define and validate `intake.json` (§2 Data Models). This includes `feat_id` null-or-pattern, the `phase` enum, the `research.depth` enum, the `jira.mode` enum, the `source` enum on questions, `additionalProperties: false` at every object level, and the required keys `schema_version, run_id, started_at, updated_at, phase, flow, research, answers, rounds`.
- **Depends on**: none
- **Interface Skeleton**:
  ```jsonc
  // sdd/templates/intake.schema.json  (new)
  {"$schema": "https://json-schema.org/draft/2020-12/schema",
   "$id": "sdd/templates/intake.schema.json",
   "title": "SDD /sdd-spec intake record",
   "type": "object", "additionalProperties": false,
   "required": ["schema_version", "run_id", "started_at", "updated_at", "phase", "flow", "research", "answers", "rounds"],
   "properties": { /* exactly the §2 Data Models fields */ }}
  ```

### Module 2: Research state schema accepts id-less intake runs
- **Path**: `sdd/templates/state.schema.json` (modifies lines 24–28 `feat_id`, line 47 `source.kind`, line 51 `raw_path` description)
- **Responsibility**: make `feat_id` nullable. Add `"intake"` to `source.kind`. Change the `raw_path` description to "sdd/state/<FEAT-ID>/source.md, or sdd/state/.intake/<slug>-<RUN_ID>/source.md in /sdd-spec intake mode". Every existing `sdd/state/FEAT-*/state.json` must still validate.
- **Depends on**: none
- **Interface Skeleton**:
  ```jsonc
  // sdd/templates/state.schema.json  (modifies :24 and :47)
  "feat_id": {"type": ["string", "null"], "pattern": "^FEAT-[0-9]{3,}$",
              "description": "Stable feature ID. Null while a /sdd-spec intake run is staged id-less; set when §5 reserves it."},
  "kind": {"enum": ["jira", "inline", "file", "intake"]}
  ```

### Module 3: Intake procedure (single source)
- **Path**: `sdd/templates/intake.procedure.md` (new)
- **Responsibility**: the complete, tool-agnostic procedure from §2 Overview. It covers the trigger-rule restatement, staging layout, Round 0 plus the fixed batch (exact question wording and validation), the confirm/edit summary, the research dispatch per depth (including the subagent brief: `source.md`, budget block, `wiki_available`, "return only the synthesis.json path"), degrade rules, the adaptive-round algorithm and stop rule, the spec mapping table, the §3b intake brief-source mapping, the Jira step, resume, and the `intake.json` update points (every phase transition updates `phase` + `updated_at`). It says "use your interactive question tool (e.g. `AskUserQuestion`) when available; otherwise ask in plain text", so the codex/`.agent` lanes can follow it too.
- **Depends on**: M1, M2 (references their paths)
- **Interface Skeleton**:
  ```markdown
  # /sdd-spec Intake Procedure
  ## 0. When this runs (trigger rule — mirrors /sdd-spec §1)
  ## 1. Staging (RUN_ID, sdd/state/.intake/<slug>-<RUN_ID>/, intake.json init)
  ## 2. Round 0 + fixed intake batch (questions, validation, confirm/edit)
  ## 3. Research by depth (full → subagent via /sdd-proposal Phases 1–3; light; none; degrade)
  ## 3b. Brainstorm hand-off offer (synthesis recommends sdd-brainstorm → switch | continue)
  ## 4. Adaptive rounds (2–4, gap-driven, stop rule)
  ## 5. Hand-off to /sdd-spec §2d–§6 (spec mapping table, §3b intake brief sources)
  ## 6. Jira (existing → stamp; create → /sdd-tojira after §6; none)
  ## 7. Resume (--resume [<staging-dir>])
  ## 8. Failure handling (never abort the spec for a research failure)
  ```

### Module 4: `/sdd-spec` twins wire intake mode in
- **Path**: `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md` (modify both identically)
- **Responsibility**:
  - Usage (line 6ff): the new flags from §2 New Public Interfaces.
  - §1 Parse Input (38): the trigger rule. `<feature-name>` is optional when intake runs.
  - New **§1.5 Intake Mode** (≤ 40 lines): a pointer to `sdd/templates/intake.procedure.md`, plus the statement that §2d–§6 then run with the intake record as input.
  - §2 (48): "If neither exists, proceed to §3" becomes "…proceed to §1.5 when intake mode is active, otherwise §3".
  - §3b preconditions (218–219): add the intake alternative. In §3b.2 add the intake source column.
  - §3 Clarifying Questions: in intake mode it is skipped (the adaptive rounds replace it).
  - §6 (568ff): promote `sdd/state/.intake/<slug>-<RUN_ID>` → `sdd/state/<FEAT-ID>/intake/`, with the same collision-safe copy/move pattern as the design-research promotion. Stage it with the spec. Set `intake.json.phase = committed` and `feat_id` before staging.
  - §7 Output: add `Intake: research <depth> (confidence <c> | degraded | skipped), rounds <n>, open questions <m>, Jira <KEY | created KEY | none>`.
  - Reference (633ff): add the procedure and schema paths.
  - The parity anchor at line 637 (`- Worktree policy: \`CLAUDE.md\` (section "Worktree Policy")`) must remain present **exactly once** and unchanged.
- **Depends on**: M3 (points at it), M1/M2 (names the schemas)
- **Interface Skeleton**:
  ```markdown
  ### 1.5 Intake Mode (interactive only)
  Runs when §1's trigger rule selects it. Follow `sdd/templates/intake.procedure.md`
  end to end; it hands back a confirmed `intake.json` (+ `synthesis.json` for
  `--research full`) under `sdd/state/.intake/<slug>-<RUN_ID>/`. Then continue at
  §2d with `doc_path=None` and the Round 0 flow as overrides …
  ```

### Module 5: Codex-side skill summary
- **Path**: `.agents/skills/sdd-spec/SKILL.md` (modifies line 11 invocation + Workflow section)
- **Responsibility**: add the new flags to the `$sdd-spec` invocation line, plus a short "Intake mode" paragraph that points at `sdd/templates/intake.procedure.md`.
- **Depends on**: M3

### Module 6: Unattended callers never interview
- **Path**: `.claude/agents/sdd-research.md:75-76` and `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md:75-76`; `.claude/agents/sdd-planner.md:46` and `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md:46`
- **Responsibility**: every `/sdd-spec` invocation line gains `--no-interview`. The planner's prose line 46 ("run ``/sdd-spec`` to scaffold…") becomes "run ``/sdd-spec <slug> --no-interview`` …". The two copies of each agent stay byte-identical (`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`).
- **Depends on**: M4 (the flag must exist)
- **Interface Skeleton**:
  ```
  /sdd-spec <slug> --type hotfix --base-branch main --no-interview      # kind == "bug"
  /sdd-spec <slug> --type feature --base-branch dev --no-interview       # kind == "enhancement" | "new_feature"
  ```

### Module 7: Contract tests
- **Path**: `tests/sdd_scripts/test_intake_templates.py` (new; also covers M2), `tests/sdd_scripts/test_command_contracts.py` (extend)
- **Responsibility**: the tests in §4.
- **Depends on**: M1, M2, M4, M6

### Module 8: Docs + ignore rule
- **Path**: `.gitignore` (add `sdd/state/.intake/` beside lines 406–407), `docs/sdd/WORKFLOW.md` (new subsection "Starting from an interview: `/sdd-spec` intake mode")
- **Responsibility**: keep staging out of git. Document the new entry point, its flags, and how it relates to `/sdd-brainstorm` / `/sdd-proposal`.
- **Depends on**: M3

### Module 9: Intake staging retention
- **Path**: `scripts/sdd/prune_intake.py` (new), `tests/sdd_scripts/test_prune_intake.py` (new), `.claude/commands/sdd-status.md` + `.agent/workflows/sdd-status.md` + `.agents/skills/sdd-status/SKILL.md` (modify)
- **Responsibility**: find and (with `--apply`) delete staged intake runs older than N days (default 10) that are direct child directories of `sdd/state/.intake/`. The script is dry-run by default. It refuses a `--root` that doesn't resolve to a path ending in `sdd/state/.intake` inside the repo, and it never follows symlinks, deletes files at the root level, or touches anything outside the root. Deletion uses `shutil.rmtree` on the vetted child path only. `/sdd-status` gains **Step 0 — Prune stale intake staging** that calls it with `--apply` and prints `🧹 Pruned N stale intake run(s) (>10 days): <names>`. The Guardrail line 18 becomes "Read-only — do not modify any files, **except** Step 0's pruning of git-ignored `sdd/state/.intake/` staging (FEAT-577)". The two sdd-status copies stay byte-identical modulo frontmatter, and the codex skill gets the same exception.
- **Depends on**: M1 (reads `intake.json.updated_at`)
- **Interface Skeleton**:
  ```python
  # scripts/sdd/prune_intake.py  (new)
  """``prune_intake.py`` — prune stale /sdd-spec intake staging (FEAT-577)."""
  from __future__ import annotations
  import argparse
  import logging
  from datetime import datetime, timedelta, timezone
  from pathlib import Path
  from pydantic import BaseModel

  DEFAULT_ROOT: Path = Path("sdd/state/.intake")
  DEFAULT_MAX_AGE_DAYS: int = 10

  class StaleIntake(BaseModel):
      """One staged run selected for pruning."""
      path: Path
      age_days: float
      age_source: str  # "updated_at" | "mtime"

  def run_age(run_dir: Path, now: datetime) -> tuple[timedelta, str]:
      """Age from intake.json ``updated_at``; falls back to the dir mtime when missing/unparsable."""

  def find_stale(root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, now: datetime | None = None) -> list[StaleIntake]:
      """Direct child dirs of ``root`` (no symlinks) older than ``max_age_days``. Missing root → []."""

  def prune(root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, *, apply: bool = False, now: datetime | None = None) -> list[StaleIntake]:
      """Return the stale runs; delete them only when ``apply``. Raises ValueError for an unsafe root."""

  def main(argv: list[str] | None = None) -> int:
      """CLI: --root, --older-than-days (default 10), --apply. Prints one line per run; exit 0, or 2 on an unsafe root."""
  ```

### Module 10: `/sdd-brainstorm` accepts a hand-off from intake
- **Path**: `.claude/commands/sdd-brainstorm.md` (modify §1 Parse Input + §3 Interactive Discovery)
- **Responsibility**: when the `--` notes contain `intake: <staging-dir>`, read `<staging-dir>/intake.json` (+ `synthesis.json`). Treat Round 0 and the fixed-batch facts (name, projects, overview, problem, Jira, why) as answered, show them as a carry-in summary, and seed Round 1 with the synthesis `unknowns` and competing hypotheses. The two mandatory rounds still run. Copy the synthesis `localization` into `## Code Context` after re-verifying it. A missing or invalid staging dir prints a warning, and the brainstorm runs normally.
- **Depends on**: M1 (reads the `intake.json` shape), M3 (the procedure emits the pointer)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_intake_schema_is_valid_draft_2020_12` | M1 | `Draft202012Validator.check_schema` passes |
| `test_intake_sample_validates` | M1 | a full sample (all phases' fields populated) validates |
| `test_intake_rejects_bad_feat_id` | M1 | `feat_id: "FEAT-1"` fails; `null` and `"FEAT-123"` pass |
| `test_intake_rejects_unknown_keys` | M1 | an extra top-level or nested key fails (`additionalProperties: false`) |
| `test_intake_rejects_bad_enums` | M1 | a bad `phase` / `research.depth` / `jira.mode` / question `source` fails |
| `test_state_schema_accepts_null_feat_id_and_intake_kind` | M2 | an intake-mode `state.json` sample validates |
| `test_existing_state_files_still_validate` | M2 | every committed `sdd/state/FEAT-*/state.json` validates against the modified schema (skip the file if it didn't validate before the change, and record that in the test docstring) |
| `test_unattended_callers_pass_no_interview` | M6/M7 | every line matching `/sdd-spec` as an invocation in `sdd-research.md` / `sdd-planner.md` (both copies) contains `--no-interview` |
| `test_sdd_spec_points_at_intake_procedure` | M4/M7 | both twins mention `sdd/templates/intake.procedure.md` and the procedure file exists |
| `test_intake_procedure_names_its_schemas` | M3/M7 | the procedure references `intake.schema.json`, `state.schema.json`, `research_plan.prompt.md` and `synthesis.prompt.md`, and each path exists |
| `test_intake_procedure_offers_brainstorm_handoff` | M3/M7 | the procedure names `recommended_next_command`, `sdd-brainstorm` and `handed_off` |
| `test_intake_schema_accepts_handed_off` | M1 | `phase: handed_off` + `research.handoff_declined` validate |
| `test_find_stale_uses_updated_at` | M9 | a run with `updated_at` 11 days ago is stale; one at 9 days is not (fixed `now`) |
| `test_find_stale_falls_back_to_mtime` | M9 | a missing or corrupt `intake.json` falls back to the dir mtime (`os.utime`) |
| `test_prune_dry_run_deletes_nothing` | M9 | without `apply` the dirs survive, and the result lists them |
| `test_prune_apply_deletes_only_stale_children` | M9 | the fresh run, root-level files and symlinked dirs survive `apply=True` |
| `test_prune_rejects_unsafe_root` | M9 | `--root /tmp/x` or `sdd/state` → ValueError / exit 2 |
| `test_prune_missing_root_is_noop` | M9 | a missing root returns `[]`, exit 0 |
| `test_sdd_status_prunes_intake_first` | M9/M7 | both sdd-status copies name `scripts.sdd.prune_intake` and the FEAT-577 read-only exception |
| `test_brainstorm_accepts_intake_pointer` | M10/M7 | `sdd-brainstorm.md` documents the `intake:` pointer and `intake.json` |

### Integration Tests
| Test | Description |
|---|---|
| `tests/sdd_scripts/test_command_twin_parity.py` (existing) | still passes after M4 |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` (existing) | still passes after M6 |
| `tests/sdd_scripts/test_design_research_templates.py` (existing) | still passes (unchanged templates) |
| Manual dry run | `/sdd-spec` with no args on a scratch slug: intake → `--research light` → 2 rounds → spec committed with `sdd/state/<FEAT>/intake/` promoted; then interrupt a second run after research and `--resume` it. Record evidence in `artifacts/logs/`. |

### Test Data / Fixtures
```python
@pytest.fixture
def intake_sample() -> dict:
    """A complete intake.json record at phase 'rounds_complete' with full research."""

@pytest.fixture
def intake_state_sample() -> dict:
    """A state.json for an intake-mode research run: feat_id None, source.kind 'intake'."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `/sdd-spec` with no exploration doc and no `--` notes enters intake mode. `--interview` forces it; `--no-interview` restores today's path (G1).
- [ ] With an exploration doc present, `--interview` prints a warning and the carry-forward path runs (the brainstorm stays authoritative).
- [ ] The fixed batch asks exactly: Round 0 flow/base; feature name/slug; related project(s); overview; problem; Jira (existing | create | none); why it matters. A summary is shown for confirmation before research (G2).
- [ ] `--research` accepts `full|light|none` and defaults to **`full`**. `full` uses the unchanged `/sdd-proposal` prompts/schemas in a subagent, writing `state.json`, `research_plan.json`, `findings/`, `synthesis.json` into the staging dir (G3).
- [ ] The research-plan gate is shown by default in intake mode; `--no-gate` skips it.
- [ ] A research failure under `full` degrades to `light`, is recorded in `intake.json.research`, and never aborts the command.
- [ ] Research runs **between** the fixed batch and the adaptive rounds (G3).
- [ ] Adaptive rounds: at least 2, at most 4; they stop after round 2 when there are no critical gaps; unresolved items land in §8 `[ ]` (G4).
- [ ] Nothing is written under `sdd/state/<FEAT-ID>/` before §5. Staging lives in `sdd/state/.intake/<slug>-<RUN_ID>/` and is git-ignored (G5).
- [ ] The FEAT-ID is reserved in §5 exactly as today (same `existing_feature_id` check and `reserve_ids.py` call).
- [ ] §6 promotes staging to `sdd/state/<FEAT-ID>/intake/`, without overwriting an existing dir, and commits it together with the spec. `intake.json` ends at `phase: committed` with `feat_id` set.
- [ ] `--resume` continues the newest non-committed staged intake for the slug without re-running a completed research phase. `--resume FEAT-<NNN>` is rejected with an explanatory message (G6).
- [ ] §3b runs in intake mode over intake + synthesis, using the intake brief-source mapping. It never includes spec-draft content, and it still skips cleanly without codex (G7).
- [ ] Jira: an existing key is regex-validated and stamped as `**Jira**: [KEY](url)`. "Create" runs `/sdd-tojira` after the spec commit, and a failure there leaves the spec committed and prints the manual command (G8).
- [ ] `projects:` / `tags:` frontmatter is written from the intake when FEAT-576 is available, and falls back to free text in the spec body otherwise (G9).
- [ ] Intake mode never writes a `.brainstorm.md` or `.proposal.md` (G10).
- [ ] `sdd-research` and `sdd-planner` (both copies each) pass `--no-interview`. Both parity tests pass (G11).
- [ ] All tests in §4 pass: `pytest tests/sdd_scripts/ packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v`.
- [ ] `docs/sdd/WORKFLOW.md` documents intake mode.
- [ ] No change to `/sdd-proposal`'s FEAT allocation.
- [ ] When `full` research recommends `sdd-brainstorm`, the user is offered the switch. Accepting it writes no spec, reserves no FEAT-ID, sets `phase: handed_off` and prints the seeded `/sdd-brainstorm` command. Declining it records `handoff_declined: true` and continues (G12).
- [ ] `/sdd-brainstorm <slug> -- intake: <dir>` treats the intake facts as answered, seeds Round 1 from the synthesis, and still runs its 2 mandatory rounds (G12).
- [ ] `/sdd-status` prunes `sdd/state/.intake/` runs older than 10 days and never touches anything outside that directory. `prune_intake.py` is dry-run unless `--apply` is passed (G13).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from scripts.sdd.sdd_meta import resolve_flow, parse, FlowMeta, KNOWN_BRANCHES  # verified: scripts/sdd/sdd_meta.py:10-20 (shim re-export of parrot.knowledge.wiki.ledger.sdd_meta)
from scripts.sdd.reserve_ids import existing_feature_id, reserve_ids           # verified: scripts/sdd/reserve_ids.py:420, :468
from jsonschema import Draft202012Validator, ValidationError                   # verified: tests/sdd_scripts/test_design_research_templates.py:10
```

### Existing Class Signatures
```python
# scripts/sdd/reserve_ids.py
def existing_feature_id(root: Path, label: str) -> tuple[str, str] | None:  # line 420
def reserve_ids(...)                                                         # line 468
# CLI (lines 626-633): --kind {task,feature} --count N --base-branch B --label L [--max-retries 5]

# scripts/sdd/sdd_meta.py → parrot.knowledge.wiki.ledger.sdd_meta
resolve_flow(doc_path: Path | None, type_override: str | None, base_branch_override: str | None) -> FlowMeta
# (call shape verified in .claude/commands/sdd-spec.md:147-155; returns FlowMeta with .type/.base_branch)
```

### Command / template anchors (verified 2026-09-19)
- `.claude/commands/sdd-spec.md` (647 lines): Usage `:6`; §1 Parse Input `:38`; "If neither exists, proceed to §3." `:48`; §2d `:138`; §3b `:210`, preconditions `:218-219`; `DR="sdd/state/.design_research/<feature-name>-${RUN_ID}"` `:246` (id-independent staging, the pattern intake reuses); §3b.2 brief sources `:278ff`; §3 Clarifying Questions `:386`; §4 `:409`; §5 `:446`; §6 `:553`, `git add sdd/specs/<feature-name>.spec.md` `:568`; §7 `:592`; Reference `:633`; **parity anchor** `:637` = ``- Worktree policy: `CLAUDE.md` (section "Worktree Policy")``.
- `.agent/workflows/sdd-spec.md`: the twin. It differs only by frontmatter and the one substitution at the parity anchor.
- `.agents/skills/sdd-spec/SKILL.md` (134 lines): invocation line `:11`; Workflow `:30`; reserve line `:84`.
- `.claude/commands/sdd-proposal.md`: `--budget` table `~:93-97`; Phase 1 plan with `research_plan.prompt.md` `:155`; plan gate `:168`; Phase 2 loop `:198-239`; Phase 3 synthesis `:241-282` (`synthesis.prompt.md` `:254`, lint rules `:262-282`); Phase 5 targeted Q&A `:329`; Step R resume `:428`. Its FEAT allocation at `:79-82` is a `max+1` scan and **is out of scope**.
- `.claude/commands/sdd-tojira.md`: usage `:16-21` (accepts a spec path or `FEAT-<NNN>`); recognises `**Jira**: [NAV-8036](...)` in a spec body `:100`.
- `sdd/templates/state.schema.json` (draft-07): `required` includes `feat_id` `:9`; `feat_id` `:24` = `{"type": "string", "pattern": "^FEAT-[0-9]{3,}$"}`; `feature_slug` `:29`; `source.required = ["kind","raw_path"]` `:44`; `source.kind` enum `["jira","inline","file"]` `:47`; `raw_path` `:51`; `phase` enum = `source_resolved, plan_drafted, plan_approved, research_running, research_complete, synthesis_complete, review_gate, qa_pending, qa_complete, proposal_drafted, committed, failed`; `mode` enum `investigation|enrichment|auto`.
- `sdd/templates/synthesis.prompt.md:188`: the output example carries `"feat_id": "FEAT-156"`. In intake mode the subagent emits `null` (the synthesis lint rules at sdd-proposal `:262-282` do not check `feat_id`).
- `sdd/templates/spec.md`: header fields `Feature ID/Date/Author/Status/Target version` (`:11-15`). There is **no** `**Jira**` field; `/sdd-tojira` adds that line.
- `.gitignore:406-407`: `# FEAT-545: id-independent staging…` / `sdd/state/.design_research/`.
- `sdd/templates/synthesis.prompt.md:158-166` (Step 8): `recommended_next_command.command` is exactly one of `sdd-spec`, `sdd-brainstorm`, `sdd-task`, `manual-review`; `sdd-brainstorm` = "medium confidence OR multiple viable architectural paths". Output shape `:292-295` = `{"command": …, "rationale": …}`.
- `.claude/commands/sdd-status.md` (104 lines): Guardrail `:18` = "- Read-only — do not modify any files."; `## Steps` `:21`; `### 1. Read All Per-Spec Indexes` `:23`. `.agent/workflows/sdd-status.md` is the same body plus a `model: haiku` frontmatter (`:18` identical). `.agents/skills/sdd-status/SKILL.md:18` = "- Read-only: never modifies any files."
- `.claude/commands/sdd-brainstorm.md` (214 lines): the command body the user invokes. There is no `.agent/workflows` parity test for it (`_TWINNED` covers only `sdd-spec`, `sdd-task`).
- `scripts/sdd/check_task_graph.py`: the pattern for a small `scripts/sdd` CLI with `main(argv) -> int`.

### Unattended callers (verified 2026-09-19)
- `.claude/agents/sdd-research.md:75-76` and `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md:75-76`:
  `/sdd-spec <slug> --type hotfix --base-branch main` / `/sdd-spec <slug> --type feature --base-branch dev`. **No `--` notes and no exploration doc, so this line matches the auto-trigger today.**
- `.claude/agents/sdd-planner.md:46` and `_subagent_data/sdd-planner.md:46`: "run ``/sdd-spec`` to scaffold …" (only when a brainstorm/proposal exists, so it would not auto-trigger. The flag is still added for explicitness.)
- `.claude/agents/sdd-autopilot.md` and `sdd-ideation.md` mention `/sdd-spec` only in prose (`:77`, `:151`; `:275-296`). They do not invoke it, so there is no change.
- Byte parity between `.claude/agents/<name>.md` and `_subagent_data/<name>.md` is enforced by `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`.

### Tests to extend / mirror
- `tests/sdd_scripts/test_command_twin_parity.py`: `_TWINNED = ("sdd-spec", "sdd-task")`; `_SUBSTITUTIONS["sdd-spec"]` anchor must occur exactly once.
- `tests/sdd_scripts/test_design_research_templates.py`: the pattern for schema tests (`_REPO_ROOT = Path(__file__).resolve().parents[2]`, `Draft202012Validator`).
- `tests/sdd_scripts/test_command_contracts.py`: the pattern for text-contract tests over command/agent files (`_REPO_ROOT`, parametrized over relative paths).

### Planned by FEAT-576 (NOT implemented at time of writing — dependency)
```python
# parrot.knowledge.wiki.ledger.sdd_meta (per sdd/specs/sdd-spec-changes.spec.md §3; tasks TASK-3459..3468 pending)
KNOWN_PROJECTS: frozenset[str]
def normalize_project(raw: str) -> str: ...
def normalize_tag(raw: str) -> str: ...
def parse_taxonomy(doc_path: Path) -> DocTaxonomy: ...
```
TASK-3465 (FEAT-576) also edits `/sdd-spec` (carrying projects/tags forward), which is the same file pair as M4.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `/sdd-spec` §1.5 | `intake.procedure.md` | prompt reference | new |
| intake research subagent | `/sdd-proposal` Phases 1–3 | follows the command text | `.claude/commands/sdd-proposal.md:141-282` |
| intake hand-off | `resolve_flow(doc_path=None, …)` | python -c in §2d | `.claude/commands/sdd-spec.md:147-155` |
| §6 promotion | design-research promotion pattern | copy → mv → rm, no overwrite | `.claude/commands/sdd-spec.md:569-581` |
| Jira create | `/sdd-tojira <spec-path>` | slash command | `.claude/commands/sdd-tojira.md:16` |

### Does NOT Exist (Anti-Hallucination)
- ~~`/sdd-feature`~~: no such command, and none will be created.
- ~~`--interview`, `--no-interview`, `--resume`, `--research`, `--no-gate`, `--budget` on `/sdd-spec`~~: not present before this feature.
- ~~`sdd/templates/intake.procedure.md`, `sdd/templates/intake.schema.json`~~: created by M3/M1.
- ~~`sdd/state/.intake/`, `sdd/state/<FEAT>/intake/`~~: new conventions.
- ~~A Python `IntakeRecord` model or `scripts/sdd/spec_intake.py`~~: explicitly not built (Option C rejected).
- ~~`KNOWN_PROJECTS` / `normalize_project` / `parse_taxonomy` in `sdd_meta` today~~: FEAT-576, pending.
- ~~A `**Jira**` field in `sdd/templates/spec.md`~~: absent.
- ~~`scripts/sdd/prune_intake.py`~~: created by M9. No existing SDD script deletes staging dirs (`.design_research/` is pruned manually).
- ~~An `intake:` pointer in `/sdd-brainstorm`~~: added by M10.
- ~~`/sdd-proposal` using `reserve_ids.py`~~: it doesn't, and this feature does not change that.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Id-independent staging** exactly like §3b's `sdd/state/.design_research/<slug>-${RUN_ID}` and its collision-safe promotion in §6.
- **Reuse, don't copy**: the research subagent is told to follow `/sdd-proposal` Phases 1–3 and its templates by path. The procedure must not paraphrase those phases, so they cannot drift.
- **Twin discipline**: edit `.claude/commands/sdd-spec.md` first, then copy the body byte-for-byte to `.agent/workflows/sdd-spec.md`, keeping its frontmatter and the one documented substitution. Same for `.claude/agents/*` → `_subagent_data/*` (no substitution; fully identical).
- **Tool-agnostic procedure**: the `.agent`/codex lanes read the same `intake.procedure.md`, so interactive-tool names appear only as examples.
- **Carry-forward wins**: an existing brainstorm/proposal always takes precedence over intake.
- Question batches: one batch per round, each question answerable independently. The same resolved-question convention (`[x] … : answer`) is used when routing answers into §8.

### Known Risks / Gotchas
- **An unattended caller hangs waiting for a human.** `sdd-research` matches the auto-trigger today. Mitigation: M6 adds explicit flags, the procedure has a "cannot ask ⇒ behave as `--no-interview`" rule, and a contract test guards it.
- **Twin drift.** M4 touches a byte-parity-tested pair. Mitigation: keep the §1.5 body short, and run the parity test in the same task.
- **Collision with FEAT-576 TASK-3465** on the same file pair. Mitigation: land FEAT-576 first (see Worktree Strategy).
- **Existing `state.json` files vs a changed schema.** M2 only widens (nullable plus one enum value). The regression test validates every committed file.
- **Long `full` research** (the `default` budget is 300 s wall). Mitigation: the gate shows the plan first, `--budget tight` and `--research light` exist, and it degrades on failure.
- **Stale staging dirs** accumulate in `sdd/state/.intake/`. They are git-ignored and `--resume` picks the newest; cleanup is manual (same as `.design_research/`).
- **An abandoned intake burns no FEAT-ID** (reservation stays in §5). This is why id-less staging was chosen.
- **`synthesis.prompt.md` shows a FEAT example.** The subagent brief must say `feat_id: null` explicitly, or the model may invent an ID.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jsonschema` | already installed | schema tests (Draft 2020-12 for intake; the draft-07 state schema is validated with its declared draft) |
| `codex` CLI | optional | §3b; `agy` is banned for this seat |
| `wikitoolkit` | already installed | wiki-first research queries (budget-free) |

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec. The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1, M2 (the procedure names both schemas; `test_intake_procedure_names_its_schemas` checks the paths exist).
  - M4 → M3 (the twins point at the procedure; `test_sdd_spec_points_at_intake_procedure`).
  - M5 → M3 (the skill points at the procedure).
  - M6 → M4 (`--no-interview` must be a real flag first).
  - M7 → M1, M2, M4, M6 (tests over their outputs). It may be split so each module's tests ship with it.
  - M8 → M3 (docs describe it).
  - M9 → M1 (reads `intake.json.updated_at` per the schema; its tests build samples from it).
  - M10 → M1, M3 (reads the `intake.json` shape; the procedure emits the `intake:` pointer).
  - M1 and M2 have no edge between them and run concurrently.
- **Shared files**: `.claude/commands/sdd-spec.md` + `.agent/workflows/sdd-spec.md` (M4 only). `tests/sdd_scripts/test_command_contracts.py` (M7 only; the M9/M10 contract checks live there too, so they serialize with M7). `sdd/templates/intake.procedure.md` (M3; the hand-off section is part of M3).
- **Exclusive resources**: none (no lockfile, migration or rebuild).
- **Cross-feature dependencies**: **FEAT-576 `sdd-spec-changes` must merge first**. It provides `KNOWN_PROJECTS` / `normalize_*` and its TASK-3465 edits the same `/sdd-spec` twin pair.

---

## 8. Open Questions

- [x] New command or mode? — *Resolved in brainstorm*: a mode of `/sdd-spec`.
- [x] Research depth? — *Resolved in brainstorm*: `--research full|light|none`, default `full`.
- [x] When to create Jira? — *Resolved in brainstorm*: after the spec is written, via `/sdd-tojira`.
- [x] Trigger? — *Resolved in brainstorm*: auto (no exploration doc and no notes), plus `--interview` / `--no-interview`.
- [x] Persist intake? — *Resolved in brainstorm*: committed under `sdd/state/<FEAT-ID>/intake/`.
- [x] Unattended lanes? — *Resolved in brainstorm*: interactive only; unattended callers pass `--no-interview`.
- [x] Relation to FEAT-576? — *Resolved in brainstorm*: depends on it; the intake writes `projects:`/`tags:`.
- [x] Codex §3b in intake mode? — *Resolved in brainstorm*: runs over confirmed intake + research synthesis.
- [x] Adaptive rounds? — *Resolved in brainstorm*: min 2, max 4, gap-driven.
- [x] Research ordering? — *Resolved in brainstorm*: between the fixed intake and the adaptive rounds.
- [x] When is the FEAT-ID reserved in intake mode? — *Resolved in spec Q&A*: stage id-less in `sdd/state/.intake/<slug>-<RUN_ID>/` and reserve in §5 as today; `state.schema.json` relaxes `feat_id` to nullable.
- [x] Inline procedure or shared file? — *Resolved in spec Q&A*: shared `sdd/templates/intake.procedure.md`; the twins carry a short §1.5 pointer.
- [x] `--resume` in v1? — *Resolved in spec Q&A*: yes. Because intake is id-less until §5, it is keyed by slug/staging dir (`--resume [<staging-dir>]`), not by `FEAT-<NNN>`; `--resume FEAT-<NNN>` is rejected with an explanation.
- [x] Research-plan gate and `/sdd-proposal` allocator? — *Resolved in spec Q&A*: the gate is shown by default (`--no-gate` skips it); the allocator fix is left to a separate change.
- [x] Should `sdd/state/.intake/` staging dirs older than N days be pruned automatically, or stay manual like `.design_research/`? — *Resolved in spec review*: prune during `/sdd-status` after 10 days, and keep the dir git-ignored. Landed in G13, §2 "Staging retention", Module 9, §5. This is a documented exception to `/sdd-status`'s read-only guardrail, limited to untracked `sdd/state/.intake/` children.
- [x] Should a synthesis whose `recommended_next_command` suggests a brainstorm offer to switch to `/sdd-brainstorm` instead of writing the spec? — *Resolved in spec review*: yes. Landed in G12, §2 "Brainstorm hand-off", Module 10, §5. It is an offer the user can decline, not an automatic switch.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (exploration doc status is `exploration`, not `accepted`)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-19 | Jesus Lara | Initial draft from `sdd/proposals/sdd-feature-specification.brainstorm.md` (Option A) + spec Q&A |
| 0.2 | 2026-09-19 | Jesus Lara | Approved; last two §8 questions resolved → G12 brainstorm hand-off (M10), G13 intake retention via `/sdd-status` (M9) |
