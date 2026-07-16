---
type: Wiki Overview
title: 'Brainstorm: PBAC-Driven DatasetManager Policy Enforcement'
id: doc:sdd-proposals-pbac-datasetmanager-policy-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is a data-leak vector. Concrete failure case: user `jleon@trocglobal.com`
  opens a chat with a finance-aware agent and the LLM is happily exposed to a `financial_data`
  dataset that — by HR/compliance policy — that user is not entitled to query. The
  LLM may list it, describe i'
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.dataset_guard
  rel: mentions
- concept: mod:parrot.auth.pbac
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.resolver
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: PBAC-Driven DatasetManager Policy Enforcement

**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`DatasetManager` (a `parrot.tools.AbstractToolkit`) exposes datasets to LLM-driven agents via async methods such as `list_available()`, `get_metadata()`, `fetch_dataset()`, `activate_datasets()`. Today the catalog has only a global `is_active` flag per `DatasetEntry`: every authenticated user that interacts with the agent sees every active dataset in the toolkit, regardless of who they are.

This is a data-leak vector. Concrete failure case: user `jleon@trocglobal.com` opens a chat with a finance-aware agent and the LLM is happily exposed to a `financial_data` dataset that — by HR/compliance policy — that user is not entitled to query. The LLM may list it, describe its schema, or fetch rows from it.

`navigator-auth` already provides a full ABAC/PBAC stack (`PolicyEvaluator`, `PolicyDecisionPoint`, YAML-based policies, `Guardian` middleware) and `ai-parrot` already integrates it for **tool-level** enforcement (`PBACPermissionResolver` at `parrot/auth/resolver.py:247`, wired through `AbstractTool.execute()` and `AbstractToolkit.get_tools_filtered()`). What is missing is a **dataset-level** resource model: a way for an admin to author a YAML policy that says "user `jleon@trocglobal.com` cannot see resource `dataset:financial_data` (action `dataset:read`)" and have the `DatasetManager` honour that decision both in the catalog the LLM sees and in the data it gets back.

The feature also needs **column-level** filtering: an admin can hide specific sensitive columns inside an otherwise-visible dataset (e.g. drop `profit_margin` from `sales` for tier-1 reps but keep it for managers).

## Constraints & Requirements

- **Cross-repo dependency**: `ResourceType.DATASET` must be added to `navigator-auth` as a parallel PR; `ai-parrot` consumes it once merged. The brainstorm/spec proceeds assuming the enum value will be available.
- **Backwards compatibility**: existing `DatasetManager` users without policies must keep working unchanged. Default = permissive (no policy declared → dataset visible to all). Opt-in only.
- **Fail-closed evaluation**: when policy evaluation cannot complete (navigator-auth import error after wiring, malformed YAML, evaluator timeout), datasets must be treated as **denied** — *except* during the import-degradation case for backwards compat (no policies installed = nothing to enforce).
- **Filter at two layers**: (1) tool-list visibility (the LLM never sees forbidden dataset-tools), and (2) schema/metadata (forbidden columns are dropped from `DatasetInfo.columns`, `column_types`, and from the materialised `DataFrame`).
- **Drop-silent column semantics**: hidden columns must not appear in `DatasetInfo`, `get_metadata()`, or `fetch_dataset()` results. The LLM never learns they exist.
- **Identity propagation**: `user_id` already travels from the aiohttp handler (`parrot/handlers/chat.py:463`) into `bot.ask(...)` and `bot.ask_stream(...)` (`parrot/bots/abstract.py:3477`, `:3528`). The dataset filter must consume it via `PermissionContext` (`parrot/auth/permission.py:80`) — no new identity mechanism.
- **YAML authoring**: policies live in `policies/datasets/*.yml`, loaded by an extended `setup_pbac()` (`parrot/auth/pbac.py:35`) alongside the existing `policies/agents/` directory. Same `PolicyEvaluator` instance — single source of truth.
- **Resource identity**: a dataset is keyed by `DatasetEntry.name` (the existing string used by `add_dataframe(name=...)`). YAML policies reference that name verbatim.
- **No async-blocking in tool list**: filtering happens during the already-async `get_tools_filtered()` and inside async tool methods; it must not introduce new sync I/O.

---

## Options Explored

### Option A: Native PBAC integration with extended `ResourceType.DATASET`

Make the dataset a **first-class resource type** in `navigator-auth` (`ResourceType.DATASET`) and wire `DatasetManager` directly into the existing PBAC stack (`PolicyEvaluator`, `PBACPermissionResolver`).

**How it works (description, no code):**

1. A new helper class `DatasetPolicyGuard` (lives in `parrot/auth/dataset_guard.py`) wraps a `PolicyEvaluator` and exposes three async methods:
   - `filter_datasets(context, dataset_names) → set[str]` — uses `evaluator.filter_resources(resource_type=ResourceType.DATASET, action="dataset:read")` to return the names the user is allowed to see.
   - `filter_columns(context, dataset_name, columns) → list[str]` — for fine-grained column visibility, uses `evaluator.filter_resources(resource_type=ResourceType.DATASET, resource_names=[f"{dataset_name}:{col}" for col in columns], action="dataset:column:read")`.
   - `can_read_dataset(context, dataset_name) → bool` — single-resource convenience for the `fetch_dataset` path.
2. `DatasetManager` gains a constructor kwarg `policy_guard: Optional[DatasetPolicyGuard] = None`. When provided, it stores it and:
   - Overrides `get_tools_filtered(...)` to first delegate to `super().get_tools_filtered()` (which handles tool-level PBAC) and then post-filter any tool whose `_method_name` is in the dataset-tool set (`fetch_dataset`, `get_metadata`, etc.) using `policy_guard.filter_datasets()`.
   - Wraps `list_datasets()` / `list_available()` to drop forbidden datasets from the listing.
   - Wraps `to_info()` / `get_metadata()` to remove forbidden columns from `DatasetInfo.columns` and `DatasetInfo.column_types`.
   - Wraps `materialize()` (called inside `fetch_dataset()`) to drop forbidden columns from the returned `DataFrame` before it leaves the toolkit.
3. The `_permission_context` already carried by `ToolkitTool._execute()` (`parrot/tools/toolkit.py:127`, lifecycle hook line 153–156) supplies the user identity. `DatasetManager._pre_execute()` reads `self._current_pctx` and calls `policy_guard` accordingly.
4. `setup_pbac()` (`parrot/auth/pbac.py:35`) gets one extra line: load `policies/datasets/*.yml` into the same `PolicyEvaluator`. Optional: yield a registered `DatasetPolicyGuard` instance via the app context so callers don't need to construct it.
5. **Fail-closed**: any exception inside `DatasetPolicyGuard` methods (besides `ImportError` for navigator-auth not installed) is logged and treated as deny.

✅ **Pros:**
- Single PBAC source of truth: tool policies and dataset policies share the same `PolicyEvaluator`, same YAML directory, same `EvalContext` — admins author them in one place.
- Built on infrastructure that already exists and ships in `parrot/auth/` — no parallel auth path.
- The "drop silently" column semantic is enforced at the only three exit points (`to_info`, `list_*`, `materialize`), keeping the surface small.
- Compatible with the existing handler-level `Guardian.filter_resources()` pattern: dataset enforcement becomes Layer 1 (filter at list time) + Layer 2 (filter at execute time), exactly mirroring tools.
- YAML authoring grows naturally: `policies/agents/`, `policies/datasets/`, future `policies/<resource>/`.

❌ **Cons:**
- Requires a parallel PR in `navigator-auth` to add `ResourceType.DATASET`. Until that lands, the brainstorm/spec is blocked from coding the import. Mitigation: agreed in Round 3 — open the navigator-auth PR first, this FEAT consumes the new release.
- New `DatasetPolicyGuard` is yet another class users must learn — but it sits inside `parrot/auth/`, where the rest of the policy story already lives, so the cognitive cost is small.
- Column-level filtering produces one `filter_resources` call per dataset whose metadata or rows are being returned. For a 50-column dataset that is one PolicyEvaluator round-trip with 50 names; the existing evaluator cache (`cache_ttl_seconds`, `parrot/auth/pbac.py:114`) absorbs repeated calls within a turn.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth` | `PolicyEvaluator`, `ResourceType.DATASET`, `EvalContext`, `Environment` | Requires version bump that adds `ResourceType.DATASET`; cross-repo PR. Imports already used in `parrot/auth/resolver.py:313–314` (`ResourceType.TOOL`, `Environment`). |
| `pydantic` | `DatasetInfo`, `UserSession`, `PermissionContext` data models | Already a project dependency; `BaseModel` used throughout the toolkit. |
| `pyyaml` (transitive via `navigator-auth`) | YAML policy storage | Already used by `YAMLStorage` in `setup_pbac()` (`parrot/auth/pbac.py:88`). |
| `pandas` | DataFrame column drop in `materialize` wrapper | Already a `DatasetManager` dependency. |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/auth/resolver.py:247` — `PBACPermissionResolver` as the design template for `DatasetPolicyGuard`. Same wrapping pattern, same fail-open-on-ImportError, same `to_eval_context` bridge.
- `packages/ai-parrot/src/parrot/auth/permission.py:80` — `PermissionContext` and `to_eval_context()` (`:160`) already bridge user identity to navigator-auth.
- `packages/ai-parrot/src/parrot/auth/pbac.py:35` — `setup_pbac(app, policy_dir, ...)` extension point: add one extra glob for `policy_dir/datasets/`.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:382` — `AbstractToolkit.get_tools_filtered()` already implements Layer-1 filtering via `resolver.filter_tools(...)`. `DatasetManager` overrides this to add the dataset-name post-filter.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:127–156` — `ToolkitTool._execute()` already exposes `_permission_context` to subclass `_pre_execute()` hooks. Used by `JiraToolkit`; pattern is proven.
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:382` — `DatasetEntry.to_info()` is the single chokepoint where columns flow into `DatasetInfo`. Best place to apply column filtering.

---

### Option B: Per-`DatasetEntry` policy declaration with TOOL-namespace workaround

Avoid touching `navigator-auth`. Reuse `ResourceType.TOOL` with naming convention `dataset:<name>` and `dataset:<name>:column:<col>`. Each `DatasetEntry` declares an optional `policy_resource: Optional[str]` (defaulting to `f"dataset:{self.name}"`). A new `DatasetPolicyAdapter` translates dataset operations into TOOL-resource policy checks against the existing `PBACPermissionResolver`.

✅ **Pros:**
- Zero changes to `navigator-auth`. We could ship in a single PR.
- Policies still author against the existing `ResourceType.TOOL` enum the YAML schema already accepts.

❌ **Cons:**
- **Pollutes the TOOL resource namespace**: a YAML reader cannot tell whether `dataset:financial_data` is a real tool or a dataset. Loses semantic clarity that admins need.
- Conflicts with the user's explicit Round 2 choice ("Extender `ResourceType` con `DATASET`"). Adopting it would walk back a decided design point.
- Future granularities (rows, actions) would need ad-hoc string conventions instead of the structured enum + action vocabulary navigator-auth already provides.
- Forces every YAML to encode the type as part of the resource name string, defeating the point of an enum.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth` | `PolicyEvaluator`, `ResourceType.TOOL` (existing) | No version bump. |
| `pydantic` | Data models | Existing. |

🔗 **Existing Code to Reuse:**
- Same set as Option A, minus the navigator-auth ResourceType extension.
- `packages/ai-parrot/src/parrot/auth/resolver.py:341` — `PBACPermissionResolver.filter_tools()` reused with a `dataset:`-prefixed name array.

---

### Option C: Policy-aware DatasetManager subclass (`PolicyAwareDatasetManager`)

Leave the base `DatasetManager` untouched; ship a subclass that adds policy enforcement. Subclass overrides `list_datasets`, `to_info`, `materialize` paths and a new `_pre_execute` hook. Apps that need security swap their toolkit class; apps that don't keep using `DatasetManager`.

✅ **Pros:**
- Strongest opt-in: existing tests, fixtures, and downstream apps that don't care about policies are guaranteed unaffected.
- Easy to A/B during rollout: feature-flag the toolkit class instance in app config.

❌ **Cons:**
- Two parallel toolkit codepaths to maintain. Drift risk over time as `DatasetManager` evolves (already 2k+ lines).
- Doesn't actually achieve cleaner backwards compatibility than Option A — Option A's "no `policy_guard` argument = no enforcement" is just as opt-in, with no class fork.
- Inheriting from a 2k-line base class to override three call sites is heavier than instrumenting those call sites directly behind a single optional kwarg.
- Discovery problem: developers must know to instantiate `PolicyAwareDatasetManager` instead of `DatasetManager`. Easy to miss and silently lose enforcement.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | — | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477` — `class DatasetManager(AbstractToolkit)` as the parent class.
- Otherwise identical reuse list to Option A.

---

## Recommendation

**Option A** is recommended.

It aligns with the user's explicit choices in Round 2 (extend `ResourceType` with `DATASET`) and Round 3 (parallel PR in `navigator-auth`, drop-silent columns, opt-in by `DatasetEntry.name`). It reuses the entire PBAC stack already in `parrot/auth/` (`PermissionContext`, `to_eval_context`, the `PolicyEvaluator` shared with the `Guardian` middleware), so dataset enforcement gets the same cache, the same audit trail, and the same YAML directory model as tool enforcement.

We're trading off: (a) coupling to a navigator-auth release that adds `ResourceType.DATASET`, and (b) one extra `filter_resources` round-trip per metadata/fetch call (for column filtering). Both are acceptable: (a) is a parallel PR with low surface area and (b) is amortised by `PolicyEvaluator`'s `cache_ttl_seconds=30` cache, which is already in production.

Option B is rejected because it walks back the explicit Round 2 decision and pollutes the TOOL resource namespace. Option C is rejected because the class fork is heavier than the single optional kwarg in Option A, and Option A is no less opt-in.

---

## Feature Description

### User-Facing Behavior

**Admin (policy author):**
- Drops a YAML file into `policies/datasets/finance.yml` describing rules such as "deny user `jleon@trocglobal.com` from resource `financial_data`, action `dataset:read`" or "deny role `tier-1-rep` from resource `sales:profit_margin`, action `dataset:column:read`".
- Restarts (or hot-reloads, if the deployment uses the existing PolicyEvaluator TTL refresh) the application. No code change.

**End user (chat / agent client):**
- Logs in as `jleon@trocglobal.com` and asks the finance agent "list the datasets you have." The agent responds with the catalog **excluding** `financial_data` — as if it never existed.
- Asks the agent "what columns does `sales` have?" The response from `get_metadata()` lists every column the user is permitted to see; `profit_margin` is silently absent.
- Asks "fetch the top 100 rows of `sales`." The returned DataFrame contains every permitted column; `profit_margin` is silently absent.
- An admin user with a different policy gets the full catalog and the full column set in the same conversation flow.

**Agent / LLM:**
- Tool catalogue presented at agent boot is filtered before the LLM sees it. The dataset-named tools (and dataset-name parameters in `get_metadata`, `fetch_dataset`, etc.) reflect only what the user can see.
- The LLM cannot infer a forbidden dataset by name, by column, or by error message. There is no "permission denied" surface for these resources — they simply don't appear.

### Internal Behavior

**Initialisation flow:**

1. App startup calls `setup_pbac(app, policy_dir="policies", ...)`. This now also globs `policies/datasets/*.yml` into the same `YAMLStorage`. The single `PolicyEvaluator` returned by `setup_pbac()` knows about both agent and dataset policies.
2. App constructs a `DatasetPolicyGuard(evaluator=evaluator)` and passes it into `DatasetManager(policy_guard=...)` (or registers it on a manager-level setter for late binding).
3. `DatasetManager` stores `self._policy_guard`. If `None`, all enforcement paths short-circuit to "allow" (backwards-compat opt-in).

**Per-turn flow:**

1. The aiohttp handler builds a `PermissionContext` from the session (`user_id`, `tenant_id`, roles) and forwards it through `bot.ask(...)` (existing path).
2. The bot constructs the agent's tool catalogue by calling `toolkit.get_tools_filtered(permission_context, resolver)` (existing PBAC Layer-1).
3. `DatasetManager.get_tools_filtered()` overrides the base method:
   - Calls `super().get_tools_filtered(...)` to get the resolver-allowed tools.
   - Walks the result and removes any dataset-named tool whose dataset is denied per `policy_guard.filter_datasets(context, all_dataset_names)`.
4. When the LLM invokes a dataset method (e.g. `fetch_dataset(name="sales")`), `ToolkitTool._execute()` injects `_permission_context` into `_pre_execute()` (existing hook). `DatasetManager._pre_execute()` consults `policy_guard.can_read_dataset(context, name)`. If denied, return a `ToolResult(status='forbidden', ...)` (matching the pattern used by `AbstractTool.execute` at line 402–412).
5. After execution, in the `_post_execute()` hook (or inline inside the dataset method, whichever is cleaner), apply column filtering via `policy_guard.filter_columns(context, name, df.columns.tolist())`. Drop the disallowed columns from the `DataFrame` and from any `DatasetInfo` returned.

**Where the filter touches the data:**

| Touchpoint | What is filtered | Mechanism |
|---|---|---|
| `DatasetManager.list_datasets` / `list_available` | Dataset rows in the listing | Pre-filter via `policy_guard.filter_datasets` |
| `DatasetEntry.to_info` (`dataset_manager/tool.py:382`) | Columns inside `DatasetInfo` | Post-filter via `policy_guard.filter_columns`, called from a `DatasetManager` wrapper that knows the user context |
| `DatasetManager.get_metadata` | Same as above | Same |
| `DatasetManager.fetch_dataset` → `DatasetEntry.materialize` (`:225`) | DataFrame columns | Drop columns post-fetch in the `DatasetManager` method, before returning to the LLM |
| `DatasetManager.get_active`, `activate_datasets`, `deactivate_datasets` | Dataset names | Pre-filter via `policy_guard.filter_datasets` so the LLM cannot probe by activation toggling |

### Edge Cases & Error Handling

- **`policy_guard is None`**: every guard call short-circuits to allow. Backwards compat preserved.
- **`navigator-auth not installed`**: `DatasetPolicyGuard` mirrors `PBACPermissionResolver`'s pattern (`parrot/auth/resolver.py:315–317`): on `ImportError`, return "all allowed". This is consistent with the rest of the auth stack but is noted in fail-mode design (only ImportError is allow-on-failure; runtime errors are deny-on-failure).
- **`PolicyEvaluator.filter_resources` raises**: caught, logged at WARNING with user_id and dataset_name, treated as deny. Fail-closed.
- **YAML policy parse error at startup**: `setup_pbac()` already returns `(None, None, None)` on failure (`parrot/auth/pbac.py:89–104`). If the evaluator is `None`, `DatasetPolicyGuard` constructor receives `None` and either (a) the manager declines to construct one (and runs unprotected), or (b) the constructor raises — design point for the spec.
- **Column hidden but referenced in user query**: the LLM doesn't know it exists, so it should not reference it. If the LLM hallucinates the name, `fetch_dataset` returns the DataFrame without that column. Downstream pandas operations on a missing column produce the standard `KeyError`, which the LLM sees as a normal tool error, not a security signal.
- **User identity missing (`PermissionContext` not propagated)**: treat as anonymous. Fail-closed: deny all policy-protected datasets. Datasets without policies remain visible (opt-in).
- **Dataset renamed**: policy referencing the old name silently no-ops (no resource matches). This is a known migration-day gap; flagged in Open Questions.
- **Cache staleness**: `PolicyEvaluator` caches per its `cache_ttl_seconds=30` default. A policy edit takes up to 30s to take effect. Acceptable per Round 1; flagged for ops in Open Questions.
- **Hot reload**: out of scope for v1.

---

## Capabilities

### New Capabilities
- `pbac-datasetmanager-policy`: PBAC enforcement for `DatasetManager` at dataset and column granularity, integrated with the existing `navigator-auth` `PolicyEvaluator`.

### Modified Capabilities
- `parrot-auth-pbac` (existing capability behind `parrot/auth/pbac.py` + `parrot/auth/resolver.py`): extended to load `policies/datasets/*.yml` and to support `ResourceType.DATASET` (new in `navigator-auth`).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator-auth` (external repo) | extends | Add `ResourceType.DATASET` enum value. Parallel PR; this FEAT consumes the resulting release. |
| `parrot/auth/pbac.py` | modifies | `setup_pbac()` learns to glob `policy_dir/datasets/*.yml` alongside `policy_dir/agents/*.yml`. |
| `parrot/auth/dataset_guard.py` | creates | New `DatasetPolicyGuard` class wrapping `PolicyEvaluator` with `filter_datasets`, `filter_columns`, `can_read_dataset`. |
| `parrot/auth/__init__.py` | modifies | Export `DatasetPolicyGuard`. |
| `parrot/tools/dataset_manager/tool.py` | modifies | `DatasetManager.__init__` accepts `policy_guard`; overrides `get_tools_filtered`, wraps `list_datasets`, `to_info`, `materialize` flow, implements `_pre_execute`/`_post_execute` hooks for dataset and column filtering. |
| `policies/datasets/` (new directory in deployments) | creates | YAML policies authored by ops/admins. Sample policy committed alongside the spec for documentation. |
| `tests/auth/` and `tests/tools/dataset_manager/` | extends | New unit tests for `DatasetPolicyGuard` and integration tests for filtered dataset access. |
| Bots/agent runtime | depends on | No code change required if bots already pass `permission_context` into toolkit execution. Confirmed via `parrot/tools/manager.py:1126` — already supported. |

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (Round 1)
# Identity already travels through bot.ask(...) and bot.ask_stream(...) via session.
# Existing pipeline:
#   handler chat.py → reads session['user_id'] → bot.ask(..., user_id=user_id) →
#   ToolManager.execute_tool(name, params, permission_context=...) →
#   AbstractTool.execute(...) → ToolkitTool._execute(...) → toolkit method
#
# Example denied user: jleon@trocglobal.com
# Example denied dataset: financial_data
```

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/auth/permission.py:20
@dataclass(frozen=True)
class UserSession:
    user_id: str
    tenant_id: Optional[str]
    roles: frozenset[str]
    metadata: dict
    # ...

# From packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    extra: dict = ...

# From packages/ai-parrot/src/parrot/auth/permission.py:160
def to_eval_context(context: PermissionContext) -> "EvalContext":
    """Bridge ai-parrot PermissionContext → navigator-auth EvalContext."""
    ...

# From packages/ai-parrot/src/parrot/auth/resolver.py:25
class AbstractPermissionResolver(ABC):
    @abstractmethod
    async def can_execute(self, context: PermissionContext, tool_name: str,
                          required_permissions: set[str]) -> bool: ...
    @abstractmethod
    async def filter_tools(self, context: PermissionContext,
                           tools: list[Any]) -> list[Any]: ...

# From packages/ai-parrot/src/parrot/auth/resolver.py:247

…(truncated)…
