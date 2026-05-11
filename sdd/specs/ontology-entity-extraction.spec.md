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
| `test_e2e_auth_required_deep_link` | Mocked `CredentialResolver` returns `None` → `AuthorizationRequired` surfaces with `auth_url` → `ContextEnvelope(state="auth_required", auth_prompt.auth_url=…)`. |
| `test_e2e_cache_isolates_targets` | Two users query the same pattern with different targets; second query is NOT served from the first's cache entry. |

### Test Data / Fixtures

```python
# fixtures: synthetic 3-tenant Employee graph
@pytest.fixture
def ontology_fixture(tmp_path) -> MergedOntology:
    """Loads a 5-employee Employee ontology with reports_to edges:
    CEO → CTO → (Jesús Lara, Jesús Pérez) → Junior."""
    ...

@pytest.fixture
def jira_toolkit_mock():
    """JiraToolkit subclass with mocked _pre_execute + jira_search_issues
    that records call kwargs (including _permission_context) for assertion."""
    ...

@pytest.fixture
def credential_resolver_mock():
    """Returns a token for user_id='alice', None for user_id='charlie'
    (to exercise AuthorizationRequired path)."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] A YAML pattern with `entity_extraction`, `authorization`, and `tool_call` sections loads, validates, and round-trips through `OntologyMerger` without loss.
- [ ] `EntityResolver.extract_and_resolve` resolves an unambiguous name to a single `_id` without invoking an LLM (heuristic path).
- [ ] `EntityResolver` raises `EntityAmbiguityError(name, candidates)` on multiple matches when `ambiguity_strategy=ask_user`; resolves automatically with `use_context` when the asking user shares a department or management chain with exactly one candidate.
- [ ] `ToolCallDispatcher.dispatch` renders Jinja2 templates with `StrictUndefined` and rejects JQL-injection inputs (`jql_quote` adversarial test passes).
- [ ] `ToolCallDispatcher.dispatch` forwards `_permission_context` to the tool call, and `JiraToolkit._pre_execute` (line 866) successfully reads it and resolves user-scoped OAuth via its own `CredentialResolver`.
- [ ] `AuthorizationChecker` denies cross-organization queries via `target_in_management_chain`; allows transitive subordinate queries up to depth 10.
- [ ] An empty graph result with `empty_team_behavior=short_circuit` does NOT call the tool and returns `ContextEnvelope` with a structured "no team members" outcome.
- [ ] `OntologyRAGMixin.ontology_process` returns `ContextEnvelope` for ALL paths; legacy callers that read `result.graph_context` are migrated to `result.context.graph_context`.
- [ ] `OntologyCache.build_key` produces distinct keys for two users querying the same pattern with different `resolved_entities` values; backwards-compatible call (no `resolved_entities`) produces today's key shape exactly.
- [ ] `IntentRouterMixin._run_graph_pageindex` forwards `user_context` and `tenant_id` to `ontology_process` via `_get_permission_context()`; the silent `try/except Exception: pass` is replaced with a narrow, logged catch.
- [ ] End-to-end test: a user query matching `team_work_in_progress` returns a `ContextEnvelope.tool_result["in_progress_issues"]` populated with mocked Jira issues fetched with the requesting user's OAuth credentials.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_entity_resolver.py tests/knowledge/test_authorization.py tests/knowledge/test_tool_dispatcher.py tests/knowledge/test_ontology_mixin.py -v`.
- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py -v`.
- [ ] No regression in `tests/test_intent_router_e2e.py` and `tests/knowledge/test_ontology_integration.py`.
- [ ] `OntologyIntentResolver` remains untouched (soft-deprecated path still works).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Confirmed via grep + read on 2026-05-11 against branch dev.
from parrot.knowledge.ontology.schema import (
    TraversalPattern,         # schema.py:131
    ResolvedIntent,           # schema.py:279
    EntityDef,                # schema.py:39
    RelationDef,              # schema.py:106
    MergedOntology,           # schema.py:185
    EnrichedContext,          # schema.py:303
)
from parrot.knowledge.ontology.mixin import OntologyRAGMixin           # mixin.py:27
from parrot.knowledge.ontology.intent import OntologyIntentResolver    # intent.py:48
from parrot.knowledge.ontology.graph_store import OntologyGraphStore   # graph_store.py:33
from parrot.knowledge.ontology.merger import OntologyMerger            # merger.py:26
from parrot.knowledge.ontology.cache import OntologyCache              # cache.py
from parrot.bots.mixins.intent_router import IntentRouterMixin         # intent_router.py:107
from parrot.auth.credentials import (
    CredentialResolver,          # credentials.py:27 (abstract)
    OAuthCredentialResolver,     # credentials.py:49
    StaticCredentialResolver,    # credentials.py:81
    StaticCredentials,           # credentials.py:70 (dataclass)
)
from parrot.auth.exceptions import AuthorizationRequired               # auth/exceptions.py:12
from parrot.tools.manager import ToolManager                           # tools/manager.py:203
from parrot.tools.toolkit import AbstractToolkit                       # tools/toolkit.py:168
from parrot.tools.decorators import tool_schema                        # tools/decorators.py:37
from parrot_tools.jiratoolkit import JiraToolkit                       # package: parrot-ai-tools (parrot_tools.*)
```

### Existing Class Signatures

```python
# parrot/knowledge/ontology/schema.py
class TraversalPattern(BaseModel):                              # line 131
    description: str                                            # line 132+
    trigger_intents: list[str]
    query_template: str
    post_action: Literal[...]   # currently includes "tool_call"
    post_query: str | None
    model_config = ConfigDict(extra="forbid")

class ResolvedIntent(BaseModel):                                # line 279
    action: Literal["graph_query", "vector_only"]
    pattern: str | None
    aql: str | None
    params: dict
    collection_binds: dict
    post_action: str
    post_query: str | None
    source: str

class EnrichedContext(BaseModel):                               # line 303
    source: str
    graph_context: list[dict] | None
    vector_context: list[dict] | None
    tool_hint: str | None
    intent: ResolvedIntent | None
    metadata: dict

# parrot/knowledge/ontology/intent.py
class OntologyIntentResolver:                                   # line 48
    # NOTE: soft-deprecated per intent.py:9 — but still the entry point.
    async def resolve(
        self, query: str, user_context: dict[str, Any]
    ) -> ResolvedIntent:                                        # lines 97-127
        # Binds: params={"user_id": user_context.get("user_id")}   # line 151

# parrot/knowledge/ontology/mixin.py
class OntologyRAGMixin:                                         # line 27
    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext:                                       # lines 65-177
        # Cache key built at line 114:
        #   cache_key = OntologyCache.build_key(tenant_id, user_id, pattern_name)
        # tool_call branch lines 150-151:
        #   elif intent.post_action == "tool_call" and graph_result:
        #       tool_hint = self._build_tool_hint(graph_result)

    @staticmethod
    def _build_tool_hint(graph_result: list[dict[str, Any]]) -> str:   # lines 235-256

# parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:                                       # line 33
    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:                                  # lines 185-223

# parrot/knowledge/ontology/cache.py
class OntologyCache:
    @staticmethod
    def build_key(tenant_id: str, user_id: str, pattern: str) -> str:    # lines 43-55
        # Returns: f"{prefix}:{tenant_id}:{user_id}:{pattern}"

# parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                        # line 107
    async def _run_graph_pageindex(
        self,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> Optional[str]:                                         # lines 615-640
        # Today (line 636): result = await ontology_process(prompt)
        # NOTE: missing user_context and tenant_id args; call wrapped in
        # try/except Exception: pass at line 639 — silently fails in production.

# parrot/auth/credentials.py
class CredentialResolver(ABC):                                  # line 27
    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...    # line 31

    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...         # line 40

    async def is_connected(self, channel: str, user_id: str) -> bool: ...        # line 44

class OAuthCredentialResolver(CredentialResolver):              # line 49
    def __init__(self, oauth_manager: "JiraOAuthManager") -> None: ...           # line 59

class StaticCredentialResolver(CredentialResolver):             # line 81

@dataclass
class StaticCredentials:                                        # line 70
    server_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    auth_type: str = "basic_auth"

# parrot/auth/exceptions.py
class AuthorizationRequired(Exception):                         # line 12
    def __init__(
        self,
        tool_name: str,
        message: str,
        auth_url: Optional[str] = None,
        provider: str = "unknown",
        scopes: Optional[List[str]] = None,
    ) -> None: ...

# parrot/tools/manager.py
class ToolManager:                                              # line 203
    async def get_tool(self, tool_name: str) -> Optional[Any]: ...               # lines 822-832

# parrot/tools/toolkit.py
class AbstractToolkit:                                          # line 168
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...          # lines 261-274
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...    # lines 276-290

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:              # line 866
        # Reads kwargs.get("_permission_context")  (line 878)
        # Reads perm_ctx.user_id, perm_ctx.channel  (lines 891-892)
        # Calls self.credential_resolver.resolve(channel, user_id)  (line 902)
        # On None token → calls self.credential_resolver.get_auth_url(...)  (line 905)
        # Raises AuthorizationRequired(tool_name, message, auth_url, provider, scopes)

    async def jira_search_issues(                               # line 2291
        self,
        jql: str,
        start_at: int = 0,
        max_results: Optional[int] = 100,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
        json_result: bool = True,
        store_as_dataframe: bool = False,
        dataframe_name: Optional[str] = None,
        summary_only: bool = False,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> JiraToolEnvelope: ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EntityResolver.extract_and_resolve` | `OntologyGraphStore.execute_traversal` | AQL fuzzy/exact lookup | `graph_store.py:185` |
| `AuthorizationChecker.check` | `OntologyGraphStore.execute_traversal` | `reports_to` AQL traversal | `graph_store.py:185` |
| `ToolCallDispatcher.dispatch` | `ToolManager.get_tool` | string lookup `f"{toolkit}.{method}"` | `manager.py:822` |
| `ToolCallDispatcher.dispatch` | `AbstractToolkit._pre_execute` | forwards `_permission_context` kwarg | `toolkit.py:261`, `jiratoolkit.py:878` |
| `OntologyRAGMixin.ontology_process` | `EntityResolver`, `AuthorizationChecker`, `ToolCallDispatcher` | composed inside refactored body | `mixin.py:65-177` |
| `OntologyRAGMixin._get_permission_context` | concrete agent override | hook returns dict | new — added in Module 5 |
| `OntologyRAGMixin.ontology_process` | `OntologyCache.build_key` | extended with `resolved_entities` | `cache.py:43` |
| `IntentRouterMixin._run_graph_pageindex` | `OntologyRAGMixin.ontology_process` | forwards `user_context` + `tenant_id` | `intent_router.py:615` |

### Does NOT Exist (Anti-Hallucination)

These look plausible but are NOT in the codebase. Implementation agents MUST NOT reference them:

- ~~`JiraToolkit.search_issues_jql`~~ — actual method is **`jira_search_issues`** (`parrot_tools/jiratoolkit.py:2291`).
- ~~`CredentialResolver.resolve_service_account(toolkit)`~~ — does not exist. Use `resolve(channel, user_id)` for both user and service-account flows; service-account is modeled by `StaticCredentialResolver` (`credentials.py:81`) which ignores `channel`/`user_id`.
- ~~`EnrichedContext.clarification_needed`~~, ~~`EnrichedContext.auth_prompt`~~, ~~`EnrichedContext.denial_reason`~~, ~~`EnrichedContext.tool_result`~~ — none exist. These live on the new `ContextEnvelope`, not on `EnrichedContext`.
- ~~`AbstractToolkit` method-level `_credential_override` kwarg~~ — no precedent in any toolkit. The dispatcher MUST use the existing `_permission_context` kwarg that `_pre_execute` already reads (verified at `jiratoolkit.py:878`).
- ~~`OntologyCache.build_key` already including entities~~ — it does NOT. Current shape: `f"{prefix}:{tenant_id}:{user_id}:{pattern}"`. Module 6 extends it.
- ~~`ontology_process(query=…, user_context=…, tenant_id=…)` working today through `_run_graph_pageindex`~~ — the call site at `intent_router.py:636` is `await ontology_process(prompt)` (single arg); it is wrapped in `try/except Exception: pass` and silently fails. Module 7 fixes this.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first.** Every public method on the new modules is `async`. No blocking I/O in async contexts.
- **Pydantic v2** for all new schema types, with `ConfigDict(extra="forbid")` matching the existing ontology schema conventions.
- **Logger over print.** Use `self.logger = logging.getLogger(__name__)` in each new module.
- **`_pre_execute` is the credential extension point.** The dispatcher MUST forward `_permission_context` to `tool.execute`; the toolkit's own `_pre_execute` handles credential resolution. Do NOT introduce a new kwarg on toolkit methods.
- **`PermissionContext` shape.** The toolkit reads `perm_ctx.user_id` and `perm_ctx.channel` (`jiratoolkit.py:891-892`). The dispatcher must accept either a `PermissionContext` object or build one from `user_context: dict[str, Any]` — pick the existing class if present, otherwise wrap the dict in a simple `SimpleNamespace`-like adapter. Verify the existing class location before locking the contract (see Open Question §8).
- **Jinja2 environment** is per-dispatcher (single instance with registered filters); `autoescape=False` is intentional — outputs are non-HTML query strings; safety is per-filter (`jql_quote`, etc.).
- **AQL parameter binding.** Entity-lookup AQL must use bind variables (`@mention`, `@user_department`), never string interpolation. The `OntologyGraphStore.execute_traversal` API already enforces this — pass values via `bind_vars`.
- **Default-deny authorization.** When no rule matches, `AuthorizationChecker.check` returns `(False, "no authorization rule matched")`. Document this loudly in the module docstring.

### Known Risks / Gotchas

- **Jinja template injection.** Mitigation: `autoescape=False` is paired with explicit per-field escapers; no raw `{{ value }}` lands in security-sensitive positions. Adversarial inputs are in the test matrix.
- **Cache poisoning across users.** Mitigation: `OntologyCache.build_key` extended in Module 6 to include sorted `resolved_entities`. Acceptance criterion `test_cache_key_includes_resolved_entities` validates.
- **Soft-deprecated `OntologyIntentResolver` drift.** The resolver is the entry point of the flow and must NOT be replaced. The new modules sit *between* `resolve()` and `execute_traversal`, leaving the resolver untouched.
- **`_run_graph_pageindex` silent-fail.** Module 7 removes the broad `try/except Exception: pass` for the ontology call path and replaces it with a narrow, logged catch — same fallthrough semantics, but errors are visible.
- **PermissionContext class location.** Open Question §8 — must be resolved before Module 4 lands.
- **Hybrid_concept_match strategy** is reserved for FEAT-concept-document-authority; in this spec, the EntityResolver MUST raise `NotImplementedError` (with a clear message pointing to the parent feature) when this strategy is configured.
- **Edge cases & error handling** (per brainstorm "Edge Cases & Error Handling"):
  - Empty graph result + `empty_team_behavior` decides short-circuit / call-anyway / fail.
  - `ambiguity_strategy=use_context` re-ranks by dept/mgmt-chain proximity; falls through to `ask_user` when still tied.
  - Credential resolution returns `None` → `AuthorizationRequired` with `auth_url` (toolkit-driven).
  - Jinja `UndefinedError` from `StrictUndefined` → `ContextEnvelope(state="render_error")`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `jinja2` | `>=3.1` | Template rendering of tool parameters with `StrictUndefined` + custom safety filters. Likely already transitive — confirm during Module 4. |
| `pydantic` | `>=2` (already pinned) | Schema for all new models with `ConfigDict(extra="forbid")`. |
| `python-arango` (via existing `OntologyGraphStore`) | unchanged | Auth-rule and entity-lookup AQL traversals. No new dep. |

---

## Worktree Strategy

**Default isolation unit:** `per-spec` (single worktree, sequential tasks).

**Rationale:** Internal task parallelism is real but small (3 new modules × 2-3 days each plus a Mixin refactor). Coordinating across multiple worktrees on shared schema files (Module 1 is a prerequisite for all others) costs more than the wall-clock savings. One worktree with sequential commits keeps schema additions and Mixin refactor atomic and reviewable as a coherent change.

**Cross-feature dependencies (must merge first or coordinate):** none. FEAT-concept-document-authority and FEAT-topic-authority-operational *consume* this feature's schema additions but are downstream; they should not block this spec. FEAT-156 (`agentsflow-refactor-spec3`) operates on `parrot.core.node.AgentNode`, not the ontology layer — no overlap.

**Worktree creation (after task decomposition):**
```bash
git checkout dev && git pull --ff-only origin dev
git worktree add -b feat-158-ontology-entity-extraction \
  .claude/worktrees/feat-158-ontology-entity-extraction HEAD
```

---

## 8. Open Questions

> Questions resolved during brainstorm and §4 research are marked `[x]` and carried forward verbatim. Items remaining unresolved are `[ ]`.

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Coupling of EntityResolver + ToolCallDispatcher + Authorization — *Resolved in brainstorm*: ship as a single bundled feature (Option A).
- [x] Resolution strategy surface — *Resolved in brainstorm*: all four strategies (`exact_id_match`, `fuzzy_name_match`, `ai_assisted`, `hybrid_concept_match`) live in one `EntityResolver` with per-rule strategy dispatch. `hybrid_concept_match` is wired but raises `NotImplementedError` until FEAT-concept-document-authority lands.
- [x] `EnrichedContext` extension approach — *Resolved in brainstorm*: introduce a new `ContextEnvelope` Pydantic model wrapping `EnrichedContext`. `EnrichedContext` itself is untouched.
- [x] Return type of `ontology_process` — *Resolved during §3 spec discussion*: widen to `ContextEnvelope` for ALL paths. Callers reading `.graph_context` directly migrate to `.context.graph_context`. The previous `EnrichedContext` is reachable as `envelope.context` and is `None` only for non-`state="ok"` envelopes.
- [x] Tool method naming — *Resolved in brainstorm*: use real method names (`jira_search_issues`); no rename in this feature.
- [x] Credential injection mechanism — *Resolved in brainstorm + refined via §4 research*: extend the existing `_pre_execute` extension point. Specifically, the dispatcher forwards `_permission_context` to `tool.execute`; the toolkit's own `_pre_execute` (e.g., `JiraToolkit._pre_execute` at `jiratoolkit.py:866`) reads it and resolves credentials via its own injected `CredentialResolver`. No new kwarg on toolkit methods; no new convention key — the existing `_permission_context` channel is sufficient.
- [x] Router → ontology gap — *Resolved in brainstorm + verified at `intent_router.py:636-639`*: add `_get_permission_context()` hook to `OntologyRAGMixin` (defaults to `{}`); `_run_graph_pageindex` forwards `self._get_permission_context()` + `getattr(self, "_tenant_id", "default")` to `ontology_process`. Replace the broad `try/except Exception: pass` with a narrow, logged catch (same fallthrough behaviour, visible errors).
- [x] `CredentialResolver` channel string for Jira — *Resolved during §4 research*: the channel string is provided per-toolkit by the toolkit's own configuration (`JiraToolkit` uses its `_permission_context.channel` value, set by the caller). The dispatcher does NOT pick the channel — it only forwards `_permission_context`. No design impact on this feature.

Genuinely unresolved (do not block spec, may be resolved during implementation):

- [x] `PermissionContext` class location — *Owner: Module 4 implementer*: identify the existing `PermissionContext` type used in production (read by `JiraToolkit._pre_execute` at `jiratoolkit.py:891`). The dispatcher must either accept that type directly or wrap a dict in a compatible adapter. Resolve before Module 4 PR.: I think is on parrot.auth.permission
- [ ] Per-rule LLM threshold for `ai_assisted` resolution — *Owner: Module 2 implementer*: confidence threshold for heuristic→LLM fallback. Should this live in `EntityExtractionRule` (per-rule) or in a global `ResolverConfig`? Recommendation: start with a single module-level constant; promote to per-rule only if a real pattern demands it.
- [ ] Ambiguity UX across channels — *Owner: integrations team, follow-up issue*: Telegram has `sendPrompt`-style callbacks; AgenTalk WebSocket and MS Teams do not. v1 ships Telegram-only ambiguity UX; AgenTalk/Teams receive raw `ContextEnvelope(state="ambiguous")` and the agent's prompt layer handles fallback rendering. Document as known limitation; create a follow-up ticket post-merge.
- [ ] Empty-team semantics — *Owner: YAML pattern authors*: "team" can mean direct reports or full department. Two patterns with distinct triggers (`team_work_in_progress_directs` vs. `team_work_in_progress_department`) is the recommended convention; not a code change.
- [ ] Toolkit credential-binding audit — *Owner: Module 4 implementer, scoped down*: since we are NOT introducing a new kwarg, the full audit promised in the brainstorm is moot. The narrower check is: confirm no other toolkit binds OAuth in `__init__` in a way that would conflict with the `_pre_execute`-driven path. Spot-check 3–5 toolkits; document findings inline in the dispatcher module docstring.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesús Lara | Initial draft. Carries forward `ontology-entity-extraction.brainstorm.md` (Option A) with credential-injection design refined via `jiratoolkit.py:866-902` codebase research. |
