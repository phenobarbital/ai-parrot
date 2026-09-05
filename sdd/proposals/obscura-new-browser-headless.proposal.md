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
---

# FEAT-528 — Evaluate Obscura as a CDP-backed browser engine and optional MCP server for ai-parrot

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-528/`](../state/FEAT-528/)

---

## 0. Origin

The original request is preserved in `sdd/state/FEAT-528/source.md`.

> $sdd-proposal obscura-new-browser-headless -- Current ScrapingToolkit+WebBrowsingToolkits are using or own driver for Selenium+Playright or Chrome Dev Tools MCP, there is a new headless browser engine written in Rust called Obscura: https://github.com/h4ckf0r0day/obscura, `Obscura` is compatible with Chrome DevTools protocol, and is a drop-in replacement to work with Puppeterr+Playright, documentation: `https://docs.obscura.sh/` the idea is providing to our Playwright driver the ability to connect Obscura: https://docs.obscura.sh/quickstart/connect-puppeteer-or-playwright to interact with the headless browser provided by Obscura, Obscura exposes an API Surface to be used as a Rust Library and the idea is because ai-parrot have PyO3 support (there are several crates installed into ai-parrot codebase) think if we can use Obscura as a direct replacement of Chrome DevTools in some existing toolkits and added as an MCP server to a ai-parrot agent or a Codex session.

**Initial signals**: additive verbs; named entities include Obscura, Playwright, Selenium, Chrome DevTools MCP, PyO3, and Codex; no acceptance criteria were provided.

## 1. Synthesis Summary

The request is bounded to Linux and Obscura `v0.2.2`, supervised by ai-parrot. `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` can gain a CDP connection mode configured through `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`, selected through `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`, while preserving `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`. The existing `packages/ai-parrot/src/parrot/mcp/integration.py` and `packages/ai-parrot/src/parrot/bots/chrome.py` can be reused with an Obscura CDP endpoint, while the native Obscura MCP server is required for Codex and agent UI-management use cases. Compatibility acceptance covers the feature surface already supported by the Playwright driver. Selenium remains ChromeDriver-based, and native PyO3 embedding is deferred until the supervised Playwright/CDP integration has been battle-tested.

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|---|---|---|---|---|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | `AbstractDriver` | 11-180 | Shared async browser contract | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | `PlaywrightDriver.start` | 15-105 | Current Playwright launch and lifecycle | F001, F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py` | `PlaywrightConfig` | 12-73 | Browser launch and context configuration | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | `DriverFactory` | 1-80 | Driver selection seam | F001, F002 |
| 5 | `packages/ai-parrot/src/parrot/mcp/integration.py` | `create_chrome_devtools_mcp_server` | 1105-1192 | External browser MCP configuration | F003 |
| 6 | `packages/ai-parrot/src/parrot/bots/chrome.py` | `WebAgent.configure` | 290-334 | Agent wiring for browser MCP | F003 |
| 7 | `packages/ai-parrot-server/src/parrot/mcp/chrome.py` | `ChromeManager` | 8-70 | Managed local browser lifecycle | F003 |
| 8 | `docs/mcp-local-toolkits.md` | `mcp-toolkits.yaml` schema | 45-115 | Local MCP exposure and environment configuration | F004 |
| 9 | `packages/navrules/pyproject.toml` | `tool.maturin` | 1-4, 40-44 | PyO3/Maturin packaging precedent | F004 |
| 10 | `packages/navrules/rust/Cargo.toml` | `navrules_native` | 8-23 | Rust extension crate precedent | F004 |
| 11 | `https://github.com/h4ckf0r0day/obscura` | CDP, Playwright, and MCP surfaces | README sections | Upstream process-level integration surface | F005, F007 |
| 12 | `https://github.com/h4ckf0r0day/obscura/blob/main/crates/obscura/src/lib.rs` | `Browser`, `Page` | 261-315 | Upstream native Rust API | F008 |
| 13 | `https://github.com/h4ckf0r0day/obscura/blob/main/crates/obscura-mcp/src/lib.rs` | `obscura_mcp::run` | 2572-2696, 3537-3624 | Upstream direct MCP server | F007 |
| 14 | `https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_chromium/selenium.webdriver.chromium.options.html` | `ChromiumOptions.debugger_address` | API reference | Selenium remote DevTools capability | F009 |

### 2.2 Constraints Discovered

- The first adapter must preserve `AbstractDriver` and `DriverFactory`; existing scraping actions should not need a new browser-specific contract. *Evidence*: F001, F002.
- CDP attachment and browser process ownership are separate concerns. ai-parrot will supervise the Obscura process and expose CLI start/stop commands. *Evidence*: F002, F003, F005.
- Direct Obscura MCP is required for Codex and agent UI-management use cases; its `browser_*` tools and state semantics require their own lifecycle tests. *Evidence*: F003, F007.
- The selected target is Obscura `v0.2.2` on Linux. *Evidence*: F010.
- Selenium's CDP commands operate through an established WebDriver/ChromeDriver session. A direct Selenium-to-Obscura path requires a WebDriver bridge or upstream WebDriver implementation. *Evidence*: F009.
- PyO3 interaction is deferred until after the Playwright/CDP integration is battle-tested; no hard build or artifact thresholds are required now. *Evidence*: F004, F008.
- Obscura's renderer is independent and evolving; CSS, Web API, media, compositor, and font behavior can differ from Chromium. *Evidence*: F005.

### 2.3 Recent History (Relevant)

Recent history includes local toolkit MCP support and scraping model/driver changes. Existing tests cover Playwright driver/configuration, scraping driver discovery, and local MCP toolkit configuration. No repository history or source entry establishes an existing Obscura integration or an Obscura binary in CI. The selected upstream release is v0.2.2. *Evidence*: F006, F010.

## 3. Probable Scope

### What's New

- Obscura v0.2.2 Linux process supervision with ai-parrot CLI start/stop commands.
- Obscura CDP endpoint configuration and lifecycle support for the Playwright-backed scraping/browsing path.
- A required Obscura MCP server configuration for Codex and agent UI-management sessions.
- A compatibility test matrix covering the existing Playwright driver feature surface.
- Follow-up PyO3 feasibility work after the Playwright/CDP path is battle-tested.

### What Changes

- `PlaywrightConfig` and `PlaywrightDriver.start` gain an explicit connect-over-CDP mode while retaining launch mode. *Evidence*: F002.
- `DriverFactory` and toolkit configuration expose the selected engine without changing `AbstractDriver` callers. *Evidence*: F001, F002, F004.
- The Chrome DevTools MCP factory and `WebAgent` gain an Obscura endpoint/process configuration path, with browser process ownership explicit. *Evidence*: F003, F007.
- Direct Obscura MCP registration uses the existing external stdio MCP configuration pattern and validates tool/session behavior for Codex and agents. *Evidence*: F003, F004, F007.
- Selenium remains backed by ChromeDriver in the first milestone. A WebDriver bridge is a separate proposal if Selenium parity is required. *Evidence*: F009.

### What's Untouched (Non-Goals)

- Replacing Selenium's Chrome backend in the first milestone.
- Making Obscura the default browser engine before compatibility tests pass.
- Embedding the full Obscura engine into Python before the supervised Playwright/CDP path is battle-tested.
- Reimplementing Obscura's MCP tool schema inside ai-parrot.

### Patterns to Follow

- Reuse the async `AbstractDriver` lifecycle and lazy dependency behavior. *Evidence*: F001, F002.
- Reuse endpoint-based `MCPServerConfig` and agent registration. *Evidence*: F003.
- Reuse local MCP toolkit configuration for optional host exposure and environment variables. *Evidence*: F004.
- If native embedding proceeds, use the existing maturin/PyO3 package shape and pin an upstream Obscura tag. *Evidence*: F004, F008.

### Integration Risks

- CDP method or context gaps can break Playwright flows; mitigate with driver contract tests and upstream CDP parity cases. *Evidence*: F005, F006, F007.
- Direct MCP and Chrome DevTools MCP may diverge in tool names, snapshots, outputs, or session behavior; keep direct MCP optional until parity is measured. *Evidence*: F003, F007.
- Obscura may not support Selenium because Selenium requires WebDriver semantics; avoid claiming Selenium support without a bridge and end-to-end test. *Evidence*: F009.
- Native PyO3 builds may be slow, large, platform-sensitive, and unsafe across event-loop or V8 thread boundaries; gate it behind a spike. *Evidence*: F008.
- Private-network access is restricted by default upstream, so local test fixtures and deployment configuration need an explicit policy. *Evidence*: F005.

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|---|---|---|---|---|
| C1 | `AbstractDriver` is the shared async browser contract. | F001 | high | Direct source read. |
| C2 | The current Playwright path launches a browser and lacks a CDP endpoint mode. | F002 | high | Direct source read. |
| C3 | Chrome DevTools MCP is already endpoint-oriented and agent-integrated. | F003 | high | Direct source read. |
| C4 | Local MCP configuration supports external or importable toolkit exposure with kwargs and environment variables. | F004 | high | Direct source and documentation read. |
| C5 | Obscura documents CDP, Playwright/Puppeteer connectivity, and direct MCP. | F005, F007 | medium | Upstream documentation and source read; supplied docs site was unavailable to the crawler. |
| C6 | Direct Obscura MCP creates a distinct browser tool/session contract. | F007 | medium | Upstream MCP source read. |
| C7 | Obscura exposes a Rust Browser/Page API but builds V8 from source through a git dependency. | F008 | medium | Upstream manifest and library guide read. |
| C8 | Selenium cannot be assumed to drive Obscura directly through CDP. | F009 | high | Selenium API/protocol documentation and upstream Obscura surface comparison. |
| C9 | Obscura rendering requires compatibility validation before default adoption. | F005, F006 | medium | Upstream limitations plus existing test seams. |

Distribution: **4 high**, **5 medium**, **0 low**. Overall confidence is **medium** because process-level compatibility is well localized, while upstream release/platform behavior and native embedding remain unresolved.

## 5. Open Questions

### Resolved

- [x] **Should Selenium be treated as a direct Obscura integration?** — *Resolved*: no, not without a WebDriver-to-CDP bridge or upstream WebDriver support. *Resolves*: C8.
- [x] **Which path should lead the integration?** — *Resolved*: CDP reuse through the existing Playwright/Chrome DevTools seams leads the driver integration, and direct Obscura MCP is required for Codex and agent UI-management use cases. *Resolves*: C5, C6.
- [x] **Which Obscura release and platform are targeted?** — *Resolved*: v0.2.2 on Linux. *Resolves*: C5, C9. *Evidence*: F010.
- [x] **Who owns the Obscura process lifecycle?** — *Resolved*: ai-parrot supervises it and exposes CLI start/stop commands. *Resolves*: C2, C3.
- [x] **What defines compatibility acceptance?** — *Resolved*: the feature surface already supported by the Playwright driver. *Resolves*: C6, C9.
- [x] **When should PyO3 embedding be addressed?** — *Resolved*: after the supervised Playwright/CDP path has been battle-tested; no hard numbers are required now. *Resolves*: C7.

### Deferred implementation detail

There are no unresolved proposal questions. The specification must turn these decisions into acceptance criteria and task boundaries.

## 6. Recommended Next Step

**`/sdd-spec obscura-new-browser-headless`** — specify Linux Obscura v0.2.2 supervision, CLI lifecycle commands, Playwright CDP integration, required direct Obscura MCP exposure for Codex/agents, and Playwright feature parity tests. Keep Selenium unchanged and defer PyO3 embedding until after battle testing.

### Alternatives

- **`/sdd-brainstorm obscura-new-browser-headless`** — if the team later wants to revisit native PyO3 embedding or a Selenium WebDriver bridge.
- **Manual review** — required before changing the Linux/v0.2.2 target or treating native embedding as a release commitment.

## 7. Research Audit

| Artifact | Path |
|---|---|
| State checkpoints | `sdd/state/FEAT-528/state.json` |
| Source | `sdd/state/FEAT-528/source.md` |
| Research plan | `sdd/state/FEAT-528/research_plan.json` |
| Findings | `sdd/state/FEAT-528/findings/F001-*.md` through `F010-*.md` |
| Synthesis | `sdd/state/FEAT-528/synthesis.json` |

**Budget consumed**: 23/40 files, 7/25 grep calls, 2/10 git calls, approximately 240/300 seconds; research was not truncated. The Obscura documentation URLs supplied in the request returned a crawl error, so equivalent upstream GitHub README, source, wiki, and release evidence was used. The v0.2.2 release selection was verified separately in F010.

## 8. Provenance

| Field | Value |
|---|---|
| Generated by | `/sdd-proposal v1.0` |
| Mode | `enrichment` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | user-directed Codex session |
