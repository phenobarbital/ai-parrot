---
type: feature
base_branch: dev
---

# Feature Specification: Supervised Obscura Browser Integration

**Feature ID**: FEAT-530
**Related proposal**: FEAT-528 — `sdd/proposals/obscura-new-browser-headless.proposal.md`
**Date**: 2026-09-05
**Author**: Jesus Lara
**Status**: draft
**Target version**: next development release

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's scraping and browsing toolkits currently launch Playwright or Selenium browser sessions, while its agent-facing browser path uses Chrome DevTools MCP. Obscura provides a Linux headless browser engine with a CDP server and a native MCP server. AI-Parrot needs a supervised Obscura integration that lets the existing Playwright driver connect over CDP and lets Codex and AI-Parrot agents use Obscura's native MCP tools without requiring users to manage browser processes manually.

### Goals

- Support Obscura `v0.2.2` on Linux as a supervised browser process.
- Add an explicit connect-over-CDP mode to the existing Playwright driver path.
- Preserve the current `AbstractDriver`, `DriverFactory`, scraping plan, and browsing toolkit contracts.
- Expose Obscura's native MCP server as a first-class agent/Codex browser capability.
- Provide AI-Parrot CLI commands to start, stop, and inspect the supervised Obscura process.
- Validate Obscura against the current Playwright driver feature surface, including its known unsupported or incomplete action paths.
- Keep native PyO3 embedding out of this feature; consider it only after the supervised Playwright/CDP path has been battle-tested.

### Non-Goals

- Replacing the existing Selenium ChromeDriver backend.
- Implementing a Selenium-to-Obscura WebDriver bridge.
- Making Obscura the default engine before compatibility validation passes.
- Embedding the Obscura Rust library into Python in this feature.
- Reimplementing Obscura's MCP tools inside AI-Parrot.
- Supporting non-Linux Obscura binaries in the first release.

## 2. Architectural Design

### Overview

The feature has two coordinated process-level integrations. `ObscuraProcessManager` supervises the pinned Linux binary and exposes lifecycle operations. `PlaywrightDriver` connects to the manager's CDP WebSocket endpoint when configured for the Obscura engine. Separately, the MCP integration creates a stdio configuration for `obscura mcp`, allowing `WebAgent`, AI-Parrot agents, Codex, and other MCP hosts to use Obscura's native browser tools. The existing Chrome DevTools MCP integration remains available for Chrome.

```text
AI-Parrot CLI / Agent lifecycle
              │
              ▼
ObscuraProcessManager ──starts──> obscura v0.2.2 (Linux)
              │                         │
              │ CDP endpoint            │ native MCP stdio
              ▼                         ▼
PlaywrightDriver                    Obscura MCP server
              │                         │
              ▼                         ▼
AbstractDriver                    Codex / WebAgent / Agent
              │
              ▼
WebScrapingToolkit / WebBrowsingToolkit
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractDriver` | preserves | Obscura is consumed through the existing async browser surface. |
| `PlaywrightConfig` | extends | Adds engine/endpoint/process configuration while retaining launch mode. |
| `PlaywrightDriver` | modifies | Uses `chromium.connect_over_cdp()` when Obscura mode is selected; retains existing launch behavior otherwise. |
| `DriverFactory` | extends | Maps an Obscura driver configuration to `PlaywrightDriver` in CDP mode. |
| `WebScrapingToolkit` | uses | Existing plan execution continues to issue `AbstractDriver` calls. |
| `WebBrowsingToolkit` | uses | Existing catalogued browser actions can select the Obscura-backed Playwright driver. |
| `create_chrome_devtools_mcp_server` | parallels | A separate Obscura MCP factory avoids changing Chrome-specific startup semantics. |
| `WebAgent` | extends | Configuration selects the Obscura MCP server for agent browser sessions. |
| local MCP configuration/installer | integrates | Codex and other hosts receive a managed `obscura mcp` stdio entry. |

### Data Models

The implementation should use the repository's existing configuration style and add fields equivalent to the following. Exact names may be finalized during task decomposition, but the semantics are required:

```python
@dataclass
class PlaywrightConfig:
    # Existing fields remain supported.
    browser_type: str = "chromium"
    headless: bool = True
    # New Obscura connection fields.
    engine: str = "playwright"
    cdp_endpoint_url: str | None = None
    obscura_binary: str | None = None
    obscura_port: int = 9222
    obscura_stealth: bool = False
    obscura_allow_private_network: bool = False
```

```python
@dataclass
class ObscuraProcessConfig:
    binary_path: str
    port: int = 9222
    host: str = "127.0.0.1"
    stealth: bool = False
    allow_private_network: bool = False
```

The manager must track whether it started the process so shutdown does not terminate an externally pre-existing process accidentally. Since the feature requires supervision, an externally running endpoint should be adopted only when explicitly configured as an attach-only mode; the normal managed mode starts and owns the process.

### New Public Interfaces

These are proposed public interfaces for specification purposes; implementation names and exact return models must be finalized against existing CLI conventions:

```python
class ObscuraProcessManager:
    async def start(self) -> str: ...
    async def stop(self) -> None: ...
    async def status(self) -> dict[str, object]: ...


def create_obscura_mcp_server(
    *,
    binary_path: str | None = None,
    stealth: bool = False,
    port: int = 9222,
    **kwargs: object,
) -> MCPServerConfig: ...
```

The CLI must expose start, stop, and status operations for the supervised process and an MCP operation that starts `obscura mcp` through the existing stdio MCP client/host integration.

## 3. Module Breakdown

### Module 1: Obscura Process Configuration and Manager

- **Path**: `packages/ai-parrot-server/src/parrot/mcp/obscura.py` (new)
- **Responsibility**: Validate Linux Obscura binary configuration, start `obscura serve` and `obscura mcp` processes when requested, probe readiness, retain process ownership, stop owned processes, and report status.
- **Depends on**: existing `ChromeManager` process/readiness pattern and `MCPServerConfig` transport model.

### Module 2: Playwright Obscura Connection Mode

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py` (modify)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` (modify)
- **Responsibility**: Add explicit CDP endpoint and Obscura configuration. Start Playwright, connect with `chromium.connect_over_cdp()` when configured, create the context/page required by the existing driver methods, and close only resources owned by the driver.
- **Depends on**: `AbstractDriver`, Playwright async API, and Module 1 readiness contract.

### Module 3: Driver and Toolkit Selection

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` (modify)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` (modify only if current configuration plumbing requires it)
- **Responsibility**: Accept an Obscura engine configuration and return the existing `PlaywrightDriver` in CDP mode. Preserve `driver_type="selenium"` and `driver_type="playwright"` behavior.
- **Depends on**: Module 2 and existing toolkit configuration models.

### Module 4: Native Obscura MCP Integration

- **Path**: `packages/ai-parrot/src/parrot/mcp/integration.py` (modify)
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome.py` (modify if WebAgent configuration is generalized)
- **Responsibility**: Add a factory/helper for the native `obscura mcp` stdio server, including binary path, version, stealth, port, and environment handling. Register it for agent use without changing the Chrome DevTools MCP defaults.
- **Depends on**: Module 1 and existing `MCPServerConfig`/agent registration.

### Module 5: AI-Parrot CLI Lifecycle

- **Path**: `packages/ai-parrot/src/parrot/cli/` (modify the existing lazy command registration)
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/` (modify the command implementation location selected by existing CLI conventions)
- **Responsibility**: Add commands to start, stop, and inspect the supervised Obscura process and a command/configuration path for the Obscura MCP server.
- **Depends on**: Module 1 and existing CLI lazy registration.

### Module 6: Compatibility and Integration Tests

- **Path**: `packages/ai-parrot-tools/tests/scraping/test_playwright_config.py` (extend)
- **Path**: `packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py` (extend)
- **Path**: `packages/ai-parrot-tools/tests/scraping/test_driver_factory.py` (extend)
- **Path**: `packages/ai-parrot-tools/tests/scraping/test_driver_integration.py` (extend)
- **Path**: `packages/ai-parrot/tests/bots/test_chrome.py` (extend if WebAgent configuration changes)
- **Path**: `tests/mcp/` (add Obscura MCP configuration tests)
- **Responsibility**: Test configuration, process ownership, CDP connection, MCP command construction, and Playwright feature parity using mocks plus an opt-in Linux Obscura integration fixture.
- **Depends on**: Modules 1–5.

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_obscura_config_defaults` | 1 | Validates Linux-oriented defaults, port bounds, and binary configuration. |
| `test_obscura_manager_start_waits_for_cdp` | 1 | Starts the configured binary, waits for the CDP endpoint, and records ownership. |
| `test_obscura_manager_stop_only_terminates_owned_process` | 1 | Does not terminate an adopted process; terminates a process started by the manager. |
| `test_obscura_manager_start_failure` | 1 | Returns a diagnosable error when the binary is absent or readiness times out. |
| `test_playwright_config_obscura_mode` | 2 | Preserves existing fields and carries endpoint/process settings. |
| `test_playwright_driver_connects_over_cdp` | 2 | Calls Playwright Chromium connect-over-CDP and creates the expected context/page. |
| `test_playwright_driver_quit_does_not_close_external_browser_unless_owned` | 2 | Separates Playwright client cleanup from Obscura process ownership. |
| `test_factory_creates_obscura_playwright_driver` | 3 | Obscura configuration returns `PlaywrightDriver` with CDP mode. |
| `test_factory_preserves_selenium_and_playwright_launch_modes` | 3 | Existing driver behavior remains unchanged. |
| `test_create_obscura_mcp_server_args` | 4 | Builds the `obscura mcp` stdio command and forwards supported options. |
| `test_obscura_cli_lifecycle` | 5 | CLI start/stop/status commands delegate to the manager. |

### Integration Tests

| Test | Description |
|---|---|
| `test_obscura_playwright_fixture_site` | Against a Linux Obscura v0.2.2 fixture, exercises the same navigation, DOM, waits, script, screenshot, cookie, and extraction calls used by the Playwright driver. |
| `test_obscura_scraping_plan_driver_parity` | Runs representative scraping plan actions through the existing executor and compares driver-level results. |
| `test_obscura_browsing_toolkit_catalog_flow` | Runs a representative catalogued browsing flow with the Obscura-backed Playwright driver. |
| `test_obscura_native_mcp_stdio_interop` | Starts `obscura mcp`, performs initialize/list/call interactions, and validates Codex-compatible MCP responses. |
| `test_obscura_webagent_configuration` | Verifies an agent receives native Obscura MCP tools while Chrome configuration remains available. |

### Compatibility Matrix

The matrix must enumerate every method in `AbstractDriver` and every action currently exercised by the Playwright integration tests. It must separately record pass, unsupported, and known-existing-gap outcomes. At minimum it covers navigation, back/forward/reload, click, fill, select, hover, keypress, page source, text/attributes, screenshots, selector/navigation/load waits, JavaScript evaluation, request interception, HAR, PDF, tracing, route mocking, authentication, cookies, file upload, human/browser-event waits, and downloads.

### Test Data / Fixtures

- A local deterministic fixture site already used by `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`.
- A Linux-only `obscura` binary fixture or operator-provided binary pinned to v0.2.2.
- An opt-in marker for tests requiring the external Obscura binary; ordinary unit tests must mock process and Playwright APIs.
- A temporary port and profile/storage directory per integration test to prevent cross-test state.

## 5. Acceptance Criteria

- [ ] Obscura v0.2.2 Linux binary configuration is validated and documented.
- [ ] AI-Parrot can start, stop, and report the status of an owned Obscura `serve` process through CLI commands.
- [ ] Startup waits for a responsive CDP endpoint and reports actionable failures.
- [ ] `PlaywrightDriver` connects to Obscura through CDP when configured and retains current launch behavior otherwise.
- [ ] `AbstractDriver` callers and existing scraping plans require no Obscura-specific branching.
- [ ] Selenium remains functional and continues to use its existing ChromeDriver/Selenium path.
- [ ] The native `obscura mcp` server is exposed as an MCP capability for Codex and AI-Parrot agents.
- [ ] Obscura MCP lifecycle and tool discovery work over stdio without polluting the JSON-RPC channel.
- [ ] The compatibility matrix covers every existing `AbstractDriver` method and Playwright integration action, with known gaps recorded explicitly.
- [ ] The deterministic fixture-site integration passes for the supported Playwright feature surface.
- [ ] Existing scraping, browsing, Playwright, Selenium, and MCP tests pass.
- [ ] No native PyO3 code or Obscura Rust library dependency is introduced by this feature.
- [ ] Documentation describes Linux/v0.2.2 prerequisites, CLI lifecycle commands, MCP setup, and the current compatibility limits.

## 6. Codebase Contract

### Verified Imports

```python
from parrot.tools.scraping.drivers.abstract import AbstractDriver
from parrot.tools.scraping.driver_factory import DriverFactory
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot.mcp.integration import MCPServerConfig
```

Verified by `packages/ai-parrot-tools/tests/scraping/test_driver_integration.py:13-15, 209-218` and `packages/ai-parrot/src/parrot/mcp/integration.py:22-26`.

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11
class AbstractDriver(ABC):
    async def start(self) -> None: ...  # :36-38
    async def quit(self) -> None: ...  # :40-42
    async def navigate(self, url: str, timeout: int = 30) -> None: ...  # :46-53
    async def click(self, selector: str, timeout: int = 10) -> None: ...  # :69-76
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...  # :78-88
    async def screenshot(self, path: str, full_page: bool = False) -> bytes: ...  # :168-180

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:15
class PlaywrightDriver(AbstractDriver):
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None: ...  # :30-37
    async def start(self) -> None: ...  # :41-91
    async def quit(self) -> None: ...  # :93-105

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:9
@dataclass
class PlaywrightConfig:
    browser_type: str = "chromium"  # :54
    headless: bool = True  # :55
    timeout: int = 30  # :57
    storage_state: Optional[str] = None  # :71
    user_data_dir: Optional[str] = None  # :72

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:31
class DriverFactory:
    @staticmethod
    def create(config: Optional[Union[Dict[str, Any], Any]] = None) -> AbstractDriver: ...  # :43-46

# packages/ai-parrot/src/parrot/mcp/integration.py:22
MCPServerConfig = MCPClientConfig
```

`PlaywrightDriver.start` currently calls `async_playwright().start()`, selects the configured browser launcher, and calls `launch()` or `launch_persistent_context()` at `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:41-85`. The Obscura branch must be added without changing the existing branch's semantics.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Obscura process manager | `ChromeManager` pattern | readiness probe and owned `Popen` lifecycle | `packages/ai-parrot-server/src/parrot/mcp/chrome.py:8-70` |
| Obscura Playwright mode | `PlaywrightDriver` | `async_playwright()` and Chromium CDP connection | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:41-85` |
| Driver selection | `DriverFactory.create()` | normalized configuration dictionary | `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:43-109` |
| Obscura agent MCP | `MCPServerConfig` | stdio command/args configuration | `packages/ai-parrot/src/parrot/mcp/integration.py:1105-1192` |
| Obscura local MCP | toolkit/MCP host configuration | command and environment configuration | `packages/ai-parrot/src/parrot/mcp/toolkit_config.py:19-61`, `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:30-73` |
| Compatibility tests | existing driver surface | `AbstractDriver` method calls and fixture-site flows | `packages/ai-parrot-tools/tests/scraping/test_driver_integration.py:92-178`, `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py:1-32` |

### Does NOT Exist (Anti-Hallucination)

- `parrot_tools.scraping.drivers.ObscuraDriver` does not exist; the design reuses `PlaywrightDriver` in CDP mode.
- `ObscuraProcessManager` does not exist yet; it is a proposed new component.
- Obscura is not an existing dependency, binary, or configuration entry in this repository.
- Selenium cannot currently be assumed to connect to Obscura's CDP endpoint; no WebDriver-to-Obscura bridge exists.
- Native PyO3 bindings for Obscura do not exist in this repository and are explicitly out of scope.

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Preserve `AbstractDriver` as the browser-neutral contract and keep all public browser operations asynchronous.
- Follow the existing `PlaywrightDriver` lazy import and lifecycle pattern.
- Follow `ChromeManager` readiness and owned-process cleanup behavior, with explicit distinction between managed and adopted processes.
- Follow `MCPServerConfig` stdio command/argument construction and existing agent `add_mcp_server` registration.
- Use the existing CLI lazy-registration approach rather than introducing a second command framework.
- Keep structured configuration in the repository's dataclass/Pydantic conventions and log lifecycle transitions with the component logger.

### Known Risks / Gotchas

- Obscura v0.2.2 has an evolving independent renderer; compatibility is measured against the current Playwright driver contract, not assumed from CDP protocol naming.
- Obscura's `--allow-private-network` is required for local fixture pages and must not be enabled silently in general deployments.
- A supervised process must not kill a process it did not start; ownership state must be explicit.
- Obscura MCP is a second tool schema from Chrome DevTools MCP. Codex registration and tool discovery must be tested independently.
- Existing Playwright integration tests document known gaps around cookie reads, some waits, file uploads, and downloads; the new matrix must preserve those distinctions.
- Linux-only packaging should be explicit. No platform fallback should silently launch Chrome or Selenium when Obscura was selected.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `obscura` binary | `v0.2.2` | Supervised Linux headless browser and native MCP server. |
| `playwright` | existing project constraint | Python CDP client and current driver implementation. |
| `selenium` | existing project constraint | Unchanged legacy/ChromeDriver backend. |

No new Python package or PyO3/Rust dependency is introduced by this specification.

## 8. Open Questions

- [x] Target release/platform — **Resolved**: Obscura v0.2.2 on Linux.
- [x] Process ownership — **Resolved**: ai-parrot supervises Obscura and exposes CLI start/stop/status commands.
- [x] Compatibility target — **Resolved**: the existing Playwright driver feature surface, including explicit known gaps.
- [x] PyO3 timing — **Resolved**: defer until after the Playwright/CDP path is battle-tested.
- [x] MCP integration — **Resolved**: native Obscura MCP is required for Codex and AI-Parrot agent UI-management use cases.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-05 | Jesus Lara | Initial formal specification from FEAT-528 proposal and resolved decisions |
