"""WebAgent — browser interaction via Chrome DevTools MCP."""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Literal

from pydantic import BaseModel, Field

from ..models import AIMessage, CompletionUsage
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

    @property
    def exit_code(self) -> int:
        """Return 0 if all tests passed, 1 if any failure or error occurred.

        Returns:
            int: `0` when `failed + errors == 0`, otherwise `1`. Intended
            to be used directly as a CI process exit code.
        """
        return 1 if (self.failed + self.errors) > 0 else 0

    def to_junit_xml(self, suite_name: str = "WebAgent QA") -> str:
        """Serialize this report to a JUnit XML document.

        Uses only `xml.etree.ElementTree` (stdlib) to build a
        `<testsuites><testsuite>...</testsuite></testsuites>` document
        compatible with CircleCI, GitHub Actions, GitLab CI, and Jenkins
        JUnit parsers.

        Args:
            suite_name: Name reported for the `<testsuite>` element and
                used as the `classname` attribute on each `<testcase>`.

        Returns:
            str: The complete XML document (including the XML
            declaration) as a string.
        """
        testsuites = ET.Element("testsuites")
        total_time = (self.duration_ms or 0) / 1000
        testsuite = ET.SubElement(
            testsuites,
            "testsuite",
            {
                "name": suite_name,
                "tests": str(self.total),
                "failures": str(self.failed),
                "errors": str(self.errors),
                "skipped": str(self.skipped),
                "time": str(total_time),
            },
        )
        for finding in self.findings:
            time_s = (finding.duration_ms or 0) / 1000
            testcase = ET.SubElement(
                testsuite,
                "testcase",
                {
                    "name": finding.test_name,
                    "classname": suite_name,
                    "time": str(time_s),
                },
            )
            if finding.status == "fail":
                failure = ET.SubElement(
                    testcase, "failure", {"message": finding.detail}
                )
                failure.text = self._junit_detail_body(finding)
            elif finding.status == "error":
                error = ET.SubElement(
                    testcase, "error", {"message": finding.detail}
                )
                error.text = self._junit_detail_body(finding)
            elif finding.status == "skip":
                ET.SubElement(testcase, "skipped", {"message": finding.detail})
            # "pass" -> no child element

        return ET.tostring(
            testsuites, encoding="unicode", xml_declaration=True
        )

    @staticmethod
    def _junit_detail_body(finding: "QAFinding") -> str:
        """Build the failure/error text body for a `QAFinding`.

        Args:
            finding: The finding to render (status must be "fail" or
                "error").

        Returns:
            str: Multi-line body with detail, console errors (if any),
            and retry count (if > 0).
        """
        lines = [f"Detail: {finding.detail}"]
        if finding.console_errors:
            lines.append("Console errors:")
            lines.extend(f"- {err}" for err in finding.console_errors)
        if finding.retries > 0:
            lines.append(f"Retries: {finding.retries}")
        return "\n" + "\n".join(lines) + "\n"


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

Assertion types you support:
- element_visible: Check if a CSS selector is visible on the page. Respect \
  the wait_timeout_ms — wait up to that many milliseconds before declaring \
  the element not found.
- element_not_visible: Inverse of element_visible.
- text_contains: Check if the page contains the specified text.
- url_matches: Check the current URL matches the target pattern.
- no_console_errors: Verify no JavaScript errors in the console.
- no_network_failures: Verify no failed network requests (4xx/5xx).
- response_status: Verify the HTTP response status code matches the target \
  value.
- accessibility_check: Perform basic accessibility validation — check for \
  ARIA roles, alt text on images, and proper heading hierarchy.
- screenshot_diff: (placeholder — not yet implemented)
- performance: Check performance metrics against thresholds.

When an assertion has a wait_timeout_ms value, wait up to that many \
milliseconds for the condition to become true before reporting failure.

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
        default_timeout_ms: int = 60_000,
        screenshot_dir: str | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        # WebAgent uses its own legacy system_prompt_template (see ProductReport
        # for the same pattern): BasicAgent.__init__ defaults to the composable
        # PromptBuilder whenever no explicit system_prompt is given, which would
        # silently discard WEB_AGENT_SYSTEM_PROMPT. Force the legacy path.
        self._prompt_builder = None
        self.chrome_config = chrome_config or ChromeConfig()
        self.default_timeout_ms = default_timeout_ms
        self.screenshot_dir = screenshot_dir
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
        tags: list[str] | None = None,
    ) -> AIMessage:
        """Execute QA test cases and return a structured QAReport.

        Each test case is executed individually (one `ask()` call per
        case) so that per-test retry and timeout can be applied. Cases
        that don't match `tags` (when provided) are reported as
        `status="skip"` without calling the LLM.

        Args:
            test_cases: List of test cases to execute.
            url: Base URL override (defaults to first test case's URL).
            tags: Optional tag filter — only test cases whose `tags`
                intersect this list are executed. `None` runs all cases.

        Returns:
            AIMessage with the aggregate QAReport in `.output` and the
            summary in `.response`.
        """
        base_url = url or (test_cases[0].url if test_cases else "")
        findings: list[QAFinding] = []

        for case in test_cases:
            if tags and not set(tags).intersection(case.tags):
                findings.append(
                    QAFinding(
                        test_name=case.name,
                        status="skip",
                        detail="Filtered by tags",
                    )
                )
                continue

            finding: QAFinding | None = None
            for attempt in range(1 + case.max_retries):
                timeout_ms = case.timeout_ms or self.default_timeout_ms
                timeout_s = timeout_ms / 1000
                try:
                    finding = await asyncio.wait_for(
                        self._execute_single_test(case, base_url),
                        timeout=timeout_s,
                    )
                except TimeoutError:
                    finding = QAFinding(
                        test_name=case.name,
                        status="error",
                        detail=f"Test timed out after {timeout_ms}ms",
                    )
                except Exception as exc:
                    # CI reliability: a single failing test case (LLM/MCP/
                    # network error) must not abort the whole suite (see
                    # spec Motivation: "a single network glitch... causing
                    # false negatives").
                    self.logger.exception(
                        "QA test case %r raised an unexpected error", case.name
                    )
                    finding = QAFinding(
                        test_name=case.name,
                        status="error",
                        detail=f"Unexpected error: {exc}",
                    )
                finding.retries = attempt
                if finding.status == "pass":
                    break
            findings.append(finding)

        report = QAReport(
            summary=(
                f"{sum(1 for f in findings if f.status == 'pass')}/"
                f"{len(findings)} passed"
            ),
            url=base_url,
            findings=findings,
            total=len(findings),
            passed=sum(1 for f in findings if f.status == "pass"),
            failed=sum(1 for f in findings if f.status == "fail"),
            errors=sum(1 for f in findings if f.status == "error"),
            skipped=sum(1 for f in findings if f.status == "skip"),
        )
        return AIMessage(
            input=f"Execute {len(test_cases)} QA test case(s) against {base_url}",
            output=report,
            response=report.summary,
            model="",
            provider="",
            usage=CompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
        )

    async def _execute_single_test(
        self,
        case: QATestCase,
        base_url: str,
    ) -> QAFinding:
        """Execute a single QA test case and return its finding.

        Args:
            case: The test case to execute.
            base_url: Base URL to report in the prompt (test cases may
                have their own `url`, but `base_url` reflects the
                `run_tests()`-level override).

        Returns:
            QAFinding: The structured result of executing this test case.
        """
        prompt = (
            f"Execute the following QA test case against {base_url}.\n"
            f"Navigate to the URL, execute the steps, evaluate the "
            f"expected result and any assertions.\n"
            f"Take a screenshot on failure if screenshot_on_fail is true.\n"
        )
        if self.screenshot_dir:
            timestamp = int(time.time())
            screenshot_path = f"{self.screenshot_dir}/{case.name}_{timestamp}.png"
            prompt += (
                f"On failure, save the screenshot to exactly this path: "
                f"{screenshot_path}\n"
                f"Report this exact path in the finding's screenshot_path "
                f"field.\n"
            )
        for assertion in case.assertions:
            if assertion.wait_timeout_ms and assertion.check in (
                "element_visible",
                "element_not_visible",
                "text_contains",
            ):
                prompt += (
                    f"For '{assertion.check}' on '{assertion.target}': "
                    f"wait up to {assertion.wait_timeout_ms}ms.\n"
                )
        prompt += f"\nTest case:\n{case.model_dump_json(indent=2)}"

        result = await self.ask(prompt, structured_output=QAFinding)
        return result.output
