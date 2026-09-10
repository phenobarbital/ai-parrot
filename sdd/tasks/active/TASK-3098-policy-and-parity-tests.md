# TASK-3098: CLAUDE.md policy + command twin-parity test + design-research template tests

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 6, §4 Test Specification)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3093, TASK-3094, TASK-3095, TASK-3096, TASK-3097
**Assigned-to**: unassigned

---

## Context

Everything before this task is prose; this task makes it enforceable. It documents the design-research seat in `CLAUDE.md` (spec G3/AC-8), adds a parity test so the `.agent/workflows` twins cannot drift (G5/AC-7), and adds template/schema tests (AC-1/AC-6). Tests live in `tests/sdd_scripts/`, the existing home of SDD tooling tests.

---

## Scope

- Add a "Design research" paragraph + env var to `CLAUDE.md` §Adversarial Second Opinion.
- Create `tests/sdd_scripts/test_command_twin_parity.py` (2 parametrized cases).
- Create `tests/sdd_scripts/test_design_research_templates.py` (6 tests).

**NOT in scope**: editing the commands/templates (done in TASK-3093…3097); running codex (TASK-3099).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | ~12-line paragraph inside §Adversarial Second Opinion |
| `tests/sdd_scripts/test_command_twin_parity.py` | CREATE | frontmatter-strip + normalize + equality |
| `tests/sdd_scripts/test_design_research_templates.py` | CREATE | schema + prompt + template assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json                                              # stdlib
from pathlib import Path                                 # stdlib
import pytest                                            # used by every file in tests/sdd_scripts/
from jsonschema import Draft202012Validator, ValidationError  # jsonschema 4.26.0 installed; packages/ai-parrot/pyproject.toml:80
```
### Test-location facts
```text
tests/sdd_scripts/__init__.py exists (package); siblings: test_reserve_ids.py, test_sdd_meta.py, test_lint_new.py, ...
Repo root from a file in tests/sdd_scripts/:  Path(__file__).resolve().parents[2]
Precedent for twin parity: packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py:44-66
   (parametrized over names; read_text(encoding="utf-8") equality; skip when repo dir absent)
```
### `CLAUDE.md` anchors (verified 2026-09-10)
```text
:124  ### Adversarial Second Opinion
:126-128 "Use an external CLI agent as an independent perspective for adversarial code reviews, design opinions, brainstorming, research cross-checks, and implementation sanity checks. The reviewer is **`codex` (OpenAI)**."
:130  > **`agy` (Google Gemini / Antigravity) MUST NOT be used as a reviewer.**   ← leave untouched
:144  - Never feed the reviewer your reasoning, justification, or preferred conclusion.
:168  #### codex commands   (fenced bash :169-180)                                  ← insert the new paragraph AFTER this fenced block
```
### Twin files (inputs to the parity test; must exist after TASK-3094/3097)
```text
.claude/commands/sdd-spec.md   ↔ .agent/workflows/sdd-spec.md   (twin has 4-line YAML frontmatter + "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`")
.claude/commands/sdd-task.md   ↔ .agent/workflows/sdd-task.md
```
### Template strings asserted (must exist after TASK-3093/3095/3096)
```text
sdd/templates/task.md:  "## Implementation Blueprint"  "### Steps (in order)"  "### FILL IN checklist"
sdd/templates/spec.md:  "Interface Skeleton"  "## 9. Design Research Cross-Check"
sdd/templates/design_research.prompt.md: {{problem_statement}} {{constraints_and_goals}} {{recommended_option_or_scope}} {{code_context_paths}} {{open_questions}} {{question}}
sdd/templates/design_research.schema.json: kind enum = architecture|api|testing|risk|alternative
```
### Does NOT Exist
- ~~`tests/sdd_scripts/conftest.py`~~ — none; do not assume shared fixtures
- ~~`scripts.sdd.twin_parity`~~ / any helper module — the test is self-contained
- ~~`parrot.flows.dev_loop._subagent_data` for commands~~ — commands are NOT packaged; compare the two repo files directly

---

## Implementation Notes

### Pattern to Follow
`test_subagent_parity.py:44-66` for the parity test shape. Keep tests dependency-light (stdlib + jsonschema + pytest).

### Key Constraints
- Normalization removes only: a leading `---…---` frontmatter block, and lines starting with `- Worktree policy:`. Nothing else may differ.
- Do NOT touch the `agy` ban text in CLAUDE.md.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the CLAUDE.md paragraph — *why*: policy home; sdd-spec §3b already points readers here for the `agy` ban.
2. Write the parity test — *why*: G5; catches drift introduced by any later edit to either twin.
3. Write the template tests — *why*: AC-1/AC-6 make the template contract executable.
4. Run `pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v` (expect 8 passed).

### `CLAUDE.md` (MODIFY — insert after the `#### codex commands` fenced block, before `## Key References`)
```markdown

#### Design research at spec time (FEAT-545)

The same codex seat gives an **independent design opinion** in `/sdd-spec`
§3b, over the *accepted* brainstorm/proposal only — never over the spec
draft. Model: `${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}` with
`-c model_reasoning_effort=high` and `--ignore-user-config` (the operator's
`~/.codex/config.toml` must not swap the model silently). The pass is
**optional and never blocking**: no `codex`, failed probe, timeout or invalid
output ⇒ spec §9 reads `Status: skipped (<reason>)` and the command continues
(`sdd-planner` runs it unattended). Every suggestion is triaged
`CONFIRM` / `REJECT` / `ESCALATE` in spec **§9 Design Research Cross-Check**;
the transcript is committed under `sdd/state/<FEAT-ID>/design_research/`.
The `agy` ban above applies to this seat too.
```

### `tests/sdd_scripts/test_command_twin_parity.py` (CREATE)
```python
"""Body parity between `.claude/commands/<name>.md` and its `.agent/workflows/<name>.md` twin (FEAT-545).

The twin may differ ONLY by a leading YAML frontmatter block and by the
`- Worktree policy:` reference line; every other line must be identical.
Pattern: packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TWINNED = ("sdd-spec", "sdd-task")


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---`` … ``---`` YAML block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text if end == -1 else text[end + len("\n---\n"):].lstrip("\n")


def _normalize(text: str) -> str:
    """Remove the single tolerated delta line and trailing whitespace noise."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("- Worktree policy:")]
    return "\n".join(lines).strip()


@pytest.mark.parametrize("name", _TWINNED)
def test_command_twin_parity(name: str) -> None:
    """`.agent/workflows/<name>.md` body == `.claude/commands/<name>.md` body."""
    original = _REPO_ROOT / ".claude" / "commands" / f"{name}.md"
    twin = _REPO_ROOT / ".agent" / "workflows" / f"{name}.md"
    if not original.is_file() or not twin.is_file():
        pytest.skip(f"{name}: command or twin missing at this checkout")
    got = _normalize(_strip_frontmatter(twin.read_text(encoding="utf-8")))
    want = _normalize(original.read_text(encoding="utf-8"))
    assert got == want, f"{name}.md drifted between .claude/commands/ and .agent/workflows/"
```
**Why this shape**: mirrors the packaged-prompt parity test; `skip` (not fail) when files are absent so the test is safe on partial checkouts; the frontmatter stripper is deliberately minimal (the twins' frontmatter is exactly 3 lines + blank).

### `tests/sdd_scripts/test_design_research_templates.py` (CREATE)
```python
"""Executable contract for the FEAT-545 templates (spec §4)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TPL = _REPO_ROOT / "sdd" / "templates"
_SCHEMA = _TPL / "design_research.schema.json"
_PROMPT = _TPL / "design_research.prompt.md"
_PLACEHOLDERS = {
    "problem_statement", "constraints_and_goals", "recommended_option_or_scope",
    "code_context_paths", "open_questions", "question",
}


@pytest.fixture
def schema() -> dict:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def sample_suggestions() -> dict:
    return {
        "summary": "Two suggestions on the accepted design.",
        "suggestions": [
            {"id": "S1", "kind": "architecture", "title": "Stage output under sdd/state",
             "rationale": "artifacts/ is gitignored.", "affected_paths": [".gitignore"],
             "risk": "low", "confidence": "high"},
            {"id": "S2", "kind": "testing", "title": "Add twin parity test",
             "rationale": "Twins drift silently.", "affected_paths": [".agent/workflows/sdd-spec.md"],
             "risk": "medium", "confidence": "medium"},
        ],
    }


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)


def test_sample_suggestions_validate(schema: dict, sample_suggestions: dict) -> None:
    Draft202012Validator(schema).validate(sample_suggestions)


def test_unknown_kind_rejected(schema: dict, sample_suggestions: dict) -> None:
    sample_suggestions["suggestions"][0]["kind"] = "perf"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(sample_suggestions)


def test_prompt_has_all_placeholders() -> None:
    found = set(re.findall(r"{{([a-z_]+)}}", _PROMPT.read_text(encoding="utf-8")))
    assert found == _PLACEHOLDERS


def test_task_template_has_blueprint_section() -> None:
    text = (_TPL / "task.md").read_text(encoding="utf-8")
    for needle in ("## Implementation Blueprint", "### Steps (in order)", "### FILL IN checklist"):
        assert needle in text, needle
    assert text.index("## Implementation Blueprint") < text.index("## Acceptance Criteria")


def test_spec_template_has_skeleton_and_section_9() -> None:
    text = (_TPL / "spec.md").read_text(encoding="utf-8")
    assert "Interface Skeleton" in text
    assert "## 9. Design Research Cross-Check" in text
    assert text.index("## 8. Open Questions") < text.index("## 9. Design Research Cross-Check") < text.index("## Revision History")
```
**Why this shape**: each test maps to one spec §4 row; fixtures are inline (no conftest exists); ordering assertions encode AC-2/AC-3's "placed before" clauses.

### FILL IN checklist
- [ ] If TASK-3097 changed the twin's frontmatter to more than 3 lines, adjust `_strip_frontmatter` accordingly (it handles any length, but verify).
- [ ] Confirm the exact insertion point in CLAUDE.md after TASK-3097 (the `#### codex commands` fenced block ends at `:180` today).

---

## Acceptance Criteria

- [ ] `pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v` → 8 passed (spec AC-1)
- [ ] `grep -n "Design research at spec time" CLAUDE.md` → one match inside §Adversarial Second Opinion; `grep -c "agy.*MUST NOT" CLAUDE.md` unchanged (spec AC-8)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` still passes (spec AC-12)
- [ ] `ruff check tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py` clean

---

## Test Specification

The two new files ARE the test specification (see blueprint). Run with the venv active:
```bash
source .venv/bin/activate
pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v
```

---

## Agent Instructions

1. Read spec §3 Module 6 and §4.
2. Dependencies: TASK-3093…3097 all in `sdd/tasks/completed/`.
3. Implement from the blueprint; run tests; commit the three files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
