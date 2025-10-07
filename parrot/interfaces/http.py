from typing import Optional, Union, Dict, Any, Tuple
import random
import os
import asyncio
import ssl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from email.message import Message
from urllib import parse
from urllib.parse import urlencode, urlparse
import urllib3
import aiofiles
# parsing:
from bs4 import BeautifulSoup as bs
from lxml import html, etree
# backoff retries:
import backoff
# aiohttp:
import aiohttp
from aiohttp import BasicAuth
# httpx
import httpx
# config:
from datamodel.typedefs import SafeDict
from datamodel.parsers.json import JSONContent, json_encoder  # pylint: disable=E0611 # noqa
from navconfig.logging import logging
from proxylists.proxies import FreeProxy, Oxylabs
from ..conf import (
    HTTPCLIENT_MAX_SEMAPHORE,
    HTTPCLIENT_MAX_WORKERS,
    GOOGLE_SEARCH_API_KEY,
    GOOGLE_SEARCH_ENGINE_ID
)


# Suppress warnings
logging.getLogger("urllib3").setLevel(logging.WARNING)
urllib3.disable_warnings()
for logger_name in ["httpx", "httpcore", "aiohttp", "hpack"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)


# User agents and impersonation profiles
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

MOBILE_UA_LIST = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
]

IMPERSONATES = (
    "chrome_120", "chrome_123", "chrome_124", "chrome_126", "chrome_127", "chrome_128",
    "chrome_129", "chrome_130", "chrome_131",
    "safari_ios_18.1.1", "safari_18", "safari_18.2", "safari_ipad_18",
    "edge_127", "edge_131", "firefox_128", "firefox_133",
)

VALID_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']


class BackoffConfig:
    """Configuration for backoff retry behavior."""

    def __init__(
        self,
        max_tries: int = 3,
        max_time: int = 120,
        exponential: bool = True,
        jitter: bool = True,
        retry_statuses: tuple = (429, 500, 502, 503, 504)
    ):
        self.max_tries = max_tries
        self.max_time = max_time
        self.wait_gen = backoff.expo if exponential else backoff.constant
        self.jitter = backoff.full_jitter if jitter else None
        self.retry_statuses = retry_statuses


class HTTPService:
    """
    Unified HTTP client abstraction supporting both aiohttp and httpx.

    Features:
    - Proxy support (free and paid)
    - User-Agent rotation
    - Automatic retry with backoff
    - HTTP/2 support
    - Session management
    - Response processing or raw response
    """

    def __init__(self, *args, **kwargs):
        # Proxy configuration
        self.use_proxy: bool = kwargs.pop("use_proxy", False)
        self._free_proxy: bool = kwargs.pop('free_proxy', False)
        self._proxies: list = []

        # User-Agent configuration
        self.rotate_ua: bool = kwargs.pop("rotate_ua", True)
        self._ua: str = random.choice(UA_LIST) if self.rotate_ua else UA_LIST[0]

        # HTTP configuration
        self.use_async: bool = kwargs.pop("use_async", True)
        self.timeout: int = kwargs.get('timeout', 30)
        self.use_streams: bool = kwargs.get('use_streams', True)
        self.as_binary: bool = kwargs.get('as_binary', False)
        self.accept: str = kwargs.get('accept', "application/json")

        # HTTP/2 support
        self.use_http2: bool = kwargs.pop('use_http2', False)

        # Backoff configuration
        backoff_config = kwargs.pop('backoff_config', None)
        if backoff_config and isinstance(backoff_config, dict):
            self.backoff_config = BackoffConfig(**backoff_config)
        elif isinstance(backoff_config, BackoffConfig):
            self.backoff_config = backoff_config
        else:
            self.backoff_config = BackoffConfig()

        # Headers setup
        self.headers: dict = kwargs.get('headers', {})
        self.headers.update({
            "Accept": self.accept,
            "Accept-Encoding": "gzip, deflate, br" if self.use_http2 else "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self._ua,
        })

        # Cookies
        self.cookies = kwargs.get('cookies', {})

        # Authentication
        self.credentials: dict = kwargs.get('credentials', {})
        self.auth_type: str = None
        self.token_type: str = "Bearer"
        self._user, self._pwd = None, None
        self._setup_auth()

        # Google API
        self.google_api_key: str = kwargs.pop('google_api_key', GOOGLE_SEARCH_API_KEY)
        self.google_cse: str = kwargs.pop('google_cse', GOOGLE_SEARCH_ENGINE_ID)

        # Response handling
        self.no_errors: dict = kwargs.get('no_errors', {})
        self._default_parser: str = kwargs.pop('bs4_parser', 'html.parser')

        # Utilities
        self._encoder = JSONContent()
        self._executor = ThreadPoolExecutor(max_workers=int(HTTPCLIENT_MAX_WORKERS))
        self._semaphore = asyncio.Semaphore(int(HTTPCLIENT_MAX_SEMAPHORE))
        self._debug: bool = kwargs.pop('debug', False)
        self.logger = logging.getLogger(__name__)

        # Store remaining arguments
        self.arguments = kwargs

    def _setup_auth(self):
        """Setup authentication based on credentials."""
        if "apikey" in self.credentials:
            self.auth_type = "api_key"
            self.headers["Authorization"] = f"{self.token_type} {self.credentials['apikey']}"
        elif "username" in self.credentials:
            self.auth_type = "basic"
            self._user = self.credentials["username"]
            self._pwd = self.credentials["password"]
        elif "token" in self.credentials:
            self.auth_type = "token"
            self.headers["Authorization"] = f"{self.token_type} {self.credentials['token']}"
        elif "key" in self.credentials:
            self.auth_type = "key"

    async def get_proxies(self, session_time: float = 1) -> list:
        """Get proxy list (free or paid)."""
        if self._free_proxy:
            return await FreeProxy().get_list()
        else:
            return await Oxylabs(session_time=session_time, timeout=10).get_list()

    async def refresh_proxies(self):
        """Refresh the proxy list."""
        if self.use_proxy:
            self._proxies = await self.get_proxies()

    def build_url(
        self,
        url: str,
        queryparams: Optional[str] = None,
        args: Optional[dict] = None,
        params: Optional[dict] = None
    ) -> str:
        """Build complete URL with query parameters."""
        if args:
            url = str(url).format_map(SafeDict(**args))
        if queryparams:
            url += ("&" if "?" in url else "?") + queryparams
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)

        if self._debug:
            self.logger.debug(f"Built URL: {url}")
        return url

    def _create_ssl_context(self, verify_ssl: bool = True) -> ssl.SSLContext:
        """Create SSL context with secure defaults."""
        ssl_context = ssl.create_default_context()
        ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        if verify_ssl:
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        return ssl_context

    def _should_retry(self, exception) -> bool:
        """Determine if request should be retried based on exception."""
        if isinstance(exception, (httpx.HTTPStatusError, aiohttp.ClientResponseError)):
            status = getattr(exception, 'status_code', getattr(exception, 'status', None))
            return status in self.backoff_config.retry_statuses
        return isinstance(exception, (
            httpx.TimeoutException,
            aiohttp.ServerTimeoutError,
            aiohttp.ClientError
        ))

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError),
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        giveup=lambda e: isinstance(e, httpx.HTTPStatusError) and
                        e.response.status_code not in [429, 500, 502, 503, 504]
    )
    async def httpx_request(
        self,
        url: str,
        method: str = 'GET',
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[httpx.Cookies] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        use_json: bool = False,
        use_proxy: bool = None,
        use_ssl: bool = True,
        verify_ssl: bool = True,
        follow_redirects: bool = True,
        full_response: bool = False,
        download: bool = False,
        filename: Optional[str] = None,
        timeout: Optional[Union[int, float]] = None,
        **kwargs
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """
        Make async HTTP request using httpx with HTTP/2 support.

        Returns:
            Tuple[result, error]: Processed result or raw response, and any error
        """
        # Determine proxy usage
        use_proxy = use_proxy if use_proxy is not None else self.use_proxy
        proxy_config = None

        if use_proxy:
            proxies = await self.get_proxies()
            if proxies:
                proxy = proxies[0]
                proxy_config = {
                    "http://": f"http://{proxy}",
                    "https://": f"http://{proxy}"
                }

        # SSL configuration
        ssl_context = self._create_ssl_context(verify_ssl) if use_ssl else None

        # Setup transport with retry capability
        transport = httpx.AsyncHTTPTransport(
            retries=kwargs.pop('num_retries', 2),
            verify=ssl_context
        )

        # Timeout configuration
        timeout_config = httpx.Timeout(
            timeout=timeout or self.timeout,
            connect=kwargs.pop('connect_timeout', 5.0),
            read=kwargs.pop('read_timeout', 20.0),
            write=kwargs.pop('write_timeout', 5.0),
            pool=kwargs.pop('pool_timeout', 20.0)
        )

        # Merge headers
        request_headers = {**self.headers, **(headers or {})}

        method = method.upper()
        if method not in VALID_METHODS:
            raise ValueError(f"Invalid HTTP method: {method}")

        async with httpx.AsyncClient(
            transport=transport,
            headers=request_headers,
            cookies=cookies,
            proxy=proxy_config or None,
            timeout=timeout_config,
            http2=self.use_http2,  # Enable HTTP/2
            follow_redirects=follow_redirects,
            **kwargs
        ) as client:
            try:
                # Build request arguments
                request_args = {
                    "method": method,
                    "url": url,
                }

                if data:
                    request_args["json" if use_json else "data"] = data
                if params:
                    request_args["params"] = params

                # Make request
                response = await client.request(**request_args)
                response.raise_for_status()

                # Return full response if requested
                if full_response:
                    return response, None

                # Process response
                result, error = await self._process_response(
                    response,
                    url,
                    download=download,
                    filename=filename
                )
                return result, error

            except httpx.TimeoutException as e:
                self.logger.error(f"Request timeout: {url}")
                raise
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP {e.response.status_code}: {url}")
                raise
            except httpx.RequestError as e:
                self.logger.error(f"Request error: {e}")
                raise

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, aiohttp.ServerTimeoutError, aiohttp.ClientResponseError),
        max_tries=3,
        max_time=60,
        jitter=backoff.full_jitter,
        giveup=lambda e: isinstance(e, aiohttp.ClientResponseError) and
                        e.status not in [429, 500, 502, 503, 504]
    )
    async def aiohttp_request(
        self,
        url: str,
        method: str = 'GET',
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        use_json: bool = False,
        use_proxy: bool = None,
        use_ssl: bool = False,
        verify_ssl: bool = True,
        full_response: bool = False,
        download: bool = False,
        filename: Optional[str] = None,
        timeout: Optional[Union[int, float]] = None,
        **kwargs
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """
        Make async HTTP request using aiohttp.

        Returns:
            Tuple[result, error]: Processed result or raw response, and any error
        """
        # Determine proxy usage
        use_proxy = use_proxy if use_proxy is not None else self.use_proxy
        proxy = None

        if use_proxy:
            proxies = await self.get_proxies()
            if proxies:
                proxy = random.choice(proxies)

        # Authentication setup
        auth = None
        if self.auth_type == "basic" and self._user:
            auth = BasicAuth(self._user, self._pwd)

        # SSL configuration
        ssl_context = self._create_ssl_context(verify_ssl) if use_ssl else None

        # Merge headers
        request_headers = {**self.headers, **(headers or {})}

        # Timeout configuration
        timeout_config = aiohttp.ClientTimeout(total=timeout or self.timeout)

        method = method.upper()

        async with aiohttp.ClientSession(
            headers=request_headers,
            timeout=timeout_config,
            auth=auth,
            json_serialize=json_encoder,
        ) as session:
            try:
                # Build request kwargs
                request_kwargs = {
                    "proxy": proxy,
                    "ssl": ssl_context if ssl_context else use_ssl,
                }

                # Make request
                if use_json and data:
                    async with session.request(method, url, json=data, **request_kwargs) as response:
                        return await self._handle_aiohttp_response(
                            response, url, full_response, download, filename
                        )
                else:
                    async with session.request(method, url, data=data, **request_kwargs) as response:
                        return await self._handle_aiohttp_response(
                            response, url, full_response, download, filename
                        )

            except aiohttp.ClientError as e:
                self.logger.error(f"aiohttp error: {e}")
                raise

    async def _handle_aiohttp_response(
        self,
        response,
        url: str,
        full_response: bool,
        download: bool,
        filename: Optional[str]
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """Handle aiohttp response."""
        if full_response:
            return response, None

        # Check status
        if response.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=f"HTTP {response.status}",
                headers=response.headers
            )

        return await self._process_response(response, url, download, filename)

    async def _process_response(
        self,
        response,
        url: str,
        download: bool = False,
        filename: Optional[str] = None
    ) -> Tuple[Any, Optional[Any]]:
        """
        Unified response processing for both httpx and aiohttp.

        Returns:
            Tuple[result, error]
        """
        error = None
        result = None

        # Download handling
        if download:
            result = await self._handle_download(response, url, filename)
            return result, error

        # Content type based processing
        if self.accept == 'application/octet-stream':
            data = await self._get_response_content(response)
            buffer = BytesIO(data)
            buffer.seek(0)
            result = buffer

        elif self.accept in ('text/html', 'application/xhtml+xml', 'application/xml'):
            content = await self._get_response_content(response)
            try:
                if self.accept == 'text/html':
                    result = bs(content, self._default_parser)
                else:
                    result = etree.fromstring(content)
            except Exception as e:
                error = e
                result = content

        elif self.accept == "application/json":
            try:
                result = await self._get_response_json(response)
            except Exception as e:
                # Fallback to text/HTML parsing
                try:
                    text = await self._get_response_text(response)
                    result = bs(text, self._default_parser)
                except Exception:
                    error = e

        elif self.as_binary:
            result = await self._get_response_content(response)
        else:
            result = await self._get_response_text(response)

        return result, error

    async def _handle_download(
        self,
        response,
        url: str,
        filename: Optional[str] = None
    ) -> Path:
        """Handle file download."""
        if not filename:
            filename = os.path.basename(url)

        # Try to get filename from headers
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            msg = Message()
            msg["Content-Disposition"] = content_disposition
            header_filename = msg.get_param("filename", header="Content-Disposition")
            utf8_filename = msg.get_param("filename*", header="Content-Disposition")

            if utf8_filename:
                _, utf8_filename = utf8_filename.split("''", 1)
                filename = parse.unquote(utf8_filename)
            elif header_filename:
                filename = header_filename

        filepath = Path(filename)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        if filepath.exists():
            self.logger.warning(f"File already exists: {filepath}")
            return filepath

        # Download file
        total_size = response.headers.get("Content-Length")
        self.logger.info(f"Downloading: {filepath} (size: {total_size})")

        # Stream download
        if self.use_streams and hasattr(response, 'content'):
            async with aiofiles.open(filepath, 'wb') as f:
                if hasattr(response.content, 'iter_chunked'):  # aiohttp
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
                else:  # httpx
                    async for chunk in response.aiter_bytes(8192):
                        await f.write(chunk)
        else:
            content = await self._get_response_content(response)
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(content)

        self.logger.info(f"Downloaded: {filepath}")
        return filepath

    async def _get_response_json(self, response):
        """Get JSON from response (handles both httpx and aiohttp)."""
        if hasattr(response, 'json'):
            if asyncio.iscoroutinefunction(response.json):
                return await response.json()
            return response.json()
        raise ValueError("Response does not support JSON")

    async def _get_response_text(self, response):
        """Get text from response (handles both httpx and aiohttp)."""
        if hasattr(response, 'text'):
            if asyncio.iscoroutinefunction(response.text):
                return await response.text()
            return response.text
        raise ValueError("Response does not support text")

    async def _get_response_content(self, response):
        """Get binary content from response (handles both httpx and aiohttp)."""
        if hasattr(response, 'content'):
            if asyncio.iscoroutinefunction(response.content):
                return await response.content()
            return response.content
        if hasattr(response, 'read'):
            return await response.read()
        if hasattr(response, 'aread'):
            return await response.aread()
        raise ValueError("Response does not support content reading")

    async def request(
        self,
        url: str,
        method: str = 'GET',
        client: str = 'httpx',
        **kwargs
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """
        Unified request method that delegates to httpx or aiohttp.

        Args:
            url: URL to request
            method: HTTP method
            client: 'httpx' or 'aiohttp' (default: 'httpx')
            **kwargs: Additional arguments passed to specific client

        Returns:
            Tuple[result, error]
        """
        if client.lower() == 'httpx':
            return await self.httpx_request(url, method, **kwargs)
        elif client.lower() == 'aiohttp':
            return await self.aiohttp_request(url, method, **kwargs)
        else:
            raise ValueError(f"Unsupported client: {client}. Use 'httpx' or 'aiohttp'")

    # Convenience methods
    async def get(self, url: str, client: str = 'httpx', **kwargs):
        """GET request."""
        return await self.request(url, 'GET', client, **kwargs)

    async def post(self, url: str, client: str = 'httpx', **kwargs):
        """POST request."""
        return await self.request(url, 'POST', client, **kwargs)

    async def put(self, url: str, client: str = 'httpx', **kwargs):
        """PUT request."""
        return await self.request(url, 'PUT', client, **kwargs)

    async def delete(self, url: str, client: str = 'httpx', **kwargs):
        """DELETE request."""
        return await self.request(url, 'DELETE', client, **kwargs)

    async def patch(self, url: str, client: str = 'httpx', **kwargs):
        """PATCH request."""
        return await self.request(url, 'PATCH', client, **kwargs)
