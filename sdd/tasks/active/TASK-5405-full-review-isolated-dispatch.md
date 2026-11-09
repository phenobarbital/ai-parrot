# TASK-5405: Enforce read-only tool dispatch for isolated full reviews

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5404
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Implement _ask_llm_for_full_review using a new per-review Agent, ToolManager and client context through AbstractClient.
- Build an explicit audited read allowlist and enforce it at dispatch; do not reuse self.ask or the parent manager.
- Disable defaults, dynamic loading, arbitrary toolkit registration and shared client/tool mutation; clean up only review-owned resources.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Read-only isolated full-review execution |
| `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` | MODIFY | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from parrot.bots.agent import Agent
from parrot.tools.manager import ToolManager
from typing import Any, Dict
from parrot.bots.github_reviewer import GitHubReviewer
import pytest
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2372
async def _ask_llm_for_review(self, *, payload: Dict[str, Any], ticket_key: str, ticket: Dict[str, Any], diff_text: str, diff_truncated: bool, diff_available: bool, use_wiki: bool=True) -> PRReviewResult

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1296
def _attach_toolkit(self, toolkit: Any, name: str) -> None

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:134
def _read_only_excludes(toolkit_cls: type, keep: Sequence[str]) -> tuple[str, ...]

# packages/ai-parrot/src/parrot/bots/agent.py:86
def __init__(self, name: str='Agent', agent_id: str='agent', use_llm: str='google', llm: str=None, tools: List[AbstractTool]=None, system_prompt: str=None, human_prompt: str=None, use_tools: bool=True, instructions: Optional[str]=None, dataframes: Optional[Dict[str, pd.DataFrame]]=None, **kwargs)

# packages/ai-parrot/src/parrot/bots/agent.py:451
def _get_default_tools(self, tools: Optional[list], *, use_tools: bool=True) -> List[AbstractTool]

# packages/ai-parrot/src/parrot/bots/agent.py:1579
def agent_tools(self) -> List[AbstractTool]

# packages/ai-parrot/src/parrot/bots/base.py:1069
async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, a2ui_surface_state: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, system_prompt: Optional[str]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, use_tools: bool=True, trace_context=None, tenant: Optional[str]=None, **kwargs) -> AIMessage

# packages/ai-parrot/src/parrot/tools/manager.py:302
def __init__(self, logger: Optional[logging.Logger]=None, debug: bool=False, include_search_tool: bool=False, resolver: Optional['AbstractPermissionResolver']=None, execution_policy: Optional[Any]=None)

# packages/ai-parrot/src/parrot/tools/manager.py:856
def register_tool(self, tool: Union[dict, ToolDefinition, AbstractTool]=None, name: str=None, description: str=None, input_schema: Dict[str, Any]=None, function: Callable=None) -> None

# packages/ai-parrot/src/parrot/tools/manager.py:1419
def get_tools(self) -> Dict[str, Any]

# packages/ai-parrot/src/parrot/tools/manager.py:1799
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional['PermissionContext']=None, *, return_tool_result: bool=False) -> Any

# packages/ai-parrot/src/parrot/tools/manager.py:2419
async def execute_tool_call(self, content_block: Dict[str, Any], permission_context: Optional['PermissionContext']=None) -> Dict[str, Any]
```

### Does NOT Exist

- There is no existing isolated full-review dispatcher or FullReviewContext before TASK-5404.
- ToolManager.clone is not sufficient isolation: tools/owners may be shared. Hiding schemas is not a dispatch boundary.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._ask_llm_for_review",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._attach_toolkit",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#_read_only_excludes",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent._get_default_tools",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent.agent_tools",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.get_tools",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool_call"
  ]
}
```

## Implementation Notes

- Do not mock _ask_llm_for_full_review in the security regressions: drive a fake provider through the real dispatch path. Capture parent registry/client state before, during and after concurrent execution.
- The tool manager constructor defaults include_search_tool=False; keep that explicit. verify each selected callable and client factory at implementation time before registering it. No change to clients/base.py, bots/agent.py or tools/manager.py is authorized.

**Parallelism**: TASK-5404 creates FullReviewContext, FullPRReview and FullReviewLLMError; serialize overlapping github_reviewer.py and test_github_reviewer_pr_review.py writes.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

- Anchor `def _format_command_reply(`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:3433.

```python
# BEFORE _format_command_reply, inside GitHubReviewer:
async def _ask_llm_for_full_review(self, context: "FullReviewContext") -> FullPRReview:
    """Run an isolated read-only review and validate the structured result."""
    # FILL IN: AC1-AC5. Instantiate independent Agent/ToolManager/client context;
    # use_tools=False at construction suppresses BasicAgent._get_default_tools defaults.
    # Explicitly register only audited read callables, then enable those tools for ask.
    # Never register a whole toolkit, copy parent's manager or pass a shared client
    # whose registry can be mutated. Validate provider selection before construction.
    # Enforce the allowlist before actual execute_tool dispatch, including fabricated names.
    # Use structured_output=FullPRReview, max_iterations=self.max_full_review_tool_calls+1.
    # Validate output with FullPRReview.model_validate; wrap errors in FullReviewLLMError.
    # Resource cleanup owns only the isolated agent/client, never the borrowed toolkit.
    raise NotImplementedError
```

**Why**: Read-only isolated full-review execution. Implement _ask_llm_for_full_review using a new per-review Agent, ToolManager and client context through AbstractClient.

### `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` (MODIFY)

Created by TASK-5404; planned anchor `async def test_report_has_claude_headings_and_bot_tables() -> None:` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Enforce read-only tool dispatch for isolated full reviews."""
import pytest

async def test_full_review_dispatch_rejects_write_tools() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_full_review_tool_isolation_under_concurrency() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_full_review_llm_failure_writes_nothing() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Implement _ask_llm_for_full_review using a new per-review Agent, ToolManager and client context through AbstractClient.

### FILL IN checklist

- [ ] packages/ai-parrot/src/parrot/bots/github_reviewer.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.

## Acceptance Criteria

- [ ] AC1: Only explicitly audited non-mutating PR/file/comment and required Jira/wiki reads can dispatch.
- [ ] AC2: Fake provider calls to add_pr_comment, submit_pr_review, convert_pr_to_draft and unknown names are rejected by the actual dispatcher in dry-run and normal review.
- [ ] AC3: Concurrent strict/full reviews have distinct registries and clients; parent tool sets and strict/webhook write access remain unchanged.
- [ ] AC4: LLM uses structured_output=FullPRReview and max_iterations=max_full_review_tool_calls+1; malformed/missing output or any LLM/isolation failure raises FullReviewLLMError.
- [ ] AC5: Isolation failure closes owned resources and fails before LLM invocation; cleanup never closes borrowed toolkits.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_full_review_llm_failure_writes_nothing` | M7 | `_ask_llm_for_full_review` raises `FullReviewLLMError` → it propagates; no GitHub write |
| `test_full_review_dispatch_rejects_write_tools` | M7 | Fake provider requests each write tool and an unknown tool through the actual isolated dispatcher, then returns or raises; dry-run and normal full review perform no model-originated writes. Do not mock _ask_llm_for_full_review |
| `test_full_review_tool_isolation_under_concurrency` | M7 | Concurrent strict and full reviews keep separate tool sets; parent/shared client registry is unchanged, and only guarded caller code may write after validated full-review output |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5405`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
