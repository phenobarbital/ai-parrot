# TASK-5011: Spec template + /sdd-spec and /sdd-task entry points (M10a)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (documents part) and AC15/AC19. The audit only matters if the SDD authoring lane
calls it. This task wires the three new spec sections into the template and adds:

- to the three `/sdd-spec` entry points (Claude command, Antigravity workflow, Codex skill): a
  **retrieve** step (`wikitoolkit spec governing`) before scaffolding, and a **consequence gate** step
  (`python -m scripts.sdd.check_spec_consequences <spec> --render`, then the read-only check) before
  committing; `**Status**: approved` is refused on a non-zero exit or stale/missing sections, never on
  `skipped`;
- to the three `/sdd-task` entry points: one **advisory** step
  (`python -m scripts.sdd.check_spec_consequences <spec> --advisory`) after reading the spec — silent when
  there is no report, a warning when contrary, never a refusal (owner Q3).

Command names, flags and section headings are frozen by the spec (§3 M9/M10), so this task has no code
dependency and can run in parallel with everything else.

---

## Scope

- `sdd/templates/spec.md`: insert `## Governing Decisions` (generated) above `## 2. Architectural Design`;
  insert `## Decisions`, `## Decision Waivers` (authored, optional) and `## Consequences` (generated)
  above `## 8. Open Questions` (i.e. after §7), in that order. Each block ends with a `---` separator to
  match the template's section rhythm.
- `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md`: insert the **identical** text
  `### 4b. Retrieve Governing Decisions` above `### 5. Scaffold the Spec` and
  `### 5b. Consequence Gate` above `### 6. Commit the Spec`.
- `.agents/skills/sdd-spec/SKILL.md`: insert `9b.` above `10. Write the spec:` and `10b.` above `11. Commit:`.
- `.claude/commands/sdd-task.md` and `.agent/workflows/sdd-task.md`: insert the **identical**
  `### 2b. Advisory Decision-Audit Check` above `### 3. Plan Task Decomposition`.
- `.agents/skills/sdd-task/SKILL.md`: insert `4b.` above `5. Plan task decomposition:`.
- Create `tests/sdd_scripts/test_decision_audit_entry_points.py`.

**NOT in scope**: the gate script itself (TASK-5010), the CLI (TASK-5009), the taxonomy / seed files
(TASK-5012/P17), the docs page `docs/sdd/decision-audit.md` (TASK-5013), CI wiring, `/sdd-brief`
(deferred, spec §8), aligning `codebase-conventions.md`'s httpx wording (spec M10 follow-up note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | Add Governing Decisions / Decisions / Decision Waivers / Consequences sections |
| `.claude/commands/sdd-spec.md` | MODIFY | Add §4b retrieve and §5b gate steps |
| `.agent/workflows/sdd-spec.md` | MODIFY | Byte-identical twin of the sdd-spec inserts |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Add steps 9b / 10b (Codex) |
| `.claude/commands/sdd-task.md` | MODIFY | Add §2b advisory check |
| `.agent/workflows/sdd-task.md` | MODIFY | Byte-identical twin of the sdd-task insert |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Add step 4b (Codex) |
| `tests/sdd_scripts/test_decision_audit_entry_points.py` | CREATE | Template headings + entry-point step tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test module only — stdlib + pytest
from pathlib import Path
import pytest
```

### Existing Signatures to Use
```text
sdd/templates/spec.md:50        ---                                   (separator above §2)
sdd/templates/spec.md:52        ## 2. Architectural Design            (count 1)
sdd/templates/spec.md:302       ## 7. Implementation Notes & Constraints
sdd/templates/spec.md:325       ---                                   (separator above §8)
sdd/templates/spec.md:327       ## 8. Open Questions                  (count 1)
.claude/commands/sdd-spec.md:444   ### 5. Scaffold the Spec          (count 1)
.claude/commands/sdd-spec.md:580   ### 6. Commit the Spec            (count 1)
.agent/workflows/sdd-spec.md:448   ### 5. Scaffold the Spec          (count 1)
.agent/workflows/sdd-spec.md:584   ### 6. Commit the Spec            (count 1)
.agents/skills/sdd-spec/SKILL.md:116  10. Write the spec:            (count 1)
.agents/skills/sdd-spec/SKILL.md:149  11. Commit:                    (count 1)
.claude/commands/sdd-task.md:101   ### 2. Read the Spec              (count 1)
.claude/commands/sdd-task.md:106   ### 3. Plan Task Decomposition    (count 1)
.agent/workflows/sdd-task.md:97    ### 2. Read the Spec              (count 1)
.agent/workflows/sdd-task.md:102   ### 3. Plan Task Decomposition    (count 1)
.agents/skills/sdd-task/SKILL.md:66   5. Plan task decomposition:    (count 1)

tests/sdd_scripts/test_command_twin_parity.py:22  _TWINNED includes "sdd-spec", "sdd-task" — the
    .claude/commands file and its .agent/workflows twin must be byte-identical modulo frontmatter and ONE
    listed substitution line; any inserted text must therefore be identical in both.
tests/sdd_scripts/test_command_contracts.py:102-131  _SHIPPED_WITH_INLINE_PYTHON_BAN covers both sdd-spec
    twins, both sdd-task twins and .agents/skills/sdd-task/SKILL.md; regex
    `python3?\s+(?:-c\s+"|-\s+(?:"\$\w+"\s+)?<<)` — never write `python -c "` or a `python - <<` heredoc;
    `python -m scripts.sdd.check_spec_consequences` is fine.
```

### Does NOT Exist
- ~~`## Governing Decisions` / `## Decisions` / `## Decision Waivers` / `## Consequences` in `sdd/templates/spec.md`~~ — added here.
- ~~any decision-plane call in `/sdd-spec` or `/sdd-task`~~ — zero today; added here.
- ~~`wikitoolkit spec` CLI group~~ — created by TASK-5009 (referenced by name only).
- ~~`scripts/sdd/check_spec_consequences.py`~~ — created by TASK-5010 (referenced by name only).
- ~~a `### 4b.` / `### 5b.` / `### 2b.` heading in these files today~~ — verify `grep -c '^### 4b\.'` is 0 before inserting.
- ~~`/sdd-brief` decision preview~~ — deferred (spec §8); do not touch `sdd-brief` files.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/templates/spec.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_decision_audit_entry_points.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Twins: write each insert ONCE, then paste the exact same bytes into the `.claude/commands` and
  `.agent/workflows` file. Run `test_command_twin_parity.py` before committing.
- Never refuse in `/sdd-task`: the advisory step's text must say "never refuses" and "continue" (AC19).
- `/sdd-spec` refuses only the `approved` transition, and only on exit 1/2/3 or stale/missing sections;
  `skipped` (exit 0, one-line note) proceeds normally (G8).
- The governing dossier needs the spec's frontmatter (`projects`, `tags`) and Codebase Contract targets,
  so §4b tells the author to write a draft file with frontmatter + §1 first, render the dossier into it,
  and read it before drafting §2 (G1).
- Keep the template's `---` section rhythm; generated sections carry an HTML comment saying they are
  generated and must not be hand-edited.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `sdd/templates/spec.md` (two inserts) — *why*: the template is what `/sdd-spec` copies (AC15).
2. Write the `/sdd-spec` §4b and §5b text once; insert into both twins — *why*: twin parity test.
3. Write the `/sdd-task` §2b text once; insert into both twins — *why*: twin parity test.
4. Adapt the same content as numbered steps for the two Codex skills — *why*: Codex runs the same flow.
5. Write the test module and run it with the twin-parity and command-contract tests — *why*: those two existing tests break on a mismatched or inline-python insert.

### `sdd/templates/spec.md` (MODIFY)
````markdown
<!-- occurrences: 1 (verified: grep -c '^## 2. Architectural Design' sdd/templates/spec.md) -->
<!-- BEFORE — insert above `## 2. Architectural Design` (verified: sdd/templates/spec.md:52) -->
## Governing Decisions

<!-- GENERATED by `python -m scripts.sdd.check_spec_consequences <spec> --render` — do not edit by hand.
     Lists every accepted decision governing this spec's subsystems and targets (FEAT-784).
     Unconfigured repositories render one line: "decision audit not configured in this repository". -->

---

<!-- occurrences: 1 (verified: grep -c '^## 8. Open Questions' sdd/templates/spec.md) -->
<!-- BEFORE — insert above `## 8. Open Questions` (verified: sdd/templates/spec.md:327) -->
## Decisions

<!-- OPTIONAL, authored. Omit the whole section when the spec decides nothing architectural.
     Grammar: docs/sdd/decision-audit.md. Each entry id becomes adr:spec:<document_id>#<id>. -->
```yaml
schema_version: 1
document_id: <feature-slug>
entries:
  - id: <entry-id>
    statement: <one normative sentence>
    relation: constrains   # constrains | forbids | requires
    about: [<taxonomy subsystem id>]
    targets: [<sym:… | file:… | dir:…>]
    contradicts: []
    supersedes: []
    rationale: ""
    rejected_alternatives: []
```

## Decision Waivers

<!-- OPTIONAL, authored; only for an approved waiver of a blocking contradiction. -->

## Consequences

<!-- GENERATED by `python -m scripts.sdd.check_spec_consequences <spec> --render` — do not edit by hand. -->

---

````
**Why**: positions are fixed by the renderer's splice contract (spec M7: Governing before §2, the
generated Consequences before §8) and the authored block sits after §7 (spec M10). FILL IN: when
pasting, the `---` already present above `## 8.` (line 325) stays where it is — make sure exactly one
`---` separates each section; verify by eye in a rendered preview.

### `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md` (MODIFY — identical bytes)
````markdown
# occurrences: 1 each (verified: grep -c '^### 5. Scaffold the Spec' — claude:444, agent:448)
# BEFORE — insert above `### 5. Scaffold the Spec`
### 4b. Retrieve Governing Decisions

Before drafting §2, write the draft spec file with its frontmatter (`projects`, `tags`) and §1, then run:

```bash
wikitoolkit spec governing sdd/specs/<feature-name>.spec.md
```

Read every listed decision (rationale, consequences, supersession, freshness) and design §2–§7 within
them. A spec that changes a governing decision must say so in `## Decisions` with `supersedes:` or
`contradicts:` — never silently. When the command prints `decision audit not configured in this
repository`, skip this step.

# occurrences: 1 each (verified: grep -c '^### 6. Commit the Spec' — claude:580, agent:584)
# BEFORE — insert above `### 6. Commit the Spec`
### 5b. Consequence Gate

Render, then check (read-only):

```bash
python -m scripts.sdd.check_spec_consequences sdd/specs/<feature-name>.spec.md --render
python -m scripts.sdd.check_spec_consequences sdd/specs/<feature-name>.spec.md
```

Exit codes: `0` pass or skipped · `1` conflict · `2` invalid · `3` incomplete, stale or missing
generated sections. **Refuse `**Status**: approved` on any non-zero exit** and report the findings;
`skipped` (repository not configured) proceeds normally. Never hand-edit `## Governing Decisions` or
`## Consequences` — re-run `--render` instead.
````
**Why**: placement and wording are frozen by spec M10 / AC15; identical bytes keep
`test_command_twin_parity.py` green. FILL IN: none beyond verbatim insertion.

### `.agents/skills/sdd-spec/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^10\. Write the spec:' — SKILL.md:116)
# BEFORE — insert above `10. Write the spec:`
9b. Retrieve governing decisions (FEAT-784), before drafting §2:
   - write the draft spec with frontmatter (`projects`, `tags`) and §1 first
   - run `wikitoolkit spec governing <spec>` and design within the listed decisions
   - changing one requires an explicit `supersedes:` / `contradicts:` entry in `## Decisions`
   - skip when it prints `decision audit not configured in this repository`
# occurrences: 1 (verified: grep -c '^11\. Commit:' — SKILL.md:149)
# BEFORE — insert above `11. Commit:`
10b. Consequence gate (FEAT-784):
   - `python -m scripts.sdd.check_spec_consequences <spec> --render`, then the same without `--render`
   - exit 0 pass/skipped · 1 conflict · 2 invalid · 3 incomplete/stale/missing
   - refuse `**Status**: approved` on any non-zero exit; `skipped` proceeds
```

### `.claude/commands/sdd-task.md` and `.agent/workflows/sdd-task.md` (MODIFY — identical bytes)
````markdown
# occurrences: 1 each (verified: grep -c '^### 3\. Plan Task Decomposition' — claude:106, agent:102)
# BEFORE — insert above `### 3. Plan Task Decomposition` (i.e. right after §2 Read the Spec)
### 2b. Advisory Decision-Audit Check

```bash
python -m scripts.sdd.check_spec_consequences <spec-path> --advisory
```

Advisory only (FEAT-784): it **never refuses** decomposition and always exits 0. It is silent when the
repository is not configured or the spec has no generated report; when an existing report is
`conflict`, `invalid`, `incomplete` or stale it prints a warning — copy that warning into the §6 output
and continue.
````

### `.agents/skills/sdd-task/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^5\. Plan task decomposition:' — SKILL.md:66)
# BEFORE — insert above `5. Plan task decomposition:`
4b. Advisory decision-audit check (FEAT-784):
   - `python -m scripts.sdd.check_spec_consequences <spec> --advisory`
   - never refuses, always exits 0; repeat any warning in the final output and continue
```

### `tests/sdd_scripts/test_decision_audit_entry_points.py` (CREATE)
```python
"""FEAT-784 M10: the template and every /sdd-spec and /sdd-task entry point carry the audit steps."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_ENTRY_POINTS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md")
_TASK_ENTRY_POINTS = (".claude/commands/sdd-task.md", ".agent/workflows/sdd-task.md", ".agents/skills/sdd-task/SKILL.md")


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def test_template_sections_in_order() -> None:
    # FILL IN: index of "## Governing Decisions" < "## 2. Architectural Design" <
    #   "## 7. Implementation Notes" < "## Decisions" < "## Decision Waivers" < "## Consequences" <
    #   "## 8. Open Questions" (match full lines) — bounded by spec M7/M10 placement
    raise NotImplementedError


@pytest.mark.parametrize("rel", _SPEC_ENTRY_POINTS)
def test_sdd_spec_has_retrieve_and_gate(rel: str) -> None:
    # FILL IN: text contains "wikitoolkit spec governing", "check_spec_consequences", "--render" and
    #   "approved"; retrieve step appears before the gate step — AC15
    raise NotImplementedError


@pytest.mark.parametrize("rel", _TASK_ENTRY_POINTS)
def test_sdd_task_check_is_advisory(rel: str) -> None:
    # FILL IN: contains "check_spec_consequences" and "--advisory" and "never refuses" — AC19
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Template separators: exactly one `---` between sections after both inserts
- [ ] Twins byte-identical (run the parity test)
- [ ] Three test bodies

---

## Acceptance Criteria

- [ ] Template carries the four new headings in the order above (AC15).
- [ ] All three `/sdd-spec` entry points carry the retrieve and gate steps; `approved` refused on non-zero exit or stale/missing sections, never on `skipped` (AC15, G8).
- [ ] All three `/sdd-task` entry points carry the advisory step, worded as never refusing (AC19).
- [ ] `test_command_twin_parity.py` and `test_command_contracts.py` still pass.
- [ ] `ruff check tests/sdd_scripts/test_decision_audit_entry_points.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_decision_audit_entry_points.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

See the blueprint test module: `test_template_sections_in_order`, `test_sdd_spec_has_retrieve_and_gate`
(3 params), `test_sdd_task_check_is_advisory` (3 params).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Re-run every `grep -c` anchor listed above; a count other than 1 means drift — re-locate and fix the contract first.
3. Mark in-progress, apply the inserts, run the Validation Commands.
4. Shared-tree hazard (spec §7): other features edit the `/sdd-spec` files — rebase onto `origin/dev` right before committing.
5. Commit only the eight listed files; close with `scripts/sdd/close_task.sh TASK-5011 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
