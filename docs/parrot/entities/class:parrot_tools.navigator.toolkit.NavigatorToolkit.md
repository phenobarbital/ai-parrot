---
type: Wiki Entity
title: NavigatorToolkit
id: class:parrot_tools.navigator.toolkit.NavigatorToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for managing the Navigator platform.
relates_to:
- concept: class:parrot.bots.database.toolkits.postgres.PostgresToolkit
  rel: extends
---

# NavigatorToolkit

Defined in [`parrot_tools.navigator.toolkit`](../summaries/mod:parrot_tools.navigator.toolkit.md).

```python
class NavigatorToolkit(PostgresToolkit)
```

Toolkit for managing the Navigator platform.

Provides tools for full lifecycle management of Programs, Modules,
Dashboards and Widgets, including permissions and search.

Inherits PostgresToolkit (FEAT-106) — DB connection managed by parent
via asyncdb pool.  All write tools require ``read_only=False``
(default for NavigatorToolkit: always False).

Args:
    confirm_execution: When ``True``, all write tools skip the dry-run
        confirmation step and execute immediately.  Useful for scripted
        or trusted contexts where human-in-the-loop approval is handled
        externally.  Defaults to ``False`` (safe, interactive mode).

Example usage::

    toolkit = NavigatorToolkit(dsn="postgres://user:pw@host/db")
    tools = toolkit.get_tools()  # nav_create_program, nav_get_program, …

    # Skip all dry-run gates (e.g. in an automated pipeline):
    toolkit = NavigatorToolkit(dsn="...", confirm_execution=True)

## Methods

- `async def stop(self) -> None` — Close the underlying DB connection and clear permissions cache.
- `async def execute_sql(self, sql: str, params: tuple=(), conn: Optional[Any]=None, returning: bool=False, single_row: bool=False) -> Any` — Execute a raw SQL statement (DDL or DML).
- `async def create_program(self, program_name: str, program_slug: str, description: Optional[str]=None, abbrv: Optional[str]=None, is_active: bool=True, attributes: Optional[Dict[str, Any]]=None, image_url: Optional[str]=None, visible: Optional[bool]=True, allow_filtering: Optional[bool]=None, filtering_show: Optional[Dict[str, Any]]=None, conditions: Optional[Dict[str, Any]]=None, client_ids: Optional[List[int]]=None, client_slugs: Optional[List[str]]=None, group_ids: List[int]=None, confirm_execution: bool=False) -> Dict[str, Any]` — Create a new Navigator program with client and group assignments.
- `async def update_program(self, program_id: int, **kwargs) -> Dict[str, Any]` — Update an existing Navigator program. Only provided fields are changed.
- `async def get_program(self, entity_id: Optional[int]=None, entity_slug: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Get a program by ID or slug. Requires access to the program.
- `async def list_programs(self, active_only: bool=True, limit: int=50, **kwargs) -> Dict[str, Any]` — List Navigator programs the current user has access to.
- `async def create_module(self, module_name: str, module_slug: str, program_id: Optional[int]=None, program_slug: Optional[str]=None, classname: Optional[str]=None, description: Optional[str]=None, active: bool=True, parent_module_id: Optional[int]=None, attributes: Optional[Dict[str, Any]]=None, allow_filtering: Optional[bool]=None, filtering_show: Optional[Dict[str, Any]]=None, conditions: Optional[Dict[str, Any]]=None, client_ids: Optional[List[int]]=None, client_slugs: Optional[List[str]]=None, group_ids: List[int]=None, confirm_execution: bool=False) -> Dict[str, Any]` — Create a Navigator module with optional menu hierarchy and permissions.
- `async def update_module(self, module_id: int, **kwargs) -> Dict[str, Any]` — Update an existing Navigator module. Requires write access.
- `async def get_module(self, entity_id: Optional[int]=None, entity_slug: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Get a module by ID or Slug. Requires access to the module.
- `async def list_modules(self, program_id: Optional[int]=None, active_only: bool=True, limit: int=50, sort_by_newest: bool=False, **kwargs) -> Dict[str, Any]` — List Navigator modules the current user has access to.
- `async def create_dashboard(self, name: str, module_id: Optional[int]=None, module_slug: Optional[str]=None, program_id: Optional[int]=None, program_slug: Optional[str]=None, description: Optional[str]=None, dashboard_type: str='3', position: int=1, enabled: bool=True, shared: bool=False, published: bool=True, allow_filtering: bool=True, allow_widgets: bool=True, params: Optional[Dict[str, Any]]=None, attributes: Optional[Dict[str, Any]]=None, conditions: Optional[Dict[str, Any]]=None, user_id: Optional[int]=None, save_filtering: bool=True, slug: Optional[str]=None, cond_definition: Optional[Dict[str, Any]]=None, filtering_show: Optional[Dict[str, Any]]=None, confirm_execution: bool=False) -> Dict[str, Any]` — Create a new Navigator dashboard inside a module.
- `async def update_dashboard(self, dashboard_id: str, confirm_execution: bool=False, **kwargs) -> Dict[str, Any]` — Update an existing Navigator dashboard. Requires write access.
- `async def get_dashboard(self, entity_uuid: Optional[str]=None, entity_slug: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Get a dashboard by UUID or Name. Requires access to the dashboard.
- `async def list_dashboards(self, program_id: Optional[int]=None, module_id: Optional[int]=None, active_only: bool=True, limit: int=50, **kwargs) -> Dict[str, Any]` — List dashboards the current user has access to.
- `async def publish_dashboard(self, dashboard_id: str, confirm_execution: bool=False) -> Dict[str, Any]` — Publish a draft dashboard — promote to system-wide.
- `async def clone_dashboard(self, source_dashboard_id: str, new_name: str, target_module_id: Optional[int]=None, target_program_id: Optional[int]=None, user_id: Optional[int]=None, confirm_execution: bool=False) -> Dict[str, Any]` — Clone a dashboard and all its active widgets to a new dashboard.
- `async def create_widget(self, dashboard_id: Optional[str]=None, dashboard_name: Optional[str]=None, program_id: Optional[int]=None, program_slug: Optional[str]=None, widget_type_id: str='api-echarts', template_id: Optional[str]=None, widget_name: Optional[str]=None, title: Optional[str]=None, widgetcat_id: int=3, module_id: Optional[int]=None, url: Optional[str]=None, params: Optional[Dict[str, Any]]=None, attributes: Optional[Dict[str, Any]]=None, conditions: Optional[Dict[str, Any]]=None, format_definition: Optional[Dict[str, Any]]=None, query_slug: Optional[Dict[str, Any]]=None, grid_position: Optional[Dict[str, int]]=None, user_id: Optional[int]=None, description: Optional[str]=None, cond_definition: Optional[Dict[str, Any]]=None, where_definition: Optional[Dict[str, Any]]=None, embed: Optional[str]=None, confirm_execution: bool=False) -> Dict[str, Any]` — Create a widget inside a dashboard.
- `async def update_widget(self, widget_id: str, confirm_execution: bool=False, **kwargs) -> Dict[str, Any]` — Update an existing widget. Only provided fields are changed.
- `async def get_widget(self, entity_uuid: Optional[str]=None, entity_slug: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Get a widget by UUID or Name. Requires access to the widget.
- `async def list_widgets(self, dashboard_id: Optional[str]=None, program_id: Optional[int]=None, active_only: bool=True, limit: int=50, **kwargs) -> Dict[str, Any]` — List widgets the current user has access to.
- `async def assign_module_to_client(self, client_id: int, program_id: int, module_id: int, active: bool=True, confirm_execution: bool=False) -> Dict[str, Any]` — Activate a module for a specific client within a program.
- `async def assign_module_to_group(self, group_id: int, module_id: int, program_id: int, client_id: int, active: bool=True, confirm_execution: bool=False) -> Dict[str, Any]` — Grant a group access to a module within a specific client context.
- `async def list_widget_types(self) -> Dict[str, Any]` — List all available widget types in the platform (108 types).
- `async def list_widget_categories(self) -> Dict[str, Any]` — List all widget categories (6 categories: generic, walmart, utility, mso, blank, loreal).
- `async def list_clients(self, active_only: bool=True, limit: int=500, **kwargs) -> Dict[str, Any]` — List Navigator clients (tenants). Returns up to 500 by default.
- `async def list_groups(self, client_id: Optional[int]=None, active_only: bool=True, limit: int=50, **kwargs) -> Dict[str, Any]` — List auth groups, optionally filtered by client.
- `async def get_widget_schema(self, widget_type_id: str) -> Dict[str, Any]` — Get the full JSON configuration schema for a specific widget type.
- `async def find_widget_templates(self, widget_type_id: str, program_id: Optional[int]=None, limit: int=10) -> Dict[str, Any]` — Find available widget templates for a given widget type.
- `async def search_widget_docs(self, query: str) -> Dict[str, Any]` — Search the Navigator widget documentation using PageIndex tree-search.
- `async def get_full_program_structure(self, entity_id: Optional[int]=None, entity_slug: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Get the complete structure of a program: modules, dashboards, and widget count.
- `async def search(self, query: str, entity_type: Optional[str]=None, limit: int=20) -> Dict[str, Any]` — Search across Navigator entities by name, slug, or title.
