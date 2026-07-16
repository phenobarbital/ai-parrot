---
type: Wiki Overview
title: 'TASK-1217: Pydantic input/output models for PR-context tools'
id: doc:sdd-tasks-completed-task-1217-pydantic-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundational task. Defines the Pydantic input and output models that the
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1217: Pydantic input/output models for PR-context tools

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundational task. Defines the Pydantic input and output models that the
three new `@tool_schema` tools (`get_file_content_at_ref`,
`compare_pr_versions`, `search_repo_code`) will consume and produce.

Implements spec §2 Data Models and is a prerequisite for TASK-1219,
TASK-1220 and TASK-1221.

---

## Scope

- Add six new Pydantic models to
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`, placed
  alongside the existing input-model block (near `GeneratePatchInput` /
  `CreatePullRequestInput`):
  - `GetFileContentInput`
  - `ComparePRVersionsInput`
  - `SearchRepoCodeInput`
  - `FileContentResult`
  - `CompareVersionsResult`
  - `SearchCodeResult`
- Write unit tests in
  `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py`
  (create the file) verifying:
  - required fields raise `ValidationError` when omitted,
  - `start_line` / `end_line` reject values `< 1`,
  - `max_results` rejects values outside `[1, 100]`.

**NOT in scope**:
- The tool methods themselves (TASK-1219/1220/1221).
- The cache helper (TASK-1218).
- Touching `github_reviewer.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add 6 Pydantic models in the input-model block |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` | CREATE | Unit tests for the 6 models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported at the top of gittoolkit.py (verified):
from pydantic import BaseModel, Field, model_validator   # gittoolkit.py:37
from typing import Any, Dict, List, Literal, Optional   # gittoolkit.py:31
```

No new imports needed. Use existing pydantic 2 idioms.

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
# Pattern to mirror — every existing *Input model in this file uses these
# pydantic v2 idioms:
class GeneratePatchInput(BaseModel):                       # line 136
    files: List[GitPatchFile] = Field(description="...")
    context_lines: int = Field(default=3, ge=0, description="...")
    include_apply_snippet: bool = Field(default=True, description="...")

class CreatePullRequestInput(BaseModel):                   # line 183
    repository: Optional[str] = Field(default=None, description="...")
    title: str = Field(description="...")
    # ...
```

### Does NOT Exist

- ~~`pydantic.BaseModel` v1 style (`Config` inner class)~~ — this file is on
  pydantic v2; use `model_config = ConfigDict(...)` if config needed (likely none).
- ~~`Field(...)` positional default~~ — always use `Field(default=...)`.

---

## Implementation Notes

### Model definitions (final shape)

Verbatim from spec §2 Data Models. Implementer must paste these as-is,
keeping field descriptions intact (they become tool schema descriptions
in the LLM prompt). The full model bodies are listed in
`sdd/specs/gittoolkit-pr-context-retrieval.spec.md` §2 — copy them
verbatim.

### Key Constraints

- Pydantic v2 only. No `BaseConfig` / `Config` inner class needed.
- Every `Field` must include a `description=` so the JSON schema is useful
  to the LLM.
- `FileContentResult.error` is a `Literal[...]`-like string today
  (`'file_too_large' | 'rate_limited' | None`). Keep it as
  `Optional[str]` to allow future error codes without a schema migration.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:136` —
  `GeneratePatchInput` (pattern to mirror).
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:153` —
  `GitHubFileChange` (pattern with `Literal` enum field).

---

## Acceptance Criteria

- [ ] All 6 models defined in `gittoolkit.py` and importable:
  `from parrot_tools.gittoolkit import GetFileContentInput, FileContentResult, ...`
- [ ] `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py::test_pydantic_models_validate_inputs -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` passes.
- [ ] No existing tests broken: `pytest packages/ai-parrot-tools/tests/ -v`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py
import pytest
from pydantic import ValidationError
from parrot_tools.gittoolkit import (
    GetFileContentInput,
    ComparePRVersionsInput,
    SearchRepoCodeInput,
    FileContentResult,
)


def test_get_file_content_requires_path_and_ref():
    with pytest.raises(ValidationError):
        GetFileContentInput()  # path and ref are required

def test_get_file_content_line_bounds():
    with pytest.raises(ValidationError):
        GetFileContentInput(path="a.py", ref="main", start_line=0)
    GetFileContentInput(path="a.py", ref="main", start_line=10, end_line=20)

def test_search_max_results_ceiling():
    with pytest.raises(ValidationError):
        SearchRepoCodeInput(query="x", max_results=200)
    SearchRepoCodeInput(query="x")  # default 20 OK
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/gittoolkit-pr-context-retrieval.spec.md` §2.
2. Verify the codebase contract is still current (re-read `gittoolkit.py`
   lines 31-180 and confirm pydantic v2 patterns).
3. Add the 6 models verbatim from spec §2.
4. Write the unit tests above plus the validators listed in spec §4
   (`test_pydantic_models_validate_inputs`).
5. Run `pytest` and `ruff check`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec
   index `sdd/tasks/index/gittoolkit-pr-context-retrieval.json` to mark
   status `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**:

**Deviations from spec**: none
