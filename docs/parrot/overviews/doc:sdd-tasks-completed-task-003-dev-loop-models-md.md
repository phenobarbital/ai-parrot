---
type: Wiki Overview
title: 'TASK-003: Dev-loop model additions (`RepoSpec`, `RevisionBrief`, QA/Research
  fields)'
id: doc:sdd-tasks-completed-task-003-dev-loop-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2 Data Models and Module 3. Foundational Pydantic contracts
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-003: Dev-loop model additions (`RepoSpec`, `RevisionBrief`, QA/Research fields)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2 Data Models and Module 3. Foundational Pydantic contracts
consumed by repo provisioning (TASK-006), the code-review gate (TASK-008),
the close node (TASK-009), and revision mode (TASK-012). All additions are
backward-compatible (new optional fields, defaulted).

---

## Scope

- Add `RepoSpec(BaseModel)`: `alias: str`, `url: str`, `branch: str = "main"`,
  `private: bool = False`.
- Add `RevisionBrief(BaseModel)`: `repo_path`, `branch`, `pr_number: int`,
  `repository`, `jira_issue_key`, `feedback`, `head_sha`.
- Extend `QAReport` with `code_review_passed: bool = True` and
  `code_review_findings: List[str] = Field(default_factory=list)`.
- Extend `ResearchOutput` with `repo_path: str = ""` (the clone Development cd's
  into; defaults empty for back-compat — keep existing `worktree_path`).
- Extend `ClaudeCodeDispatchProfile.subagent` Literal to include
  `"sdd-codereview"`.
- Unit tests.

**NOT in scope**: any node/flow logic; conf settings (TASK-004).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | Add models + fields |
| `packages/ai-parrot/tests/flows/dev_loop/test_models_feat250.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import (
    WorkBrief, BugBrief, ResearchOutput, DevelopmentOutput, QAReport,
    CriterionResult, ClaudeCodeDispatchProfile, LogSource,
)  # models.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class ResearchOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    jira_issue_key: str
    spec_path: str
    feat_id: str
    branch_name: str
    worktree_path: str
    log_excerpts: List[str] = Field(default_factory=list)

class QAReport(BaseModel):
    passed: bool
    criterion_results: List[CriterionResult]
    lint_passed: bool
    lint_output: str = ""
    notes: str = ""

class ClaudeCodeDispatchProfile(BaseModel):
    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa"]] = "sdd-worker"  # ← add "sdd-codereview"
    system_prompt_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Literal["default","acceptEdits","plan","bypassPermissions"] = "default"
    setting_sources: List[Literal["user","project","local"]] = Field(default_factory=lambda: ["project"])
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    model: str = "claude-sonnet-4-6"
```

### Does NOT Exist
- ~~`RepoSpec`, `RevisionBrief`~~ — this task creates them.
- ~~`QAReport.code_review_passed` / `code_review_findings`~~ — added here.
- ~~`ResearchOutput.repo_path`~~ — added here (do NOT remove `worktree_path`).

---

## Implementation Notes

### Key Constraints
- Pydantic v2; defaults must keep existing `QAReport(...)`/`ResearchOutput(...)`
  constructions valid (so add fields with defaults only).
- Do not break the `BugBrief = WorkBrief` alias.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` — match the file's existing model style.

---

## Acceptance Criteria

- [ ] `RepoSpec`/`RevisionBrief` validate and round-trip.
- [ ] `QAReport()` with no code-review fields defaults `code_review_passed=True`, `code_review_findings==[]`.
- [ ] `ResearchOutput(...)` without `repo_path` still validates (defaults `""`).
- [ ] `ClaudeCodeDispatchProfile(subagent="sdd-codereview")` validates.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_models_feat250.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models.py` clean.

---

## Test Specification
```python
from parrot.flows.dev_loop.models import RepoSpec, RevisionBrief, QAReport, ResearchOutput, ClaudeCodeDispatchProfile

def test_qareport_codereview_defaults():
    r = QAReport(passed=True, criterion_results=[], lint_passed=True)
    assert r.code_review_passed is True and r.code_review_findings == []

def test_repospec_defaults():
    s = RepoSpec(alias="nav", url="org/nav")
    assert s.branch == "main" and s.private is False

def test_profile_accepts_codereview():
    assert ClaudeCodeDispatchProfile(subagent="sdd-codereview").subagent == "sdd-codereview"
```

---

## Agent Instructions
Standard SDD lifecycle.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`dev_loop/models.py`)
- Added `RepoSpec(alias, url, branch="main", private=False)`.
- Added `RevisionBrief(repo_path, branch, pr_number, repository, jira_issue_key,
  feedback, head_sha)`.
- `QAReport` gained `code_review_passed: bool = True` and
  `code_review_findings: List[str] = []` (defaults keep legacy paths valid).
- `ResearchOutput` gained `repo_path: str = ""` (with `validation_alias` for
  `repo`/`clone_path`); `worktree_path` left untouched/required.
- `ClaudeCodeDispatchProfile.subagent` Literal widened to include
  `"sdd-codereview"`.

**Scope note**: per task file-fidelity, `dev_loop/__init__.py` was NOT modified
(not listed). Downstream tasks import the new models from
`parrot.flows.dev_loop.models` directly, as the Codebase Contract specifies.

**Verification**
- `pytest test_models_feat250.py` → 11 passed.
- Regression: `pytest -k model` (dev_loop) → 33 passed.
- `ruff check` clean on both files.
