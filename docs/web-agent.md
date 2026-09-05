# WebAgent — Browser Interaction via Chrome DevTools

## Overview

`WebAgent` (`parrot.bots.chrome`) is a general-purpose web-interaction agent
that drives a real Google Chrome instance through the **Chrome DevTools
Protocol (CDP)**. Instead of Selenium/Playwright, it mounts the
[`chrome-devtools-mcp`](https://github.com/ChromeDevTools/chrome-devtools-mcp)
MCP server, which exposes navigation, clicking, form filling, screenshots,
console logs, network monitoring and performance tracing as LLM-callable
tools.

Two ways of working:

- **Free-form interaction** — `await agent.ask("Open the pricing page and
  tell me the cheapest plan")`. The LLM decides which DevTools tools to
  call.
- **QA test execution** — `await agent.run_tests([...])` runs a list of
  `QATestCase` objects (natural-language steps + formal assertions) and
  returns a structured `QAReport` with a CI exit code and JUnit XML.

If you want deterministic, catalogued navigation on top of your own Chrome
profile instead, see [WebNavigatorAgent](web-navigator-agent.md).

## Architecture

```
WebAgent (BasicAgent)
   │  configure()
   ▼
add_chrome_devtools_mcp_server(browser_url=..., headless=..., ensure_running=True)
   │
   ├── ensure_chrome_running()  ── only when ensure_running=True and the host
   │      │                        is loopback (skipped with auto_connect=True)
   │      └── ChromeManager (parrot.mcp.chrome, async: aiohttp probe +
   │            asyncio subprocess) ── launches Chrome with
   │            --remote-debugging-port=<port> if nothing answers on it
   │
   └── MCP stdio client ──► npx -y chrome-devtools-mcp@latest --browser-url=http://127.0.0.1:9222 ...
                                   │
                                   └── CDP ──► Google Chrome
```

`ChromeConfig` (Pydantic) captures the subset of `chrome-devtools-mcp`
flags AI-Parrot needs and renders them with `to_mcp_args()`.

`create_chrome_devtools_mcp_server()` is a pure config builder — it never
starts a browser. Starting (or reusing) the managed local Chrome is the job
of the async `ensure_chrome_running()` helper, which the
`add_chrome_devtools_mcp_server()` hook awaits before connecting. Pass
`ensure_running=False` when you manage the browser yourself.

## Requirements

- **Google Chrome** (or Chromium) installed and on `PATH`
  (`google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`
  or the macOS app bundle are auto-detected).
- **Node.js / `npx`** — `chrome-devtools-mcp` is fetched on first run.
- An LLM provider key in the environment.

## Quick start

```python
import asyncio
from parrot.bots.chrome import WebAgent, ChromeConfig

async def main():
    agent = WebAgent(
        chrome_config=ChromeConfig(headless=False, viewport="1920x1080"),
        llm="google:gemini-2.5-flash",
    )
    await agent.configure()   # awaits Chrome startup (if needed) + the MCP server
    result = await agent.ask(
        "Go to https://quotes.toscrape.com, open the 'love' tag and list the authors"
    )
    print(result.response)

asyncio.run(main())
```

## `ChromeConfig` reference

| Field | Default | Description |
|---|---|---|
| `browser_url` | `None` → `http://127.0.0.1:<port>` | Debugging endpoint of an already-running Chrome. |
| `port` | `9222` | Remote-debugging port used when `browser_url` is not set. |
| `headless` | `False` | Launch Chrome without a window. Sessions are **visible by default**. |
| `user_data_dir` | `None` | Chrome user-data directory to reuse (cookies, logins, extensions). |
| `channel` | `None` | `stable` / `beta` / `dev` / `canary`. |
| `viewport` | `None` | Initial viewport, e.g. `"1920x1080"`. |
| `executable_path` | `None` | Explicit Chrome binary. |
| `isolated` | `False` | Temporary user-data-dir, cleaned up on close. |
| `no_usage_statistics` | `True` | Opt out of `chrome-devtools-mcp` telemetry. |
| `auto_connect` | `False` | Let `chrome-devtools-mcp` discover a running local Chrome (Chrome ≥ 144). Skips `ensure_chrome_running()` / `ChromeManager`. |

`WebAgent` itself also accepts `default_timeout_ms` (per-test timeout for
`run_tests`, default 60 s) and `screenshot_dir` (where failure screenshots
are saved).

## Attaching to your own Chrome (remote debugging)

By default `ensure_chrome_running()` has `ChromeManager` launch a
**profile-less** Chrome when nothing answers on the debugging port (the
probe and the launch are fully async, so `configure()` never blocks the
event loop while Chrome comes up). To reuse your sessions, extensions and saved
logins, start Chrome yourself with the debugging port open and a dedicated
user-data directory, then point `WebAgent` at it.

!!! warning "Chrome ≥ 136 requires an explicit `--user-data-dir`"
    Chrome refuses `--remote-debugging-port` on the default profile. Use a
    dedicated directory — a copy of your real profile works well (see
    [copying the profile](web-navigator-agent.md#copying-your-chrome-profile)).

=== "Linux"

    ```bash
    google-chrome \
      --remote-debugging-port=9222 \
      --user-data-dir="$HOME/.config/chrome-debug" \
      --profile-directory=Default \
      --remote-allow-origins='*' &
    ```

=== "macOS"

    ```bash
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --remote-debugging-port=9222 \
      --user-data-dir="$HOME/chrome-debug" &
    ```

=== "Windows (PowerShell)"

    ```powershell
    & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
      --remote-debugging-port=9222 `
      --user-data-dir="$env:LOCALAPPDATA\chrome-debug"
    ```

Verify the endpoint, then connect:

```bash
curl -s http://127.0.0.1:9222/json/version
```

```python
agent = WebAgent(
    chrome_config=ChromeConfig(browser_url="http://127.0.0.1:9222"),
    llm="anthropic:claude-sonnet-5",
)
```

Any bot can gain the same capability without subclassing `WebAgent`:

```python
await bot.add_chrome_devtools_mcp_server(browser_url="http://127.0.0.1:9222")

# Browser managed elsewhere (container, CI, a remote host): skip the launch
await bot.add_chrome_devtools_mcp_server(
    browser_url="http://127.0.0.1:9222", ensure_running=False
)
```

## QA test execution

`run_tests()` executes each `QATestCase` in its own `ask()` call so that
per-test retries and timeouts apply, and a single LLM/MCP/network error
never aborts the suite.

```python
from parrot.bots.chrome import QATestCase, QAAssertion

cases = [
    QATestCase(
        name="homepage-smoke",
        url="http://localhost:3000",
        steps=["Wait for the page to fully load"],
        expected="Page loads without errors",
        assertions=[
            QAAssertion(check="no_console_errors"),
            QAAssertion(check="no_network_failures"),
            QAAssertion(check="response_status", target="200"),
        ],
        tags=["smoke"],
        max_retries=1,
        timeout_ms=30_000,
    ),
    QATestCase(
        name="login-validation",
        url="http://localhost:3000/login",
        steps=[
            "Leave the email field empty",
            "Type '123' in the password field",
            "Click the submit/login button",
        ],
        expected="Validation errors appear for required fields",
        assertions=[
            QAAssertion(check="url_matches", target="/login"),
            QAAssertion(check="element_visible", target=".error-message",
                        wait_timeout_ms=3000),
        ],
        tags=["regression"],
    ),
]

msg = await agent.run_tests(cases, tags=["smoke"])
report = msg.output            # QAReport
print(msg.response)            # "1/2 passed"
open("results.xml", "w").write(report.to_junit_xml())
raise SystemExit(report.exit_code)
```

### Assertion types

| `check` | `target` / `value` | Meaning |
|---|---|---|
| `element_visible` / `element_not_visible` | CSS selector | Waits up to `wait_timeout_ms` (default 5000). |
| `text_contains` | text | Page contains the text. |
| `url_matches` | pattern | Current URL matches. |
| `no_console_errors` | — | No JS errors in the console. |
| `no_network_failures` | — | No 4xx/5xx requests. |
| `response_status` | status code | Main document status. |
| `performance` | threshold | Performance metrics against thresholds. |
| `accessibility_check` | — | ARIA roles, `alt` text, heading hierarchy. |
| `screenshot_diff` | — | Placeholder — not implemented yet. |

### `QAReport`

`summary`, `url`, `findings: list[QAFinding]`, `total/passed/failed/errors/skipped`,
`duration_ms`, plus:

- `exit_code` → `0` when `failed + errors == 0`, else `1`.
- `to_junit_xml(suite_name)` → JUnit XML for CircleCI, GitHub Actions,
  GitLab CI and Jenkins.

Each `QAFinding` carries `status` (`pass|fail|error|skip`), `detail`,
`screenshot_path`, `console_errors`, `duration_ms` and `retries`.

## CLI runner (CI/CD)

`parrot.bots.chrome_runner` runs a JSON test file without writing Python:

```bash
python -m parrot.bots.chrome_runner \
    --test-file examples/qa-tests-sample.json \
    --url http://localhost:3000 \
    --headless --tags smoke \
    --junit-output qa-results/results.xml \
    --screenshot-dir qa-screenshots/ \
    --default-timeout 60000 --port 9222 --viewport 1920x1080
```

The process exits with `QAReport.exit_code`, so it works directly as a
deploy-or-block gate. See `examples/chrome_ci_test.py` for a CircleCI
snippet, and `examples/qa-tests-sample.json` for the file format
(one `QATestCase` per array element).

## Examples

| File | What it shows |
|---|---|
| `examples/chrome_qa_test.py` | Interactive QA run against a site. |
| `examples/chrome_ci_test.py` | Headless CI pipeline: tags, retries, JUnit, screenshots, exit code. |
| `examples/chrome_performance_test.py` | Performance assertions. |
| `examples/qa-tests-sample.json` | Test file for the CLI runner. |

## See also

- [WebNavigatorAgent](web-navigator-agent.md) — catalogued, deterministic
  navigation with `WebBrowsingToolkit` on a real Chrome profile.
- [Design note — WebAgent Chrome DevTools MCP](superpowers/specs/2026-08-04-web-agent-chrome-devtools-design.md)
- [MCP Sessions](mcp_session.md)
