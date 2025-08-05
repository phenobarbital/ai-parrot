from typing import Optional, Union, Dict, Any
from collections.abc import Callable
import random
import os
import asyncio
import ssl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from email.message import Message
from urllib import parse
from urllib.parse import quote, urlencode, urlparse
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
from datamodel.parsers.json import JSONContent, json_encoder  # pylint: disable=E0611
from navconfig.logging import logging
from proxylists.proxies import (
    FreeProxy,
    Oxylabs
)
from ..conf import (
    HTTPCLIENT_MAX_SEMAPHORE,
    HTTPCLIENT_MAX_WORKERS,
    GOOGLE_SEARCH_API_KEY,
    GOOGLE_SEARCH_ENGINE_ID
)


logging.getLogger("urllib3").setLevel(logging.WARNING)
urllib3.disable_warnings()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.INFO)


ua = [
    # Chrome - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    # Chrome - Desktop (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",  # noqa
    # Safari - Desktop (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",  # noqa
    # Firefox - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    # Edge - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.46",  # noqa
    # Chrome - Mobile (Android)
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",  # noqa
    # Safari - Mobile (iOS)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",  # noqa
    # Samsung Internet - Mobile (Android)
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/21.0 Chrome/118.0.0.0 Mobile Safari/537.36",  # noqa
    # Firefox - Mobile (Android)
    "Mozilla/5.0 (Android 13; Mobile; rv:118.0) Gecko/118.0 Firefox/118.0",
    # Opera - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0"  # noqa
    # Firefox - Desktop (Linux)
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Chrome - Desktop (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Other:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa
]  # noqa

mobile_ua = [
    "Mozilla/5.0 (Linux; Android 4.2.1; en-us; Nexus 5 Build/JOP40D) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.166 Mobile Safari/535.19",  # noqa
    'Mozilla/5.0 (iPhone; CPU iPhone OS 12_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.0 Mobile/15E148 Safari/604.1',  # noqa
    'Mozilla/5.0 (Linux; Android 9; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.119 Mobile Safari/537.36',  # noqa
    'Mozilla/5.0 (Linux; Android 8.0.0; Pixel 2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.93 Mobile Safari/537.36',  # noqa
    'Mozilla/5.0 (Linux; Android 10; HUAWEI VOG-L29) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Mobile Safari/537.36',  # noqa
    'Mozilla/5.0 (iPad; CPU OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0 Mobile/15E148 Safari/604.1',  # noqa
]

impersonates = (
    "chrome_100", "chrome_101", "chrome_104", "chrome_105", "chrome_106", "chrome_107",
    "chrome_108", "chrome_109", "chrome_114", "chrome_116", "chrome_117", "chrome_118",
    "chrome_119", "chrome_120", "chrome_123", "chrome_124", "chrome_126", "chrome_127",
    "chrome_128", "chrome_129", "chrome_130", "chrome_131",
    "safari_ios_16.5", "safari_ios_17.2", "safari_ios_17.4.1", "safari_ios_18.1.1",
    "safari_15.3", "safari_15.5", "safari_15.6.1", "safari_16", "safari_16.5",
    "safari_17.0", "safari_17.2.1", "safari_17.4.1", "safari_17.5",
    "safari_18", "safari_18.2",
    "safari_ipad_18",
    "edge_101", "edge_122", "edge_127", "edge_131",
    "firefox_109", "firefox_117", "firefox_128", "firefox_133",
)  # fmt: skip

impersonates_os = ("android", "ios", "linux", "macos", "windows")


accept_list = {
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",  # noqa
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "image/webp",
    "image/apng",
    "*/*",
    "application/signed-exchange",
    "application/json",
}

valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']


def bad_gateway_exception(exc):
    """Check if the exception is a 502 Bad Gateway error."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 502


class HTTPService:
    """
    Abstraction Class for working with HTTP Clients.

    - aiohttp Client
    - HTTPx
    - Requests
    """
    def __init__(self, *args, **kwargs):
        self.use_proxy: bool = kwargs.pop("use_proxy", False)
        self._free_proxy: bool = kwargs.pop('free_proxy', False)
        self._proxies: list = []
        self.rotate_ua: bool = kwargs.pop("rotate_ua", True)
        self.use_async: bool = bool(kwargs.pop("use_async", True))
        self.google_api_key: str = kwargs.pop('google_api_key', GOOGLE_SEARCH_API_KEY)
        self.google_cse: str = kwargs.pop('google_cse', GOOGLE_SEARCH_ENGINE_ID)
        self.headers: dict = kwargs.get('headers', {})
        self.accept: str = kwargs.get('accept', "application/json")
        self.timeout: int = kwargs.get('timeout', 30)
        self.use_streams: bool = kwargs.get('use_streams', True)
        self.as_binary: bool = kwargs.get('as_binary', False)
        self.no_errors: dict = kwargs.get('no_errors', {})
        self._httpclient: Callable = kwargs.get('httpclient', None)
        self._ua: str = ""
        if self.rotate_ua is True:
            self._ua = random.choice(ua)
        else:
            self._ua: str = ua[0]
        self.headers = {
            "Accept": self.accept,
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self._ua,
            **self.headers,
        }
        # potentially cookies to be used by request.
        self.cookies = kwargs.get('cookies', {})
        self._encoder = JSONContent()
        # other arguments:
        self.arguments = kwargs
        # Executor:
        self._executor = ThreadPoolExecutor(
            max_workers=int(HTTPCLIENT_MAX_WORKERS)
        )
        self._semaphore = asyncio.Semaphore(
            int(HTTPCLIENT_MAX_SEMAPHORE)
        )
        # Authentication information:
        self.auth: dict = {}
        self.auth_type: str = None
        self.token_type: str = "Bearer"
        self._user, self._pwd = None, None
        self.credentials: dict = kwargs.get('credentials', {})
        if "apikey" in self.credentials:
            self.auth_type = "api_key"
        elif "username" in self.credentials:
            self.auth_type = "basic"
            self._user = self.credentials["username"]
            self._pwd = self.credentials["password"]
        elif "token" in self.credentials:
            self.auth_type = "token"
        elif "key" in self.credentials:
            self.auth_type = "key"
        elif "auth" in self.credentials:
            self.auth_type = "auth"
        # Debugging:
        self._debug: bool = kwargs.pop('debug', False)
        # Parser to be used:
        self._default_parser: str = kwargs.pop('bs4_parser', 'html.parser')
        # Logger:
        self.logger = logging.getLogger(__name__)

    async def get_proxies(self, session_time: float = 1):
        """
        Asynchronously retrieves a list of free proxies.
        TODO: SELECT or rotate the free/paid proxies.
        """
        if self._free_proxy is True:
            return await FreeProxy().get_list()
        else:
            return await Oxylabs(
                session_time=session_time,
                timeout=10
            ).get_list()

    async def refresh_proxies(self):
        """
        Asynchronously refreshes the list of proxies if proxy usage is enabled.
        """
        if self.use_proxy is True:
            self._proxies = await self.get_proxies()

    def build_url(
        self,
        url: str,
        queryparams: Optional[str] = None,
        args: Optional[dict] = None,
        params: Optional[dict] = None
    ) -> str:
        """
        Constructs a full URL with optional query parameters and arguments.

        Args:
            url (str): The base URL.
            queryparams (Optional[str]): The query parameters to append to the URL.
            args (Optional[dict]): Additional arguments to format into the URL.
            params (Optional[dict]): Additional query parameters to append to the URL.

        Returns:
            str: The constructed URL.
        """
        if args:
            url = str(url).format_map(SafeDict(**args))
        if queryparams is not None:
            if "?" in url:
                url += "&" + queryparams
            else:
                url += "?" + queryparams
        if params is not None:
            if "?" in url:
                url += "&" + urlencode(params)
            else:
                url = f"{url}?{urlencode(params)}"
        self.logger.debug(
            f"URL: {url}"
        )
        return url

    def extract_host(self, url):
        """
        Extracts the host from a URL.
        """
        parsed_url = urlparse(url)
        return parsed_url.netloc

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: logging.warning(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
        giveup=lambda e: isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in [429, 500, 502, 503, 504]  # pylint: disable=C0301
    )
    async def _request(
        self,
        url: str,
        method: str = 'get',
        cookies: Optional[httpx.Cookies] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float] = 30.0,
        use_proxy: bool = True,
        free_proxy: bool = False,
        use_ssl: bool = True,
        use_json: bool = False,
        follow_redirects: bool = True,
        raise_for_status: bool = True,
        full_response: bool = False,
        connect_timeout: Union[int, float] = 5.0,
        read_timeout: Union[int, float] = 20.0,
        write_timeout: Union[int, float] = 5.0,
        pool_timeout: Union[int, float] = 20.0,
        num_retries: int = 2,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make an asynchronous HTTPx request, returning the response object.

        Args:
            url (str): The URL to send the request to.
            method (str): The HTTP method to use (default: 'get').
            headers (dict, optional): Dictionary of HTTP headers to include in the request.
            cookies (httpx.Cookies, optional): Cookies to include in the request.
            params (dict, optional): Dictionary of query parameters to include in the URL.
            data (dict, optional): Dictionary of data to send in the request body.
            timeout (float, optional): Total timeout for the request in seconds.
            use_proxy (bool): Whether to use a proxy for the request.
            free_proxy (bool): Whether to use a free proxy.
            use_ssl (bool): Whether to use SSL for the request.
            use_json (bool): Whether to send data as JSON.
            follow_redirects (bool): Whether to follow redirects.
            raise_for_status (bool): Whether to raise an exception for HTTP errors.
            full_response (bool): Whether to return the full response object.
            connect_timeout (float): Timeout for connecting to the server.
            read_timeout (float): Timeout for reading from the server.
            write_timeout (float): Timeout for writing to the server.
            pool_timeout (float): Timeout for connection pool operations.
            num_retries (int): Number of retries to attempt at the transport level.
            **kwargs: Additional arguments to pass to httpx.AsyncClient.

        Returns:
            Tuple[Any, Optional[Dict[str, Any]]]: A tuple containing the result and any error information.

        Raises:
            httpx.TimeoutException: When the request times out.
            httpx.TooManyRedirects: When too many redirects are encountered.
            httpx.HTTPStatusError: When an HTTP error status is encountered.
            httpx.HTTPError: When an HTTP-related error occurs.
            AttributeError: When the HTTP method is invalid.
            RuntimeError: When an unknown error occurs.
        """
        proxy_config = None
        if use_proxy is True:
            self._free_proxy = free_proxy
            proxies = await self.get_proxies()
            if not proxies and use_proxy:
                self.logger.warning(
                    "No proxies available despite use_proxy=True"
                )
            proxy = proxies[0] if proxies else None  # Ensure there's at least one proxy
            proxy_config = {
                "http://": f"http://{proxy}" if proxy else None,
                "https://": f"http://{proxy}" if proxy else None  # Using the same proxy for HTTPS
            }

            # Remove proxies with None values
            proxy_config = {k: v for k, v in proxy_config.items() if v is not None}

        ssl_context = None
        if use_ssl:
            # Define custom SSL context
            ssl_context = ssl.create_default_context()
            # Disable older protocols if needed
            ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
            # Ensure at least TLS 1.2 is used
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            # Make this configurable rather than hardcoded to CERT_NONE
            if kwargs.get('verify_ssl', True):
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
            else:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

        # Use AsyncHTTPTransport to pass in SSL context explicitly
        transport_options = {
            'retries': num_retries,
            'verify': ssl_context
        }
        if 'transport_options' in kwargs:
            transport_options.update(kwargs.pop('transport_options'))
        transport = httpx.AsyncHTTPTransport(
            **transport_options
        )
        timeout = httpx.Timeout(
            timeout=timeout,
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout
        )
        method = method.upper()
        if method not in valid_methods:
            raise ValueError(
                f"Invalid HTTP method: {method}. Must be one of {valid_methods}"
            )
        async with httpx.AsyncClient(
            cookies=cookies,
            transport=transport,
            headers=headers,
            proxy=proxy_config or None,
            timeout=timeout,
            # http2=kwargs.pop('use_http2', True),
            follow_redirects=follow_redirects,
            **kwargs
        ) as client:
            try:
                args = {
                    "method": method.upper(),
                    "url": url,
                    "follow_redirects": follow_redirects
                }
                if data:
                    if use_json:
                        args["json"] = data
                    else:
                        args["data"] = data
                if params:
                    args["params"] = params
                if self._httpclient:
                    # keep session alive.
                    response = await client.request(
                        **args
                    )
                else:
                    response = await client.request(**args)
                if raise_for_status:
                    response.raise_for_status()
                if full_response:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(
                            f"Response from {url}: status={response.status_code}, headers={response.headers}"
                        )
                    return response, None
                result, error = await self.process_response(
                    response,
                    url,
                    download=kwargs.get('download', False),
                    filename=kwargs.get('filename', None)
                )
                return result, error
            except httpx.TimeoutException:
                self.logger.error("Request timed out.")
                raise
            except httpx.TooManyRedirects:
                self.logger.error("Too many redirects.")
                raise
            except httpx.HTTPStatusError as ex:
                self.logger.error(
                    f"HTTP status error occurred: {ex.response.status_code} - {ex}"
                )
                raise
            except httpx.HTTPError as ex:
                self.logger.error(f"HTTP error occurred: {ex}")
                raise
            except AttributeError as e:
                self.logger.error(f"HTTPx Client doesn't have attribute {method}: {e}")
                raise
            except Exception as exc:
                self.logger.error(f'Unknown Error > {exc}')
                raise RuntimeError(
                    f"An error occurred: {exc}"
                ) from exc

    @backoff.on_exception(
        backoff.expo,                     # Use exponential backoff
        (aiohttp.ClientError,             # Retry on network-related errors
        aiohttp.ServerTimeoutError,      # Retry on timeouts
        aiohttp.ClientResponseError),    # Retry on certain HTTP errors
        max_tries=3,                      # Maximum number of retries
        max_time=60,                      # Maximum total time to try (in seconds)
        jitter=backoff.full_jitter,       # Use full jitter to randomize retry intervals
        giveup=lambda e: isinstance(e, aiohttp.ClientResponseError) and e.status not in [429, 500, 502, 503, 504]  # pylint: disable=C0301
    )
    async def async_request(
        self,
        url,
        method: str = 'GET',
        data: dict = None,
        use_ssl: bool = False,
        use_json: bool = False,
        use_proxy: bool = False,
        accept: Optional[str] = None,
        download: bool = False,
        full_response: bool = False
    ):
        """
        Asynchronously sends an HTTP request using aiohttp.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :param use_json: Whether to send the data as JSON.
        :param use_proxy: force proxy usage.
        :param accept: The accept header to use.
        :param download: Whether to download the response as a file.
        :param full_response: Whether to return the full response object or result processed.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxy = None
        ssl_context = None

        if use_proxy is True:
            self._proxies = await self.get_proxies()
        if self._proxies:
            proxy = random.choice(self._proxies)
        if self.credentials:
            if "apikey" in self.auth:
                self.headers[
                    "Authorization"
                ] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == "api_key":
                self.headers = {**self.headers, **self.credentials}
            elif self.auth_type == "key":
                url = self.build_url(
                    url,
                    args=self.arguments,
                    queryparams=urlencode(self.credentials)
                )
            elif self.auth_type in ["basic", "auth", "user"]:
                auth = BasicAuth(
                    self.credentials["username"],
                    self.credentials["password"]
                )
        elif "apikey" in self.auth:
            self.headers["Authorization"] = f"{self.token_type} {self.auth['apikey']}"
        elif self.auth:
            token_type, token = list(self.auth.items())[0]
            self.headers["Authorization"] = f"{token_type} {token}"
        elif self._user and self.auth_type == "basic":
            auth = BasicAuth(self._user, self._pwd)
        self.logger.debug(
            f"HTTP: Connecting to {url} using {method}",
            level="DEBUG"
        )
        if auth is not None:
            args = {"auth": auth}
        else:
            args = {}
        if use_ssl:
            ssl_context = ssl.create_default_context()
            # Disable older protocols if needed
            ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
            # Ensure at least TLS 1.2 is used
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            args['ssl'] = True
            args['ssl_context'] = ssl_context
        if accept is not None:
            self.headers["Accept"] = accept
        else:
            self.headers["Accept"] = self.accept
        if download is True:
            self.headers["Accept"] = "application/octet-stream"
            self.headers["Content-Type"] = "application/octet-stream"
            if hasattr(self, "use_streams"):
                self.headers["Transfer-Encoding"] = "chunked"
                args["stream"] = True
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(
            headers=self.headers,
            timeout=timeout,
            auth=auth,
            json_serialize=json_encoder,
        ) as session:
            try:
                if use_json is True:
                    async with session.request(
                        method.upper(), url, json=data, proxy=proxy, **args
                    ) as response:
                        if full_response is True:
                            return full_response, None
                        result, error = await self.process_response(response, url, download=download)
                else:
                    async with session.request(
                        method.upper(), url, data=data, proxy=proxy, **args
                    ) as response:
                        if full_response is True:
                            return full_response, None
                        # Process the response
                        result, error = await self.process_response(response, url, download=download)
            except aiohttp.ClientError as e:
                error = str(e)
        return (result, error)

    async def evaluate_error(
        self, response: Union[str, list], message: Union[str, list, dict]
    ) -> tuple:
        """evaluate_response.

        Check Response status and available payloads.
        Args:
            response (_type_): _description_
            url (str): _description_

        Returns:
            tuple: _description_
        """
        if isinstance(response, list):
            # a list of potential errors:
            for msg in response:
                if message in msg:
                    return True
        if isinstance(response, dict) and "errors" in response:
            errors = response["errors"]
            if isinstance(errors, list):
                for error in errors:
                    try:
                        if message in error:
                            return True
                    except TypeError:
                        if message == error:
                            return True
            else:
                if message == errors:
                    return True
        else:
            if message in response:
                return True
        return False

    def response_status(self, response):
        if hasattr(response, 'status_code'):
            return response.status_code
        return response.status

    async def response_json(self, response):
        if asyncio.iscoroutinefunction(response.json):
            return await response.json()
        return response.json()

    async def response_read(self, response):
        if hasattr(response, 'aread'):
            return await response.aread()
        return await response.read()

    async def response_text(self, response):
        if asyncio.iscoroutinefunction(response.text):
            return await response.text()
        return response.text

    async def response_reason(self, response):
        # Attempt to retrieve `reason`, `reason_phrase`, or fallback to an empty string
        reason = getattr(response, 'reason', getattr(response, 'reason_phrase', b''))
        return f"{reason!s}"

    async def process_response(
        self,
        response, url: str,
        download: bool = False,
        filename: Optional[str] = None
    ) -> tuple:
        """
        Processes the response from an HTTP request.

        :param response: The response object from aiohttp.
        :param url: The URL that was requested.
        :param download: Whether to download the response as a file.
        :param filename: The filename to use for downloading the response.
        :return: A tuple containing the processed result and any error information.
        """
        error = None
        result = None
        # Process the response
        status = self.response_status(response)

        if status >= 400:
            # Evaluate response body and headers.
            print(" == ERROR Headers == ")
            print(f"{response.headers}")
            content_type = response.headers.get("Content-Type", "").lower()
            if "application/json" in content_type:
                message = await self.response_json(response)
            elif "text/" in content_type:
                message = await self.response_text(response)
            elif "X-Error" in response.headers:
                message = response.headers["X-Error"]
            else:
                # Fallback to a unified read method for the raw body content
                message = await self.response_read(response)

            # Combine response headers and body for enriched logging
            error_context = {
                "status": status,
                "reason": await self.response_reason(response),
                "headers": response.headers,
                "body": message
            }

            # Log the detailed error context
            self.logger.error(
                f"Error: {error_context}"
            )

            # Additional error handling or custom evaluation based on status
            if self.no_errors:
                for key, msg in self.no_errors.items():
                    if int(key) == status and await self.evaluate_error(message, msg):
                        return response, status

            # Raise an exception if error handling does not continue
            raise ConnectionError(
                f"HTTP Error {status}: {message!s}"
            )
        else:
            if download is True:
                if not filename:
                    filename = os.path.basename(url)
                # Get the filename from the response headers, if available
                content_disposition = response.headers.get("content-disposition")
                if content_disposition:
                    msg = Message()
                    msg["Content-Disposition"] = response.headers.get("content-disposition")
                    filename = msg.get_param("filename", header="Content-Disposition")
                    utf8_filename = msg.get_param("filename*", header="Content-Disposition")
                    if utf8_filename:
                        _, utf8_filename = utf8_filename.split("''", 1)
                        filename = parse.unquote(utf8_filename)
                if "{filename}" in str(filename):
                    filename = str(filename).format_map(
                        SafeDict(filename=filename)
                    )
                if "{" in str(filename):
                    filename = str(filename).format_map(
                        SafeDict(**self.arguments)
                    )
                if isinstance(filename, str):
                    filename = Path(filename)
                # Saving File in Directory:
                total_length = response.headers.get("Content-Length")
                self.logger.info(
                    f"HTTPClient: Saving File {filename}, size: {total_length}"
                )
                pathname = filename.parent.absolute()
                if not pathname.exists():
                    # Create a new directory
                    pathname.mkdir(parents=True, exist_ok=True)
                transfer = response.headers.get("transfer-encoding", None)
                if transfer is None:
                    chunk_size = int(total_length)
                else:
                    chunk_size = 8192
                # Asynchronous file writing
                if filename.exists() and filename.is_file():
                    self.logger.warning(
                        f"HTTPClient: File Already exists: {filename}"
                    )
                    # Filename already exists
                    result = filename
                    return result, error
                if self.use_streams is True:
                    async with aiofiles.open(filename, "wb") as file:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await file.write(chunk)
                else:
                    with open(filename, "wb") as fp:
                        try:
                            fp.write(await self.response_read(response))
                        except Exception:
                            pass
                self.logger.debug(
                    f"Filename Saved Successfully: {filename}"
                )
                result = filename
            else:
                if self.accept == 'application/octet-stream':
                    data = await self.response_read(response)
                    buffer = BytesIO(data)
                    buffer.seek(0)
                    result = buffer
                elif self.accept in ('text/html'):
                    result = await self.response_read(response)
                    try:
                        # html parser for lxml
                        self._parser = html.fromstring(result)
                        # BeautifulSoup parser
                        self._bs = bs(response.text, self._default_parser)
                        result = self._bs
                    except Exception as e:
                        error = e
                elif self.accept in ('application/xhtml+xml', 'application/xml'):
                    result = await self.response_read(response)
                    try:
                        self._parser = etree.fromstring(result)  # pylint: disable=I1101
                    except etree.XMLSyntaxError:  # pylint: disable=I1101
                        self._parser = html.fromstring(result)
                    except Exception as e:
                        error = e
                elif self.accept == "application/json":
                    try:
                        result = await self.response_json(response)
                    except Exception as e:
                        logging.error(e)
                        # is not an json, try first with beautiful soup:
                        try:
                            self._bs = bs(
                                await self.response_text(response),
                                self._default_parser
                            )
                            result = self._bs
                        except Exception:
                            error = e
                elif self.as_binary is True:
                    result = await self.response_read(
                        response
                    )
                else:
                    result = await self.response_text(
                        response
                    )
        return result, error
