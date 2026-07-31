# TASK-1893: Generic Pydantic Wizard Engine (`parrot/cli/wizard.py`)

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / Goal G2. The console must collect `WorkBrief` /
`RevisionBrief` through interactive prompts generated **from the pydantic
models themselves** — a generic, reusable engine (resolved proposal U2), not a
hand-written form. Field metadata (`description`, defaults, `Literal`
choices, required-ness) drives the prompts. This module is deliberately
standalone: it must not import anything from `parrot.flows.dev_loop` (it is
tested against those models, but the engine is model-agnostic).

---

## Scope

- Implement `WizardFieldOverride`, `WizardConfig`, and `PydanticWizard` in
  `packages/ai-parrot/src/parrot/cli/wizard.py` per spec §2 "New Public
  Interfaces".
- `PydanticWizard(model, *, config=None, console=None)` with
  `async def collect(self, *, initial: dict | None = None) -> BaseModel`.
- Field handling driven by `model.model_fields` (pydantic v2):
  - str/int/float: text prompt; show description + default; empty input →
    default (or re-prompt if required).
  - `bool`: y/n prompt.
  - `Literal[...]`: numbered choice list.
  - `Optional[X]`: allow empty → `None`.
  - Nested `BaseModel`: recursive sub-form.
  - `List[...]`: interactive "add another? [y/N]" loop of typed item
    sub-forms; for `Union` item types (e.g. the acceptance-criterion union)
    show a variant picker first (G6).
  - `@path` file input (G6 + spec §7): for plain-text fields with
    `file_loadable=True` (or `allow_file_input`), `@some/file.md` inlines
    the file's contents (cap 64 KiB, prepend a `# source: <path>` header
    line per spec §7); for list/model fields, parse the file as YAML/JSON
    into the field value.
  - `initial=` pre-seeds answers (fields present in `initial` are skipped
    unless validation fails).
- Per-field validation loop: build the model at the end; on
  `ValidationError`, re-prompt ONLY the offending field(s), keeping prior
  answers.
- Use `prompt_toolkit` async prompting (`PromptSession.prompt_async`) and
  Rich for presentation. Must be usable while no Rich Live is active
  (the console pauses Live around wizard use — not this task's concern).
- Unit tests per spec §4 (wizard rows) in
  `packages/ai-parrot/tests/cli/test_wizard.py`, using prompt_toolkit
  pipe input (`prompt_toolkit.input.create_pipe_input`) and
  `rich.console.Console(record=True)`.

**NOT in scope**: anything devloop-specific (defaults from navconfig,
reporter identity resolution — TASK-1896); the `parrot/cli/devloop/`
package (TASK-1894+); click commands (TASK-1897).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/wizard.py` | CREATE | PydanticWizard + WizardConfig/WizardFieldOverride |
| `packages/ai-parrot/tests/cli/test_wizard.py` | CREATE | Unit tests (pipe input) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, ValidationError   # pydantic v2 (core dep)
from rich.console import Console                          # rich>=13.0, pyproject.toml:77
from prompt_toolkit import PromptSession                  # prompt_toolkit>=3.0, pyproject.toml:82
from prompt_toolkit.input import create_pipe_input        # for tests
# Test-target models (engine itself must NOT import these at module level):
from parrot.flows.dev_loop.models import (                # models.py — verified 2026-07-24
    WorkBrief,            # line 129
    RevisionBrief,        # line 274
    FlowtaskCriterion,    # line 44
    ShellCriterion,       # line 55
    ManualCriterion,      # line 70
    LogSource,            # line 118
)
```

### Existing Signatures to Use
```python
# pydantic v2 introspection (the whole engine keys off this):
# model.model_fields: dict[str, FieldInfo]
#   FieldInfo.is_required() -> bool
#   FieldInfo.default / .default_factory
#   FieldInfo.description: str | None
#   FieldInfo.annotation  -> resolve with typing.get_origin/get_args
#     (Literal choices, Optional, List[...], Union members)

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:129
class WorkBrief(BaseModel):
    kind: Literal['bug','enhancement','new_feature'] = 'bug'
    summary: str                       # required, ≤255
    description: str = ''
    affected_component: str            # required
    log_sources: List[LogSource]
    acceptance_criteria: List[FlowtaskCriterion|ShellCriterion|ManualCriterion]
    escalation_assignee: str           # required
    reporter: str                      # required
    existing_issue_key: Optional[str] = None
    dev_agents: Optional[List[DevAgentSpec]] = None
    dev_isolation: Optional[Literal['shared','isolated']] = None
# RevisionBrief (models.py:274): repo_path, branch, pr_number: int,
#   repository, jira_issue_key, feedback, head_sha — all required str/int.

# Rich console conventions in this repo:
# packages/ai-parrot/src/parrot/cli/renderer.py:21 — class ResponseRenderer
```

### Does NOT Exist
- ~~`pydantic.forms` / `pydantic_cli` / any form library~~ — build on
  `model_fields` directly; no new dependency may be added.
- ~~`questionary` / `InquirerPy` / `textual`~~ — not dependencies; use
  prompt_toolkit + rich only.
- ~~`parrot.cli.wizard`~~ — does not exist yet; this task creates it.
- ~~`WorkBrief.model_fields[...].choices`~~ — pydantic FieldInfo has no
  `.choices`; derive Literal options via `typing.get_args`.

---

## Implementation Notes

### Pattern to Follow
- Module/docstring/logging style: `packages/ai-parrot/src/parrot/cli/repl.py`
  (REPLConfig:27, AgentREPL:58) — Google docstrings, strict type hints,
  `logging.getLogger(__name__)`.
- Async-first: `collect()` is async; all prompting via
  `PromptSession.prompt_async()`.

### Key Constraints
- Zero new dependencies (spec AC).
- Engine is model-agnostic: no `parrot.flows.*` import in `wizard.py`.
- `@path` reads are capped at 64 KiB; oversize → friendly error + re-prompt.
- Discriminated-union list items: pick variant by class name (e.g.
  `FlowtaskCriterion` / `ShellCriterion` / `ManualCriterion`), then sub-form.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/repl.py` — style/async patterns.
- `packages/ai-parrot/src/parrot/human/cli_companion.py` — Rich question
  rendering precedent.

---

## Acceptance Criteria

- [ ] `PydanticWizard(WorkBrief).collect()` returns a validated `WorkBrief`
  from scripted pipe input (full round-trip test).
- [ ] Literal → numbered choices; bool → y/n; Optional empty → None;
  defaults honored; required re-prompts.
- [ ] List fields: "add another?" loop + union variant picker; YAML/JSON
  `@file` fills a whole list field.
- [ ] `@path` on a text field inlines contents with `# source:` header and
  64 KiB cap.
- [ ] `ValidationError` re-prompts only the offending field, keeping others.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/test_wizard.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/wizard.py` clean.
- [ ] `from parrot.cli.wizard import PydanticWizard` works.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_wizard.py
import pytest
from prompt_toolkit.input import create_pipe_input
from parrot.cli.wizard import PydanticWizard, WizardConfig
from parrot.flows.dev_loop.models import WorkBrief

async def test_wizard_workbrief_roundtrip(pipe_console):
    """Scripted answers produce the expected validated WorkBrief."""

async def test_wizard_literal_choice_rejects_invalid(pipe_console):
    """Out-of-range choice for `kind` re-prompts."""

async def test_wizard_validation_loop(pipe_console):
    """summary > 255 chars re-prompts only `summary`."""

async def test_wizard_list_loop_union_variants(pipe_console):
    """acceptance_criteria: Shell + Manual items via variant picker."""

async def test_wizard_file_input_text_and_yaml(tmp_path, pipe_console):
    """@path inlines description text; @file.yaml fills list field."""
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/devloop-cli-console.spec.md` (§2, §3 M1, §6, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — grep/read each reference before coding.
4. **Update status** in `sdd/tasks/index/devloop-cli-console.json` → `"in-progress"`.
5. **Implement** (TDD: tests first).
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
