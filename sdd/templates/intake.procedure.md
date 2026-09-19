# /sdd-spec Intake Procedure (FEAT-577)

> Single source for `/sdd-spec` intake mode. Both `/sdd-spec` twins point here
> from their §1.5. Outputs a confirmed `intake.json` (validated by
> `sdd/templates/intake.schema.json`) and, for `--research full`, a
> `synthesis.json`, then hands back to `/sdd-spec` §2d.

## 0. When this runs

The intake mode is triggered by the following rule (bounded by G1, G11):

```
if --resume:                                 → resume intake (G6)
elif --no-interview:                         → today's path
elif --interview:                            → intake (warn and ignore if an exploration doc exists: carry-forward wins)
elif no exploration doc and no `--` notes:   → intake
else:                                        → today's path
```

- **Resume** (`--resume`): resumes an interrupted intake run from the staging directory.
- **No interview** (`--no-interview`): skips intake and follows today's path (used by unattended agents).
- **Interview** (`--interview`): forces intake mode. If an exploration doc (brainstorm or proposal) already exists, warn the user and let the carry-forward path win.
- **Auto-trigger**: when no exploration doc exists AND no `--` notes were given, intake mode starts automatically.

**Agent fallback**: An agent that cannot ask the user anything (running as a subagent, no interactive question tool) must behave as `--no-interview` even without the flag. This is a defensive fallback on top of G11.

## 1. Staging

Create a staging directory for the intake run:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
# If slug is not yet known, stage under _pending-
STAGE="sdd/state/.intake/<slug>-${RUN_ID}"
# Once slug is confirmed, rename: mv "sdd/state/.intake/_pending-${RUN_ID}" "sdd/state/.intake/<slug>-${RUN_ID}"
mkdir -p "$STAGE"
```

The staging directory is **git-ignored** (add `sdd/state/.intake/` to `.gitignore` if not already present).

Initialize `intake.json` with phase `started`:

```json
{
  "schema_version": "1.0",
  "run_id": "<RUN_ID>",
  "feature_slug": null,
  "feat_id": null,
  "started_at": "<ISO timestamp>",
  "updated_at": "<ISO timestamp>",
  "phase": "started",
  "flow": {"type": "feature", "base_branch": "dev"},
  "research": {
    "depth": "full",
    "gate": true,
    "budget": "default",
    "degraded_from": null,
    "failure_reason": null,
    "synthesis_path": null,
    "handoff_declined": false
  },
  "answers": {
    "feature_name": "",
    "projects": [],
    "tags": [],
    "overview": "",
    "problem": "",
    "why_important": "",
    "jira": {"mode": "none", "key": null}
  },
  "rounds": [],
  "spec_path": null,
  "errors": []
}
```

**Staging retention (G13)**: The staging directory is git-ignored and pruned after 10 days by a daily git hook (installed separately by TASK-3473/TASK-3476). The hook runs on `post-checkout`, `post-merge`, and `post-commit`. `/sdd-status` remains read-only.

## 2. Round 0 + fixed intake batch

Ask one batch of questions to collect the core feature information. Use an interactive question tool when available; otherwise ask in plain text.

**Questions in order:**

1. **Flow type and base branch**: `type: feature | hotfix`, `base_branch: dev | main | staging`
   - Default: `feature` / `dev`
   - If `type: hotfix`, enforce `base_branch: main`

2. **Feature name / slug**: The kebab-case slug for the feature.
   - Validate: does `sdd/specs/<slug>.spec.md` already exist? If yes, abort with a pointer to the existing spec.
   - Validate: does `sdd/proposals/<slug>.brainstorm.md` or `<slug>.proposal.md` exist? If yes, stop intake and fall back to the carry-forward path (the exploration doc wins).

3. **Related project(s)**: Select from `KNOWN_PROJECTS` (FEAT-576) if available. Also allow free text, normalized with `normalize_project`. If FEAT-576 is not importable, use free text as fallback.

4. **Overview**: Free-text description of the feature.

5. **Problem being solved**: What user pain point or gap does this feature address?

6. **Jira**: Choose one of:
   - `existing`: Provide a Jira key (validate with regex `^[A-Z][A-Z0-9]+-\d+$`)
   - `create`: Create a Jira ticket after the spec is committed
   - `none`: No Jira ticket

7. **Why it matters**: Business value or motivation for this feature.

**Confirmation**: After collecting all answers, show a summary and ask the user to confirm or edit:

```
📋 Intake Summary — <feature-name>

Type: <feature|hotfix>  Base: <base_branch>
Project(s): <projects>
Jira: <existing KEY | create | none>

Overview: <overview>

Problem: <problem>

Why it matters: <why_important>

Confirm? [y / edit / abort]
```

- `y`: Proceed to research.
- `edit`: Re-open the specific question(s) the user wants to change.
- `abort`: Mark phase as `failed`, record the reason, and exit.

Update `intake.json`:
- Set `phase` to `intake_confirmed`
- Populate `answers` with the confirmed values
- Set `feature_slug` to the confirmed slug
- Update `flow.type` and `flow.base_branch`
- Update `updated_at`

This step is bounded by G2, G9.

## 3. Research by depth

Run research between the fixed batch and the adaptive rounds, at the depth specified by `--research` (default: `full`).

### 3a. Write source.md

Create `${STAGE}/source.md` with:

```yaml
---
kind: intake
fetched_at: <ISO timestamp>
summary_oneline: <one-line summary from intake answers>
---
```

And the intake answers as body text.

Also create `${STAGE}/state.json` per `sdd/templates/state.schema.json`:
- `feat_id: null` (intake mode keeps it null until §5)
- `source.kind: "intake"`
- `source.raw_path: "sdd/state/.intake/<slug>-<RUN_ID>/source.md"`

### 3b. Full research (depth=full)

Dispatch a research subagent that follows `.claude/commands/sdd-proposal.md` Phases 1–3 verbatim:

1. **Phase 1**: Generate research plan using `sdd/templates/research_plan.prompt.md`. Present the gate to the user unless `--no-gate` is set.
2. **Phase 2**: Execute the plan, writing findings to `findings/F*.md` using `sdd/templates/finding.md`.
3. **Phase 3**: Run synthesis using `sdd/templates/synthesis.prompt.md`, producing `synthesis.json`.

**Critical**: The brief for the research subagent must:
- Set `feat_id: null` (the synthesis should not allocate an ID)
- Instruct it to return only the `synthesis.json` path when done
- Pass the `--budget` flag value (default `default`) to control research depth

**Budget table** (from `.claude/commands/sdd-proposal.md`):

| `--budget` | files_read | grep_calls | git_calls | depth | wall_seconds |
|------------|-----------|-----------|----------:|------:|-------------:|
| `tight`    |         15 |         10 |         5 |     1 |          120 |
| `default`  |         40 |         25 |        10 |     2 |          300 |
| `loose`    |        100 |         60 |        20 |     3 |          900 |

**Failure handling**: If the research subagent fails or times out:
- Degrade to `light` research
- Set `research.degraded_from: "full"`
- Set `research.failure_reason` to the error message
- Continue with the intake (never abort the spec)

Update `intake.json`:
- Set `phase` to `research_running`, then `research_complete` (or `research_degraded`)
- Set `research.synthesis_path` to `"synthesis.json"` when full succeeds
- Update `updated_at`

### 3c. Light research (depth=light)

Run today's §4 scan (codebase contract build) immediately:
- Grep/glob for relevant files based on the intake answers
- Write findings to `findings/F*.md` digests
- No synthesis is produced

### 3d. No research (depth=none)

Skip research entirely. §4 will build the codebase contract later from scratch.

This step is bounded by G3.

## 3b. Brainstorm hand-off offer

This step runs only when:
- `research.depth == "full"` AND
- `synthesis.json.recommended_next_command.command == "sdd-brainstorm"`

Show the rationale from the synthesis and offer the user a choice:

```
🧠 Research recommends `/sdd-brainstorm`

Rationale: <synthesis.recommended_next_command.rationale>

The research found competing architectural approaches that benefit from
exploration before committing to a spec.

Switch to `/sdd-brainstorm` (seeded with this intake), or continue to the spec?

[s] Switch to brainstorm  [c] Continue to spec
```

- **Switch (`s`)**: 
  - Set `intake.json.phase = "handed_off"`
  - Set `research.handoff_declined = false`
  - Stop `/sdd-spec` (no §2d–§6, no FEAT-ID)
  - Print: `Run: /sdd-brainstorm <slug> -- intake: <STAGE>`
  - The staging dir stays in place and is pruned under G13

- **Continue (`c`)**:
  - Set `research.handoff_declined = true`
  - Proceed to adaptive rounds

**Other recommended commands**:
- `manual-review`: Print the rationale as a warning and continue (no switch offered)
- `sdd-spec`, `sdd-task`, `light`, `none`: No offer is made

This step is bounded by G12.

## 4. Adaptive rounds (2–4)

Run 2–4 rounds of targeted Q&A, each collecting 3–5 questions.

**Question sources**:
- **Gap**: Questions about information missing from the intake answers
- **Synthesis**: Questions derived from `synthesis.unknowns` and competing hypotheses (when research was `full`)

**Question format** (recorded in `intake.json.rounds`):

```json
{
  "round": 1,
  "questions": [
    {
      "id": "Q1",
      "question": "<question text>",
      "source": "gap | synthesis",
      "answer": "<user answer> | null"
    }
  ]
}
```

**Stop conditions**:
- After round 2: if no critical gap remains, stop early
- After round 4: any remaining unresolved items go to spec §8 as `[ ]`

**Critical gap definition**: A gap that would materially affect the spec's architectural decisions or acceptance criteria.

Update `intake.json`:
- Append each round to `rounds` array
- Set `phase` to `rounds_complete` when done
- Update `updated_at`

This step is bounded by G4.

## 5. Hand-off to /sdd-spec §2d–§6

Once intake is complete, hand off to the normal `/sdd-spec` pipeline:

### 5a. Resolve flow

Call `resolve_flow(doc_path=None, type_override, base_branch_override)` with the values from Round 0:
- `type_override` = `intake.json.flow.type`
- `base_branch_override` = `intake.json.flow.base_branch`

### 5b. Spec mapping

Map intake data to spec sections:

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

### 5c. §3b in intake mode

The codex design-research pass runs with the extended precondition:
- "exploration doc with status `accepted`" **OR** `intake.json.phase >= rounds_complete`

Brief sources in intake mode:
- `problem_statement.txt` ← intake problem + why it matters
- `constraints_and_goals.txt` ← synthesis `constraints` (or "none")
- `recommended_option_or_scope.txt` ← intake overview + answered adaptive questions
- `code_context_paths.txt` ← synthesis `localization[].path` (or `light` findings' paths)
- `open_questions.txt` ← unresolved items

Forbidden-content rule unchanged: nothing from the spec draft goes in.

### 5d. §4 seeded by synthesis

The codebase contract build is seeded by:
- `synthesis.localization[].path` for code context
- `synthesis.constraints` for known constraints
- Re-verify all paths in §4

### 5e. §5 reserve FEAT-ID

Reserve the FEAT-ID as usual via `scripts/sdd/reserve_ids.py`. Write the reserved ID to `intake.json.feat_id`.

### 5f. §6 promote and commit

Promote the staging directory:
```bash
# Create the final directory
mkdir -p "sdd/state/<FEAT-ID>/intake"
# Move (not copy) contents
mv "sdd/state/.intake/<slug>-<RUN_ID>"/* "sdd/state/<FEAT-ID>/intake/"
# Remove now-empty staging dir
rmdir "sdd/state/.intake/<slug>-<RUN_ID>" 2>/dev/null || true
```

**No overwrite**: If `sdd/state/<FEAT-ID>/intake/` already exists, abort with an error.

Set `intake.json.phase = "committed"` and commit the spec along with the intake directory.

This step is bounded by G5, G7.

## 6. Jira

After the spec is committed (§6):

- **Existing key**: Stamp `**Jira**: [KEY](<instance>/browse/KEY)` in the spec header.
- **Create**: Run `/sdd-tojira sdd/specs/<slug>.spec.md`. It commits its own stamp. On failure, report the error and print the manual command. The spec stays committed.
- **None**: Do nothing.

This step is bounded by G8.

## 7. Resume

Resume an interrupted intake run:

```bash
/sdd-spec <slug> --resume
# or
/sdd-spec --resume <staging-dir>
```

**Selection logic**:
1. Find the newest `sdd/state/.intake/<slug>-*/intake.json` for the given slug
2. Filter to those where `phase` is NOT `committed` and NOT `handed_off`
3. If no staging dir is given, use the newest matching one

**Validation**:
- Validate `intake.json` against `sdd/templates/intake.schema.json`
- If invalid, report the error and offer to start fresh

**Resume point**:
- Continue from the first incomplete phase
- If `phase == "research_complete"` or `"research_degraded"`, do NOT re-run research
- If `phase == "research_running"`, resume with `/sdd-proposal` Step R semantics against the staged `state.json`
- If `phase == "rounds_complete"` or later, continue from there

**No resume found**: Report "nothing to resume for this slug" and suggest `--interview`.

**FEAT-ID resume**: Reject `--resume FEAT-<NNN>` with a message explaining that intake has no FEAT-ID until §5.

**Pruned runs**: If the staging directory was pruned (older than 10 days), it's gone — the user must start fresh with `--interview`.

This step is bounded by G6, G13.

## 8. Failure handling

- **Research failures**: Never abort the spec. Degrade gracefully (full → light → none) and continue.
- **Invalid intake.json on resume**: Report the validation error and offer to start fresh.
- **Unrecoverable errors**: Set `phase = "failed"` and populate `errors[]` with descriptive messages.

This step is bounded by spec §2 and §7 Known Risks.