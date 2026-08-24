---
id: F004
query_id: Q002
type: read
intent: Find the selenium/playwright driver abstraction and the Chrome DevTools MCP integration path
executed_at: 2026-08-23T09:25:00Z
depth: 0
parent_id: null
---

# F004 — Both driver backends and a working Chrome DevTools MCP agent already exist

## Summary

`AbstractDriver` defines a 27-method browser surface (navigate, click, fill,
select_option, hover, press_key, wait_for_selector, screenshot, execute_script,
intercept_requests, record_har, save_pdf, tracing, mock_route). Playwright and
Selenium both implement it; `DriverFactory` + `driver_context` handle
construction and lifecycle. Separately, `WebAgent(BasicAgent)` in
`parrot/bots/chrome.py` is a fully-built agent that connects the
`chrome-devtools-mcp` npx server through `add_chrome_devtools_mcp_server()`,
parameterized by a `ChromeConfig` Pydantic model — so the second automation
channel the source names is not hypothetical either.

Notably `AbstractDriver.save_pdf()` exists — relevant for pulling issued
invoices out of Hooba as PDFs.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
  lines: 37-337
  symbol: `AbstractDriver`
  excerpt: |
    async def navigate/go_back/go_forward/reload/click/fill/select_option
    async def hover/press_key/get_page_source/get_text/get_attribute
    async def screenshot/wait_for_selector/wait_for_navigation/execute_script
    async def intercept_requests/record_har/save_pdf/start_tracing/mock_route

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/`
  lines: 1-1
  symbol: "driver implementations"
  excerpt: |
    abstract.py  page_driver.py  playwright_config.py
    playwright_driver.py  selenium_driver.py

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
  lines: 1-1
  symbol: `DriverFactory`

- path: `packages/ai-parrot/src/parrot/bots/chrome.py`
  lines: 290-334
  symbol: `WebAgent.configure`
  excerpt: |
    class WebAgent(BasicAgent):
        """General-purpose web interaction agent via Chrome DevTools MCP."""
        async def configure(self, app=None) -> None:
            await super().configure(app)
            await self.add_chrome_devtools_mcp_server(
                browser_url=config.browser_url or f"http://127.0.0.1:{config.port}",
                headless=config.headless, user_data_dir=config.user_data_dir, ...)

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1105-1145, 1476
  symbol: `create_chrome_devtools_mcp_server`, `add_chrome_devtools_mcp_server`

- path: `docs/superpowers/specs/2026-08-04-web-agent-chrome-devtools-design.md`
  lines: 1-35
  symbol: "WebAgent design (Status: Approved)"

## Notes

`ChromeConfig.user_data_dir` means an authenticated Hooba Chrome profile can be
reused across runs — a cookie-jar alternative to replaying `authenticate` each
session. Note `.mcp.json` in this repo registers only `wikitoolkit`; the Chrome
DevTools MCP server is launched by the agent at runtime via npx, not declared there.
