# TASK-2346: `FirefliesFilters` Pydantic model + field-name mapping

**Feature**: FEAT-441 — Fireflies MCP Meeting Filters & Native Summary Retrieval
**Spec**: `sdd/specs/fireflies-mcp-improvements.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundational module for the `fireflies-mcp-meeting-filters` capability
(spec §3 Module 1). `FirefliesObsidianAgent.sync_fireflies_transcripts()`
currently calls `fireflies_get_transcripts` with only `limit` — every other
filter the tool supports (date range, keyword/scope, organizer/participant
emails, mine-only, channel) is unreachable. This task defines the typed
model and the pure mapping function everything else in the feature builds
on (TASK-2347, TASK-2348 both depend on this).

Also introduces this feature's only new dependency: `email-validator`
(required for `pydantic.EmailStr`).

---

## Scope

- Add a new `email-validator` dependency to
  `packages/ai-parrot/pyproject.toml` (via `uv add email-validator`, per
  `CLAUDE.md`: manage dependencies through `pyproject.toml`).
- Add `FirefliesFilters(BaseModel)` to
  `packages/ai-parrot/src/parrot/agents/obsidian.py` with fields:
  `from_date: Optional[str]`, `to_date: Optional[str]`, `keyword:
  Optional[str]` (max_length=255), `scope: Literal["title", "sentences",
  "all"] = "all"`, `organizers: list[EmailStr]` (default empty),
  `participants: list[EmailStr]` (default empty), `mine: Optional[bool]`,
  `channel_id: Optional[str]`.
- Add the new imports this requires: `from pydantic import BaseModel,
  Field, EmailStr` and `Literal` from `typing` (already imports `Optional,
  Dict, Any, List` — add `Literal` to that import line).
- Add a pure mapping function, e.g. `_filters_to_tool_args(filters:
  FirefliesFilters) -> Dict[str, Any]`, that converts the model's
  snake_case fields to the tool's camelCase parameter names
  (`from_date`→`fromDate`, `to_date`→`toDate`, `channel_id`→`channelId`;
  `keyword`/`scope`/`organizers`/`participants`/`mine` pass through
  unchanged) and drops any field left at its unset/`None`/empty-list
  default so the resulting dict only carries filters the caller actually
  specified.
- Write unit tests for the model (valid construction, `scope` enum
  rejection, malformed-email rejection) and the mapping function (correct
  camelCase keys, unset fields dropped).

**NOT in scope**:
- Wiring `FirefliesFilters` into `sync_fireflies_transcripts()` or the
  constructor — that's TASK-2347/TASK-2348.
- Anything related to `include_summary` / `fireflies_get_summary` —
  that's TASK-2349.
- Documenting `default_filters` in `fireflies_daemon.yaml` — that's
  TASK-2350.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `email-validator` dependency. |
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | Add `FirefliesFilters` model, new imports, `_filters_to_tool_args()` mapping function. |
| `packages/ai-parrot/tests/agents/test_obsidian.py` | MODIFY | Add tests for the model and mapping function. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:11-22 (already present — verify unchanged before editing)
import os
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path, PurePosixPath
import logging
from navconfig import config
from parrot.bots.agent import BasicAgent
from parrot.tools.obsidian import ObsidianToolkit
from parrot.models.responses import AIMessage
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType, RelationType

# NEW for this task — add:
from pydantic import BaseModel, Field, EmailStr
# and add Literal to the existing typing import line:
from typing import Optional, Dict, Any, List, Literal
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:48
class FirefliesObsidianAgent(BasicAgent):
    ANALYSIS_HEADING: str = "## Analysis"  # line 74 — pattern reference only, not touched by this task
```

### Does NOT Exist
- ~~`FirefliesFilters` anywhere in `obsidian.py`~~ — does not exist yet; this task creates it.
- ~~`email-validator` installed in the current environment~~ — verified NOT installed (`pydantic.EmailStr` currently raises `ImportError: email-validator is not installed`). This task must add it.
- ~~A `_filters_to_tool_args` or similarly-named mapping function~~ — does not exist yet.
- ~~`pydantic[email]` extra already declared anywhere in `packages/ai-parrot/pyproject.toml`~~ — not present; use a plain `email-validator` dependency entry (or the `pydantic[email]` extra — either satisfies the import, pick the plain package for a smaller diff unless the extra is already the project's convention elsewhere).

---

## Implementation Notes

### Pattern to Follow
```python
# Model shape (spec §2 Data Models) — exact field set, do not add extra fields:
class FirefliesFilters(BaseModel):
    """Structured, validated filters over the fireflies_get_transcripts
    MCP tool. Field names are snake_case; sync_fireflies_transcripts()
    maps them to the tool's camelCase parameter names before the call.
    """
    from_date: Optional[str] = None     # → fromDate (ISO-8601, e.g. "2023-01-01")
    to_date: Optional[str] = None       # → toDate
    keyword: Optional[str] = Field(default=None, max_length=255)
    scope: Literal["title", "sentences", "all"] = "all"
    organizers: list[EmailStr] = Field(default_factory=list)
    participants: list[EmailStr] = Field(default_factory=list)
    mine: Optional[bool] = None
    channel_id: Optional[str] = None    # → channelId; raw ID only, no name resolution
```

### Key Constraints
- `from_date`/`to_date` stay plain `Optional[str]` — do NOT use
  `datetime.date`; the underlying tool takes an ISO-8601 string and a date
  type would only add a formatting step with no validation benefit (spec §2).
- Do not attempt to resolve a channel name to `channel_id` — out of scope
  for the whole feature (spec Non-Goals).
- The mapping function must be a pure function (no `self`), independently
  testable per the Test Specification below.
- Follow existing naming conventions in `obsidian.py` (snake_case methods,
  `@staticmethod`/plain function for stateless helpers).

### References in Codebase
- `packages/ai-parrot/src/parrot/agents/obsidian.py:520` `_build_okf_frontmatter()` — existing `@staticmethod` pattern in this file for a pure, stateless helper.
- `sdd/specs/fireflies-mcp-improvements.spec.md` §2 (Data Models), §6 (Fireflies MCP Tool Parameters — `fireflies_get_transcripts`) — full parameter reference.

---

## Acceptance Criteria

- [ ] `email-validator` is added to `packages/ai-parrot/pyproject.toml` and `pydantic.EmailStr` imports/works without raising `ImportError`.
- [ ] `FirefliesFilters` model exists with exactly the fields listed above.
- [ ] `FirefliesFilters(scope="invalid")` raises `pydantic.ValidationError`.
- [ ] `FirefliesFilters(organizers=["not-an-email"])` raises `pydantic.ValidationError`.
- [ ] Mapping function converts `from_date`/`to_date`/`channel_id` to `fromDate`/`toDate`/`channelId` and passes other fields through unchanged.
- [ ] Mapping function omits any field left at its default/unset value from the output dict.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/agents/test_obsidian.py -v -k Filters`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/agents/obsidian.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/agents/test_obsidian.py
import pytest
from pydantic import ValidationError
from parrot.agents.obsidian import FirefliesFilters, _filters_to_tool_args


class TestFirefliesFilters:
    def test_valid_construction(self):
        f = FirefliesFilters(from_date="2026-08-01", mine=True)
        assert f.from_date == "2026-08-01"
        assert f.mine is True

    def test_rejects_bad_scope(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(scope="invalid")

    def test_rejects_malformed_email(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(organizers=["not-an-email"])

    def test_defaults(self):
        f = FirefliesFilters()
        assert f.scope == "all"
        assert f.organizers == []
        assert f.participants == []


class TestFiltersToToolArgs:
    def test_maps_camel_case_fields(self):
        f = FirefliesFilters(from_date="2026-08-01", to_date="2026-08-31", channel_id="abc123")
        args = _filters_to_tool_args(f)
        assert args["fromDate"] == "2026-08-01"
        assert args["toDate"] == "2026-08-31"
        assert args["channelId"] == "abc123"

    def test_passthrough_fields_unchanged(self):
        f = FirefliesFilters(keyword="standup", scope="title", mine=True)
        args = _filters_to_tool_args(f)
        assert args["keyword"] == "standup"
        assert args["scope"] == "title"
        assert args["mine"] is True

    def test_unset_fields_omitted(self):
        args = _filters_to_tool_args(FirefliesFilters())
        assert "fromDate" not in args
        assert "channelId" not in args
        assert "organizers" not in args
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fireflies-mcp-improvements.spec.md` for full context.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the existing imports in `obsidian.py:11-22` haven't changed.
   - Confirm `pydantic.EmailStr` still raises `ImportError` before adding the dependency (sanity check the "Does NOT Exist" claim still holds).
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2346-fireflies-filters-model.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: claude-sonnet-5 (sdd-start session)
**Date**: 2026-08-22
**Notes**: Implemented `FirefliesFilters` (Pydantic model) and
`_filters_to_tool_args()` exactly per scope in
`packages/ai-parrot/src/parrot/agents/obsidian.py`. Added
`email-validator>=2.0` to `packages/ai-parrot/pyproject.toml` (verified
`EmailStr` raised `ImportError` before, works after `uv pip install
email-validator`). Added 10 new unit tests (`TestFirefliesFilters`,
`TestFiltersToToolArgs`) — all pass; full `test_obsidian.py` suite
(56 passed, 1 pre-existing skip) shows no regressions. Fixed only the
import-sort (`ruff --select I001 --fix`) introduced by my own new imports;
left all other pre-existing ruff findings in the file untouched (out of
this task's scope).

Environment note (not a scope deviation, but worth recording): this
worktree's shared `.venv` was missing two things unrelated to this task —
the compiled Cython extensions for `parrot.utils.types` /
`parrot.utils.parsers.toml` (copied the `.so` files from the main repo
checkout; both are gitignored build artifacts, not source changes) and the
optional `google-genai` package (installed via `uv pip install
google-genai`) which the test file's import chain needs transitively.
Neither was caused by this task; both were blocking collection of the
*entire* `test_obsidian.py` file, not just the new tests.

**Deviations from spec**: none.
