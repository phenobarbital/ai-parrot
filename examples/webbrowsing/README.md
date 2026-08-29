# WebBrowsingToolkit example — agent + pre-built catalog

Example of an agent driving a website through **catalogued, deterministic
action scripts** ("guiones") with `WebBrowsingToolkit`
(`parrot_tools.browsing`). The target is
[quotes.toscrape.com](https://quotes.toscrape.com) — a public scraping
sandbox with a demo login (any credentials are accepted), quote listings,
tag pages and author pages.

## Files

| File | What it is |
|---|---|
| `catalog/quotes-toscrape-com/` | **Pre-built catalog**: `_site.json` + one JSON script per action, ready to use. |
| `seed_catalog.py` | Source of truth — regenerates the catalog (`python seed_catalog.py`). Importable with a different `base_url`. |
| `browsing_agent.py` | LLM agent wired with the toolkit: it matches natural language against the catalog and runs actions deterministically. |
| `local_demo.py` | **No LLM, no network**: serves an offline replica of the site's DOM and runs the same catalog against it — doubles as an end-to-end smoke test. |
| `../agents/webbrowser/webbrowsing_agent.py` | `WebNavigatorAgent` — an Agent subclass that receives the Chrome profile paths (`user_data_dir`, `profile_directory`) at initialization and drives sites through this catalog. |

## Catalogued actions

| Action | Kind | Params | Description |
|---|---|---|---|
| `login` | operation | `username`, `password` (defaults) | Fill and submit the demo login form. |
| `list-quotes` | operation | — | Extract every quote (text/author/tags) on the home page. |
| `quotes-by-tag` | operation | `tag` | Open `/tag/{{tag}}/` and extract its quotes. |
| `top-tags` | operation | — | Read the "Top Ten tags" sidebar. |
| `author-info` | operation | `author` | Extract an author's name, birth date and bio. |
| `login-and-list` | composite | forwards login params | `requires: [login]` + `compose: [list-quotes]` — login is injected once per sequence. |

## Run it

```bash
# Deterministic, offline (no API keys needed):
python examples/webbrowsing/local_demo.py

# With an LLM in the loop (needs a provider key, e.g. GOOGLE_API_KEY):
python examples/webbrowsing/browsing_agent.py "dame las citas del tag love"
python examples/webbrowsing/browsing_agent.py "inicia sesión en quotes y lista la portada"
```

## The structured contract (`execute_web_task`)

The core agentic pattern: from "register a customer at hooba" the LLM
prepares ONE structured request — it never improvises navigation —

```json
{"site": "hooba", "action": "register-customer",
 "data": {"name": "ACME S.L.", "vat": "B12345678"}}
```

and `execute_web_task` resolves the site's catalog, loads the script and
replays it deterministically (prerequisites like `login` injected once).
Multi-step flows use `plan` instead of `action`:

```json
{"site": "hooba", "data": {"customer": "ACME"},
 "plan": [{"action": "goto-crm"},
          {"action": "search-customer"},
          {"action": "new-invoice-draft"}]}
```

Failures come back **structured and repairable** instead of raising, so
the LLM can self-correct in one round-trip:

| `error.code` | Hint included |
|---|---|
| `unknown_site` | `known_sites` (slug, title, aliases) |
| `unknown_action` | `available_actions` (name, description, params) |
| `missing_params` | `expected_params` per action + `provided_data` |
| `invalid_request` / `invalid_plan` | validation message |

`WebTaskRequest` (`parrot_tools.browsing`) is a Pydantic model, so it
also works as a structured-output schema for the LLM directly.

The discovery tools (`list_sites`, `list_site_actions`,
`run_site_action`, `run_site_sequence`) remain available — the LLM only
ever decides **which** script to run and with **what** data; the steps
themselves are replayed exactly as catalogued.

## Using a real Chrome profile

To operate a site where you are already logged in, hand the toolkit your
Chrome user-data directory (close Chrome first, or use a copy — Chrome
locks a profile in use):

```python
WebBrowsingToolkit(
    catalog_dir="browsing_catalog",
    driver_type="playwright",
    user_data_dir="~/.config/google-chrome",
    profile_directory="Default",
    browser_channel="chrome",   # real Chrome, not bundled Chromium
)
```

For real logins, never store passwords in scripts — `save_site_action`
rejects literal credentials. Use an `authenticate` step with
`credential_provider` plus a `credential_resolver` (CredentialBroker).
