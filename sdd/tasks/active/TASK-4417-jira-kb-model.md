# TASK-4417: Jira Knowledge Base Model

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 6 — the KB data model, YAML load/save, lookup methods,
> and the merge logic for `sync-kb`. This is a root task with no dependencies;
> its `JiraKnowledgeBase` class is consumed by the parity-tools task (TASK-4420)
> and the CLI task (TASK-4422).

---

## Scope

- Create `jira_kb.py` with all Pydantic models (`IssueTypeEntry`, `ProjectEntry`,
  `PrioritiesEntry`, `LimitsEntry`, `TemplateEntry`, `JiraKnowledgeBase`).
- Implement `load()`, `save()`, `resolve_issue_type()`, `resolve_field()`,
  `status_category()`, `merge_generated()`.
- Write unit tests in `test_jira_kb.py`.

**NOT in scope**: integrating KB lookups into `jiratoolkit.py` methods (TASK-4420),
the `sync-kb` CLI command (TASK-4422), or any `jiratoolkit.py` edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jira_kb.py` | CREATE | KB model + lookups + merge |
| `packages/ai-parrot-tools/tests/unit/test_jira_kb.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/unit/fixtures/jira_kb_sample.yaml` | CREATE | Sample KB fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict                    # verified: pydantic v2 used throughout
import yaml                                                    # verified: PyYAML>=6.0.2 in packages/ai-parrot/pyproject.toml:58
import logging                                                 # stdlib
from pathlib import Path                                       # stdlib
```

### Existing Signatures to Use
```python
# No existing classes extended — this is a standalone module.
```

### Does NOT Exist
- ~~`ruamel.yaml`~~ — not a dependency; use PyYAML
- ~~`parrot_tools.jira_kb`~~ — does not exist yet; this task creates it
- ~~`python-dotenv`~~ — not a declared dependency

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_kb.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_kb.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/fixtures/jira_kb_sample.yaml",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Pydantic v2 `BaseModel` with `model_config = ConfigDict(extra="allow")` on the
  root model so user-added YAML keys survive round-trips.
- `yaml.safe_load` / `yaml.safe_dump` for I/O.

### Key Constraints
- `resolve_field(alias)` returns unknown aliases unchanged (pass-through).
- `merge_generated()` keeps curated sections (`status_map`, `templates`, `limits`,
  `priorities.legacy`, `priorities.default`, extra keys) from `self` and takes
  structural sections from `generated`.
- `save()` writes a header comment noting the file is generated.

---

## Implementation Blueprint

### Steps (in order)
1. Create `jira_kb_sample.yaml` fixture — *why*: tests need a real-shaped KB file.
2. Create `jira_kb.py` with all models and methods — *why*: this is the core deliverable.
3. Create `test_jira_kb.py` — *why*: validates load, resolve, merge, and limits.

### `packages/ai-parrot-tools/tests/unit/fixtures/jira_kb_sample.yaml` (CREATE)
```yaml
site: "https://acme.atlassian.net"
cloud_id: "abc-123"
verified: "2026-10-16"
projects:
  NAV:
    name: "Navigator"
    issue_types:
      Story:
        id: "10001"
        subtask: false
        level: 0
      Bug:
        id: "10004"
        subtask: false
        level: 0
      Sub-task:
        id: "10003"
        subtask: true
        level: 1
priorities:
  scale:
    - Highest
    - High
    - Medium
    - Low
    - Lowest
  legacy:
    - Critical
    - Blocker
  default: Medium
status_map:
  to_do:
    - Open
    - Reopened
  in_progress:
    - "In Progress"
    - "In Review"
  done:
    - Done
    - Closed
fields:
  team: "customfield_10001"
  sprint: "customfield_10020"
  story_points: "customfield_10028"
limits:
  summary_max_chars: 255
  description_max_chars: 32767
  summary_target_chars: 80
templates:
  bug_report:
    types:
      - Bug
    default: "bug_report"
components:
  - Backend
  - Frontend
  - DevOps
```
**Why this shape**: mirrors the proposal's example YAML and exercises every model field.

### `packages/ai-parrot-tools/src/parrot_tools/jira_kb.py` (CREATE)
```python
"""Jira site knowledge base — YAML-backed structural cache (FEAT-696 M6)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class IssueTypeEntry(BaseModel):
    """One issue type inside a project."""
    id: str
    subtask: bool = False
    level: int = 0


class ProjectEntry(BaseModel):
    """Project with its issue-type map."""
    name: str
    issue_types: dict[str, IssueTypeEntry] = {}


class PrioritiesEntry(BaseModel):
    """Priority scale plus legacy names."""
    scale: list[str] = []
    legacy: list[str] = []
    default: Optional[str] = None


class LimitsEntry(BaseModel):
    """Field length limits enforced before API calls."""
    description_max_chars: Optional[int] = None
    summary_max_chars: Optional[int] = None
    summary_target_chars: Optional[int] = None


class TemplateEntry(BaseModel):
    """Template → allowed issue types mapping."""
    types: list[str]
    default: str


class JiraKnowledgeBase(BaseModel):
    """Jira site structural cache loaded from a YAML file."""

    model_config = ConfigDict(extra="allow")

    site: str
    cloud_id: Optional[str] = None
    verified: Optional[str] = None
    projects: dict[str, ProjectEntry] = {}
    priorities: PrioritiesEntry = PrioritiesEntry()
    status_map: dict[str, list[str]] = {}
    fields: dict[str, str] = {}
    limits: LimitsEntry = LimitsEntry()
    templates: dict[str, TemplateEntry] = {}
    components: list[str] = []

    @classmethod
    def load(cls, path: Union[str, Path]) -> "JiraKnowledgeBase":
        """Load a KB from a YAML file."""
        p = Path(path)
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"KB file {p} does not contain a YAML mapping")
        return cls.model_validate(data)

    def save(self, path: Union[str, Path]) -> None:
        """Write the KB to a YAML file with an informational header."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="python", exclude_none=False)
        with p.open("w", encoding="utf-8") as fh:
            fh.write("# Jira knowledge base — generated by `parrot jiratoolkit sync-kb`.\n")
            fh.write("# Curated sections (status_map, templates, limits, priorities.legacy/default)\n")
            fh.write("# are preserved on re-sync. Inline YAML comments are NOT preserved.\n\n")
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def resolve_issue_type(self, project: str, name_or_id: str) -> Optional[IssueTypeEntry]:
        """Resolve an issue type by name or id within a project."""
        proj = self.projects.get(project)
        if proj is None:
            return None
        entry = proj.issue_types.get(name_or_id)
        if entry is not None:
            return entry
        for _name, ite in proj.issue_types.items():
            if ite.id == name_or_id:
                return ite
        return None

    def resolve_field(self, alias: str) -> str:
        """Return the Jira field id for an alias, or the alias unchanged."""
        return self.fields.get(alias, alias)

    def status_category(self, status: str) -> Optional[str]:
        """Return the category name for a status, or None."""
        # FILL IN: case-insensitive lookup across status_map values — bounded by spec §2 M6
        raise NotImplementedError

    def validate_limits(self, *, summary: Optional[str] = None, description: Optional[str] = None) -> None:
        """Raise ValueError if field lengths exceed KB limits."""
        # FILL IN: check summary/description against limits — bounded by AC8
        raise NotImplementedError

    def merge_generated(self, generated: "JiraKnowledgeBase") -> "JiraKnowledgeBase":
        """Merge structural sections from `generated` with curated sections from self."""
        # FILL IN: structural from generated (site, cloud_id, verified, projects.*.issue_types,
        #          priorities.scale, fields discovered, components);
        #          curated from self (status_map, templates, limits, priorities.legacy/default,
        #          extra keys, hand-edited field aliases whose ids still exist)
        #          — bounded by spec §2 M6 sync-kb behaviour
        raise NotImplementedError
```
**Why this shape**: matches spec §3 M6 interface skeleton exactly; `extra="allow"` preserves
user-added YAML keys; `FILL IN` stubs are bounded by spec sections.

### `packages/ai-parrot-tools/tests/unit/test_jira_kb.py` (CREATE)
```python
"""Tests for JiraKnowledgeBase (FEAT-696 M6)."""
from __future__ import annotations

import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestJiraKBLoad:
    def test_load_sample(self):
        """Loads the sample YAML fixture successfully."""
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        assert kb.site == "https://acme.atlassian.net"
        assert "NAV" in kb.projects
        assert kb.projects["NAV"].issue_types["Story"].id == "10001"

    def test_load_preserves_extra_keys(self):
        """Extra YAML keys survive via extra='allow'."""
        # FILL IN: write a tmp_path YAML with an extra key, load, check — bounded by spec extra="allow"
        pass


class TestResolve:
    def test_resolve_issue_type_by_name(self):
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        entry = kb.resolve_issue_type("NAV", "Story")
        assert entry is not None and entry.id == "10001"

    def test_resolve_issue_type_by_id(self):
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        entry = kb.resolve_issue_type("NAV", "10004")
        assert entry is not None

    def test_resolve_field_alias(self):
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        assert kb.resolve_field("team") == "customfield_10001"
        assert kb.resolve_field("unknown_field") == "unknown_field"

    def test_resolve_issue_type_missing(self):
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        assert kb.resolve_issue_type("NAV", "NonExistent") is None
        assert kb.resolve_issue_type("MISSING_PROJECT", "Story") is None


class TestStatusCategory:
    def test_status_category_found(self):
        # FILL IN: load KB, check status_category("Open") == "to_do" — bounded by spec §2 M6
        pass

    def test_status_category_missing(self):
        # FILL IN: load KB, check status_category("Unknown") is None — bounded by spec §2 M6
        pass


class TestLimits:
    def test_summary_over_limit_raises(self):
        # FILL IN: load KB, call validate_limits with oversized summary — bounded by AC8
        pass

    def test_within_limits_ok(self):
        # FILL IN: load KB, call validate_limits with valid lengths — bounded by AC8
        pass


class TestMergeGenerated:
    def test_merge_keeps_curated(self):
        # FILL IN: create two KBs, merge, verify curated sections kept — bounded by AC9
        pass

    def test_merge_updates_structural(self):
        # FILL IN: create two KBs, merge, verify structural sections updated — bounded by AC9
        pass


class TestSave:
    def test_save_roundtrip(self, tmp_path):
        from parrot_tools.jira_kb import JiraKnowledgeBase
        kb = JiraKnowledgeBase.load(FIXTURE_DIR / "jira_kb_sample.yaml")
        out = tmp_path / "out.yaml"
        kb.save(out)
        kb2 = JiraKnowledgeBase.load(out)
        assert kb2.site == kb.site
        assert kb2.projects == kb.projects
```
**Why this shape**: covers spec §4 test rows for M6: load, field alias, issue-type resolution,
limits, merge, and save round-trip.

### FILL IN checklist
- [ ] `jira_kb.py::JiraKnowledgeBase.status_category` — case-insensitive lookup; bounded by spec §2 M6
- [ ] `jira_kb.py::JiraKnowledgeBase.validate_limits` — summary/description length check; bounded by AC8
- [ ] `jira_kb.py::JiraKnowledgeBase.merge_generated` — structural vs curated merge; bounded by spec §2 M6 sync-kb rules
- [ ] `test_jira_kb.py::TestStatusCategory` — fill test bodies; bounded by spec §2 M6
- [ ] `test_jira_kb.py::TestLimits` — fill test bodies; bounded by AC8
- [ ] `test_jira_kb.py::TestMergeGenerated` — fill test bodies; bounded by AC9
- [ ] `test_jira_kb.py::TestJiraKBLoad.test_load_preserves_extra_keys` — fill body; bounded by extra="allow"

---

## Acceptance Criteria

- [ ] `JiraKnowledgeBase.load()` parses the sample YAML fixture
- [ ] `resolve_issue_type("NAV", "Story")` returns the entry with id `"10001"`
- [ ] `resolve_field("team")` returns `"customfield_10001"`; unknown alias returned unchanged
- [ ] `status_category("Open")` returns `"to_do"`; unknown status returns `None`
- [ ] `validate_limits(summary="x" * 256)` raises `ValueError` with the sample KB's 255-char limit
- [ ] `merge_generated()` keeps `status_map`, `templates`, `limits`, `priorities.legacy/default` from self
- [ ] `save()` + `load()` round-trips without data loss
- [ ] `ruff check` clean on new files
- [ ] No new third-party dependency added (AC11)

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_kb.py -q`

---

## Test Specification

See `test_jira_kb.py` in the Implementation Blueprint above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`)
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md` for full context
3. **Check dependencies** — this task has none; proceed immediately
4. **Verify the Codebase Contract** — confirm PyYAML is available
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — start from the Implementation Blueprint, complete FILL IN markers
7. **Verify** all acceptance criteria
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4417 jiratoolkit-upgrades verified`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
