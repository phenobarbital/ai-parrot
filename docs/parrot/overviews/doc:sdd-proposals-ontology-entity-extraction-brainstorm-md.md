---
type: Wiki Overview
title: 'Brainstorm: Ontology Entity Extraction & Tool-Call Dispatch'
id: doc:sdd-proposals-ontology-entity-extraction-brainstorm-md
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
- concept: mod:parrot.tools
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

# Brainstorm: Ontology Entity Extraction & Tool-Call Dispatch

**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`OntologyRAGMixin.ontology_process` resolves intents and runs graph traversals, but two production paths are dead today:

1. **Named entities in queries cannot be resolved to graph nodes.** `OntologyIntentResolver.resolve(query, user_context)` (`intent.py:97-127`) binds only `params={"user_id": user_context.get("user_id")}` (`intent.py:151`). A query like *"¿en qué está trabajando el equipo de Jesús?"* leaves `"Jesús"` unbound — the AQL has no `@target_id` to traverse from.
2. **`post_action: tool_call` is non-functional.** In `OntologyRAGMixin.ontology_process` (`mixin.py:150-151`), the branch calls `_build_tool_hint(graph_result)` which returns a descriptive string. No tool is invoked, no per-user OAuth credentials are resolved, no real result reaches the LLM.

Compounding both: `IntentRouterMixin._run_graph_pageindex` (`intent_router.py:615-640`) invokes `await ontology_process(prompt)` with a SINGLE positional arg — but `ontology_process` requires `(query, user_context, tenant_id)`. The call is wrapped in `try/except Exception: pass` (line 639), so it **silently fails in production today** and falls through to direct graph-store queries.

**Affected users:** any agent built on `IntentRouterMixin` + `OntologyRAGMixin` that wants natural-language entity binding (employee assistants, support triage, document discovery). **Driving use case:** answer *"what is Jesús's team working on?"* by extracting *"Jesús"* → resolving `Employee._id` → traversing INBOUND `reports_to` → dispatching `JiraToolkit.jira_search_issues` with the requesting user's OAuth → returning the issue list.

---

## Constraints & Requirements

- **Backwards compatibility for `_pre_execute`.** The toolkit lifecycle hook (`toolkit.py:261-274`) is already used in production. Any credential-injection mechanism must extend, not replace, it.
- **Toolkit statelessness.** Toolkits must NOT bind OAuth credentials in `__init__`. Per-call credentials only.
- **Tenant scoping.** All graph traversals run under `TenantContext` (`graph_store.execute_traversal`). Entity resolution must respect tenant boundaries.
- **Cache safety.** `OntologyCache.build_key(tenant_id, user_id, pattern_name)` (`cache.py:43-55`) does NOT include resolved entities today — using it as-is would cross-contaminate results between users querying the same pattern with different targets.
- **Authorization on intent, not data.** Pattern matchers must be able to refuse a query before the AQL fires (e.g., HR-only patterns).
- **`AuthorizationRequired` surface preserved.** The auth exception (`auth/exceptions.py:12`) already carries `auth_url`, `provider`, `scopes` for deep-link re-auth flows — we MUST surface it unchanged to UX layers.
- **Pydantic v2 with `extra="forbid"`** for all new schema models, matching existing ontology schema conventions.
- **No LLM call in the heuristic path.** Cost-sensitive deployments must be able to disable AI-assisted resolution without losing the feature.
- **Single bundled feature.** Per Round 1: ship EntityResolver + ToolCallDispatcher + Authorization together, in one spec.

---

## Options Explored

### Option A: Bundled pipeline — EntityResolver + ToolCallDispatcher + AuthChecker, composed by Mixin

Add three cooperating modules under `parrot/knowledge/ontology/` and orchestrate them inside a refactored `ontology_process`:

- **`entity_resolver.py`** — extracts mentions from the query (heuristic with optional LLM fallback), resolves them to `_id`s via four pluggable strategies (`exact_id_match`, `fuzzy_name_match`, `ai_assisted`, `hybrid_concept_match`), applies scope filters from `user_context`, and raises typed errors (`EntityAmbiguityError`, `EntityNotFoundError`).
- **`authorization.py`** — declarative `AuthorizationSpec` evaluated after resolution; rules `target_is_self`, `target_in_management_chain` (transitive AQL traversal), `has_role`, `same_department`, `always`. OR-combined; default-deny.
- **`tool_dispatcher.py`** — Jinja2 (`StrictUndefined`, `autoescape=False`) renders parameterized tool calls from `(graph, ctx, extras)` namespaces with safety filters (`jql_quote`, `jira_accounts`, `join_ids`, `map_attr`, `json`); resolves credentials via `CredentialResolver.resolve(channel, user_id)`; invokes `ToolManager.get_tool(f"{toolkit}.{method}")`.
- **Credential injection** — extends the existing `AbstractToolkit._pre_execute` hook. Dispatcher passes a `_permission_context` kwarg that toolkits already accept; the credential payload rides on that same channel (new key `_resolved_credentials`).
- **`ContextEnvelope`** — a NEW Pydantic model wrapping `EnrichedContext` with the additional states (`ambiguous`, `entity_not_found`, `denied`, `auth_required`, `tool_called`). Leaves `EnrichedContext` untouched.
- **Mixin hook** — `OntologyRAGMixin._get_permission_context()` defaults to `{}`; concrete agents override. `IntentRouterMixin._run_graph_pageindex` becomes `ontology_process(prompt, user_context=self._get_permission_context(), tenant_id=getattr(self, "_tenant_id", "default"))`.

✅ **Pros:**
- Single bundled PR matches the driving use case end-to-end.
- Reuses the existing `_pre_execute` extension point — zero new kwargs on toolkit methods, no audit-and-refactor of every toolkit.
- `ContextEnvelope` wrapper means we never break callers reading `EnrichedContext.graph_context`/`tool_hint`.
- Heuristic-first resolver keeps cost predictable; LLM only on fallback.
- Declarative YAML — non-engineers can author patterns.

❌ **Cons:**
- Three new modules in one PR raise review surface area.
- Jinja2 with `autoescape=False` shifts the safety burden to per-field filters; missing a filter is a security bug.
- `target_in_management_chain` adds an extra AQL traversal per request (mitigable with a small in-memory cache).
- The `_pre_execute` channel becomes polysemic (`_permission_context` now also carries credentials).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jinja2` (≥3.1) | Template rendering of tool params from graph results | Already a transitive dep via several toolkits; use `StrictUndefined` + custom filters. |
| `pydantic` (v2, already pinned) | Schema for `EntityExtractionRule`, `AuthorizationSpec`, `ToolCallSpec`, `ContextEnvelope` | Use `ConfigDict(extra="forbid")` like existing ontology schema. |
| `arango` driver (via existing `OntologyGraphStore`) | Auth-rule AQL traversals + fuzzy/exact entity lookups | No new dep — reuse `execute_traversal(ctx, aql, bind_vars, collection_binds)`. |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/ontology/schema.py` — extend `TraversalPattern` + `ResolvedIntent` (lines 131-152, 279-300).
- `parrot/knowledge/ontology/mixin.py` — refactor `ontology_process` (lines 65-177), wrap `_build_tool_hint` as a fallback only.
- `parrot/knowledge/ontology/graph_store.py:185-223` — `execute_traversal` for entity-lookup AQL.
- `parrot/auth/credentials.py:31` — `CredentialResolver.resolve(channel, user_id)`.
- `parrot/auth/exceptions.py:12` — `AuthorizationRequired(tool_name, message, auth_url, provider, scopes)` surfaces unchanged.
- `parrot/tools/manager.py:822-832` — `ToolManager.get_tool(tool_name)`.
- `parrot/tools/toolkit.py:261-274` — extend `_pre_execute(tool_name, **kwargs)` to consume injected credentials.

---

### Option B: Phased — extraction first, dispatch + authorization later

Split the work into two specs:
- **Phase 1 (this feature):** ship EntityResolver + schema extensions + Mixin hook only. `post_action: tool_call` remains a no-op; pattern authors get entity binding but still no real tool dispatch.
- **Phase 2 (follow-up):** layer ToolCallDispatcher + Authorization on top.

✅ **Pros:**
- Smaller PRs; easier review.
- Entity resolution is useful on its own for `vector_search` post-actions (e.g., resolve target, vector-search around them).
- Decouples the credential-injection refactor from the entity-resolution work — they can move at different paces.

❌ **Cons:**
- Driving use case ("team of Jesús" → Jira issues) stays broken until Phase 2 ships.
- Schema versioning headache: `TraversalPattern.tool_call` is dead config in Phase 1 — either we add the field and ignore it, or we re-do the schema in Phase 2.
- Forces premature commitment to abstractions before the dispatch path is known.

📊 **Effort:** Medium (per phase)

📦 **Libraries / Tools:** Same as Option A, split across two specs.

🔗 **Existing Code to Reuse:** Same as Option A.

---

### Option C: Resolver protocol with registered strategies + plugin-style dispatchers

Define a `Resolver` protocol (`extract`, `resolve` methods) and a `Dispatcher` protocol; register implementations by name. YAML references resolvers/dispatchers by registry key. Adding a new strategy or dispatcher is a single registration call.

```python
@register_resolver("graph_authority")
class GraphAuthorityResolver: ...

@register_dispatcher("airtable")
class AirtableDispatcher: ...
```

✅ **Pros:**
- Cleanest extension story; third-party packages can ship strategies without modifying core.
- Lets `hybrid_concept_match` (reserved for FEAT-concept-document-authority) be added without touching `entity_resolver.py`.
- Naturally separates "credential injection contract" from "graph-store contract."

❌ **Cons:**
- Heavier upfront design — protocol definitions, registry, lifecycle, error contract.
- YAML becomes more verbose: `resolver: graph_authority` vs. `resolver: fuzzy_name_match`.
- We don't have a second dispatcher target on the roadmap. Building plug-in surface before the second consumer arrives is speculative.
- Postpones the driving use case for design refinement.

📊 **Effort:** High

📦 **Libraries / Tools:** Same as Option A, plus a small registry module (no external dep).

🔗 **Existing Code to Reuse:** Same as Option A.

---

## Recommendation

**Option A** is recommended.

It is the only option that delivers the driving use case end-to-end in a single ship. The cited risks (review surface, polysemic `_pre_execute`, Jinja safety) are addressable inside this feature:

- **Review surface** — the three modules are independently testable behind well-typed boundaries (`EntityResolver` → `ResolvedIntent.resolved_entities`, `AuthChecker` → bool + `denial_reason`, `ToolCallDispatcher` → `ContextEnvelope`). Each can land as a separate task within the same spec.
- **Polysemic `_pre_execute`** — confined to a single new convention key `_resolved_credentials` in the existing `_permission_context` payload. Documented in the toolkit base class. We are explicitly trading a small amount of coupling for skipping a full toolkit-API audit, which would balloon the blast radius of this feature.
- **Jinja safety** — explicit filter inventory (`jql_quote`, `jira_accounts`, `join_ids`, `map_attr`, `json`) with adversarial inputs in the test matrix; `autoescape=False` is intentional because the output is non-HTML query strings.

We reject Option B because the *primary* business value is the dispatch, not the binding — Phase 1 alone ships nothing the LLM can actually use. We reject Option C because we have one consumer; building plug-in machinery before the second arrives is speculative. If a second dispatcher target emerges, Option C is a trivial refactor of Option A's `ToolCallDispatcher`.

---

## Feature Description

### User-Facing Behavior

An agent built on `OntologyRAGMixin` + `IntentRouterMixin` becomes able to:

1. Receive *"¿en qué está trabajando el equipo de Jesús?"* and bind *"Jesús"* to a graph node (`Employee/abc123`) automatically.
2. Refuse the query — with a structured `denial_reason` — when the asking user lacks authority (e.g., cross-department probing without `hr_manager` role).
3. Ask for clarification — *"Found 3 Jesús — Lara, Pérez, Romero. Which one?"* — when the name is ambiguous and the strategy is `ask_user`.
4. Dispatch a real Jira/Trello/etc. call **with the requesting user's OAuth token** (not a service account), and return the result as part of the EnrichedContext for the LLM to compose.
5. Surface `AuthorizationRequired` with a deep-link re-auth prompt when the user's OAuth has lapsed.

### Internal Behavior

Pipeline inside `ontology_process(query, user_context, tenant_id)`:

1. **Tenant + ontology resolution** (existing).
2. **Intent resolution** (existing — `OntologyIntentResolver.resolve` with `user_context`).
3. **Entity extraction (NEW)** — if `pattern.entity_extraction` non-empty:
   - For each rule, run the configured resolver (heuristic → LLM fallback when configured).
   - Apply scope filter (`same_tenant`, `same_department`, `anywhere`) from `user_context`.
   - On ambiguity → raise `EntityAmbiguityError`; Mixin returns `ContextEnvelope(state="ambiguous", clarification=…)`.
   - On miss with `required=True` → return `ContextEnvelope(state="entity_not_found")`.
   - Bind into `intent.params` (rule name `target_employee` → bind key `@target_id`).
4. **Authorization (NEW)** — if `pattern.authorization` set:
   - Evaluate rules in order; OR-combine; first match passes; default-deny.
   - On deny → `ContextEnvelope(state="denied", denial_reason=…)`.
5. **Cache lookup** — key now `(tenant, user, pattern, sorted(resolved_entities.items()))` to prevent cross-target collisions.
6. **Graph traversal** (existing — `execute_traversal`).
7. **Post-action**:
   - `vector_search` (existing).
   - `tool_call` (NEW): render parameters via Jinja2 with `(graph, ctx, extras)` namespaces + safety filters; resolve credentials via `CredentialResolver.resolve(channel=toolkit, user_id=...)`; invoke via `ToolManager.get_tool(...)` passing credentials through the `_permission_context` payload that `_pre_execute` reads.
   - Result is bound under `pattern.tool_call.result_binding` inside `ContextEnvelope.tool_result`.

### Edge Cases & Error Handling

- **Empty graph result** (e.g., target has no direct reports) — `empty_team_behavior` decides: `short_circuit` (no tool call, return structured "no members"), `call_anyway` (rare; useful for "show all in-progress in project X"), `fail`.
- **Multiple resolutions, `ambiguity_strategy=use_context`** — re-rank by department / mgmt-chain proximity; pick the unique candidate within the requesting user's department; if still tied, fall through to `ask_user`.
- **Credential resolution returns `None`** — surface as `AuthorizationRequired` with the toolkit's known auth URL (if any) so the UX can deep-link the user to re-auth.
- **Jinja `UndefinedError`** — `StrictUndefined` means a missing binding (e.g., `{{ ctx.user_department }}` when not in context) raises immediately rather than silently producing `"None"` in a JQL string. Caught and returned as `ContextEnvelope(state="render_error", reason=…)`.
- **JQL injection attempt** — `jql_quote` filter escapes single quotes + backslashes; `jira_accounts` filter validates input is a list of valid `accountId` shapes before joining. Adversarial test inputs are part of acceptance criteria.
- **Soft-deprecated `OntologyIntentResolver`** — still the entry point for `_run_graph_pageindex`; the new flow lives inside `ontology_process` regardless of which strategy invoked it.

---

## Capabilities

### New Capabilities
- `ontology-entity-extraction`: declarative named-entity resolution inside ontology patterns, gated authorization, and per-user OAuth tool dispatch.

### Modified Capabilities
- (none — `OntologyRAGMixin` is internal infrastructure; no existing spec governs it directly.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/ontology/schema.py` | extends | New `EntityExtractionRule`, `AuthorizationRule`, `AuthorizationSpec`, `ToolCallSpec`, `ContextEnvelope`; new fields on `TraversalPattern` and `ResolvedIntent`. Pydantic v2, `extra="forbid"`. |
| `parrot/knowledge/ontology/mixin.py` | modifies | `ontology_process` refactor (lines 65-177); `_build_tool_hint` becomes a fallback path, retained for compat. Return type widens from `EnrichedContext` to `EnrichedContext \| ContextEnvelope` (or `ContextEnvelope` wraps `EnrichedContext` — pick one in spec). |
| `parrot/knowledge/ontology/cache.py` | modifies | `OntologyCache.build_key` extended to include sorted resolved entities. |
| `parrot/knowledge/ontology/` (new files) | adds | `entity_resolver.py`, `authorization.py`, `tool_dispatcher.py`. |
| `parrot/bots/mixins/intent_router.py` | modifies | `_run_graph_pageindex` (lines 615-640) starts forwarding `user_context` and `tenant_id`. Adds `_get_permission_context()` convention. |
| `parrot/tools/toolkit.py` | extends (convention) | `_pre_execute` (lines 261-274) docs updated to describe `_resolved_credentials` key in `_permission_context`. No signature change. |
| `parrot_tools/jiratoolkit.py` (and similar) | reuses | `jira_search_issues` (line 2291) — the existing method; dispatcher invokes it via `ToolManager.get_tool("JiraToolkit.jira_search_issues")`. |
| Pattern YAML files under `parrot/knowledge/ontology/` | extends | New optional sections `entity_extraction`, `authorization`, `tool_call`. Backwards compatible — absence preserves today's behavior. |

---

## Code Context

### User-Provided Code

The user provided the prior draft at `sdd/proposals/FEAT-ontology-entity-extraction-brainstorm.md` (untracked). Its core schema sketch carries forward, with the following corrections against the live codebase (see "Does NOT Exist" below).

### Verified Codebase References

#### Classes & Signatures

```python
# parrot/knowledge/ontology/schema.py:131-152
class TraversalPattern(BaseModel):
    description: str
    trigger_intents: list[str]
    query_template: str
    post_action: Literal[...]  # currently includes "tool_call"
    post_query: str | None
    # ConfigDict(extra="forbid")

# parrot/knowledge/ontology/schema.py:279-300
class ResolvedIntent(BaseModel):
    action: Literal["graph_query", "vector_only"]
    pattern: str | None
    aql: str | None
    params: dict
    collection_binds: dict
    post_action: str
    post_query: str | None
    source: str

# parrot/knowledge/ontology/schema.py:303
class EnrichedContext(BaseModel):
    source: str
    graph_context: list[dict] | None
    vector_context: list[dict] | None
    tool_hint: str | None
    intent: ResolvedIntent | None
    metadata: dict

# parrot/knowledge/ontology/intent.py:48
class OntologyIntentResolver:
    async def resolve(
        self, query: str, user_context: dict[str, Any]
    ) -> ResolvedIntent: ...  # line 97-127
    # binds params={"user_id": user_context.get("user_id")}  # line 151
    # NOTE: soft-deprecated per intent.py:9

# parrot/knowledge/ontology/mixin.py:27
class OntologyRAGMixin:
    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext: ...  # lines 65-177
    # cache_key: OntologyCache.build_key(tenant_id, user_id, pattern_name)  # line 114-122
    # tool_call branch:                                                     # lines 150-151
    #     elif intent.post_action == "tool_call" and graph_result:
    #         tool_hint = self._build_tool_hint(graph_result)
    @staticmethod
    def _build_tool_hint(graph_result: list[dict[str, Any]]) -> str: ...    # lines 235-256

# parrot/knowledge/ontology/graph_store.py:33
class OntologyGraphStore:
    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]: ...  # lines 185-223

# parrot/knowledge/ontology/merger.py:26
class OntologyMerger:
    def merge(self, yaml_paths): ...               # line 51
    def merge_definitions(self, definitions): ...  # line 99

# parrot/knowledge/ontology/cache.py:43-55
class OntologyCache:
    @staticmethod
    def build_key(tenant_id: str, user_id: str, pattern: str) -> str:
        return f"{prefix}:{tenant_id}:{user_id}:{pattern}"

# parrot/bots/mixins/intent_router.py:107
class IntentRouterMixin:
    async def _run_graph_pageindex(  # lines 615-640
        self, prompt: str, candidates: list[RouterCandidate],
    ) -> Optional[str]:
        # Today: await ontology_process(prompt)  ← MISSING user_context, tenant_id
        # Wrapped in try/except Exception: pass — silently dead in production.

# parrot/auth/credentials.py:27 (abstract base)
class CredentialResolver:
    async def resolve(
        self, channel: str, user_id: str
    ) -> Optional[Any]: ...  # line 31

# parrot/auth/exceptions.py:12
class AuthorizationRequired(Exception):
    def __init__(
        self,
        tool_name: str,
        message: str,
        auth_url: Optional[str] = None,
        provider: str = "unknown",
        scopes: Optional[List[str]] = None,
    ): ...

# parrot/tools/manager.py:203
class ToolManager:
    async def get_tool(self, tool_name: str) -> Optional[Any]: ...  # lines 822-832

# parrot/tools/toolkit.py:168
class AbstractToolkit:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...  # lines 261-274
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...  # lines 276-290

# parrot_tools/jiratoolkit.py:2291  (note: package is parrot_tools, not parrot.tools)
class JiraToolkit:
    async def jira_search_issues(
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

#### Verified Imports

```python
from parrot.knowledge.ontology.schema import (
    TraversalPattern, ResolvedIntent, EntityDef, RelationDef,
    MergedOntology, EnrichedContext,
)
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.intent import OntologyIntentResolver
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.auth.credentials import CredentialResolver
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema
from parrot_tools.jiratoolkit import JiraToolkit
```

#### Key Attributes & Constants

- `OntologyRAGMixin._build_tool_hint(graph_result) -> str` (`mixin.py:235-256`) — current placeholder, retained.
- `OntologyIntentResolver.resolve` already accepts `user_context: dict[str, Any]` — no signature change required to plumb permission context; the change is *binding* (extracting entities) and routing the context through.
- `AbstractToolkit._pre_execute(tool_name, **kwargs)` accepts arbitrary kwargs forwarded from the call site — the credential channel is an existing extension point.
- `AuthorizationRequired` carries `auth_url` for deep-link reauth — UX layer already knows how to render this.

### Does NOT Exist (Anti-Hallucination)

The previous draft cited these symbols that **do not exist** in the live codebase. The brainstorm above is corrected:

- ~~`JiraToolkit.search_issues_jql`~~ — actual method is **`jira_search_issues`** (`parrot_tools/jiratoolkit.py:2291`).

…(truncated)…
