import asyncio
import xml.etree.ElementTree as ET
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
from pydantic import ValidationError


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


def test_web_agent_uses_system_prompt_template():
    """Verify WEB_AGENT_SYSTEM_PROMPT is actually used (not overridden by PromptBuilder)."""
    agent = WebAgent(name="test-agent")
    assert agent._prompt_builder is None


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
    """TASK-2117: run_tests() now processes one case at a time, so each
    ask() call uses structured_output=QAFinding (not QAReport); the
    aggregate QAReport is built in Python and returned in a fresh
    AIMessage, not passed through directly."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        mock_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = mock_finding
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
        assert call_kwargs.kwargs.get("structured_output") is QAFinding
        assert isinstance(result.output, QAReport)
        assert result.output.total == 1
        assert result.output.passed == 1


@pytest.mark.asyncio
async def test_run_tests_serializes_case_in_its_own_prompt():
    """TASK-2117: each case gets its own ask() call/prompt (no longer a
    single combined prompt for all cases)."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        mock_msg = MagicMock()
        mock_msg.output = QAFinding(test_name="x", status="pass", detail="ok")
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="http://a.com", steps=["step1"], expected="ok"),
            QATestCase(name="t2", url="http://b.com", steps=["step2"], expected="ok"),
        ]
        await agent.run_tests(cases)

        assert agent.ask.call_count == 2
        prompt1 = agent.ask.call_args_list[0][0][0]
        prompt2 = agent.ask.call_args_list[1][0][0]
        assert "t1" in prompt1 and "step1" in prompt1
        assert "t1" not in prompt2 or "step2" not in prompt1
        assert "t2" in prompt2 and "step2" in prompt2


@pytest.mark.asyncio
async def test_run_tests_uses_explicit_url_param():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "WebAgent"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()
        mock_msg = MagicMock()
        mock_msg.output = QAFinding(test_name="t1", status="pass", detail="ok")
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="http://a.com", steps=["s"], expected="ok"),
        ]
        await agent.run_tests(cases, url="http://override.com")

        prompt = agent.ask.call_args[0][0]
        assert "http://override.com" in prompt


# --- TASK-2115: QA Model Enhancements ---


def test_qa_assertion_wait_timeout_default():
    a = QAAssertion(check="element_visible")
    assert a.wait_timeout_ms == 5000


def test_qa_assertion_wait_timeout_custom():
    a = QAAssertion(check="element_visible", wait_timeout_ms=3000)
    assert a.wait_timeout_ms == 3000


def test_qa_assertion_wait_timeout_zero():
    a = QAAssertion(check="element_visible", wait_timeout_ms=0)
    assert a.wait_timeout_ms == 0


def test_qa_assertion_response_status():
    a = QAAssertion(check="response_status", target="200")
    assert a.check == "response_status"


def test_qa_assertion_accessibility_check():
    a = QAAssertion(check="accessibility_check")
    assert a.check == "accessibility_check"


def test_qa_assertion_check_is_required():
    with pytest.raises(ValidationError):
        QAAssertion()


def test_qa_test_case_max_retries_default():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e")
    assert tc.max_retries == 0


def test_qa_test_case_max_retries_custom():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e", max_retries=3)
    assert tc.max_retries == 3


def test_qa_test_case_timeout_ms_default():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e")
    assert tc.timeout_ms is None


def test_qa_test_case_timeout_ms_custom():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e", timeout_ms=30000)
    assert tc.timeout_ms == 30000


def test_qa_test_case_timeout_ms_minimum():
    with pytest.raises(ValidationError):
        QATestCase(name="t", url="/", steps=["s"], expected="e", timeout_ms=500)


def test_qa_finding_retries_default():
    f = QAFinding(test_name="t", status="pass", detail="ok")
    assert f.retries == 0


def test_qa_finding_retries_custom():
    f = QAFinding(test_name="t", status="fail", detail="nok", retries=2)
    assert f.retries == 2


def test_new_fields_serialization_roundtrip():
    tc = QATestCase(
        name="t", url="/", steps=["s"], expected="e",
        max_retries=2, timeout_ms=15000,
        assertions=[
            QAAssertion(check="response_status", target="200", wait_timeout_ms=3000)
        ],
    )
    restored = QATestCase.model_validate_json(tc.model_dump_json())
    assert restored.max_retries == 2
    assert restored.timeout_ms == 15000
    assert restored.assertions[0].wait_timeout_ms == 3000
    assert restored.assertions[0].check == "response_status"


# --- TASK-2116: JUnit XML Serialization & Exit Code ---


def test_qa_report_exit_code_all_pass():
    r = QAReport(summary="ok", url="/", total=3, passed=3)
    assert r.exit_code == 0


def test_qa_report_exit_code_with_failure():
    r = QAReport(summary="nok", url="/", total=3, passed=2, failed=1)
    assert r.exit_code == 1


def test_qa_report_exit_code_with_error():
    r = QAReport(summary="err", url="/", total=3, passed=2, errors=1)
    assert r.exit_code == 1


def test_qa_report_exit_code_empty():
    r = QAReport(summary="empty", url="/")
    assert r.exit_code == 0


def test_to_junit_xml_well_formed():
    r = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    xml_str = r.to_junit_xml()
    assert xml_str.startswith("<?xml")
    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"


def test_to_junit_xml_pass_no_children():
    r = QAReport(
        summary="ok", url="/",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok", duration_ms=2100)],
        total=1, passed=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    tc = root.find(".//testcase[@name='t1']")
    assert tc is not None
    assert len(tc) == 0  # no child elements
    assert float(tc.get("time", "0")) == pytest.approx(2.1, abs=0.01)


def test_to_junit_xml_failure_with_console_errors():
    r = QAReport(
        summary="nok", url="/",
        findings=[QAFinding(
            test_name="t1", status="fail", detail="broken",
            console_errors=["TypeError: x is undefined"],
            retries=2,
        )],
        total=1, failed=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    failure = root.find(".//testcase/failure")
    assert failure is not None
    assert "broken" in (failure.text or "")
    assert "TypeError" in (failure.text or "")
    assert "Retries: 2" in (failure.text or "")


def test_to_junit_xml_error_status():
    r = QAReport(
        summary="err", url="/",
        findings=[QAFinding(test_name="t1", status="error", detail="timed out")],
        total=1, errors=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    error = root.find(".//testcase/error")
    assert error is not None


def test_to_junit_xml_skipped_status():
    r = QAReport(
        summary="skip", url="/",
        findings=[QAFinding(test_name="t1", status="skip", detail="filtered")],
        total=1, skipped=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    skipped = root.find(".//testcase/skipped")
    assert skipped is not None


def test_to_junit_xml_suite_attributes():
    r = QAReport(
        summary="2/3", url="/",
        findings=[
            QAFinding(test_name="t1", status="pass", detail="ok"),
            QAFinding(test_name="t2", status="fail", detail="nok"),
            QAFinding(test_name="t3", status="skip", detail="filtered"),
        ],
        total=3, passed=1, failed=1, skipped=1, duration_ms=5000,
    )
    root = ET.fromstring(r.to_junit_xml())
    suite = root.find("testsuite")
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "1"
    assert suite.get("skipped") == "1"


# --- TASK-2117: WebAgent run_tests Enhancements ---


def test_web_agent_default_timeout_ms():
    agent = WebAgent(name="test")
    assert agent.default_timeout_ms == 60_000


def test_web_agent_custom_timeout_ms():
    agent = WebAgent(name="test", default_timeout_ms=30_000)
    assert agent.default_timeout_ms == 30_000


def test_web_agent_screenshot_dir_default():
    agent = WebAgent(name="test")
    assert agent.screenshot_dir is None


def test_web_agent_screenshot_dir_custom():
    agent = WebAgent(name="test", screenshot_dir="/tmp/screenshots")
    assert agent.screenshot_dir == "/tmp/screenshots"


@pytest.mark.asyncio
async def test_run_tests_tag_filtering():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["smoke"]),
            QATestCase(name="t2", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        result = await agent.run_tests(cases, tags=["smoke"])
        report = result.output

        assert report.total == 2
        assert report.skipped == 1
        # Only one ask() call (the smoke test), not two
        assert agent.ask.call_count == 1


@pytest.mark.asyncio
async def test_run_tests_empty_after_tag_filtering():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()
        agent.ask = AsyncMock()

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        result = await agent.run_tests(cases, tags=["smoke"])
        report = result.output

        assert report.total == 1
        assert report.skipped == 1
        assert report.passed == 0
        agent.ask.assert_not_called()


@pytest.mark.asyncio
async def test_run_tests_no_tags_runs_all():
    """Backward compatibility: no tags filter runs everything."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["smoke"]),
            QATestCase(name="t2", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        await agent.run_tests(cases)

        assert agent.ask.call_count == 2


@pytest.mark.asyncio
async def test_run_tests_screenshot_dir_in_prompt():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = "/tmp/qa-screenshots"
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [QATestCase(name="t1", url="/", steps=["s"], expected="e")]
        await agent.run_tests(cases)

        prompt = agent.ask.call_args[0][0]
        assert "/tmp/qa-screenshots" in prompt


@pytest.mark.asyncio
async def test_run_tests_retry_on_failure():
    """max_retries=2 -> ask() called up to 1 + 2 = 3 times for a failing case."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        fail_finding = QAFinding(test_name="t1", status="fail", detail="nok")
        mock_msg = MagicMock()
        mock_msg.output = fail_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", max_retries=2),
        ]
        result = await agent.run_tests(cases)

        assert agent.ask.call_count == 3
        finding = result.output.findings[0]
        assert finding.status == "fail"
        assert finding.retries == 2


@pytest.mark.asyncio
async def test_run_tests_retry_stops_on_first_pass():
    """A test that passes on the first attempt should not be retried."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", max_retries=2),
        ]
        result = await agent.run_tests(cases)

        assert agent.ask.call_count == 1
        assert result.output.findings[0].retries == 0


@pytest.mark.asyncio
async def test_run_tests_timeout_marks_error():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        async def slow_ask(*args, **kwargs):
            await asyncio.sleep(0.2)
            mock_msg = MagicMock()
            mock_msg.output = QAFinding(test_name="t1", status="pass", detail="ok")
            return mock_msg

        agent.ask = slow_ask

        cases = [
            QATestCase(
                name="t1", url="/", steps=["s"], expected="e", timeout_ms=1000,
            ),
        ]
        # Bypass the ge=1000 minimum (Pydantic doesn't re-validate plain
        # attribute assignment) so the real asyncio.wait_for actually
        # fires within the test's timeframe — avoids mocking wait_for
        # itself, which would leave the wrapped coroutine unawaited.
        cases[0].timeout_ms = 50
        result = await agent.run_tests(cases)

        finding = result.output.findings[0]
        assert finding.status == "error"
        assert "timed out" in finding.detail.lower()


@pytest.mark.asyncio
async def test_run_tests_wait_timeout_ms_in_prompt():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        mock_msg = MagicMock()
        mock_msg.output = QAFinding(test_name="t1", status="pass", detail="ok")
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(
                name="t1", url="/", steps=["s"], expected="e",
                assertions=[
                    QAAssertion(
                        check="element_visible", target=".error", wait_timeout_ms=3000,
                    ),
                ],
            ),
        ]
        await agent.run_tests(cases)

        prompt = agent.ask.call_args[0][0]
        assert "3000" in prompt
        assert ".error" in prompt


def test_web_agent_system_prompt_documents_new_assertions():
    from parrot.bots.chrome import WEB_AGENT_SYSTEM_PROMPT
    assert "response_status" in WEB_AGENT_SYSTEM_PROMPT
    assert "accessibility_check" in WEB_AGENT_SYSTEM_PROMPT
    assert "wait_timeout_ms" in WEB_AGENT_SYSTEM_PROMPT
