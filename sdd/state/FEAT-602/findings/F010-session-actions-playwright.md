---
id: F010
query_id: Q024
type: read
intent: Session actions: authenticate + CredentialResolverFn contract; Playwright driver.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — session_actions provides fail-closed authenticate, cookie export/import and file upload primitives the web half can reuse

## Summary

`scraping/session_actions.py` exposes module-level `exec_authenticate(driver, action, ..., credential_resolver=None)` (74), `exec_get_cookies` (288), `exec_set_cookies` (334), `exec_await_human` (383), `exec_upload_file` (722), `exec_wait_for_download` (780); `CredentialResolverFn = Callable[[Authenticate], Awaitable[Optional[Tuple[Optional[str], Optional[str]]]]]` (65). `models.py::Authenticate(BrowserAction)` (486): `method: Literal["form","basic","oauth","custom"]`, `credential_provider`, `username_selector` etc.; `GetCookies` (393), `SetCookies` (403), `UploadFile` (648). Every function returns False on failure (never silently True). `exec_get_cookies` is the bridge that can hand a browser-obtained `sid` cookie to the REST half if API login ever breaks.

## Citations


- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py`
  lines: 1-16, 65, 74-79
  symbol: `exec_authenticate, CredentialResolverFn`
  excerpt: |
    CredentialResolverFn = Callable[[Authenticate], Awaitable[Optional[Tuple[Optional[str], Optional[str]]]]]
    async def exec_authenticate(driver, action, ..., credential_resolver: Optional[CredentialResolverFn] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py`
  lines: 288, 334, 722, 780
  symbol: `exec_get_cookies, exec_set_cookies, exec_upload_file, exec_wait_for_download`
  excerpt: |
    async def exec_get_cookies(driver, action: GetCookies) -> Dict[str, Any]  # 288
    async def exec_upload_file(driver, action: UploadFile) -> bool  # 722

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 393, 403, 486-506, 648
  symbol: `GetCookies, SetCookies, Authenticate, UploadFile`
  excerpt: |
    class Authenticate(BrowserAction):  # 486
        method: Literal["form", "basic", "oauth", "custom"]  # 492
        credential_provider: Optional[str]  # 495

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/`
  lines: listing
  symbol: `drivers`
  excerpt: |
    abstract.py, page_driver.py, playwright_config.py (PlaywrightConfig:11), playwright_driver.py (PlaywrightDriver:15), selenium_driver.py
