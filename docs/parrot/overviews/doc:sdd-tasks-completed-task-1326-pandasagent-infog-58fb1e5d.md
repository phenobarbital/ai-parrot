---
type: Wiki Overview
title: 'TASK-1326: `PandasAgent.ask` post-loop branch for `InfographicRenderResult`'
id: doc:sdd-tasks-completed-task-1326-pandasagent-infographic-post-loop-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 3 from the spec. The LLM tool-calling loop produces an
relates_to:
- concept: mod:parrot.bots.data
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1326: `PandasAgent.ask` post-loop branch for `InfographicRenderResult`

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 3)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1323, TASK-1318, TASK-1320
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Module 3 from the spec. The LLM tool-calling loop produces an
`InfographicRenderResult` envelope (from TASK-1323's `return_direct=True`
toolkit). `PandasAgent.ask` must detect that envelope, populate the
`AIMessage` with the multi-dataset data + URL + artifact_id + output_mode,
and SKIP both the response formatter AND the structured-output reformat
path so the HTML response stays verbatim.

The new branch follows the existing `_rerun_for_map` pattern in
`PandasAgent` — isinstance check on the last tool result, mutate the
response in place, return early.

---

## Scope

- In `PandasAgent.ask` (in `parrot/bots/data.py`), after the tool-calling
  loop finishes, BEFORE the formatter/structured-output reformat path,
  add an `isinstance(last_tool_result, InfographicRenderResult)` branch
  that:
  1. Calls `await self._inject_multi_data_from_variables(response,
     envelope.data_variables)` to populate `response.data` as
     `List[DatasetResult.model_dump()]`.
  2. Sets:
     ```python
     response.output = envelope.html_inline or envelope.html_url
     response.output_mode = OutputMode.INFOGRAPHIC
     response.artifact_id = envelope.artifact_id
     ```
     Also set helpful metadata: `response.metadata` (or whichever
     dict-like field exists on the response object) should include
     `html_url`, `html_inline_omitted`, `enhanced`, `template_name`,
     `theme`.
  3. Returns the response IMMEDIATELY, skipping formatter +
     structured-output reformat.
- Place the new branch adjacent to `_rerun_for_map` for reviewability.
- Robust handling of "multiple `infographic_render` calls in one turn"
  — only the LAST tool result of that type is inspected (documented in
  spec §7).
- Tests with a mocked LLM tool loop that produces an
  `InfographicRenderResult`.

**NOT in scope**:
- The toolkit itself (TASK-1323).
- HTTP layer formatter (TASK-1320 owns the `_format_response` branch).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Add post-loop branch in `PandasAgent.ask`. |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py` | CREATE | Branch + multi-data injection + bypass tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.infographic_toolkit import InfographicRenderResult
# verified location: packages/ai-parrot/src/parrot/tools/infographic_toolkit.py (TASK-1323)

from parrot.models.outputs import OutputMode
# verified: parrot/models/outputs.py:39 — OutputMode.INFOGRAPHIC added by TASK-1320

from parrot.models.responses import AIMessage
# verified: parrot/models/responses.py:72 — artifact_id added by TASK-1318
```

### Existing Signatures to Use

```python
# parrot/bots/data.py
class PandasAgent(BasicAgent):
    DEFAULT_MAX_ITERATIONS = 10
    _prompt_builder = _build_pandas_prompt_builder()

    async def ask(self, question, ...) -> AIMessage: ...

    # PATTERN TO REPLICATE (place the new branch adjacent):
    async def _rerun_for_map(self, *, client, question, ...): ...

    async def _inject_multi_data_from_variables(
        self, response: AIMessage, data_variables: List[str],
    ) -> List[str]:
        """Populates response.data as List[DatasetResult.model_dump()]
        for each name in data_variables (pulled from pandas REPL locals)."""

    async def _inject_data_from_variable(
        self, response: AIMessage, data_variable: str,
    ) -> None: ...

    def _get_python_pandas_tool(self) -> Optional[PythonPandasTool]: ...
    def _get_repl_locals(self) -> Dict[str, Any]: ...
```

### Does NOT Exist
- ~~`PandasAgent._handle_infographic_envelope`~~ — name the new method
  whatever you like; the spec doesn't require a specific name.
- ~~`response.set_output_mode()`~~ — set the attribute directly:
  `response.output_mode = OutputMode.INFOGRAPHIC`.

---

## Implementation Notes

### Where to place the branch

Look for `_rerun_for_map` in `parrot/bots/data.py`. The new branch should
sit in the same post-loop region (BEFORE the formatter call). Pattern:

```python
# After the LLM tool loop finishes ...
last_tool_result = self._extract_last_tool_result(...)

if isinstance(last_tool_result, InfographicRenderResult):
    await self._inject_multi_data_from_variables(
        response, last_tool_result.data_variables,
    )
    response.output = last_tool_result.html_inline or last_tool_result.html_url
    response.output_mode = OutputMode.INFOGRAPHIC
    response.artifact_id = last_tool_result.artifact_id
    # Surface URL + flags via the response metadata
    meta = getattr(response, "metadata", None) or {}
    meta.update({
        "html_url": last_tool_result.html_url,
        "html_inline_omitted": last_tool_result.html_inline is None,
        "enhanced": last_tool_result.enhanced,
        "template_name": last_tool_result.template_name,
        "theme": last_tool_result.theme,
    })
    if hasattr(response, "metadata"):
        response.metadata = meta
    return response   # skip formatter + structured reformat
```

### Extracting the last tool result

If the existing loop already stores tool results in
`response.tool_calls` or `response.intermediate_steps` (verify the actual
attribute), iterate in reverse and pick the first
`InfographicRenderResult`. Document the lookup in a comment.

### Key Constraints
- The branch MUST run BEFORE both the response formatter and the
  structured-output reformat path. If both are invoked in sequence after
  the loop, your `return response` early-exit must beat both of them.
- DO NOT touch the `_rerun_for_map` branch.
- Async throughout.

---

## Acceptance Criteria

- [ ] `PandasAgent.ask` sets `response.output_mode = OutputMode.INFOGRAPHIC`
      when the last tool result is `InfographicRenderResult`.
- [ ] `response.data` is populated as `List[DatasetResult.model_dump()]`
      for every name in `data_variables`.
- [ ] `response.artifact_id == envelope.artifact_id`.
- [ ] `response.output` is `html_inline` when present, else `html_url`.
- [ ] `response.metadata["html_url"]` is set.
- [ ] Formatter and structured-output reformat are NOT called when the
      branch is taken (assert via spy / mock on the existing call sites).
- [ ] When the last tool result is NOT an `InfographicRenderResult`, the
      existing behaviour is unchanged (regression guard).
- [ ] When multiple `infographic_render` calls occurred in the same turn,
      the LAST is used.
- [ ] `pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py -v` passes.
- [ ] `ruff check parrot/bots/data.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.bots.data import PandasAgent
from parrot.models.outputs import OutputMode
from parrot.tools.infographic_toolkit import InfographicRenderResult


@pytest.fixture
def envelope():
    return InfographicRenderResult(
        artifact_id="art-1",
        html_url="https://signed/x",
        html_inline="<html>tiny</html>",
        template_name="financial_projection_variance",
        theme="dark",
        data_variables=["revenue", "ebitda"],
        enhanced=False,
    )


@pytest.fixture
def repl_locals():
    return {
        "revenue": pd.DataFrame([{"day": 1, "v": 10}]),
        "ebitda": pd.DataFrame([{"day": 1, "v": 4}]),
    }


async def test_branch_sets_output_mode_and_artifact_id(envelope, repl_locals):
    agent = _make_agent(repl_locals)
    response = await _run_ask_with_last_tool_result(agent, envelope)
    assert response.output_mode is OutputMode.INFOGRAPHIC
    assert response.artifact_id == "art-1"


async def test_branch_injects_multi_data(envelope, repl_locals):
    agent = _make_agent(repl_locals)
    response = await _run_ask_with_last_tool_result(agent, envelope)
    names = [d["data_variable"] for d in response.data]   # adjust to actual key
    assert set(names) == {"revenue", "ebitda"}


async def test_formatter_not_called_for_infographic(envelope, repl_locals):
    agent = _make_agent(repl_locals)
    with patch.object(agent, "_format_for_output_mode") as fmt:
        await _run_ask_with_last_tool_result(agent, envelope)
        fmt.assert_not_called()
        # Adjust the patched name if the existing call site uses another method.


async def test_last_envelope_wins(repl_locals):
    agent = _make_agent(repl_locals)
    first = InfographicRenderResult(artifact_id="a", html_url="u", template_name="t",
                                     data_variables=["revenue"])
    last = InfographicRenderResult(artifact_id="b", html_url="u2", template_name="t",
                                    data_variables=["revenue"])
    response = await _run_ask_with_tool_results(agent, [first, last])
    assert response.artifact_id == "b"


async def test_non_infographic_path_unchanged():
    # Last tool result is a plain str — branch must NOT fire.
    agent = _make_agent({})
    response = await _run_ask_with_last_tool_result(agent, "boring")
    assert response.output_mode is not OutputMode.INFOGRAPHIC
```

---

## Agent Instructions

1. Confirm TASK-1318, TASK-1320, TASK-1323 are merged.
2. Read `parrot/bots/data.py` end-to-end and locate:
   - The post-tool-loop section in `ask()`.
   - The `_rerun_for_map` method as a reference pattern.
   - The exact attribute used to inspect intermediate tool results.
3. Add the branch. Run the broader PandasAgent suite afterwards to catch
   regressions:
   `pytest packages/ai-parrot/tests/unit/bots/ -v`.
4. Move to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
