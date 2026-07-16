---
type: Wiki Overview
title: 'Feature Specification: Ontology Entity Extraction & Tool-Call Dispatch'
id: doc:sdd-specs-ontology-entity-extraction-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '1. **Named entities in queries cannot be resolved to graph nodes.** `OntologyIntentResolver.resolve(query,
  user_context)` (`intent.py:97-127`) binds only `params={"user_id": user_context.get("user_id")}`
  (`intent.py:151`). A query like *"¿en qué está trabajando el equipo de Jesús'
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.core
  rel: mentions
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.intent
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Ontology Entity Extraction & Tool-Call Dispatch

**Feature ID**: FEAT-158
**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`OntologyRAGMixin.ontology_process` (`packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:65-177`) resolves intents and runs graph traversals, but two production paths are dead today:

1. **Named entities in queries cannot be resolved to graph nodes.** `OntologyIntentResolver.resolve(query, user_context)` (`intent.py:97-127`) binds only `params={"user_id": user_context.get("user_id")}` (`intent.py:151`). A query like *"¿en qué está trabajando el equipo de Jesús?"* leaves *"Jesús"* unbound — the AQL has no `@target_id` to traverse from.

2. **`post_action: tool_call` is non-functional.** In `ontology_process` (`mixin.py:150-151`), the branch calls `_build_tool_hint(graph_result)` which returns only a descriptive string. No tool is invoked, no per-user OAuth credentials flow, no real result reaches the LLM.

Compounding both: `IntentRouterMixin._run_graph_pageindex` (`intent_router.py:615-640`) invokes `await ontology_process(prompt)` with a single positional arg — but `ontology_process` requires `(query, user_context, tenant_id)`. The call is wrapped in `try/except Exception: pass` (line 639), so the ontology strategy **silently fails in production today** and falls through to direct graph-store queries.

**Driving use case:** an employee-assistant agent answers *"¿en qué está trabajando el equipo de Jesús?"* by (1) extracting *"Jesús"* and resolving it to an `Employee._id`, (2) traversing INBOUND `reports_to` to find subordinates, (3) dispatching `JiraToolkit.jira_search_issues` with the asking user's OAuth credentials, (4) returning a structured result for the LLM to compose.

### Goals

- Add declarative **entity extraction** to `TraversalPattern` so YAML specifies which named entities to extract and how to resolve them.
- Implement `EntityResolver` converting natural-language mentions to `_id`s with four pluggable strategies (`exact_id_match`, `fuzzy_name_match`, `ai_assisted`, `hybrid_concept_match` — reserved for FEAT-concept-document-authority) and typed errors the Mixin can translate to UX.
- Implement `ToolCallDispatcher` that renders parameterized tool calls from graph results via Jinja2 with safety filters (`jql_quote`, `jira_accounts`, `join_ids`, `map_attr`, `json`), and invokes the tool by **forwarding `_permission_context` to the existing `AbstractToolkit._pre_execute` hook**. The toolkit (e.g., `JiraToolkit`) owns its own `CredentialResolver` and resolves credentials via that hook — the dispatcher does NOT resolve credentials itself.
- Add declarative **authorization** at intent level: rules `target_is_self`, `target_in_management_chain`, `has_role`, `same_department`, `always`. OR-combined; default-deny.
- Wire `IntentRouterMixin._run_graph_pageindex` to pass `user_context` + `tenant_id` into `ontology_process` via a new `_get_permission_context()` hook on `OntologyRAGMixin` (defaults to `{}`, overridable on concrete agents).
- Widen `ontology_process` to return a new `ContextEnvelope` wrapping `EnrichedContext` plus state-specific fields (`state`, `clarification`, `denial_reason`, `auth_prompt`, `tool_result`).
- Extend `OntologyCache.build_key` to include resolved entities so cache lookups cannot cross-contaminate users querying the same pattern with different targets.

### Non-Goals (explicitly out of scope)

- New entity types or relations in the ontology — owned by FEAT-concept-document-authority.
- Operational curation tables — owned by FEAT-topic-authority-operational.
- Replacing `OntologyIntentResolver` — kept soft-deprecated, reused as the entry point of the new flow.
- Cross-tenant entity resolution.
- A new `_credential_override` kwarg on toolkit methods. *(Rejected in brainstorm — see proposals/ontology-entity-extraction.brainstorm.md Option A vs. its "_credential_override" alternative. Real toolkits already resolve credentials inside `_pre_execute` via their own injected `CredentialResolver`; the dispatcher only needs to forward `_permission_context`.)*
- Phased ship (extraction-only first, dispatch later). *(Rejected in brainstorm Option B — primary value is dispatch, Phase 1 alone would ship nothing the LLM can use.)*

---

## 2. Architectural Design

### Overview

Three new modules under `parrot/knowledge/ontology/` cooperate inside a refactored `ontology_process`:

- **`entity_resolver.py`** — `EntityResolver` extracts mentions from the query (heuristic + optional LLM fallback) and resolves them to `_id`s via strategy dispatch (`exact_id_match`, `fuzzy_name_match`, `ai_assisted`, `hybrid_concept_match`). Raises `EntityAmbiguityError(name, candidates)` and `EntityNotFoundError(rule)` for the Mixin to translate.
- **`authorization.py`** — `AuthorizationChecker` evaluates `AuthorizationSpec` rules after resolution; OR-combined, default-deny. `target_in_management_chain` uses a bounded AQL traversal (depth ≤ 10) against the `reports_to` edge collection.
- **`tool_dispatcher.py`** — `ToolCallDispatcher` renders parameters via Jinja2 (`StrictUndefined`, `autoescape=False`) with `(graph, ctx, extras)` namespaces and the safety filters listed in §1 Goals. Invokes the tool via `ToolManager.get_tool(...)` and forwards `_permission_context` so the toolkit's own `_pre_execute` resolves user-scoped OAuth credentials.

`OntologyRAGMixin.ontology_process` is refactored to compose these three after intent resolution, before graph traversal (extraction → authorization → cache → traversal → post-action). The return type widens from `EnrichedContext` to a new `ContextEnvelope` that wraps `EnrichedContext` and adds state-specific fields.

`IntentRouterMixin._run_graph_pageindex` is fixed to forward `user_context` and `tenant_id` to `ontology_process`, pulled from a new `_get_permission_context()` hook on `OntologyRAGMixin` (defaults to `{}`).

### Component Diagram

```
User query
   │
   ▼
IntentRouterMixin._run_graph_pageindex
   │  (NEW: forwards user_context + tenant_id)
   ▼
OntologyRAGMixin.ontology_process(query, user_context, tenant_id)
   │
   ├─► OntologyIntentResolver.resolve(query, user_context)   ── intent.py:97 (existing)
   │
   ├─► EntityResolver.extract_and_resolve(pattern, query, user_context)   ── NEW
   │       │
   │       └─► OntologyGraphStore.execute_traversal(ctx, aql, binds)      ── graph_store.py:185 (existing)
   │       │
   │       └─► raises EntityAmbiguityError | EntityNotFoundError ─────────► ContextEnvelope(state=...)
   │
   ├─► AuthorizationChecker.check(pattern.authorization, user_context, resolved_entities)   ── NEW
   │       │
   │       └─► OntologyGraphStore.execute_traversal (for management-chain rule)
   │       │
   │       └─► returns (allowed: bool, denial_reason: str | None) ────────► ContextEnvelope(state="denied")
   │
   ├─► OntologyCache.build_key(tenant, user, pattern, sorted(entities))   ── modified
   │
   ├─► OntologyGraphStore.execute_traversal(...)   ── existing
   │
   └─► Post-action dispatch
           │
           ├─ vector_search   ── existing
           │
           └─ tool_call (NEW)
                   │
                   └─► ToolCallDispatcher.dispatch(spec, graph_result, perm_ctx)
                            │
                            ├─► Jinja2 render of `parameters` with safety filters
                            │
                            └─► ToolManager.get_tool(f"{toolkit}.{method}")
                                       │
                                       └─► tool.execute(**rendered, _permission_context=perm_ctx)
                                                  │
                                                  └─► AbstractToolkit._pre_execute reads perm_ctx,
                                                      calls its own CredentialResolver.resolve(channel, user_id),
                                                      raises AuthorizationRequired with auth_url on miss.
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OntologyIntentResolver` (`intent.py:48`) | uses, unchanged | Entry point of the flow; remains soft-deprecated per `intent.py:9`. |
| `OntologyRAGMixin.ontology_process` (`mixin.py:65`) | modifies | Body refactored to compose EntityResolver + AuthChecker + ToolCallDispatcher. Return type widens to `ContextEnvelope`. `_build_tool_hint` retained as a fallback when `tool_call` spec is absent. |
| `OntologyRAGMixin` (`mixin.py:27`) | extends | New `_get_permission_context()` method (default returns `{}`). |
| `OntologyGraphStore.execute_traversal` (`graph_store.py:185`) | uses, unchanged | Called by EntityResolver for entity lookup AQL and by AuthorizationChecker for management-chain traversal. |
| `OntologyCache.build_key` (`cache.py:43`) | modifies | Extends key to include sorted resolved entities to prevent cross-target cache poisoning. |
| `TraversalPattern`, `ResolvedIntent`, `EnrichedContext` (`schema.py:131/279/303`) | extends | New optional fields on `TraversalPattern` and `ResolvedIntent`; new `ContextEnvelope` wraps `EnrichedContext`. |
| `IntentRouterMixin._run_graph_pageindex` (`intent_router.py:615`) | modifies | Forwards `user_context` and `tenant_id` to `ontology_process`. Removes the silent `try/except Exception: pass` swallow (line 639) for the call path. |
| `CredentialResolver` (`auth/credentials.py:27`) | uses, unchanged | Toolkits own their resolver; dispatcher does not call `.resolve()` directly. |
| `AbstractToolkit._pre_execute` (`toolkit.py:261`) | uses, unchanged | Dispatcher forwards `_permission_context` kwarg; existing toolkits like `JiraToolkit` already read it (`jiratoolkit.py:878`). |
| `AuthorizationRequired` (`auth/exceptions.py:12`) | uses, unchanged | Surfaces through the dispatcher unchanged; mapped into `ContextEnvelope(state="auth_required", auth_prompt=auth_url)`. |
| `ToolManager.get_tool` (`tools/manager.py:822`) | uses, unchanged | Dispatcher's tool resolution path. |
| YAML pattern files under `parrot/knowledge/ontology/` | extends | New optional sections `entity_extraction`, `authorization`, `tool_call`. Backwards compatible — absence preserves today's behavior. |

### Data Models

```python
# parrot/knowledge/ontology/schema.py — new types

class EntityExtractionRule(BaseModel):
    type: str                                      # Ontology entity type, e.g. "Employee"
    resolver: Literal[
        "exact_id_match",
        "fuzzy_name_match",
        "ai_assisted",
        "hybrid_concept_match",                    # reserved for FEAT-concept-document-authority
    ]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal[
        "ask_user", "pick_first", "use_context", "fail", "rerank_by_authority",
    ] = "ask_user"
    required: bool = True
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


class AuthorizationRule(BaseModel):
    rule: Literal[
        "target_is_self",
        "target_in_management_chain",
        "has_role",
        "same_department",
        "always",
    ]
    role: str | None = None                        # required when rule == "has_role"
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


class AuthorizationSpec(BaseModel):
    rules: list[AuthorizationRule] = Field(default_factory=list)
    default_deny: bool = True
    model_config = ConfigDict(extra="forbid")


class ToolCallSpec(BaseModel):
    toolkit: str                                   # e.g., "JiraToolkit"
    method: str                                    # e.g., "jira_search_issues"
    credential_mode: Literal[
        "requesting_user", "service_account", "agent_owner",
    ] = "requesting_user"
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_binding: str
    empty_team_behavior: Literal[
        "short_circuit", "call_anyway", "fail",
    ] = "short_circuit"
    model_config = ConfigDict(extra="forbid")


# Extensions to existing schema types

class TraversalPattern(BaseModel):
    # ... existing fields ...
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None
    model_config = ConfigDict(extra="forbid")


class ResolvedIntent(BaseModel):
    # ... existing fields ...
    resolved_entities: dict[str, str] = Field(default_factory=dict)   # rule_name -> _id
    tool_call: ToolCallSpec | None = None
    denial_reason: str | None = None
    model_config = ConfigDict(extra="forbid")


class ContextEnvelope(BaseModel):
    """Wraps EnrichedContext with state-specific fields for non-happy paths."""
    state: Literal[
        "ok",
        "ambiguous",
        "entity_not_found",
        "denied",
        "auth_required",
        "render_error",
        "tool_failed",
    ]
    context: EnrichedContext | None = None
    clarification: dict[str, Any] | None = None    # {entity_rule, mention, candidates}
    denial_reason: str | None = None
    auth_prompt: dict[str, Any] | None = None      # {provider, auth_url, scopes}
    tool_result: dict[str, Any] | None = None      # bound under spec.result_binding
    error: str | None = None
    model_config = ConfigDict(extra="forbid")
```

### New Public Interfaces

```python
# parrot/knowledge/ontology/entity_resolver.py

class EntityResolver:
    def __init__(
        self,
        graph_store: OntologyGraphStore,
        ontology: MergedOntology,
        llm_client: AbstractClient | None = None,    # required only for ai_assisted/hybrid
    ) -> None: ...

    async def extract_and_resolve(
        self,
        pattern: TraversalPattern,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, str]:
        """Returns rule_name -> resolved _id. Raises EntityAmbiguityError or
        EntityNotFoundError on failure; raises only for `required=True` rules."""
        ...


class EntityAmbiguityError(Exception):
    rule_name: str
    mention: str
    candidates: list[dict[str, Any]]    # [{_id, name, ...display_fields}]


class EntityNotFoundError(Exception):
    rule_name: str
    mention: str | None


# parrot/knowledge/ontology/authorization.py

class AuthorizationChecker:
    def __init__(self, graph_store: OntologyGraphStore) -> None: ...

    async def check(
        self,
        spec: AuthorizationSpec,
        user_context: dict[str, Any],
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> tuple[bool, str | None]:
        """Returns (allowed, denial_reason). Evaluates rules in order;
        first match passes (OR semantics). Default-deny when no rule matches."""
        ...


# parrot/knowledge/ontology/tool_dispatcher.py

class ToolCallDispatcher:
    def __init__(self, tool_manager: ToolManager) -> None: ...

    async def dispatch(
        self,
        spec: ToolCallSpec,
        graph_result: list[dict[str, Any]],
        user_context: dict[str, Any],
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Renders parameters via Jinja2 with (graph, ctx, extras) namespaces
        and safety filters, then invokes the tool via ToolManager.
        Returns {result_binding: tool_output}. Surfaces AuthorizationRequired
        unchanged for the Mixin to translate to ContextEnvelope."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Schema extensions
- **Path**: `parrot/knowledge/ontology/schema.py` (modify)
- **Responsibility**: Add `EntityExtractionRule`, `AuthorizationRule`, `AuthorizationSpec`, `ToolCallSpec`, `ContextEnvelope`. Extend `TraversalPattern` and `ResolvedIntent` with optional fields. All Pydantic v2 with `ConfigDict(extra="forbid")`.
- **Depends on**: (none — pure additions to existing module)

### Module 2: EntityResolver
- **Path**: `parrot/knowledge/ontology/entity_resolver.py` (new)
- **Responsibility**: Mention extraction (heuristic + optional LLM fallback) and `_id` resolution via four strategies. Scope filtering from `user_context`. Typed errors (`EntityAmbiguityError`, `EntityNotFoundError`).
- **Depends on**: Module 1, `OntologyGraphStore`, `MergedOntology`.

### Module 3: AuthorizationChecker
- **Path**: `parrot/knowledge/ontology/authorization.py` (new)
- **Responsibility**: Evaluate `AuthorizationSpec` rules OR-combined; default-deny. `target_in_management_chain` uses bounded AQL traversal (depth ≤ 10) against the `reports_to` edge.
- **Depends on**: Module 1, `OntologyGraphStore`.

### Module 4: ToolCallDispatcher
- **Path**: `parrot/knowledge/ontology/tool_dispatcher.py` (new)
- **Responsibility**: Jinja2 rendering (`StrictUndefined`, `autoescape=False`) of `ToolCallSpec.parameters` with `(graph, ctx, extras)` namespaces and safety filters (`jql_quote`, `jira_accounts`, `join_ids`, `map_attr`, `json`). Tool resolution via `ToolManager.get_tool`. Forwards `_permission_context` so the toolkit's own `_pre_execute` resolves user-scoped credentials. Surfaces `AuthorizationRequired` unchanged.
- **Depends on**: Module 1, `ToolManager`.

### Module 5: OntologyRAGMixin refactor
- **Path**: `parrot/knowledge/ontology/mixin.py` (modify)
- **Responsibility**: Refactor `ontology_process` to compose Modules 2–4 after intent resolution. Add `_get_permission_context()` hook (default `{}`). Widen return type to `ContextEnvelope`. Retain `_build_tool_hint` as fallback when `pattern.tool_call` is absent.
- **Depends on**: Modules 1–4.

### Module 6: Cache key extension
- **Path**: `parrot/knowledge/ontology/cache.py` (modify)
- **Responsibility**: Extend `OntologyCache.build_key` to include sorted resolved entities. Backwards-compatible signature change (add `resolved_entities: dict[str, str] | None = None` parameter).
- **Depends on**: Module 1.

### Module 7: IntentRouterMixin integration
- **Path**: `parrot/bots/mixins/intent_router.py` (modify)
- **Responsibility**: Update `_run_graph_pageindex` (lines 615-640) to forward `user_context` and `tenant_id` to `ontology_process`, pulled from `self._get_permission_context()` and `getattr(self, "_tenant_id", "default")`. Replace the silent `try/except Exception: pass` (line 639) for the ontology call with a narrow catch that logs (we still need to fall through on errors, but not silently).
- **Depends on**: Module 5.

### Module 8: Example YAML pattern + end-to-end test
- **Path**: `packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py` (new), `packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml` (new)
- **Responsibility**: End-to-end test for the driving use case: load a pattern with `entity_extraction` + `authorization` + `tool_call`, exercise the full pipeline against an ArangoDB sandbox + mocked `JiraToolkit`. Asserts the `ContextEnvelope.tool_result["in_progress_issues"]` is populated under the requesting user's OAuth.
- **Depends on**: All prior modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_schema_pattern_loads_full` | Module 1 | YAML with all three new sections (entity_extraction, authorization, tool_call) round-trips through `OntologyMerger` without loss. |
| `test_schema_pattern_loads_minimal` | Module 1 | Pattern without any new sections still loads (backwards compat). |
| `test_schema_authorization_has_role_requires_role` | Module 1 | `rule: has_role` without a `role` field raises Pydantic ValidationError. |
| `test_entityresolver_exact_match` | Module 2 | Unambiguous name resolves to a single `_id` via `exact_id_match` strategy, no LLM call. |
| `test_entityresolver_fuzzy_match_ambiguous` | Module 2 | Multiple matches with `ambiguity_strategy=ask_user` raise `EntityAmbiguityError(name, candidates)`. |
| `test_entityresolver_fuzzy_use_context` | Module 2 | Two candidates, one in user's department; resolver picks the in-department one. |
| `test_entityresolver_not_found_required` | Module 2 | `required=True` rule with no match raises `EntityNotFoundError`. |
| `test_entityresolver_not_found_optional` | Module 2 | `required=False` rule with no match returns without raising. |
| `test_entityresolver_scope_same_department` | Module 2 | `scope=same_department` filters out candidates in other departments. |
| `test_auth_target_is_self_allows` | Module 3 | Requesting user equals target → allowed. |
| `test_auth_target_in_management_chain` | Module 3 | Transitive subordinate at depth 3 → allowed. |
| `test_auth_target_in_management_chain_denies_depth_11` | Module 3 | Beyond depth-10 limit → denied. |
| `test_auth_has_role_allows` | Module 3 | User has `hr_manager` role → allowed. |
| `test_auth_default_deny` | Module 3 | No rule matches → denied with `denial_reason`. |
| `test_dispatcher_renders_basic` | Module 4 | Jinja2 renders `parameters` with `(graph, ctx, extras)` namespaces. |
| `test_dispatcher_strict_undefined_raises` | Module 4 | Missing binding triggers `UndefinedError` → translated to `ContextEnvelope(state="render_error")`. |
| `test_dispatcher_jql_quote_escapes_quotes` | Module 4 | Input `Jesús" OR project="OTHER` is escaped — adversarial test. |
| `test_dispatcher_jira_accounts_validates_shape` | Module 4 | Invalid accountId shape raises before tool call. |
| `test_dispatcher_empty_team_short_circuit` | Module 4 | `empty_team_behavior=short_circuit` with empty graph result → no tool call, returns structured result. |
| `test_dispatcher_forwards_permission_context` | Module 4 | `_permission_context` kwarg reaches `tool.execute`; assert via spy on `AbstractToolkit._pre_execute`. |
| `test_dispatcher_translates_authorization_required` | Module 4 | Toolkit raises `AuthorizationRequired` → caller receives the exception unchanged (Mixin handles translation to `ContextEnvelope`). |
| `test_mixin_ontology_process_happy_path` | Module 5 | Full pipeline: extraction → auth → traversal → tool_call → `ContextEnvelope(state="ok", tool_result=…)`. |
| `test_mixin_ontology_process_ambiguity` | Module 5 | `EntityAmbiguityError` translates to `ContextEnvelope(state="ambiguous", clarification=…)`. |
| `test_mixin_ontology_process_denied` | Module 5 | AuthorizationChecker denies → `ContextEnvelope(state="denied", denial_reason=…)`. |
| `test_mixin_ontology_process_auth_required` | Module 5 | Tool surfaces `AuthorizationRequired` → `ContextEnvelope(state="auth_required", auth_prompt={auth_url, provider, scopes})`. |
| `test_mixin_get_permission_context_default` | Module 5 | Default returns `{}`. |
| `test_cache_key_includes_resolved_entities` | Module 6 | Two users querying same pattern with different target IDs produce distinct cache keys. |
| `test_cache_key_backwards_compat` | Module 6 | Call without `resolved_entities` kwarg produces today's key shape exactly. |
| `test_intent_router_forwards_context` | Module 7 | `_run_graph_pageindex` passes `user_context` + `tenant_id` to `ontology_process` (verified via spy). |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_team_work_in_progress_happy_path` | Driving use case: query *"¿en qué está trabajando el equipo de Jesús?"* with a real ArangoDB fixture and a mocked `JiraToolkit`. Assert `ContextEnvelope.tool_result["in_progress_issues"]` contains the mocked Jira issues, and that the request used the requesting user's OAuth (not a service account). |
| `test_e2e_ambiguous_name_returns_clarification` | Same flow with two `Jesús` candidates → `ContextEnvelope(state="ambiguous", clarification.candidates=[...])`. |
| `test_e2e_denied_cross_department` | User without `hr_manager` role querying another department's manager → `ContextEnvelope(state="denied")`. |

…(truncated)…
