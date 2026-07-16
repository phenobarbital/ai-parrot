---
type: Wiki Overview
title: FEAT-ontology-entity-extraction — Brainstorm
id: doc:sdd-proposals-feat-ontology-entity-extraction-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Today''s `OntologyRAGMixin.ontology_process` resolves intents and executes
  graph traversals but cannot resolve **named entities mentioned in the user''s query**
  (e.g. *"the team of Jesús"*), and its `post_action: tool_call` only builds a static
  hint via `_build_tool_hint` rather th'
relates_to:
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.knowledge.ontology.authorization
  rel: mentions
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.intent
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tool_dispatcher
  rel: mentions
---

# FEAT-ontology-entity-extraction — Brainstorm

**Status:** brainstorm
**Type:** infrastructure
**Dependencies:** existing `OntologyRAGMixin`, `OntologyIntentResolver`, `IntentRouterMixin`, `CredentialResolver` (per-user OAuth infra), `ToolManager`, `AbstractToolkit`
**Drives:** FEAT-concept-document-authority, FEAT-topic-authority-operational
**Owner:** TBD

---

## Summary

Today's `OntologyRAGMixin.ontology_process` resolves intents and executes graph traversals but cannot resolve **named entities mentioned in the user's query** (e.g. *"the team of Jesús"*), and its `post_action: tool_call` only builds a static hint via `_build_tool_hint` rather than dispatching a real tool invocation. This feature delivers the two missing components — `EntityResolver` and `ToolCallDispatcher` — plus the Pydantic schema additions and `Mixin` orchestration changes required to make `tool_call` a first-class post-action that drives toolkit calls with per-user credentials.

**Driving use case:** an employee-assistant agent answers *"¿en qué está trabajando el equipo de Jesús?"* by (1) extracting *"Jesús"* from the query and resolving it to an `Employee._id`, (2) traversing INBOUND `reports_to` to find subordinates, (3) dispatching `JiraToolkit.search_issues_jql` with the asking user's OAuth credentials, (4) returning an `EnrichedContext` for the LLM to compose. None of (1), (2)→(3) handoff, or (3)'s credential injection works end-to-end today.

---

## Motivation

Three concrete production gaps:

1. **No identity from natural language.** Trigger intents like *"the team of X"* cannot bind `X` to a graph node. The fast-path resolver currently binds only `user_id` from `permission_context`, leaving named entities in the query unresolved.
2. **`post_action: tool_call` is non-functional.** `OntologyRAGMixin._build_tool_hint` returns a descriptive dict; no tool is invoked, no credentials are resolved, no result reaches the LLM. The branch is reserved for future use and provides no production value.
3. **No authorization layer on traversal patterns.** Any user matching a trigger intent can execute any pattern, regardless of whether they should be allowed to ask about the target entity (e.g. asking about another department's team). Authorization on the *intent itself* (vs. on the data) is currently absent.

---

## Goals

- Add declarative **entity extraction** to `TraversalPattern` so YAML specifies which named entities to extract from the query and how to resolve them.
- Implement `EntityResolver` converting natural-language mentions to `_id`s with typed errors (`EntityAmbiguityError`, `EntityNotFoundError`) the Mixin can translate to UX.
- Implement `ToolCallDispatcher` that renders parameterized tool calls from graph results via Jinja2 templates with safe filters (`jql_quote`, `jira_accounts`, `map_attr`, `join_ids`).
- Add declarative **authorization** to traversal patterns: rules `target_is_self`, `target_in_management_chain`, `has_role`, `same_department`.
- Wire `IntentRouterMixin._run_graph_pageindex` to pass `user_context` + `tenant_id` into `ontology_process` (today only the prompt is forwarded).
- All credential handling stays out of toolkits: dispatcher resolves and injects via `_credential_override` kwarg → toolkit statelessness invariant preserved.

## Non-goals

- New entity types or relations in the ontology — live in FEAT-concept-document-authority.
- Operational curation tables — live in FEAT-topic-authority-operational.
- Replacing `OntologyIntentResolver` (kept soft-deprecated, reused as `GRAPH_PAGEINDEX` sub-strategy).
- Cross-tenant entity resolution.
- Replacing existing `_build_tool_hint` consumers; if any code path reads `tool_hint`, it continues to work — the dispatcher result is additive.

---

## Codebase contract

### What exists today

- `parrot.knowledge.ontology.schema`: `TraversalPattern`, `ResolvedIntent`, `EntityDef`, `RelationDef`, `MergedOntology`. Pydantic v2 with `ConfigDict(extra="forbid")`.
- `parrot.knowledge.ontology.intent.OntologyIntentResolver`: fast-path keyword match + LLM path with structured output; binds only `user_id` in `params` today.
- `parrot.knowledge.ontology.mixin.OntologyRAGMixin.ontology_process`: orchestrates resolve → traverse → post_action; the `tool_call` branch calls `_build_tool_hint(graph_result)` and stops.
- `parrot.knowledge.ontology.graph_store.OntologyGraphStore.execute_traversal(ctx, aql, bind_vars, collection_binds)`: AQL executor.
- `parrot.bots.mixins.intent_router.IntentRouterMixin._run_graph_pageindex`: cascades `ontology_process(prompt)` → `graph_store.query(prompt)` → `pageindex_retriever.retrieve(prompt)`; single-arg, no session context propagated.
- `CredentialResolver` (per-user OAuth resolution; provides `AuthorizationRequired` exception with deep-link payload for re-auth flows).
- `ToolManager`, `AbstractToolkit`, `@tool_schema`.

### What this feature builds

- `parrot.knowledge.ontology.entity_resolver` — new module.
- `parrot.knowledge.ontology.tool_dispatcher` — new module.
- `parrot.knowledge.ontology.authorization` — new module.
- Schema extensions in `parrot.knowledge.ontology.schema`:
  - `EntityExtractionRule`
  - `AuthorizationRule`, `AuthorizationSpec`
  - `ToolCallSpec`
  - Extensions to `TraversalPattern` and `ResolvedIntent`.
- Refactor of `OntologyRAGMixin.ontology_process` to compose the new components.
- Minimal hook on `IntentRouterMixin` (or agent convention) to surface `permission_context` + `tenant_id` into `_run_graph_pageindex`.

---

## Proposed design

### Schema additions

```python
class EntityExtractionRule(BaseModel):
    type: str                                  # Ontology entity type, e.g. "Employee"
    resolver: Literal[
        "exact_id_match",
        "fuzzy_name_match",
        "ai_assisted",
        "hybrid_concept_match",                # reserved for FEAT-concept-document-authority
    ]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal[
        "ask_user", "pick_first", "use_context", "fail", "rerank_by_authority"
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
    role: str | None = None                    # required when rule == "has_role"
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


class AuthorizationSpec(BaseModel):
    rules: list[AuthorizationRule] = Field(default_factory=list)
    default_deny: bool = True


class ToolCallSpec(BaseModel):
    toolkit: str
    method: str
    credential_mode: Literal[
        "requesting_user", "service_account", "agent_owner"
    ] = "requesting_user"
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_binding: str
    empty_team_behavior: Literal[
        "short_circuit", "call_anyway", "fail"
    ] = "short_circuit"
    model_config = ConfigDict(extra="forbid")


class TraversalPattern(BaseModel):                # extension
    # ... existing fields ...
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None


class ResolvedIntent(BaseModel):                  # extension
    # ... existing fields ...
    resolved_entities: dict[str, str] = Field(default_factory=dict)
    tool_call: ToolCallSpec | None = None
    denial_reason: str | None = None
```

### EntityResolver

Single async component. Responsibilities:

1. **Mention extraction** per rule:
   - Heuristic: strip trigger phrases from the query, take residual capitalized tokens.
   - AI-assisted: LLM structured output with schema `{rule_name: extracted_value | null}`.
   - Defaults to heuristic; LLM fallback only when heuristic returns nothing or rule says `resolver="ai_assisted"`.

2. **Resolution to `_id`** per rule:
   - `exact_id_match`: AQL `FILTER e.{key_field} == @mention LIMIT 2`.
   - `fuzzy_name_match`: AQL `FILTER LIKE(LOWER(e.name), CONCAT('%', LOWER(@mention), '%')) SORT LENGTH(e.name) ASC LIMIT 10`.
   - `ai_assisted`: shortlist by fuzzy, then LLM picks one.
   - `hybrid_concept_match`: synonyms → vector → LLM (extended in FEAT-concept-document-authority).

3. **Scope filtering** via `permission_ctx`: `same_department` adds `FILTER e.department == @user_department`; `same_tenant` is implicit (tenant DB scoping).

4. **Ambiguity handling** per `ambiguity_strategy`:
   - `ask_user`/`fail` → raise `EntityAmbiguityError(name, candidates)`.
   - `pick_first` → return first by sort order.
   - `use_context` → re-rank using permission_context proximity (same dept → same mgmt chain → others).
   - `rerank_by_authority` → reserved for FEAT-concept-document-authority.

5. **Typed exceptions** for the Mixin to translate:
   - `EntityAmbiguityError(name, candidates)` → `EnrichedContext(source="ambiguous", clarification_needed={...})`.
   - `EntityNotFoundError` → `EnrichedContext(source="entity_not_found")` if `required=True`.

### ToolCallDispatcher

Responsibilities:

1. **Empty-team gate**: short-circuit | call_anyway | fail per `empty_team_behavior`.
2. **Jinja2 rendering** with `StrictUndefined`. Namespaces:
   - `graph`: traversal result (`graph.rows`, `graph.team` as semantic alias).
   - `ctx`: `permission_context` plus `ctx.original_query` for templates that need the raw query.
   - `extras`: intent-supplied extra bindings (date ranges, etc.).
3. **Custom filters**: `jira_accounts`, `jql_quote`, `join_ids`, `map_attr`, `json`. All defense-in-depth escapers.
4. **Credential resolution**:
   - `requesting_user` → `CredentialResolver.resolve(provider=toolkit, user_id=ctx.user_id)`.
   - `service_account` → `CredentialResolver.resolve_service_account(toolkit)`.
   - `agent_owner` → resolved from agent configuration.
5. **Tool invocation** via `ToolManager.get_tool(f"{toolkit}.{method}")` → `tool.execute(**rendered, _credential_override=cred_ctx)`.
6. **Surfaces `AuthorizationRequired` unchanged** so the Mixin can return `EnrichedContext(source="auth_required", auth_prompt=deep_link)`.

### OntologyRAGMixin.ontology_process refactor

New flow:

1. Resolve tenant + ontology (existing).
2. Resolve intent (existing).
3. **NEW** — if pattern has `entity_extraction`:
   - Call `EntityResolver.extract_and_resolve(...)`.
   - On `EntityAmbiguityError` → return `EnrichedContext(source="ambiguous", clarification_needed=...)`.
   - On `EntityNotFoundError` (required) → return `EnrichedContext(source="entity_not_found")`.
   - Bind resolved entities into `intent.params` with naming convention: rule `target_employee` → bind `@target_id`.
4. **NEW** — if pattern has `authorization`:
   - Run rules in order; OR-combine; pass on first match.
   - On deny → return `EnrichedContext(source="denied", denial_reason=...)`.
5. **Cache lookup**: cache key now includes `resolved_entities` (sorted) to prevent cross-target collisions.
6. Execute graph traversal (existing).
7. **Post-action**:
   - `vector_search`: existing.
   - **NEW** `tool_call`: `ToolCallDispatcher.dispatch(spec, graph_result, permission_ctx)`. On `AuthorizationRequired` → return `EnrichedContext(source="auth_required", auth_prompt=...)`. Result bound under `pattern.tool_call.result_binding`.

### IntentRouterMixin integration

Single hook on the mixin (default returns empty dict, overridable on concrete agents):

```python
def _get_permission_context(self) -> dict[str, Any]:
    """Return the current session's permission context. Override on concrete agents."""
    return {}
```

`_run_graph_pageindex` passes it through:

```python
result = await self.ontology_process(
    query=prompt,
    user_context=self._get_permission_context(),
    tenant_id=getattr(self, "_tenant_id", "default"),
)
```

This is a strictly backwards-compatible extension. Agents that don't override `_get_permission_context` keep current behavior.

---

## Example YAML — driving use case

```yaml
team_work_in_progress:
  description: In-progress Jira issues owned by direct reports of a named employee.
  trigger_intents:
    - en qué está trabajando el equipo de
    - qué hace el equipo de
    - issues in progress for the team of
    - subordinados de

  entity_extraction:
    target_employee:
      type: Employee
      resolver: fuzzy_name_match
      scope: same_tenant
      ambiguity_strategy: ask_user
      required: true

  authorization:
    rules:
      - rule: target_is_self
      - rule: target_in_management_chain
      - rule: has_role
        role: hr_manager

  query_template: |
    LET target = DOCUMENT(@target_id)
    FOR teammate IN 1..1 INBOUND target._id @@reports_to
      RETURN {
        employee_id:     teammate.employee_id,
        name:            teammate.name,
        jira_account_id: teammate.jira_account_id,
        manager_name:    target.name
      }

  post_action: tool_call
  tool_call:
    toolkit: JiraToolkit
    method: search_issues_jql
    credential_mode: requesting_user
    parameters:
      jql: |
        project = TROC
        AND status = "In Progress"
        AND assignee in ({{ graph.team | jira_accounts }})
      fields: [summary, status, assignee, components, updated, priority]
      max_results: 50
    result_binding: in_progress_issues
    empty_team_behavior: short_circuit
```

---

## Implementation plan

Each step independently testable and shippable:

1. **Schema extensions** + Pydantic validation + golden YAML loading/round-trip tests.
2. **`EntityResolver`** standalone, with mock graph store and synthetic ontology fixtures.
3. **`ToolCallDispatcher`** standalone with mock `ToolManager` + mock `CredentialResolver`. Includes JQL injection tests (`'Jesús" OR project="OTHER'` etc.).
4. **Authorization checker** standalone — `_is_in_management_chain` AQL traversal test.
5. **Refactor `OntologyRAGMixin.ontology_process`** to compose 1–4.
6. **Hook into `IntentRouterMixin._run_graph_pageindex`** with `_get_permission_context()` convention.
7. **End-to-end test** against ArangoDB sandbox + `JiraToolkit` mock with per-user OAuth simulation.

---

## Open questions

- **AI-assisted vs heuristic default for entity extraction.** Pure heuristic is fast and deterministic but fails on perífrasis. AI-assisted is slower but robust. **Recommendation:** heuristic first, fall back to LLM when heuristic returns nothing OR confidence < threshold.
- **"Team" semantics ambiguity.** Direct reports vs full department? **Recommendation:** ship two patterns with distinct triggers (`team_work_in_progress_directs` vs `team_work_in_progress_department`), let the LLM path pick when both could match.
- **`AuthorizationRequired` surface across channels.** Telegram deep-link is solved; AgenTalk WebSocket and MS Teams need a different UX. Document as known limitation; defer to a follow-up.
- **Ambiguity UX in Telegram.** When `EntityAmbiguityError` surfaces, do we present numbered options or free-form clarification? **Recommendation:** numbered options with `sendPrompt`-style callback for selection.

---

## Acceptance criteria

- A YAML pattern with `entity_extraction`, `authorization`, and `tool_call` loads, validates, and round-trips through `OntologyMerger` without loss.
- `EntityResolver` resolves an unambiguous name to a single `_id` without LLM (heuristic path).
- `EntityResolver` raises typed `EntityAmbiguityError` on multiple matches with `ambiguity_strategy=ask_user`; resolves automatically with `use_context` when the asking user shares a department/mgmt chain with exactly one candidate.
- `ToolCallDispatcher` rejects JQL injection attempts (`jql_quote` filter test with adversarial inputs).
- End-to-end: a user query matching `team_work_in_progress` returns an `EnrichedContext` whose `in_progress_issues` field contains real Jira issues fetched with the requesting user's OAuth token.
- Authorization rule `target_in_management_chain` denies cross-org queries; allows transitive subordinate queries up to depth 10.
- An empty graph result with `empty_team_behavior=short_circuit` does NOT call the tool and returns a structured "no team members" context.

---

## Risks

- **Jinja template injection.** Mitigated by `autoescape=False` + explicit per-field escaping filters. No raw `{{ value }}` in dangerous positions.
- **Per-call credential override breaks existing toolkits.** Audit all existing toolkits; refactor any that bind credentials in `__init__` to accept per-call override instead. Ship audit script as part of this feature.
- **Cache poisoning across users.** Cache keys MUST include `(tenant, user, pattern, sorted_resolved_entity_ids)`. Test with two users querying the same pattern with different targets.
- **`OntologyIntentResolver` soft-deprecation drift.** Since the resolver is soft-deprecated, the new behavior must also be reachable via the active `IntentRouterMixin` path. The hook on `_run_graph_pageindex` is the bridge.

---

## References

- `packages/ai-parrot/src/parrot/knowledge/ontology/` — current ontology package.
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` — IntentRouterMixin.
- `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py` — PageIndex integration patterns.
