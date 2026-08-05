# TASK-2121: dev_flow package skeleton + models (DevRequestBrief, DevFlowBrief, IdeationOutput)

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: done
**Completed**: 2026-08-05
**Verification**: verified
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Root of the FEAT-412 dependency graph: every other task
consumes these Pydantic contracts. Creates the new sibling package
`parrot/flows/dev_flow/` (spec §2 Overview — deliberate separation of
concerns from the ops-oriented `dev_loop`; reuse happens by import).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_flow/__init__.py` with
  lazy-import hygiene mirroring `parrot/flows/dev_loop/__init__.py`.
- Implement `packages/ai-parrot/src/parrot/flows/dev_flow/models.py`:
  - `DevRequestKind = Literal["enhancement", "new_feature"]`
  - `DevRequestBrief` — `kind: DevRequestKind`, `title: str` (min_length 1,
    slug source), `description: str` (min_length 1, the NL request),
    `context: str = ""`, `jira_issue_key: Optional[str] = None`,
    `dev_agents: Optional[List[DevAgentSpec]] = None`,
    `judge_panel: Optional[JudgePanelConfig] = None` (spec §2 Data Models).
  - `DevFlowBrief = Annotated[Union[DevRequestBrief, FeatureBrief],
    Field(discriminator="kind")]`
  - `parse_dev_brief(raw: dict) -> DevRequestBrief | FeatureBrief` loader
    (mirror `parse_brief` in `dev_loop.models`).
  - `IdeationOutput` — `document_path: str`,
    `document_kind: Literal["brainstorm", "proposal"]`, `slug: str`,
    `resumed_existing: bool = False`, `open_questions: List[str] = []`,
    `summary: str = ""`, `committed: bool = False`.
- Write unit tests
  (`packages/ai-parrot/tests/flows/dev_flow/test_models.py` + package
  `__init__.py`/`conftest.py` as needed).

**NOT in scope**: nodes, gate-model changes, subagent prompt, topology,
runner, server, UI (TASK-2122…2131).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/__init__.py` | CREATE | Package init, lazy exports |
| `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` | CREATE | New models + union + loader |
| `packages/ai-parrot/tests/flows/dev_flow/__init__.py` | CREATE | Test package |
| `packages/ai-parrot/tests/flows/dev_flow/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# verified 2026-08-05 (models/__init__.py re-exports from models/base.py)
from parrot.flows.dev_loop.models import (
    FeatureBrief,        # models/base.py:725
    DevAgentSpec,
    JudgePanelConfig,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:725
class FeatureBrief(BaseModel):
    kind: Literal["feature"] = "feature"                       # :737
    document_path: str        # eager readability validator     # :738/:780
    document_kind: Literal["brainstorm", "proposal", "spec"]    # :747
    jira_issue_key: Optional[str] = None                        # :755
    dev_agents: Optional[List[DevAgentSpec]] = None             # :763
    judge_panel: Optional["JudgePanelConfig"] = None            # :771
```

Pattern reference: the `Brief = WorkBrief | FeatureBrief` discriminated
union + `parse_brief` already live in `dev_loop.models` (TASK-1918) —
mirror that construction for `DevFlowBrief`/`parse_dev_brief`.

### Does NOT Exist
- ~~`parrot/flows/dev_flow/`~~ — the package does not exist yet; this task
  creates it.
- ~~`DevRequestBrief` / `DevFlowBrief` / `IdeationOutput`~~ — new models.
- ~~`FeatureBrief.title` / `FeatureBrief.description`~~ — FeatureBrief is
  document-based; NL fields exist only on the new `DevRequestBrief`.

---

## Implementation Notes

### Key Constraints
- Pydantic v2, frozen where the dev_loop models are frozen; every field with
  a default so future additive evolution stays backward-compatible.
- `DevRequestBrief` needs NO document validators (there is no document yet);
  `FeatureBrief` keeps its own eager `document_path` validation.
- Google docstrings + strict type hints; no I/O in models.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` — model style
- `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` — lazy-import pattern

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_flow.models import DevRequestBrief, DevFlowBrief, IdeationOutput, parse_dev_brief` works
- [ ] Union discriminates: `parse_dev_brief({"kind": "feature", ...})` yields `FeatureBrief`; `"enhancement"`/`"new_feature"` yield `DevRequestBrief`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_models.py -v`
- [ ] `ruff check` clean on new files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_models.py
def test_dev_request_brief_requires_title_and_description(): ...
def test_dev_request_brief_kind_literal(): ...          # bug/feature rejected
def test_parse_dev_brief_discriminates_union(): ...     # 3 kinds
def test_parse_dev_brief_feature_passthrough(tmp_path): ...  # doc must exist
def test_ideation_output_defaults(): ...                # committed False, resumed False
def test_ideation_output_document_kind_literal(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

Created the `parrot.flows.dev_flow` package with the three FEAT-412 contracts:

- `models.py` — `DevRequestKind` Literal, `DevRequestBrief` (NL intake, no
  document validators, `title`/`description` `min_length=1`, optional
  `context`/`jira_issue_key`/`dev_agents`/`judge_panel`), the
  `DevFlowBrief` discriminated union on `kind`, `parse_dev_brief()` loader
  shim, and `IdeationOutput` (all optional fields defaulted).
- `__init__.py` — eager re-export of the light model contracts plus a
  `__getattr__`/`_LAZY_EXPORTS` hook so the heavier topology/runner symbols
  landing in TASK-2127/2128 can be resolved lazily without the package init
  importing aiohttp/redis/dispatcher machinery.
- 14 unit tests covering every case in the task's Test Specification plus
  union `TypeAdapter` validation and the package re-export surface.

Verified against the Codebase Contract before writing code: `FeatureBrief`
(`models/base.py:725`, eager `document_path` validator at :780),
`DevAgentSpec` (:388), `JudgePanelConfig` (:866), and the
`Brief`/`parse_brief` precedent (:984/:987) — all as documented.

Design note: `parse_dev_brief` deliberately **raises** on a missing/unknown
`kind` rather than defaulting. `parse_brief`'s `WorkBrief` fallback exists
only to preserve pre-FEAT-378 callers that omit `kind`; dev-flow has no such
legacy surface and the spec states the intent is always user-selected, so a
silent default would mask a UI/brief bug. Covered by
`test_parse_dev_brief_requires_explicit_kind`.

Validation: `pytest packages/ai-parrot/tests/flows/dev_flow/ -q` → 14 passed.
`ruff check` clean. `mypy` reports 0 errors in `dev_flow/` (the repo-wide
count comes from pre-existing errors in followed imports, unchanged by this
task).

**Deviations from spec**: none. `ruff --fix` normalized the spec's
`Optional[X]`/`List[X]`/`Union[...]` annotation style to PEP 604/585
(`X | None`, `list[X]`, `A | B`) per the project's lint config — a
cosmetic style change; field names, types and semantics are exactly as
specified.
