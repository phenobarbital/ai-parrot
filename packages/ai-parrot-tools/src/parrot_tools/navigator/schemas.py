"""
Pydantic input schemas for NavigatorToolkit methods.

Each schema maps to a @tool_schema decorator on a toolkit method.
Field descriptions are sent to the LLM as part of the tool definition.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# PROGRAM SCHEMAS
# =============================================================================

class ProgramCreateInput(BaseModel):
    """Input for creating a new Navigator program."""

    program_name: str = Field(
        description="Display name of the program (e.g., 'Retail360', 'Pokemon')"
    )
    program_slug: str = Field(
        description="Unique immutable slug in lowercase_snake_case (e.g., 'retail360', 'pokemon')"
    )
    description: Optional[str] = Field(
        default=None,
        description="Program description"
    )
    abbrv: Optional[str] = Field(
        default=None,
        description="Short abbreviation (e.g., 'R360', 'PKM')"
    )
    is_active: bool = Field(default=True)
    attributes: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Extended config JSON. Common keys: version ('v3'), "
            "workday_client, modules_multisections (bool), "
            "modeAgent (bool), nameAgent, admin-roles, theme_color"
        )
    )
    image_url: Optional[str] = Field(default=None)
    visible: Optional[bool] = Field(default=True)
    allow_filtering: Optional[bool] = Field(default=None)
    filtering_show: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)
    client_ids: Optional[List[int]] = Field(
        default=None,
        description="Client IDs to assign. Use this OR client_slugs."
    )
    client_slugs: Optional[List[str]] = Field(
        default=None,
        description="Client slugs to assign (e.g., ['navigator_new', 'navigator_dev']). Resolved to client_ids automatically."
    )
    group_ids: List[int] = Field(
        default=[1],
        description="Group IDs with access (1=superuser, always included)"
    )

    @field_validator('program_slug')
    @classmethod
    def clean_slug(cls, v: str) -> str:
        return v.lower().strip().replace(' ', '_').replace('-', '_')

    @field_validator('group_ids')
    @classmethod
    def ensure_superuser(cls, v: List[int]) -> List[int]:
        if 1 not in v:
            v.insert(0, 1)
        return v


class ProgramUpdateInput(BaseModel):
    """Input for updating an existing program."""

    program_id: int = Field(description="ID of the program to update")
    program_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    abbrv: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    attributes: Optional[Dict[str, Any]] = Field(default=None)
    image_url: Optional[str] = Field(default=None)
    visible: Optional[bool] = Field(default=None)
    allow_filtering: Optional[bool] = Field(default=None)
    filtering_show: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)


# =============================================================================
# MODULE SCHEMAS
# =============================================================================

class ModuleCreateInput(BaseModel):
    """Input for creating a Navigator module."""

    module_name: str = Field(description="Module name (e.g., 'Sales Dashboard')")
    module_slug: str = Field(description="URL slug (e.g., 'retail360_sales')")
    program_id: Optional[int] = Field(default=None, description="Parent program ID (or use program_slug)")
    program_slug: Optional[str] = Field(default=None, description="Parent program slug (e.g., 'google360'). Resolved to program_id automatically.")
    classname: Optional[str] = Field(
        default=None, description="Python class name for the module"
    )
    description: Optional[str] = Field(default=None)
    active: bool = Field(default=True)
    parent_module_id: Optional[int] = Field(
        default=None, description="FK to parent module for tree hierarchy"
    )
    attributes: Dict[str, Any] = Field(
        default_factory=lambda: {
            "icon": "mdi:view-dashboard",
            "color": "#1E90FF",
            "order": "1",
            "layout_style": "min"
        },
        description=(
            "Visual config JSON. Keys: icon (iconify format), color (hex), "
            "order (string number), layout_style ('min'), menu_type ('parent'|'child'), "
            "menu_id (list of parent module IDs), parent_menu (display label), "
            "parent_img (SVG filename), img (SVG filename), quick ('true'|'false'), "
            "component ('ai' for chatbot modules), moduleAi (chatbot config)"
        )
    )
    allow_filtering: Optional[bool] = Field(default=None)
    filtering_show: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)
    client_ids: Optional[List[int]] = Field(
        default=None,
        description=(
            "Client IDs to activate the module for. "
            "If omitted, auto-resolved from the program's assigned clients (program_clients)."
        )
    )
    group_ids: List[int] = Field(
        default=[1],
        description="Group IDs with access to this module"
    )

    @field_validator('module_slug')
    @classmethod
    def clean_slug(cls, v: str) -> str:
        return v.lower().strip().replace(' ', '_').replace('-', '_')


class ModuleUpdateInput(BaseModel):
    """Input for updating an existing module."""

    module_id: int = Field(description="ID of the module to update")
    module_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    classname: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    attributes: Optional[Dict[str, Any]] = Field(default=None)
    allow_filtering: Optional[bool] = Field(default=None)
    filtering_show: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)


# =============================================================================
# DASHBOARD SCHEMAS
# =============================================================================

class DashboardCreateInput(BaseModel):
    """Input for creating a Navigator dashboard."""

    name: str = Field(description="Dashboard name")
    module_id: Optional[int] = Field(default=None, description="Container module ID (or use module_slug)")
    module_slug: Optional[str] = Field(default=None, description="Container module slug. Resolved to module_id automatically.")
    program_id: Optional[int] = Field(default=None, description="Program ID (or use program_slug)")
    program_slug: Optional[str] = Field(default=None, description="Program slug (e.g., 'google360'). Resolved to program_id automatically.")
    description: Optional[str] = Field(default=None)
    dashboard_type: str = Field(
        default="3",
        description="Type: '3'=standard (default), '1'=custom, '100'=CMS, '0'=home, '7'=sales"
    )
    position: int = Field(default=1, description="Display order")
    enabled: bool = Field(default=True)
    shared: bool = Field(default=False)
    published: bool = Field(default=True)
    allow_filtering: bool = Field(default=True)
    allow_widgets: bool = Field(default=True)
    is_system: bool = Field(default=True)
    params: Dict[str, Any] = Field(
        default_factory=lambda: {
            "closable": False, "sortable": False, "showSettingsBtn": True
        },
        description="Behavior config: closable, sortable, showSettingsBtn, _preload, min_required_filters"
    )
    attributes: Dict[str, Any] = Field(
        default_factory=lambda: {
            "cols": "12", "icon": "mdi:view-dashboard",
            "color": "#1E90FF", "explorer": "v3",
            "widget_location": {}
        },
        description=(
            "Visual config: cols, icon, color, explorer ('v3'), "
            "widget_location ({name: {h,w,x,y}}), sticky, disable_drag"
        )
    )
    conditions: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Filtering config: filtering (date, store, region), "
            "filteringadv (boolean filters), share (API call integration)"
        )
    )
    user_id: Optional[int] = Field(
        default=None,
        description="Creator user ID (integer). Omit if unknown — the toolkit will use its configured user_id."
    )

    @field_validator('user_id', mode='before')
    @classmethod
    def coerce_user_id(cls, v):
        if v is None or v == '':
            return None
        if isinstance(v, str) and not v.isdigit():
            return None  # reject non-numeric strings like 'anonymous'
        return int(v) if v is not None else None


class DashboardUpdateInput(BaseModel):
    """Input for updating an existing dashboard."""

    dashboard_id: str = Field(description="UUID of the dashboard to update")
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    enabled: Optional[bool] = Field(default=None)
    published: Optional[bool] = Field(default=None)
    position: Optional[int] = Field(default=None)
    params: Optional[Dict[str, Any]] = Field(default=None)
    attributes: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)


class CloneDashboardInput(BaseModel):
    """Input for cloning a dashboard with all its widgets."""

    source_dashboard_id: str = Field(description="UUID of the dashboard to clone")
    new_name: str = Field(description="Name for the cloned dashboard")
    target_module_id: Optional[int] = Field(
        default=None, description="Target module ID (None = same module)"
    )
    target_program_id: Optional[int] = Field(
        default=None, description="Target program ID (None = same program)"
    )
    user_id: Optional[int] = Field(default=None, description="Creator user ID")


# =============================================================================
# WIDGET SCHEMAS
# =============================================================================

class WidgetCreateInput(BaseModel):
    """Input for creating a widget in a dashboard."""

    dashboard_id: Optional[str] = Field(default=None, description="UUID of the container dashboard (or use dashboard_name)")
    dashboard_name: Optional[str] = Field(default=None, description="Dashboard name to search for. Resolved to dashboard_id automatically.")
    program_id: Optional[int] = Field(default=None, description="Program ID (or use program_slug)")
    program_slug: Optional[str] = Field(default=None, description="Program slug. Resolved to program_id automatically.")
    widget_type_id: str = Field(
        description=(
            "Widget type. Top 5: 'api-echarts' (charts), 'api-pqtable' (grids), "
            "'api-card' (KPI cards), 'api-table' (simple tables), "
            "'api-selectPqTable' (interactive grids). "
            "Media: 'media-editor-wysiwyg', 'media-iframe', 'media-bot', 'media-list-cards'. "
            "Other: 'api-maps', 'api-route', 'api-leaderboard', 'api-photo-feed-widget'"
        )
    )
    template_id: Optional[str] = Field(
        default=None,
        description="UUID of the base template (recommended - 99.9%% of widgets use templates)"
    )
    widget_name: Optional[str] = Field(default=None, description="Override template name")
    title: Optional[str] = Field(default=None, description="Override display title")
    widgetcat_id: int = Field(default=3, description="Category (3=generic, 1=walmart, 2=utility)")
    module_id: Optional[int] = Field(default=None)
    url: Optional[str] = Field(default=None, description="Data URL or iframe URL")
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Widget behavior config. For api-echarts: {graph: {type, xkey, ykey}, query: {slug}}. "
            "For api-card: {card: {cols, type, cards: {metric: {icon, class, title, value, format}}}}. "
            "For api-pqtable: {pqgrid: {...}, toolbar_items: [...]}. "
            "For settings override: {settings: {toolbar: {...}, header: {...}}}"
        )
    )
    attributes: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Visual config: icon, color, explorer ('v3'), fg_color"
    )
    conditions: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Filter config. Date tokens: CURRENT_DATE, FDOM, LDOM, FDOW, LDOW, FDOY. "
            "Structure: {lastdate, firstdate, where_cond, fields, grouping, ordering}"
        )
    )
    format_definition: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Column formatting. For api-table: {fnFormatPercent: [col_indices]}. "
            "For api-pqtable: {col_name: {align, order, title, dataIndx, dataType, format}}. "
            "For wysiwyg: {html: '<content>'}. For iframe: {url, type, height}"
        )
    )
    query_slug: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Data source reference. Simple: {slug: 'query_name'}. "
            "With options: {slug: 'name', comparison: true}. "
            "V3: {v3: true, slug: 'name', conditional_filtering: {...}}. "
            "Dashboard ref: {dashboard: 'name'}"
        )
    )
    grid_position: Optional[Dict[str, int]] = Field(
        default=None,
        description="Position in dashboard grid: {h: height, w: width(max12), x: col, y: row}"
    )


class WidgetUpdateInput(BaseModel):
    """Input for updating an existing widget."""

    widget_id: str = Field(description="UUID of the widget to update")
    widget_name: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    published: Optional[bool] = Field(default=None)
    url: Optional[str] = Field(default=None)
    params: Optional[Dict[str, Any]] = Field(default=None)
    attributes: Optional[Dict[str, Any]] = Field(default=None)
    conditions: Optional[Dict[str, Any]] = Field(default=None)
    format_definition: Optional[Dict[str, Any]] = Field(default=None)
    query_slug: Optional[Dict[str, Any]] = Field(default=None)
    grid_position: Optional[Dict[str, int]] = Field(default=None)


# =============================================================================
# ASSIGNMENT SCHEMAS
# =============================================================================

class AssignModuleClientInput(BaseModel):
    """Input for assigning a module to a client."""

    client_id: int = Field(description="Client ID")
    program_id: int = Field(description="Program ID")
    module_id: int = Field(description="Module ID")
    active: bool = Field(default=True)


class AssignModuleGroupInput(BaseModel):
    """Input for assigning a module to a group (permissions)."""

    group_id: int = Field(description="Group ID")
    module_id: int = Field(description="Module ID")
    program_id: int = Field(description="Program ID")
    client_id: int = Field(description="Client ID")
    active: bool = Field(default=True)


# =============================================================================
# LOOKUP & SEARCH SCHEMAS
# =============================================================================

class EntityLookupInput(BaseModel):
    """Input for looking up an entity by ID or slug."""

    entity_id: Optional[int] = Field(default=None, description="Numeric entity ID")
    entity_uuid: Optional[str] = Field(default=None, description="UUID (for dashboards/widgets)")
    entity_slug: Optional[str] = Field(default=None, description="Slug identifier")
    program_id: Optional[int] = Field(default=None, description="Filter by program")
    program_slug: Optional[str] = Field(default=None, description="Filter by program slug")
    module_id: Optional[int] = Field(default=None, description="Filter by module")
    dashboard_id: Optional[str] = Field(default=None, description="Filter by dashboard UUID")
    active_only: bool = Field(default=True, description="Only return active entities")
    limit: int = Field(default=50, description="Max results")


class SearchInput(BaseModel):
    """Input for searching across Navigator entities."""

    query: str = Field(description="Search text (searches names, slugs, titles)")
    entity_type: Optional[str] = Field(
        default=None,
        description="Limit to: 'program', 'module', 'dashboard', 'widget'. None = search all"
    )
    limit: int = Field(default=20, description="Max results per entity type")
