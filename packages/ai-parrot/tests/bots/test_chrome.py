from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.bots.agent import BasicAgent
from parrot.bots.chrome import (
    ChromeConfig,
    QAAssertion,
    QAFinding,
    QAReport,
    QATestCase,
    WebAgent,
)
from parrot.mcp.integration import create_chrome_devtools_mcp_server


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
