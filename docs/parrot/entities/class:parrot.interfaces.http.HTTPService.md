---
type: Wiki Entity
title: HTTPService
id: class:parrot.interfaces.http.HTTPService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTPService.
relates_to:
- concept: class:parrot.interfaces.dataframes.PandasDataframe
  rel: extends
---

# HTTPService

Defined in [`parrot.interfaces.http`](../summaries/mod:parrot.interfaces.http.md).

```python
class HTTPService(CredentialsInterface, PandasDataframe)
```

HTTPService.

Overview

        Interface for making connections to HTTP services.

## Methods

- `def add_metric(self, key: str, value: Any) -> None` — Stub method for adding metrics.
- `async def get_proxies(self, session_time: float=0.4, free_proxy: bool=False)` — Asynchronously retrieves a list of free proxies.
- `async def refresh_proxies(self)` — Asynchronously refreshes the list of proxies if proxy usage is enabled.
- `def build_url(self, url, queryparams: str='', args=None)` — Constructs a full URL with optional query parameters and arguments.
- `def extract_host(self, url)`
- `async def session(self, url: str, method: str='get', data: dict=None, cookies: dict=None, headers: dict=None, use_json: bool=False, follow_redirects: bool=False, use_proxy: bool=False, accept: str=None, return_response: bool=False)` — Asynchronously sends an HTTP request using HTTPx.
- `async def async_request(self, url, method: str='GET', data: dict=None, use_json: bool=False, use_proxy: bool=False, accept: Optional[str]=None)` — Asynchronously sends an HTTP request using aiohttp.
- `async def evaluate_error(self, response: Union[str, list], message: Union[str, list, dict]) -> tuple` — evaluate_response.
- `async def process_response(self, response, url: str) -> tuple` — Processes the response from an HTTP request.
- `async def request(self, url: str, method: str='GET', data: dict=None, use_proxy: bool=False, accept: Optional[str]=None) -> tuple` — Sends an HTTP request using the requests library.
- `async def process_request(self, future, url: str)` — Processes the result of an asynchronous HTTP request.
- `async def response_read(response)`
- `async def response_json(response)`
- `def response_status(response)`
- `async def response_text(response)`
- `async def response_reason(response)`
- `async def api_get(self, url: str, cookies: httpx.Cookies=None, params: Dict[str, Any]=None, headers: Dict[str, str]=None, use_proxy: bool=None, free_proxy: bool=False, use_http2: bool=True) -> Dict[str, Any]` — Make an asynchronous HTTP GET request.
- `async def api_post(self, url: str, payload: Dict, cookies: httpx.Cookies=None, use_proxy: bool=None, free_proxy: bool=False, full_response: bool=False) -> Dict[str, Any]`
- `def get_httpx_cookies(self, domain: str=None, path: str='/', cookies: dict=None)`
