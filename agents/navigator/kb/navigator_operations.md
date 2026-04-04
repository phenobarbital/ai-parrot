# Navigator Agent - Base de Conocimiento Completa

> Documento de referencia para un agente AI que gestiona Programs, Modules, Dashboards y Widgets
> en la plataforma Navigator. Basado en datos reales de producción.

---

## 1. Estadísticas de Producción

| Entidad | Registros | Tabla |
|---------|-----------|-------|
| Clientes (tenants) | 108 | auth.clients |
| Programas | 127 (68 activos) | auth.programs |
| Grupos | 224 | auth.groups |
| User-Groups | 22,409 | auth.user_groups |
| Program-Clients | 278 | auth.program_clients |
| Program-Groups | 322 | auth.program_groups |
| Módulos | 913 | navigator.modules |
| Client-Modules | 2,301 | navigator.client_modules |
| Modules-Groups | 5,375 | navigator.modules_groups |
| Dashboards | 1,382 | navigator.dashboards |
| Widget Types | 108 | navigator.widget_types |
| Widget Categories | 6 | navigator.widgets_categories |
| Widget Templates | 1,218 | navigator.widgets_templates |
| Widgets | 4,494 | navigator.widgets |

---

## 2. Arquitectura de Ambientes

| client_id | Nombre | subdomain_prefix | Propósito |
|-----------|--------|------------------|-----------|
| 1 | TROC Navigator | navigator | **PRODUCCIÓN** (830 módulos) |
| 2 | Navigator New | navigator-new | Walmart producción (300 módulos) |
| 3 | Navigator DEV | navigator-dev | Desarrollo (164 módulos) |
| 4 | TROC Navigator Next | navai | Next/Preview (97 módulos) |
| 6 | TROC Navigator | navigator-staging | Staging (118 módulos) |
| 7 | TROC Navigator | navigator-demo | Demo (61 módulos) |

Cada programa tiene su propio client dedicado (ej: client_id=72 para Pokemon, client_id=79 para Retail360).

---

## 3. Programas - Patrones Reales

### 3.1 Generaciones de Programas

**Legacy (is_active=false)**: walmart, samsung, xfinity, tmobile, cricket, playstation, verizon, etc.
**Activos estándar**: walmart(3), apple(5), epson(19), att(27), hisense(47), bose(56), pokemon(99)
**Plataforma 360 (nueva generación, 2025-2026)**: retail360, hisense360, epson360, bose360, google360, troc360, att360, flex360, assembly360, bridgestone360, recruit360, primo360, pet360, assurant360

### 3.2 Estructura de `attributes` por tipo de programa

**Programa con integración Workday (HR):**
```json
{"workday_client": "bose"}
{"workday_client": ["epson_us", "epson_canada"]}
```

**Programa v3 (UI moderna):**
```json
{
  "version": "v3",
  "hide_menu": false,
  "logo_text": "WeProtectU",
  "hide_ticket": true,
  "theme_color": "cyan",
  "hide_support": true
}
```

**Programa 360 con AI Agent:**
```json
{
  "modeAgent": true,
  "nameAgent": "hisense_prices",
  "modules_multisections": true,
  "modules_multisections_label": "360 Style",
  "modules_multisections_default": true
}
```

**Programa con admin-roles (control granular):**
```json
{
  "admin-roles": {
    "superuser": {
      "widget": ["create", "delete"],
      "dashboard": ["create", "customize"]
    },
    "hisense360": {
      "widget": ["create"],
      "superuser": true
    }
  }
}
```

**Programa con URL externa (redirect):**
```json
{"url": "https://vision.mobileinsight.com/login", "tooltip": "Field Rep"}
```

**Programa con store fields (location-based):**
```json
{"store": {"fields": ["territory_id", "region_id", "market_id", "store_id", "store_name"]}}
```

### 3.3 Branding del Cliente
```json
{
  "logo": "/static/apps/{slug}/images/{slug}-login.png",
  "owner": "{owner_name}",
  "version": "2",
  "app_icon": "/static/apps/{slug}/images/{slug}-favicon.png",
  "app_logo": "/static/apps/{slug}/images/{slug}-login.png",
  "app_name": "{display_name}",
  "app_title": "Navigator"
}
```

### 3.4 Auth Backends disponibles
`BasicAuth`, `AzureAuth`, `ADFSAuth`, `APIKeyAuth`, `GoogleAuth`, `TokenAuth`, `TrocToken`, `DjangoAuth`, `NoAuth`

La mayoría de clientes usan: `{BasicAuth, AzureAuth}`

---

## 4. Módulos - Patrones Reales

### 4.1 Top programas por cantidad de módulos
| program_id | Programa | Módulos |
|------------|----------|---------|
| 108 | retail360 | 51 |
| 3 | walmart | 44 |
| 8 | retail | 42 |
| 124 | google360 | 35 |
| 117 | epson360 | 30 |
| 113 | hisense360 | 30 |
| 1 | troc | 29 |
| 47 | hisense | 23 |
| 112 | roadshows | 19 |

### 4.2 Jerarquía de Módulos (Patrón Menu)

Los módulos usan `attributes.menu_type` para crear jerarquía visual:

**Módulo padre:**
```json
{
  "icon": "mdi:store",
  "color": "#f57c20",
  "order": "4",
  "quick": "False",
  "menu_type": "parent",
  "parent_img": "execute.svg",
  "parent_menu": "Execute"
}
```

**Módulo hijo:**
```json
{
  "img": "routing.svg",
  "icon": "tabler:route",
  "color": "blue",
  "order": "1",
  "quick": "true",
  "menu_id": [938, 922],
  "menu_type": "child",
  "extra_order": {"922": 4, "938": 1},
  "parent_menu": "Prepare",
  "layout_style": "min"
}
```

**Módulo AI/Chatbot:**
```json
{
  "img": "bot-orange.svg",
  "icon": "mdi:robot-happy",
  "color": "#ff60f9",
  "menu_id": [940, 919],
  "moduleAi": {
    "chatBot": true,
    "agentBot": false,
    "titleBot": "Chatbot",
    "titleAgent": "Agents",
    "moduleAiTitle": "Field Assistant"
  },
  "component": "ai",
  "menu_type": "child"
}
```

**Módulo con modal/redirect:**
```json
{
  "img": "nextstop.svg",
  "icon": "fa fa-camera",
  "modal": {
    "type": "podcast",
    "title": "Podcast",
    "width": 400,
    "height": 200
  },
  "redirect": "https://retail360.trocdigital.io/media/audio/...",
  "menu_type": "child",
  "layout_style": "min"
}
```

### 4.3 Iconos
- **Legacy**: `fa fa-home`, `fa fa-tasks`, `fa fa-bar-chart-o`, `fa fa-users`
- **Modern (iconify)**: `mdi:robot-happy`, `tabler:route`, `mdi:store`, `mdi:chart-bar`
- **Images (img)**: `routing.svg`, `nextstop.svg`, `bot-orange.svg`, `smartpix.svg`, `execute.svg`

### 4.4 Filtering en Módulos
```json
{
  "filtering": {
    "date": {
      "name": "Pick a date range",
      "type": "date",
      "order": 1,
      "params": {
        "period": "weekly",
        "dateRange": ["weekly", "daily", "fullMonth", "custom", "mtd"],
        "weekOffset": "04-05"
      }
    },
    "store": {
      "id": "store_id",
      "name": "Store",
      "order": 6,
      "value": "store_name",
      "hierarchy": true
    },
    "region_id": {
      "id": "region_id",
      "name": "Area",
      "order": 4,
      "value": "region_name",
      "hierarchy": true
    }
  }
}
```

---

## 5. Dashboards - Patrones Reales

### 5.1 Tipos de Dashboard
| dashboard_type | Count | Uso |
|---------------|-------|-----|
| **3** | 319 | Standard (más común) |
| **1** | 94 | Custom/config |
| **100** | 26 | Content/CMS (iframes, wysiwyg) |
| **0** | 14 | Base/home |
| **7** | 13 | Sales complejo |

### 5.2 Estructura `params`
```json
{
  "closable": false,
  "sortable": false,
  "showSettingsBtn": true,
  "dashboardClone": true,
  "min_required_filters": 1,
  "_preload": {
    "loadAlert": {
      "id": "load-alert-id",
      "type": "warning",
      "title": "Warning",
      "message": "Please ensure one of the filters is applied..."
    }
  }
}
```

### 5.3 Estructura `attributes`
```json
{
  "cols": "12,12",
  "icon": "fa fa-tasks",
  "color": "#1E90FF",
  "order": 0,
  "fg_color": "#333333",
  "explorer": "v3",
  "row_header": "false",
  "multiselect": "true",
  "sticky": true,
  "disable_drag": true,
  "_skip_grid": true,
  "operational_date": "ROADSHOWS_DATE",
  "operational_date_label": "Data loaded up to ",
  "widget_location": {
    "timestamp": 1746652646798,
    "Widget Name": {"h": 37, "w": 12, "x": 0, "y": 0},
    "Another Widget": {"h": 34, "w": 12, "x": 0, "y": 37}
  }
}
```

### 5.4 Widget Location (Grid Layout)
**Formato moderno** (en `attributes.widget_location`):
```json
{
  "timestamp": 1746652646798,
  "Opportunities": {"h": 37, "w": 12, "x": 0, "y": 0},
  "List of Employees": {"h": 34, "w": 12, "x": 0, "y": 37}
}
```
- `w`: ancho (máx 12 columnas)
- `h`: alto (en unidades de grid)
- `x`: posición horizontal (0-11)
- `y`: posición vertical

**Formato legacy** (en columna `widget_location`):
```json
{
  "lobipanel-parent-stateful_2977_0": {"<widget-uuid>": 0}
}
```

### 5.5 Conditions (Filtering System)
```json
{
  "filtering": {
    "date": {
      "name": "Pick a date range",
      "type": "date",
      "jump": true,
      "order": 0,
      "params": {
        "period": "yearly",
        "dateRange": ["yearly", "custom", "weekly", "fullMonth", "mtd", "daily"]
      }
    },
    "<field_name>": {
      "id": "<db_column>",
      "name": "<Display Label>",
      "slug": "<api_selector_slug>",
      "order": 1,
      "value": "<display_column>",
      "hierarchy": true,
      "multiple": true,
      "required": true,
      "dependence": {"value": "store", "selector": "origin_selector"},
      "add_condition": {"associate_id": "associate_id"}
    }
  },
  "filteringadv": {
    "<field>": {"type": "boolean", "slug": "hisense_focus", "format": "boolean"}
  },
  "share": {
    "slug": "{BASE_URL_API}/troc/api/v1/travel_search",
    "method": "POST",
    "callback": "pokemonOptimalRoute"
  }
}
```

### 5.6 Slug Pattern
Auto-generado como: `<descriptive_name>_<random_6char>`
Ejemplos: `tasks_qtGbM9`, `main_MbkQee`, `chatbot_agent_Gh4WU0`

---

## 6. Widget Types - Catálogo Completo (108 tipos)

### 6.1 Top 5 tipos (cubren 95% del uso)

| widget_type | Descripción | classbase | Templates | Widgets |
|------------|-------------|-----------|-----------|---------|
| `api-echarts` | Charts (bar, line, donut, gauge, area) | EchartsWidget | 529 | 1,342 |
| `api-pqtable` | Grids avanzados ParamQuery | pqTableWidget | 86 | 902 |
| `api-card` | KPI cards con drilldowns | CardWidget | 241 | 720 |
| `api-table` | Tablas simples con roll-up | ApiTableWidget | 181 | 392 |
| `api-selectPqTable` | Grids interactivos con select | selectpqtableWidget | 46 | 158 |

### 6.2 Tipos de media (UI components)
| widget_type | Descripción | classbase |
|------------|-------------|-----------|
| `media-editor-wysiwyg` | Editor WYSIWYG | EditorWysiwyg |
| `media-iframe` | Iframe embebido | Iframe |
| `media-list-cards` | Lista de cards | ListOrCard |
| `media-carousel` | Carrusel de imágenes | Carousel |
| `media-list-of-links` | Lista de enlaces | ListOfLinks |
| `media-list-of-documents` | Lista de documentos | ListOfDocuments |
| `media-bot` | Chatbot AI | ChatbotAI |
| `media-botagent` | Chatbot Agent AI | ChatbotAgentAI |
| `media-comments` | Comentarios | Comments |
| `media-announcements` | Anuncios | Announcements |
| `media-actionPanel` | Panel de acciones | ActionPanel |
| `media-ticket-zammad` | Tickets Zammad | TicketZammad |

### 6.3 Tipos especializados
| widget_type | Descripción | classbase |
|------------|-------------|-----------|
| `api-maps` / `api-leaflet` | Mapas | MapsWidget / MapsLeaflet |
| `api-route` | Rutas óptimas | RouteWidget |
| `api-leaderboard` | Ranking/leaderboard | LeaderboardWidget |
| `api-rewards` | Sistema de recompensas | RewardsWidget |
| `api-photo-feed-widget` | Feed de fotos | photoFeedWidget |
| `api-file-manager` | Gestor de archivos | FileManager |
| `api-ia` | Widget con agente AI | iaWidget |
| `expert-system` | Sistema experto | systemExpertWidget |
| `priority-briefing` | Briefing por prioridades | PriorityBriefing |
| `task-detail` / `task-status` | Gestión de tareas | TaskDetailsPanelWidgetWidget |
| `map-reps` | Mapa de representantes | MapRepsWidget |

### 6.4 Widget Categories
| widgetcat_id | category | color | Uso |
|---|---|---|---|
| 1 | walmart | #f39C12 | Widgets Walmart |
| 2 | utility | #418aca | Utilidades genéricas |
| 3 | **generic** | #65BD77 | **Más usado** |
| 4 | mso | #f39C12 | Widgets MSO |
| 5 | Blank | #ffffff | Vacío/placeholder |
| 6 | loreal | #ffffff | Widgets L'Oreal |

---

## 7. Widgets - Estructura de params por tipo

### 7.1 `api-echarts` (Charts)
```json
{
  "graph": {
    "type": "bar|barline|area|donut|double_donut|gauge|echarts|line",
    "pie": true,
    "xkey": "column_name",
    "ykey": ["col1", "col2"],
    "yline": "line_column",
    "xformat": "date|category",
    "zoom": "false",
    "gradients": true,
    "rotatexAxis": true,
    "legend_bottom": true,
    "series": {
      "col_name": {
        "type": "bar|line",
        "color": "blue|#hex",
        "order": 0,
        "format": "fnFormatNumber",
        "label_position": "inside|top",
        "stack": "A"
      }
    },
    "markPoint": {"active": false}
  },
  "query": {"slug": "query_slug_name"},
  "evClick": {
    "active": true,
    "callback": "donutDrilldown",
    "params": {"drilldowns": true}
  }
}
```

### 7.2 `api-card` (KPIs)
```json
{
  "ajax": {"type": "POST"},
  "card": {
    "cols": 2,
    "type": "card|trend-card",
    "colspan": 3,
    "cards": {
      "metric_name": {
        "icon": "fa fa-fw fa-phone",
        "class": "navigator-blue|navigator-teal|navigator-red",
        "order": 0,
        "title": "Total Agent Calls",
        "value": ["total_calls"],
        "format": "fnFormatNumberInteger|fnFormatPercent|fnFormatMoney",
        "hidden": false,
        "drilldowns": [{
          "title": "Detail View",
          "params": {"query": {"slug": "drill_slug"}},
          "classbase": "pqTableWidget",
          "attributes": {"icon": "fa fa-table"},
          "conditions": {
            "fields": ["col1", "col2"],
            "ordering": "col1 DESC",
            "where_cond": {}
          },
          "format_definition": {}
        }],
        "drilldownsClear": true
      }
    }
  },
  "query": {
    "slug": "query_slug",
    "comparison": true,
    "comparison_period": "mtd|column_compare"
  }
}
```

### 7.3 `api-pqtable` (Grids avanzados)
```json
{
  "ajax": {"method": "POST"},
  "query": {"slug": "slug_name"},
  "pqgrid": {
    "rowInit": "scorecardSales",
    "maxHeight": 1000,
    "pageModel": {"rPP": 10000, "layout": ["strDisplay"]},
    "scrollModel": {"autoFit": true},
    "sortModel": {"sorter": [{"dir": "up", "dataIndx": "column"}]}
  },
  "pqgridOptions": {"freezeCols": 3},
  "toolbar_items": ["export_raw", "filter", "export_raw_excel"],
  "addFilterConditions": {"store_id": "store_id"},
  "groupModel": {
    "on": true,
    "title": ["{0} ({1})"],
    "dataIndx": ["program_slug"],
    "collapsed": [false]
  }
}
```

### 7.4 `api-table` (Tablas simples)
```json
{
  "ajax": {"method": "POST"},
  "query": {
    "slug": "slug_name",
    "hlevel": ["company", "territory_id", "region_name"]
  },
  "table": {
    "roll_up": {
      "sum": ["qty", "revenue"],
      "avg": ["rate"],
      "total": "TOTAL:",
      "total_col": "description"
    }
  }
}
```

### 7.5 `api-selectPqTable` (Grids interactivos)
```json
{
  "ajax": {"METHOD": "POST"},
  "query": {"slug": "slug_name"},
  "pqgrid": {"pageModel": {"rPP": 1000}},
  "actions": {
    "btns": ["play", "export", "sound"],
    "render": "btnsRenderTasksActions"
  },
  "refresh": {"active": true, "milliseconds": 300000},
  "groupModel": {
    "on": true,
    "dataIndx": ["program_slug"],
    "collapsed": [false]
  },
  "toolbar_items": ["filter", "export_raw"]
}
```

### 7.6 Settings/Toolbar Override (cualquier tipo)
```json
{
  "hidden": true,
  "settings": {
    "toolbar": {
      "cut": false, "max": false, "pin": false,
      "copy": false, "help": false, "like": false,
      "show": true, "clone": false, "close": false,
      "share": false, "export": false, "reload": false,
      "collapse": false, "comments": false,
      "filtering": false, "screenshot": false
    },
    "footer": {"like": true, "show": true, "share": true, "comments": true},
    "header": {"icon": false, "show": false, "title": false, "toolbar": false},
    "appearance": {"color": "#37507f", "border": false, "opacity": 0, "background": "#"}
  }
}
```

---

## 8. Conditions - Tokens de Fecha

| Token | Significado |
|-------|-------------|
| `CURRENT_DATE` | Fecha actual |
| `YESTERDAY` | Ayer |
| `FDOM` | First Day of Month |
| `LDOM` | Last Day of Month |
| `FDOW` | First Day of Week |
| `LDOW` | Last Day of Week |
| `FDOY` | First Day of Year |
| `FDOFFM` | First Day of Fiscal Full Month |
| `LDOFFM` | Last Day of Fiscal Full Month |
| `FDOPW` | First Day of Previous Week |
| `LDOPW` | Last Day of Previous Week |
| `POSTPAID_DATE` | Fecha específica de postpaid |
| `KPI_CE_DATE` | Fecha de KPI Customer Experience |

---

## 9. format_definition - Patrones

### Para api-table (por índice de columna):
```json
{
  "fnFormatPercent": [3],
  "fnFormatPercentPlain": [3, 4, 6, 8],
  "fnFormatNumberInteger": [1, 2],
  "fnFormatMoney": [7],
  "fnFormatMoneyInteger": [1, 2, 4, 5, 6],
  "colHidden": [0]
}
```

### Para api-pqtable (definición de columnas):
```json
{
  "column_name": {
    "align": "left|right|center",
    "order": 1,
    "title": "Display Title",
    "dataIndx": "column_name",
    "dataType": "string|float|integer",
    "format": "$##,###|##,###|#,###.00%",
    "hidden": true,
    "filter": {"crules": [{"condition": "range"}]},
    "render": "dateAndTime|link|clickCell",
    "maxWidth": "200",
    "width": 330
  }
}
```

### Para media-editor-wysiwyg (HTML content):
```json
{"html": "<h1><strong>Content here...</strong></h1>"}
```

### Para media-iframe:
```json
{
  "url": "https://example.com/page",
  "type": ["iFrame"],
  "height": "100%",
  "external": true
}
```

---

## 10. query_slug - Patrones de Referencia a Datos

```json
// Simple
{"slug": "walmart_postpaid_yoy_by_day"}

// Con opciones
{"slug": "query_name", "null_rollup": "true"}
{"slug": "query_name", "options": {"select_child": "true"}}

// Con jerarquía
{"slug": "query_name", "hlevel": ["company", "territory_id", "region_id"]}

// Con comparación temporal
{"slug": "query_name", "comparison": true, "comparison_period": "mtd"}

// V3 con filtering condicional
{"v3": true, "slug": "epson360_query", "conditional_filtering": {"visit": ["store_id"]}}

// Referencia a dashboard (no API)
{"dashboard": "photoFeed"}
{"dashboard": "Map"}

// Múltiples opciones (dropdown)
{"slug": [{"Postpaid": "dataexport_postpaid"}, {"Raw": "dataexport_raw"}]}
```

---

## 11. Herencia Template → Widget

**99.9% de los widgets tienen template_id**. El patrón es:

1. Template define la configuración base (params, conditions, format_definition, query_slug)
2. Widget hereda todo del template
3. Widget puede override cualquier campo individual
4. La vista `vw_active_widgets` resuelve con `COALESCE(widget.campo, template.campo)`

**Ejemplo real de herencia:**
- Template `71e3670f` (api-selectPqTable para tareas) es usado por:
  - Widget programa bose → `query_slug: {"slug": "bose_tasks"}`
  - Widget programa tracfone → `query_slug: {"slug": "tracfone_tasks"}`
  - Widget programa viba_demo → `query_slug: {"slug": "viba_demo_tasks"}`
  - Misma estructura visual, diferente fuente de datos

---

## 12. Flujos Operativos para el Agente

### 12.1 Crear un Programa Nuevo

```sql
-- 1. Crear programa
INSERT INTO auth.programs (program_name, program_slug, is_active, abbrv, attributes, created_by)
VALUES ('Mi Programa', 'mi_programa', true, 'MP',
        '{"version": "v3", "modules_multisections": true}'::jsonb, 'agent');

-- 2. Crear grupo dedicado
INSERT INTO auth.groups (group_name, client_id, is_active, created_by)
VALUES ('mi_programa', :dedicated_client_id, true, 'agent');

-- 3. Asignar a clientes (prod + dedicated)
INSERT INTO auth.program_clients (program_id, client_id, program_slug, active)
VALUES (:program_id, 1, 'mi_programa', true),  -- navigator prod
       (:program_id, :dedicated_client_id, 'mi_programa', true);

-- 4. Asignar grupos (superuser + dedicado)
INSERT INTO auth.program_groups (program_id, group_id)
VALUES (:program_id, 1),  -- superuser SIEMPRE
       (:program_id, :group_id);
```

### 12.2 Crear un Módulo con Jerarquía

```sql
-- Módulo padre
INSERT INTO navigator.modules (module_name, module_slug, classname, active, description, program_id, attributes)
VALUES ('Overview', 'mi_programa_overview', 'Overview', true, 'Program Overview', :program_id,
        '{"icon": "mdi:view-dashboard", "color": "#1E90FF", "order": "1", "menu_type": "parent", "parent_img": "overview.svg", "parent_menu": "Overview"}'::jsonb);

-- Módulo hijo
INSERT INTO navigator.modules (module_name, module_slug, classname, active, description, program_id, attributes)
VALUES ('Sales Dashboard', 'mi_programa_sales', 'SalesDashboard', true, 'Sales', :program_id,
        '{"img": "sales.svg", "icon": "mdi:chart-bar", "color": "blue", "order": "1", "quick": "true", "menu_id": [:parent_module_id], "menu_type": "child", "layout_style": "min", "parent_menu": "Overview"}'::jsonb);

-- Activar para cliente
INSERT INTO navigator.client_modules (client_id, program_id, module_id, active)
VALUES (:client_id, :program_id, :module_id, true);

-- Asignar a grupo
INSERT INTO navigator.modules_groups (group_id, module_id, program_id, client_id, active)
VALUES (:group_id, :module_id, :program_id, :client_id, true);
```

### 12.3 Crear un Dashboard

```sql
INSERT INTO navigator.dashboards (
  name, module_id, program_id, enabled, shared, published,
  allow_filtering, allow_widgets, dashboard_type, position,
  render_partials, save_filtering, is_system,
  params, attributes, conditions
) VALUES (
  'Sales Overview', :module_id, :program_id, true, false, true,
  true, true, '3', 1, false, false, true,
  '{"closable": false, "sortable": false, "showSettingsBtn": true}'::jsonb,
  '{"cols": "12", "icon": "mdi:chart-bar", "color": "#1E90FF", "explorer": "v3", "widget_location": {"timestamp": extract(epoch from now())::bigint * 1000}}'::jsonb,
  '{"filtering": {"date": {"name": "Pick a date range", "type": "date", "order": 0, "params": {"period": "weekly", "dateRange": ["weekly", "custom", "monthly"]}}}}'::jsonb
);
```

### 12.4 Crear un Widget (con template)

```sql
-- Seleccionar template existente apropiado
-- Los más usados: api-echarts para gráficos, api-pqtable para grids, api-card para KPIs

INSERT INTO navigator.widgets (
  widget_name, title, dashboard_id, template_id,
  program_id, widget_type_id, widgetcat_id,
  active, published,
  params, attributes, conditions, query_slug, format_definition
) VALUES (
  'mi_programa Sales by Day', 'Sales by Day', :dashboard_id, :template_id,
  :program_id, 'api-echarts', 3,
  true, true,
  '{"graph": {"type": "bar", "xkey": "date", "ykey": ["sales"], "xformat": "date"}, "query": {"slug": "mi_programa_sales_by_day"}}'::jsonb,
  '{"icon": "mdi:chart-bar", "color": "#ffffff", "explorer": "v3"}'::jsonb,
  '{"lastdate": "CURRENT_DATE", "firstdate": "FDOM", "where_cond": {}}'::jsonb,
  '{"slug": "mi_programa_sales_by_day"}'::jsonb,
  NULL
);

-- Actualizar widget_location del dashboard
UPDATE navigator.dashboards
SET attributes = jsonb_set(
  attributes,
  '{widget_location}',
  (COALESCE(attributes->'widget_location', '{}'::jsonb) ||
   jsonb_build_object('Sales by Day', '{"h": 20, "w": 12, "x": 0, "y": 0}'::jsonb))
)
WHERE dashboard_id = :dashboard_id;
```

### 12.5 Clonar un Dashboard Completo

```sql
-- 1. Copiar dashboard
INSERT INTO navigator.dashboards (name, description, module_id, program_id, user_id,
  enabled, shared, published, allow_filtering, allow_widgets, dashboard_type,
  position, params, attributes, conditions, render_partials, save_filtering, is_system)
SELECT 'Copy of ' || name, description, :new_module_id, :new_program_id, :user_id,
  enabled, shared, false, allow_filtering, allow_widgets, dashboard_type,
  position, params, attributes, conditions, render_partials, save_filtering, false
FROM navigator.dashboards WHERE dashboard_id = :source_id
RETURNING dashboard_id AS new_dashboard_id;

-- 2. Copiar widgets
INSERT INTO navigator.widgets (widget_name, title, description, url,
  params, embed, attributes, conditions, cond_definition, where_definition,
  format_definition, query_slug, save_filtering, master_filtering, allow_filtering,
  module_id, program_id, widget_slug, widgetcat_id, widget_type_id,
  active, published, template_id, dashboard_id)
SELECT widget_name, title, description, url,
  params, embed, attributes, conditions, cond_definition, where_definition,
  format_definition, query_slug, save_filtering, master_filtering, allow_filtering,
  :new_module_id, :new_program_id, NULL, widgetcat_id, widget_type_id,
  active, published, template_id, :new_dashboard_id
FROM navigator.widgets WHERE dashboard_id = :source_id AND active = true;
```

---

## 13. Reglas de Negocio para el Agente

1. **program_slug es inmutable** - nunca cambiar después de creación
2. **Superuser (group_id=1) siempre tiene acceso** - incluir en program_groups
3. **client_id=1 (navigator) es el hub central** - mapear programas aquí siempre
4. **Soft delete obligatorio** - usar `active=false` / `enabled=false`, nunca DELETE
5. **Slugs se auto-generan** por triggers (`update_slugify()`) en templates y widgets
6. **widget_location.timestamp** - actualizar al modificar layout
7. **explorer: "v3"** - usar en dashboards y widgets modernos
8. **widgetcat_id=3 (generic)** - usar por defecto para widgets nuevos
9. **dashboard_type="3"** - usar por defecto para dashboards nuevos
10. **Replicar permisos por ambiente** - modules_groups debe tener entradas para cada client_id relevante (1=prod, 3=dev, 6=staging)
