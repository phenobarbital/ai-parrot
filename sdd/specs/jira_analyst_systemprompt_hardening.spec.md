# Feature Specification: jira_analyst_systemprompt_hardening

**Feature ID**: FEAT-138
**Date**: 2026-05-01
**Author**: Juan Rodríguez
**Status**: approved
**Target version**: next-version (TBD at merge time — not a forced minor bump)

---

## 1. Motivation & Business Requirements

### Problem Statement

`JiraSpecialist` (and its concrete subclasses such as `Jirachi`) is currently
driven by a single monolithic legacy template
(`JIRA_SPECIALIST_PROMPT`, `packages/ai-parrot/src/parrot/bots/jira_specialist.py:152-461`)
assigned to `system_prompt_template` instead of the project's composable
prompt-layer system (`PromptBuilder` + `PromptLayer`).

When the underlying LLM is `GoogleModel.GEMINI_3_FLASH_PREVIEW`
(`jira_specialist.py:489`) — which has aggressive completion behaviour and
a small reasoning budget — and `JiraToolkit` returns an empty result set,
an unmapped issue, or an error, the agent **fabricates ticket data instead
of declaring "not found"**. Observed failure modes (paraphrased from real
production transcripts):

- **Field fabrication on miss**: asked about a real ticket key, the agent
  invents a plausible-looking summary, status, reporter, assignee, dates,
  and even error descriptions when the toolkit response does not contain
  that ticket.
- **Cross-ticket bleeding**: data from a prior tool call (or an earlier
  search result) leaks into the answer for a different ticket key.
- **Apology-then-fabricate loop**: when the user corrects a wrong answer,
  the agent acknowledges a "cache problem" or "search system failure" and
  produces a **second, different, fabricated** answer instead of re-querying
  the toolkit and reporting `Data not available`.
- **Phantom IDs / dates**: fabricated user IDs (e.g. `5f5125ee6db35e0039ef01df`)
  and fabricated close-dates with a "system updates this month" justification.

The existing `STRICT_GROUNDING_LAYER`
(`packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67-102`) is
data-analysis-oriented (columns, dataframes, `python_repl_pandas`) and does
not address Jira-specific failure modes.

In parallel, `JiraToolkit` returns shapes that the LLM can mis-parse:
empty searches return `{"total": 0, "issues": [], "pagination": {...}}`
without an explicit `not_found` / `empty` signal
(`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2355-2367`),
and `jira_get_issue` returns a raw issue dict on success but **raises** on
a missing key (`jiratoolkit.py:1159-1205`), which the LLM may then ignore
silently.

### Goals

- **G1**: Migrate `JiraSpecialist.system_prompt_template` fully to the
  composable `PromptBuilder` API. No new code path may rely on the legacy
  monolithic string.
- **G2**: Introduce a Jira-specific anti-hallucination layer
  (`JIRA_GROUNDING_LAYER`) registered in `domain_layers.py`, reusable by
  every `JiraSpecialist` subclass.
- **G3**: Decompose `JIRA_SPECIALIST_PROMPT` into named, reordered
  layers with explicit responsibilities (workflow, cancellation,
  fresh-turn, mandatory HITL, escalation, grounding) so each can evolve
  independently.
- **G4**: Normalise `JiraToolkit` responses on the empty / not-found path
  so the LLM receives an unambiguous `status: "empty"` / `status: "not_found"`
  envelope instead of having to infer it from `total: 0` or an exception.
- **G5**: Lock in the behaviour with regression tests that simulate the
  observed hallucination triggers (empty search, unknown key, toolkit
  exception) and assert the agent does not fabricate fields.

### Non-Goals (explicitly out of scope)

- Replacing `Gemini-3-Flash-preview` as the default model. Hardening
  must work *with* Flash, not by escaping to a stronger model.
- Re-architecting the daily-standup workflow, callback handlers, or
  Telegram integration. They consume the same agent but their logic is
  unchanged.
- Adding new Jira capabilities (transitions, fields, OAuth flows).
- Per-user prompt personalisation.
- Migrating other agents (`JiraAnalyst` non-existent today; only
  `JiraSpecialist` and its subclasses are in scope).
- Multi-language reply support. The new layers and sentinel phrases are
  **English-only**; any non-English text present in the legacy
  `JIRA_SPECIALIST_PROMPT` (greetings, form questions, cancellation text)
  is rewritten in English during decomposition. Channel-specific
  localisation is a future-FEAT concern.

---

## 2. Architectural Design

### Overview

`JiraSpecialist` is reshaped into a **PromptBuilder-driven agent**:

1. The class no longer sets `system_prompt_template`. Instead its
   `__init__` builds a `PromptBuilder` instance composed of the standard
   `default()` stack **plus** a Jira-specific overlay:
   - `IDENTITY_LAYER` (existing, unchanged)
   - `SECURITY_LAYER` (existing, unchanged)
   - **`JIRA_WORKFLOW_LAYER`** (new) — Mandatory HITL rules, fresh-turn
     rule, cancellation/timeout protocol, daily standup, assignment
     intake, end-of-day wrap, escalation. This is `JIRA_SPECIALIST_PROMPT`
     decomposed and re-anchored as a single CONFIGURE-phase layer.
   - `KNOWLEDGE_LAYER` / `USER_SESSION_LAYER` (existing)
   - `TOOLS_LAYER` (existing) with Jira-specific tool guidance injected
     via `extra_tool_instructions`.
   - **`JIRA_GROUNDING_LAYER`** (new) — strict anti-hallucination rules
     for tool-output-grounded behaviour: every ticket field must come
     from a tool call in the *current turn*; on `status: "not_found"` or
     `status: "empty"` the agent says so verbatim and stops; never
     re-emit a previous tool's data for a different key.
   - `BEHAVIOR_LAYER` (existing, with conservative `rationale`).
2. `JiraToolkit` returns a normalised envelope on the empty / not-found
   paths so the LLM has an unambiguous machine-readable signal that the
   grounding layer can reference.
3. Both pieces are exercised by regression tests that mock the toolkit
   and assert the agent's reply does not contain fabricated fields.

### Component Diagram

```
JiraSpecialist.__init__
  └── builds PromptBuilder
        ├── IDENTITY_LAYER
        ├── SECURITY_LAYER
        ├── JIRA_WORKFLOW_LAYER   (new) ─┐
        ├── KNOWLEDGE_LAYER              │
        ├── USER_SESSION_LAYER           │
        ├── TOOLS_LAYER                  │ assembled per-request
        ├── JIRA_GROUNDING_LAYER  (new) ─┤   into the system prompt
        └── BEHAVIOR_LAYER               ┘

Agent.ask()
  └── PromptBuilder.build(request_ctx) → system prompt
                                              │
                                              ▼
                                     GoogleModel.GEMINI_3_FLASH_PREVIEW
                                              │
                                              ▼
                                       JiraToolkit.<tool>
                                              │
                                              ▼
                          { "status": "ok" | "empty" | "not_found" | "error",
                            "data": ... ,
                            "message": "..." }
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.prompts.builder.PromptBuilder` | uses (`PromptBuilder.default()` + `.add()`) | composes the agent's prompt |
| `parrot.bots.prompts.domain_layers` | extends (registers two new layers) | new layers must be exported and added to `_DOMAIN_LAYERS` |
| `parrot.bots.abstract.AbstractBot._configure_prompt_builder` | uses unchanged | already resolves CONFIGURE-phase vars |
| `parrot.bots.jira_specialist.JiraSpecialist` | refactor | drops `system_prompt_template`, sets `prompt_builder` instead |
| `parrot_tools.jiratoolkit.JiraToolkit` | extends (response normalisation) | `jira_get_issue`, `jira_search_issues`, similar lookups gain a uniform envelope |
| `parrot.models.google.GoogleModel.GEMINI_3_FLASH_PREVIEW` | uses unchanged | model identity is preserved |

### Data Models

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
from typing import Literal, TypedDict, Any, Optional

class JiraToolEnvelope(TypedDict, total=False):
    """Uniform envelope — the single return type for read-only
    JiraToolkit lookups (`jira_get_issue`, `jira_search_issues`,
    `jira_search_users`, etc.). The legacy native shapes are removed;
    callers either read `envelope["data"]` for the success payload or
    branch on `envelope["status"]`.
    """
    status: Literal["ok", "empty", "not_found", "error"]
    data: Any                 # the original payload (issue dict, list, etc.)
    message: str              # human-readable explanation; required on non-"ok"
    query: Optional[str]      # JQL or key that produced this result
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
JIRA_WORKFLOW_LAYER: PromptLayer  # decomposed JIRA_SPECIALIST_PROMPT body
JIRA_GROUNDING_LAYER: PromptLayer # anti-hallucination rules for Jira tools

# Both registered in _DOMAIN_LAYERS so get_domain_layer("jira_grounding") works.
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW
    # NOTE: system_prompt_template REMOVED — PromptBuilder is authoritative.

    def __init__(self, **kwargs):
        kwargs.setdefault("injection_probability_threshold", 0.995)
        # Build the layered prompt before super().__init__ so AbstractBot
        # picks it up via the prompt_builder property.
        kwargs.setdefault("prompt_builder", self._build_prompt_builder())
        ...

    @staticmethod
    def _build_prompt_builder() -> PromptBuilder:
        from parrot.bots.prompts import (
            PromptBuilder, get_domain_layer,
        )
        b = PromptBuilder.default()
        b.add(get_domain_layer("jira_workflow"))
        b.add(get_domain_layer("jira_grounding"))
        return b
```

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
# Global flip — no envelope= kwarg. The envelope shape is now the only
# return type for read-only lookups. Three (3) non-LLM callers are
# migrated in Module 5b.
async def jira_get_issue(
    self,
    issue: str,
    ...,
) -> JiraToolEnvelope:
    ...
async def jira_search_issues(
    self,
    jql: str,
    ...,
) -> JiraToolEnvelope:
    ...
async def jira_search_users(
    self,
    ...,
) -> JiraToolEnvelope:
    ...
```

---

## 3. Module Breakdown

> Each module maps to a Task Artifact in `/sdd-task`.

### Module 1: `JIRA_WORKFLOW_LAYER` (decomposition of legacy prompt)
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
- **Responsibility**: Carry forward the workflow rules currently embedded
  in `JIRA_SPECIALIST_PROMPT` (sections: *Default posture*, *Fresh-turn rule*,
  *Cancellation rule*, *Mandatory human interaction*, *Daily standup flow*,
  *Mid-day blockers*, *Assignment intake*, *End-of-day wrap*, *Escalation*).
  Phase: `CONFIGURE`. Priority: `LayerPriority.PRE_INSTRUCTIONS + 5` so it
  renders after identity/security but before knowledge.
  **Language**: the layer template is **English-only**, including all
  reply templates and form questions. Any non-English phrasing in the
  legacy `JIRA_SPECIALIST_PROMPT` (greetings, form prompts, cancellation
  text) must be rewritten in English when copied into the layer.
- **Depends on**: existing `PromptLayer`, `LayerPriority`, `RenderPhase`
  in `prompts/layers.py`.

### Module 2: `JIRA_GROUNDING_LAYER`
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
- **Responsibility**: Tool-output grounding rules specifically for Jira:
  - Every ticket field (key, summary, status, reporter, assignee, dates,
    labels, components, comments, history) MUST be quoted verbatim from a
    tool call made *in the current turn*.
  - On `status: "not_found"` or `status: "empty"` reply literally
    `No results found for <KEY|JQL>.` and STOP. Do not retry the same
    tool with cosmetic variations of the input.
  - Never reuse fields from a prior tool call's result for a different
    issue key. Re-call the tool.
  - Never invent IDs, dates, accountIds, displayNames, project keys.
  - On a tool error / exception, reply literally `Jira lookup failed:
    <message>.` and stop. Do NOT apologise + re-emit a fabricated
    answer.
  - Forbid the "apology-then-fabricate" loop explicitly.
- **Depends on**: Module 1 (registered alongside it).
- Phase: `CONFIGURE`. Priority: `LayerPriority.BEHAVIOR - 5` (same slot
  the existing `STRICT_GROUNDING_LAYER` uses; they are mutually exclusive
  per agent — Jira agent picks the Jira one).

### Module 3: Domain layer registry update
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
  and `packages/ai-parrot/src/parrot/bots/prompts/__init__.py`
- **Responsibility**: Add `JIRA_WORKFLOW_LAYER` and `JIRA_GROUNDING_LAYER`
  to `_DOMAIN_LAYERS` and re-export both from `prompts/__init__.py` so
  external bots can opt-in via `get_domain_layer("jira_grounding")`.
- **Depends on**: Modules 1 and 2.

### Module 4: `JiraSpecialist` migration
- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**:
  - Delete the class attribute `system_prompt_template`.
  - **Delete the `JIRA_SPECIALIST_PROMPT` string literal entirely**
    (lines 152-461) once `JIRA_WORKFLOW_LAYER` is verified equivalent.
    No `DeprecationWarning` shim, no compatibility re-export — the
    symbol is removed in the same commit.
  - In `__init__`, install the layered `PromptBuilder` via the
    `prompt_builder` kwarg before `super().__init__()`.
  - Verify `Jirachi` (the public concrete subclass) still works without
    code changes — the prompt builder must be inheritable.
- **Depends on**: Module 3.

### Module 5: `JiraToolkit` response envelope (global flip)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: The envelope shape becomes the **single, unconditional
  return type** for `jira_get_issue`, `jira_search_issues`,
  `jira_search_users`, and other read-only lookup tools that today either
  return an empty list/dict or raise. There is **no `envelope=False`
  fallback** — the shape change is global and atomic.
  - On success:
    `{"status": "ok", "data": <native>, "query": ..., "message": ""}`.
  - On a search returning zero rows:
    `{"status": "empty", "data": [], "query": jql, "message": "..."}`.
  - On `JIRAError` "issue does not exist":
    `{"status": "not_found", "data": None, "query": issue, "message": ...}`.
  - On other recoverable exceptions:
    `{"status": "error", "data": None, "query": ..., "message": str(exc)}`.
    Do NOT suppress the original log line — keep `self.logger.error(...)`.
  - Authentication/permission errors keep raising (so the agent surface
    layer sees them, not the LLM) — they are NOT recoverable for the
    grounding layer.
- **Depends on**: nothing in this spec; it's a self-contained toolkit
  change. Land first or in parallel with Modules 1-4.

### Module 5b: Migrate non-LLM callers to the envelope shape
- **Path**:
  - `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  - `packages/ai-parrot/tests/debug_jira.py`
- **Responsibility**: With the global flip there is no opt-out, so the
  three programmatic call-sites that read the return shape must be
  migrated in the same change-set:
  1. `research.py:546` — `await self._jira.jira_get_issue(...)` discards
     the return; the only behaviour change is that exceptions for
     unknown keys are now `{"status":"not_found", ...}` instead of a
     `JIRAError`. Update the surrounding `try/except` to also branch on
     `result["status"] != "ok"` and treat it as the previous "not found"
     fallback path.
  2. `research.py:572-588` — replace the `result.get("issues") or
     result.get("results") or result.get("data") or []` fallback chain
     with explicit envelope handling:
     ```python
     if result["status"] == "empty":
         issues = []
     elif result["status"] == "ok":
         issues = result["data"]["issues"]
     else:
         self.logger.warning("Jira lookup failed: %s", result["message"])
         return None
     ```
  3. `tests/debug_jira.py:42-44` — change to read `issue["data"]["key"]`
     and `issue["data"]["fields"]["summary"]`, gated on
     `issue["status"] == "ok"`.
- **Depends on**: Module 5.

### Module 6: Regression tests
- **Path**: `packages/ai-parrot/tests/test_jira_specialist_grounding.py` (new)
- **Responsibility**: Exercise the hallucination triggers using a
  mocked `JiraToolkit`:
  - **T1**: `jira_get_issue("NAV-99999")` returns
    `{"status": "not_found", ...}`. Assert the agent reply contains
    `No results found for NAV-99999` and does not include any fabricated
    summary, status, assignee, or date.
  - **T2**: `jira_search_issues("project = NAV AND ...")` returns
    `{"status": "empty", ...}`. Assert the reply does not list any
    ticket key.
  - **T3**: `jira_get_issue` raises an unexpected `RuntimeError`. Assert
    the reply contains `Jira lookup failed` and stops.
  - **T4 — apology-then-fabricate**: simulate a turn where the user
    contradicts the agent. Assert the agent re-calls the tool (visible
    in the mock) instead of producing a second answer with the same
    `not_found` envelope.
  - **T5 — cross-ticket bleed**: in a single ask, after a successful
    `jira_get_issue("NAV-1")` returns data, ask about `NAV-2` (which
    returns `not_found`). Assert no field from NAV-1 appears in the
    NAV-2 answer.
- **Depends on**: Modules 4 and 5.

### Module 7: Documentation
- **Path**: `docs/jira-specialist-prompt-layers.md` (new)
- **Responsibility**: Describe the new layered prompt, what
  `JIRA_GROUNDING_LAYER` enforces, and how subclasses
  (`Jirachi`, future variants) can replace or extend layers.
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_jira_workflow_layer_renders` | 1 | Layer renders all CONFIGURE vars; sections (cancellation, fresh-turn, standup) appear in the output. |
| `test_jira_grounding_layer_renders` | 2 | Layer renders without missing-var errors; key phrases (`No results found for`, `Jira lookup failed`) appear verbatim. |
| `test_get_domain_layer_jira_grounding` | 3 | `get_domain_layer("jira_grounding")` and `get_domain_layer("jira_workflow")` resolve. |
| `test_jiraspecialist_uses_prompt_builder` | 4 | `JiraSpecialist().prompt_builder` is set; `JiraSpecialist().system_prompt_template` is unset or unused after configure(). |
| `test_jiraspecialist_layers_include_jira_grounding` | 4 | The builder's `layer_names` contains both `jira_workflow` and `jira_grounding`. |
| `test_jirachi_inherits_layers` | 4 | A bare `class Jirachi(JiraSpecialist): pass` instance has the same layers as the parent. |
| `test_envelope_get_issue_not_found` | 5 | `jira_get_issue("ZZZ-9999")` against a 404 stub returns `status="not_found"`. |
| `test_envelope_get_issue_ok` | 5 | Successful call returns `status="ok"` with `data` containing the issue dict. |
| `test_envelope_search_empty` | 5 | `jira_search_issues("project = NOPE")` returns `status="empty"`, `data=[]`. |
| `test_envelope_search_ok_shape` | 5 | Successful search returns `status="ok"` with `data` carrying the legacy `{total, issues, pagination, ...}` payload intact. |
| `test_research_node_envelope_ok` | 5b | `research.py` duplicate lookup returns the issue key when `status="ok"`. |
| `test_research_node_envelope_empty` | 5b | `research.py` returns `None` when search yields `status="empty"`. |

### Integration / Behaviour Tests (Module 6)

| Test | Description |
|---|---|
| `test_grounding_not_found_no_fabrication` | Agent + mocked toolkit; assert no fabricated fields on `not_found`. |
| `test_grounding_empty_search_no_fabrication` | Agent + mocked empty search; assert no ticket keys in reply. |
| `test_grounding_toolkit_error_reports_error` | Agent + raising toolkit; assert error sentence + stop. |
| `test_grounding_correction_re_calls_tool` | Two-turn dialogue: corrected user → assert second tool call rather than a new fabricated answer. |
| `test_grounding_no_cross_ticket_bleed` | Two consecutive lookups, second `not_found`; assert no fields from first leak into second's reply. |

### Test Data / Fixtures

```python
@pytest.fixture
def stub_jira_toolkit_not_found():
    """JiraToolkit double whose jira_get_issue always returns not_found."""
    tk = AsyncMock(spec=JiraToolkit)
    tk.jira_get_issue.return_value = {
        "status": "not_found",
        "data": None,
        "query": "NAV-99999",
        "message": "Issue NAV-99999 does not exist or is not visible.",
    }
    return tk
```

---

## 5. Acceptance Criteria

This feature is complete when ALL are true:

- [ ] **AC1** — `JiraSpecialist` no longer references
      `system_prompt_template`; its prompt is assembled by
      `PromptBuilder` with at least `jira_workflow` and `jira_grounding`
      layers present in `prompt_builder.layer_names`. The
      `JIRA_SPECIALIST_PROMPT` symbol is fully removed from
      `jira_specialist.py` and a repo-wide grep returns zero references.
- [ ] **AC2** — `JIRA_WORKFLOW_LAYER` and `JIRA_GROUNDING_LAYER` are
      exported from `parrot.bots.prompts` and registered in
      `_DOMAIN_LAYERS`.
- [ ] **AC3** — `JiraToolkit.jira_get_issue`, `jira_search_issues`, and
      `jira_search_users` return the `JiraToolEnvelope` shape
      unconditionally on `ok`/`empty`/`not_found`/`error`. There is no
      `envelope=False` opt-out; the legacy shapes are removed.
- [ ] **AC3b** — The three non-LLM callers identified in Module 5b are
      migrated:
      - `flows/dev_loop/nodes/research.py:546` (re-checks `status`)
      - `flows/dev_loop/nodes/research.py:572-588` (explicit envelope branching)
      - `tests/debug_jira.py:42-44` (reads `issue["data"]`)
      A repository-wide grep confirms no remaining caller of those three
      methods reads `result["issues"]`, `result["total"]`, `issue["key"]`,
      or `issue["fields"]` directly without going through `["data"]`.
- [ ] **AC4** — When the toolkit returns `status="not_found"` for a
      requested key, the agent's reply contains the verbatim phrase
      `No results found for <KEY>` and contains **no** fabricated
      summary, status, assignee, reporter, dates, labels, components,
      accountId, or comments. Verified by
      `test_grounding_not_found_no_fabrication`.
- [ ] **AC5** — When the toolkit returns `status="empty"` for a JQL
      search, the agent's reply contains no ticket keys. Verified by
      `test_grounding_empty_search_no_fabrication`.
- [ ] **AC6** — When the toolkit raises an unexpected exception, the
      agent reply contains `Jira lookup failed` and the agent issues
      no further tool calls in that turn. Verified by
      `test_grounding_toolkit_error_reports_error`.
- [ ] **AC7** — On user contradiction (e.g. "that ticket is not named
      that"), the agent re-calls the toolkit instead of producing a new
      answer from memory. Verified by
      `test_grounding_correction_re_calls_tool`.
- [ ] **AC8** — In a sequence of two lookups where the second returns
      `status="not_found"`, no field value from the first issue appears
      anywhere in the agent's reply about the second. Verified by
      `test_grounding_no_cross_ticket_bleed`.
- [ ] **AC9** — Existing tests in
      `packages/ai-parrot/tests/test_jira_*.py` still pass without
      modification (no behaviour regression for happy-path flows).
- [ ] **AC10** — `Jirachi(JiraSpecialist)` (the production subclass) runs
      without any change to its own definition and exposes both Jira
      layers via `prompt_builder.layer_names`.
- [ ] **AC11** — `pytest packages/ai-parrot/tests/ -v` passes.
- [ ] **AC12** — Documentation updated:
      `docs/jira-specialist-prompt-layers.md` describes the new layer
      stack and how to extend it.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep` or `read`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/prompts/__init__.py:14-37
from parrot.bots.prompts import (
    PromptLayer,
    LayerPriority,
    RenderPhase,
    PromptBuilder,
    get_preset, register_preset, list_presets,
    get_domain_layer,
)

# verified: packages/ai-parrot/src/parrot/bots/prompts/__init__.py:30-37
from parrot.bots.prompts.domain_layers import (
    STRICT_GROUNDING_LAYER,
    KNOWLEDGE_SCOPE_LAYER,
    RAG_GROUNDING_LAYER,
    DATAFRAME_CONTEXT_LAYER,
    SQL_DIALECT_LAYER,
    COMPANY_CONTEXT_LAYER,
    CREW_CONTEXT_LAYER,
)

# verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:34-50
from parrot.bots import Agent
from parrot.models.google import GoogleModel
from parrot_tools.jiratoolkit import JiraToolkit
from parrot.tools.reminder import ReminderToolkit

# verified: packages/ai-parrot/src/parrot/bots/abstract.py:118
from parrot.bots.prompts.builder import PromptBuilder
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):                           # line 22
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    SECURITY = 20
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

class RenderPhase(str, Enum):                           # line 35
    CONFIGURE = "configure"
    REQUEST = "request"

@dataclass(frozen=True)
class PromptLayer:                                      # line 50
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]:        # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:  # line 83
```

```python
# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                    # line 20
    def __init__(self, layers: Optional[List[PromptLayer]] = None)
    @classmethod
    def default(cls) -> PromptBuilder                   # line 45
    @classmethod
    def agent(cls) -> PromptBuilder                     # line 91 — adds STRICT_GROUNDING_LAYER
    def add(self, layer: PromptLayer) -> PromptBuilder  # line 116
    def remove(self, name: str) -> PromptBuilder        # line 128
    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder  # line 140
    def configure(self, context: Dict[str, Any]) -> None               # line 184
    def build(self, context: Dict[str, Any]) -> str                    # line 204
    @property
    def layer_names(self) -> List[str]                  # line 239
```

```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
STRICT_GROUNDING_LAYER: PromptLayer  # line 67   — pandas/data-analysis oriented
_DOMAIN_LAYERS: Dict[str, PromptLayer]  # line 172
def get_domain_layer(name: str) -> PromptLayer  # line 183
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
JIRA_SPECIALIST_PROMPT: str  # line 152 (legacy monolithic; ~310 lines)

class JiraSpecialist(Agent):                            # line 468
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW          # line 489
    system_prompt_template: str = JIRA_SPECIALIST_PROMPT  # line 490 — TO BE REMOVED
    def __init__(self, **kwargs)                        # line 492
    async def post_configure(self) -> None              # line 554 — keep as-is
    def agent_tools(self)                               # line 544
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    _prompt_builder: Optional[PromptBuilder]            # line 176
    @property
    def prompt_builder(self) -> Optional[PromptBuilder] # line 838
    @prompt_builder.setter
    def prompt_builder(self, builder: PromptBuilder)    # line 843
    async def _configure_prompt_builder(self) -> None   # line 847
    def _build_prompt(self, ...) -> str                 # line 898
```

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(...):
    async def jira_get_issue(
        self, issue: str, fields=..., expand=..., structured=...,
        include_history: bool = False, history_page_size: int = 100,
    ) -> Union[Dict[str, Any], Any]                     # line 1159
    async def jira_search_issues(
        self, jql: str, start_at: int = 0, max_results: Optional[int] = 100,
        fields=..., expand=..., json_result: bool = True,
        store_as_dataframe: bool = False, dataframe_name: Optional[str] = None,
        summary_only: bool = False, structured=...,
    ) -> Dict[str, Any]                                 # line 2189
    # Empty search returns: {"total": 0, "issues": [], "pagination": {...}}
    #   (line 2356-2367) — no explicit "empty" signal today
    # Missing key path: self.jira.issue(...) raises JIRAError (caller-handled)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JIRA_WORKFLOW_LAYER` | `_DOMAIN_LAYERS` registry | dict insertion | `domain_layers.py:172` |
| `JIRA_GROUNDING_LAYER` | `_DOMAIN_LAYERS` registry | dict insertion | `domain_layers.py:172` |
| `JiraSpecialist.__init__` | `AbstractBot._prompt_builder` | kwarg `prompt_builder=` | `abstract.py:176, 843` |
| `JiraSpecialist.__init__` | `PromptBuilder.default()` + `.add()` | factory + chained add | `builder.py:45, 116` |
| `JiraToolkit.jira_get_issue` (envelope, sole shape) | LLM tool message + Python callers | structured dict return | `jiratoolkit.py:1159` |
| `JiraToolkit.jira_search_issues` (envelope, sole shape) | LLM tool message + Python callers | structured dict return | `jiratoolkit.py:2189` |
| `JiraToolkit.jira_search_users` (envelope, sole shape) | LLM tool message + Python callers | structured dict return | `jiratoolkit.py:1971` |
| Migrated caller `research.py:546,572` | `JiraToolEnvelope` | direct `["status"]` / `["data"]` reads | `flows/dev_loop/nodes/research.py:546,572-588` |
| Migrated caller `tests/debug_jira.py:42` | `JiraToolEnvelope` | direct `["data"]` reads | `tests/debug_jira.py:42-44` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PromptBuilder.jira()`~~ — not a factory method; use `PromptBuilder.default()` + `.add(get_domain_layer("jira_grounding"))`.
- ~~`JIRA_GROUNDING_LAYER` (today)~~ — does not exist yet; this spec adds it.
- ~~`JIRA_WORKFLOW_LAYER` (today)~~ — does not exist yet; this spec adds it.
- ~~`JiraToolkit.search_users_envelope`~~ — no separate envelope method; the existing methods change shape unconditionally.
- ~~`envelope: bool = True` parameter~~ — does NOT exist. Q1 was resolved as a global flip; there is no opt-out kwarg.
- ~~`JiraToolkit(default_envelope=True)` constructor flag~~ — does NOT exist; the shape is global, not per-instance.
- ~~`get_domain_layer("jira")`~~ — registry keys are `"jira_workflow"` and `"jira_grounding"`, not `"jira"`.
- ~~`PromptLayer.replace()`~~ — replacement is on the `PromptBuilder`, not the layer (`PromptBuilder.replace(name, layer)`, `builder.py:140`).
- ~~`AbstractBot.set_prompt_builder()`~~ — assignment is via the property setter (`abstract.py:843`) or the `prompt_builder=` kwarg.
- ~~`GoogleModel.GEMINI_3_FLASH`~~ — the constant in use is `GEMINI_3_FLASH_PREVIEW` (`jira_specialist.py:489`).
- ~~`JiraToolkit.set_default_envelope`~~ — there is no module-level toggle; envelope is per-call.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Layer authoring: copy the shape of `STRICT_GROUNDING_LAYER`
  (`domain_layers.py:67`) — `frozen=True` dataclass instance, XML-style
  template tag, explicit `phase` and `priority`, optional `condition`.
- Use `LayerPriority.PRE_INSTRUCTIONS + 5` for `JIRA_WORKFLOW_LAYER` and
  `LayerPriority.BEHAVIOR - 5` for `JIRA_GROUNDING_LAYER` so they slot
  before knowledge and just before behaviour respectively.
- Inject the builder in `JiraSpecialist.__init__` via a kwarg the parent
  consumes (the `prompt_builder=` path already exists in `AbstractBot`).
- Keep `injection_probability_threshold = 0.995` (`jira_specialist.py:497`)
  — pytector (deBERTa, English-trained) flags non-English imperative
  phrasing as injection at p > 0.98 by default; the elevated threshold
  is required and unrelated to this spec's English-only sentinel choice.
- The envelope shape change is global and unconditional (Q1 resolved).
  Module 5b is the migration ledger for the three programmatic
  read-callers; AC3b's repo-wide grep gate keeps the change atomic.
  Write-method callers (`jira_add_comment`, `jira_create_issue`,
  `jira_update_issue`, `jira_transition_issue`) are out of scope and
  must remain untouched.
- Logging stays via `self.logger` (project rule, `CLAUDE.md`).

### Known Risks / Gotchas

- **Risk: prompt size blow-up.** Decomposing `JIRA_SPECIALIST_PROMPT`
  into a separate `JIRA_WORKFLOW_LAYER` plus a new `JIRA_GROUNDING_LAYER`
  may push total tokens over the previous footprint. **Mitigation**:
  measure total system-prompt token count before/after on a fixed
  configure context; trim duplicated phrasing between workflow and
  grounding layers; keep the `BEHAVIOR_LAYER` rationale terse.
- **Risk: Gemini Flash ignores the grounding layer if buried.**
  `BEHAVIOR_LAYER` priority 70 sits late; `JIRA_GROUNDING_LAYER` at
  `BEHAVIOR - 5 = 65` renders just before BEHAVIOR but late in the
  prompt overall. **Mitigation**: the layer's template echoes the most
  load-bearing rules (no fabrication, on-empty phrase, on-error phrase)
  in the *first* paragraph so they survive truncation.
- **Risk: Global return-shape flip for `jira_get_issue` /
  `jira_search_issues` / `jira_search_users`.** The shape change is
  unconditional and breaks any caller that reads `result["issues"]`,
  `result["total"]`, `issue["key"]`, or `issue["fields"]` directly.
  **Blast-radius audit (verified at spec time):**
  - 22 write-method callers (`jira_add_comment`, `jira_create_issue`,
    `jira_update_issue`, `jira_transition_issue`) — out of scope, untouched.
  - `flows/dev_loop/nodes/research.py:546` — discards the return; only
    needs the `try/except` updated to also branch on `status != "ok"`.
  - `flows/dev_loop/nodes/research.py:572-588` — currently relies on a
    `result.get("issues") or result.get("results") or result.get("data")`
    fallback chain that *coincidentally* works under the envelope (the
    third clause hits `data`); the spec still requires explicit
    rewrite for correctness, not survival.
  - `tests/debug_jira.py:42-44` — debug script; rewrite to read
    `issue["data"]`.
  - LLM-side: every agent that exposes `JiraToolkit` as a tool receives
    the new shape automatically — that is the goal.
  **Mitigation**: Module 5b explicitly migrates all three programmatic
  call-sites in the same change-set as Module 5; AC3b adds a
  repo-wide grep gate to prevent regressions.
- **Risk: Subclass override drift.** `Jirachi` (or future subclasses)
  may set `system_prompt_template` of their own. **Mitigation**: leave
  `system_prompt_template` accessible for subclasses but document that
  setting it is a no-op when `prompt_builder` is also set; assert in
  `_configure_prompt_builder` and emit a `self.logger.warning`.
- **Risk: Template rendering order**. `PromptBuilder.build()` sorts by
  priority ascending (`builder.py:221`). Verify the assembled prompt
  visually before committing — workflow rules must precede grounding,
  identity must precede everything.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | Spec is internal to existing modules. |

---

## 8. Open Questions

- [x] Should the envelope default flip to `True` globally for all
      `JiraToolkit` callers in this spec, or strictly via a constructor
      flag the agent passes? — *Owner: Juan Rodríguez*: **global flip**.
      Audit confirmed only 3 programmatic read-call sites (research.py
      twice, debug_jira.py once) and zero tests on read methods —
      blast radius is acceptable. The legacy native shapes are removed;
      Module 5b migrates all three call-sites in the same change-set.
- [x] Are the English sentinel phrases (`No results found for <KEY>`,
      `Jira lookup failed: <message>`) the final wording, or should they
      be tuned for tone/length? — *Owner: Juan Rodríguez*: **keep as-is**.
      Both phrases are the verbatim assertion targets in tests T1 and T3
      and acceptance criteria AC4 / AC6. The grounding layer ships
      English-only; channel-specific localisation is explicitly out of
      scope.
- [x] After the migration, should we deprecate `JIRA_SPECIALIST_PROMPT`
      formally (raise on use, removal target version)? — *Owner: Juan
      Rodríguez*: **delete immediately**. Once `JIRA_WORKFLOW_LAYER`
      carries the verified-equivalent text, the literal is removed in
      the same change-set as Module 4 — no `DeprecationWarning`, no
      grace period. Repo-wide grep confirms no external import.

---

## Worktree Strategy

- **Default isolation unit**: per-spec.
- **Justification**: Modules 1-4 mutate the same two files
  (`prompts/domain_layers.py`, `prompts/__init__.py`,
  `bots/jira_specialist.py`); serialising them in one worktree avoids
  trivial merge conflicts. Module 5 (`JiraToolkit`) is in a different
  package and could be parallelised, but its envelope shape is
  consumed by Modules 4 and 6, so sequencing keeps semantics aligned.
- **Worktree creation**:
  ```bash
  git worktree add -b feat-138-jira-analyst-systemprompt-hardening \
    .claude/worktrees/feat-138-jira-analyst-systemprompt-hardening HEAD
  ```
- **Cross-feature dependencies**: none. `STRICT_GROUNDING_LAYER`,
  `PromptBuilder`, and the AbstractBot wiring are all already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-01 | Juan Rodríguez | Initial draft. |
