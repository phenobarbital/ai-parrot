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
