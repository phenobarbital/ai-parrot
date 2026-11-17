# AI-Parrot Tools Quick Reference Guide

Fast lookup for key AI-parrot tools with minimal examples.

---


## MathTool

**Purpose:** Basic arithmetic operations

```python
from parrot.tools.math import MathTool

tool = MathTool()
result = await tool.execute(a=10, operation="add", b=5)
# Returns: {"result": 15, "expression": "10 + 5 = 15"}
```

**Operations:** `add`, `subtract`, `multiply`, `divide`, `sqrt`

**Quick Examples:**
```python
await tool.execute(a=144, operation="sqrt")           # √144 = 12
await tool.execute(a=100, operation="divide", b=4)    # 100 ÷ 4 = 25
await tool.execute(a=7, operation="multiply", b=6)    # 7 × 6 = 42
```

---


## OpenWeatherTool

**Purpose:** Current weather and forecasts

```python
from parrot.tools.openweather import OpenWeatherTool

tool = OpenWeatherTool(api_key="YOUR_API_KEY")
weather = await tool.execute(
    latitude=40.7128,
    longitude=-74.0060,
    request_type='weather',  # or 'forecast'
    units='imperial'         # 'metric', 'standard'
)
```

**Key Parameters:**
- `latitude`, `longitude`: Coordinates
- `request_type`: `'weather'` | `'forecast'`
- `units`: `'imperial'` | `'metric'` | `'standard'`
- `forecast_days`: 1-16 (for forecasts)

**Quick Examples:**
```python
# Current weather
await tool.execute(latitude=51.5074, longitude=-0.1278, units='metric')

# 5-day forecast
await tool.execute(latitude=35.6762, longitude=139.6503,
                   request_type='forecast', forecast_days=5)
```

---


## DatabaseTool

**Purpose:** Natural language to SQL, query execution

```python
from parrot.tools.db import DatabaseTool, DatabaseFlavor

tool = DatabaseTool(
    default_connection_params={
        DatabaseFlavor.POSTGRESQL: {
            "host": "localhost",
            "database": "mydb",
            "user": "user",
            "password": "pass"
        }
    }
)

result = await tool.execute(
    natural_language_query="Show top 10 users by signup date",
    database_flavor="postgresql",
    operation="full_pipeline"
)
```

**Operations:**
- `schema_extract`: Get table schemas
- `query_generate`: NL → SQL
- `query_validate`: Check SQL safety
- `query_execute`: Run SQL
- `full_pipeline`: All of the above

**Quick Examples:**
```python
# Direct SQL
await tool.execute(
    sql_query="SELECT * FROM users WHERE active = true",
    operation="query_execute"
)

# Schema only
await tool.execute(
    operation="schema_extract",
    schema_names=["public"]
)

# Natural language
await tool.execute(
    natural_language_query="What products sold over $1000 last month?",
    operation="full_pipeline"
)
```

**Supported DBs:** PostgreSQL, MySQL, SQLite, SQL Server, Oracle

---


## WebScrapingTool

**Purpose:** Browser automation and web scraping

```python
from parrot.tools.scraping import WebScrapingTool

tool = WebScrapingTool(
    browser='chrome',      # 'firefox', 'edge', 'undetected'
    headless=True,
    mobile=False
)

result = await tool.execute(
    steps=[
        {"action": "navigate", "url": "https://example.com"},
        {"action": "click", "selector": "#button"},
        {"action": "wait", "condition": "element_visible", "selector": ".result"}
    ],
    selectors=[
        {"name": "title", "selector": "h1", "extract_type": "text"}
    ]
)
```

**Common Actions:**

| Action | Example |
|--------|---------|
| Navigate | `{"action": "navigate", "url": "https://..."}` |
| Click | `{"action": "click", "selector": "#btn"}` |
| Fill Form | `{"action": "fill", "selector": "#email", "value": "user@example.com"}` |
| Wait | `{"action": "wait", "condition": "element_visible", "selector": ".content"}` |
| Scroll | `{"action": "scroll", "direction": "down", "amount": 500}` |
| Screenshot | `{"action": "screenshot", "filename": "page.png"}` |
| Get Text | `{"action": "get_text", "selector": "p"}` |
| Get HTML | `{"action": "get_html"}` |

**Selector Extraction:**

```python
selectors=[
    # Single text element
    {"name": "title", "selector": "h1.main", "extract_type": "text"},

    # Multiple elements
    {"name": "prices", "selector": ".price", "extract_type": "text", "multiple": True},

    # Attribute
    {"name": "links", "selector": "a", "extract_type": "attribute",
     "attribute": "href", "multiple": True}
]
```

**Quick Examples:**
```python
# Simple scraping
await tool.execute(
    steps=[{"action": "navigate", "url": "https://news.ycombinator.com"}],
    selectors=[{"name": "titles", "selector": ".titleline", "multiple": True}]
)

# Form login
await tool.execute(
    steps=[
        {"action": "navigate", "url": "https://example.com/login"},
        {"action": "fill", "selector": "#username", "value": "user"},
        {"action": "fill", "selector": "#password", "value": "pass"},
        {"action": "click", "selector": "button[type='submit']"}
    ]
)

# Mobile scraping
mobile_tool = WebScrapingTool(mobile=True, mobile_device='iPhone 14')
```

---


## Full Catalog

The complete tool catalog lives in the [Wiki](https://github.com/phenobarbital/ai-parrot/wiki/Home).