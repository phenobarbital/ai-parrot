"""WebAgent — browser interaction via Chrome DevTools MCP."""

from typing import Literal

from pydantic import BaseModel, Field


class ChromeConfig(BaseModel):
    """Configuration for the `chrome-devtools-mcp` server.

    Captures the subset of `chrome-devtools-mcp` CLI flags AI-Parrot's
    WebAgent needs to launch or attach to a Chrome instance, and renders
    them as the argument list consumed by `npx chrome-devtools-mcp@latest`.

    Attributes:
        browser_url: Existing browser debugging endpoint to attach to
            (e.g. `http://127.0.0.1:9333`). When set, chrome-devtools-mcp
            connects instead of launching a new browser.
        headless: Whether to launch Chrome without a visible window.
            Defaults to `False` so WebAgent sessions are visible by
            default; callers that want a headless session must opt in.
        user_data_dir: Path to a Chrome user data directory to reuse
            (profile, cookies, extensions).
        channel: Chrome release channel to launch, one of `stable`,
            `beta`, `dev`, or `canary`.
        viewport: Initial viewport size as `"<width>x<height>"`
            (e.g. `"1920x1080"`).
        executable_path: Explicit path to the Chrome/Chromium binary to
            launch, overriding auto-detection.
        isolated: Whether to use an isolated (incognito-like) browser
            context instead of the persistent profile.
        no_usage_statistics: Whether to disable chrome-devtools-mcp's
            usage statistics reporting. Defaults to `True`.
        auto_connect: Whether to auto-connect to an already-running
            Chrome instance instead of launching a new one.
        port: Remote debugging port Chrome listens on. Defaults to
            `9222`.
    """

    browser_url: str | None = None
    headless: bool = False
    user_data_dir: str | None = None
    channel: Literal["stable", "beta", "dev", "canary"] | None = None
    viewport: str | None = None
    executable_path: str | None = None
    isolated: bool = False
    no_usage_statistics: bool = True
    auto_connect: bool = False
    port: int = Field(default=9222, ge=1, le=65535)

    def to_mcp_args(self) -> list[str]:
        """Build the argument list for `npx chrome-devtools-mcp@latest`.

        Returns:
            list[str]: CLI arguments, starting with the `npx` invocation
            flags (`-y chrome-devtools-mcp@latest`) followed by one flag
            per configured option. Falsy/`None` fields are omitted.
        """
        args: list[str] = ["-y", "chrome-devtools-mcp@latest"]
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
    target: str | None = None
    value: str | None = None


class QATestCase(BaseModel):
    """A QA test case with natural-language steps and optional assertions."""

    name: str
    url: str
    steps: list[str]
    expected: str
    assertions: list[QAAssertion] = []
    screenshot_on_fail: bool = True
    viewport: str | None = None
    tags: list[str] = []


class QAFinding(BaseModel):
    """Result of a single QA test case execution."""

    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: str | None = None
    console_errors: list[str] = []
    duration_ms: int | None = None


class QAReport(BaseModel):
    """Structured QA report — maps to AIMessage.response (summary) + AIMessage.output."""

    summary: str
    url: str
    findings: list[QAFinding] = []
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: int | None = None
