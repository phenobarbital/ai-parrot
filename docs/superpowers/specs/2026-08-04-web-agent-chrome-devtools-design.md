# WebAgent — Chrome DevTools MCP Integration

**Date**: 2026-08-04
**Status**: Approved
**Author**: Jesus Lara + Claude

## Summary

General-purpose web interaction agent (`WebAgent`) that integrates Chrome DevTools
MCP server for browser automation, QA testing, scraping, and monitoring. Designed
as `WebAgent(BasicAgent)` in `parrot/bots/chrome.py`. First use case: interactive
QA of the AI-Parrot web UI.

## Architecture

```
WebAgent(BasicAgent)
    │
    ├── ChromeConfig (Pydantic)      → parametrizes chrome-devtools-mcp
    │
    ├── configure()                  → launches MCP server via ChromeConfig
    │    └── add_chrome_devtools_mcp_server(**config)
    │
    ├── ask(prompt)                  → free-form web interaction
    │    └── returns AIMessage (text)
    │
    ├── ask(prompt, structured_output=QAReport)  → with structured report
    │    └── returns AIMessage + QAReport in .output
    │
    └── run_tests([QATestCase, ...]) → QA convenience method
         ├── serializes test cases into prompt
         ├── auto-sets structured_output=QAReport
         └── returns AIMessage + QAReport
```

## ChromeConfig

Pydantic model that parametrizes all chrome-devtools-mcp server options.
Default: visible (no-headless), telemetry disabled.

```python
class ChromeConfig(BaseModel):
    browser_url: Optional[str] = None        # connect to existing Chrome
    headless: bool = False                    # visible by default
    user_data_dir: Optional[str] = None      # local Chrome profile
    channel: Optional[Literal["stable", "beta", "dev", "canary"]] = None
    viewport: Optional[str] = None           # "1280x720"
    executable_path: Optional[str] = None    # custom Chrome binary
    isolated: bool = False                   # temporary profile
    no_usage_statistics: bool = True         # opt-out Google telemetry
    auto_connect: bool = False               # Chrome 144+ remote debugging
    port: int = 9222                         # debugging port

    def to_mcp_args(self) -> list[str]:
        """Generate args list for npx chrome-devtools-mcp."""
        ...
```

## QA Models

### Input

```python
class QAAssertion(BaseModel):
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
    target: Optional[str] = None   # selector, text, URL pattern, metric
    value: Optional[str] = None    # threshold, baseline path, etc.

class QATestCase(BaseModel):
    name: str
    url: str
    steps: list[str]                         # natural language
    expected: str                            # free-form expected result
    assertions: list[QAAssertion] = []       # formal checks (optional)
    screenshot_on_fail: bool = True
    viewport: Optional[str] = None
    tags: list[str] = []
```

### Output

```python
class QAFinding(BaseModel):
    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: Optional[str] = None
    console_errors: list[str] = []
    duration_ms: Optional[int] = None

class QAReport(BaseModel):
    summary: str                     # maps to AIMessage.response
    url: str
    findings: list[QAFinding] = []
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: Optional[int] = None
```

### Output routing

| Caller passes | WebAgent uses | Output |
|---|---|---|
| Only prompt | Nothing (free text) | `msg.response` = text |
| `structured_output=QAReport` | QAReport | `msg.response` + `msg.output` |
| `test_cases=[...]` via `run_tests()` | QAReport automatic | `msg.response` + `msg.output` |
| `structured_output=ScrapingResult` | ScrapingResult | `msg.response` + `msg.output` |

Future output types (ScrapingResult, MonitoringSnapshot) require only a new
Pydantic model — no changes to WebAgent.

## WebAgent Class

```python
class WebAgent(BasicAgent):
    chrome_config: ChromeConfig = ChromeConfig()

    def __init__(self, name="WebAgent", chrome_config=None, **kwargs):
        super().__init__(name=name, **kwargs)
        if chrome_config:
            self.chrome_config = chrome_config

    async def configure(self, app=None) -> None:
        await super().configure(app)
        await self.add_chrome_devtools_mcp_server(
            browser_url=self.chrome_config.browser_url
                or f"http://127.0.0.1:{self.chrome_config.port}",
            args_override=self.chrome_config.to_mcp_args(),
        )

    async def run_tests(self, test_cases, url=None) -> AIMessage:
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

### System Prompt

Generic web interaction prompt — QA instructions come via user prompt in
`run_tests()`, not baked into the system prompt:

```
You are a web interaction agent with access to a Chrome browser via Chrome
DevTools tools. You can navigate pages, interact with elements, take
screenshots, inspect console logs, monitor network requests, and analyze
performance.

When given QA test cases, execute each one methodically:
1. Navigate to the target URL
2. Execute each step using the appropriate browser tools
3. Verify the expected result and any formal assertions
4. Take a screenshot on failure if requested
5. Report findings with pass/fail status and details

When used for general web interaction, follow the user's instructions and
report what you observe.

Always report console errors and network failures you encounter, even if
not explicitly asked.
```

## Changes to Existing Code

| File | Change |
|---|---|
| `parrot/mcp/integration.py` | `create_chrome_devtools_mcp_server()` accepts `headless`, `user_data_dir`, `channel`, `viewport`, `executable_path`, `isolated`, `no_usage_statistics`, `auto_connect` and builds args from them |
| `parrot/mcp/integration.py` | `MCPEnabledMixin.add_chrome_devtools_mcp_server()` forwards new params + accepts `args_override` |
| `parrot-server/parrot/mcp/chrome.py` | `ChromeManager.start()` accepts `headless: bool = True` — omits `--headless=new` when `False` |
| `parrot/bots/__init__.py` | Re-export `WebAgent` |

### Not touched

- `BasicAgent` — inherited as-is
- `MCPClient` / transports — chrome-devtools-mcp is stdio, already supported
- WebScrapingToolkit DSL — future follow-up for structured step DSL

## Usage Examples

### Free-form interaction

```python
agent = WebAgent(
    chrome_config=ChromeConfig(headless=False, viewport="1920x1080")
)
await agent.configure()
async with agent:
    msg = await agent.ask("Navigate to http://localhost:8080 and describe the UI")
```

### QA with test cases

```python
agent = WebAgent(
    chrome_config=ChromeConfig(headless=True)  # CI mode
)
await agent.configure()
async with agent:
    report = await agent.run_tests([
        QATestCase(
            name="login-happy",
            url="http://localhost:8080/login",
            steps=["Fill email 'admin@test.com'", "Fill password 'secret'", "Click submit"],
            expected="Redirect to /dashboard",
            assertions=[
                QAAssertion(check="url_matches", target="/dashboard"),
                QAAssertion(check="no_console_errors"),
            ],
        ),
    ])
    print(report.output.summary)
    print(f"{report.output.passed}/{report.output.total} passed")
```

### Connect to existing Chrome with local profile

```python
agent = WebAgent(
    chrome_config=ChromeConfig(
        browser_url="http://127.0.0.1:9222",
        user_data_dir="~/.config/google-chrome",
    )
)
```

## Test Plan

Unit tests in `packages/ai-parrot/tests/bots/test_chrome.py`:

- `test_web_agent_inherits_basic_agent`
- `test_chrome_config_defaults`
- `test_chrome_config_to_mcp_args_headless`
- `test_chrome_config_to_mcp_args_full`
- `test_chrome_config_to_mcp_args_no_headless_omits_flag`
- `test_qa_test_case_minimal`
- `test_qa_test_case_with_assertions`
- `test_qa_report_counts`
- `test_web_agent_configure_adds_mcp_server` (async, mocked MCP)
- `test_run_tests_calls_ask_with_structured_output` (async, mocked)
- `test_run_tests_serializes_all_cases_in_prompt` (async, mocked)

## Future Follow-ups

- WebScrapingToolkit DSL integration for structured steps
- ScrapingResult / MonitoringSnapshot output models
- Visual regression baseline management (screenshot_diff assertion)
- CI integration recipe (headless + report artifact)
