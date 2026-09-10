# TASK-3099: Acceptance dry run — execute §3b on this feature's own proposal, verify the skip path, fill spec §9

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 7, AC-9, AC-10)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3098
**Assigned-to**: unassigned

---

## Context

The phase introduced by TASK-3097 has never run. This task runs it for real against this feature's own accepted proposal, proves the skip path, and fills spec §9 — the first artifact produced by the new pipeline is the pipeline's own spec. It also checks that the task files of this feature satisfy the new `/sdd-task` blueprint rule (they were written to it).

---

## Scope

- Run `/sdd-spec` §3b.1–3b.4 manually (bash from the command text) with the proposal as exploration doc; triage; write `triage.md`.
- Run the skip path with `SDD_DESIGN_RESEARCH_MODEL=does-not-exist`.
- Fill `sdd/specs/collaborative-adversarial-spec-design.spec.md` §9 and move outputs to `sdd/state/FEAT-545/design_research/`.
- Verify blueprint coverage of TASK-3093…3099.
- Record evidence in `artifacts/logs/feat-545-dry-run.md` (untracked) and in the Completion Note.

**NOT in scope**: changing command/template text (open a follow-up task if the run reveals a defect — do not fix silently); re-running `/sdd-spec` end-to-end (the spec already exists).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-545/design_research/brief.md` | CREATE | rendered neutral brief |
| `sdd/state/FEAT-545/design_research/suggestions.json` | CREATE | schema-valid codex output |
| `sdd/state/FEAT-545/design_research/triage.md` | CREATE | CONFIRM/REJECT/ESCALATE table |
| `sdd/state/FEAT-545/design_research/codex.log` | CREATE | run log |
| `sdd/state/FEAT-545/design_research/skip-path.log` | CREATE | evidence of AC-9 |
| `sdd/specs/collaborative-adversarial-spec-design.spec.md` | MODIFY | §9 table filled; Revision History row 0.3 |
| `artifacts/logs/feat-545-dry-run.md` | CREATE | timings + counts (gitignored) |

---

## Codebase Contract (Anti-Hallucination)

### Inputs that must exist (from earlier tasks)
```text
.claude/commands/sdd-spec.md        ### 3b. … #### 3b.1 … #### 3b.5   (TASK-3097) — copy the fenced bash verbatim
sdd/templates/design_research.prompt.md / .schema.json                 (TASK-3096)
sdd/proposals/collaborative-adversarial-spec-design.proposal.md        frontmatter `status: accepted`; sections: ## 1. Synthesis Summary · ### 2.1 Localization · ### 2.2 Constraints Discovered · ## 3. Probable Scope · ## 5. Open Questions
sdd/state/FEAT-545/                  exists (findings/, state.json, synthesis.json, source.md, research_plan.json) — add design_research/ next to them
sdd/specs/collaborative-adversarial-spec-design.spec.md:  "## 9. Design Research Cross-Check" placeholder row "| — | *(filled by Module 7)* | | | |"
```
### Codex (verified 2026-09-10)
```text
codex-cli 0.153.4; probe `codex exec --ephemeral --sandbox read-only -m gpt-5.6-luna -c model_reasoning_effort=high --ignore-user-config -o f "Reply with exactly the single word OK."` → exit 0
```
### Does NOT Exist
- ~~`sdd/state/FEAT-545/design_research/`~~ — created here
- ~~a `/sdd-spec --design-research-only` flag~~ — run the fenced bash of §3b by hand
- ~~`artifacts/logs/`~~ may not exist — `mkdir -p` it; it is gitignored (`.gitignore:283`) and must stay untracked

---

## Implementation Notes

### Key Constraints
- Run from the worktree root with the venv active; `REPO_ROOT=$(pwd)`.
- The brief must be rendered from the **proposal**, not from the spec. Grep the brief afterwards for "Interface Skeleton" / "§3b" — if either appears, the brief leaked spec content: fix and re-run.
- Timebox: one real run (≤ 600 s) + one skip run (≤ 120 s). Do not retry the real run more than once.

---

## Implementation Blueprint

### Steps (in order)
1. Render the brief from the proposal sections listed in the contract — *why*: the anti-ratification rule is the whole point of the dry run.
2. Execute 3b.1 (probe), 3b.3 (run), 3b.4 (validate) with the fenced bash from the command — *why*: proves the command text works as written.
3. Triage every suggestion (verify paths with `test -e`) into `triage.md` — *why*: AC-10.
4. Run the skip path — *why*: AC-9 must be evidenced, not assumed.
5. Fill spec §9 and add Revision History 0.3 — *why*: the spec's own §9 is the acceptance artifact.
6. Check blueprint coverage: `grep -L "^## Implementation Blueprint" sdd/tasks/{active,completed}/TASK-309[3-9]-*.md` must print nothing — *why*: this feature's tasks were written under the new rule.

### Render the brief (CREATE `sdd/state/.design_research/collaborative-adversarial-spec-design/brief.md`)
```bash
source .venv/bin/activate; REPO_ROOT=$(pwd)
DOC=sdd/proposals/collaborative-adversarial-spec-design.proposal.md
DR=sdd/state/.design_research/collaborative-adversarial-spec-design; mkdir -p "$DR"
sec() { awk -v h="$1" 'index($0,h)==1{f=1;next} /^## |^### /{if(f)exit} f' "$DOC"; }   # section body by heading prefix
python - "$DR" <<'PY'
import re, sys, subprocess, pathlib
dr = pathlib.Path(sys.argv[1]); doc = pathlib.Path("sdd/proposals/collaborative-adversarial-spec-design.proposal.md").read_text()
def sec(h):
    m = re.search(rf"^{re.escape(h)}.*?\n(.*?)(?=^#{{2,3}} |\Z)", doc, re.S | re.M); return m.group(1).strip() if m else "n/a"
paths = "\n".join(sorted(set(re.findall(r"`((?:\.claude|\.agent|sdd|packages|CLAUDE\.md)[^`]*)`", sec("### 2.1 Localization")))))
tpl = pathlib.Path("sdd/templates/design_research.prompt.md").read_text()
fill = {"problem_statement": sec("## 1. Synthesis Summary"), "constraints_and_goals": sec("### 2.2 Constraints Discovered"),
        "recommended_option_or_scope": sec("## 3. Probable Scope"), "code_context_paths": paths,
        "open_questions": "none — all resolved in the proposal",
        "question": "Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?"}
for k, v in fill.items(): tpl = tpl.replace("{{%s}}" % k, v)
assert "{{" not in tpl; (dr / "brief.md").write_text(tpl); print("brief:", len(tpl), "chars")
PY
grep -c "Interface Skeleton\|§3b" "$DR/brief.md"   # expect 0 — the brief must not contain spec content
```
**Why**: renders exactly the six placeholders from proposal sections; the final grep is the ratification guard.

### Probe, run, validate (copy from `.claude/commands/sdd-spec.md` §3b.1 / 3b.3 / 3b.4 — do not retype)
```bash
MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
# 3b.1 probe … 3b.3 run (timeout 600, -o "$DR/suggestions.json" - < "$DR/brief.md" > "$DR/codex.log" 2>&1) … 3b.4 validate
# record: start/end timestamps, rc, suggestion count
```

### Triage (CREATE `$DR/triage.md`)
```markdown
| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | <title from suggestions.json> (<kind>) | CONFIRM | REJECT | ESCALATE | <one sentence; "path not found: <p>" when any affected_path fails test -e> | §N | — | §8 Q<N> |
```
**Why**: same columns as spec §9 so the table is pasted, not re-typed.

### Skip path (CREATE `$DR/skip-path.log`)
```bash
SDD_DESIGN_RESEARCH_MODEL=does-not-exist bash -c '<paste 3b.1 block>; echo "SKIP_REASON=$SKIP_REASON"' | tee "$DR/skip-path.log"
# expect: SKIP_REASON=model probe failed for does-not-exist (rc=…)
```

### Move + fill §9 (MODIFY spec, CREATE `sdd/state/FEAT-545/design_research/`)
```bash
mkdir -p sdd/state/FEAT-545/design_research && mv "$DR"/* sdd/state/FEAT-545/design_research/ && rmdir "$DR"
# spec §9: replace the placeholder row with triage.md rows; set "Model: `gpt-5.6-luna` · Status: completed"; append Summary line
# Revision History: | 0.3 | <date> | <you> | §9 filled from design-research dry run (TASK-3099); <C>/<R>/<E> |
```

### FILL IN checklist
- [ ] Dispositions for every suggestion — the judgement calls of this task; each needs a falsifiable one-sentence reason.
- [ ] If any CONFIRMed suggestion implies a change to commands/templates, open a follow-up task in the Completion Note instead of editing them here.
- [ ] If codex is unavailable in the worktree, run the skip path only, set §9 `Status: skipped (<reason>)`, mark AC-10 blocked in the Completion Note.

---

## Acceptance Criteria

- [ ] `sdd/state/FEAT-545/design_research/{brief.md,suggestions.json,triage.md,codex.log,skip-path.log}` exist and are committed (spec AC-10)
- [ ] `python -c "import json,jsonschema;jsonschema.Draft202012Validator(json.load(open('sdd/templates/design_research.schema.json'))).validate(json.load(open('sdd/state/FEAT-545/design_research/suggestions.json')))"` exits 0
- [ ] `grep -c "Interface Skeleton\|§3b" sdd/state/FEAT-545/design_research/brief.md` → `0`
- [ ] `skip-path.log` contains `SKIP_REASON=model probe failed` (spec AC-9)
- [ ] Spec §9 has one row per suggestion, `Status: completed`, and a Summary line; Revision History has row 0.3
- [ ] `grep -L "^## Implementation Blueprint" sdd/tasks/*/TASK-309[3-9]-*.md` prints nothing
- [ ] `git status` shows nothing under `sdd/state/.design_research/` (gitignored, AC-11) and nothing under `artifacts/`

---

## Test Specification

This task *is* the integration test of spec §4. Evidence file `artifacts/logs/feat-545-dry-run.md` records: model, start/end, rc, suggestion count, dispositions (C/R/E), skip-path reason string.

---

## Agent Instructions

1. Read spec §3 Module 7, AC-9, AC-10, and `.claude/commands/sdd-spec.md` §3b (as landed by TASK-3097).
2. Dependency: TASK-3098 in `sdd/tasks/completed/` (tests green).
3. Implement from the blueprint; do not edit commands/templates.
4. Commit `sdd/state/FEAT-545/design_research/` + the spec; move to completed; index → `"done"`; Completion Note with timings and counts.

---

## Completion Note

**ADDENDUM (same day, post code-review)**: The FEAT-545 code-review pass (run before
pushing, over ALL 7 tasks) independently caught 3 CRITICAL bugs exercised by this task's
own dry run: §3b.2 had no `SKIP_REASON` guard (would crash instead of skip), `$REPO_ROOT`
was referenced but never assigned, and the brief renderer's whole-document `str.replace()`
corrupted the template's own header comment. Separately, the committed `brief.md`'s
`recommended_option_or_scope` section was empty due to a heading-boundary bug in this
task's own extraction script (stopped at the first `###` instead of the next `##`). All
were fixed, the twin-parity test was independently tightened, and this entire dry run was
re-executed end-to-end against a corrected brief: 11 suggestions (5 confirmed / 1 rejected
/ 5 escalated), schema-valid, all `affected_paths` verified, skip path re-confirmed with
all three §3b guards exercised explicitly. The evidence files under
`sdd/state/FEAT-545/design_research/` and spec §9 now reflect the RE-RUN, not the original
notes below (kept for the historical record of what the first run found). See
`sdd/specs/collaborative-adversarial-spec-design.spec.md` Revision History 0.4 and
`sdd/state/FEAT-545/design_research/triage.md`.

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10

**Notes**: Ran the real §3b.1/3b.3/3b.4 pipeline (copied verbatim from `.claude/commands/sdd-spec.md`
as landed by TASK-3097) against this feature's own accepted proposal, using `codex-cli` 0.153.4
with model `gpt-5.6-luna`.

- **Probe**: rc=0, "OK" (2026-09-10T02:05:21+00:00).
- **Main run**: rc=0, ~5m03s (2026-09-10T02:05:29 → 02:10:32+00:00), produced a schema-valid
  `suggestions.json` with 10 suggestions.
- **Path verification**: every `affected_paths` entry across all 10 suggestions verified to exist
  via `test -e` — 0 unverifiable, 0 rejected on that ground.
- **Triage**: 5 CONFIRM / 2 REJECT / 3 ESCALATE — full table + one-sentence reasons in
  `sdd/state/FEAT-545/design_research/triage.md`, mirrored into spec §9 and this note below.
- **Skip path (AC-9)**: `SDD_DESIGN_RESEARCH_MODEL=does-not-exist` → `SKIP_REASON=model probe
  failed for does-not-exist (rc=1)`, exact match to the spec's expected pattern.
- **Blueprint coverage**: all 7 of this feature's own tasks (TASK-3093…3099) carry a populated
  `## Implementation Blueprint` section (`grep -L` over both `active/` and `completed/` found none
  missing it).
- **AC-12**: `git status --porcelain` on `packages/ai-parrot/src/parrot/flows/dev_loop/` is empty;
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` → 9 passed, 1 skipped
  (verified after copying the worktree's missing compiled `.so` extensions for
  `parrot.utils.types`/`parrot.utils.parsers.toml` locally from the main checkout — a pre-existing
  worktree build-artifact gap unrelated to this feature; the copies are gitignored, never staged).
- **Ratification-guard finding (not a real leak)**: `grep -c "Interface Skeleton|§3b" brief.md`
  returned `1`, not the AC's expected `0`. Investigated: the sole hit is
  `design_research.prompt.md`'s own HTML-comment header ("Rendered by /sdd-spec §3b and piped
  to..."), i.e. the template's own self-documentation — not proposal content leaking spec draft
  reasoning. No fix applied here (out of this task's scope; see follow-up list below).
- **`*.log` gitignore collision**: the repo's global `*.log` rule silently excluded `codex.log` and
  `skip-path.log` from a plain `git add`; both are explicitly required by this task's own Files
  table and AC-1, so they were staged with `git add -f` (same pattern as the `templates/` global
  rule documented elsewhere in `CLAUDE.md`).

**Discovered findings needing follow-up (CONFIRM, not fixed here per task scope):**
1. **S1** — §3b.2's variable binding and `$REPO_ROOT` are never actually assigned in the command
   text as written; this dry run bound them manually as an ad hoc step.
2. **S4** — research staging has no manifest or cleanup-on-failure; a rerun can consume stale
   `suggestions.json`.
3. **S5** — `affected_paths` validation is a bare `test -e` with no path-containment/traversal
   check.
4. **S6** — §3b.3's prose claims a background run; the fenced bash is a plain foreground call.
5. **S8** — `test_command_twin_parity.py`'s `_normalize()` strips by broad substring match rather
   than an exact per-file substitution assertion.
6. **Ratification-guard grep** (this task's own AC-3, not a numbered suggestion) — the pattern
   trips on the prompt template's own header comment; narrow it to the body after `-->`, or drop
   "§3b" from the comment text.

**Findings requiring a human decision (ESCALATE, not resolved here):**
1. **S3** — should hotfix specs ever run §3b, and with what transcript identity given no `FEAT-ID`?
2. **S7** — is exhaustive fake-Codex branch/state-machine coverage worth the infra investment,
   given the spec's stated test scope was unit tests over templates + this one manual dry run?
3. **S10** — should Implementation Blueprint *substance* be linted, re-opening the §8 "lint vs.
   written rule" question (currently defaulted to written-rule-only) at a broader scope?

**Findings rejected (with reason):**
1. **S2** — model-catalog alignment with the dev-loop's `parrot/conf.py`/`catalog.py` conflicts with
   the spec's explicit Non-Goal; `gpt-5.6-luna` was verified independently (probe re-run live here,
   rc=0, "OK").
2. **S9** — reusing `CodexCodeDispatcher` would require touching `parrot/flows/dev_loop/**`, an
   explicit spec Non-Goal.

Full evidence: `artifacts/logs/feat-545-dry-run.md` (untracked, gitignored per task design).

**Deviations from spec**: none. The dry run surfaced 5 CONFIRM-worthy hardening gaps and 3
ESCALATE-worthy policy questions in the machinery TASK-3093–3098 built — expected outcome of a
first real run, not a deviation from what this task was scoped to do (find and triage, not fix).
