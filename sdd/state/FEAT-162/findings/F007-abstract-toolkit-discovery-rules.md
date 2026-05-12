---
id: F007
query_id: Q007
type: read
intent: Read the AbstractToolkit module to confirm constructor signature, get_tools(), and exclude lists.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — AbstractToolkit auto-discovery: only async public methods become tools; built-in exclude list + `exclude_tools` tuple

## Summary

`AbstractToolkit._generate_tools()` iterates `dir(self)`, skipping (a) names
starting with `_`, (b) lifecycle methods `get_tools, get_tools_filtered,
get_tools_sync, get_tool, list_tool_names, start, stop, cleanup`, (c) anything
in `self.exclude_tools`, (d) anything not a coroutine function. Subclasses can
optionally set `tool_prefix` to namespace tool names (idempotent if the method
already starts with the prefix). Constructor is `__init__(**kwargs)`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 218-260
  symbol: class attributes + __init__
  excerpt: |
    exclude_tools: tuple[str, ...] = ()
    tool_prefix: Optional[str] = None
    prefix_separator: str = "_"
    def __init__(self, **kwargs):
        self.return_direct = kwargs.get('return_direct', self.return_direct)
        self.base_url = kwargs.get('base_url', self.base_url)
        self._tool_cache: Dict[str, ToolkitTool] = {}
        self._tools_generated = False
        self.logger = logging.getLogger(self.__class__.__name__)

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 368-403
  symbol: _generate_tools
  excerpt: |
    def _generate_tools(self) -> None:
        for name in dir(self):
            if name.startswith('_'):
                continue
            if name in ('get_tools', 'get_tools_filtered', 'get_tools_sync',
                        'get_tool', 'list_tool_names', 'start', 'stop', 'cleanup',
                        *self.exclude_tools):
                continue
            attr = getattr(self, name)
            if not inspect.iscoroutinefunction(attr):
                continue
            tool_name = self._resolve_tool_name(name)
            tool = self._create_tool_from_method(tool_name, attr)
            self._tool_cache[tool_name] = tool

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 263-313
  symbol: start/stop/cleanup/_pre_execute/_post_execute (lifecycle hooks)
  excerpt: |
    async def start(self) -> None: ...   # override for startup
    async def stop(self) -> None: ...    # override for shutdown
    async def cleanup(self) -> None: ... # override for cleanup
    async def _pre_execute(self, tool_name, **kwargs) -> None: ...
    async def _post_execute(self, tool_name, result, **kwargs) -> Any: ...

## Notes

- For `ReportPersistenceMixin`, the `_persist_report` method begins with `_` so
  it is automatically excluded from tool generation — no need to add it to
  `exclude_tools`.
- For `SecurityReportToolkit`, set `tool_prefix = "security"` or similar to
  namespace tools (e.g. `security_find_security_report`). The brainstorm leaves
  this unspecified.
- Helper attribute names assigned in `__init__` like `self.file_manager`,
  `self.report_store`, `self.parser_version` are not coroutine functions, so
  they won't be picked up as tools — safe.
