# TASK-4037: English and Spanish daily and roll-up rendering

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4031
**Assigned-to**: unassigned

---

## Context

Implement M5 render wording and static en/es headings. Required keys: title, plate, by_project, internal, since, hygiene and section labels. Daily format follows spec item line; only headings localize and source titles remain verbatim. Week/month use Closed this period/Still open/Decisions taken and cite daily source IDs. Omit empty projects and first-run delta; render Hygiene and diagnostics visibly. Escape markup where necessary without changing title text meaning. Keep fallback bullets <=3 and deterministic; no LLM or I/O here.

---

## Scope

Implement M5 render wording and static en/es headings. Required keys: title, plate, by_project, internal, since, hygiene and section labels. Daily format follows spec item line; only headings localize and source titles remain verbatim. Week/month use Closed this period/Still open/Decisions taken and cite daily source IDs. Omit empty projects and first-run delta; render Hygiene and diagnostics visibly. Escape markup where necessary without changing title text meaning. Keep fallback bullets <=3 and deterministic; no LLM or I/O here.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/render.py` | CREATE | Wording remains an explicitly bounded design decision; this is not a full delegation packet. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py` | CREATE | Keep expected Markdown literals in the test file for reviewable snapshots. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.standup.models import BriefDocument  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.render as subject  # planned in TASK-4037; not present before that task
```

### Existing Signatures to Use

No existing implementation symbol is required beyond the explicitly listed dependency contracts and installed libraries.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/render.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/render.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

TASK-4031: consumes BriefDocument

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/render.py` (CREATE)

```python
"""Pure localized Markdown rendering for daily and period briefs."""
from parrot.knowledge.wiki.standup.models import BriefDocument

HEADINGS: dict[str, dict[str, str]] = {
    "en": {"title": "Daily brief", "plate": "On your plate today", "by_project": "By project",
           "internal": "Internal", "since": "Since last brief", "hygiene": "Hygiene"},
    "es": {"title": "Resumen diario", "plate": "Tus pendientes de hoy", "by_project": "Por proyecto",
           "internal": "Interno", "since": "Desde el último resumen", "hygiene": "Higiene"},
}
# FILL IN: extend both tables with matching section and roll-up keys; AC6/AC12.

def render_markdown(doc: BriefDocument, language: str) -> str:
    """Render stable sections and source references, localizing headings only."""
    # FILL IN: daily/roll-up templates, empty/delta omission and Hygiene; AC6/10/12.
    raise NotImplementedError
```

**Why**: Wording remains an explicitly bounded design decision; this is not a full delegation packet.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.render as subject


def test_daily_en_es_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify daily en es golden."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_weekly_monthly_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify weekly monthly golden."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_empty_and_first_run_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify empty and first run sections."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Keep expected Markdown literals in the test file for reviewable snapshots.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/render.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Golden Markdown covers en/es daily and week/month roll-ups with stable links/qualified IDs.
- [ ] Empty and first-run sections are omitted; urgent items stay ordered and titles are not translated.
- [ ] No credentials, email or raw source bodies appear in generated output.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_render.py -q`

---

## Test Specification

- Golden Markdown covers en/es daily and week/month roll-ups with stable links/qualified IDs.
- Empty and first-run sections are omitted; urgent items stay ordered and titles are not translated.
- No credentials, email or raw source bodies appear in generated output.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4037`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
