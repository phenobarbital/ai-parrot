# WebAgent — Chrome DevTools MCP Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a general-purpose `WebAgent(BasicAgent)` that launches Chrome DevTools MCP server on configure, supports free-form web interaction and structured QA test execution.

**Architecture:** `WebAgent` inherits from `BasicAgent` (which already inherits `MCPEnabledMixin`). A `ChromeConfig` Pydantic model parametrizes all chrome-devtools-mcp flags. `run_tests()` is a convenience method that serializes `QATestCase` objects into a prompt and delegates to `ask()` with `structured_output=QAReport`. The LLM uses MCP tools (navigate, click, fill, screenshot, etc.) to execute the steps.

**Tech Stack:** Python 3.12+, Pydantic v2, chrome-devtools-mcp (npm), pytest + pytest-asyncio

## Global Constraints

- All models use Pydantic v2 (`BaseModel` from `pydantic`)
- Async-first — no blocking I/O
- `self.logger` for all diagnostics — no `print`
- Google-style docstrings + strict type hints on all public methods
- Tests use `pytest-asyncio` with `AsyncMock`/`MagicMock` for MCP/LLM mocking
- `ruff check` clean on all new/modified files

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chrome.py` | CREATE | `ChromeConfig`, QA models (`QAAssertion`, `QATestCase`, `QAFinding`, `QAReport`), `WebAgent` class |
| `packages/ai-parrot/src/parrot/bots/__init__.py` | MODIFY | Add `WebAgent` to re-exports |
| `packages/ai-parrot-server/src/parrot/mcp/chrome.py` | MODIFY | `ChromeManager.start()` accepts `headless` param |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | Extend `create_chrome_devtools_mcp_server()` and `add_chrome_devtools_mcp_server()` with new Chrome config params |
| `packages/ai-parrot/tests/bots/test_chrome.py` | CREATE | Unit tests for all new code |
| `examples/chrome_qa_test.py` | CREATE | Usage example |

---

### Task 1: ChromeConfig model and ChromeManager headless support

**Files:**
- Create: `packages/ai-parrot/src/parrot/bots/chrome.py` (initial — ChromeConfig only)
- Modify: `packages/ai-parrot-server/src/parrot/mcp/chrome.py:35-71` (ChromeManager.start)
- Test: `packages/ai-parrot/tests/bots/test_chrome.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ChromeConfig` — Pydantic model with fields: `browser_url: Optional[str]`, `headless: bool`, `user_data_dir: Optional[str]`, `channel: Optional[Literal["stable","beta","dev","canary"]]`, `viewport: Optional[str]`, `executable_path: Optional[str]`, `isolated: bool`, `no_usage_statistics: bool`, `auto_connect: bool`, `port: int`
  - `ChromeConfig.to_mcp_args() -> list[str]`
  - `ChromeManager.start(headless: bool = True) -> bool`

- [ ] **Step 1: Write failing tests for ChromeConfig**

Create `packages/ai-parrot/tests/bots/test_chrome.py`:

```python
import pytest
from parrot.bots.chrome import ChromeConfig


def test_chrome_config_defaults():
    config = ChromeConfig()
    assert config.headless is False
    assert config.port == 9222
    assert config.no_usage_statistics is True
    assert config.isolated is False
    assert config.auto_connect is False
    assert config.browser_url is None
    assert config.user_data_dir is None
    assert config.channel is None
    assert config.viewport is None
    assert config.executable_path is None


def test_chrome_config_to_mcp_args_minimal():
    """No-headless config should NOT include --headless flag."""
    config = ChromeConfig()
    args = config.to_mcp_args()
    assert "-y" in args
    assert "chrome-devtools-mcp@latest" in args
    assert "--headless" not in args
    assert "--no-usage-statistics" in args


def test_chrome_config_to_mcp_args_headless():
    config = ChromeConfig(headless=True)
    args = config.to_mcp_args()
    assert "--headless" in args


def test_chrome_config_to_mcp_args_full():
    config = ChromeConfig(
        browser_url="http://127.0.0.1:9333",
        headless=True,
        user_data_dir="/tmp/chrome-profile",
        channel="canary",
        viewport="1920x1080",
        executable_path="/usr/bin/chromium",
        isolated=True,
        auto_connect=True,
    )
    args = config.to_mcp_args()
    assert "--browser-url=http://127.0.0.1:9333" in args
    assert "--headless" in args
    assert "--user-data-dir=/tmp/chrome-profile" in args
    assert "--channel=canary" in args
    assert "--viewport=1920x1080" in args
    assert "--executable-path=/usr/bin/chromium" in args
    assert "--isolated" in args
    assert "--auto-connect" in args
    assert "--no-usage-statistics" in args


def test_chrome_config_to_mcp_args_no_stats_disabled():
    config = ChromeConfig(no_usage_statistics=False)
    args = config.to_mcp_args()
    assert "--no-usage-statistics" not in args
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v
```

Expected: `ModuleNotFoundError: No module named 'parrot.bots.chrome'`

- [ ] **Step 3: Implement ChromeConfig**

Create `packages/ai-parrot/src/parrot/bots/chrome.py`:

```python
"""WebAgent — browser interaction via Chrome DevTools MCP."""

from typing import Optional, Literal, List
from pydantic import BaseModel, Field


class ChromeConfig(BaseModel):
    """Configuration for chrome-devtools-mcp server."""

    browser_url: Optional[str] = None
    headless: bool = False
    user_data_dir: Optional[str] = None
    channel: Optional[Literal["stable", "beta", "dev", "canary"]] = None
    viewport: Optional[str] = None
    executable_path: Optional[str] = None
    isolated: bool = False
    no_usage_statistics: bool = True
    auto_connect: bool = False
    port: int = Field(default=9222, ge=1, le=65535)

    def to_mcp_args(self) -> List[str]:
        """Generate args list for npx chrome-devtools-mcp."""
        args = ["-y", "chrome-devtools-mcp@latest"]
        if self.browser_url:
            args.append(f"--browser-url={self.browser_url}")
        if self.headless:
            args.append("--headless")
        if self.user_data_dir:
            args.append(f"--user-data-dir={self.user_data_dir}")
        if self.channel:
            args.append(f"--channel={self.channel}")
        if self.viewport:
            args.append(f"--viewport={self.viewport}")
        if self.executable_path:
            args.append(f"--executable-path={self.executable_path}")
        if self.isolated:
            args.append("--isolated")
        if self.no_usage_statistics:
            args.append("--no-usage-statistics")
        if self.auto_connect:
            args.append("--auto-connect")
        return args
```

- [ ] **Step 4: Run ChromeConfig tests to verify they pass**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v -k "chrome_config"
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Update ChromeManager.start() for headless param**

Modify `packages/ai-parrot-server/src/parrot/mcp/chrome.py`. Change `start()` signature from `def start(self) -> bool` to `def start(self, headless: bool = True) -> bool`.

In the `cmd` list construction at line 64-72, conditionally include `--headless=new`:

```python
def start(self, headless: bool = True) -> bool:
    """Start Chrome if not already running."""
    if self.is_chrome_running():
        self.logger.info("Chrome is already running on port %s", self.port)
        return True

    mode = "headless" if headless else "visible"
    self.logger.info("Starting %s Chrome...", mode)

    cmd = [
        "google-chrome",
        f"--remote-debugging-port={self.port}",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--remote-allow-origins=*",
    ]
    if headless:
        cmd.insert(1, "--headless=new")
    # ... rest of method unchanged
```

- [ ] **Step 6: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/chrome.py \
       packages/ai-parrot/tests/bots/test_chrome.py \
       packages/ai-parrot-server/src/parrot/mcp/chrome.py
git commit -m "feat(chrome): add ChromeConfig model and headless support in ChromeManager"
```

---

### Task 2: Extend MCP factory and mixin for Chrome config params

**Files:**
- Modify: `packages/ai-parrot/src/parrot/mcp/integration.py:1110-1166` (`create_chrome_devtools_mcp_server`)
- Modify: `packages/ai-parrot/src/parrot/mcp/integration.py:1449-1464` (`add_chrome_devtools_mcp_server`)
- Test: `packages/ai-parrot/tests/bots/test_chrome.py` (append)

**Interfaces:**
- Consumes: `ChromeConfig.to_mcp_args() -> list[str]` from Task 1
- Produces:
  - `create_chrome_devtools_mcp_server(browser_url, name, headless, user_data_dir, channel, viewport, executable_path, isolated, no_usage_statistics, auto_connect, **kwargs) -> MCPServerConfig`
  - `MCPEnabledMixin.add_chrome_devtools_mcp_server(browser_url, name, headless, user_data_dir, channel, viewport, executable_path, isolated, no_usage_statistics, auto_connect, **kwargs) -> List[str]`

- [ ] **Step 1: Write failing test for extended factory**

Append to `packages/ai-parrot/tests/bots/test_chrome.py`:

```python
from parrot.mcp.integration import create_chrome_devtools_mcp_server


def test_create_chrome_devtools_mcp_server_default_args():
    config = create_chrome_devtools_mcp_server()
    assert config.command == "npx"
    assert "--no-usage-statistics" in config.args
    assert "--headless" not in config.args


def test_create_chrome_devtools_mcp_server_headless():
    config = create_chrome_devtools_mcp_server(headless=True)
    assert "--headless" in config.args


def test_create_chrome_devtools_mcp_server_full_config():
    config = create_chrome_devtools_mcp_server(
        browser_url="http://127.0.0.1:9333",
        headless=True,
        user_data_dir="/tmp/profile",
        channel="dev",
        viewport="1280x720",
    )
    assert "--browser-url=http://127.0.0.1:9333" in config.args
    assert "--headless" in config.args
    assert "--user-data-dir=/tmp/profile" in config.args
    assert "--channel=dev" in config.args
    assert "--viewport=1280x720" in config.args
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py::test_create_chrome_devtools_mcp_server_default_args -v
```

Expected: `TypeError: create_chrome_devtools_mcp_server() got an unexpected keyword argument 'headless'` (on the headless test) or missing `--no-usage-statistics` in args.

- [ ] **Step 3: Rewrite create_chrome_devtools_mcp_server()**

Replace `packages/ai-parrot/src/parrot/mcp/integration.py:1110-1166`:

```python
def create_chrome_devtools_mcp_server(
    browser_url: str = "http://127.0.0.1:9222",
    name: str = "chrome-devtools",
    headless: bool = False,
    user_data_dir: Optional[str] = None,
    channel: Optional[str] = None,
    viewport: Optional[str] = None,
    executable_path: Optional[str] = None,
    isolated: bool = False,
    no_usage_statistics: bool = True,
    auto_connect: bool = False,
    **kwargs
) -> MCPServerConfig:
    """Create configuration for Chrome DevTools MCP server.

    Args:
        browser_url: URL where Chrome is listening for devtools protocol.
        name: Server name.
        headless: Run Chrome without UI (default: False — visible).
        user_data_dir: Path to Chrome user data directory (profile).
        channel: Chrome channel — "stable", "beta", "dev", "canary".
        viewport: Initial viewport size, e.g. "1280x720".
        executable_path: Path to custom Chrome executable.
        isolated: Use temporary user-data-dir, cleaned up on close.
        no_usage_statistics: Opt out of Google usage statistics.
        auto_connect: Auto-connect to locally running Chrome (144+).
        **kwargs: Additional MCPServerConfig parameters.

    Returns:
        MCPServerConfig configured for Chrome DevTools.
    """
    port = 9222
    is_local = False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(browser_url)
        if parsed.port:
            port = parsed.port
        hostname = parsed.hostname or "localhost"
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            is_local = True
    except Exception:
        is_local = True

    if is_local and not auto_connect:
        if port not in _chrome_managers:
            chrome_manager = ChromeManager(port=port)
            _chrome_managers[port] = chrome_manager
        else:
            chrome_manager = _chrome_managers[port]
        chrome_manager.start(headless=headless)

    args = ["-y", "chrome-devtools-mcp@latest", f"--browser-url={browser_url}"]
    if headless:
        args.append("--headless")
    if user_data_dir:
        args.append(f"--user-data-dir={user_data_dir}")
    if channel:
        args.append(f"--channel={channel}")
    if viewport:
        args.append(f"--viewport={viewport}")
    if executable_path:
        args.append(f"--executable-path={executable_path}")
    if isolated:
        args.append("--isolated")
    if no_usage_statistics:
        args.append("--no-usage-statistics")
    if auto_connect:
        args.append("--auto-connect")

    return MCPServerConfig(
        name=name,
        command="npx",
        args=args,
        transport="stdio",
        **kwargs
    )
```

- [ ] **Step 4: Update add_chrome_devtools_mcp_server() on MCPEnabledMixin**

Replace `packages/ai-parrot/src/parrot/mcp/integration.py:1449-1464`:

```python
    async def add_chrome_devtools_mcp_server(
        self,
        browser_url: str = "http://127.0.0.1:9222",
        name: str = "chrome-devtools",
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        channel: Optional[str] = None,
        viewport: Optional[str] = None,
        executable_path: Optional[str] = None,
        isolated: bool = False,
        no_usage_statistics: bool = True,
        auto_connect: bool = False,
        **kwargs
    ) -> List[str]:
        """Add Chrome DevTools MCP server capability.

        Args:
            browser_url: URL where Chrome is listening for devtools protocol.
            name: Server name.
            headless: Run Chrome without UI.
            user_data_dir: Path to Chrome profile directory.
            channel: Chrome channel (stable/beta/dev/canary).
            viewport: Initial viewport size, e.g. "1280x720".
            executable_path: Path to custom Chrome executable.
            isolated: Use temporary profile.
            no_usage_statistics: Opt out of Google telemetry.
            auto_connect: Auto-connect to local Chrome (144+).
            **kwargs: Additional MCPServerConfig parameters.

        Returns:
            List of registered tool names.
        """
        config = create_chrome_devtools_mcp_server(
            browser_url=browser_url,
            name=name,
            headless=headless,
            user_data_dir=user_data_dir,
            channel=channel,
            viewport=viewport,
            executable_path=executable_path,
            isolated=isolated,
            no_usage_statistics=no_usage_statistics,
            auto_connect=auto_connect,
            **kwargs
        )
        return await self.add_mcp_server(config)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v -k "create_chrome"
```

Expected: all 3 factory tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/ai-parrot/src/parrot/mcp/integration.py \
       packages/ai-parrot/tests/bots/test_chrome.py
git commit -m "feat(mcp): extend chrome-devtools factory with headless, profile, channel params"
```

---

### Task 3: QA models (QAAssertion, QATestCase, QAFinding, QAReport)

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/chrome.py` (append models)
- Test: `packages/ai-parrot/tests/bots/test_chrome.py` (append)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `QAAssertion(check: Literal[...], target: Optional[str], value: Optional[str])`
  - `QATestCase(name: str, url: str, steps: list[str], expected: str, assertions: list[QAAssertion], screenshot_on_fail: bool, viewport: Optional[str], tags: list[str])`
  - `QAFinding(test_name: str, status: Literal["pass","fail","error","skip"], detail: str, screenshot_path: Optional[str], console_errors: list[str], duration_ms: Optional[int])`
  - `QAReport(summary: str, url: str, findings: list[QAFinding], total: int, passed: int, failed: int, errors: int, skipped: int, duration_ms: Optional[int])`

- [ ] **Step 1: Write failing tests for QA models**

Append to `packages/ai-parrot/tests/bots/test_chrome.py`:

```python
from parrot.bots.chrome import (
    QAAssertion,
    QATestCase,
    QAFinding,
    QAReport,
)


def test_qa_test_case_minimal():
    tc = QATestCase(
        name="login-test",
        url="http://localhost:8080/login",
        steps=["Fill email", "Click submit"],
        expected="Redirect to dashboard",
    )
    assert tc.name == "login-test"
    assert tc.assertions == []
    assert tc.screenshot_on_fail is True
    assert tc.tags == []
    assert tc.viewport is None


def test_qa_test_case_with_assertions():
    tc = QATestCase(
        name="login-validation",
        url="http://localhost:8080/login",
        steps=["Leave email empty", "Click submit"],
        expected="Error shown",
        assertions=[
            QAAssertion(check="element_visible", target=".error-msg"),
            QAAssertion(check="no_console_errors"),
        ],
        viewport="375x812",
        tags=["smoke", "mobile"],
    )
    assert len(tc.assertions) == 2
    assert tc.assertions[0].check == "element_visible"
    assert tc.assertions[1].target is None
    assert tc.viewport == "375x812"


def test_qa_finding_defaults():
    f = QAFinding(
        test_name="login-test",
        status="pass",
        detail="Redirected to /dashboard",
    )
    assert f.screenshot_path is None
    assert f.console_errors == []
    assert f.duration_ms is None


def test_qa_report_counts():
    report = QAReport(
        summary="2 of 3 tests passed",
        url="http://localhost:8080",
        findings=[
            QAFinding(test_name="t1", status="pass", detail="ok"),
            QAFinding(test_name="t2", status="fail", detail="not ok"),
            QAFinding(test_name="t3", status="pass", detail="ok"),
        ],
        total=3,
        passed=2,
        failed=1,
    )
    assert report.total == 3
    assert report.passed == 2
    assert report.failed == 1
    assert report.errors == 0
    assert report.skipped == 0
    assert len(report.findings) == 3


def test_qa_test_case_serialization_roundtrip():
    tc = QATestCase(
        name="test-1",
        url="http://localhost/",
        steps=["Click button"],
        expected="Modal opens",
        assertions=[QAAssertion(check="element_visible", target="#modal")],
    )
    json_str = tc.model_dump_json()
    restored = QATestCase.model_validate_json(json_str)
    assert restored.name == tc.name
    assert restored.assertions[0].target == "#modal"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v -k "qa_"
```

Expected: `ImportError: cannot import name 'QAAssertion' from 'parrot.bots.chrome'`

- [ ] **Step 3: Implement QA models**

Append to `packages/ai-parrot/src/parrot/bots/chrome.py` after `ChromeConfig`:

```python
class QAAssertion(BaseModel):
    """Formal acceptance criterion for a QA test case."""

    check: Literal[
        "element_visible",
        "element_not_visible",
        "text_contains",
        "url_matches",
        "no_console_errors",
        "no_network_failures",
        "screenshot_diff",
        "performance",
    ]
    target: Optional[str] = None
    value: Optional[str] = None


class QATestCase(BaseModel):
    """A QA test case with natural-language steps and optional assertions."""

    name: str
    url: str
    steps: List[str]
    expected: str
    assertions: List[QAAssertion] = []
    screenshot_on_fail: bool = True
    viewport: Optional[str] = None
    tags: List[str] = []


class QAFinding(BaseModel):
    """Result of a single QA test case execution."""

    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: Optional[str] = None
    console_errors: List[str] = []
    duration_ms: Optional[int] = None


class QAReport(BaseModel):
    """Structured QA report — maps to AIMessage.response (summary) + AIMessage.output."""

    summary: str
    url: str
    findings: List[QAFinding] = []
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: Optional[int] = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v -k "qa_"
```

Expected: all 5 QA model tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/chrome.py \
       packages/ai-parrot/tests/bots/test_chrome.py
git commit -m "feat(chrome): add QA models — QAAssertion, QATestCase, QAFinding, QAReport"
```

---

### Task 4: WebAgent class with configure() and run_tests()

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/chrome.py` (append WebAgent class)
- Modify: `packages/ai-parrot/src/parrot/bots/__init__.py` (add re-export)
- Test: `packages/ai-parrot/tests/bots/test_chrome.py` (append)

**Interfaces:**
- Consumes:
  - `ChromeConfig` and `ChromeConfig.to_mcp_args()` from Task 1
  - `QATestCase`, `QAReport` from Task 3
  - `BasicAgent.__init__(name, **kwargs)` at `parrot/bots/agent.py:62`
  - `BasicAgent.configure(app)` at `parrot/bots/agent.py:133`
  - `AbstractBot.ask(question, structured_output, **kwargs) -> AIMessage` at `parrot/bots/abstract.py:4154`
  - `MCPEnabledMixin.add_chrome_devtools_mcp_server(browser_url, headless, ...) -> List[str]` from Task 2
- Produces:
  - `WebAgent(BasicAgent)` with `chrome_config: ChromeConfig`
  - `WebAgent.configure(app) -> None` — calls super then adds MCP server
  - `WebAgent.run_tests(test_cases: list[QATestCase], url: Optional[str]) -> AIMessage`

- [ ] **Step 1: Write failing tests for WebAgent**

Append to `packages/ai-parrot/tests/bots/test_chrome.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parrot.bots.chrome import WebAgent, ChromeConfig, QATestCase, QAReport
from parrot.bots.agent import BasicAgent


def test_web_agent_inherits_basic_agent():
    assert issubclass(WebAgent, BasicAgent)


def test_web_agent_default_chrome_config():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        BasicAgent.__init__(agent, name="WebAgent")
        agent.chrome_config = ChromeConfig()
        assert agent.chrome_config.headless is False
        assert agent.chrome_config.port == 9222


def test_web_agent_custom_chrome_config():
    with patch.object(BasicAgent, "__init__", return_value=None):
        config = ChromeConfig(headless=True, viewport="1920x1080")
        agent = WebAgent.__new__(WebAgent)
        BasicAgent.__init__(agent, name="WebAgent")
        agent.chrome_config = config
        assert agent.chrome_config.headless is True
        assert agent.chrome_config.viewport == "1920x1080"


@pytest.mark.asyncio
async def test_web_agent_configure_adds_mcp_server():
    with patch.object(BasicAgent, "__init__", return_value=None), \
         patch.object(BasicAgent, "configure", new_callable=AsyncMock):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig(headless=True, port=9333)
        agent.logger = MagicMock()
        agent.add_chrome_devtools_mcp_server = AsyncMock(return_value=["click", "fill"])

        await agent.configure()

        agent.add_chrome_devtools_mcp_server.assert_called_once()
        call_kwargs = agent.add_chrome_devtools_mcp_server.call_args
        assert call_kwargs.kwargs.get("headless") is True or \
               call_kwargs[1].get("headless") is True


@pytest.mark.asyncio
async def test_run_tests_calls_ask_with_structured_output():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.logger = MagicMock()

        mock_report = QAReport(
            summary="1/1 passed",
            url="http://localhost:8080",
            total=1,
            passed=1,
        )
        mock_msg = MagicMock()
        mock_msg.output = mock_report
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(
                name="t1",
                url="http://localhost:8080/login",
                steps=["Click submit"],
                expected="Error shown",
            ),
        ]
        result = await agent.run_tests(cases)

        agent.ask.assert_called_once()
        call_kwargs = agent.ask.call_args
        assert call_kwargs.kwargs.get("structured_output") is QAReport
        assert result is mock_msg


@pytest.mark.asyncio
async def test_run_tests_serializes_all_cases_in_prompt():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.logger = MagicMock()
        agent.ask = AsyncMock(return_value=MagicMock())

        cases = [
            QATestCase(name="t1", url="http://a.com", steps=["step1"], expected="ok"),
            QATestCase(name="t2", url="http://b.com", steps=["step2"], expected="ok"),
        ]
        await agent.run_tests(cases)

        prompt = agent.ask.call_args[0][0]  # first positional arg
        assert "t1" in prompt
        assert "t2" in prompt
        assert "step1" in prompt
        assert "step2" in prompt


@pytest.mark.asyncio
async def test_run_tests_uses_explicit_url_param():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.logger = MagicMock()
        agent.ask = AsyncMock(return_value=MagicMock())

        cases = [
            QATestCase(name="t1", url="http://a.com", steps=["s"], expected="ok"),
        ]
        await agent.run_tests(cases, url="http://override.com")

        prompt = agent.ask.call_args[0][0]
        assert "http://override.com" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v -k "web_agent"
```

Expected: `ImportError: cannot import name 'WebAgent' from 'parrot.bots.chrome'`

- [ ] **Step 3: Implement WebAgent**

Append to `packages/ai-parrot/src/parrot/bots/chrome.py`:

```python
import logging
from typing import Union, Type
from ..models import AIMessage
from .agent import BasicAgent


WEB_AGENT_SYSTEM_PROMPT = """\
You are a web interaction agent with access to a Chrome browser via Chrome \
DevTools tools. You can navigate pages, interact with elements, take \
screenshots, inspect console logs, monitor network requests, and analyze \
performance.

When given QA test cases, execute each one methodically:
1. Navigate to the target URL
2. Execute each step using the appropriate browser tools
3. Verify the expected result and any formal assertions
4. Take a screenshot on failure if requested
5. Report findings with pass/fail status and details

When used for general web interaction, follow the user's instructions and \
report what you observe.

Always report console errors and network failures you encounter, even if \
not explicitly asked.\
"""


class WebAgent(BasicAgent):
    """General-purpose web interaction agent via Chrome DevTools MCP."""

    system_prompt_template: str = WEB_AGENT_SYSTEM_PROMPT

    def __init__(
        self,
        name: str = "WebAgent",
        chrome_config: Optional[ChromeConfig] = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.chrome_config = chrome_config or ChromeConfig()
        self.logger = logging.getLogger(f"{self.name}.WebAgent")

    async def configure(self, app=None) -> None:
        """Configure agent and connect Chrome DevTools MCP server."""
        await super().configure(app)
        config = self.chrome_config
        await self.add_chrome_devtools_mcp_server(
            browser_url=config.browser_url
            or f"http://127.0.0.1:{config.port}",
            headless=config.headless,
            user_data_dir=config.user_data_dir,
            channel=config.channel,
            viewport=config.viewport,
            executable_path=config.executable_path,
            isolated=config.isolated,
            no_usage_statistics=config.no_usage_statistics,
            auto_connect=config.auto_connect,
        )

    async def run_tests(
        self,
        test_cases: List[QATestCase],
        url: Optional[str] = None,
    ) -> AIMessage:
        """Execute QA test cases and return a structured QAReport.

        Args:
            test_cases: List of test cases to execute.
            url: Base URL override (defaults to first test case's URL).

        Returns:
            AIMessage with QAReport in .output and summary in .response.
        """
        cases_text = "\n\n".join(
            case.model_dump_json(indent=2) for case in test_cases
        )
        base_url = url or test_cases[0].url
        prompt = (
            f"Execute the following QA test cases against {base_url}.\n"
            f"For each test: navigate to the URL, execute the steps, "
            f"evaluate the expected result and any assertions.\n"
            f"Take a screenshot on failure if screenshot_on_fail is true.\n\n"
            f"Test cases:\n{cases_text}"
        )
        return await self.ask(prompt, structured_output=QAReport)
```

- [ ] **Step 4: Add re-export in bots/__init__.py**

Edit `packages/ai-parrot/src/parrot/bots/__init__.py`:

```python
from .abstract import AbstractBot
from .base import BaseBot
from .basic import BasicBot
from .chatbot import Chatbot
from .agent import Agent, BasicAgent
from .search import WebSearchAgent
from .chrome import WebAgent

__all__ = (
    "AbstractBot",
    "BaseBot",
    "BasicBot",
    "Agent",
    "BasicAgent",
    "Chatbot",
    "WebAgent",
    "WebSearchAgent",
)
```

- [ ] **Step 5: Run all tests to verify they pass**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v
```

Expected: all tests PASS (ChromeConfig + QA models + WebAgent).

- [ ] **Step 6: Run ruff check on all new/modified files**

```bash
source .venv/bin/activate
ruff check packages/ai-parrot/src/parrot/bots/chrome.py \
          packages/ai-parrot/src/parrot/mcp/integration.py \
          packages/ai-parrot-server/src/parrot/mcp/chrome.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/chrome.py \
       packages/ai-parrot/src/parrot/bots/__init__.py \
       packages/ai-parrot/tests/bots/test_chrome.py
git commit -m "feat(chrome): add WebAgent with run_tests() and system prompt"
```

---

### Task 5: Usage example and final validation

**Files:**
- Create: `examples/chrome_qa_test.py`
- Test: full test suite run

**Interfaces:**
- Consumes: `WebAgent`, `ChromeConfig`, `QATestCase`, `QAAssertion` from Tasks 1-4

- [ ] **Step 1: Create usage example**

Create `examples/chrome_qa_test.py`:

```python
"""WebAgent QA testing example.

Usage:
    # Visible Chrome (default):
    python examples/chrome_qa_test.py

    # Headless (CI mode):
    CHROME_HEADLESS=1 python examples/chrome_qa_test.py

    # Custom URL:
    TARGET_URL=http://myapp:3000 python examples/chrome_qa_test.py
"""

import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parrot.bots.chrome import (
    WebAgent,
    ChromeConfig,
    QATestCase,
    QAAssertion,
)

logging.basicConfig(level=logging.INFO)


async def main():
    target = os.getenv("TARGET_URL", "http://localhost:8080")
    headless = os.getenv("CHROME_HEADLESS", "0") == "1"

    agent = WebAgent(
        name="QA-Agent",
        chrome_config=ChromeConfig(
            headless=headless,
            viewport="1920x1080",
            no_usage_statistics=True,
        ),
    )

    test_cases = [
        QATestCase(
            name="homepage-loads",
            url=target,
            steps=["Wait for the page to fully load"],
            expected="Page loads without errors",
            assertions=[
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
            ],
            tags=["smoke"],
        ),
        QATestCase(
            name="login-validation",
            url=f"{target}/login",
            steps=[
                "Leave the email field empty",
                "Type '123' in the password field",
                "Click the submit/login button",
            ],
            expected="Validation errors appear for required fields",
            assertions=[
                QAAssertion(check="url_matches", target="/login"),
                QAAssertion(check="element_visible", target=".error-message"),
            ],
            tags=["regression"],
        ),
    ]

    await agent.configure()
    async with agent:
        result = await agent.run_tests(test_cases, url=target)

    report = result.output
    print(f"\n{'='*60}")
    print(f"QA Report: {report.url}")
    print(f"{'='*60}")
    print(f"Summary: {report.summary}")
    print(f"Total: {report.total} | Passed: {report.passed} | Failed: {report.failed}")
    for finding in report.findings:
        icon = "PASS" if finding.status == "pass" else "FAIL"
        print(f"  [{icon}] {finding.test_name}: {finding.detail}")
        if finding.console_errors:
            for err in finding.console_errors:
                print(f"        Console: {err}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run full test suite**

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/bots/test_chrome.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Verify ruff clean on all files**

```bash
source .venv/bin/activate
ruff check packages/ai-parrot/src/parrot/bots/chrome.py \
          packages/ai-parrot/src/parrot/bots/__init__.py \
          packages/ai-parrot/src/parrot/mcp/integration.py \
          packages/ai-parrot-server/src/parrot/mcp/chrome.py \
          examples/chrome_qa_test.py
```

- [ ] **Step 4: Commit**

```bash
git add examples/chrome_qa_test.py
git commit -m "docs(chrome): add WebAgent QA testing example"
```
