---
type: Wiki Overview
title: 'TASK-1079: InspectorToolkit skeleton + Pydantic input schemas + filter builder'
id: doc:sdd-tasks-completed-task-1079-inspector-skeleton-and-schemas-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for FEAT-161. It creates the `InspectorToolkit`
  class skeleton, all Pydantic v2 input schemas, and the private `_build_filter_criteria()`
  helper that translates simple keyword arguments into the verbose `filterCriteria`
  dict consumed by `inspector2:Lis
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot_tools.aws.inspector
  rel: mentions
---

# TASK-1079: InspectorToolkit skeleton + Pydantic input schemas + filter builder

**Feature**: FEAT-161 — AWS Inspector Toolkit (Inspector2)
**Spec**: `sdd/specs/inspector-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-161. It creates the `InspectorToolkit` class skeleton, all Pydantic v2 input schemas, and the private `_build_filter_criteria()` helper that translates simple keyword arguments into the verbose `filterCriteria` dict consumed by `inspector2:ListFindings` and `inspector2:ListFindingAggregations`.

Implements Spec Module 1 (§3).

---

## Scope

- Create `inspector.py` with the `InspectorToolkit` class inheriting from `AbstractToolkit`.
- Implement the constructor matching `SecurityHubToolkit` verbatim: `__init__(self, aws_id, region_name, **kwargs)`.
- Define all 8 Pydantic v2 `BaseModel` input schemas from §2: `ListFindingsInput`, `AggregateFindingsInput`, `GetEcrImageFindingsInput`, `ListCoverageInput`, `GetSecurityPostureInput`, `ListTopVulnerableResourcesInput`, `CreateFindingsReportInput`, `CreateSbomExportInput`.
- Implement `_build_filter_criteria(**kwargs) -> Dict[str, Any]` private helper with the rules from §7: drop `None`/`"ALL"`, `EQUALS` for enums, `PREFIX` for repository names ending `*`, `CONTAINS` for `search_term`, map `status` → `findingStatus`.
- Add placeholder method stubs (just docstrings + `raise NotImplementedError`) for all 12 operations so the class is importable.
- Create the test file with unit tests for the filter builder.

**NOT in scope**: Actual AWS API call implementations (those are TASK-1080, 1081, 1082). Package wiring / `__init__.py` (TASK-1083).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py` | CREATE | Toolkit class, schemas, filter builder |
| `packages/ai-parrot-tools/tests/aws/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py` | CREATE | Unit tests for filter builder + class instantiation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
# Sibling toolkit uses relative imports (verified: securityhub.py:1-11)
from __future__ import annotations
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from parrot.interfaces.aws import AWSInterface          # verified: packages/ai-parrot/src/parrot/interfaces/aws.py:22
from ..decorators import tool_schema                     # verified: packages/ai-parrot/src/parrot/tools/decorators.py:37
from ..toolkit import AbstractToolkit                    # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:191
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/interfaces/aws.py:22
class AWSInterface:
    def __init__(self, aws_id: str = 'default', region_name: Optional[str] = None, credentials: Optional[Dict[str, Any]] = None, **kwargs): ...
    @asynccontextmanager
    async def client(self, service_name: str, **kwargs) -> AsyncIterator[Any]: ...

# packages/ai-parrot/src/parrot/tools/toolkit.py:191
class AbstractToolkit(ABC):
    exclude_tools: tuple[str, ...] = ()
    def __init__(self, **kwargs): ...
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...
    # auto-discovers public async methods; skips `_`-prefixed names and `exclude_tools` entries

# packages/ai-parrot/src/parrot/tools/decorators.py:37
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None): ...
    # Sets func._args_schema = schema; func._tool_description = description or func.__doc__

# packages/ai-parrot-tools/src/parrot_tools/aws/securityhub.py:55-75 — constructor pattern
class SecurityHubToolkit(AbstractToolkit):
    def __init__(self, aws_id: str = "default", region_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)
```

### Does NOT Exist

- ~~`parrot_tools/aws/inspector.py`~~ — does not exist; clean slate.
- ~~`InspectorToolkit`~~ — class does not yet exist anywhere.
- ~~`parrot_tools/aws/policies/`~~ — directory does not exist yet.
- ~~`AbstractToolkit.get_security_score`~~ — no base-class scoring helper.
- ~~`inspector` (v1) client~~ — deprecated; use `inspector2` exclusively.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow SecurityHubToolkit constructor exactly (securityhub.py:55-75):
class InspectorToolkit(AbstractToolkit):
    """Stateless toolkit wrapping Amazon Inspector v2 (inspector2)."""

    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)
```

### Filter Builder Behavior (§7)

`_build_filter_criteria(**kwargs) -> Dict[str, Any]`:
- Drop kwargs that are `None` or `"ALL"`.
- Translate enum-like kwargs (`severity`, `resource_type`, `status`, `fix_available`) → `{comparison: "EQUALS", value: ...}`.
- Map `status` kwarg to `findingStatus` key in the criteria dict.
- `repository_name` ending in `*` → `{comparison: "PREFIX", value: "..."}` (strip the `*`).
- `repository_name` without `*` → `{comparison: "EQUALS", value: "..."}`.
- `search_term` → added to `title` filter with `{comparison: "CONTAINS", value: "..."}`.

### Key Constraints

- All input schemas must use `pydantic.BaseModel` with `Field(...)` descriptors.
- `_build_filter_criteria` must be `_`-prefixed so `AbstractToolkit.get_tools()` auto-excludes it.
- Method stubs for all 12 operations: use `@tool_schema(InputModel)` decorator where applicable, `async def`, `Dict[str, Any]` return type.

---

## Acceptance Criteria

- [ ] `InspectorToolkit` class exists and is importable.
- [ ] Constructor matches SecurityHubToolkit pattern exactly.
- [ ] All 8 Pydantic input schemas are defined with correct fields and defaults per §2.
- [ ] `_build_filter_criteria` is private (`_`-prefixed) and handles: None/ALL dropping, EQUALS for enums, PREFIX for repo globs, CONTAINS for search_term, status→findingStatus mapping.
- [ ] 12 method stubs exist (decorated, async, correct naming).
- [ ] Unit tests for `_build_filter_criteria` pass: `pytest packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py -v -k "filter_criteria"`.
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py
import pytest
from parrot_tools.aws.inspector import InspectorToolkit


@pytest.fixture
def toolkit():
    return InspectorToolkit(aws_id="test", region_name="us-east-1")


class TestBuildFilterCriteria:
    def test_drops_none_and_all(self, toolkit):
        result = toolkit._build_filter_criteria(severity="ALL", resource_type=None)
        assert result == {}

    def test_enum_to_equals(self, toolkit):
        result = toolkit._build_filter_criteria(severity="CRITICAL")
        assert result["severity"] == [{"comparison": "EQUALS", "value": "CRITICAL"}]

    def test_search_term_contains(self, toolkit):
        result = toolkit._build_filter_criteria(search_term="CVE-2026")
        assert result["title"] == [{"comparison": "CONTAINS", "value": "CVE-2026"}]

    def test_repo_prefix_glob(self, toolkit):
        result = toolkit._build_filter_criteria(repository_name="prod-*")
        assert result["ecrImageRepositoryName"] == [{"comparison": "PREFIX", "value": "prod-"}]

    def test_repo_exact_match(self, toolkit):
        result = toolkit._build_filter_criteria(repository_name="my-repo")
        assert result["ecrImageRepositoryName"] == [{"comparison": "EQUALS", "value": "my-repo"}]

    def test_status_maps_to_finding_status(self, toolkit):
        result = toolkit._build_filter_criteria(status="ACTIVE")
        assert "findingStatus" in result
        assert "status" not in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/inspector-toolkit.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm every import still exists
4. **Update status** in `sdd/tasks/index/inspector-toolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1079-inspector-skeleton-and-schemas.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-12
**Notes**: Implemented InspectorToolkit class skeleton with all 8 Pydantic v2 input schemas,
`_build_filter_criteria()` private helper, `_normalize_finding()` private helper, and 12 method
stubs with proper `@tool_schema` decorators. Tests created for filter builder (11 tests, all passing)
and class instantiation (6 tests, all passing). Removed unused `logging` and `ClientError` imports
from skeleton (they will be added back in TASK-1080 when actual implementations are written).

**Deviations from spec**: `_normalize_finding` was added to the skeleton (instead of TASK-1080) since
the normalization logic is a private helper that logically belongs alongside `_build_filter_criteria`.
This simplifies TASK-1080 implementation and is within scope of a skeleton task.
