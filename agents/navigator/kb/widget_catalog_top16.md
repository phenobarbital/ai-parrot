# Navigator Widget Catalog (Batch 1 - Top Used)

This catalog documents the exact JSON structures an AI agent must provide when creating each widget type. The frontend loads widgets dynamically via `ComponentType.svelte`, which resolves the component directory from `classbase` (stripping the `Widget` suffix) or by capitalizing `widget_type_id`.

**Key resolution rule:** `classbase: "EchartsWidget"` loads `./type/Echarts/Echarts.svelte`. If `classbase` is null, the system capitalizes `widget_type_id` to derive the directory name.

All widgets receive a single `export let data: any` prop. The widget reads its configuration from Svelte context: `const widget = getContext('widget')` which provides `$widget.params`, `$widget.format_definition`, `$widget.conditions`, `$widget.attributes`, etc.

---

## 1. Echarts (Charts)

**Component:** `Echarts/Echarts.svelte`
**classbase:** `EchartsWidget`
**widget_type_id:** `echarts` (or `api-echarts`)
**Renders:** Bar, line, area, barline, donut/pie, funnel, pictorial bar, word cloud charts via Apache ECharts.

### Chart Type Resolution
The `params.graph.type` value determines which sub-module is loaded:
- `"bar"` / `"dimensions"` / `"area"` / `"barline"` -> `types/bar.ts` (bar/line/area/stacked)
- `"donut"` -> `types/donut.ts` (pie / donut chart)
- `"funnel"` -> `types/funnel.ts`
- `"pictorial"` -> `types/pictorial.ts`
- `"cloudword"` -> `types/cloudword.ts` (word cloud)
- `"echarts"` -> `types/echarts.ts` (raw ECharts config passthrough)

### params structure (bar / line / area / barline)
```json
{
  "query": {
    "slug": "my_query_slug"
  },
  "graph": {
    "type": "bar",
    "xkey": "month",
    "ykey": ["sales", "returns"],
    "yline": ["target"],
    "stack": false,
    "rotatexAxis": 30,
    "format": "fnFormatNumber",
    "formatter": "percentage",
    "transformData": {
      "key": "category_column",
      "aux": "series_column",
      "val": "value_column"
    },
    "transformDataAll": false,
    "transformDataRename": ["extra_col"],
    "labels": {
      "sales": "Total Sales",
      "returns": "Total Returns"
    },
    "series": {
      "sales": {
        "order": 0,
        "type": "bar",
        "color": "blue",
        "stack": "A",
        "label_name": "Sales",
        "label_hide": false,
        "label_position": "top",
        "label_color": "#333",
        "label_size": 12,
        "format": true,
        "symbol": "emptyCircle",
        "yAxisIndex": 0,
        "step": false,
        "average": true,
        "hidden": false
      }
    },
    "hide": ["internal_id"]
  },
  "echarts": {},
  "drilldowns": {
    "colModel": {},
    "slug": "detail_query_slug",
    "conditions": {},
    "params": {
      "cell": "response",
      "where_cond": true
    },
    "classbase": "pqTableWidget",
    "multiDrilldowns": [],
    "colModel": {}
  },
  "settings": {}
}
```

### params structure (donut / pie)
```json
{
  "query": { "slug": "my_query_slug" },
  "graph": {
    "type": "donut",
    "pie": false,
    "title": "Distribution",
    "hide": ["internal_id"],
    "keys": ["label_field", "value_field"],
    "transformData": true,
    "colors": {
      "category_a": "blue",
      "category_b": "green"
    }
  }
}
```

### params structure (funnel)
```json
{
  "query": { "slug": "my_query_slug" },
  "graph": {
    "type": "funnel",
    "echarts": {}
  }
}
```

### params structure (pictorial)
```json
{
  "query": { "slug": "my_query_slug" },
  "graph": {
    "type": "pictorial",
    "max": "max_field_name",
    "name": "Chart Name",
    "formatter": "percentage",
    "legend": ["Legend A"],
    "series": [
      {
        "name": "Metric A",
        "value": "field_name",
        "icon": "path://M...",
        "color": "#229aff"
      }
    ]
  }
}
```

### format_definition (series mapping, NEW version)
Used when `params.graph.series` is empty. Maps data column names to display names:
```json
{
  "db_column_name": "Display Name",
  "another_column": "Another Label"
}
```

### conditions
```json
{
  "filterdate": true,
  "firstdate": "2024-01-01",
  "lastdate": "2024-12-31",
  "where_cond": {
    "region": "West"
  },
  "fields": ["field1", "field2"]
}
```

### Available gradient colors for series
`blue`, `green`, `orange`, `aqua`, `pink`, `yellow`, `mint`, `purple`, `gray`, `red`, `teal`, `indigo`, `lime`, `coral`, `turquoise`, `cyan`, `magenta`, `brown`, `beige`, `sky`, `lavender`, `wine`, `sand`, `peach`, `navyBlue`, `skyBlue`, `tealGreen`, `deepIndigo`, `royalBlue`, `crimsonRed`

---

## 2. pqTable / AgGrid (Advanced Data Grid)

**Component:** `pqTable/pqTable.svelte` (delegates to `AgGrid/AgGrid.svelte`)
**classbase:** `pqTableWidget`
**widget_type_id:** `pqtable` (or `api-pqtable`)
**Renders:** Full-featured data grid with sorting, filtering, pagination, drilldowns, CRUD actions, export, and toolbar.

> Note: `pqTable` is a thin wrapper. The actual implementation lives in `AgGrid/AgGrid.svelte` which uses `ag-grid-community`.

### params structure
```json
{
  "query": {
    "slug": "my_query_slug"
  },
  "colModelDef": true,
  "toolbar_items": ["export_raw", "filter", "search", "columns"],
  "pqgrid": {
    "autoHeight": true,
    "row_id": "unique_id_field",
    "rowInit": "somePostRenderCallback"
  },
  "aggrid": {
    "pagination": true,
    "paginationPageSize": 25,
    "rowSelection": "single"
  },
  "drilldowns": {
    "cellClick": "postRenderOpenDrilldown",
    "slug": "detail_slug",
    "multiDrilldowns": [
      {
        "slug": "drilldown_detail_slug",
        "title": "Detail View",
        "classbase": "pqTableWidget",
        "attributes": { "icon": "fa fa-table" },
        "conditions": {},
        "colModel": {},
        "params": {
          "cell": "field_name",
          "where_cond": true,
          "drilldowns": null
        },
        "extendConditions": "true"
      }
    ]
  },
  "btnsActions": {
    "top": {
      "title": "Add New",
      "callback": "openFormBuilder",
      "class": "btn-primary"
    },
    "bottom": {
      "title": "Export",
      "callback": "exportData",
      "params": "exportParam"
    }
  },
  "sharedData": {
    "cellClick": "postRenderOpenDrilldown"
  },
  "demo": {
    "show": false,
    "data": []
  },
  "settings": {}
}
```

### format_definition (column definitions)
Each key is a data column name. This controls column rendering:
```json
{
  "column_name": {
    "order": 1,
    "title": "Display Title",
    "align": "left",
    "minWidth": 150,
    "maxWidth": 300,
    "format": "####",
    "render": "dateAndTime",
    "hidden": false,
    "editable": false,
    "pinned": "left",
    "filter": true,
    "cellRenderer": "customRenderer",
    "postRender": "postRenderOpenDrilldown",
    "postRenderBtn": "someButtonCallback"
  }
}
```

### conditions
```json
{
  "filterdate": true,
  "firstdate": "2024-01-01",
  "lastdate": "2024-12-31",
  "where_cond": { "status": "active" },
  "fields": ["field1", "field2"]
}
```

### attributes
```json
{
  "icon": "fa fa-table",
  "fullcontent": true,
  "header": true
}
```

---

## 3. selectpqtable (Interactive Grid)

**Component:** `selectpqtable/selectpqtable.svelte` (delegates to `AgGrid/AgGrid.svelte`)
**classbase:** `selectpqtableWidget`
**widget_type_id:** `selectpqtable`
**Renders:** Same as pqTable/AgGrid. This is a legacy alias.

Same params/format_definition/conditions as pqTable above.

---

## 4. ApiTable (Simple Table)

**Component:** `ApiTable/ApiTable.svelte` (delegates to `AgGrid/AgGrid.svelte`)
**classbase:** `ApiTableWidget`
**widget_type_id:** `api-table` (or `apitable`)
**Renders:** Same as pqTable/AgGrid but exposed as a simpler "API table" type.

Same params/format_definition/conditions as pqTable above.

---

## 5. Card (KPI Cards)

**Component:** `Card/Card.svelte`
**classbase:** `CardWidget`
**widget_type_id:** `card` (or `api-card`)
**Renders:** Grid of KPI cards showing numeric values with icons, drilldowns, and formatting.

### Data expectation
Query should return a SINGLE row with multiple columns. Each column becomes a card:
```json
[{ "total_sales": 1500, "active_users": 342, "revenue": 98500.75 }]
```

### params structure
```json
{
  "query": { "slug": "my_kpi_query" },
  "card": {
    "colspan": 4,
    "cards": {}
  },
  "cols": 4,
  "default_data": { "total_sales": 0, "active_users": 0 },
  "settings": {}
}
```

### format_definition (card configuration, NEW version)
Each key matches a data column name. Overrides card appearance:
```json
{
  "total_sales": {
    "order": 0,
    "title": "Total Sales",
    "icon": "tabler-currency-dollar",
    "col": 4,
    "format": "fnFormatNumberOne",
    "frontMask": "$",
    "backMask": "",
    "class": "custom-card-class",
    "hidden": false,
    "footer": "Last 30 days",
    "jump": false,
    "value": [null, "secondary_field"],
    "formatSecond": "fnFormatNumberOne",
    "color": "text-blue-500",
    "drilldowns": [
      {
        "title": "Sales Detail",
        "classbase": "pqTableWidget",
        "attributes": { "icon": "fa fa-table" },
        "params": {
          "query": { "slug": "sales_detail" },
          "toolbar_items": ["export_raw", "filter"]
        },
        "conditions": {},
        "format_definition": {},
        "extendConditions": "true"
      }
    ]
  },
  "active_users": {
    "order": 1,
    "title": "Active Users",
    "icon": "tabler-users",
    "format": "fnFormatNumberOne",
    "hidden": false
  }
}
```

### Available format functions
- `fnFormatNumberOne` - one decimal
- `fnFormatNumber` - formatted number
- `fnFormatNumberInteger` - integer
- Custom format strings like `"####"`

### conditions
Same as Echarts (filterdate, firstdate, lastdate, where_cond, fields).

---

## 6. Maps (Google Maps with Routing)

**Component:** `Maps/Maps.svelte`
**classbase:** `MapsWidget`
**widget_type_id:** `maps` (or `api-maps`)
**Renders:** Google Maps with route calculation, traffic layer, draggable waypoints, "Add to my routes" functionality.

### Data expectation
Either an array of location objects OR a structured object:

Array mode (pins only):
```json
[
  { "latitude": 37.7749, "longitude": -122.4194, "name": "Store A", "glyph": "A", "background": "red", "color": "white" }
]
```

Object mode (routing):
```json
{
  "url": "https://maps.googleapis.com/maps/api/staticmap?markers=...",
  "origin": { "lat": 37.7749, "lng": -122.4194 },
  "departure": "2024-06-15T08:00:00",
  "locations": [
    { "lat": 37.7749, "lng": -122.4194, "label": "O", "color": "green" },
    { "lat": 34.0522, "lng": -118.2437, "label": "A", "color": "0x0000FF", "size": "mid" },
    { "lat": 36.1699, "lng": -115.1398, "label": "D", "color": "red" }
  ],
  "allLocations": [],
  "resetMarkers": false
}
```

### params structure
```json
{
  "query": { "slug": "my_locations_query" },
  "mapHeight": "500px",
  "postRenderCalculate": "calculateTotalDistance",
  "allPins": {
    "background": "orange",
    "color": "black",
    "glyph": "S",
    "scale": 0.5,
    "labelKey": "store_name"
  },
  "btnsActions": {
    "bottom": {
      "title": "Export Route",
      "callback": "exportRoute",
      "params": "exportMap",
      "class": "btn-primary mt-2"
    }
  },
  "refresh_map_change": true,
  "settings": {}
}
```

### conditions
Same as standard (filterdate, firstdate, lastdate, where_cond, fields).

---

## 7. MapsLeaflet (Leaflet Maps with Layers)

**Component:** `MapsLeaflet/MapsLeaflet.svelte`
**classbase:** `MapsLeafletWidget`
**widget_type_id:** `mapsleaflet` (or `api-mapsleaflet`)
**Renders:** Leaflet map with multiple configurable layers (point markers, polygon/zipcode choropleth), scale legends, popups with images, and tile layer selection.

### params structure
```json
{
  "query": { "slug": "my_points_query" },
  "leaflet": {
    "latField": "latitude",
    "lngField": "longitude",
    "zoom": 5,
    "minZoom": 2,
    "maxZoom": 15,
    "defaultTileLayer": "Carto Light",
    "enabledTileLayers": ["OpenStreetMap", "Google Streets", "Google Satellite", "Carto Light", "Carto Dark"],
    "display_layers": {
      "show": "Show Layers",
      "hide": "Hide Layers"
    },
    "layers": [
      {
        "name": "Stores",
        "slug": "stores_locations_query",
        "callback": "typePoint",
        "loadActive": true,
        "idField": "store_id",
        "style": {
          "fillColor": "#ff7800",
          "color": "#000",
          "weight": 1,
          "opacity": 1,
          "fillOpacity": 0.7
        },
        "popup": [
          { "key": "store_name", "label": "Store" },
          { "key": "address", "label": "Address" },
          { "key": "photo_path", "label": "Photo", "type": "image" },
          { "key": "revenue", "label": "Revenue", "decimals": 2 }
        ],
        "radius": {
          "key": "revenue",
          "scale_factor": 3,
          "min_radius": 9,
          "max_radius": 18
        },
        "popupFetch": ["fetchStoreDetails"],
        "conditions_remove_keys": ["excluded_filter_key"]
      },
      {
        "name": "Zipcodes",
        "slug": "zipcode_data_query",
        "callback": "typePolygonByZipcodes",
        "loadActive": false,
        "keyField": "value_field",
        "keyZipcode": "zipcode",
        "style": {
          "weight": 1,
          "opacity": 0.7,
          "fillOpacity": 0.5
        },
        "scale": {
          "style": { "weight": 1, "opacity": 0.7, "fillOpacity": 0.5 },
          "colors": [
            { "min": 0, "max": 25, "color": "#fee5d9" },
            { "min": 25, "max": 50, "color": "#fcae91" },
            { "min": 50, "max": 75, "color": "#fb6a4a" },
            { "min": 75, "max": 100, "color": "#cb181d" }
          ]
        },
        "popup": [
          { "key": "zipcode", "label": "Zipcode" },
          { "key": "value_field", "label": "Value" }
        ]
      }
    ]
  },
  "settings": {}
}
```

### Layer callbacks
- `"typePoint"` - renders circle markers from lat/lng data
- `"typePolygonByZipcodes"` - fetches zipcode polygon geometry and renders choropleth

### conditions
Same as standard.

---

## 8. Route (Route List with Drag Reorder)

**Component:** `Route/Route.svelte`
**classbase:** `RouteWidget`
**widget_type_id:** `route` (or `api-route`)
**Renders:** Ordered list of route stops with drag-and-drop reordering. Tracks distance/duration deltas against optimal route. Works with Maps widget via shared dashboard data.

### Data expectation
Array of location objects:
```json
[
  { "store_name": "Store A", "label": "A", "store_id": 123 },
  { "store_name": "Store B", "label": "B", "store_id": 456 }
]
```

### params structure
```json
{
  "query": { "slug": "my_route_query" },
  "map_item": {
    "name": "store_name",
    "label": "label"
  },
  "reorder": {
    "allowed": true,
    "callback": "reorderRouteCallback"
  },
  "settings": {}
}
```

### Dashboard interaction
Reads from `$dashboard.gridItemsData['Total Distance']` and `$dashboard.gridItemsData['Total Duration']` to compute deltas. When reordered, calls `actionReorder[callback](dashboard, data)`.

### conditions
Same as standard.

---

## 9. photoFeed (Photo Gallery)

**Component:** `photoFeed/photoFeed.svelte`
**classbase:** `photoFeedWidget`
**widget_type_id:** `photofeed` (or `api-photofeed`)
**Renders:** Masonry photo gallery with pagination, category filtering, image selection/download/PPT export, drilldowns on click, and table view mode.

### Data expectation
Array of photo objects:
```json
[
  {
    "photo": "filename.jpg",
    "directory": "photos/2024",
    "security": 1,
    "store_name": "Store A",
    "store_id": 123,
    "created_date": "2024-06-15",
    "visitor_name": "John Doe",
    "categories_name": ["Category A"],
    "category_id": [1, 2],
    "description": "Store front photo"
  }
]
```

### params structure
```json
{
  "query": { "slug": "my_photos_query" },
  "config": {
    "pageSize": 15,
    "forceSingleColumn": false,
    "photos": 5,
    "photo": "custom_photo_field",
    "program": "program_slug",
    "tablePhoto": false,
    "doublePhoto": false,
    "tableView": [
      { "key": "photo_id", "key_dup": "photo_id_dup", "label": "Photo ID", "format": "date" }
    ]
  },
  "photoPath": {
    "category": "program_slug_photo_categories"
  },
  "filteringCategory": true,
  "filteringCategoryNotOrder": false,
  "downloadImages": true,
  "export_ppt": true,
  "highlightKey": "is_flagged",
  "drilldowns": [
    {
      "title": "Photo Detail",
      "classbase": "pqTableWidget",
      "attributes": { "icon": "fa fa-table" },
      "params": {
        "query": { "slug": "photo_detail" },
        "cellValue": "photo_id",
        "cell": "response",
        "where_cond": true
      },
      "conditions": {},
      "extendConditions": "true"
    }
  ],
  "settings": {}
}
```

### conditions
Same as standard.

---

## 10. EditorWysiwyg (Rich Text / HTML)

**Component:** `EditorWysiwyg/EditorWysiwyg.svelte`
**classbase:** `EditorWysiwygWidget`
**widget_type_id:** `editorwysiwyg` (or `api-editorwysiwyg`)
**Renders:** Static HTML content from format_definition. Supports dynamic variable replacement via callbacks.

### params structure
```json
{
  "callback": {
    "method": "getStoreTitle",
    "slug": "query_slug_for_title",
    "param": "store_id",
    "replace": [
      { "var": "{{store_name}}", "varModel": "store_name" },
      { "var": "{{static_text}}", "varString": "Hello World" }
    ]
  },
  "settings": {}
}
```

### format_definition
```json
{
  "html": "<h1>Welcome to {{store_name}}</h1><p>Dashboard overview for your region.</p>"
}
```

### conditions
Same as standard (not typically used for HTML rendering).

---

## 11. Iframe (Embed)

**Component:** `Iframe/Iframe.svelte`
**classbase:** `IframeWidget`
**widget_type_id:** `iframe` (or `api-iframe`)
**Renders:** Embedded iframe, image, or HTML embed. Supports URL dropdown selection.

### format_definition
Single URL:
```json
{
  "url": "https://example.com/embed",
  "type": "iFrame",
  "height": "500px"
}
```

Multiple URL selector:
```json
{
  "urls": [
    { "value": "https://example.com/page1", "label": "Page 1" },
    { "value": "https://example.com/page2", "label": "Page 2" }
  ],
  "label": "Select a view",
  "type": "iFrame",
  "height": "100%"
}
```

Image mode:
```json
{
  "url": "https://example.com/image.png",
  "type": "img"
}
```

### params structure
```json
{
  "settings": {}
}
```

### Data fallback
If format_definition has no URL, falls back to `data.url`.

---

## 12. quickStart (Module Tiles)

**Component:** `quickStart/quickStart.svelte`
**classbase:** `quickStartWidget`
**widget_type_id:** `quickstart` (or `api-quickstart`)
**Renders:** Grid of module navigation tiles. Reads from the global `storeModules` store. Supports multi-level parent/child navigation with breadcrumbs.

### params structure
```json
{
  "quickstart": true,
  "multisections": true,
  "settings": {}
}
```

### Data
Does not use query data. Reads modules from `$storeModules` which are loaded at app level. Each module has `attributes.quick`, `attributes.menu_type`, `attributes.order`, `attributes.redirect`, `attributes.menu_id`, `attributes.parent_menu_id`.

### format_definition / conditions
Not used.

---

## 13. Leaderboard

**Component:** `Leaderboard/Leaderboard.svelte`
**classbase:** `LeaderboardWidget`
**widget_type_id:** `leaderboard` (or `api-leaderboard`)
**Renders:** Ranked list with optional podium (top 3 with gold/silver/bronze styling).

### Data expectation
Array of user objects, pre-sorted by rank:
```json
[
  { "display_name": "Alice", "num_badges": 150 },
  { "display_name": "Bob", "num_badges": 120 },
  { "display_name": "Charlie", "num_badges": 95 }
]
```

### params structure
```json
{
  "query": { "slug": "leaderboard_query" },
  "podium": true,
  "settings": {}
}
```

### format_definition / conditions
Standard conditions. No format_definition needed.

---

## 14. Rewards

**Component:** `Rewards/Rewards.svelte`
**classbase:** `RewardsWidget`
**widget_type_id:** `rewards` (or `api-rewards`)
**Renders:** Grid of reward/badge cards with grouping. Clicking a reward opens a drilldown table with reward details.

### Data expectation
Array of reward objects:
```json
[
  { "reward": "Star Performer", "reward_id": 1, "rewards": 5, "icon": "star.png", "description": "Top performer badge" }
]
```

### params structure
```json
{
  "query": { "slug": "rewards_query" },
  "groupBy": "reward_group",
  "title": "Reward Details",
  "drilldowns": [
    {
      "params": {
        "query": { "slug": "navigator_reward_details_by_user" },
        "toolbar_items": ["export_raw", "filter"]
      },
      "classbase": "pqTableWidget",
      "attributes": { "icon": "fa fa-table" },
      "conditions": {},
      "format_definition": {
        "award_id": { "order": 1, "title": "Award ID", "format": "####" },
        "reward": { "order": 3, "title": "Reward" },
        "awarded_at": { "title": "Awarded At", "render": "dateAndTime", "align": "center" },
        "icon": { "hidden": true }
      },
      "extendConditions": "false"
    }
  ],
  "settings": {}
}
```

### conditions
Standard conditions.

---

## 15. ChatbotAI (AI Chatbot)

**Component:** `ChatbotAI/ChatbotAI.svelte`
**classbase:** `ChatbotAIWidget`
**widget_type_id:** `chatbotai` (or `api-chatbotai`)
**Renders:** Chat interface with message history, suggested questions, source documents, disclaimer text. Connects to VITE_API_AI_URL.

### params structure
```json
{
  "navai": {
    "endpoint": "chat/my_bot_name",
    "bot": "my_bot_name",
    "chatbot_id": "uuid-of-chatbot",
    "suggested_questions": [
      { "prompt_title": "What is the revenue?", "prompt_query": "Show me total revenue" }
    ],
    "disclaimer": "AI responses may not be 100% accurate.",
    "disclaimer_text": "AI responses may not be 100% accurate.",
    "initialMessages": [
      { "role": "bot", "content": "Hello! How can I help you?" }
    ]
  },
  "settings": {}
}
```

### Endpoint resolution
- If `endpoint` starts with `agents/`, it uses agent mode (no usage tracking).
- URL is built as: `VITE_API_AI_URL/api/v1/{endpoint}`
- For regular bots: `VITE_API_AI_URL/api/v1/chat/{bot_name}`

### format_definition / conditions
Not typically used. Data prop is received but not required for chat functionality.

---

## 16. ChatbotAgentAI (AI Agent Chatbot)

**Component:** `ChatbotAgentAI/ChatbotAgentAI.svelte`
**classbase:** `ChatbotAgentAIWidget`
**widget_type_id:** `chatbotagentai` (or `api-chatbotagentai`)
**Renders:** Agent-based chat interface with file drawer, slug drawer, session persistence. Requires Google session authentication.

### params structure
```json
{
  "navai": {
    "bot": "my_agent_name",
    "chatbot_id": "uuid-of-agent",
    "initialMessages": []
  },
  "settings": {}
}
```

### Key differences from ChatbotAI
- Requires `$storeUser.gooogleSession` to be active
- Agent ID is stored in `localStorage` per tab/path
- Supports file attachments in responses (DrawerFile)
- Uses a different API endpoint pattern (`/api/agents/{agentId}/chat`)

---

## Common Structures

### Standard conditions object
```json
{
  "filterdate": true,
  "firstdate": "2024-01-01",
  "lastdate": "2024-12-31",
  "where_cond": {
    "field_name": "value",
    "another_field": "another_value"
  },
  "fields": ["field1", "field2"]
}
```

### Standard attributes object
```json
{
  "icon": "fa fa-chart-bar",
  "fullcontent": false,
  "header": true,
  "height": "400px"
}
```

### Standard settings (used by all widgets)
The `params.settings` object is passed through to drilldown children. Its structure is widget-specific but commonly includes display preferences.

### Widget type_id to classbase mapping
| widget_type_id | classbase | Component Directory |
|---|---|---|
| echarts | EchartsWidget | Echarts |
| pqtable | pqTableWidget | pqTable |
| selectpqtable | selectpqtableWidget | selectpqtable |
| api-table / apitable | ApiTableWidget | ApiTable |
| card | CardWidget | Card |
| maps | MapsWidget | Maps |
| mapsleaflet | MapsLeafletWidget | MapsLeaflet |
| route | RouteWidget | Route |
| photofeed | photoFeedWidget | photoFeed |
| editorwysiwyg | EditorWysiwygWidget | EditorWysiwyg |
| iframe | IframeWidget | Iframe |
| quickstart | quickStartWidget | quickStart |
| leaderboard | LeaderboardWidget | Leaderboard |
| rewards | RewardsWidget | Rewards |
| chatbotai | ChatbotAIWidget | ChatbotAI |
| chatbotagentai | ChatbotAgentAIWidget | ChatbotAgentAI |
