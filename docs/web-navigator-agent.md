# WebNavigatorAgent — Catalogued Web Navigation on Your Chrome Profile

## Overview

`WebNavigatorAgent` is an `Agent` that operates websites through the
**action catalog** of `WebBrowsingToolkit` (`parrot_tools.browsing`). The
LLM never improvises selectors or navigation steps: from a natural-language
request it prepares **one** structured `WebTaskRequest`
(`{site, action, data}`) and calls `execute_web_task`, which replays a
pre-recorded script deterministically over a persistent browser session.

Because the toolkit can be pointed at a **real Google Chrome user-data
directory**, every catalogued action runs with your session cookies, saved
logins and OS keyring — ideal for repeatable flows on sites where you are
already authenticated.

The reference implementation lives in
`examples/agents/webbrowser/webbrowsing_agent.py`; the sample catalog
(targeting the public sandbox [quotes.toscrape.com](https://quotes.toscrape.com))
lives in `examples/webbrowsing/`.

Compare with [WebAgent](web-agent.md), which lets the LLM drive Chrome
freely through the Chrome DevTools Protocol.

## Architecture

```
"dame las citas del tag love"
        │
        ▼
WebNavigatorAgent (Agent + system prompt)
        │  WebTaskRequest {site: "quotes", action: "quotes-by-tag", data: {tag: "love"}}
        ▼
WebBrowsingToolkit.execute_web_task
        │  resolves site → loads catalog/<site>/<action>.json
        │  injects prerequisites (requires: [login]) once per sequence
        ▼
Playwright / Selenium driver (fixed at construction)
        │  user_data_dir + profile_directory + browser_channel="chrome"
        ▼
Google Chrome (your profile)
```

## The agent

```python
from parrot.bots.agent import Agent
from parrot_tools.browsing import WebBrowsingToolkit


class WebNavigatorAgent(Agent):
    def __init__(
        self,
        user_data_dir=None,
        profile_directory="Default",
        catalog_dir="examples/webbrowsing/catalog",
        driver_type="playwright",
        headless=True,
        **kwargs,
    ):
        self.browsing_toolkit = WebBrowsingToolkit(
            catalog_dir=catalog_dir,
            driver_type=driver_type,
            browser="chrome",
            headless=headless,
            user_data_dir=user_data_dir,
            profile_directory=profile_directory if user_data_dir else None,
            # Launch the system Chrome so keyring-encrypted data is readable
            browser_channel="chrome" if user_data_dir else None,
            confirm_runs=False,   # demo; keep True for production sites
        )
        super().__init__(
            name="WebNavigator",
            tools=[self.browsing_toolkit],
            system_prompt=SYSTEM_PROMPT,
            **kwargs,
        )

    async def close(self):
        await self.browsing_toolkit.close_browser()
```

| Constructor arg | Description |
|---|---|
| `user_data_dir` | Chrome user-data directory (`~/.config/google-chrome`, `~/Library/Application Support/Google/Chrome`, `%LOCALAPPDATA%\Google\Chrome\User Data`). `None` → clean, profile-less browser. |
| `profile_directory` | Profile folder inside `user_data_dir` (`Default`, `Profile 1`, …). |
| `catalog_dir` | Catalog root: one folder per site, one JSON per action. |
| `driver_type` | `"playwright"` or `"selenium"` — fixed for the agent's lifetime. |
| `headless` | Run without a window. |
| `**kwargs` | Forwarded to `Agent` (`llm`, `use_llm`, …). |

The system prompt tells the model to build one `WebTaskRequest`, to repair
it from the structured error hints when the toolkit returns
`status="error"`, and to use `list_sites` / `list_site_actions` when
unsure — never to invent steps.

## Running the example

```bash
source .venv/bin/activate
uv pip install ai-parrot-tools playwright
playwright install chromium

# Clean browser, headless
python examples/agents/webbrowser/webbrowsing_agent.py "dame las citas del tag love"

# Visible window
HEADLESS=0 python examples/agents/webbrowser/webbrowsing_agent.py "inicia sesión en quotes"

# Against your real Chrome profile
CHROME_USER_DATA=~/.config/google-chrome CHROME_PROFILE="Profile 1" HEADLESS=0 \
python examples/agents/webbrowser/webbrowsing_agent.py "inicia sesión en quotes y lista la portada"
```

| Env var | Default | Purpose |
|---|---|---|
| `CHROME_USER_DATA` | — | User-data directory; unset → profile-less browser. |
| `CHROME_PROFILE` | `Default` | Profile folder inside `CHROME_USER_DATA`. |
| `HEADLESS` | `1` | `0` shows the browser. |

!!! warning "Chrome locks a profile in use"
    Close Chrome before running with `CHROME_USER_DATA`, or point the agent
    at a copy of the directory (next section).

Programmatic use:

```python
agent = WebNavigatorAgent(
    user_data_dir="~/.config/google-chrome",
    profile_directory="Default",
    driver_type="playwright",
    headless=False,
    llm="google:gemini-2.5-flash",
)
await agent.configure()
answer, _ = await agent.invoke("dame las citas del tag love")
await agent.close()
```

## Copying your Chrome profile

Working on a copy avoids the profile lock and protects your real profile
from anything the agent does. Quit Chrome first (otherwise the SQLite
cookie/history databases may be copied mid-write) and skip the caches.

=== "Linux"

    ```bash
    SRC="$HOME/.config/google-chrome"      # chromium: ~/.config/chromium
    DST="$HOME/.config/chrome-debug"

    pkill -x chrome 2>/dev/null; sleep 2
    rsync -a --delete \
      --exclude='Singleton*' \
      --exclude='*/Cache/' --exclude='*/Code Cache/' --exclude='*/GPUCache/' \
      --exclude='*/Service Worker/CacheStorage/' --exclude='GrShaderCache/' \
      "$SRC/" "$DST/"
    ```

=== "macOS"

    ```bash
    SRC="$HOME/Library/Application Support/Google/Chrome"
    DST="$HOME/chrome-debug"

    osascript -e 'quit app "Google Chrome"'; sleep 2
    rsync -a --delete \
      --exclude='Singleton*' \
      --exclude='*/Cache/' --exclude='*/Code Cache/' --exclude='*/GPUCache/' \
      --exclude='*/Service Worker/CacheStorage/' --exclude='GrShaderCache/' \
      "$SRC/" "$DST/"
    ```

- `Singleton*` (`SingletonLock`, `SingletonSocket`, `SingletonCookie`) are
  Chrome's lock files — never copy them; delete them from `$DST` if Chrome
  claims the copy is already in use.
- Find which `Profile N` is which in `chrome://version` (*Profile Path*)
  or `jq '.profile.info_cache' "$SRC/Local State"`.
- Cookies and passwords are encrypted with the OS keyring
  (`libsecret` / Keychain), bound to the **user**, not the path: the copy
  stays readable on the same machine and account, not on another host.
  macOS may prompt for "Chrome Safe Storage" access the first time.
- Re-run the `rsync` to refresh the copy with new sessions.

Use `$DST` both as `CHROME_USER_DATA` here and as `--user-data-dir` when
[starting Chrome with remote debugging](web-agent.md#attaching-to-your-own-chrome-remote-debugging)
for `WebAgent`.

## The action catalog

The catalog is plain JSON on disk — `catalog/<site>/_site.json` plus one
file per action. Scripts use the same `BrowserAction` DSL as
`WebScrapingToolkit` (`navigate`, `click`, `fill`, `extract`, `loop`, …)
with `{{param}}` placeholders.

```json title="catalog/quotes-toscrape-com/_site.json"
{
  "site": "quotes-toscrape-com",
  "base_url": "https://quotes.toscrape.com",
  "title": "Quotes to Scrape",
  "aliases": ["quotes", "toscrape"]
}
```

```json title="catalog/quotes-toscrape-com/quotes-by-tag.json"
{
  "name": "quotes-by-tag",
  "kind": "operation",
  "params": {"tag": {"description": "Tag slug to browse", "required": true, "example": "love"}},
  "steps": [
    {"action": "navigate", "url": "https://quotes.toscrape.com/tag/{{tag}}/"},
    {"action": "extract", "selector": "div.quote", "multiple": true,
     "extract_name": "quotes",
     "fields": {"text": {"selector": "span.text"},
                "author": {"selector": "small.author"},
                "tags": {"selector": "div.tags a.tag", "multiple": true}}}
  ]
}
```

**Composite** actions chain other actions and declare prerequisites that
are injected **once per sequence** (a login runs a single time even if
several composed actions require it):

```json title="catalog/quotes-toscrape-com/login-and-list.json"
{
  "name": "login-and-list",
  "kind": "composite",
  "requires": ["login"],
  "compose": [{"action": "list-quotes", "params": {}}],
  "params": {"username": {"required": true, "default": "parrot"},
             "password": {"required": true, "default": "parrot"}}
}
```

Regenerate the sample catalog with `python examples/webbrowsing/seed_catalog.py`;
`examples/webbrowsing/local_demo.py` replays it offline (no LLM, no
network) and doubles as a smoke test.

## The structured contract (`execute_web_task`)

```json
{"site": "quotes", "action": "quotes-by-tag", "data": {"tag": "love"}}
```

Multi-step flows use `plan` instead of `action`:

```json
{"site": "quotes", "data": {"username": "parrot", "password": "parrot"},
 "plan": [{"action": "login"}, {"action": "top-tags"}]}
```

Failures come back **structured and repairable** instead of raising, so the
LLM self-corrects in one round-trip:

| `error.code` | Hint returned |
|---|---|
| `unknown_site` | `known_sites` (slug, title, aliases) |
| `unknown_action` | `available_actions` (name, description, params) |
| `missing_params` | `expected_params` per action + `provided_data` |
| `invalid_request` / `invalid_plan` | validation message |

`WebTaskRequest` is a Pydantic model, so it can also be used directly as a
structured-output schema.

### Toolkit tools

| Tool | Purpose |
|---|---|
| `execute_web_task` | The one-shot structured entry point described above. |
| `list_sites`, `list_site_actions`, `get_site_action` | Catalog discovery. |
| `run_site_action`, `run_site_sequence` | Run one action / an explicit sequence (gated by `confirm_runs`). |
| `register_site`, `save_site_action`, `delete_site_action` | Catalog authoring. `save_site_action` rejects literal credentials — use an `authenticate` step with `credential_provider` + a `credential_resolver` (CredentialBroker). |
| `close_browser` | End the persistent session. |

### `WebBrowsingToolkit` options

| Arg | Default | Notes |
|---|---|---|
| `catalog_dir` | `"browsing_catalog"` | Catalog root. |
| `driver_type` | — | `"playwright"` / `"selenium"`, fixed at construction. |
| `user_data_dir`, `profile_directory`, `browser_channel` | `None` | Real Chrome profile; `browser_channel="chrome"` launches system Chrome. |
| `session_based` | `True` | One browser instance across every run until `close_browser()`. |
| `headless` | `False` | Catalogued flows are visible by default. |
| `confirm_runs` | `True` | Marks `run_site_action` / `run_site_sequence` as HITL-confirmed tools. |
| `max_loop_iterations` | toolkit default | Hard cap on every `loop` step (save time + run time). |
| `credential_resolver`, `human_channel` | `None` | Credential broker and `await_human` channel. |

## Choosing between the two web agents

| | `WebNavigatorAgent` | `WebAgent` |
|---|---|---|
| Browser control | Playwright/Selenium launch Chrome | Attaches to a running Chrome via CDP |
| What the LLM does | Picks a catalogued action (deterministic replay) | Navigates freely with DevTools tools |
| Profile | `user_data_dir` + `profile_directory` in the constructor | `--user-data-dir` when starting Chrome |
| Extra deps | `playwright` or `selenium` | Node / `npx` (`chrome-devtools-mcp`) |
| Best for | Repeatable flows on known sites | Exploration, QA suites, debugging (console, network, screenshots) |

## See also

- `examples/agents/webbrowser/README.md` — runnable walkthrough (ES).
- `examples/webbrowsing/README.md` — catalog reference and offline demo.
- [WebAgent](web-agent.md)
- [Tools Reference](tools.md)
