---
type: Wiki Overview
title: 'Brainstorm: Multi-Dispatcher Code Review Gate'
id: doc:sdd-proposals-new-codereviewers-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The dev-loop flow currently supports five code dispatchers for the Development
relates_to:
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

# Brainstorm: Multi-Dispatcher Code Review Gate

**Date**: 2026-07-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

**Who is affected**: DevOps engineers configuring the dev-loop server, and the
automated QA pipeline itself.

## Constraints & Requirements

- Must support the same `DevLoopCodeDispatcher` Protocol contract used by
  development dispatchers (structural compatibility).
- Code review dispatchers must be able to **fix** issues they discover (not
  read-only) and **commit** fixes to the worktree branch.
- QA flow becomes: `deterministic QA → code review + fix → re-run deterministic
  QA → pass/fail` (re-validation after fixes).
- Per-run dispatcher selection via a new `QANode` field, defaulting to
  `DEV_LOOP_CODEREVIEW_AGENT` env var (or `claude-code` if unset).
- An `AbstractCodeReviewDispatcher` ABC + `CodeReviewDispatcherFactory.create()`
  factory replaces the current direct `ClaudeCodeDispatcher` usage.
- Each code review dispatcher gets its own dispatch profile model.
- `LLMCodeDispatcher` and `GrokCodeDispatcher` are **excluded** from code review
  scope (only Claude, Codex, and Gemini).
- The `_CodeReviewVerdict` output model must be extended with severity levels,
  file references, and line numbers.
- Existing tests in `test_qa_codereview.py` must continue passing for the Claude
  path (backward compatibility).

---

## Options Explored

### Option A: ABC + Factory with Review-Aware Profile Models (Recommended)

Introduce `AbstractCodeReviewDispatcher` as a proper abstract base class that
wraps the underlying code dispatcher (Claude/Codex/Gemini) and adds
review-specific behavior: building the review prompt, enforcing the
`CodeReviewVerdict` output contract, and committing fixes. A
`CodeReviewDispatcherFactory.create(name)` factory instantiates the right
subclass. `QANode` receives a `codereview_dispatcher` field (typed as the ABC)
instead of reusing the shared `ClaudeCodeDispatcher`.

Each concrete reviewer (e.g. `ClaudeCodeReviewDispatcher`,
`CodexCodeReviewDispatcher`, `GeminiCodeReviewDispatcher`) owns its own profile
model that extends the development profile with review-specific fields
(e.g. `review_mode=True`, write permissions enabled, review-specific subagent
prompt).

The QA flow becomes a loop: `deterministic QA → code review + fix → re-run
deterministic QA`, where the code reviewer is allowed to edit, write, and commit
to the worktree branch. If the re-run fails, the QA node reports failure.

**Pros:**
- Clean separation: review dispatchers are not the same objects as development
  dispatchers — they wrap them with review-specific behavior.
- Factory pattern mirrors the existing `DEV_LOOP_DEVELOPMENT_AGENT` switch in
  `server.py` — familiar to contributors.
- Per-run selection via `QANode.codereview_agent` attribute allows flow-level
  override while defaulting to env config.
- ABC enforces the contract at class level rather than relying on duck typing.
- Each reviewer profile can tune sandbox/permission settings for write access
  without affecting the development profile.

**Cons:**
- More classes to maintain (3 concrete reviewers + ABC + factory + 3 profile
  models).
- The ABC adds a layer of indirection over the existing Protocol pattern used
  by development dispatchers — two patterns coexist.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `abc` (stdlib) | Abstract base class for `AbstractCodeReviewDispatcher` | Standard Python |
| `pydantic` | Profile models for each reviewer | Already used throughout |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` — all five dispatcher classes; `DevLoopCodeDispatcher` Protocol (line 124)
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — `QANode._run_code_review()` (line 224), `_CodeReviewVerdict` (line 72), `_CodeReviewBrief` (line 58)
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` — `ClaudeCodeDispatchProfile` (line 374), `CodexCodeDispatchProfile` (line 404), `GeminiCodeDispatchProfile` (line 433)
- `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` — `build_dev_loop_node_factories()` (line 40); pattern for injecting dispatchers into nodes
- `examples/dev_loop/server.py` — `_on_startup()` (line 445); dispatcher wiring + env var selection pattern

---

### Option B: Extend DevLoopCodeDispatcher Protocol with Review Methods

Instead of an ABC, extend the existing `DevLoopCodeDispatcher` Protocol with a
`review()` method and a `supports_review: bool` property. Each existing
dispatcher optionally implements `review()`. The factory becomes a simple
function that filters dispatchers by `supports_review` capability.

`QANode` receives a `codereview_dispatcher: DevLoopCodeDispatcher` (the same
Protocol type) and calls `dispatcher.review()` instead of
`dispatcher.dispatch()`.

**Pros:**
- No new class hierarchy — stays consistent with the Protocol pattern.
- Fewer files/classes to maintain.
- Dispatchers that support both development and review share instance state
  (e.g. Redis connection, concurrency semaphore).

**Cons:**
- Muddies the Protocol: `dispatch()` is for development, `review()` is for
  code review — the Protocol loses its clean single-responsibility.
- `LLMCodeDispatcher` and `GrokCodeDispatcher` would need stub
  `supports_review = False` implementations.
- Review-specific profile models still needed, but now they're coupled to the
  development dispatcher rather than cleanly separated.
- Harder to enforce the "review can fix + commit" behavior when the same object
  also serves as the read-only development dispatcher.

**Effort:** Low–Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `typing` (stdlib) | Extended Protocol definition | Already used |
| `pydantic` | Profile models | Already used |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` — `DevLoopCodeDispatcher` Protocol (line 124)
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — same as Option A

---

### Option C: Composition — ReviewDispatcherProxy Wrapping Any Dispatcher

Create a single `CodeReviewProxy` class (not an ABC) that wraps any
`DevLoopCodeDispatcher`-conforming dispatcher and adds review behavior. The
proxy translates a review brief into the dispatcher's `dispatch()` call with an
appropriate review profile, then extracts the `CodeReviewVerdict`.

Selection is done by passing the desired development dispatcher + a review
profile to the proxy. No factory needed — the proxy is the only class.

**Pros:**
- Minimal new code: one proxy class, one extended verdict model.
- Any future dispatcher automatically supports review if it conforms to the
  Protocol.
- No ABC/factory ceremony.

**Cons:**
- The proxy must know how to build the correct review profile for each
  dispatcher type — it becomes a switch statement internally, defeating the
  purpose of avoiding the factory.
- Review-specific subagent prompts (e.g. `sdd-codereview.md` for Claude vs.
  an AGENTS.md-based prompt for Codex) require dispatcher-specific handling
  that the proxy can't abstract away cleanly.
- Harder to test: the proxy's behavior depends on which dispatcher it wraps,
  so tests must cover every combination.
- The "fix + commit" behavior (write permissions, commit after review) must
  be configured per-dispatcher inside the proxy — complex branching logic.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Extended verdict model | Already used |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` — all dispatchers
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — `_run_code_review()` method

---

## Recommendation

**Option A** is recommended because:

- It provides a **clean architectural boundary** between development dispatchers
  and code review dispatchers. The ABC enforces that every reviewer implements
  the review contract (build prompt, dispatch, extract verdict, commit fixes)
  without polluting the development dispatcher interface.
- The **factory pattern** (`CodeReviewDispatcherFactory.create("codex")`) is
  already familiar from `server.py`'s `_on_startup` and mirrors how
  `DevelopmentNode` gets its dispatcher — contributors won't face a new pattern.
- Per-run selection via `QANode.codereview_agent` keeps the flow flexible
  without requiring server restarts.
- The "two patterns" con (ABC for review vs. Protocol for development) is
  acceptable because the two concerns are genuinely different: development
  dispatchers are general-purpose (any brief, any output model), while review
  dispatchers have a fixed contract (review brief in, verdict out, fix + commit).
  An ABC is the right tool for this narrower contract.

We trade off a few more classes for much cleaner separation, testability, and
extensibility.

---

## Feature Description

### User-Facing Behavior

Operators configure the code review dispatcher via:
- **Environment variable**: `DEV_LOOP_CODEREVIEW_AGENT=codex|gemini|claude-code`
  (defaults to `claude-code`).
- **Per-run override**: the flow context or a Jira ticket field can specify a
  different reviewer for individual runs.

When QA runs:
1. Deterministic acceptance criteria + lint execute as before.
2. The selected code reviewer dispatches, reviews the diff against acceptance
   criteria, fixes any issues it finds, and commits the fixes.
3. Deterministic QA re-runs to verify the fixes didn't break anything.
4. If re-run passes, QA passes. If re-run fails, QA fails.

The extended `CodeReviewVerdict` now includes per-finding severity, file path,
and line number, giving operators richer reporting.

### Internal Behavior

1. **Boot time** (`server.py._on_startup`):
   - Read `DEV_LOOP_CODEREVIEW_AGENT` env var.
   - Call `CodeReviewDispatcherFactory.create(agent_name, ...)` to instantiate
     the appropriate `AbstractCodeReviewDispatcher` subclass.
   - Pass it to `build_dev_loop_node_factories(codereview_dispatcher=...)`.
   - The QA factory binds it to `QANode(codereview_dispatcher=...)`.

2. **QA execution** (`QANode.execute`):
   - Run deterministic QA (unchanged).
   - Call `self._codereview_dispatcher.review(brief, run_id, node_id, cwd)`
     which internally:
     a. Builds a dispatcher-specific review profile (write-enabled).
     b. Calls the underlying dispatcher's `dispatch()` with the review
        subagent/prompt and `CodeReviewVerdict` as `output_model`.
     c. If the verdict has fixes, the subagent has already committed them.
   - Re-run deterministic QA on the (possibly modified) worktree.
   - Combine results: `passed = deterministic_passed AND cr_passed AND
     rerun_passed`.

3. **ABC contract** (`AbstractCodeReviewDispatcher`):
   - `async review(brief, run_id, node_id, cwd) -> CodeReviewVerdict`
   - `build_review_profile() -> BaseModel` (dispatcher-specific)
   - `agent_name: str` (class attribute for factory registration)

4. **Concrete reviewers**:
   - `ClaudeCodeReviewDispatcher`: wraps `ClaudeCodeDispatcher`, uses
     `sdd-codereview` subagent with `permission_mode="default"` (write-enabled),
     `allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"]`.
   - `CodexCodeReviewDispatcher`: wraps `CodexCodeDispatcher`, uses
     `codex exec` with `--sandbox=workspace-write` and
     `--approval-policy=auto-edit`.
   - `GeminiCodeReviewDispatcher`: wraps `GeminiCodeDispatcher`, uses
     `gemini` with `--sandbox=false` and `--approval-mode=auto_edit`.

### Edge Cases & Error Handling

- **Dispatcher infra error**: degrades to `(passed=True, findings=["code-review
  could not run: ..."])` — same as current FEAT-250 behavior. The deterministic
  gate is still the hard guarantee.
- **Re-run after fix fails**: QA reports `passed=False` with both the code
  review findings and the re-run failures. The `FailureHandlerNode` receives
  the full context.
- **Unknown dispatcher name**: `CodeReviewDispatcherFactory.create()` raises
  `ValueError` at boot time — fail fast, don't silently fall back.
- **Reviewer commits break the build**: the re-run deterministic QA catches this.
  The fix commit is already on the branch; the `FailureHandlerNode` or a
  subsequent revision can revert it.
- **No fixes needed**: reviewer returns `passed=True, findings=[]`. The re-run
  is skipped (no changes to validate).

---

## Capabilities

### New Capabilities
- `code-review-dispatcher-abc`: Abstract base class and factory for code review dispatchers
- `codex-code-reviewer`: Code review dispatcher using Codex CLI
- `gemini-code-reviewer`: Code review dispatcher using Gemini CLI
- `code-review-verdict-extended`: Extended verdict model with severity, file refs, line numbers
- `qa-review-fix-rerun`: QA flow with review-fix-rerun cycle

### Modified Capabilities
- `dev-loop-qa-node`: QANode accepts a `codereview_dispatcher` instead of hardcoded Claude
- `dev-loop-factories`: `build_dev_loop_node_factories` gains `codereview_dispatcher` param
- `dev-loop-server-wiring`: `server.py._on_startup` wires the code review dispatcher

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `flows/dev_loop/nodes/qa.py` | modifies | `QANode.__init__` accepts `AbstractCodeReviewDispatcher`; `_run_code_review` delegates to it; new re-run logic |
| `flows/dev_loop/dispatcher.py` | extends | New ABC, factory, and 3 concrete reviewer classes (or new module) |
| `flows/dev_loop/models.py` | extends | 3 new review profile models; extended `CodeReviewVerdict` |
| `flows/dev_loop/factories.py` | modifies | `build_dev_loop_node_factories` gains `codereview_dispatcher` param |
| `flows/dev_loop/flow.py` | modifies | `build_dev_loop_flow` passes `codereview_dispatcher` through |
| `flows/dev_loop/_subagent_data/sdd-codereview.md` | modifies | Remove read-only constraint, add fix+commit instructions |
| `examples/dev_loop/server.py` | modifies | Wire `DEV_LOOP_CODEREVIEW_AGENT` env var + factory call |
| `parrot/conf.py` | extends | New config var `DEV_LOOP_CODEREVIEW_AGENT` |
| `tests/flows/dev_loop/test_qa_codereview.py` | modifies | Tests for all 3 reviewer paths + re-run logic |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:124
class DevLoopCodeDispatcher(Protocol):
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str, node_id: str,
                       cwd: str) -> T: ...

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:145
class ClaudeCodeDispatcher:
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...
    async def dispatch(self, *, brief, profile: ClaudeCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:859
class CodexCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 codex_bin="codex") -> None: ...
    async def dispatch(self, *, brief, profile: CodexCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:1281
class GeminiCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 gemini_bin="gemini") -> None: ...
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd) -> T: ...

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:72
class _CodeReviewVerdict(BaseModel):
    passed: bool = True
    findings: List[str] = Field(default_factory=list)
    summary: str = ""

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:58
class _CodeReviewBrief(BaseModel):
    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""
    jira_issue_key: str = ""

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:86
class QANode(DevLoopNode):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 lint_command: Optional[str] = None,
                 codereview_model: Optional[str] = None,
                 name: str = "qa") -> None: ...
    async def execute(self, ctx, deps=None, **kwargs) -> QAReport: ...
    async def _run_code_review(self, shared, research, brief) -> tuple[bool, List[str]]: ...
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher  # dispatcher.py:145
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher   # dispatcher.py:859
from parrot.flows.dev_loop.dispatcher import GeminiCodeDispatcher  # dispatcher.py:1281
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher # dispatcher.py:124
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile # models.py:374
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile  # models.py:404
from parrot.flows.dev_loop.models import GeminiCodeDispatchProfile # models.py:433
from parrot.flows.dev_loop.models import QAReport                 # models.py
from parrot.flows.dev_loop.models import AcceptanceCriterion       # models.py
from parrot.flows.dev_loop.models import BugBrief                  # models.py
from parrot.flows.dev_loop.nodes.base import DevLoopNode           # nodes/base.py
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node # nodes/base.py:133
from parrot import conf                                            # conf.py
```

#### Key Attributes & Constants
- `conf.DEV_LOOP_CODEREVIEW_MODEL` → `str` (conf.py:899, default `"claude-sonnet-4-6"`)
- `_CODE_REVIEW_SKIP_PREFIX` → `str` (qa.py:40, `"code-review could not run:"`)
- `QANode._dispatcher` → `ClaudeCodeDispatcher` (qa.py:98)
- `QANode._codereview_model` → `str` (qa.py:102)

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractCodeReviewDispatcher`~~ — does not exist yet; this brainstorm proposes it
- ~~`CodeReviewDispatcherFactory`~~ — does not exist yet
- ~~`ClaudeCodeReviewDispatcher`~~ — does not exist yet
- ~~`CodexCodeReviewDispatcher`~~ — does not exist yet
- ~~`GeminiCodeReviewDispatcher`~~ — does not exist yet
- ~~`CodeReviewVerdict`~~ — does not exist as a public model; currently `_CodeReviewVerdict` is private to `qa.py`
- ~~`QANode.codereview_dispatcher`~~ — does not exist yet; currently `QANode._dispatcher` is a `ClaudeCodeDispatcher`
- ~~`DEV_LOOP_CODEREVIEW_AGENT`~~ — config var does not exist yet; only `DEV_LOOP_CODEREVIEW_MODEL` exists

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the ABC/factory (task 1), the three concrete
  reviewers (tasks 2–4), the extended verdict model (task 5), the QA re-run
  logic (task 6), and the server wiring (task 7) can be developed in parallel
  once the ABC interface is defined.
- **Cross-feature independence**: Touches `qa.py`, `dispatcher.py`, `models.py`,
  `factories.py`, `flow.py`, and `server.py` — all in `flows/dev_loop/`. No
  conflicts with in-flight specs unless another feature is also modifying
  `QANode`.
- **Recommended isolation**: `per-spec` — all tasks modify tightly coupled files
  within the same package; a single worktree avoids merge conflicts between
  the ABC definition and its consumers.
- **Rationale**: The ABC must be defined before concrete reviewers can be built,
  and the QA node modifications depend on the ABC interface. Sequential
  execution in one worktree is safest despite the parallelism potential of
  the concrete reviewers.

---

## Open Questions

- [ ] Should the code reviewer's commit message follow a specific convention (e.g. `codereview: fix <finding>`)? — *Owner: Jesus*
- [ ] Should the re-run of deterministic QA have a retry limit (e.g. max 1 review+fix cycle) to prevent infinite loops if the reviewer keeps introducing regressions? — *Owner: Jesus*
- [ ] Should the `CodeReviewVerdict.severity` field use an enum (`critical | major | minor | nit`) or free-form strings? — *Owner: Jesus*
- [ ] Do we need separate subagent prompt files for Codex and Gemini reviewers (like `sdd-codereview-codex.md`), or can the review instructions be embedded in the profile/prompt builder? — *Owner: Jesus*
