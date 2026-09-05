# Supervised Obscura Browser Integration

> **Feature**: FEAT-530 — Supervised Obscura Browser Integration
> **Spec**: [sdd/specs/obscura-new-browser-headless.spec.md](../sdd/specs/obscura-new-browser-headless.spec.md)
> **Packages**: `ai-parrot-server` (`parrot.mcp.obscura`, `parrot.mcp.cli`), `ai-parrot` (`parrot.mcp.integration`, `parrot.bots.chrome`), `ai-parrot-tools` (`parrot_tools.scraping.drivers.playwright_{config,driver}`, `parrot_tools.scraping.driver_factory`)

Obscura is a Linux headless browser engine with a Chrome DevTools
Protocol (CDP) server and a native Model Context Protocol (MCP) server.
This feature lets AI-Parrot's existing Playwright driver connect to a
supervised Obscura process over CDP, and lets AI-Parrot agents / Codex
use Obscura's native MCP tools directly — without replacing the existing
Chrome DevTools MCP or Selenium/ChromeDriver paths.

---

## Prerequisites

- **Linux only.** No non-Linux Obscura binary is supported by this
  feature. Nothing here silently falls back to launching Chrome or
  Selenium when Obscura is selected — a missing/misconfigured Obscura
  binary is reported as an actionable error instead.
- **Obscura `v0.2.2`**, pinned. Compatibility below is measured against
  the current `PlaywrightDriver` contract, not assumed from CDP protocol
  naming — Obscura's renderer is independently developed.
- The `obscura` binary must be reachable either on `PATH` or via an
  explicit path (`--binary` CLI flag / `binary_path=` in Python).

No native PyO3 bindings or Rust library embedding are introduced by this
feature — see [§ Scope Boundaries](#scope-boundaries).

---

## 1. Supervised CDP mode (Playwright driver)

### Python

```python
from parrot_tools.scraping.driver_factory import DriverFactory

driver = DriverFactory.create({
    "driver_type": "obscura",
    "obscura_binary": "/usr/local/bin/obscura",   # or resolvable on PATH
    "obscura_port": 9222,
    "obscura_stealth": False,
    "obscura_allow_private_network": False,        # required for local fixtures only
})
await driver.start()   # connects via chromium.connect_over_cdp()
...
await driver.quit()    # disconnects only — does not kill the Obscura process
```

`driver_type="obscura"` always connects over Chromium CDP (`browser`/
`browser_type` is ignored — Obscura speaks CDP as a Chromium-compatible
engine, enforced both by `DriverFactory`/`DriverRegistry` and by
`PlaywrightConfig` itself) and never falls back to Chrome/Chromium/
Selenium. Every `AbstractDriver` method (`navigate`, `click`, `fill`,
`screenshot`, `evaluate`, …) works identically regardless of engine —
no Obscura-specific branching exists anywhere above `PlaywrightDriver`.
`quit()` only closes a context it created itself — a *reused* CDP
default context/page (the common case when connecting to an existing
supervised process) is left open, since closing it could tear down
state other clients of that process still depend on.

`PlaywrightConfig` carries the underlying settings directly:

| Field | Default | Purpose |
|---|---|---|
| `engine` | `"playwright"` | `"obscura"` selects connect-over-CDP mode. |
| `cdp_endpoint_url` | `None` | Explicit CDP endpoint; derived from `obscura_port` on `127.0.0.1` when unset. |
| `obscura_binary` | `None` | Carried through for CLI/process-manager use — not used by the driver itself. |
| `obscura_port` | `9222` | CDP port. |
| `obscura_stealth` | `False` | Obscura stealth mode. |
| `obscura_allow_private_network` | `False` | Required for local fixture pages; never enable by default in general deployments. |

### CLI lifecycle (`parrot mcp obscura ...`)

```bash
# Start (or adopt, with --attach-only) the supervised Obscura process
parrot mcp obscura start --binary /usr/local/bin/obscura --port 9222

# Inspect the CDP endpoint (never spawns a process)
parrot mcp obscura status --port 9222

# Stop a previously started process
parrot mcp obscura stop --port 9222
```

`start` delegates to `parrot.mcp.obscura.ObscuraProcessManager` — it
waits for a responsive CDP endpoint and reports an actionable error
(binary not found, readiness timeout, or the spawned process exiting
early — with its captured stderr) rather than hanging or silently
falling back. It also refuses to silently adopt a *foreign* CDP endpoint
already listening on the configured port (e.g. Chrome DevTools sharing
the same conventional `9222`) — ownership must be explicit via
`--attach-only`. Because each CLI invocation is a separate OS process,
`start` records the spawned PID to a small file
(`{tempdir}/obscura-{port}.pid`) that `stop` reads back — this PID-file
adapter is CLI-only bookkeeping; `ObscuraProcessManager` itself only
tracks ownership in-process (for embedded/long-lived callers such as an
agent process holding one manager for its own lifetime). Before
signaling, `stop` sanity-checks the PID's `/proc/{pid}/cmdline` actually
looks like an Obscura process (defends a stale or PID-reused file
against terminating an unrelated process), then sends `SIGTERM`,
escalating to `SIGKILL` if the process is still alive after 5 seconds —
mirroring `ObscuraProcessManager.stop()`'s own terminate-then-kill
policy.

`--attach-only` adopts an already-running endpoint without spawning
anything, and `stop` will never terminate a process it did not start.

---

## 2. Native Obscura MCP (agent / Codex tools)

Obscura's own `obscura mcp` stdio server exposes its native browser tool
schema — a separate capability from Chrome DevTools MCP
(`create_chrome_devtools_mcp_server`), added alongside it, never instead
of it.

```bash
# Print the stdio command/args JSON for any MCP host (Codex, Claude Code, ...)
parrot mcp obscura mcp-config --binary /usr/local/bin/obscura --port 9222
```

### Python (any `MCPEnabledMixin`-based agent)

```python
tools = await agent.add_obscura_mcp_server(
    binary_path="/usr/local/bin/obscura",
    port=9222,
    stealth=False,
    allow_private_network=False,
)
```

### `WebAgent` (opt-in, alongside Chrome DevTools MCP)

```python
from parrot.bots.chrome import ObscuraMCPConfig, WebAgent

agent = WebAgent(
    name="web-agent",
    obscura_config=ObscuraMCPConfig(binary_path="/usr/local/bin/obscura"),
)
```

When `obscura_config` is set, `WebAgent.configure()` registers Obscura's
native MCP tools **in addition to** the existing, unconditional Chrome
DevTools MCP registration — Chrome DevTools MCP defaults are unaffected
whether or not Obscura is configured.

Unlike Chrome DevTools MCP (which attaches to a *separately* launched
Chrome via `--browser-url`), Obscura's native MCP mode is self-contained:
the `obscura mcp` subprocess manages its own browser engine directly and
is spawned/supervised by the MCP transport layer itself
(`StdioMCPSession`), not by AI-Parrot — so no `ensure_running`-style
pre-start step exists for it.

---

## 3. Compatibility matrix

Status legend:

- ✅ **pass** — verified against a real, headless-launched Chromium via
  `PlaywrightDriver` (the same driver class Obscura CDP mode uses).
  Obscura speaks CDP through the identical `PlaywrightDriver` code path
  (`chromium.connect_over_cdp()`), so these are expected to hold, but the
  opt-in real-Obscura fixture (below) is what actually re-verifies each
  one against a real binary — run it before enabling Obscura broadly.
- ⚠️ **known-existing-gap** — a real, already-verified incompatibility in
  `PlaywrightDriver`/`session_actions.py` itself (not introduced by, or
  specific to, Obscura — the same gap exists for ordinary launched
  Chromium too). Not fixed by this feature; see the linked test.
- ➖ **not-a-browser-action** — architecturally out of scope for any
  browser backend.

### `AbstractDriver` core surface

| Method | Status | Evidence |
|---|---|---|
| `start` / `quit` | ✅ pass | `test_playwright_driver.py::TestObscuraCDPMode`, `test_driver_integration.py::TestFactoryLifecycleObscura` |
| `navigate` / `go_back` / `go_forward` / `reload` | ✅ pass | `test_playwright_driver.py::TestObscuraModeSharesAbstractDriverSurface` |
| `click` / `fill` / `select_option` / `hover` / `press_key` | ✅ pass | same |
| `get_page_source` / `get_text` / `get_attribute` / `get_all_texts` | ✅ pass | same |
| `screenshot` | ✅ pass | same; opt-in real check: `test_fixture_site_integration.py::TestObscuraPlaywrightFixtureSite` |
| `wait_for_selector` / `wait_for_navigation` / `wait_for_load_state` | ✅ pass | inherited, no Obscura-specific branching |
| `execute_script` / `evaluate` | ✅ pass | `TestObscuraModeSharesAbstractDriverSurface::test_evaluate_delegates_to_page` |
| `current_url` | ✅ pass | `TestDriverSwapTransparency` (parametrized incl. `"obscura"`) |

### Playwright-exclusive extended surface

| Method | Status | Evidence |
|---|---|---|
| `intercept_requests` / `intercept_by_resource_type` / `mock_route` | ✅ pass | inherited, unmodified by Obscura mode |
| `record_har` | ✅ pass (config-time only) | `PlaywrightConfig.record_har_path` |
| `save_pdf` | ✅ pass (chromium only) | Obscura mode forces `browser_type="chromium"` |
| `start_tracing` / `stop_tracing` | ✅ pass | inherited |
| `save_storage_state` | ✅ pass | inherited |
| `new_page` | ✅ pass | inherited |
| `get_network_responses` | ✅ pass | inherited |

### Scraping-plan / browsing-catalog actions (`session_actions.py`)

These known gaps were discovered by FEAT-455's real-Chromium regression
suite (`test_fixture_site_integration.py`) and are **not** Obscura-specific
— they are JS-syntax incompatibilities between Selenium-style scripts and
Playwright's `page.evaluate()`, independent of which browser CDP connects
to:

| Action | Status | Evidence |
|---|---|---|
| `navigate` / `authenticate` / `set_cookies` | ✅ pass | `TestAuthenticatedFlowEndToEnd`, `TestStubRegressionFullPlan` |
| `get_cookies` | ⚠️ known-existing-gap | `TestSeleniumStyleScriptIncompatibilityWithPlaywright::test_get_cookies_returns_empty_due_to_bare_return` — bare `return` statement, illegal in `page.evaluate()` |
| `await_human` (`condition_type="selector"`) | ⚠️ known-existing-gap | same class — bare `return` + Selenium `arguments[0]` convention |
| `await_browser_event` | ⚠️ known-existing-gap | same class — bare `return` in polling script |
| `upload_file` | ⚠️ known-existing-gap | `TestUploadFileKnownLimitation` — Playwright rejects `.fill()` on file inputs |
| `wait_for_download` | ⚠️ known-existing-gap | `TestWaitForDownloadKnownLimitation` — no download-handling wiring in `PlaywrightDriver` |
| `await_keypress` | ➖ not-a-browser-action | `TestAwaitKeypressIsNotABrowserAction` — reads OS stdin, no driver involved |

### Native MCP

| Capability | Status | Evidence |
|---|---|---|
| stdio command/argument construction | ✅ pass | `tests/mcp/test_obscura_mcp.py::TestCreateObscuraMCPServer` |
| initialize / tools-list / tools-call over stdio | ✅ pass (mocked transport) | `tests/mcp/test_obscura_mcp.py::test_obscura_native_mcp_stdio_call_tool_interop` |
| `WebAgent` opt-in registration alongside Chrome DevTools MCP | ✅ pass | `tests/mcp/test_obscura_mcp.py::TestObscuraWebAgentConfiguration` |

### Opt-in real-binary verification

`packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`
adds three opt-in tests requiring a real Linux Obscura `v0.2.2` binary
(`OBSCURA_BINARY` env var, or `obscura` resolvable on `PATH`) — they
**skip cleanly** without one, never fail the suite:

- `TestObscuraPlaywrightFixtureSite::test_obscura_playwright_fixture_site`
  — navigation, DOM, waits, script (`evaluate`), screenshot, and cookie
  checks against the deterministic local fixture site.
- `TestObscuraScrapingPlanDriverParity::test_obscura_scraping_plan_driver_parity`
  — the same authenticated scraping plan `TestAuthenticatedFlowEndToEnd`
  runs against real Chromium, run through the Obscura-backed driver.
- `TestObscuraBrowsingToolkitCatalogFlow::test_obscura_browsing_toolkit_catalog_flow`
  — a catalogued `WebBrowsingToolkit` login flow against the
  Obscura-backed driver (injected directly via `_session_driver`, the
  same pattern `test_toolkit.py::test_start_creates_session_driver`
  already uses for Selenium).

**Run these before enabling Obscura for any real workload** — every ✅
above is measured against launched Chromium and a mocked CDP transport;
these are what actually exercises a real Obscura process end to end.

### Resolved: driver selection now covers every entry point

An earlier draft of this feature left `WebScrapingTool`/
`WebScrapingToolkit`/`WebBrowsingToolkit` unable to select Obscura end to
end — code review caught this before merge (`DriverConfig.driver_type`
rejected `"obscura"` outright via its pydantic `Literal`, `DriverRegistry`
had no `"obscura"` entry, and `WebScrapingTool.initialize_driver()`
raised `ValueError` right after successfully starting the connection).
All three are now fixed:

- `DriverConfig.driver_type: Literal["selenium", "playwright", "obscura"]`,
  with `cdp_endpoint_url`/`obscura_binary`/`obscura_port`/
  `obscura_stealth`/`obscura_allow_private_network` fields forwarded from
  `WebScrapingToolkit.__init__`.
- `DriverRegistry.register("obscura", _create_obscura_setup)` — the
  session-based path (`WebScrapingToolkit`/`WebBrowsingToolkit`'s
  `start()`) now resolves an Obscura-backed `PlaywrightDriver` exactly
  like the existing Selenium/Playwright entries.
- `WebScrapingTool.initialize_driver()` extracts Playwright handles for
  `"obscura"` the same way it does for `"playwright"` (same underlying
  driver class).

See `packages/ai-parrot-tools/tests/scraping/test_driver_context.py`,
`test_toolkit.py::test_start_creates_obscura_session_driver`, and
`test_tool_driver_integration.py::TestWebScrapingToolObscuraDriver` /
`test_initialize_obscura_extracts_handles`.

---

## Scope Boundaries

- No native PyO3 bindings or Rust library embedding — deferred until the
  supervised Playwright/CDP path has been battle-tested (see spec § 8).
- Selenium/ChromeDriver is unchanged and unaffected.
- Obscura's native MCP tools are not reimplemented inside AI-Parrot —
  `create_obscura_mcp_server()` only builds the stdio command that spawns
  Obscura's own `obscura mcp` binary.
- Non-Linux Obscura binaries are out of scope for this release.
