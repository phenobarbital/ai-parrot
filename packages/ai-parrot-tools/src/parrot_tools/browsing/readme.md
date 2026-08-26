# WebBrowsingToolkit — Catalogued, Deterministic Site Automation

`WebBrowsingToolkit` extends `WebScrapingToolkit` with a per-site **action
catalog**: named, parameterized scripts ("guiones") written in the same
BrowserAction DSL, stored on disk, and replayed deterministically against a
persistent browser session. The agent maps a natural-language request
("inicia sesión en Hooba") to a catalogued site + action, and the toolkit
executes the exact recorded steps — no LLM improvisation at run time.

## Concepts

| Concept | Meaning |
|---|---|
| **Site** | A registered web application (`hooba-es`), with base URL, title and aliases for natural-language resolution ("hooba", "hooba.es"). |
| **Action** | A named script for one site. Kinds: `navigation` (pure page movement), `operation` (does something: refresh a dashboard, download a report), `composite` (references other actions in order). |
| **Params** | Declared inputs substituted into steps via `{{name}}` placeholders (e.g. the customer to invoice). |
| **Requires** | Prerequisite actions (e.g. `login`) auto-injected once per sequence. |

## Disk layout

One folder per site, one JSON file per action:

```
browsing_catalog/
    hooba-es/
        _site.json               # SiteInfo (base_url, aliases, ...)
        login.json               # SiteAction (DSL steps)
        goto-dashboard.json
        create-invoice-draft.json
```

## Quick start

```python
from parrot_tools.browsing import WebBrowsingToolkit

toolkit = WebBrowsingToolkit(
    catalog_dir="browsing_catalog",
    driver_type="playwright",            # fixed at construction — no on-the-fly switch
    # Real Chrome profile: session cookies, saved logins, password keyring
    user_data_dir="/home/user/.config/google-chrome",
    profile_directory="Default",
    browser_channel="chrome",            # launch real Chrome (Playwright)
)

# 1. Register the site
await toolkit.register_site(
    base_url="https://hooba.es", title="Hooba", aliases=["hooba"],
)

# 2. Catalog an action (steps use the WebScrapingToolkit DSL)
await toolkit.save_site_action(
    site="hooba",
    name="login",
    description="Iniciar sesión en Hooba",
    steps=[
        {"action": "navigate", "url": "https://hooba.es/login"},
        {"action": "authenticate", "credential_provider": "hooba",
         "username_selector": "#email", "password_selector": "#password",
         "submit_selector": "button[type=submit]"},
        {"action": "wait", "condition": "#dashboard", "timeout": 15},
    ],
)

await toolkit.save_site_action(
    site="hooba",
    name="search-customer",
    description="Buscar un cliente en el CRM",
    requires=["login"],                      # auto-runs login first
    params={"customer": {"description": "Nombre del cliente"}},
    steps=[
        {"action": "navigate", "url": "https://hooba.es/crm/customers"},
        {"action": "fill", "selector": "#search", "value": "{{customer}}",
         "press_enter": True},
    ],
)

# 3. Run deterministically ("quiero buscar a ACME en Hooba")
result = await toolkit.run_site_action(
    "hooba", "search-customer", params={"customer": "ACME"},
)
```

## Composition

Composite actions chain siblings; `run_site_sequence` executes an ad-hoc
plan. Prerequisites are deduplicated across the whole sequence (login runs
at most once), and everything shares one browser session:

```python
await toolkit.save_site_action(
    site="hooba", name="invoice-draft", kind="composite",
    description="Montar un draft de factura para un cliente",
    params={"customer": {"description": "Cliente a facturar"}},
    compose=[
        {"action": "search-customer", "params": {"customer": "{{customer}}"}},
        {"action": "open-invoicing"},
        {"action": "new-draft"},
    ],
)

# Or an ad-hoc plan derived from the user's request:
await toolkit.run_site_sequence(
    "hooba",
    plan=["login", "goto-dashboard",
          {"action": "search-customer", "params": {"customer": "ACME"}}],
)
```

## Safety rails

- **Validation at save time**: steps must be valid BrowserAction DSL, every
  `{{placeholder}}` must be a declared parameter, and every `loop` must be
  bounded by `max_loop_iterations` (default 50). Invalid scripts never
  enter the catalog.
- **Bounded loops at run time**: loop limits are clamped again before
  execution (defense in depth).
- **No credentials in scripts**: use `authenticate` steps with
  `credential_provider` + a `credential_resolver` (CredentialBroker) —
  never literal passwords in catalog JSON.
- **Cycle/depth guards**: composite expansion detects reference cycles and
  caps nesting depth.

## Recording new actions

Scripts are defined by the user; alternatively, ask the agent to perform an
assisted navigation (e.g. via `scrape()` + `await_human` steps or the
Chrome DevTools MCP) and then persist the resulting step list with
`save_site_action(source="recorded")`.

## Agent tools exposed

`register_site`, `list_sites`, `list_site_actions`, `get_site_action`,
`save_site_action`, `delete_site_action`, `run_site_action`,
`run_site_sequence`, `close_browser` — plus everything inherited from
`WebScrapingToolkit` (`scrape`, `crawl`, `plan_*`).
