---
id: F009
query_id: Q008
type: comparison
intent: Determine whether Selenium Python can drive Obscura
executed_at: 2026-09-05T14:10:00Z
depth: 1
parent_id: F001
---

# F009 — Selenium can use CDP features, but cannot directly drive an arbitrary Obscura CDP endpoint

## Summary

Selenium WebDriver is based on the W3C WebDriver protocol and its Python Chromium binding exposes `debugger_address` as a ChromeOptions capability for ChromeDriver sessions. Selenium 4 also exposes CDP commands inside an established WebDriver session, but its documentation describes that CDP support as browser/version dependent and temporary while WebDriver BiDi matures. Obscura documents CDP and Playwright/Puppeteer connections, but the reviewed upstream material does not document a W3C WebDriver server or a Selenium/ChromeDriver integration.

## Citations

- path: `https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_chromium/selenium.webdriver.chromium.options.html`
  lines: `ChromiumOptions.debugger_address` API reference (accessed 2026-09-05)
  symbol: `ChromiumOptions.debugger_address`
  excerpt: |
    Selenium defines debugger_address as the address of the remote devtools
    instance in ChromeOptions. This capability is consumed by ChromeDriver;
    it is not a generic Selenium client for any CDP WebSocket server.

- path: `https://www.selenium.dev/selenium/docs/api/py/selenium_webdriver_chromium/selenium.webdriver.chromium.webdriver.html`
  lines: `execute_cdp_cmd` API reference (accessed 2026-09-05)
  symbol: `ChromiumDriver.execute_cdp_cmd`
  excerpt: |
    The Python Chromium driver exposes execute_cdp_cmd(cmd, cmd_args) to send
    a CDP command through an existing Chromium WebDriver session.

- path: `https://www.selenium.dev/documentation/webdriver/bidi/cdp/`
  lines: CDP overview (accessed 2026-09-05)
  symbol: Selenium CDP support
  excerpt: |
    Selenium says CDP support is temporary, dependent on browser versions,
    and limited for features requiring bidirectional communication.

- path: `https://github.com/h4ckf0r0day/obscura`
  lines: README sections “Puppeteer / Playwright” and “CDP API” (accessed 2026-09-05)
  symbol: Obscura CDP server
  excerpt: |
    Obscura documents Playwright connectOverCDP and Puppeteer browserWSEndpoint,
    plus a CDP domain surface. The reviewed README does not advertise WebDriver
    or ChromeDriver support.

## Notes

The realistic Selenium choices are to keep Selenium for Chrome and use Obscura through the Playwright/CDP path, build a W3C WebDriver-to-CDP bridge, or add a WebDriver server to Obscura upstream. A Selenium-facing `ObscuraDriver` that merely points `debugger_address` at Obscura is unsupported until an end-to-end experiment proves ChromeDriver accepts and controls the non-Chrome endpoint.
