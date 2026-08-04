from parrot.bots.chrome import (
    ChromeConfig,
    QAAssertion,
    QAFinding,
    QAReport,
    QATestCase,
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
