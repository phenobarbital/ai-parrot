---
type: Wiki Overview
title: 'Feature Specification: Multi-Dispatcher Code Review Gate'
id: doc:sdd-specs-new-codereviewers-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The dev-loop flow currently supports five code dispatchers for the Development
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Multi-Dispatcher Code Review Gate

**Feature ID**: FEAT-270
**Date**: 2026-07-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop flow currently supports five code dispatchers for the Development
node (`ClaudeCodeDispatcher`, `CodexCodeDispatcher`, `GeminiCodeDispatcher`,
`LLMCodeDispatcher`, `GrokCodeDispatcher`), but the QA node's code-review gate
is hardcoded to `ClaudeCodeDispatcher`. This means:

- **No flexibility**: teams using Codex or Gemini for development cannot use the
  same tool for code review — they always fall back to Claude Code.
- **No cost optimization**: Claude Code may be overkill for review-only passes
  on simpler changes; cheaper models via Codex/Gemini could reduce cost.
- **No vendor parity**: the dispatcher selection pattern established for
  `DevelopmentNode` (env var + factory) is not replicated for the code-review
  gate, creating an inconsistency in the architecture.

### Goals
- Introduce an `AbstractCodeReviewDispatcher` ABC with a
  `CodeReviewDispatcherFactory.create(name)` factory to decouple code review
  from any specific dispatcher.
- Implement three concrete code review dispatchers: Claude, Codex, Gemini.
- Allow per-run code review dispatcher selection via a `QANode` attribute,
  defaulting to `DEV_LOOP_CODEREVIEW_AGENT` env var.
- Enable code reviewers to **fix** issues they discover and **commit** fixes to
  the worktree branch.
- Change the QA flow to: deterministic QA → code review + fix → re-run
  deterministic QA → pass/fail.
- Extend the `CodeReviewVerdict` model with severity levels, file references,
  and line numbers.

### Non-Goals (explicitly out of scope)
- `LLMCodeDispatcher`-based code reviewer — excluded by design (no CLI-based
  review sandbox available).
- `GrokCodeDispatcher`-based code reviewer — excluded (inherits LLM limitation).
- Changing the development dispatcher architecture or `DevLoopCodeDispatcher`
  Protocol — this feature only adds the review layer.
- Runtime fallback-on-failure between review dispatchers (e.g., if Codex review
  fails, fall back to Claude) — see `proposals/new-codereviewers.brainstorm.md`
  Option C for the rejected proxy approach.

---

## 2. Architectural Design

### Overview

Introduce `AbstractCodeReviewDispatcher` as an abstract base class that wraps
an underlying code dispatcher (Claude/Codex/Gemini) and adds review-specific
behavior: building the review prompt, enforcing the `CodeReviewVerdict` output
contract, and committing fixes. A `CodeReviewDispatcherFactory.create(name)`
factory instantiates the right subclass.

`QANode` receives a `codereview_dispatcher` field (typed as the ABC) instead of
reusing the shared `ClaudeCodeDispatcher`. Each concrete reviewer
(`ClaudeCodeReviewDispatcher`, `CodexCodeReviewDispatcher`,
`GeminiCodeReviewDispatcher`) owns its own profile model that extends the
development profile with review-specific fields (write permissions enabled,
review-specific subagent prompt).

The QA flow becomes a loop: deterministic QA → code review + fix → re-run
deterministic QA. The code reviewer is allowed to edit, write, and commit to the
worktree branch. If the re-run fails, the QA node reports failure.

### Component Diagram
```
                         CodeReviewDispatcherFactory.create(name)
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                  ▼
      ClaudeCodeReview    CodexCodeReview    GeminiCodeReview
      Dispatcher          Dispatcher         Dispatcher
           │                   │                  │
           ▼                   ▼                  ▼
      ClaudeCode          CodexCode          GeminiCode
      Dispatcher          Dispatcher         Dispatcher
      (existing)          (existing)         (existing)

  All three inherit from AbstractCodeReviewDispatcher (ABC)
  and delegate to the corresponding development dispatcher's dispatch() method.

  QA Node Flow:
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────┐
  │ Deterministic │──►│ Code Review  │──►│ Re-run       │──►│ Pass │
  │ QA (AC+lint)  │    │ + Fix+Commit │    │ Determ. QA   │    │/Fail │
  └──────────────┘    └──────────────┘    └──────────────┘    └──────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `QANode` (qa.py:86) | modifies | Accepts `AbstractCodeReviewDispatcher` instead of `ClaudeCodeDispatcher`; new re-run loop |
| `ClaudeCodeDispatcher` (dispatcher.py:145) | wraps | `ClaudeCodeReviewDispatcher` delegates to it |
| `CodexCodeDispatcher` (dispatcher.py:859) | wraps | `CodexCodeReviewDispatcher` delegates to it |
| `GeminiCodeDispatcher` (dispatcher.py:1281) | wraps | `GeminiCodeReviewDispatcher` delegates to it |
| `build_dev_loop_node_factories` (factories.py:40) | modifies | New `codereview_dispatcher` param |
| `build_dev_loop_flow` (flow.py:159) | modifies | Passes `codereview_dispatcher` through |
| `_on_startup` (server.py:445) | modifies | Reads `DEV_LOOP_CODEREVIEW_AGENT`, creates reviewer via factory |
| `conf.py` (line 899) | extends | New `DEV_LOOP_CODEREVIEW_AGENT` config var |

### Data Models

```python
class CodeReviewFinding(BaseModel):
    """A single finding from the code review."""
    message: str
    severity: Literal["critical", "major", "minor", "nit"]
    file: str = ""
    line: int = 0

class CodeReviewVerdict(BaseModel):
    """Extended verdict emitted by all code review dispatchers."""
    passed: bool = True
    findings: List[CodeReviewFinding] = Field(default_factory=list)
    summary: str = ""
    files_modified: List[str] = Field(default_factory=list)

class ClaudeCodeReviewProfile(BaseModel):
    """Review profile for Claude Code dispatcher."""
    subagent: str = "sdd-codereview"
    permission_mode: Literal["default", "acceptEdits"] = "default"
    allowed_tools: List[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
    )
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

class CodexCodeReviewProfile(BaseModel):
    """Review profile for Codex dispatcher."""
    subagent: str = "sdd-codereview"
    model: str = "gpt-5.5"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["auto-edit", "on-request"] = "auto-edit"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

class GeminiCodeReviewProfile(BaseModel):
    """Review profile for Gemini dispatcher."""
    subagent: str = "sdd-codereview"
    model: str = "auto"
    sandbox: bool = False
    approval_mode: Literal["auto_edit", "yolo"] = "auto_edit"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
```

### New Public Interfaces

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type

class AbstractCodeReviewDispatcher(ABC):
    """ABC for all code review dispatchers."""

    agent_name: str  # class attribute, e.g. "claude-code", "codex", "gemini"

    @abstractmethod
    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> CodeReviewVerdict:
        """Run code review, optionally fix issues, return verdict."""

    @abstractmethod
    def build_review_profile(self) -> BaseModel:
        """Return the dispatcher-specific review profile."""


class CodeReviewDispatcherFactory:
    """Factory for creating code review dispatchers."""

    _registry: dict[str, Type[AbstractCodeReviewDispatcher]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a code review dispatcher."""
        def decorator(klass):
            cls._registry[name] = klass
            return klass
        return decorator

    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher:
        """Create a code review dispatcher by name."""
        if name not in cls._registry:
            raise ValueError(
                f"Unknown code review dispatcher: {name!r}. "
                f"Available: {sorted(cls._registry)}"
            )
        return cls._registry[name](**kwargs)
```

---

## 3. Module Breakdown

### Module 1: AbstractCodeReviewDispatcher ABC + Factory
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- **Responsibility**: Define the `AbstractCodeReviewDispatcher` ABC, the
  `CodeReviewDispatcherFactory`, and the `CodeReviewVerdict` /
  `CodeReviewFinding` models. The ABC enforces the `review()` and
  `build_review_profile()` contract. The factory uses a class-level registry
  with a `@register` decorator.
- **Depends on**: `pydantic`, `abc` (stdlib)

### Module 2: CodeReviewVerdict Extended Model
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` (extend)
- **Responsibility**: Add `CodeReviewFinding` and `CodeReviewVerdict` to the
  public models module. Move the private `_CodeReviewVerdict` replacement here.
  Add the three review profile models (`ClaudeCodeReviewProfile`,
  `CodexCodeReviewProfile`, `GeminiCodeReviewProfile`).
- **Depends on**: Module 1

### Module 3: ClaudeCodeReviewDispatcher
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- **Responsibility**: Wrap `ClaudeCodeDispatcher` with write-enabled review
  profile (`permission_mode="default"`, full tool list). Use `sdd-codereview`
  subagent with updated prompt that allows fixes + commits.
- **Depends on**: Module 1, `ClaudeCodeDispatcher`

### Module 4: CodexCodeReviewDispatcher
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- **Responsibility**: Wrap `CodexCodeDispatcher` with
  `sandbox="workspace-write"` and `approval_policy="auto-edit"`. Load the
  review prompt as the Codex system instruction.
- **Depends on**: Module 1, `CodexCodeDispatcher`

### Module 5: GeminiCodeReviewDispatcher
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- **Responsibility**: Wrap `GeminiCodeDispatcher` with `sandbox=False` and
  `approval_mode="auto_edit"`. Load the review prompt as the Gemini system
  instruction.
- **Depends on**: Module 1, `GeminiCodeDispatcher`

### Module 6: QANode Review-Fix-Rerun Loop
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (modify)
- **Responsibility**: Replace the hardcoded `ClaudeCodeDispatcher` usage in
  `_run_code_review()` with delegation to `AbstractCodeReviewDispatcher.review()`.
  Add the re-run loop: after code review fixes, re-dispatch the deterministic QA
  pass. Accept `codereview_dispatcher` in `__init__` (new param).
- **Depends on**: Modules 1–5

### Module 7: Factory Wiring + Server Bootstrap
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` (modify),
  `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` (modify),
  `examples/dev_loop/server.py` (modify),
  `packages/ai-parrot/src/parrot/conf.py` (extend)
- **Responsibility**: Thread the `codereview_dispatcher` through
  `build_dev_loop_node_factories()` → `build_dev_loop_flow()` → `_on_startup()`.
  Add `DEV_LOOP_CODEREVIEW_AGENT` config var. Wire the factory call in
  `_on_startup`.
- **Depends on**: Modules 1–6

### Module 8: Updated sdd-codereview Subagent Prompt
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` (modify)
- **Responsibility**: Remove the read-only constraint. Add instructions for
  fixing issues (Edit/Write tools), committing fixes to the worktree branch,
  and reporting modified files in the verdict.
- **Depends on**: None (can be done independently)

### Module 9: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` (new),
  `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` (modify)
- **Responsibility**: Unit tests for the ABC, factory, each concrete reviewer,
  the extended verdict model, and the QA re-run loop. Existing Claude-path tests
  in `test_qa_codereview.py` must continue passing.
- **Depends on**: Modules 1–7

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_factory_create_claude` | 1 | Factory creates `ClaudeCodeReviewDispatcher` for `"claude-code"` |
| `test_factory_create_codex` | 1 | Factory creates `CodexCodeReviewDispatcher` for `"codex"` |
| `test_factory_create_gemini` | 1 | Factory creates `GeminiCodeReviewDispatcher` for `"gemini"` |
| `test_factory_unknown_raises` | 1 | Factory raises `ValueError` for unknown name |
| `test_verdict_finding_fields` | 2 | `CodeReviewFinding` accepts severity, file, line |
| `test_verdict_backward_compat` | 2 | `CodeReviewVerdict` defaults match old `_CodeReviewVerdict` |
| `test_claude_review_dispatch` | 3 | `ClaudeCodeReviewDispatcher.review()` delegates with write profile |
| `test_claude_review_profile` | 3 | Profile has `permission_mode="default"`, write tools |
| `test_codex_review_dispatch` | 4 | `CodexCodeReviewDispatcher.review()` delegates with write sandbox |
| `test_codex_review_profile` | 4 | Profile has `sandbox="workspace-write"`, `approval_policy="auto-edit"` |
| `test_gemini_review_dispatch` | 5 | `GeminiCodeReviewDispatcher.review()` delegates with no sandbox |
| `test_gemini_review_profile` | 5 | Profile has `sandbox=False`, `approval_mode="auto_edit"` |
| `test_qa_rerun_on_fix` | 6 | QA re-runs deterministic gate after reviewer commits fixes |
| `test_qa_skip_rerun_no_fix` | 6 | QA skips re-run when reviewer finds no issues |
| `test_qa_rerun_fails` | 6 | QA reports failure when re-run fails after fix |
| `test_qa_degrade_on_infra_error` | 6 | Infra error degrades to pass (existing behavior preserved) |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_qa_flow_claude_review` | End-to-end QA with Claude reviewer: determ → review → fix → rerun |
| `test_full_qa_flow_codex_review` | End-to-end QA with Codex reviewer (mocked CLI) |
| `test_server_wiring_codereview_agent` | `DEV_LOOP_CODEREVIEW_AGENT` env var creates correct reviewer |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_claude_dispatcher():
    """Mock ClaudeCodeDispatcher for unit tests."""
    ...

@pytest.fixture
def mock_codex_dispatcher():
    """Mock CodexCodeDispatcher for unit tests."""
    ...

@pytest.fixture
def sample_review_brief():
    """A CodeReviewBrief with acceptance criteria."""
    return _CodeReviewBrief(
        acceptance_criteria=[...],
        worktree_path="/tmp/test-worktree",
        summary="Fix null row handling",
        jira_issue_key="OPS-123",
    )

@pytest.fixture
def sample_verdict_with_findings():
    """A CodeReviewVerdict with mixed severity findings."""
    return CodeReviewVerdict(
        passed=False,
        findings=[
            CodeReviewFinding(message="Missing null guard", severity="critical",
                              file="sync.py", line=88),
            CodeReviewFinding(message="Consider logging", severity="nit",
                              file="sync.py", line=92),
        ],
        summary="Critical null guard missing.",
    )
```

---

## 5. Acceptance Criteria

- [ ] `AbstractCodeReviewDispatcher` ABC exists with `review()` and `build_review_profile()` abstract methods
- [ ] `CodeReviewDispatcherFactory.create(name)` returns the correct dispatcher for `"claude-code"`, `"codex"`, `"gemini"`
- [ ] `CodeReviewDispatcherFactory.create("unknown")` raises `ValueError`
- [ ] `ClaudeCodeReviewDispatcher` dispatches with write-enabled profile (`permission_mode="default"`, `allowed_tools` includes `Edit`/`Write`)
- [ ] `CodexCodeReviewDispatcher` dispatches with `sandbox="workspace-write"` and `approval_policy="auto-edit"`
- [ ] `GeminiCodeReviewDispatcher` dispatches with `sandbox=False` and `approval_mode="auto_edit"`
- [ ] `CodeReviewVerdict` includes `findings: List[CodeReviewFinding]` with `severity`, `file`, `line` fields
- [ ] `QANode` accepts `codereview_dispatcher: AbstractCodeReviewDispatcher` in `__init__`
- [ ] QA flow executes: deterministic QA → code review + fix → re-run deterministic QA
- [ ] QA skips re-run when code review returns `passed=True` with no fixes
- [ ] QA reports failure when re-run of deterministic QA fails after reviewer fixes
- [ ] Infra error in code review degrades to pass (existing FEAT-250 behavior preserved)
- [ ] `DEV_LOOP_CODEREVIEW_AGENT` config var selects the review dispatcher at boot
- [ ] `sdd-codereview.md` subagent prompt allows Edit/Write and instructs commit of fixes
- [ ] All existing tests in `test_qa_codereview.py` continue passing
- [ ] All new unit tests pass: `pytest tests/flows/dev_loop/test_code_review.py -v`
- [ ] No breaking changes to existing `QANode` public API (backward compatible constructor)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher    # dispatcher.py:145
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher     # dispatcher.py:859
from parrot.flows.dev_loop.dispatcher import GeminiCodeDispatcher    # dispatcher.py:1281
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher   # dispatcher.py:124
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile   # models.py:374
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile    # models.py:404
from parrot.flows.dev_loop.models import GeminiCodeDispatchProfile   # models.py:433
from parrot.flows.dev_loop.models import QAReport                   # models.py
from parrot.flows.dev_loop.models import AcceptanceCriterion         # models.py
from parrot.flows.dev_loop.models import BugBrief                   # models.py
from parrot.flows.dev_loop.nodes.base import DevLoopNode             # nodes/base.py
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node  # nodes/base.py:133
from parrot import conf                                              # conf.py
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:124
class DevLoopCodeDispatcher(Protocol):
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str, node_id: str,
                       cwd: str) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:145
class ClaudeCodeDispatcher:
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...
    async def dispatch(self, *, brief, profile: ClaudeCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:859
class CodexCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 codex_bin="codex") -> None: ...
    async def dispatch(self, *, brief, profile: CodexCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:1281
class GeminiCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 gemini_bin="gemini") -> None: ...
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:72
class _CodeReviewVerdict(BaseModel):
    passed: bool = True                              # line 80
    findings: List[str] = Field(default_factory=list) # line 81
    summary: str = ""                                 # line 82

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:58
class _CodeReviewBrief(BaseModel):
    acceptance_criteria: List[AcceptanceCriterion]     # line 66
    worktree_path: str                                 # line 67
    summary: str = ""                                  # line 68
    jira_issue_key: str = ""                           # line 69

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:86
class QANode(DevLoopNode):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 lint_command: Optional[str] = None,
                 codereview_model: Optional[str] = None,
                 name: str = "qa") -> None: ...       # line 89
    async def execute(self, ctx, deps=None, **kwargs) -> QAReport: ...  # line 110
    async def _run_code_review(self, shared, research, brief
                               ) -> tuple[bool, List[str]]: ...  # line 224

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:374
class ClaudeCodeDispatchProfile(BaseModel):
    subagent: Optional[Literal["sdd-research", "sdd-worker",
              "sdd-qa", "sdd-codereview"]] = "sdd-worker"  # line 382
    permission_mode: Literal["default", "acceptEdits",
                     "plan", "bypassPermissions"] = "default"  # line 385
    allowed_tools: List[str] = Field(default_factory=list)     # line 384
    model: str = "claude-sonnet-4-6"                           # line 401

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:404
class CodexCodeDispatchProfile(BaseModel):
    subagent: Literal["sdd-worker"] = "sdd-worker"             # line 412
    model: str = "gpt-5.5"                                     # line 413
    sandbox: Literal["read-only", "workspace-write",
             "danger-full-access"] = "workspace-write"         # line 414
    approval_policy: Literal["untrusted", "on-request",
                     "never"] = "never"                        # line 415

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:433
class GeminiCodeDispatchProfile(BaseModel):
    subagent: Literal["sdd-worker"] = "sdd-worker"             # line 440
    model: str = "auto"                                        # line 441
    sandbox: bool = True                                       # line 442
    approval_mode: Literal["default", "auto_edit",
                   "yolo", "plan"] = "auto_edit"               # line 446

# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py:40
def build_dev_loop_node_factories(
    *, dispatcher, jira_toolkit, redis_url,
    development_dispatcher=None, development_profile=None,
    git_toolkit=None, log_toolkits=None, repos=None,
) -> Dict[str, NodeFactory]: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:159
def build_dev_loop_flow(
    *, dispatcher: ClaudeCodeDispatcher, jira_toolkit, log_toolkits,
    redis_url, name="dev-loop", publish_flow_events=True,
    lifecycle_events=True, development_dispatcher=None,
    development_profile=None, git_toolkit=None, repos=None,
) -> AgentsFlow: ...
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractCodeReviewDispatcher` | `DevLoopCodeDispatcher` | delegates `dispatch()` call | `dispatcher.py:124` |
| `ClaudeCodeReviewDispatcher` | `ClaudeCodeDispatcher.dispatch()` | wraps with review profile | `dispatcher.py:145` |
| `CodexCodeReviewDispatcher` | `CodexCodeDispatcher.dispatch()` | wraps with review profile | `dispatcher.py:859` |
| `GeminiCodeReviewDispatcher` | `GeminiCodeDispatcher.dispatch()` | wraps with review profile | `dispatcher.py:1281` |
| `QANode` (modified) | `AbstractCodeReviewDispatcher.review()` | replaces `_run_code_review` | `qa.py:224` |

…(truncated)…
