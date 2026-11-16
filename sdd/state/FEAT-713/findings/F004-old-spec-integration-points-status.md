---
id: F004
query_id: Q034, Q035, Q036, Q037, Q038, Q041, Q042, Q043
type: grep
intent: "For each integration point the old FEAT-713 spec named: does it still resolve on dev, and at what path:line."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_ids: [FC-007]
---

# F004 — Old-spec integration points: all core symbols still resolve; three line anchors moved (CLI registry, `register_object_schedules`), the scheduler call site is still not found, and nothing named accounting/finance exists in source

## Summary

Status table (✓ = resolves at the old anchor, ↻ = resolves at a new line, ✗ = missing):

| Old-spec reference | Status | Today |
|---|---|---|
| `SQLToolkit.execute_query(query, limit=1000, timeout=30)` `sql.py:297` | ✓ | `bots/database/toolkits/sql.py:297`, returns `QueryExecutionResponse \| RetryContext` |
| `SQLToolkit.database_type` `toolkits/base.py:139` | ✓ | attribute set at `base.py:139` (field at :55) |
| `SQLGLOT_DIALECT_MAP` `knowledge/common/sql_dialects.py:6` | ✓ | same line |
| `DatasetPolicyGuard` `auth/dataset_guard.py:56`, `filter_datasets` :128, `can_read_dataset` :278 | ✓ | same lines |
| `_pctx_var` `auth/context.py:33` | ✓ | same line |
| `AbstractKMSSigner` :135, `LocalHMACSigner` :166, `AzureKeyVaultSigner` :199 (`security/audit_ledger.py`) | ✓ | same lines; `AuditLedgerEntry` :80, `AuditLedger` :296 |
| `require_extra` `_imports.py:248` | ✓ | same line |
| CLI `_lazy_commands` `cli/__init__.py:109-139`, `_lazy_extras` :143 | ↻ | dict now at **:170-217**, `_lazy_extras` at **:219-231**; no `semantic` / `finance` entry |
| `@schedule` `scheduler/manager.py:50` | ✓ | same line (ai-parrot-server) |
| `SchedulerManager.register_object_schedules` `scheduler/base.py:798` | ↻ | now **:806** |
| server call site constructing the scheduler (old Q11) | ✗ | no `SchedulerManager(` anywhere in `packages/*/src`; only `AgentSchedulerManager()` in `integrations/agentd/service.py:465` and the bot path `manager.py:446` |
| `parrot mcp-local` config `.parrot/mcp-toolkits.yaml` | ✓ | file exists with 4 toolkits; no `semantic` or `finance` section |
| `docs/semantic/` | ✗ | directory does not exist; user docs live at `wiki/tools/semantic-layer.md`; examples at `examples/agents/semantic/` |
| anything named `chart_of_accounts`, `AccountingToolkit`, `parrot.semantic.accounting`, `tool_prefix = "finance"` | ✗ | zero matches in `packages/` and `examples/` |

A second guard class exists that the old spec did not use: `DataPlanePolicyGuard` (`auth/dataplane_guard.py:45`,
`authorize_source` :193) — the one the shipped semantic layer is built on (see FC-005).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  lines: 297-302
  symbol: `SQLToolkit.execute_query`
  excerpt: |
    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> Union[QueryExecutionResponse, RetryContext]:

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`
  lines: 139-140
  symbol: `database_type`
  excerpt: |
    self.database_type = database_type
    self.origin = origin or database_type  # FEAT-600: plane alias

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`
  lines: 312-312
  symbol: `execute_query (base)`
  excerpt: |
    async def execute_query(

- path: `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py`
  lines: 6-6
  symbol: `SQLGLOT_DIALECT_MAP`
  excerpt: |
    SQLGLOT_DIALECT_MAP: Dict[str, str] = {

- path: `packages/ai-parrot/src/parrot/auth/dataset_guard.py`
  lines: 56-56
  symbol: `DatasetPolicyGuard`
  excerpt: |
    class DatasetPolicyGuard:

- path: `packages/ai-parrot/src/parrot/auth/dataset_guard.py`
  lines: 128-128
  symbol: `DatasetPolicyGuard.filter_datasets`
  excerpt: |
    async def filter_datasets(

- path: `packages/ai-parrot/src/parrot/auth/dataset_guard.py`
  lines: 278-278
  symbol: `DatasetPolicyGuard.can_read_dataset`
  excerpt: |
    async def can_read_dataset(

- path: `packages/ai-parrot/src/parrot/auth/context.py`
  lines: 33-33
  symbol: `_pctx_var`
  excerpt: |
    _pctx_var: contextvars.ContextVar["PermissionContext | None"] = (

- path: `packages/ai-parrot/src/parrot/auth/dataplane_guard.py`
  lines: 45-45
  symbol: `DataPlanePolicyGuard`
  excerpt: |
    class DataPlanePolicyGuard:

- path: `packages/ai-parrot/src/parrot/auth/dataplane_guard.py`
  lines: 193-193
  symbol: `DataPlanePolicyGuard.authorize_source`
  excerpt: |
    async def authorize_source(

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 135-135
  symbol: `AbstractKMSSigner`
  excerpt: |
    class AbstractKMSSigner(ABC):

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 166-166
  symbol: `LocalHMACSigner`
  excerpt: |
    class LocalHMACSigner(AbstractKMSSigner):

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 296-296
  symbol: `AuditLedger`
  excerpt: |
    class AuditLedger:

- path: `packages/ai-parrot/src/parrot/_imports.py`
  lines: 248-248
  symbol: `require_extra`
  excerpt: |
    def require_extra(extra: str, *modules: str) -> None:

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 170-217
  symbol: `cli._lazy_commands`
  excerpt: |
    cli._lazy_commands = {
        "setup": "parrot.setup.cli",
        ...
        "mcp-local": "parrot.mcp.local_cli",
        ...
        "connections": "parrot.cli.connect",
        "disconnect": "parrot.cli.connect",
    }

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 219-231
  symbol: `cli._lazy_extras`
  excerpt: |
    cli._lazy_extras = {
        "serve": _AGENTD_INSTALL_HINT,
        ...
        "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",
    }

- path: `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
  lines: 50-50
  symbol: `schedule`
  excerpt: |
    def schedule(

- path: `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
  lines: 397-446
  symbol: `AgentSchedulerManager`
  excerpt: |
    class AgentSchedulerManager(SchedulerManager):
        ...
        return self.register_object_schedules(types.SimpleNamespace(**members), bot_name)

- path: `packages/ai-parrot-server/src/parrot/scheduler/base.py`
  lines: 806-812
  symbol: `SchedulerManager.register_object_schedules`
  excerpt: |
    def register_object_schedules(self, obj: Any, name: str) -> int:
        """Register ``@schedule`` methods from an object as in-memory code jobs."""
        registered = 0
        for method_name, method in inspect.getmembers(obj, predicate=inspect.ismethod):
            if not hasattr(method, "_schedule_config"):
                continue

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`
  lines: 465-465
  symbol: `AgentSchedulerManager()`
  excerpt: |
    manager = AgentSchedulerManager()

- path: `.parrot/mcp-toolkits.yaml`
  lines: 1-56
  symbol: `toolkits`
  excerpt: |
    toolkits:
        class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
        class: parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit
        class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit
        class: parrot.tools.working_memory.tool.WorkingMemoryToolkit

- path: `wiki/tools/semantic-layer.md`
  lines: 1-1
  symbol: `user-facing docs`
  excerpt: |
    (file exists, 8.2K; not opened)

- path: `examples/agents/semantic/README.md`
  lines: 1-1
  symbol: `examples`
  excerpt: |
    (directory holds README.md, _common.py, agent_semantic_example.py, governed_joins_agent.py,
     llm_metrics_agent.py, masked_policy_agent.py, mcp_local_agent.py, models/, models_ungoverned/; not opened)

## Notes

- Old Q11 (scheduler call site) is still open, with one new lead: the scheduler that is actually
  constructed is `AgentSchedulerManager()` inside the agentd service (`ai-parrot-integrations`), not in
  `ai-parrot-server/manager/`. Whether the aiohttp server builds one elsewhere (e.g. via an app-factory
  attribute rather than a `SchedulerManager(` call) was not established.
- The old spec's M10 path `docs/semantic/accounting-metrics-layer.md` points at a directory that does not
  exist; semantic docs follow the `wiki/tools/` convention.
- `packages/ai-parrot/build/lib.linux-*/` contains stale copies (e.g. `_SQLGLOT_DIALECT_MAP` in a build
  copy of `sql.py`); those hits are not source.
- The MCP grep in `packages/ai-parrot-server/src/parrot/mcp` matched only the English word "semantics";
  `mcp/toolkit_config.py:130-133` cited by the old spec was not re-verified.
- `SQLToolkit.execute_query` default `limit=1000` still applies (old-spec risk "execute_query limit").
