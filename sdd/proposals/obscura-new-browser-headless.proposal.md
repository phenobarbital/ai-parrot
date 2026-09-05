---
id: FEAT-528
title: Evaluate Obscura as a CDP-backed browser engine and optional MCP server for ai-parrot
slug: obscura-new-browser-headless
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-05
  summary_oneline: Evaluate Obscura as a CDP-backed browser engine and optional MCP server for ai-parrot
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-528/
created: 2026-09-05
updated: 2026-09-05
revision: 2
---

# FEAT-528 — Evaluate Obscura as a CDP-backed browser engine and optional MCP server for ai-parrot

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-528/`](../state/FEAT-528/)
> **Revision 2 (2026-09-05)**: review pass corrected the upstream source
> citations (F007/F008), added the `DriverConfig`/`DriverRegistry` seam,
> the Chrome DevTools MCP process-ownership trap, the remote/containerized
> discovery limitation, the Selenium `debugger_address` experiment, and
> pinned the upstream minimum to **v0.2.2 (render build)**. It also folds in
> the Q&A decisions recorded in `synthesis.json` (commit `e4771cb80`) that the
> original document never absorbed: Linux-only, ai-parrot-supervised process
> with CLI start/stop, native Obscura MCP **required** for Codex/agents, and
> PyO3 deferred.

---

## 0. Origin

The original request is preserved in `sdd/state/FEAT-528/source.md`.

> $sdd-proposal obscura-new-browser-headless -- Current ScrapingToolkit+WebBrowsingToolkits are using or own driver for Selenium+Playright or Chrome Dev Tools MCP, there is a new headless browser engine written in Rust called Obscura: https://github.com/h4ckf0r0day/obscura, `Obscura` is compatible with Chrome DevTools protocol, and is a drop-in replacement to work with Puppeterr+Playright, documentation: `https://docs.obscura.sh/` the idea is providing to our Playwright driver the ability to connect Obscura: https://docs.obscura.sh/quickstart/connect-puppeteer-or-playwright to interact with the headless browser provided by Obscura, Obscura exposes an API Surface to be used as a Rust Library and the idea is because ai-parrot have PyO3 support (there are several crates installed into ai-parrot codebase) think if we can use Obscura as a direct replacement of Chrome DevTools in some existing toolkits and added as an MCP server to a ai-parrot agent or a Codex session.

**Initial signals**: additive verbs; named entities include Obscura, Playwright, Selenium, Chrome DevTools MCP, PyO3, and Codex; no acceptance criteria were provided.

## 1. Synthesis Summary

The request is feasible through a staged, process-level integration. `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` can gain a connect-over-CDP mode configured through `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`, selected through the **three** driver-selection seams (`DriverConfig` → `DriverRegistry` / `DriverFactory`), while preserving `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`. The existing `packages/ai-parrot/src/parrot/mcp/integration.py` and `packages/ai-parrot/src/parrot/bots/chrome.py` can be reused with an Obscura CDP endpoint **once browser-process ownership is made explicit** — today the factory silently launches Google Chrome on the configured port when nothing answers there, and the remote-discovery path (`/json/version`) hardcodes a loopback WebSocket URL upstream, so Obscura mode must connect by WebSocket endpoint rather than HTTP discovery. Obscura's native MCP server is **required** (user decision, Q&A U3) for Codex and agent UI-management use cases and is exposed as a first-class supervised capability alongside the CDP path; it creates a second browser tool and session contract that needs its own parity tests. Selenium remains ChromeDriver-based; the reviewed Obscura surface documents CDP and Playwright/Puppeteer, not W3C WebDriver, but `SeleniumSetup` already exposes a `debugger_address` attach option, so the "does ChromeDriver accept an Obscura endpoint" question is a cheap experiment in the compatibility matrix rather than a separate proposal. Native PyO3 embedding is **deferred** (Q&A U5) until the Playwright/CDP integration is battle-tested, because the upstream `Browser`/`Page` API pulls V8 through workspace path crates that build it from source and introduces Tokio, a single shared V8 isolate, and packaging constraints.

**Upstream target is v0.2.2 (released 2026-09-05), Linux, `render` build (Q&A U1).** ai-parrot supervises `obscura serve` and exposes CLI commands to start and stop it (Q&A U2). The v0.2.2 notes are the first to state that Playwright form filling and context setup complete end to end; earlier releases must not be accepted. The `-no-render` archive variants drop screenshots and PDF, which the `AbstractDriver` contract requires.

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|---|---|---|---|---|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | `AbstractDriver` | 11-180 | Shared async browser contract | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | `PlaywrightDriver.start` | 41-93 | Current Playwright launch and lifecycle (launch / `launch_persistent_context` only) | F001, F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py` | `PlaywrightConfig` | 12-73 | Browser launch and context configuration | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | `DriverFactory.create` | 43-92 | Direct driver selection seam; builds `PlaywrightConfig` at line 92 | F001, F002 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` | `DriverConfig` | 15-60 | Pydantic driver config; `driver_type: Literal["selenium", "playwright"]` (line 44) and `browser: Literal[...]` (45-47) are **closed** | F002 (rev. 2) |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py` | `DriverRegistry.register` / `.get` | 36-60, 188 | Toolkit session-mode selection seam (`WebScrapingToolkit` line 345 calls `DriverRegistry.get(config.driver_type)`); builds `PlaywrightConfig` at line 188 | F002 (rev. 2) |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/scraping/driver.py` | `SeleniumSetup.debugger_address` | 68, 108, 184-187 | Existing Selenium attach-to-remote-debugger seam (`options.debugger_address`) | F009 (rev. 2) |
| 8 | `packages/ai-parrot/src/parrot/mcp/integration.py` | `create_chrome_devtools_mcp_server` | 1105-1192 | External browser MCP configuration; lines 1158-1166 call `ChromeManager.start()` for any local URL; only `--browser-url` is emitted (line 1168) | F003 |
| 9 | `packages/ai-parrot/src/parrot/bots/chrome.py` | `ChromeConfig`, `WebAgent.configure` | 15-45, 290-334 | Agent wiring for browser MCP | F003 |
| 10 | `packages/ai-parrot-server/src/parrot/mcp/chrome.py` | `ChromeManager` | 9-131 | Managed local browser lifecycle; synchronous, uses `requests` (line 6, 29-31) and `time.sleep` (line 110), launches `google-chrome` when the port is silent (74-106) | F003 |
| 11 | `docs/mcp-local-toolkits.md` | `mcp-toolkits.yaml` schema | 45-115 | Local MCP exposure and environment configuration | F004 |
| 12 | `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | `_install_mcp` | 112-170 | Existing writer of `[mcp_servers.parrot-<name>]` tables into `.codex/config.toml` | F004 (rev. 2) |
| 13 | `packages/navrules/pyproject.toml`, `packages/navrules/rust/Cargo.toml` | `tool.maturin`, `navrules_native` | 1-4, 40-44; 8-23 | PyO3/Maturin packaging precedent | F004 |
| 14 | `packages/ai-parrot/src/parrot/yaml-rs/Cargo.toml`, `packages/ai-parrot/src/parrot/codec-rs/Cargo.toml` | core Rust crates | — | Additional in-core Rust extension precedent | F004 (rev. 2) |
| 15 | `https://github.com/h4ckf0r0day/obscura` (README, v0.2.2) | CDP, Playwright, and MCP surfaces | README sections | Upstream process-level integration surface | F005, F007 |
| 16 | `crates/obscura/Cargo.toml` @ `v0.2.2` | `obscura` crate manifest | 3, 10-14, 16-24 | Version `0.1.0`; features `api`/`stealth`/`render`; **path** deps on `obscura-browser`/`obscura-net`, optional `tokio` — no V8 or git dependency in this manifest | F008 |
| 17 | `crates/obscura/src/lib.rs` @ `v0.2.2` | public re-exports | 24-32 | `Browser`, `BrowserConfig`, `Cookie`, `CookieStore`, `Error`, `Page`, interception and request/response callback types | F008 |
| 18 | `crates/obscura-mcp/src/lib.rs` @ `v0.2.2` | `dispatch`, `run`, `handle_tools_list`, tool dispatch | 223-228, 235-238, 314-720, 742-759 | Newline-delimited JSON-RPC over stdin; 37 `browser_*` tools | F007 |
| 19 | `crates/obscura-cdp/src/server.rs` @ `v0.2.2` | HTTP control plane | 86, 177, 208, 736-740, 786-800 | Serves `/json/version`, `/json/list`, `/json/protocol`; default bind `127.0.0.1`; **`webSocketDebuggerUrl` is hardcoded to `ws://127.0.0.1:<port>/…`** (791, 800); reports `Chrome/145.0.0.0` | F005, F007 (rev. 2) |
| 20 | `https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md` | `--browser-url`, `--ws-endpoint` | option table | `--ws-endpoint` is the documented alternative to HTTP discovery | F003 (rev. 2) |
| 21 | `https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_chromium/selenium.webdriver.chromium.options.html` | `ChromiumOptions.debugger_address` | API reference | Selenium remote DevTools capability | F009 |

### 2.2 Constraints Discovered

- The first adapter must preserve `AbstractDriver`; existing scraping actions should not need a new browser-specific contract. *Evidence*: F001, F002.
- **Engine selection has three seams, not one.** `DriverConfig.driver_type` / `.browser` are closed `Literal`s consumed by both `DriverRegistry` (toolkit session mode) and `DriverFactory` (direct use). An `"obscura"` choice must land in all three or the browsing toolkit and the `.parrot/mcp-toolkits.yaml` path cannot select it. *Evidence*: F002.
- **Connect mode invalidates launch-only fields.** `browser_type` must be `chromium`; `channel`, `user_data_dir` (persistent context), `proxy`, `slow_mo`, `record_video_dir`, and `storage_state` are launch-time or unsupported upstream (video, tracing and storage-state save/restore are documented as not implemented; use `obscura serve --storage-dir`). `PlaywrightConfig` must reject or ignore them explicitly in connect mode. *Evidence*: F002, F005.
- **CDP attachment and browser-process ownership are separate concerns, and the current factory conflates them.** `create_chrome_devtools_mcp_server` calls `ChromeManager.start()` for every local URL unless `auto_connect` is set; when nothing answers on the port it launches `google-chrome` there. With Obscura configured but not yet running, the agent would silently get Chrome. The Obscura process must be either externally managed, supervised by an explicit manager, or containerized — never implicitly replaced. *Evidence*: F003.
- **Obscura does serve the HTTP control plane, so local discovery works.** `/json/version` and `/json/list` are implemented (server.rs 736-800), so `ChromeManager.is_chrome_running()` and `chrome-devtools-mcp --browser-url` succeed against a local `obscura serve`. *Evidence*: F005, F007.
- **Remote or containerized Obscura cannot be reached through HTTP discovery.** `/json/version` advertises `ws://127.0.0.1:<port>/devtools/browser` regardless of `--host`, so any HTTP-discovery client (the `--browser-url` flag, Puppeteer `browserURL`) will dial loopback. Obscura mode must connect by WebSocket endpoint: Python Playwright `connect_over_cdp("ws://…")` and `chrome-devtools-mcp --ws-endpoint`. The factory currently emits only `--browser-url`. *Evidence*: F003, F007.
- Direct Obscura MCP can be launched as an external stdio server, but its `browser_*` tools and state semantics require their own parity and lifecycle tests. *Evidence*: F003, F007.
- Selenium's CDP commands operate through an established WebDriver/ChromeDriver session. `SeleniumSetup(debugger_address=…)` already exists, so whether ChromeDriver accepts Obscura's endpoint is a one-config experiment; a WebDriver bridge is only needed if that experiment fails. *Evidence*: F009.
- PyO3 precedent (navrules, plus the in-core `yaml-rs` and `codec-rs` crates) does not remove the cost of embedding V8. A native spike must measure build time, artifact size, platform coverage, event-loop ownership, and V8 concurrency behaviour (pages share one V8 isolate upstream). *Evidence*: F004, F008.
- Obscura's renderer is independent and evolving; CSS, Web API, service workers, media, compositor, and font behaviour can differ from Chromium. PDFs are raster-backed (not searchable). *Evidence*: F005.
- Private-network fetches are blocked by default (`--allow-private-network` / `OBSCURA_ALLOW_PRIVATE_NETWORK=1`); every local test fixture needs it. *Evidence*: F005.
- **Release matrix (v0.2.2)**: Linux x86_64/aarch64 and macOS aarch64 archives in four variants (`render`, `render-stealth`, `no-render`, `no-render-stealth`); glibc 2.35+ on Linux; Docker image on `distroless/cc`; Windows is **absent** from the v0.2.2 artifact list. *Evidence*: F005.
- `ChromeManager` uses the synchronous `requests` library and `time.sleep`, which violates the project's aiohttp/async-only rules. An Obscura process manager must not copy that pattern. *Evidence*: F003.

### 2.3 Recent History (Relevant)

Recent history includes local toolkit MCP support and scraping model/driver changes. Existing tests cover Playwright driver/configuration, scraping driver discovery, local MCP toolkit configuration, and `WebAgent` (`packages/ai-parrot/tests/bots/test_chrome.py`). No repository history or source entry establishes an existing Obscura integration or an Obscura binary in CI. *Evidence*: F006.

## 3. Probable Scope

### What's New

- Obscura CDP endpoint configuration and lifecycle support for the Playwright-backed scraping/browsing path, selectable through `DriverConfig`, `DriverRegistry` and `DriverFactory`.
- An explicit, async browser-process manager (aiohttp probe + `asyncio` subprocess) that supervises `obscura serve` (default) and `obscura mcp`, plus CLI commands to start/stop/status the supervised process. An externally managed `ws://` endpoint remains a supported configuration; Obscura mode never falls back to launching Chrome.
- `--ws-endpoint` support in the Chrome DevTools MCP factory and `ChromeConfig`, used by Obscura mode unconditionally.
- A **required** native Obscura MCP server integration: `create_obscura_mcp_server()` (`MCPServerConfig`, stdio, supervised), an `add_obscura_mcp_server()` bot hook, and Codex registration via the existing `.codex/config.toml` installer.
- A compatibility test matrix whose acceptance bar is **the feature surface the Playwright driver already supports** (Q&A U4), plus the `no-render`/`render` distinction and the Selenium `debugger_address` experiment.
- (Deferred) A PyO3 feasibility spike for the upstream `obscura` Rust crate — follow-up work, not part of this feature.

### What Changes

- `PlaywrightConfig` and `PlaywrightDriver.start` gain an explicit connect-over-CDP mode (`cdp_endpoint: ws://…`) while retaining launch mode; launch-only fields are rejected in connect mode. *Evidence*: F002, F005.
- `DriverConfig.driver_type` gains `"obscura"` (or an `engine` field), threaded through `DriverRegistry` and `DriverFactory` without changing `AbstractDriver` callers. *Evidence*: F002.
- `create_chrome_devtools_mcp_server` / `ChromeConfig` gain `ws_endpoint`, and process ownership becomes explicit: the factory never launches a browser unless asked to. *Evidence*: F003, F007.
- Native Obscura MCP registration uses the existing external stdio MCP configuration pattern and the Codex installer, and validates tool/session parity against the 37 `browser_*` tools. *Evidence*: F003, F004, F007.
- Selenium remains backed by ChromeDriver in the first milestone. The compatibility matrix includes the `SeleniumSetup(debugger_address="127.0.0.1:9222")` experiment against `obscura serve` v0.2.2; its result decides whether a WebDriver bridge proposal is ever needed. *Evidence*: F009.

### What's Untouched (Non-Goals)

- Replacing Selenium's Chrome backend in the first milestone.
- Making Obscura the default browser engine before compatibility tests pass.
- Embedding the full Obscura engine into Python as part of the CDP integration.
- Reimplementing Obscura's MCP tool schema inside ai-parrot.
- Supporting Obscura releases older than v0.2.2, `no-render` builds, or non-Linux hosts in the first milestone.
- Native PyO3 embedding (deferred to follow-up work).

### Patterns to Follow

- Reuse the async `AbstractDriver` lifecycle and lazy dependency behaviour. *Evidence*: F001, F002.
- Reuse endpoint-based `MCPServerConfig` and agent registration. *Evidence*: F003.
- Reuse local MCP toolkit configuration for optional host exposure and environment variables; reuse the Codex installer's marker-block upsert for `.codex/config.toml`. *Evidence*: F004.
- Process supervision must be async (aiohttp for the `/json/version` probe, `asyncio.create_subprocess_exec`, `asyncio.sleep`) — never `requests`, `httpx`, or blocking sleeps. *Evidence*: F003, project rules.
- If native embedding proceeds, use the existing maturin/PyO3 package shape and pin an upstream Obscura git tag (the crate is not on crates.io). *Evidence*: F004, F008.

### Integration Risks

- CDP method or context gaps can break Playwright flows; mitigate with driver contract tests and upstream CDP parity cases. *Evidence*: F005, F006, F007.
- Silent engine substitution: without explicit ownership the current factory starts Chrome where Obscura was expected. Mitigate by making Obscura mode fail fast when the endpoint is unreachable. *Evidence*: F003.
- HTTP discovery dials loopback for remote Obscura; mitigate by always using `ws://` endpoints in Obscura mode. *Evidence*: F007.
- Native Obscura MCP and Chrome DevTools MCP diverge in tool names, snapshots, outputs, and session behaviour; `WebAgent` prompts and any tool-name assumptions must be reviewed when the Obscura server is attached. *Evidence*: F003, F007.
- Obscura may not support Selenium because Selenium requires WebDriver semantics; do not claim Selenium support until the `debugger_address` experiment passes end to end. *Evidence*: F009.
- Native PyO3 builds may be slow, large, platform-sensitive, and unsafe across event-loop or V8 thread boundaries; gate it behind a spike. *Evidence*: F008.
- Private-network access is restricted by default upstream, so local test fixtures and deployment configuration need an explicit policy. *Evidence*: F005.
- No Windows artifact in v0.2.2; Windows users must build from source or use Docker. *Evidence*: F005.

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|---|---|---|---|---|
| C1 | `AbstractDriver` is the shared async browser contract. | F001 | high | Direct source read. |
| C2 | The current Playwright path launches a browser and lacks a CDP endpoint mode; engine selection passes through `DriverConfig`, `DriverRegistry` and `DriverFactory`. | F002 | high | Direct source read. |
| C3 | Chrome DevTools MCP is endpoint-oriented but implicitly launches Chrome for local URLs and emits only `--browser-url`. | F003 | high | Direct source read. |
| C4 | Local MCP configuration and the Codex installer support external toolkit/server exposure. | F004 | high | Direct source and documentation read. |
| C5 | Obscura v0.2.2 documents CDP (with `/json/*` discovery), Playwright/Puppeteer connectivity, and direct MCP. | F005, F007 | high | Upstream docs site, README, and server source read at tag v0.2.2. |
| C6 | Direct Obscura MCP creates a distinct browser tool/session contract (37 `browser_*` tools). | F007 | high | Upstream MCP source read at tag v0.2.2, line-verified. |
| C7 | Obscura exposes a Rust `Browser`/`Page` API; V8 enters through workspace path crates and is built from source, and the crate is consumed as a git dependency. | F008 | medium | Manifest and library guide read; build cost not measured. |
| C8 | Selenium cannot be assumed to drive Obscura directly through CDP; the `debugger_address` experiment is the cheapest way to settle it. | F009 | high | Selenium API/protocol documentation, existing `SeleniumSetup` seam, and upstream surface comparison. |
| C9 | Obscura rendering requires compatibility validation before default adoption. | F005, F006 | medium | Upstream limitations plus existing test seams. |
| C10 | Remote Obscura is unreachable through HTTP discovery because `/json/version` hardcodes a loopback WebSocket URL. | F007 | high | Direct upstream source read (server.rs 791, 800). |

Distribution: **8 high**, **2 medium**, **0 low**. Overall confidence stays **medium** because upstream rendering parity and native embedding cost remain unmeasured.

## 5. Open Questions

### Resolved

- [x] **Should Selenium be treated as a direct Obscura integration?** — *Resolved*: no, not without a WebDriver-to-CDP bridge or upstream WebDriver support; the `debugger_address` experiment is included in the compatibility matrix to settle it empirically. *Resolves*: C8.
- [x] **Which path should lead the integration?** — *Resolved*: CDP through the existing Playwright seam is the driver path; the native Obscura MCP server is a required, parallel deliverable for Codex and agents (Q&A U3). *Resolves*: C5, C6.
- [x] **Which Obscura release and build variant?** — *Resolved*: **v0.2.2 or later, `render` build (with or without `stealth`)**. Earlier releases and `no-render` variants are rejected. *Resolves*: C5, C9.
- [x] **How does Obscura reach Codex?** — *Resolved*: via the existing `.codex/config.toml` installer in `parrot/knowledge/wiki/codex/installer.py`, as one more `[mcp_servers.parrot-obscura]` table. *Resolves*: C4.

- [x] **Should ai-parrot supervise `obscura serve`, or require an externally managed endpoint?** — *Resolved (user, Q&A U2)*: ai-parrot supervises the process and exposes CLI commands to start and stop it. An external `ws://` endpoint stays configurable. *Resolves*: C2, C3.
- [x] **Is the native Obscura MCP server required, or is Chrome DevTools MCP over Obscura CDP enough?** — *Resolved (user, Q&A U3)*: the native server is required for Codex and agent UI-management; the CDP path remains required for the Playwright driver. *Resolves*: C5, C6.
- [x] **What defines compatibility acceptance?** — *Resolved (user, Q&A U4)*: the feature surface already supported by the Playwright driver. *Resolves*: C9.
- [x] **PyO3 spike gates?** — *Resolved (user, Q&A U5)*: no numbers now; defer native embedding to follow-up work. *Resolves*: C7.
- [x] **Platforms?** — *Resolved (user, Q&A U1)*: Linux only for the first milestone; Windows has no v0.2.2 artifact anyway. *Resolves*: C9.

### Unresolved (defer to spec / implementation)

- [ ] Which pages/fixtures back the Playwright-parity matrix, and how is the Obscura binary provisioned in CI (release archive vs Docker)? *Owner*: tbd. *Blocks*: C9.
- [ ] Does the `SeleniumSetup(debugger_address=…)` experiment pass against Obscura v0.2.2? Decides whether a WebDriver bridge proposal is ever needed. *Owner*: tbd. *Blocks*: C8.

## 6. Recommended Next Step

**`/sdd-spec obscura-new-browser-headless`** — specify the Linux Obscura v0.2.2 (render) integration: async process supervision with CLI start/stop, the Playwright connect-over-CDP mode, `--ws-endpoint` support, the three-seam engine selection, the required native Obscura MCP server (agents + Codex), and the Playwright-parity compatibility matrix including the Selenium `debugger_address` experiment. Keep Selenium ChromeDriver-based and defer PyO3 embedding to follow-up work.

### Alternatives

- **`/sdd-brainstorm obscura-new-browser-headless`** — only if the team later reopens native PyO3 embedding or a Selenium WebDriver bridge.
- **Manual review** — required before a native embedding plan or Selenium bridge is treated as a release commitment.

## 7. Research Audit

| Artifact | Path |
|---|---|
| State checkpoints | `sdd/state/FEAT-528/state.json` |
| Source | `sdd/state/FEAT-528/source.md` |
| Research plan | `sdd/state/FEAT-528/research_plan.json` |
| Findings | `sdd/state/FEAT-528/findings/F001-*.md` through `F010-*.md` |
| Synthesis | `sdd/state/FEAT-528/synthesis.json` |

**Budget consumed**: 23/40 files, 7/25 grep calls, 2/10 git calls, approximately 240/300 seconds; research was not truncated. The original run could not reach `docs.obscura.sh`; the revision-2 review pass reached it and verified the quickstart, Playwright guide, installation, and CLI reference pages, plus the v0.2.2 sources.

## 8. Provenance

| Field | Value |
|---|---|
| Generated by | `/sdd-proposal v1.0` |
| Mode | `enrichment` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | user-directed Codex session |
| Revision 2 | Claude Code review pass, 2026-09-05 — upstream citations re-verified at tag `v0.2.2`; original line ranges for `crates/obscura/*` and `crates/obscura-mcp/src/lib.rs` did not exist in the repository and were replaced |
