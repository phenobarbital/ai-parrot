# TASK-3470: Intake procedure — the single source for `/sdd-spec` intake mode

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3469
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3**. The whole intake flow lives in one shared,
tool-agnostic file, `sdd/templates/intake.procedure.md`. The two `/sdd-spec`
twins only point at it (TASK-3471), which keeps the byte-parity-tested twins
small. It covers spec §2 Overview end to end: trigger rule, staging, Round 0 +
fixed batch, research by depth, the G12 brainstorm hand-off, adaptive rounds,
hand-off to `/sdd-spec` §2d–§6, Jira, resume, and failure handling.

---

## Scope

- Write `sdd/templates/intake.procedure.md` with the section skeleton below,
  filled from spec §2 (Overview, Brainstorm hand-off, Staging retention, Spec
  mapping, §3b in intake mode, Resume) and G1–G13.
- Write `tests/sdd_scripts/test_intake_procedure.py`
  (`test_intake_procedure_names_its_schemas`,
  `test_intake_procedure_offers_brainstorm_handoff`).

**NOT in scope**: editing `/sdd-spec` (TASK-3471), `/sdd-brainstorm` (TASK-3474),
`/sdd-status` or the pruning script (TASK-3473), and the WORKFLOW doc (TASK-3475).
Do **not** paraphrase `/sdd-proposal` Phases 1–3. Reference them by path and
section (spec §7 "Reuse, don't copy").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/intake.procedure.md` | CREATE | the full intake procedure |
| `tests/sdd_scripts/test_intake_procedure.py` | CREATE | text-contract tests for the procedure |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path  # stdlib
import pytest              # test deps
```

### Existing Signatures / Anchors to Reference (by path, verbatim)
- `sdd/templates/intake.schema.json` — created by TASK-3469 (phases incl. `handed_off`; `research.handoff_declined`).
- `sdd/templates/state.schema.json` — `feat_id` nullable, `source.kind` `intake` (TASK-3469).
- `.claude/commands/sdd-proposal.md` — `--budget` table `~:93-97`; Phase 1 plan `:141`/`:155` (`sdd/templates/research_plan.prompt.md`), gate `:168`; Phase 2 loop `:198-239`; Phase 3 synthesis `:241-282` (`sdd/templates/synthesis.prompt.md` `:254`, lint `:262-282`); Step R resume `:428`.
- `sdd/templates/finding.md` — finding digest format.
- `sdd/templates/synthesis.prompt.md:158-166` — `recommended_next_command.command` ∈ {`sdd-spec`, `sdd-brainstorm`, `sdd-task`, `manual-review`}; output shape `:292-295` `{"command", "rationale"}`; its example at `:188` carries `"feat_id": "FEAT-156"` → the brief must demand `feat_id: null`.
- `.claude/commands/sdd-spec.md` — §2d `resolve_flow(doc_path=None, type_override, base_branch_override)` `:147-156`; §3b.2 brief files `:278-290` (`problem_statement.txt`, `constraints_and_goals.txt`, `recommended_option_or_scope.txt`, `code_context_paths.txt`, `open_questions.txt`, `question.txt`); §6 design-research promotion pattern `:569-581`.
- `.claude/commands/sdd-tojira.md:16` — `/sdd-tojira <spec-path>`; `:100` recognises `**Jira**: [KEY](...)`.
- FEAT-576 (pending at time of writing): `KNOWN_PROJECTS`, `normalize_project`, `normalize_tag` in `parrot.knowledge.wiki.ledger.sdd_meta` — reference with the soft fallback (free text) when not importable.

### Does NOT Exist
- ~~`/sdd-feature`~~ — no such command.
- ~~`--resume FEAT-<NNN>` for intake~~ — rejected by design; resume is keyed by slug/staging dir.
- ~~`/sdd-proposal` using `reserve_ids.py`~~ — it doesn't; irrelevant here since intake reserves nothing.
- ~~`scripts/sdd/spec_intake.py`~~ — no Python engine.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/templates/intake.procedure.md", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_intake_procedure.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Tool-agnostic**: "use your interactive question tool (e.g. `AskUserQuestion`)
  when available; otherwise ask in plain text". Codex (`.agents/skills`) and
  `.agent/workflows` lanes read this same file.
- **Cannot ask ⇒ `--no-interview`**: an agent without a way to reach the user
  must never enter intake (spec §2 trigger rule, G11).
- **Phase bookkeeping**: every phase transition updates `intake.json.phase`
  and `updated_at`, and the file must validate against `intake.schema.json`
  after each write.
- **Order is fixed**: Round 0 + fixed batch → confirm → research → hand-off offer
  (only if `full` and the synthesis recommends `sdd-brainstorm`) → adaptive
  rounds (2–4) → `/sdd-spec` §2d.
- **Staging**: `sdd/state/.intake/<slug>-<RUN_ID>/`, or `_pending-<RUN_ID>`
  renamed once the slug is confirmed. Never write under `sdd/state/<FEAT-ID>/`
  before §5.
- Retention: state that staging is git-ignored and pruned after 10 days by
  `/sdd-status` (G13). That behavior itself is TASK-3473's.

---

## Implementation Blueprint

### Steps (in order)
1. Create the file with exactly the section skeleton below. *Why*: TASK-3471's
   §1.5 and the tests reference these section numbers.
2. Fill each section from the spec passages named in its `FILL IN`. *Why*: the
   spec is authoritative, and the procedure must not invent behavior.
3. Write the two tests. *Why*: they stop the procedure silently dropping its
   schemas, prompts or the hand-off.

### `sdd/templates/intake.procedure.md` (CREATE)
```markdown
# /sdd-spec Intake Procedure (FEAT-577)

> Single source for `/sdd-spec` intake mode. Both `/sdd-spec` twins point here
> from their §1.5. Outputs a confirmed `intake.json` (validated by
> `sdd/templates/intake.schema.json`) and, for `--research full`, a
> `synthesis.json`, then hands back to `/sdd-spec` §2d.

## 0. When this runs
<!-- FILL IN: restate the spec §2 trigger rule verbatim (resume / no-interview / interview / auto / else),
     the "--interview with an exploration doc ⇒ warn, carry-forward wins" rule, and
     "an agent that cannot ask the user behaves as --no-interview" — bounded by G1, G11 -->

## 1. Staging
<!-- FILL IN: RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; STAGE=sdd/state/.intake/<slug>-${RUN_ID} (or _pending-${RUN_ID});
     initial intake.json (phase started); git-ignored; pruned after 10 days by /sdd-status — bounded by G5, G13 -->

## 2. Round 0 + fixed intake batch
<!-- FILL IN: one batch — flow type/base branch; feature name/slug; related project(s) (KNOWN_PROJECTS choices +
     free text via normalize_project; free-text fallback when FEAT-576 is not importable); overview; problem;
     Jira existing|create|none (key regex ^[A-Z][A-Z0-9]+-\d+$); why it matters. Slug checks: spec exists ⇒ abort
     with pointer; exploration doc exists ⇒ stop intake, carry-forward path. Show summary, confirm/edit.
     phase → intake_confirmed — bounded by G2, G9 -->

## 3. Research by depth
<!-- FILL IN: write source.md (kind intake) + state.json (feat_id null). full: dispatch a research subagent that
     follows .claude/commands/sdd-proposal.md Phases 1–3 (plan gate unless --no-gate; --budget default "default")
     using sdd/templates/research_plan.prompt.md, finding.md, synthesis.prompt.md, writing into $STAGE; the brief
     says feat_id MUST be null and to return only the synthesis.json path. light: today's §4 scan now, findings as
     findings/F*.md, no synthesis. none: skip (§4 still builds the contract). full failure/timeout ⇒ degrade to
     light, research.degraded_from=full, failure_reason; never abort — bounded by G3 -->

## 3b. Brainstorm hand-off offer
<!-- FILL IN: only when depth=full and synthesis.json recommended_next_command.command == "sdd-brainstorm":
     show rationale, offer switch|continue. Switch ⇒ phase handed_off, stop /sdd-spec (no §2d–§6, no FEAT-ID),
     print `/sdd-brainstorm <slug> -- intake: <STAGE>`. Continue ⇒ research.handoff_declined=true.
     manual-review ⇒ warn and continue; other values / light / none ⇒ no offer — bounded by G12 -->

## 4. Adaptive rounds (2–4)
<!-- FILL IN: 3–5 questions per round from intake gaps + synthesis unknowns/competing hypotheses, each recorded
     with source gap|synthesis; stop after round 2 if no critical gap; after round 4 the rest → spec §8 [ ].
     phase → rounds_complete — bounded by G4 -->

## 5. Hand-off to /sdd-spec §2d–§6
<!-- FILL IN: resolve_flow(doc_path=None, Round 0 overrides); spec mapping table (spec §2 "Spec mapping from
     intake"); §3b intake brief sources (spec §2 "§3b in intake mode"), forbidden-content rule unchanged;
     §4 seeded by synthesis localization/constraints (re-verify); §5 reserves FEAT-ID unchanged → write
     intake.json.feat_id; §6 promotes $STAGE → sdd/state/<FEAT-ID>/intake/ (no overwrite), phase committed — bounded by G5, G7 -->

## 6. Jira
<!-- FILL IN: existing ⇒ stamp `**Jira**: [KEY](<instance>/browse/KEY)` in the spec header; create ⇒ after §6
     run `/sdd-tojira sdd/specs/<slug>.spec.md` (it commits its own stamp); failure ⇒ report + manual command,
     spec stays committed; none ⇒ nothing — bounded by G8 -->

## 7. Resume
<!-- FILL IN: `/sdd-spec <slug> --resume` or `--resume <staging-dir>`: newest non-committed, non-handed_off
     $STAGE for the slug; validate intake.json; continue at first incomplete phase; research_complete is never
     re-run; research_running resumes with /sdd-proposal Step R semantics on the staged state.json; nothing to
     resume ⇒ say so, suggest --interview; `--resume FEAT-<NNN>` ⇒ reject with explanation; pruned runs are gone — bounded by G6, G13 -->

## 8. Failure handling
<!-- FILL IN: research failures never abort the spec; invalid intake.json on resume ⇒ report + start fresh;
     phase failed + errors[] for anything unrecoverable — bounded by spec §2, §7 Known Risks -->
```
**Why this shape**: one section per spec §2 phase, so TASK-3471's §1.5 can say
"follow §0–§8". Replace every `<!-- FILL IN -->` comment with real prose/bash.
No comment may remain.

### `tests/sdd_scripts/test_intake_procedure.py` (CREATE)
```python
"""Text contract for sdd/templates/intake.procedure.md (FEAT-577, spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROCEDURE = _REPO_ROOT / "sdd" / "templates" / "intake.procedure.md"
_REFERENCED = (
    "sdd/templates/intake.schema.json",
    "sdd/templates/state.schema.json",
    "sdd/templates/research_plan.prompt.md",
    "sdd/templates/synthesis.prompt.md",
)


@pytest.fixture
def procedure() -> str:
    return _PROCEDURE.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _REFERENCED)
def test_intake_procedure_names_its_schemas(procedure: str, rel: str) -> None:
    """The procedure references each schema/prompt by path, and the path exists."""
    assert rel in procedure
    assert (_REPO_ROOT / rel).is_file()


def test_intake_procedure_offers_brainstorm_handoff(procedure: str) -> None:
    for needle in ("recommended_next_command", "sdd-brainstorm", "handed_off"):
        assert needle in procedure


# FILL IN: test_intake_procedure_has_no_unfilled_markers — assert "FILL IN" not in procedure — bounded by AC-3
```

### FILL IN checklist
- [ ] §0–§8 of the procedure, each from its named spec passage
- [ ] `test_intake_procedure_has_no_unfilled_markers`

---

## Acceptance Criteria

- [ ] `sdd/templates/intake.procedure.md` covers spec §2 end to end (G1–G13 behavior that belongs to intake)
- [ ] It references `/sdd-proposal` Phases 1–3 by path/section and does not paraphrase them
- [ ] It contains no `FILL IN` marker
- [ ] `pytest tests/sdd_scripts/test_intake_procedure.py -q` passes

---

## Validation Commands

- `pytest tests/sdd_scripts/test_intake_procedure.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 fully (Overview → Resume) and G1–G13.
2. Confirm TASK-3469 is done (`intake.schema.json` exists).
3. Implement; run the Validation Commands.
4. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*
