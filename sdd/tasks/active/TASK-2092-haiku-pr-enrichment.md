# TASK-2092: Haiku PR-body enrichment (enrich, never replace)

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2084
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of the spec — the mechanical seat. Both handoff nodes
build their PR title and body from **deterministic string templates**
(`feature_handoff.py:507,511`; `deployment_handoff.py:474,479`) — there is no LLM
anywhere in the PR-creation path today.

The decision ([R2]) is deliberately conservative: **enrich, never replace.** The
template stays the skeleton *and* the fallback; Claude Haiku 4.5 contributes only
a "Summary of changes" section. Any failure, timeout, or missing configuration
must produce byte-identical output to today.

This is the smallest-risk seat and is fully independent of the dev and
adversarial seats.

---

## Scope

- Add a small mechanical-seat helper that issues one no-tools `ask()` on
  Claude Haiku 4.5 using `NovaMechanicalProfile` and returns a short
  "Summary of changes" markdown block.
- Call it from `FeatureHandoffNode._build_body` and
  `DeploymentHandoffNode._build_body`, splicing the section into the existing
  template output.
- Guarantee the fallback: on any exception, timeout, or absent config, return
  the template output unchanged.
- Never modify `_build_title` — titles stay fully deterministic.
- Write unit tests, including a byte-identical fallback test.

**NOT in scope**: replacing the templates; touching `_create_pr`
(`feature_handoff.py:278`, `deployment_handoff.py:331`) or the `gh`/REST paths;
Jira comment text; commit/squash summaries; log-excerpt summarization in
`research.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` | MODIFY | Mechanical-seat helper (one no-tools `ask()`) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py` | MODIFY | Splice the summary into `_build_body` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | Same |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_LOOP_NOVA_MECHANICAL_MODEL` (if not already added) |
| `packages/ai-parrot/tests/flows/dev_loop/test_pr_enrichment.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.models import NovaMechanicalProfile   # TASK-2084
from parrot.clients.nova import NovaClient                       # clients/nova/__init__.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py
        title = self._build_title(planner)                            # line 166
        body = self._build_body(planner, development, synthesis,
                                qa_report, accept_notes)              # line 167
        ...
        pr_url = await self._create_pr(planner.branch_name, title, body)  # line 172
    async def _create_pr(self, branch: str, title: str, body: str) -> str: ...  # line 278
    @staticmethod
    def _build_title(planner: PlannerOutput) -> str: ...              # line 507
    def _build_body(...)                                              # line 511

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py
        pr_url = await self._create_pr(...)                           # line 151
    async def _create_pr(self, branch: str, title: str, body: str) -> str: ...  # line 331
    @staticmethod
    def _build_title(brief: BugBrief, research: ResearchOutput) -> str: ...  # line 474
    def _build_body(...)                                              # line 479

# packages/ai-parrot/src/parrot/clients/bedrock.py
async def ask(self, ..., tools=None, use_tools=None, ...): ...        # line 578
# use_tools defaults to self.enable_tools (line 638); toolConfig only injected
# when _use_tools is truthy (lines 724-731) — pass use_tools=False explicitly
```

### Does NOT Exist

- ~~Any LLM call in the PR-creation path~~ — `_build_title`/`_build_body` are pure string templates; this task introduces the first one
- ~~A shared "mechanical dispatcher" class~~ — the spec's public interfaces list only `NovaCodeDispatcher` and `NovaAdversarialReviewDispatcher`; this is a small helper, not a third dispatcher
- ~~`NovaClient._chat_completion`~~ — does not exist; use `ask()`
- ~~An existing `Summary of changes` section in either template~~ — verify the current template output before splicing so the fallback assertion is exact

---

## Implementation Notes

### Pattern to Follow

```python
async def summarize_changes(diff: str, *, profile: NovaMechanicalProfile,
                            logger) -> str:
    """Return a short 'Summary of changes' block, or '' on any failure.

    Never raises: the caller falls back to the deterministic template when this
    returns an empty string.
    """
    try:
        ...  # one NovaClient.ask(..., use_tools=False) under a timeout
    except Exception:                       # noqa: BLE001 - enrichment must never break handoff
        logger.warning("PR summary enrichment failed; using template only.", exc_info=True)
        return ""
```

Then in `_build_body`, append the section only when non-empty. The template path
must remain reachable and unchanged.

### Key Constraints

- **The fallback is the feature.** A test must assert the output is
  byte-identical to the current template when enrichment is disabled or fails.
- Pass `use_tools=False` explicitly — do not rely on `enable_tools`'s default.
- Bound the call with `NovaMechanicalProfile.timeout_seconds`; a slow model must
  not delay a PR.
- Swallow every exception from the enrichment path (`noqa: BLE001` with a
  comment, as `_shared.py:70` does for its shim).
- Do not touch `_build_title` or `_create_pr`.
- async throughout; `self.logger`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:53-74` —
  the "swallow and log, never break the caller" precedent
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:145-157` —
  another degrade-on-error precedent in this package
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:507-560` —
  the template to preserve

---

## Acceptance Criteria

- [ ] With the mechanical seat unconfigured, `_build_body` output is
      **byte-identical** to before this task (both nodes)
- [ ] With it configured, the body gains exactly one "Summary of changes" section
- [ ] An LLM exception, a timeout, or an empty response all fall back silently to
      the template (warning logged, PR still created)
- [ ] `ask()` is called with `use_tools=False`
- [ ] `_build_title` is unchanged in both nodes
- [ ] `_create_pr` and the `gh`/REST paths are untouched
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_pr_enrichment.py -v` passes
- [ ] Existing handoff-node tests still pass
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_pr_enrichment.py
import pytest
from unittest.mock import AsyncMock


class TestFallbackIsExact:
    def test_body_unchanged_when_unconfigured(self, feature_node, planner, qa_report):
        """The deterministic template must survive byte-for-byte."""
        before = EXPECTED_TEMPLATE_BODY   # captured from the current implementation
        assert feature_node._build_body(planner, ..., qa_report, ...) == before

    async def test_llm_exception_falls_back(self, feature_node, monkeypatch):
        monkeypatch.setattr("...summarize_changes", AsyncMock(side_effect=RuntimeError))
        body = await feature_node._build_body_async(...)
        assert "Summary of changes" not in body

    async def test_timeout_falls_back(self, feature_node, monkeypatch):
        monkeypatch.setattr("...summarize_changes", AsyncMock(side_effect=TimeoutError))
        body = await feature_node._build_body_async(...)
        assert "Summary of changes" not in body

    async def test_empty_response_falls_back(self, feature_node, monkeypatch):
        monkeypatch.setattr("...summarize_changes", AsyncMock(return_value=""))
        body = await feature_node._build_body_async(...)
        assert "Summary of changes" not in body


class TestEnrichment:
    async def test_section_added_when_configured(self, feature_node, monkeypatch):
        monkeypatch.setattr("...summarize_changes", AsyncMock(return_value="- did a thing"))
        body = await feature_node._build_body_async(...)
        assert "Summary of changes" in body and "did a thing" in body

    async def test_ask_called_without_tools(self, mechanical_client):
        kwargs = mechanical_client.ask.await_args.kwargs
        assert kwargs.get("use_tools") is False


class TestUntouched:
    def test_build_title_unchanged(self, feature_node, planner):
        assert feature_node._build_title(planner) == EXPECTED_TITLE
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (Module 8, §1 Non-Goals)
2. **Check dependencies** — verify TASK-2084 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - **Capture the current `_build_body` output verbatim** for both nodes — that
     string is the fallback assertion; the task is not done without it
   - Confirm `_build_title`/`_build_body`/`_create_pr` line numbers in both nodes
   - Confirm `ask()`'s `use_tools` gating at `clients/bedrock.py:638,724-731`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2092-haiku-pr-enrichment.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
