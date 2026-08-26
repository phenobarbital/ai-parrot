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

The agent flow is: `list_sites` → `list_site_actions` (match intent →
action + params) → `run_site_action` / `run_site_sequence`. The LLM only
decides **which** script to run and with **what** parameters — the steps
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
