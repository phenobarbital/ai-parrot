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
class PBACPermissionResolver(AbstractPermissionResolver):
    def __init__(self, evaluator: "PolicyEvaluator",
                 logger: Optional[logging.Logger] = None) -> None: ...
    async def can_execute(self, context, tool_name, required_permissions) -> bool:
        # Bridges to evaluator.check_access(
        #   ctx=eval_ctx, resource_type=ResourceType.TOOL,
        #   resource_name=tool_name, action="tool:execute", env=Environment()
        # )
        ...
    async def filter_tools(self, context, tools) -> list[Any]:
        # evaluator.filter_resources(
        #   ctx=eval_ctx, resource_type=ResourceType.TOOL,
        #   resource_names=[t.name for t in tools],
        #   action="tool:execute", env=Environment()
        # )
        ...

# From packages/ai-parrot/src/parrot/auth/pbac.py:35
async def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]: ...
# Loads policy_dir/*.yml and policy_dir/agents/*.yml today.
# Returns (None, None, None) on failure (graceful degradation).

# From packages/ai-parrot/src/parrot/tools/toolkit.py:168
class AbstractToolkit:
    tool_prefix: Optional[str] = None        # line 219
    prefix_separator: str = "_"              # line 222
    exclude_tools: tuple[str, ...] = ()      # line 205

    def get_tools(self, permission_context=None, resolver=None
                  ) -> List[AbstractTool]: ...                    # line 292
    async def get_tools_filtered(self,
        permission_context: "PermissionContext",
        resolver: "AbstractPermissionResolver",
    ) -> List[AbstractTool]: ...                                  # line 382

    # Subclass hooks (overridable):
    async def _pre_execute(self, tool_name: str, **kwargs) -> dict: ...   # line 261
    async def _post_execute(self, tool_name: str, result, **kwargs): ...  # line 280

# From packages/ai-parrot/src/parrot/tools/toolkit.py:18
class ToolkitTool(AbstractTool):
    async def _execute(self, **kwargs):                           # line 127
        # Pops _permission_context from parent AbstractTool,
        # forwards into toolkit._pre_execute() at line 156.
        ...

# From packages/ai-parrot/src/parrot/tools/abstract.py:375
class AbstractTool:
    async def execute(self, **kwargs) -> ToolResult:
        # Reads kwargs['_permission_context'] (line 391)
        # Reads kwargs['_resolver'] (line 392)
        # Stores in self._current_pctx (line 421)
        # Calls resolver.can_execute(...) (line 396)
        # Returns ToolResult(status='forbidden', ...) on deny (lines 402–412)
        ...

# From packages/ai-parrot/src/parrot/tools/manager.py:1126
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                       permission_context: Optional[PermissionContext] = None
                       ) -> Any:
    # Injects _permission_context (line 1174) and _resolver (line 1176)
    # into the tool.execute(**exec_kwargs) call (line 1178).
    ...

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:100
class DatasetEntry:
    def __init__(self, name: str, description: Optional[str] = None,
                 source: Optional[DataSource] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 is_active: bool = True,
                 # ... computed_columns, usage_guidance, protected, ...
                 ) -> None: ...
    async def materialize(self, **params) -> pd.DataFrame: ...     # line 225
    def to_info(self) -> DatasetInfo: ...                          # line 382

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:36
class DatasetInfo(BaseModel):
    name: str
    columns: List[str]
    column_types: Dict[str, str]
    shape: Tuple[int, int]
    is_active: bool
    source_type: str
    # ... usage_do, usage_dont, ...

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477
class DatasetManager(AbstractToolkit):
    tool_prefix = "dataset"                                        # line 497
    exclude_tools = ("setup", "add_dataset", "list_available")     # line 498
    _datasets: Dict[str, DatasetEntry]                             # line 509
    # Async tools exposed to the LLM (subset):
    async def list_available(self) -> List[Dict[str, Any]]: ...    # line 2506
    async def get_active(self) -> List[str]: ...                   # line 2510
    async def get_metadata(self, name: str) -> Dict[str, Any]: ... # line 2553
    async def activate(self, names: List[str]): ...                # line 2061
    async def deactivate(self, names: List[str]): ...              # line 2079
    async def add_dataframe(self, name: str, df: pd.DataFrame,
                            is_active: bool = True): ...           # line 959
```

#### Verified Imports

```python
# These imports have been confirmed to work in the current codebase:
from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
# packages/ai-parrot/src/parrot/auth/permission.py
from parrot.auth.resolver import (
    AbstractPermissionResolver,
    PBACPermissionResolver,
    DefaultPermissionResolver,
    AllowAllResolver,
    DenyAllResolver,
)
# packages/ai-parrot/src/parrot/auth/resolver.py
from parrot.auth.pbac import setup_pbac
# packages/ai-parrot/src/parrot/auth/pbac.py:35
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
# packages/ai-parrot/src/parrot/tools/toolkit.py
from parrot.tools.abstract import AbstractTool, ToolResult
# packages/ai-parrot/src/parrot/tools/abstract.py
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry, DatasetInfo
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py

# Imports from navigator-auth that PBACPermissionResolver already uses (lazy-imported
# inside methods to allow graceful degradation when navigator-auth is absent):
from navigator_auth.abac.policies.evaluator import PolicyEvaluator   # used at pbac.py:86
from navigator_auth.abac.policies.resources import ResourceType      # used at resolver.py:313
from navigator_auth.abac.policies.environment import Environment     # used at resolver.py:314
# After the parallel PR lands:
#   ResourceType.DATASET  ← NEW enum value to be added
```

#### Key Attributes & Constants

- `DatasetEntry.name` → `str` (`packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:135`) — **the canonical resource identity** used by policy YAML.
- `DatasetEntry.is_active` → `bool` (`:121`, `:2070`, `:2088`) — orthogonal to policy; remains the LLM-controllable lifecycle flag. Policy filtering happens *on top of* `is_active`.
- `DatasetInfo.columns` → `List[str]` (`:36` field block) — column-filter target.
- `DatasetInfo.column_types` → `Dict[str, str]` — column-filter target (must be filtered in lockstep with `columns`).
- `DatasetManager.tool_prefix` → `"dataset"` (`:497`) — the prefix used to identify dataset-related tools when filtering the catalogue.
- `DatasetManager.exclude_tools` → `("setup", "add_dataset", "list_available")` (`:498`) — already-hidden methods; policy filtering layers on top.
- `setup_pbac(...).cache_ttl` → `int = 30` seconds (`pbac.py:35`) — policy-evaluation cache window.
- `PolicyEvaluator.check_access(ctx, resource_type, resource_name, action, env)` and `.filter_resources(ctx, resource_type, resource_names, action, env)` — the two methods `DatasetPolicyGuard` will wrap.

### Does NOT Exist (Anti-Hallucination)

- `~~parrot.auth.dataset_guard~~` — module **does not exist yet**; this FEAT creates it.
- `~~DatasetPolicyGuard~~` — class does not exist; new in this FEAT.
- `~~ResourceType.DATASET~~` — enum value does **not exist** in `navigator-auth` at the time of writing. **Bring up the parallel `navigator-auth` PR before any task that imports it.** Until merged, mock or skip in tests.
- `~~DatasetEntry.policy_resource~~` / `~~DatasetEntry.required_roles~~` / `~~DatasetEntry.allowed_users~~` — not real attributes. Decisions in Round 3 mean we identify by `DatasetEntry.name`, not by an extra field.
- `~~@dataset_policy~~` decorator — there is **no** Python decorator-based policy declaration in `parrot.auth`. PBAC declarations live in YAML. `parrot/tools/abstract.py` only sets `_required_permissions` post-hoc (line 470–471) and is unrelated to the dataset path.
- `~~Guardian.filter_datasets~~` — `Guardian` (navigator-auth) only knows about tool resources today via `Guardian.filter_resources`. Dataset filtering goes through our new `DatasetPolicyGuard`; the existing `Guardian` middleware is untouched in this FEAT.
- `~~filter_tools_by_policy~~` hook in `AbstractToolkit` — the existing hook is `get_tools_filtered()` (`toolkit.py:382`); there is no separate `filter_tools_by_policy` method. Don't invent one.
- `~~contextvars.ContextVar~~` carrying user identity — not present today. Identity propagation goes through explicit `permission_context=` arguments. Don't assume an ambient `current_user`.
- `~~OAuth 3LO per-dataset credentials~~` — out of scope; the `_pre_execute` hook does support OAuth-style credential resolution (used by `JiraToolkit`) but this FEAT does not introduce per-dataset OAuth.
- `~~policies/datasets/~~` directory — does not yet exist on disk in any deployment. The spec must create it (sample) and update `setup_pbac()` to load it.

---

## Parallelism Assessment

- **Internal parallelism**: limited. The work is concentrated in three files (`parrot/auth/pbac.py`, new `parrot/auth/dataset_guard.py`, `parrot/tools/dataset_manager/tool.py`) and they have a clear dependency order: `DatasetPolicyGuard` must exist before `DatasetManager` can consume it; `setup_pbac()` extension is independent. One developer in one worktree can complete this end-to-end without contention. Splitting between two engineers would introduce more coordination overhead than it would save.
- **Cross-feature independence**: low conflict surface. `parrot/auth/` is currently quiet — no in-flight specs touch `permission.py` or `pbac.py`. `parrot/tools/dataset_manager/tool.py` is a 2k-line file actively maintained; coordinate with anyone touching `to_info`, `list_datasets`, or `materialize` in their own branches. The cross-repo dependency on `navigator-auth` (`ResourceType.DATASET` PR) is the main blocker — it must merge first.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: small file blast radius, strict task ordering (cross-repo PR → guard class → DatasetManager wiring → tests → sample YAML), and shared private helpers between tasks make per-spec the cleaner choice. A `mixed` strategy adds worktree ceremony without paralleling any genuinely independent work.

---

## Open Questions

- [ ] Cross-repo coordination: who owns the `navigator-auth` PR adding `ResourceType.DATASET`, and what's the target version/release tag this FEAT will pin? — *Owner: Jesus*
- [ ] Where exactly is `DatasetPolicyGuard` instantiated and how does it reach `DatasetManager`? Two candidates: (a) constructor kwarg `policy_guard=...` set at toolkit instantiation in app bootstrap; (b) registered on the aiohttp `app` and looked up via a manager-level setter at request time. — *Owner: spec author*
- [ ] What is the policy YAML schema for column-level rules? Use `resource_name="<dataset>:<column>"` and `action="dataset:column:read"`, or split into `resource_name="<dataset>"` with column-level metadata in the policy body? Resolve before `/sdd-spec`. — *Owner: spec author + navigator-auth maintainer*
- [ ] What is the audit-log format for dataset/column denials? Mirror `PBACPermissionResolver`'s `WARNING` line format (`parrot/auth/resolver.py:331–337`) verbatim, or emit structured JSON for downstream SIEM ingestion? — *Owner: ops*
- [ ] Hot-reload: do we need to invalidate the `PolicyEvaluator` cache when an admin edits `policies/datasets/*.yml`, or is the existing 30s TTL sufficient for v1? — *Owner: ops*
- [ ] Dataset rename behaviour: when a dataset is renamed, the policy referencing the old name silently no-ops. Do we add a startup-time validator that warns about orphan policy resources? — *Owner: spec author*
- [ ] Telemetry: should denials emit a metric (e.g. `parrot_dataset_policy_denied_total{resource,user}`) for dashboarding? — *Owner: ops*
