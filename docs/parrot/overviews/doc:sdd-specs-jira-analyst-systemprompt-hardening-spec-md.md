---
type: Wiki Overview
title: 'Feature Specification: Jira Analyst System Prompt Hardening'
id: doc:sdd-specs-jira-analyst-systemprompt-hardening-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: JiraSpecialist instances using `gemini-3-flash-preview` hallucinate invented
  Jira
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.domain_layers
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.tools.reminder
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# Feature Specification: Jira Analyst System Prompt Hardening

**Feature ID**: FEAT-139
**Date**: 2026-05-01
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

JiraSpecialist instances using `gemini-3-flash-preview` hallucinate invented Jira
tickets and fabricated Jira information when:

1. **No tool response**: A Jira tool call returns empty results, an error, or `None`
   — the LLM fills the gap with plausible-looking but fake ticket keys, summaries,
   statuses, and assignees.
2. **No connection to Jira**: When the JIRA client cannot reach the server (network
   error, DNS failure, service down), unhandled exceptions surface as generic errors.
   The LLM then "remembers" tickets from prior conversation turns or training data
   and presents them as real.
3. **Expired OAuth2 credentials**: When OAuth2 3LO tokens expire mid-session, the
   `AuthorizationRequired` result is returned but the system prompt lacks explicit
   instructions on how to handle it — the LLM may attempt to continue answering
   from memory instead of surfacing the auth error.

The current `JIRA_SPECIALIST_PROMPT` is a 310-line monolithic string assigned to
`system_prompt_template`. It contains some anti-hallucination guidance (fresh-turn
rule, error reporting directive) but lacks the explicit, structured grounding rules
that the codebase already provides for data-analysis agents via
`STRICT_GROUNDING_LAYER` and `RAG_GROUNDING_LAYER`.

### Goals

- Eliminate hallucinated Jira ticket data (keys, summaries, statuses, assignees,
  dates, comments) by adding explicit anti-hallucination rules to the system prompt.
- Migrate JiraSpecialist from monolithic `system_prompt_template` to `PromptBuilder`
  with composable layers, enabling reuse of the new grounding layer across future
  Jira-related agents.
- Improve JiraToolkit error messages so the LLM receives clear, actionable error
  descriptions (especially for expired OAuth2 credentials and connection failures).
- Ensure the LLM hard-stops on tool errors rather than fabricating fallback data.

### Non-Goals (explicitly out of scope)

- Rewriting the entire JiraSpecialist system prompt — the existing domain logic
  (standup flows, assignment intake, interaction patterns) is preserved as-is.
- Changing the LLM model from gemini-3-flash-preview.
- Adding retry logic or automatic token refresh in JiraToolkit (separate concern).
- Modifying the `PromptBuilder` or `PromptLayer` core classes.

---

## 2. Architectural Design

### Overview

The solution has three parts:

1. **New `JIRA_GROUNDING_LAYER`** — A domain-specific `PromptLayer` in
   `domain_layers.py` containing explicit anti-hallucination rules for Jira agents.
   Modeled after the existing `STRICT_GROUNDING_LAYER` but tailored for tool-using
   agents that interact with external APIs (not dataframes).

2. **Migrate JiraSpecialist to PromptBuilder** — Replace the monolithic
   `system_prompt_template = JIRA_SPECIALIST_PROMPT` with a `PromptBuilder` that
   composes the existing identity/security/tools layers plus a new `CUSTOM`-priority
   layer containing the Jira-specific operational rules (standup flow, interaction
   patterns, etc.) plus the new `JIRA_GROUNDING_LAYER`.

3. **Improve JiraToolkit error surfaces** — Wrap common failure modes (connection
   errors, HTTP 401/403, expired tokens) with clear error messages that explicitly
   tell the LLM what went wrong and that it must NOT fabricate data.

### Component Diagram

```
PromptBuilder.default()
  ├── IDENTITY_LAYER (10)        ← name, role, goal, backstory
  ├── PRE_INSTRUCTIONS (15)      ← pre_instructions
  ├── SECURITY_LAYER (20)        ← security policy
  ├── KNOWLEDGE_LAYER (30)       ← knowledge_context (if any)
  ├── USER_SESSION_LAYER (40)    ← user_context + chat_history
  ├── TOOLS_LAYER (50)           ← tool policy
  ├── OUTPUT_LAYER (60)          ← output format
  ├── JIRA_GROUNDING_LAYER (65)  ← NEW: anti-hallucination for Jira  ← NEW
  ├── BEHAVIOR_LAYER (70)        ← rationale
  └── JIRA_OPERATIONS_LAYER (80) ← NEW: standup, assignment, interaction rules
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PromptBuilder` | uses | Factory + `add()` for custom layers |
| `PromptLayer` | uses | Dataclass for layer definition |
| `domain_layers.py` | extends | Add `JIRA_GROUNDING_LAYER` to registry |
| `JiraSpecialist` | modifies | Replace `system_prompt_template` with `_prompt_builder` |
| `JiraToolkit._pre_execute` | modifies | Improve error messages for expired tokens |
| `JiraToolkit` tool methods | modifies | Wrap connection errors with clear messages |
| `AbstractBot._prompt_builder` | uses | Existing property on base class |

### Data Models

No new data models required. Uses existing `PromptLayer` dataclass and
`ToolResult` model.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
JIRA_GROUNDING_LAYER: PromptLayer  # Anti-hallucination layer for Jira agents

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
JIRA_OPERATIONS_LAYER: PromptLayer  # Jira operational rules (standup, etc.)
```

---

## 3. Module Breakdown

### Module 1: JIRA_GROUNDING_LAYER

- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
- **Responsibility**: Define a new `PromptLayer` with anti-hallucination rules
  specific to Jira tool-using agents. Rules must cover:
  - Never invent ticket keys, summaries, statuses, assignees, dates, or comments
  - Tool output is the ONLY source of truth for Jira data
  - Empty/error tool results → explicit "no data" response, never fabrication
  - Authorization failures → surface the auth URL, never continue from memory
  - Connection failures → report the error, never substitute cached data
- **Depends on**: `layers.py` (PromptLayer, LayerPriority, RenderPhase)

### Module 2: JIRA_OPERATIONS_LAYER

- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
- **Responsibility**: Extract the operational rules from `JIRA_SPECIALIST_PROMPT`
  (standup flow, assignment intake, interaction patterns, cancellation rule,
  fresh-turn rule, ask_human patterns) into a composable `PromptLayer` at
  `CUSTOM` priority. The existing prompt text is preserved; it is just moved
  from a monolithic string into a layer.
- **Depends on**: Module 1

### Module 3: JiraSpecialist PromptBuilder Migration

- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Replace `system_prompt_template: str = JIRA_SPECIALIST_PROMPT`
  with `_prompt_builder = PromptBuilder.default()` plus `.add(JIRA_GROUNDING_LAYER)`
  and `.add(JIRA_OPERATIONS_LAYER)`. Ensure the two-phase rendering works with
  JiraSpecialist's `post_configure()` lifecycle.
- **Depends on**: Module 1, Module 2

### Module 4: JiraToolkit Error Message Hardening

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: Wrap tool method exceptions with clear, LLM-facing error
  messages. Specifically:
  - Connection errors (ConnectionError, Timeout) → "Jira is unreachable. Do NOT
    invent data. Report this error to the user."
  - HTTP 401/403 → "Jira credentials are expired or invalid. Ask the user to
    re-authorize. Do NOT use cached or remembered ticket data."
  - Generic JIRA API errors → structured error dict with `error` key and explicit
    anti-fabrication instruction.
- **Depends on**: none (independent of prompt changes)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_jira_grounding_layer_renders` | Module 1 | Layer renders anti-hallucination rules |
| `test_jira_grounding_layer_priority` | Module 1 | Priority is between OUTPUT and BEHAVIOR |
| `test_jira_operations_layer_renders` | Module 2 | Operations layer renders standup/interaction rules |
| `test_jira_operations_layer_has_fresh_turn_rule` | Module 2 | Contains fresh-turn rule text |
| `test_jira_operations_layer_has_cancellation_rule` | Module 2 | Contains cancellation rule text |
| `test_jiraspecialist_uses_prompt_builder` | Module 3 | `_prompt_builder` is not None |
| `test_jiraspecialist_prompt_contains_grounding` | Module 3 | Built prompt includes grounding rules |
| `test_jiraspecialist_prompt_contains_operations` | Module 3 | Built prompt includes operational rules |
| `test_jiratoolkit_connection_error_message` | Module 4 | Connection error returns clear message |
| `test_jiratoolkit_auth_expired_error_message` | Module 4 | Auth error includes anti-fabrication text |

### Integration Tests

| Test | Description |
|---|---|
| `test_jiraspecialist_full_prompt_assembly` | PromptBuilder produces a complete prompt with all layers in correct order |

### Test Data / Fixtures

```python
@pytest.fixture
def jira_prompt_builder():
    """PromptBuilder configured like JiraSpecialist."""
    from parrot.bots.prompts.builder import PromptBuilder
    from parrot.bots.prompts.domain_layers import (
        JIRA_GROUNDING_LAYER,
        JIRA_OPERATIONS_LAYER,
    )
    builder = PromptBuilder.default()
    builder.add(JIRA_GROUNDING_LAYER)
    builder.add(JIRA_OPERATIONS_LAYER)
    return builder
```

---

## 5. Acceptance Criteria

- [ ] JiraSpecialist uses `PromptBuilder` instead of `system_prompt_template`
- [ ] Built system prompt contains explicit anti-hallucination rules for Jira data
- [ ] Anti-hallucination rules cover: ticket keys, summaries, statuses, assignees,
      dates, comments — all must come from tool output only
- [ ] Built prompt includes rules for handling empty tool results (explicit "no data")
- [ ] Built prompt includes rules for handling authorization_required results
- [ ] Built prompt includes rules for handling connection errors
- [ ] All existing operational rules (standup, assignment, cancellation, fresh-turn,
      ask_human patterns) are preserved in the built prompt
- [ ] JiraToolkit connection errors return clear, LLM-facing error messages
- [ ] JiraToolkit auth expiration errors include anti-fabrication instruction text
- [ ] `JIRA_GROUNDING_LAYER` is registered in `_DOMAIN_LAYERS` registry
- [ ] All unit tests pass
- [ ] No breaking changes to JiraSpecialist subclasses (e.g. Jirachi)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.

### Verified Imports

```python
# Prompt layer system
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:22,35,50

from parrot.bots.prompts.builder import PromptBuilder
# verified: packages/ai-parrot/src/parrot/bots/prompts/builder.py:20

from parrot.bots.prompts.domain_layers import STRICT_GROUNDING_LAYER
# verified: packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67

from parrot.auth.exceptions import AuthorizationRequired
# verified: packages/ai-parrot/src/parrot/auth/exceptions.py:12
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):  # line 22
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    SECURITY = 20
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

class RenderPhase(str, Enum):  # line 35
    CONFIGURE = "configure"
    REQUEST = "request"

@dataclass(frozen=True)
class PromptLayer:  # line 50
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]:  # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:  # line 83

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:  # line 20
    def __init__(self, layers: Optional[List[PromptLayer]] = None):  # line 35
    @classmethod
    def default(cls) -> PromptBuilder:  # line 44
    @classmethod
    def agent(cls) -> PromptBuilder:  # line 91 — adds STRICT_GROUNDING_LAYER
    def add(self, layer: PromptLayer) -> PromptBuilder:  # line 116
    def remove(self, name: str) -> PromptBuilder:  # line 128
    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder:  # line 140
    def clone(self) -> PromptBuilder:  # line 172
    def configure(self, context: Dict[str, Any]) -> None:  # line 184
    def build(self, context: Dict[str, Any]) -> str:  # line 204

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    _prompt_builder: Optional[PromptBuilder] = None  # line 176
    @property
    def prompt_builder(self) -> Optional[PromptBuilder]:  # line 838
    @prompt_builder.setter
    def prompt_builder(self, builder: PromptBuilder) -> None:  # line 842
    async def _configure_prompt_builder(self) -> None:  # line 847

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):  # line 468
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW  # line 489
    system_prompt_template: str = JIRA_SPECIALIST_PROMPT  # line 490
    def __init__(self, **kwargs):  # line 492
    async def post_configure(self) -> None:  # line 554

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):  # line 609
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 845
    # Raises AuthorizationRequired at lines 859, 873, 889

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    # Catches AuthorizationRequired at line 1199
    # Returns ToolResult(status='authorization_required', ...) at line 1205

# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception):  # line 12
    tool_name: str
    message: str
    auth_url: Optional[str]
    provider: str
    scopes: List[str]
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JIRA_GROUNDING_LAYER` | `PromptBuilder.add()` | method call | `builder.py:116` |
| `JIRA_OPERATIONS_LAYER` | `PromptBuilder.add()` | method call | `builder.py:116` |
| `JiraSpecialist._prompt_builder` | `AbstractBot._prompt_builder` | class attribute | `abstract.py:176` |
| `JiraSpecialist._prompt_builder` | `AbstractBot._configure_prompt_builder()` | lifecycle hook | `abstract.py:847` |
| `_DOMAIN_LAYERS` registry | `JIRA_GROUNDING_LAYER` | dict entry | `domain_layers.py:172` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PromptBuilder.jira()`~~ — no Jira-specific factory method exists
- ~~`JiraSpecialist._prompt_builder`~~ — currently `None` (inherited default);
  JiraSpecialist uses `system_prompt_template` instead
- ~~`JIRA_GROUNDING_LAYER`~~ — does not exist yet; must be created
- ~~`JIRA_OPERATIONS_LAYER`~~ — does not exist yet; must be created
- ~~`JiraToolkit._handle_connection_error()`~~ — no such method; errors currently
  bubble up as raw exceptions

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow the `STRICT_GROUNDING_LAYER` pattern in `domain_layers.py:67-102` for
  the new `JIRA_GROUNDING_LAYER` — same XML-tagged template structure, same
  `CONFIGURE` phase.
- Use `LayerPriority.BEHAVIOR - 5` (= 65) for the grounding layer, matching the
  pattern used by `STRICT_GROUNDING_LAYER` and `RAG_GROUNDING_LAYER`.
- Use `LayerPriority.CUSTOM` (= 80) for the operations layer.
- When migrating to `PromptBuilder`, the `_prompt_builder` class attribute on
  JiraSpecialist replaces `system_prompt_template`. The base class
  `AbstractBot._configure_prompt_builder()` handles the two-phase lifecycle
  automatically — no manual `configure()` call needed in JiraSpecialist.
- JiraToolkit error wrapping should use the existing pattern: return a `dict` with
  an `"error"` key from tool methods rather than raising (for handled failures).

### Known Risks / Gotchas

- **JiraSpecialist subclasses** (e.g., `Jirachi`): Any subclass that references
  `system_prompt_template` directly will break. Check all subclasses and update
  them to use `_prompt_builder` or at minimum ensure they don't override
  `system_prompt_template`.
- **Prompt length**: Adding a grounding layer increases prompt token count. Gemini
  Flash has a large context window (1M tokens) so this is not a concern, but the
  layer text should be concise (target < 500 words).
- **Two-phase rendering**: The `JIRA_OPERATIONS_LAYER` uses `RenderPhase.CONFIGURE`
  because its content is static. Do not use `$variable` placeholders unless they
  are resolved during `configure()`.
- **Backward compatibility**: If `system_prompt_template` and `_prompt_builder` are
  both set, the base class logic must be checked to understand precedence. Based on
  `abstract.py:1059`, `_prompt_builder` is used when set; `system_prompt_template`
  is the fallback.

### External Dependencies

No new external dependencies required.

---

## 8. Open Questions

- [ ] Should we add a `PromptBuilder.jira()` factory method (like `.agent()` and
      `.rag()`) or just compose the builder inline in JiraSpecialist? — *Owner: Jesus*
- [ ] Are there other JiraSpecialist subclasses besides Jirachi that need updating?
      — *Owner: implementer (grep for `JiraSpecialist` subclasses)*
- [ ] Should the `JIRA_GROUNDING_LAYER` be language-specific (Spanish) to match
      the agent's operating language, or English-only (LLMs understand English
      instructions regardless of output language)? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All four modules modify files in two packages (`ai-parrot` and `ai-parrot-tools`)
  and share the same prompt layer definitions. Sequential execution avoids conflicts.
- **Cross-feature dependencies**: None. This spec is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-01 | Jesus Lara | Initial draft |
