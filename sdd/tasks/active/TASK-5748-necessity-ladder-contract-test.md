# TASK-5748: Contract test — Necessity Ladder text in templates, commands, reviewer and conventions

**Feature**: FEAT-908 — Necessity Ladder — least-new-code gate in the SDD flow
**Spec**: `sdd/specs/ponytail-like-stairway.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5741, TASK-5742, TASK-5743, TASK-5744, TASK-5745, TASK-5746, TASK-5747
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 6 (M6), test part; spec §4 Unit Tests and AC 11. One content-contract test
> file pins every text contract the seven text tasks add, in the style of
> `tests/sdd_scripts/test_feat801_doc_contract.py`. Six of the seven test methods are written
> here; the documentation task (TASK-5749) adds the seventh with the page it checks.

---

## Scope

**Ladder**: R7 · reuses the contract-test pattern (`tests/sdd_scripts/test_feat801_doc_contract.py:1-8`) · est. 0 non-test LOC

- Create `tests/sdd_scripts/test_necessity_ladder_contract.py` with class
  `TestNecessityLadderContract` and six methods: `test_spec_template_has_ladder_sections`,
  `test_sdd_spec_twins_carry_the_gate`, `test_l7_scan_is_not_table_escaped`,
  `test_proposal_states_if_not_built`, `test_task_and_reviewer_bind_the_ladder`,
  `test_conventions_name_reuse_first`.
- Confirm the packaged assets are in sync on the merged feature branch (`check_asset_sync.py --check`).

**NOT in scope**: the wiki page and its test method (TASK-5749). Do not edit any file the
text tasks own — if an assertion fails because their text is wrong, report it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_necessity_ladder_contract.py` | CREATE | Six content-contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path  # stdlib; pattern: tests/sdd_scripts/test_feat801_doc_contract.py:3
```

### Existing Signatures to Use
```text
# REPO_ROOT = Path(__file__).resolve().parents[2]  — tests/sdd_scripts/test_feat801_doc_contract.py:5
# Files the tests read (all tracked; their new text comes from TASK-5741..5747):
sdd/templates/spec.md                       (TASK-5741)
.claude/commands/sdd-spec.md, .agent/workflows/sdd-spec.md, .agents/skills/sdd-spec/SKILL.md   (TASK-5742)
sdd/templates/synthesis.prompt.md, sdd/templates/proposal.md, .claude/commands/sdd-proposal.md,
  .agent/workflows/sdd-proposal.md, .agents/skills/sdd-proposal/SKILL.md                         (TASK-5743)
sdd/templates/brainstorm.md, .claude/commands/sdd-brainstorm.md, .agent/workflows/sdd-brainstorm.md,
  .agents/skills/sdd-brainstorm/SKILL.md                                                         (TASK-5744)
.claude/commands/sdd-task.md, .agent/workflows/sdd-task.md, .agents/skills/sdd-task/SKILL.md,
  sdd/templates/task.md                                                                          (TASK-5745)
.claude/agents/code-reviewer.md, packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md,
  .agents/agents/code-reviewer/agent.md                                                          (TASK-5746)
sdd/CONVENTIONS.md, .claude/rules/codebase-conventions.md, .agent/rules/codebase-conventions.md,
  packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md                        (TASK-5747)
# Frontmatter: .agent/workflows/* and some .claude/commands/* start with a `---` YAML block; compare bodies
#   with it stripped (same rule as tests/sdd_scripts/test_command_twin_parity.py::_strip_frontmatter).
```

### Does NOT Exist
- ~~`tests/sdd_scripts/test_necessity_ladder_contract.py`~~ — created by this task
- ~~a shared helper module for reading SDD assets in tests~~ — each contract test defines its own `_read`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/sdd_scripts/test_necessity_ladder_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Assert exact strings the text tasks wrote (quoted in the FILL IN checklist) — they were proven
  together in a dry run at `a09f65b651`: all six methods passed on the combined edits.
- The test must FAIL on today's `dev` (none of the strings exist yet) — that is what makes it a contract.
- `ruff check` must pass on the new file.

---

## Implementation Blueprint

### Steps (in order)
1. Write the block below, then fill each method body from the checklist — *why*: the strings are fixed by the text tasks.
2. `python scripts/sdd/check_asset_sync.py --check` exits 0 — *why*: confirms every text task regenerated its packaged copies (spec AC 10).
3. Run the Validation Commands and `ruff check tests/sdd_scripts/test_necessity_ladder_contract.py`.

### `tests/sdd_scripts/test_necessity_ladder_contract.py` (CREATE)
```python
"""FEAT-908 contract: the Necessity Ladder in the spec template, the SDD commands and review."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC_TWINS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md")
SPEC_SKILL = ".agents/skills/sdd-spec/SKILL.md"
SPEC_USAGE = (
    "/sdd-spec [<feature-slug>] [--type feature] [--base-branch <branch>] [--interview | --no-interview] "
    "[--resume [<staging-dir>]] [--research full|light|none] [--no-gate] [--budget tight|default|loose] "
    "[-- <notes>]"
)
L7_SCAN = "grep -niE 'future|later|extensib|pluggable|generic|just in case'"
REVIEWER_COPIES = (
    ".claude/agents/code-reviewer.md",
    "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md",
    ".agents/agents/code-reviewer/agent.md",
)
CONVENTIONS_COPIES = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)
REUSE_PACKAGES = ("asyncdb", "navconfig", "navigator-auth", "navigator-eventbus")


def _read(rel: str) -> str:
    """Return the text of a tracked file under the repository root."""
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _body(text: str) -> str:
    """Drop a leading YAML frontmatter block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text if end == -1 else text[end + len("\n---\n") :].lstrip("\n")


def _section(text: str, heading: str) -> str:
    """Return the body under ``heading`` up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading) + len(heading)
    ends = [text.find(f"\n{'#' * n} ", start) for n in range(1, len(level) + 1)]
    ends = [e for e in ends if e != -1]
    return text[start : min(ends)] if ends else text[start:]


class TestNecessityLadderContract:
    """Text contracts FEAT-908 adds to the shipped SDD commands, templates and review agents."""

    def test_spec_template_has_ladder_sections(self) -> None:
        """Template carries the ladder table, Totals line, Deferred line, Known Shortcuts and the §5 criterion."""
        # FILL IN: assertions — bounded by checklist item 1 (spec AC 1)

    def test_sdd_spec_twins_carry_the_gate(self) -> None:
        """Both full twins carry the guardrail, §4c, §5a and the `Ladder:` line and stay identical; the codex skill names them."""
        # FILL IN: assertions — bounded by checklist item 2 (spec AC 2, 3, 5)

    def test_l7_scan_is_not_table_escaped(self) -> None:
        """No sdd-spec twin carries the `\\|`-escaped scan; the plain alternation sits in a fenced block."""
        # FILL IN: assertions — bounded by checklist item 3 (spec AC 4)

    def test_proposal_states_if_not_built(self) -> None:
        """Synthesis prompt, both exploration templates and their command twins carry the clause and the deferred list."""
        # FILL IN: assertions — bounded by checklist item 4 (spec AC 6)

    def test_task_and_reviewer_bind_the_ladder(self) -> None:
        """sdd-task twins and the task template carry the `**Ladder**:` line; the reviewer copies carry the red flags."""
        # FILL IN: assertions — bounded by checklist item 5 (spec AC 7, 8)

    def test_conventions_name_reuse_first(self) -> None:
        """The seed's Reuse first section names no package; the three conventions copies are identical and name four."""
        # FILL IN: assertions — bounded by checklist item 6 (spec AC 9)
```
**Why this shape**: `_body` mirrors the twin-parity test's frontmatter rule; `_section` lets each
assertion target the section the spec names, not the whole file. Method names are fixed by spec §4.

### FILL IN checklist
1. `test_spec_template_has_ladder_sections` (`sdd/templates/spec.md`): `#### Necessity Ladder` index < `#### Delegation-eligible modules` index; contains `| Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |` and `Totals: <M> modules — reuse <a>`; `_section(text, "### Non-Goals (explicitly out of scope)")` contains `- Deferred: <thing not built> — <what would justify building it>`; `### External Dependencies` < `### Known Shortcuts` < `## Decisions`; contains `- [ ] No public symbol, file or dependency beyond §3 Interface Skeletons, §6 Edit Sites`.
2. `test_sdd_spec_twins_carry_the_gate`: `_body(claude).strip() == _body(google).strip()`; claude contains each of `**Least new code**`, `### 4c. Necessity Ladder (least-new-code gate)`, `### 5a. Lean Review (checks the Necessity Ladder — never asks)`, `   Ladder: reuse <a> · stdlib/platform <b>`, ``| Deferred Capabilities | §1 Non-Goals (`Deferred:` lines, verbatim) |``, ``"`sdd/CONVENTIONS.md`\n   § Reuse first"``, `SPEC_USAGE`; order `### 4b. Retrieve Governing Decisions` < `### 4c. Necessity Ladder` < `### 5. Scaffold the Spec`, and `### 5a. Lean Review` < `### 5b. Consequence Gate`; the skill contains `Least new code`, `Necessity Ladder`, `Lean Review`, `` `Ladder:` line ``.
3. `test_l7_scan_is_not_table_escaped`: `"future\\|later"` absent from both twins and the skill; each twin contains ``"```bash\n# L7 — speculation scan"``; every line containing `L7_SCAN` exists and does not start (after `lstrip`) with `|`.
4. `test_proposal_states_if_not_built`: synthesis prompt contains `` `if_not_built` `` and `- what is DEFERRED`; proposal template contains `*If not built*: <requirement left unmet>` and `- Deferred: <capability considered and not proposed>`; both `/sdd-proposal` full twins contain ``6. In enrichment mode, every NEW item has a non-empty `if_not_built` `` and ``| §3 What's Untouched — `Deferred:` lines | Spec §1 Non-Goals``; proposal skill contains ``listed as `Deferred:` under Non-Goals``; brainstorm template contains `*If not built*: <requirement left unmet>` and `### Deferred Capabilities`; both `/sdd-brainstorm` full twins contain `goes under "Deferred Capabilities" instead` and ``- **Deferred Capabilities** → Spec Section 1 (Non-Goals, `Deferred:` lines)``; brainstorm skill contains `"Deferred Capabilities", not proposed`.
5. `test_task_and_reviewer_bind_the_ladder`: both `/sdd-task` full twins contain `**Necessity Ladder is binding (FEAT-908).**` and ``"`**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`"``; task skill contains ``"`**Ladder**:` line"``; `_section(task template, "## Scope")` contains `**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`; for each `REVIEWER_COPIES`, `_section(text, "## Universal Red Flags")` contains `spec's Necessity Ladder does not declare`, ``around twice the task's `**Ladder**` estimate`` and ``"`# shortcut:` comment without a Known Shortcuts row"``; `REVIEWER_COPIES[0]` text == `REVIEWER_COPIES[1]` text.
6. `test_conventions_name_reuse_first`: `_section(seed, "## Reuse first")` contains `Necessity Ladder` and none of `REUSE_PACKAGES`; the three `CONVENTIONS_COPIES` are equal; `_section(first, "## Reuse first — check these before writing new code")` contains each package in backticks; `## Reuse first` index < `## Repository layout` index.

Add `assert …, <path or marker>` messages so a failure names the file.

---

## Acceptance Criteria

- [ ] The six methods exist with the names above and pass on the merged feature branch
- [ ] `python scripts/sdd/check_asset_sync.py --check` exits 0 (spec AC 10)
- [ ] `ruff check tests/sdd_scripts/test_necessity_ladder_contract.py` passes
- [ ] All Validation Commands pass

---

## Validation Commands

- `pytest tests/sdd_scripts/test_necessity_ladder_contract.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

The blueprint above is the test scaffold; the checklist fixes every assertion.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug ponytail-like-stairway --feature-id FEAT-908`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5741 … TASK-5747 must be `"done"` in
   `sdd/tasks/index/ponytail-like-stairway.json`
4. **Verify the Codebase Contract** — read each file in the list; the strings in the checklist must be present
5. **Update status** in `sdd/tasks/index/ponytail-like-stairway.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the blueprint, complete every `# FILL IN:` marker, never rename a method
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the file this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5748 ponytail-like-stairway verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
