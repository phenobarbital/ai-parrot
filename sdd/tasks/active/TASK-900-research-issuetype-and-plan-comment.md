# TASK-900: `ResearchNode` — issuetype routing + plan-summary comment

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4–8h)
**Depends-on**: TASK-896, TASK-897
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 + §1 Goals G3, G4, G5. Two tightly-coupled changes
on `ResearchNode`:

1. **Issuetype routing**: `jira_create_issue(issuetype=…)` now picks
   from `_ISSUE_TYPE_BY_KIND[brief.kind]` instead of being hardcoded
   to `"Bug"`. Mapping: `bug → "Bug"`, `enhancement → "Story"`,
   `new_feature → "New Feature"`.

2. **Plan-summary comment**: when the ticket is **newly created**
   (the path that today calls `jira_create_issue` directly), generate
   an LLM plan summary and post it as the FIRST comment with body
   `"Plan for run-<run_id>\n\n<plan>"`. The reuse path
   (`existing_key is not None`) keeps the existing
   `_comment_retriggered` call unchanged — no plan summary on
   re-trigger.

The summarizer LLM client is the existing one
(`DEV_LOOP_SUMMARY_LLM`) unless `DEV_LOOP_PLAN_LLM` is set
(TASK-897).

---

## Scope

- Add the constant `_ISSUE_TYPE_BY_KIND` to
  `parrot/flows/dev_loop/nodes/research.py`.
- Pass `issuetype=_ISSUE_TYPE_BY_KIND[brief.kind]` to
  `jira_create_issue` in the create branch.
- Add `_plan_llm_default()` helper that returns
  `DEV_LOOP_PLAN_LLM` when set, else `DEV_LOOP_SUMMARY_LLM`'s
  default. Mirror the existing `_summarizer_llm_default()`.
- Add `ResearchNode._build_plan_summary(brief, excerpts) -> str`:
  - Builds a plan-oriented prompt (system + user prompt) consuming
    `brief.summary`, `brief.description`, `brief.kind`, and the
    pre-collected `excerpts`.
  - Calls the plan-LLM client (lazy-initialised, cached on
    `self._plan_client`).
  - Falls back to a deterministic stub on error
    (`"Plan unavailable: <error>"`).
- Add `ResearchNode._post_plan_summary_comment(*, issue_key, plan,
  run_id) -> None`:
  - Posts via `JiraToolkit.jira_add_comment(issue=issue_key,
    body=f"Plan for run-{run_id}\n\n{plan}")`.
  - Same defensive `try/except` shape as `_comment_retriggered`.
- In `ResearchNode.execute()`, on the **create** branch:
  - After `issue_key = self._extract_issue_key(jira_resp)`, build the
    plan summary and post it as a comment.
  - Do NOT post a plan summary on the reuse branch.
- Extend `tests/flows/dev_loop/test_research.py` with the four new
  test cases listed in spec §4.

**NOT in scope**:
- The `kind` field declaration (TASK-896).
- `IntentClassifierNode` integration (TASK-898).
- Flow factory rewire (TASK-901).
- UI form changes (TASK-902).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | New constant, two new helpers, modified `execute`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_research.py` | MODIFY | Add issuetype routing tests + plan-summary tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.factory import LLMFactory                # factory.py:38
from parrot.conf import config, DEV_LOOP_PLAN_LLM            # post-TASK-897
from parrot import conf                                       # conf.py
from parrot.flows.dev_loop.models import (
    WorkBrief, ResearchOutput,
)
from parrot_tools.jiratoolkit import JiraToolkit             # jiratoolkit.py:609
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(Node):
    def __init__(
        self, *, dispatcher, jira_toolkit, log_toolkits=None,
        summarizer_llm=None, name="research",
    ): ...
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> ResearchOutput:
        # ... 1. logs ...
        # ... 2. existing_key = await self._find_existing_issue(brief) ...
        # On create branch:
        reporter_fields = await self._reporter_fields(brief.reporter)
        jira_resp = await self._jira.jira_create_issue(
            summary=brief.summary,
            issuetype="Bug",                                  # ← REPLACE per kind
            description=description,
            assignee=conf.FLOW_BOT_JIRA_ACCOUNT_ID or None,
            fields=reporter_fields,
        )
        issue_key = self._extract_issue_key(jira_resp)
        # ↑ insert plan-summary comment HERE (create-only)

    async def _summarize_excerpts(self, excerpts: List[str]) -> str:
        # PATTERN to mirror for the plan-summary helper.
        ...

    def _get_summarizer_client(self) -> Any:
        # PATTERN to mirror for the plan client.
        ...

    async def _comment_retriggered(self, *, issue_key, run_id, description):
        # PATTERN for the new _post_plan_summary_comment helper.
        ...

# parrot_tools.jiratoolkit.JiraToolkit
async def jira_create_issue(
    self,
    project: Optional[str] = None,
    summary: str = "",
    issuetype: Optional[str] = None,                         # ← target field
    description: Optional[str] = None,
    assignee: Optional[str] = None,
    ...
) -> Dict[str, Any]: ...                                     # line 1366

async def jira_add_comment(self, issue: str, body: str) -> Dict[str, Any]: ...
```

### Does NOT Exist

- ~~A separate `jira_post_plan` helper on JiraToolkit~~ — use
  `jira_add_comment(issue, body)` (same call site as
  `_comment_retriggered`).
- ~~`brief.kind` mapping inside `JiraToolkit`~~ — the mapping lives
  on `ResearchNode` only. Don't push it down into the toolkit.
- ~~Posting the plan as a Jira `description` instead of a comment~~ —
  spec §1 G4 explicitly says "first comment of the ticket". The
  description is the existing `_build_description` output.
- ~~`AbstractClient.summarize(...)`~~ — the LLM is invoked via
  `client.ask(prompt, ...)` (same as the existing
  `_summarize_excerpts`).

---

## Implementation Notes

### Pattern to Follow

```python
# Mapping at module level:
from parrot.flows.dev_loop.models import WorkKind  # internal alias

_ISSUE_TYPE_BY_KIND: Dict[str, str] = {
    "bug": "Bug",
    "enhancement": "Story",
    "new_feature": "New Feature",
}


def _plan_llm_default() -> str:
    """Resolve the plan-summary LLM string.

    Falls back to DEV_LOOP_SUMMARY_LLM's default when DEV_LOOP_PLAN_LLM
    is unset.
    """
    pinned = conf.config.get("DEV_LOOP_PLAN_LLM", fallback="")
    if pinned:
        return pinned
    return _summarizer_llm_default()


# On ResearchNode:
class ResearchNode(Node):
    def __init__(self, *, dispatcher, jira_toolkit,
                 log_toolkits=None, summarizer_llm=None, plan_llm=None,
                 name="research"):
        ...
        self._plan_llm = plan_llm or _plan_llm_default()
        self._plan_client: Any = None  # lazy

    async def _build_plan_summary(
        self, brief: WorkBrief, excerpts: List[str]
    ) -> str:
        try:
            client = self._get_plan_client()
            prompt = self._compose_plan_prompt(brief, excerpts)
            response = await client.ask(prompt, max_tokens=1200)
            text = (response.response or "").strip()
            if text:
                return text
        except Exception as exc:
            self.logger.warning(
                "Plan summarization via %s failed (%s); "
                "falling back to deterministic stub",
                self._plan_llm, exc,
            )
        return self._deterministic_plan_stub(brief)

    @staticmethod
    def _compose_plan_prompt(brief, excerpts) -> str:
        # System frame + user content. Stay short.
        return (
            "You are an SRE planning a fix or change for a Jira "
            "ticket. Read the request and produce a SHORT actionable "
            "plan (max 8 bullet points) describing the steps you would "
            "take to resolve it. Reference modules / files when "
            "obvious from the description. Don't quote logs verbatim "
            "and don't restate the summary.\n\n"
            f"Kind: {brief.kind}\n"
            f"Summary: {brief.summary}\n"
            f"Component: {brief.affected_component}\n"
            f"Description: {brief.description or '(none)'}\n"
            f"Log excerpts (truncated):\n"
            + ("\n---\n".join(excerpts) if excerpts else "(none)")
        )

    @staticmethod
    def _deterministic_plan_stub(brief: WorkBrief) -> str:
        return (
            f"Plan unavailable (LLM call failed). Manual triage "
            f"required for kind={brief.kind!r}, component "
            f"{brief.affected_component!r}."
        )

    async def _post_plan_summary_comment(
        self, *, issue_key: str, plan: str, run_id: str,
    ) -> None:
        body = f"Plan for run-{run_id}\n\n{plan}"
        try:
            await self._jira.jira_add_comment(issue=issue_key, body=body)
        except Exception as exc:
            self.logger.warning(
                "Could not post plan-summary comment on %s: %s",
                issue_key, exc,
            )

    def _get_plan_client(self) -> Any:
        if self._plan_client is None:
            self._plan_client = LLMFactory.create(self._plan_llm)
        return self._plan_client
```

### Key Constraints

- Issuetype mapping is a `dict[str, str]` with the three literal keys
  matching `WorkKind`. If `brief.kind` is missing from the map (it
  cannot be — Pydantic literal enforces it — but defensive code is
  cheap), default to `"Bug"`.
- Plan summary fires ONLY on the create branch. Inspect `existing_key`
  flow control in the current `execute`.
- The plan-summary comment is the FIRST post-create comment. Do NOT
  combine it with the description — the user already sees the
  description in the ticket body.
- LLM-call failures must NOT abort the flow. Same fallback shape as
  `_summarize_excerpts`.

### References in Codebase

- `parrot/flows/dev_loop/nodes/research.py::_summarize_excerpts` —
  exact pattern for the plan helper.
- `parrot/flows/dev_loop/nodes/research.py::_comment_retriggered` —
  exact pattern for posting the comment.
- `parrot/clients/factory.py:38` — LLMFactory entry point.

---

## Acceptance Criteria

- [ ] `_ISSUE_TYPE_BY_KIND` constant exists with the three mappings.
- [ ] `jira_create_issue` is called with `issuetype` derived from
  `brief.kind` (verified by mock-call assertion in tests for each
  of the three kinds).
- [ ] `_build_plan_summary` returns the LLM output on success and the
  deterministic stub on error.
- [ ] `_post_plan_summary_comment` posts a body starting with
  `Plan for run-<run_id>` exactly once on the create branch.
- [ ] On the reuse branch (`existing_key is not None`), no
  `Plan for run-` comment is posted.
- [ ] All four new tests pass (`test_research_issuetype_for_each_kind`,
  `test_research_plan_summary_posted_on_create`,
  `test_research_no_plan_summary_on_reuse`,
  `test_research_plan_summary_falls_back_to_tail_on_llm_error`).
- [ ] Pre-existing dev_loop suite stays green.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_research.py — additions
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestIssueTypeRouting:
    @pytest.mark.parametrize("kind, expected", [
        ("bug", "Bug"),
        ("enhancement", "Story"),
        ("new_feature", "New Feature"),
    ])
    async def test_issuetype_per_kind(self, node, sample_kwargs, kind, expected):
        from parrot.flows.dev_loop import WorkBrief, ShellCriterion
        brief = WorkBrief(
            kind=kind,
            **sample_kwargs,
            acceptance_criteria=[ShellCriterion(name="r", command="ruff check .")],
        )
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        kwargs = node._jira.jira_create_issue.call_args.kwargs
        assert kwargs["issuetype"] == expected


class TestPlanSummaryOnCreate:
    async def test_plan_comment_posted_on_create(self, node, good_brief):
        # _find_existing_issue returns None — pure create path
        node._jira.jira_search_issues = AsyncMock(return_value={"issues": []})
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        # Stub the plan client so we don't hit the network.
        fake_response = MagicMock(response="Step 1.\nStep 2.")
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(return_value=fake_response)
        await node.execute("", {"bug_brief": good_brief, "run_id": "r2"})
        bodies = [c.kwargs["body"] for c in node._jira.jira_add_comment.call_args_list]
        assert any(b.startswith("Plan for run-r2") for b in bodies)


class TestPlanSummaryNotOnReuse:
    async def test_no_plan_comment_when_reused(self, node, good_brief):
        # _find_existing_issue returns NAV-99 — reuse path
        node._jira.jira_get_issue = AsyncMock(return_value={"key": "NAV-99"})
        good_brief = good_brief.model_copy(update={"existing_issue_key": "NAV-99"})
        node._jira.jira_create_issue = AsyncMock(side_effect=AssertionError("must not be called"))
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute("", {"bug_brief": good_brief, "run_id": "r3"})
        bodies = [c.kwargs["body"] for c in node._jira.jira_add_comment.call_args_list]
        assert not any(b.startswith("Plan for run-") for b in bodies)


class TestPlanSummaryFallback:
    async def test_falls_back_to_stub_on_llm_error(self, node, good_brief):
        node._jira.jira_search_issues = AsyncMock(return_value={"issues": []})
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-2"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(side_effect=RuntimeError("boom"))
        await node.execute("", {"bug_brief": good_brief, "run_id": "r4"})
        bodies = [c.kwargs["body"] for c in node._jira.jira_add_comment.call_args_list]
        assert any("Plan for run-r4" in b for b in bodies)
        # The body should still be posted; deterministic stub fires.
```

---

## Agent Instructions

1. Confirm TASK-896 (`WorkBrief.kind`) and TASK-897 (`DEV_LOOP_PLAN_LLM`)
   are merged — the imports above depend on them.
2. Implement the constant + three new helpers + execute-branch edits.
3. Add the four tests; verify they pass under
   `pytest packages/ai-parrot/tests/flows/dev_loop/test_research.py -v`.
4. Run the full dev_loop suite — pre-existing tests must stay green.
5. Commit; move file; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
