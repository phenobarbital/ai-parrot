# TASK-881: `ResearchNode` — Jira ticket + log fetch + sdd-research dispatch

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-874, TASK-878
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** from spec §3. The most complex node before
Development. Sequence:

1. Fetch logs via `CloudWatchToolkit` and/or `ElasticsearchTool` for
   each `LogSource`.
2. Create the Jira ticket via `jira_toolkit.jira_create_issue(...)`
   — reporter remains the original human, assignee is the bot.
3. Dispatch to the `sdd-research` subagent. The subagent runs
   `/sdd-spec` and `/sdd-task` inside a worktree it creates.
4. Validate dispatch output as `ResearchOutput` (TASK-874).

Spec acceptance criterion: "ResearchNode creates the Jira ticket BEFORE
dispatching (verified by mock call ordering)."

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/research.py`:
  - `class ResearchNode(Node)`.
  - `__init__(*, dispatcher, jira_toolkit, log_toolkits: dict, ...)`.
  - `async def execute(self, prompt, ctx) -> ResearchOutput`.
- Detect duplicate worktree (spec §7 R5): if
  `WORKTREE_BASE_PATH/feat-<id>-<slug>` already exists, raise
  `RuntimeError` with a clear message instructing the human to clean
  up. Do NOT auto-recover.
- The dispatcher call MUST come AFTER `jira_create_issue` returns. The
  test pins this with a mock-call-order assertion.
- The dispatched prompt is built from `BugBrief` + collected log
  excerpts. Embed the Jira issue key returned by step 2 so the
  subagent can attach the spec link to the ticket.

**NOT in scope**:
- The dispatcher itself (TASK-878).
- The flow wiring (TASK-886).
- Webhook-driven worktree cleanup (TASK-887).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | CREATE | `ResearchNode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_research.py` | CREATE | Unit tests with mocked toolkits + dispatcher. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import logging
import os
from typing import Any, Dict, List

from parrot.bots.flow.node import Node                       # node.py:14
from parrot.flows.dev_loop.models import (
    BugBrief, ClaudeCodeDispatchProfile, LogSource, ResearchOutput,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.conf import WORKTREE_BASE_PATH

from parrot_tools.jiratoolkit import JiraToolkit              # jiratoolkit.py:609
from parrot_tools.elasticsearch import ElasticsearchTool      # elasticsearch.py:167
from parrot_tools.aws.cloudwatch import CloudWatchToolkit     # aws/cloudwatch.py:168
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                           # line 609
    async def jira_create_issue(self, ...): ...               # line 1366
    # NB: verify exact arg names (project_key, summary, description,
    # issue_type, reporter, assignee) by reading lines 1366-1450 before
    # implementing. The spec mentions these but does not pin the
    # signature.

# packages/ai-parrot-tools/src/parrot_tools/aws/cloudwatch.py
class CloudWatchToolkit(AbstractToolkit):                     # line 168
    # Has tools for log-group querying — verify exact public method
    # name (likely `query_logs` or `get_log_events`) before use.

# packages/ai-parrot-tools/src/parrot_tools/elasticsearch.py
class ElasticsearchTool(AbstractTool):                        # line 167
```

### Does NOT Exist

- ~~`parrot.tools.cloudwatch`~~ — the tool lives in the SIBLING
  package `parrot_tools.aws.cloudwatch`. Class is `CloudWatchToolkit`
  (NOT `CloudWatchTool`).
- ~~`JiraToolkit.create_ticket`~~ — the method is `jira_create_issue`.
- ~~`LogSource.fetch()`~~ — `LogSource` is a Pydantic model only; the
  node selects the right toolkit based on `LogSource.kind`.

---

## Implementation Notes

### Toolkit selection

```python
async def _fetch_logs(self, source: LogSource) -> List[str]:
    if source.kind == "cloudwatch":
        result = await self._log_toolkits["cloudwatch"].query_logs(
            log_group=source.locator,
            window_minutes=source.time_window_minutes,
        )
        return self._tail_text(result)
    if source.kind == "elasticsearch":
        ...
    if source.kind == "attached_file":
        with open(source.locator) as f:
            return [f.read()[-4000:]]
    raise ValueError(f"Unknown log source kind: {source.kind}")
```

The exact method name on `CloudWatchToolkit` MUST be verified before
implementation — `grep "async def" packages/ai-parrot-tools/src/parrot_tools/aws/cloudwatch.py`.

### Worktree pre-existence check

```python
def _check_no_existing_worktree(self, branch_name: str) -> None:
    path = os.path.join(WORKTREE_BASE_PATH, branch_name)
    if os.path.exists(path):
        raise RuntimeError(
            f"Worktree {path!r} already exists. Run `git worktree remove "
            f"{path}` and retry. Auto-recovery is not in scope (spec R5)."
        )
```

But note: at this point we do NOT yet know `branch_name`. The subagent
mints it. The check happens INSIDE `_validate_research_output` — after
the subagent returns, before we declare success — verifying that the
worktree the subagent claims to have created actually exists AND that
`feat_id` is unique among in-flight runs (delegated to the orchestrator
lock, see spec §7 R9).

### Order of operations (CRITICAL)

```python
async def execute(self, prompt, ctx):
    brief: BugBrief = ctx["bug_brief"]                 # set by BugIntakeNode

    # 1. Fetch logs FIRST (cheap, deterministic)
    excerpts: List[str] = []
    for src in brief.log_sources:
        excerpts.extend(await self._fetch_logs(src))

    # 2. Create Jira issue BEFORE dispatching
    jira_resp = await self._jira.jira_create_issue(
        summary=brief.summary,
        description=self._build_description(brief, excerpts),
        reporter=brief.reporter,
        assignee=os.environ.get("FLOW_BOT_JIRA_ACCOUNT_ID")
                  or config.FLOW_BOT_JIRA_ACCOUNT_ID,
    )
    issue_key = jira_resp["key"]

    # 3. Dispatch to sdd-research
    profile = ClaudeCodeDispatchProfile(
        subagent="sdd-research",
        permission_mode="acceptEdits",
        allowed_tools=["Read", "Grep", "Glob",
                       "Bash(git:*, gh:*, /sdd-spec, /sdd-task)"],
    )
    research_out = await self._dispatcher.dispatch(
        brief=brief,
        profile=profile,
        output_model=ResearchOutput,
        run_id=ctx["run_id"],
        node_id=self.name,
        cwd=os.path.abspath(WORKTREE_BASE_PATH),  # subagent creates the
                                                    # actual worktree
    )

    # 4. Inject jira_issue_key from step 2 if subagent left it blank
    if not research_out.jira_issue_key:
        research_out = research_out.model_copy(
            update={"jira_issue_key": issue_key}
        )

    return research_out
```

### Test ordering pin

```python
@pytest.mark.asyncio
async def test_creates_jira_then_dispatches(node, good_brief):
    call_order = []
    node._jira.jira_create_issue = AsyncMock(
        side_effect=lambda **kw: call_order.append("jira") or {"key": "OPS-1"}
    )
    node._dispatcher.dispatch = AsyncMock(
        side_effect=lambda **kw: call_order.append("dispatch") or research_out_fixture
    )
    await node.execute(prompt="", ctx={"run_id": "r1", "bug_brief": good_brief})
    assert call_order == ["jira", "dispatch"]
```

### Key Constraints

- `permission_mode="acceptEdits"` is required because the subagent
  invokes `/sdd-spec` and `/sdd-task`, which write files under `sdd/`.
- The dispatcher already enforces `cwd` is under `WORKTREE_BASE_PATH`
  (TASK-878 R4 check). Pass `cwd=os.path.abspath(WORKTREE_BASE_PATH)`
  itself (the subagent's working directory is the base; the worktree
  it creates underneath is its own concern).
- Service-account credentials: the `JiraToolkit` instance passed to
  `__init__` MUST already be wrapping a
  `StaticCredentialResolver(StaticCredentials(...))` for the bot —
  that wiring is the orchestrator's responsibility (TASK-886 / runtime
  config), not this node.

### References in Codebase

- `parrot/bots/jira_specialist.py:1639+` — examples of JiraToolkit
  method calls.

---

## Acceptance Criteria

- [ ] `ResearchNode.execute(...)` returns a valid `ResearchOutput`.
- [ ] Mocked `jira_create_issue` is called BEFORE mocked
  `dispatcher.dispatch` (`test_research_node_creates_jira_then_dispatches`).
- [ ] When the dispatcher raises `DispatchOutputValidationError`,
  the node propagates the exception (the flow factory routes it to
  `FailureHandlerNode`).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_research.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import BugBrief, ResearchOutput
from parrot.flows.dev_loop.nodes.research import ResearchNode


@pytest.fixture
def research_out_fixture():
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix-customer-sync",
        worktree_path="/abs/.claude/worktrees/feat-130-fix-customer-sync",
        log_excerpts=[],
    )


@pytest.fixture
def node(research_out_fixture):
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out_fixture)
    return ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={
            "cloudwatch": AsyncMock(), "elasticsearch": AsyncMock(),
        },
    )


# (the rest mirrors spec §4 unit-test list for M5)
```

---

## Agent Instructions

1. Confirm TASK-874, TASK-878 are completed.
2. `grep "async def" packages/ai-parrot-tools/src/parrot_tools/aws/cloudwatch.py`
   to discover the right log-fetching method.
3. `grep -A 30 "async def jira_create_issue"
   packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
   to pin the create-issue signature.
4. Update index → `"in-progress"`.
5. Implement; tests; lint.
6. Move to completed; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
