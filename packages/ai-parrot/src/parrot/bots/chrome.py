"""WebAgent — browser interaction via Chrome DevTools MCP."""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from ..models import AIMessage
from .agent import BasicAgent


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
        "response_status",
        "accessibility_check",
    ]
    target: str | None = None
    value: str | None = None
    wait_timeout_ms: int = Field(
        default=5000,
        ge=0,
        description="Max wait for element-based checks before asserting",
    )


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
    max_retries: int = Field(
        default=0,
        ge=0,
        description="Retry failed test up to N times before final failure",
    )
    timeout_ms: int | None = Field(
        default=None,
        ge=1000,
        description="Per-test timeout in ms; None -> use agent default",
    )


class QAFinding(BaseModel):
    """Result of a single QA test case execution."""

    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: str | None = None
    console_errors: list[str] = []
    duration_ms: int | None = None
    retries: int = 0


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
        chrome_config: ChromeConfig | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        # WebAgent uses its own legacy system_prompt_template (see ProductReport
        # for the same pattern): BasicAgent.__init__ defaults to the composable
        # PromptBuilder whenever no explicit system_prompt is given, which would
        # silently discard WEB_AGENT_SYSTEM_PROMPT. Force the legacy path.
        self._prompt_builder = None
        self.chrome_config = chrome_config or ChromeConfig()
        self.logger = logging.getLogger(f"{self.name}.WebAgent")

    async def configure(self, app=None) -> None:
        """Configure agent and connect Chrome DevTools MCP server.

        Args:
            app: Optional application/framework context, forwarded to
                ``BasicAgent.configure()``.
        """
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
        test_cases: list[QATestCase],
        url: str | None = None,
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
