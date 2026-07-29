---
type: Wiki Overview
title: 'TASK-1693: CodeReviewVerdict Extended Model + Review Profiles'
id: doc:sdd-tasks-completed-task-1693-extended-verdict-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from pydantic import BaseModel, Field # pydantic'
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-1693: CodeReviewVerdict Extended Model + Review Profiles

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1692
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec. It defines the public
> `CodeReviewVerdict` and `CodeReviewFinding` models in `models.py` (replacing
> the private `_CodeReviewVerdict` in `qa.py`), and adds the three
> review-specific dispatch profile models.

---

## Scope

- Add `CodeReviewFinding` Pydantic model to `models.py`:
  - `message: str`
  - `severity: Literal["critical", "major", "minor", "nit"]`
  - `file: str = ""`
  - `line: int = 0`
- Add `CodeReviewVerdict` Pydantic model to `models.py`:
  - `passed: bool = True`
  - `findings: List[CodeReviewFinding] = Field(default_factory=list)`
  - `summary: str = ""`
  - `files_modified: List[str] = Field(default_factory=list)`
- Add `ClaudeCodeReviewProfile` to `models.py`:
  - `subagent: str = "sdd-codereview"`
  - `permission_mode: Literal["default", "acceptEdits"] = "default"`
  - `allowed_tools: List[str]` (Read, Write, Edit, Bash, Grep, Glob)
  - `model: str = "claude-sonnet-4-6"`
  - `timeout_seconds: int`
- Add `CodexCodeReviewProfile` to `models.py`:
  - `subagent: str = "sdd-codereview"`
  - `model: str = "gpt-5.5"`
  - `sandbox: Literal["workspace-write"] = "workspace-write"`
  - `approval_policy: Literal["auto-edit", "on-request"] = "auto-edit"`
  - `timeout_seconds: int`
- Add `GeminiCodeReviewProfile` to `models.py`:
  - `subagent: str = "sdd-codereview"`
  - `model: str = "auto"`
  - `sandbox: bool = False`
  - `approval_mode: Literal["auto_edit", "yolo"] = "auto_edit"`
  - `timeout_seconds: int`
- Write unit tests for the new models.

**NOT in scope**: Removing `_CodeReviewVerdict` from `qa.py` (that happens in TASK-1697 when QANode is modified). Concrete dispatcher implementations (Tasks 1694–1696).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | Add 5 new models after existing profile models |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add model tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field                            # pydantic
from typing import List, Literal                                 # stdlib
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile  # models.py:374
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile   # models.py:404
from parrot.flows.dev_loop.models import GeminiCodeDispatchProfile  # models.py:433
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:374
class ClaudeCodeDispatchProfile(BaseModel):
    subagent: Optional[Literal[...]] = "sdd-worker"    # line 382
    permission_mode: Literal[...] = "default"          # line 385
    allowed_tools: List[str] = Field(default_factory=list)  # line 384
    model: str = "claude-sonnet-4-6"                   # line 401
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # line 400

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:404
class CodexCodeDispatchProfile(BaseModel):
    model: str = "gpt-5.5"                             # line 413
    sandbox: Literal[...] = "workspace-write"          # line 414
    approval_policy: Literal[...] = "never"            # line 415
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # line 416

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:433
class GeminiCodeDispatchProfile(BaseModel):
    model: str = "auto"                                # line 441
    sandbox: bool = True                               # line 442
    approval_mode: Literal[...] = "auto_edit"          # line 446
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # line 447

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:72
class _CodeReviewVerdict(BaseModel):
    passed: bool = True                                # line 80
    findings: List[str] = Field(default_factory=list)  # line 81
    summary: str = ""                                  # line 82
```

### Does NOT Exist
- ~~`CodeReviewFinding`~~ — this task creates it
- ~~`CodeReviewVerdict`~~ — this task creates it (public replacement for `_CodeReviewVerdict`)
- ~~`ClaudeCodeReviewProfile`~~ — this task creates it
- ~~`CodexCodeReviewProfile`~~ — this task creates it
- ~~`GeminiCodeReviewProfile`~~ — this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing profile model pattern from models.py:374+
# Each profile has: subagent, model, sandbox/permission settings, timeout
class ClaudeCodeReviewProfile(BaseModel):
    """Review profile for Claude Code dispatcher."""
    subagent: str = "sdd-codereview"
    # ... review-specific fields
```

### Key Constraints
- Place new models AFTER the existing `GrokCodeDispatchProfile` (line ~510) in `models.py`
- `CodeReviewVerdict` defaults must be backward-compatible with `_CodeReviewVerdict` (a verdict with no findings is a pass)
- `CodeReviewFinding.severity` uses `Literal["critical", "major", "minor", "nit"]` (enum-style via Literal)
- Review profiles are separate from development profiles — do NOT modify existing profiles

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:374-510` — existing profile models to mirror
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:72` — `_CodeReviewVerdict` being replaced

---

## Acceptance Criteria

- [ ] `CodeReviewFinding` has `message`, `severity`, `file`, `line` fields
- [ ] `CodeReviewFinding.severity` accepts only `"critical"`, `"major"`, `"minor"`, `"nit"`
- [ ] `CodeReviewVerdict` has `passed`, `findings`, `summary`, `files_modified` fields
- [ ] `CodeReviewVerdict` defaults match backward compatibility (empty = pass)
- [ ] `ClaudeCodeReviewProfile` has write-enabled tools and `permission_mode="default"`
- [ ] `CodexCodeReviewProfile` has `sandbox="workspace-write"` and `approval_policy="auto-edit"`
- [ ] `GeminiCodeReviewProfile` has `sandbox=False` and `approval_mode="auto_edit"`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models.py`
- [ ] Imports work: `from parrot.flows.dev_loop.models import CodeReviewVerdict, CodeReviewFinding`

---

## Test Specification

```python
import pytest
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,
    CodeReviewVerdict,
    ClaudeCodeReviewProfile,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
)


class TestCodeReviewFinding:
    def test_valid_finding(self):
        f = CodeReviewFinding(message="Missing guard", severity="critical",
                              file="sync.py", line=88)
        assert f.severity == "critical"
        assert f.file == "sync.py"
        assert f.line == 88

    def test_invalid_severity_rejected(self):
        with pytest.raises(Exception):
            CodeReviewFinding(message="x", severity="blocker")

    def test_defaults(self):
        f = CodeReviewFinding(message="x", severity="nit")
        assert f.file == ""
        assert f.line == 0


class TestCodeReviewVerdict:
    def test_default_is_pass(self):
        v = CodeReviewVerdict()
        assert v.passed is True
        assert v.findings == []
        assert v.files_modified == []

    def test_with_findings(self):
        f = CodeReviewFinding(message="issue", severity="major")
        v = CodeReviewVerdict(passed=False, findings=[f], summary="Has issues")
        assert not v.passed
        assert len(v.findings) == 1


class TestReviewProfiles:
    def test_claude_profile_has_write_tools(self):
        p = ClaudeCodeReviewProfile()
        assert "Edit" in p.allowed_tools
        assert "Write" in p.allowed_tools
        assert p.permission_mode == "default"

    def test_codex_profile_write_sandbox(self):
        p = CodexCodeReviewProfile()
        assert p.sandbox == "workspace-write"
        assert p.approval_policy == "auto-edit"

    def test_gemini_profile_no_sandbox(self):
        p = GeminiCodeReviewProfile()
        assert p.sandbox is False
        assert p.approval_mode == "auto_edit"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1692 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm existing profile models still exist at listed locations
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1693-extended-verdict-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `CodeReviewFinding`, `CodeReviewVerdict`, `ClaudeCodeReviewProfile`,
`CodexCodeReviewProfile`, `GeminiCodeReviewProfile` to `models.py`, placed
immediately after `GrokCodeDispatchProfile` and before `DispatchEvent`, per
the existing profile-model pattern. `_CodeReviewVerdict` in `qa.py` was left
untouched (its removal is scoped to TASK-1697). Added model unit tests to
`test_code_review.py` (finding validation, verdict defaults/backward
compat, profile field assertions). All 11 tests pass; `ruff check` clean.

**Deviations from spec**: none
