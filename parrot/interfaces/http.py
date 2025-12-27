from typing import Optional, Union, Dict, Any
import os
import asyncio
import random
import urllib.parse
from email.message import Message
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
import ssl
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
import urllib3
import aiofiles
import requests
import backoff
from requests.auth import HTTPBasicAuth
from requests.exceptions import HTTPError
from requests.exceptions import Timeout as RequestTimeoutException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import (
    ConversationLimitException,
    DuckDuckGoSearchException,
    RatelimitException,
    TimeoutException,
)
import primp
import aiohttp
from aiohttp import BasicAuth
import httpx
from bs4 import BeautifulSoup as bs
from lxml import html, etree
from navconfig.logging import logging
from proxylists.proxies import (
    FreeProxy,
    Oxylabs,
    Decodo,
    Geonode
)
from ..utils import cPrint, SafeDict

from ..conf import (
    HTTPCLIENT_MAX_SEMAPHORE,
    HTTPCLIENT_MAX_WORKERS,
    GOOGLE_SEARCH_API_KEY,
    GOOGLE_SEARCH_ENGINE_ID
)
from .dataframes import PandasDataframe
class ComponentError(Exception):
    """Base class for component errors."""
    pass
from .credentials import CredentialsInterface


logging.getLogger("urllib3").setLevel(logging.WARNING)
urllib3.disable_warnings()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("rquest").setLevel(logging.INFO)


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
]

UA_LIST = ua

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

valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']

def bad_gateway_exception(exc):
    """Check if the exception is a 502 Bad Gateway error."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 502

class HTTPService(CredentialsInterface, PandasDataframe):
    """
    HTTPService.

    Overview

            Interface for making connections to HTTP services.
    """
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"  # noqa

    def __init__(self, *args, **kwargs):
        self.url: str = kwargs.get("url", None)
        self.accept: str = kwargs.get(
            "accept",
            self.accept
        )
        self.use_proxy: bool = kwargs.pop("use_proxy", False)
        self.proxy_type: str = kwargs.pop('proxy_type', 'oxylabs')
        self._free_proxy: bool = kwargs.pop('use_free_proxy', True)
        self._proxies: list = []
        self.rotate_ua: bool = kwargs.pop("rotate_ua", False)
        self.use_async: bool = bool(kwargs.pop("use_async", True))
        self.google_api_key: str = kwargs.pop('google_api_key', GOOGLE_SEARCH_API_KEY)
        self.google_cse: str = kwargs.pop('google_cse', GOOGLE_SEARCH_ENGINE_ID)
        self.as_binary: bool = kwargs.pop('as_binary', False)
        self.download: bool = kwargs.pop('download', False)
        self.timeout: int = 30
        self.headers: dict = kwargs.get('headers', {})
        self.auth: dict = {}
        self.auth_type: str = kwargs.get('auth_type', None)
        self.token_type: str = "Bearer"
        self._debug: bool = kwargs.get('debug', False)
        self._user, self._pwd = None, None
        self.method: str = kwargs.get("method", "get")
        self._default_parser: str = kwargs.pop('bs4_parser', 'html.parser')
        self.parameters = {}
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

        # other arguments:
        self.arguments = kwargs
        # Executor:
        self._executor = ThreadPoolExecutor(
            max_workers=int(HTTPCLIENT_MAX_WORKERS)
        )
        self._semaphore = asyncio.Semaphore(
            int(HTTPCLIENT_MAX_SEMAPHORE)
        )
        super().__init__(*args, **kwargs)

    def add_metric(self, key: str, value: Any) -> None:
        """
        Stub method for adding metrics.
        Override in subclasses if needed.
        """
        pass

    async def get_proxies(
        self,
        session_time: float = 0.40,
        free_proxy: bool = False
    ):
        """
        Asynchronously retrieves a list of free proxies.
        TODO: SELECT or rotate the free/paid proxies.
        """
        if self._free_proxy is True:
            return await FreeProxy().get_list()
        else:
            if self.proxy_type == 'decodo':
                return await Decodo().get_list()
            elif self.proxy_type == 'oxylabs':
                return await Oxylabs(
                    session_time=session_time,
                    timeout=10
                ).get_list()
            elif self.proxy_type == 'geonode':
                return await Geonode().get_list()
            else:
                return []

    async def refresh_proxies(self):
        """
        Asynchronously refreshes the list of proxies if proxy usage is enabled.
        """
        if self.use_proxy is True:
            self._proxies = await self.get_proxies()

    def build_url(self, url, queryparams: str = "", args=None):
        """
        Constructs a full URL with optional query parameters and arguments.

        :param url: The base URL to be formatted.
        :param queryparams: Additional query parameters to be appended to the URL.
        :param args: Arguments to format within the URL.
        :return: The fully constructed URL.
        """
        url = str(url).format_map(SafeDict(**self._variables))
        if args:
            u = url.format(**args)
        else:
            u = url
        if queryparams:
            if "?" in u:
                full_url = u + "&" + queryparams
            else:
                full_url = u + "?" + queryparams
        else:
            full_url = u
        logging.debug(
            f"Resource URL: {full_url!s}"
        )
        return full_url

    def extract_host(self, url):
        parsed_url = urlparse(url)
        return parsed_url.netloc

    async def session(
        self,
        url: str,
        method: str = "get",
        data: dict = None,
        cookies: dict = None,
        headers: dict = None,
        use_json: bool = False,
        follow_redirects: bool = False,
        use_proxy: bool = False,
        accept: str = None,
        return_response: bool = False
    ):
        """
        Asynchronously sends an HTTP request using HTTPx.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :param use_json: Whether to send the data as JSON.
        :param cookies: A dictionary of cookies to send with the request.
        :param headers: A dictionary of headers to send with the request.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxies = None
        if accept is not None:
            self.headers["Accept"] = accept
        else:
            self.headers["Accept"] = self.accept
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                self._proxies = None
        if self.credentials:
            if "apikey" in self.auth:
                self.headers[
                    "Authorization"
                ] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == "api_key":
                self.headers = {**self.headers, **self.credentials}
            elif self.auth_type == "key":
                url = self.build_url(
                    url, args=self.arguments, queryparams=urlencode(self.credentials)
                )
            elif self.auth_type in ["basic", "auth", "user"]:
                auth = (self.credentials["username"], self.credentials["password"])
        elif self._user and self.auth_type == "basic":
            auth = (self._user, self._pwd)
        cPrint(
            f"HTTP: Connecting to {url} using {method}",
            level="DEBUG"
        )
        if self.download is True:
            self.headers["Accept"] = "application/octet-stream"
            self.headers["Content-Type"] = "application/octet-stream"
            if self.use_streams is True:
                self.headers["Transfer-Encoding"] = "chunked"
        headers = self.headers
        if headers is not None and isinstance(headers, dict):
            headers = {**self.headers, **headers}
        timeout = httpx.Timeout(self.timeout)
        args = {"timeout": timeout, "headers": headers, "cookies": cookies}
        if auth is not None:
            args["auth"] = auth
        if proxies:
            if isinstance(proxies, dict):
                args['mounts'] = proxies
            else:
                args["proxies"] = proxies
        # if self._debug is True:
        #    self.add_metric("HEADERS", headers)
        if proxies is not None:
            self.add_metric('Proxies', proxies)
        self.add_metric('URL', url)
        self.add_metric('METHOD', method)
        req_args = {
            "method": method.upper(),
            "url": url,
            "follow_redirects": follow_redirects,
            "json" if use_json else "data": data
        }
        # Process the response
        try:
            if hasattr(self, "_client"):
                # Use a client without context manager to keep the session alive
                # Remember to call `await self._client.aclose()` manually
                response = await self._client.request(**req_args)
            else:
                async with httpx.AsyncClient(**args) as client:
                    response = await client.request(**req_args)

            result, error = await self.process_response(response, url)

            if return_response:
                return response, result, error

        except httpx.HTTPError as e:
            error = str(e)

        return (result, error)

    async def async_request(
        self,
        url,
        method: str = 'GET',
        data: dict = None,
        use_json: bool = False,
        use_proxy: bool = False,
        accept: Optional[str] = None
    ):
        """
        Asynchronously sends an HTTP request using aiohttp.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :param use_json: Whether to send the data as JSON.
        :param use_proxy: force proxy usage.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxy = None

        if use_proxy is True:
            self._proxies = await self.get_proxies()
        if self._proxies:
            proxy = random.choice(self._proxies)
            self.add_metric("Proxies", proxy)
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
        cPrint(
            f"HTTP: Connecting to {url} using {method}",
            level="DEBUG"
        )
        if self._debug is True:
            self.add_metric("HEADERS", self.headers)
        self.add_metric("URL", url)
        self.add_metric("METHOD", method)
        if auth is not None:
            args = {"auth": auth}
        else:
            args = {}
        if accept is not None:
            self.headers["Accept"] = accept
        else:
            self.headers["Accept"] = self.accept
        if self.download is True:
            self.headers["Accept"] = "application/octet-stream"
            self.headers["Content-Type"] = "application/octet-stream"
            if hasattr(self, "use_streams"):
                self.headers["Transfer-Encoding"] = "chunked"
                args["stream"] = True
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(
            headers=self.headers, timeout=timeout, auth=auth
        ) as session:
            try:
                if use_json is True:
                    async with session.request(
                        method.upper(), url, json=data, proxy=proxy, **args
                    ) as response:
                        result, error = await self.process_response(response, url)
                else:
                    async with session.request(
                        method.upper(), url, data=data, proxy=proxy, **args
                    ) as response:
                        # Process the response
                        result, error = await self.process_response(response, url)
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

    async def process_response(self, response, url: str) -> tuple:
        """
        Processes the response from an HTTP request.

        :param response: The response object from aiohttp.
        :param url: The URL that was requested.
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
            self._logger.error(f"Error: {error_context}")

            # Additional error handling or custom evaluation based on status
            if hasattr(self, 'no_errors'):
                for key, msg in self.no_errors.items():
                    if int(key) == status and await self.evaluate_error(message, msg):
                        return response, status

            # Raise an exception if error handling does not continue
            raise ConnectionError(f"HTTP Error {status}: {message!s}")
        else:
            if self.download is True:
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
                        filename = urllib.parse.unquote(utf8_filename)
                if "{filename}" in str(self.filename):
                    self.filename = str(self.filename).format_map(
                        SafeDict(filename=filename)
                    )
                if "{" in str(self.filename):
                    self.filename = str(self.filename).format_map(
                        SafeDict(**self.arguments)
                    )
                if isinstance(self.filename, str):
                    self.filename = Path(self.filename)
                # Saving File in Directory:
                total_length = response.headers.get("Content-Length")
                self._logger.info(
                    f"HTTPClient: Saving File {self.filename}, size: {total_length}"
                )
                pathname = self.filename.parent.absolute()
                if not pathname.exists():
                    # Create a new directory
                    pathname.mkdir(parents=True, exist_ok=True)
                transfer = response.headers.get("transfer-encoding", None)
                if transfer is None:
                    chunk_size = int(total_length)
                else:
                    chunk_size = 8192
                # Asynchronous file writing
                if self.filename.exists() and self.filename.is_file():
                    overwrite = self.destination.get("overwrite", True)
                    if overwrite is False:
                        self._logger.warning(
                            f"HTTPClient: File Already exists: {self.filename}"
                        )
                        # Filename already exists
                        result = self.filename
                        return result, error
                    else:
                        self._logger.warning(
                            f"HTTPClient: Overwriting File: {self.filename}"
                        )
                        # Delete the file before downloading again.
                        try:
                            self.filename.unlink()
                        except Exception as e:
                            self._logger.warning(
                                f"HTTPClient: Error Deleting File: {self.filename}, {e}"
                            )
                if hasattr(self, "use_streams") and self.use_streams is True:
                    async with aiofiles.open(self.filename, "wb") as file:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await file.write(chunk)
                else:
                    with open(self.filename, "wb") as fp:
                        try:
                            fp.write(await self.response_read(response))
                        except Exception:
                            pass
                self._logger.debug(
                    f"Filename Saved Successfully: {self.filename}"
                )
                result = self.filename
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
                        self._parser = etree.fromstring(result)
                    except etree.XMLSyntaxError:
                        self._parser = html.fromstring(result)
                    except Exception as e:
                        error = e
                elif self.accept == "application/json":
                    try:
                        result = await self.response_json(response)
                    except Exception as e:
                        logging.warning(e)
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

    async def request(
        self,
        url: str,
        method: str = "GET",
        data: dict = None,
        use_proxy: bool = False,
        accept: Optional[str] = None
    ) -> tuple:
        """
        Sends an HTTP request using the requests library.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
        if self._proxies:
            proxy = random.choice(self._proxies)
            proxies = {"http": proxy, "https": proxy, "ftp": proxy}
            self.add_metric("Proxies", proxies)
        if self.credentials:
            if "apikey" in self.auth:
                self.headers[
                    "Authorization"
                ] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == "api_key":
                self.headers = {**self.headers, **self.credentials}
            elif self.auth_type == "key":
                url = self.build_url(
                    url, args=self.arguments, queryparams=urlencode(self.credentials)
                )
            elif self.auth_type == "basic":
                auth = HTTPBasicAuth(
                    self.credentials["username"], self.credentials["password"]
                )
            else:
                auth = HTTPBasicAuth(
                    self.credentials["username"], self.credentials["password"]
                )
        elif self._user and self.auth_type == "basic":
            auth = HTTPBasicAuth(self._user, self._pwd)
        cPrint(f"HTTP: Connecting to {url} using {method}", level="DEBUG")
        self.add_metric("URL", url)
        self.add_metric("METHOD", method)
        if auth is not None:
            args = {"auth": auth, "verify": False}
        else:
            args = {}
        if accept is not None:
            self.headers["Accept"] = accept
        else:
            self.headers["Accept"] = self.accept
        if self.download is True:
            self.headers["Accept"] = "application/octet-stream"
            self.headers["Content-Type"] = "application/octet-stream"
            if hasattr(self, "use_streams"):
                self.headers["Transfer-Encoding"] = "chunked"
                args["stream"] = True
        if self._debug is True:
            self.add_metric("HEADERS", self.headers)
        args["headers"] = self.headers
        args["timeout"] = self.timeout
        args["proxies"] = proxies
        if method == "get":
            my_request = partial(requests.get, **args)
        elif method == "post":
            my_request = partial(requests.post, data=data, **args)
        elif method == "put":
            my_request = partial(requests.put, data=data, **args)
        elif method == "delete":
            my_request = partial(requests.delete, data=data, **args)
        elif method == "patch":
            my_request = partial(requests.patch, data=data, *args)
        else:
            my_request = partial(requests.post, data=data, **args)
        try:
            # making request
            async with self._semaphore:
                loop = asyncio.get_running_loop()
                future = loop.run_in_executor(self._executor, my_request, url)
                result, error = await self.process_request(future, url)
            if error:
                if isinstance(error, BaseException):
                    raise error
                else:
                    raise ComponentError(f"{error!s}")
            return (result, error)
        except requests.exceptions.ReadTimeout as err:
            self._logger.warning(f"Timeout Error: {err!r}")
            # TODO: retrying
            raise ComponentError(f"Timeout: {err}") from err
        except Exception as err:
            self._logger.exception(str(err), stack_info=True)
            raise ComponentError(f"Error: {err}") from err

    async def process_request(self, future, url: str):
        """
        Processes the result of an asynchronous HTTP request.

        :param future: The future object representing the asynchronous operation.
        :param url: The URL that was requested.
        :return: A tuple containing the result and any error information.
        """
        # getting the result, based on the Accept logic
        error = None
        result = None
        loop = asyncio.get_running_loop()
        asyncio.set_event_loop(loop)
        done, _ = await asyncio.wait([future], return_when=asyncio.FIRST_COMPLETED)
        for f in done:
            response = f.result()
            # for response in await asyncio.gather(*future):
            # Check for HTTP errors
            try:
                response.raise_for_status()
            except HTTPError as http_err:
                # Handle HTTP errors here
                error = http_err
                # Log the error or perform other error handling
                self._logger.error(f"HTTP error occurred: {http_err}")
                # You can choose to continue, break, or return based on your logic
                continue
            try:
                if self.download is True:
                    # Filename:
                    filename = os.path.basename(url)
                    # Get the filename from the response headers, if available
                    content_disposition = response.headers.get("content-disposition")
                    if content_disposition:
                        _, params = content_disposition.split(";")
                        try:
                            key, value = params.strip().split("=")
                            if key == "filename":
                                filename = value.strip("'\"")
                        except ValueError:
                            pass
                    if "{filename}" in str(self.filename):
                        self.filename = str(self.filename).format_map(
                            SafeDict(filename=filename)
                        )
                    if "{" in str(self.filename):
                        self.filename = str(self.filename).format_map(
                            SafeDict(**self.arguments)
                        )
                    if isinstance(self.filename, str):
                        self.filename = Path(self.filename)
                    # Saving File in Directory:
                    total_length = response.headers.get("Content-Length")
                    self._logger.info(
                        f"HTTPClient: Saving File {self.filename}, size: {total_length}"
                    )
                    pathname = self.filename.parent.absolute()
                    if not pathname.exists():
                        # Create a new directory
                        pathname.mkdir(parents=True, exist_ok=True)
                    response.raise_for_status()
                    transfer = response.headers.get("transfer-encoding", None)
                    if transfer is None:
                        chunk_size = int(total_length)
                    else:
                        chunk_size = 8192
                    if self.filename.exists() and self.filename.is_file():
                        overwrite = self.destination.get("overwrite", True)
                        if overwrite is False:
                            self._logger.warning(
                                f"HTTPClient: File Already exists: {self.filename}"
                            )
                            # Filename already exists
                            result = self.filename
                            continue
                        else:
                            self._logger.warning(
                                f"HTTPClient: Overwriting File: {self.filename}"
                            )
                            # Delete the file before downloading again.
                            try:
                                self.filename.unlink()
                            except Exception as e:
                                self._logger.warning(
                                    f"HTTPClient: Error Deleting File: {self.filename}, {e}"
                                )
                    with open(self.filename, "wb") as fp:
                        try:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                fp.write(chunk)
                            fp.flush()
                        except Exception:
                            pass
                    self._logger.debug(f"Filename Saved Successfully: {self.filename}")
                    result = self.filename
                elif self.accept in ("text/html"):
                    result = response.content  # Get content of the response as bytes
                    try:
                        # html parser for lxml
                        self._parser = html.fromstring(result)
                        # BeautifulSoup parser

                        self._bs = bs(response.text, self._default_parser)
                        result = self._bs
                    except Exception as e:
                        error = e
                elif self.accept in ("application/xhtml+xml", "application/xml"):
                    result = response.content  # Get content of the response as bytes
                    try:
                        self._parser = etree.fromstring(result)
                    except Exception as e:
                        error = e
                elif self.accept == "application/json":
                    try:
                        result = response.json()
                    except Exception as e:
                        logging.error(e)
                        # is not an json, try first with beautiful soup:
                        try:
                            self._bs = bs(response.text, self._default_parser)
                            result = self._bs
                        except Exception:
                            error = e
                else:
                    result = response.text
            except requests.exceptions.ProxyError as err:
                raise ComponentError(f"Proxy Connection Error: {err!r}") from err
            except requests.ReadTimeout as err:
                return (result, err)
            except requests.exceptions.HTTPError as e:
                # Log the error or perform other error handling
                self._logger.error(f"HTTP error occurred: {error}")
                raise ComponentError(f"HTTP Error: {error!r}, ex: {e!s}") from e
            except Exception as e:
                logging.exception(e)
                return (result, e)
        # returning results
        return (result, error)

    @staticmethod
    async def response_read(response):
        if hasattr(response, 'aread'):
            return await response.aread()

        return await response.read()

    @staticmethod
    async def response_json(response):
        if asyncio.iscoroutinefunction(response.json):
            return await response.json()

        return response.json()

    @staticmethod
    def response_status(response):
        if hasattr(response, 'status_code'):
            return response.status_code

        return response.status

    @staticmethod
    async def response_text(response):
        if asyncio.iscoroutinefunction(response.text):
            return await response.text()

        return response.text

    @staticmethod
    async def response_reason(response):
        # Attempt to retrieve `reason`, `reason_phrase`, or fallback to an empty string
        reason = getattr(response, 'reason', getattr(response, 'reason_phrase', b''))

        return f"{reason!s}"

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: print(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def _get(
        self,
        url: str,
        cookies: httpx.Cookies = None,
        params: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        timeout: Union[int, float] = 30.0,
        use_proxy: bool = True,
        free_proxy: bool = False,
        connect_timeout: Union[int, float] = 5.0,
        read_timeout: Union[int, float] = 20.0,
        write_timeout: Union[int, float] = 5.0,
        pool_timeout: Union[int, float] = 20.0,
        num_retries: int = 2,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make an asynchronous HTTP GET request, returning the response object.

        Args:
            url (str): The URL to send the GET request to.
            cookies (httpx.Cookies): Cookies to include in the request.
            params (dict): Dictionary of query parameters to include in the URL.

        Returns:
            Response: The response object from the httpx.
        """
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                self._proxies = None

        # Define custom SSL context
        ssl_context = ssl.create_default_context()
        # Disable older protocols if needed
        ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        # Ensure at least TLS 1.2 is used
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Use AsyncHTTPTransport to pass in SSL context explicitly
        transport = httpx.AsyncHTTPTransport(
            retries=num_retries,
            verify=ssl_context
        )
        timeout = httpx.Timeout(
            timeout=timeout,
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout
        )
        async with httpx.AsyncClient(
            cookies=cookies,
            proxy=proxies or None,
            transport=transport,
            headers=headers,
            timeout=timeout,
            http2=True,
            follow_redirects=True,
            **kwargs
        ) as client:
            try:
                response = await client.get(
                    url,
                    params=params  # Pass query parameters here
                )
                response.raise_for_status()
                return response
            except httpx.TimeoutException:
                print("Request timed out.")
                raise
            except httpx.HTTPError as ex:
                print(f"HTTP error occurred: {ex}")
                raise httpx.HTTPError(ex) from ex
            except Exception as exc:
                print('EXC > ', exc)
                raise ComponentError(
                    f"An error occurred: {exc}"
                ) from exc

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: print(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def _post(
        self,
        url: str,
        cookies: httpx.Cookies,
        params: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        data: Dict[str, str] = None,
        follow_redirects: bool = True,
        raise_for_status: bool = True,
        use_proxy: bool = True,
        free_proxy: bool = False,
    ) -> Dict[str, Any]:
        """
        Make an asynchronous HTTP POST request, returning the response object.

        Args:
            url (str): The URL to send the POST request to.
            cookies (httpx.Cookies): Cookies to include in the request.
            params (dict): Dictionary of query parameters to include in the URL.

        Returns:
            Response: The response object from the httpx.
        """
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                self._proxies = None

        # Define custom SSL context
        ssl_context = ssl.create_default_context()
        # Disable older protocols if needed
        ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        # Ensure at least TLS 1.2 is used
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Use AsyncHTTPTransport to pass in SSL context explicitly
        transport = httpx.AsyncHTTPTransport(retries=2, verify=ssl_context)
        timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=20.0)

        async with httpx.AsyncClient(
            cookies=cookies,
            proxy=proxies or None,
            transport=transport,
            headers=headers,
            timeout=timeout
        ) as client:
            try:
                response = await client.post(
                    url,
                    data=data,
                    params=params,
                    follow_redirects=follow_redirects
                )
                if raise_for_status:
                    response.raise_for_status()
                return response
            except httpx.TimeoutException:
                print("Request timed out.")
                raise
            except httpx.HTTPError as ex:
                print(f"HTTP error occurred: {ex}")
                raise httpx.HTTPError(ex) from ex
            except Exception as exc:
                print('EXC > ', exc)
                raise ComponentError(
                    f"An error occurred: {exc}"
                ) from exc

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: print(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def api_get(
        self,
        url: str,
        cookies: httpx.Cookies = None,
        params: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        use_proxy: bool = None,
        free_proxy: bool = False,
        use_http2: bool = True
    ) -> Dict[str, Any]:
        """
        Make an asynchronous HTTP GET request.

        Args:
            url (str): The URL to send the GET request to.
            cookies (httpx.Cookies): Cookies to include in the request.
            params (dict): Dictionary of query parameters to include in the URL.

        Returns:
            dict: The JSON response from the API if the request is successful.
            Returns an empty dictionary if the request fails.
        """
        proxies = None
        use_proxy = self.use_proxy if use_proxy is None else use_proxy
        if use_proxy is True:
            self._proxies = await self.get_proxies(free_proxy=free_proxy)
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                proxies = proxies.strip() if proxies.startswith('http') else f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                proxies = None
            self._logger.debug(
                f'SELECTED PROXY: {proxies}'
            )
        # Define custom SSL context
        ssl_context = ssl.create_default_context()
        # Disable older protocols if needed
        ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        # Ensure at least TLS 1.2 is used
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Use AsyncHTTPTransport to pass in SSL context explicitly
        transport = httpx.AsyncHTTPTransport(retries=2, verify=ssl_context)
        timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=20.0)

        async with httpx.AsyncClient(
            cookies=cookies,
            proxy=proxies or None,
            transport=transport,
            headers=headers,
            timeout=timeout,
            http2=use_http2
        ) as client:
            try:
                response = await client.get(
                    url,
                    params=params
                )
                response.raise_for_status()
                if response.status_code < 400:
                    return response.json()
                else:
                    print(
                        f"API request failed with status code {response.status_code}"
                    )
                return {}
            except httpx.TimeoutException:
                print("Request timed out.")
                raise
            except httpx.HTTPError as ex:
                print(f"HTTP error occurred: {ex}")
                raise httpx.HTTPError(ex) from ex
            except Exception as exc:
                print('EXC > ', exc)
                raise ComponentError(
                    f"An error occurred: {exc}"
                ) from exc
    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: print(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def api_post(
        self,
        url: str,
        payload: Dict,
        cookies: httpx.Cookies = None,
        use_proxy: bool = None,
        free_proxy: bool = False,
        full_response: bool = False
    ) -> Dict[str, Any]:
        proxies = None
        use_proxy = self.use_proxy if use_proxy is None else use_proxy
        if use_proxy is True:
            self._proxies = await self.get_proxies(free_proxy=free_proxy)
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                proxies = proxies.strip() if proxies.startswith('http') else f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                proxies = None
        #self._logger.debug(f'SELECTED PROXY: {proxies}')
        # Define custom SSL context
        ssl_context = ssl.create_default_context()
        # Disable older protocols if needed
        ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        # Ensure at least TLS 1.2 is used
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Use AsyncHTTPTransport to pass in SSL context explicitly
        transport = httpx.AsyncHTTPTransport(retries=2, verify=ssl_context)
        timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=20.0)

        async with httpx.AsyncClient(
            cookies=cookies,
            proxy=proxies or None,
            transport=transport,
            headers=self.headers,
            timeout=timeout
        ) as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=timeout
                )
                response.raise_for_status()
                if full_response:
                    return response
                if response.status_code < 400:
                    return response.json()
                else:
                    print(
                        f"API request failed with status code {response.status_code}"
                    )
                return {}
            except httpx.TimeoutException:
                raise
            except (httpx.HTTPError) as ex:
                raise httpx.HTTPError(ex)
            except Exception as exc:
                print('EXC > ', exc)
                raise ComponentError(
                    f"An error occurred: {exc}"
                )

    @backoff.on_exception(
        backoff.expo,
        (RatelimitException, TimeoutException, DuckDuckGoSearchException),
        max_tries=5,
        max_time=120,  # Extended max time to allow sufficient retries
        jitter=backoff.full_jitter,  # Introduces randomization in retry timing
        on_backoff=lambda details: print(
            f"Retrying DuckDuckGo search: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int = 5,
        use_proxy: bool = True,
        timeout: int = 20,
        headers: dict = None,
        region: str = "wt-wt",
        backend: str = 'lite'
    ):
        """
        Search DuckDuckGo for a given query.

        Args:
            query (str): The search query.
            max_results (int): The maximum number of results to return.
            use_proxy (bool): Whether to use a proxy for the search.

        Returns:
            list: A list of search results.
        """
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxies = f"http://{proxy}"
                else:
                    proxies = proxy
            else:
                self._proxies = None
        if headers is None:
            headers = {}
        headers = {**self.headers, **headers}
        headers["User-Agent"] = random.choice(ua)
        try:
            with DDGS(
                headers=headers,
                proxy=proxies,
                timeout=timeout,
                verify=False
            ) as search:
                # 🐵 Monkey Patching Primp Client to avoid Rate-Limits issues:
                search.client = primp.Client(
                    headers=search.headers,
                    proxy=proxies,
                    timeout=timeout,
                    cookie_store=False,  # 🚀 Disable cookie persistence dynamically
                    referer=True,
                    impersonate=random.choice(DDGS._impersonates),
                    impersonate_os=random.choice(DDGS._impersonates_os),
                    follow_redirects=False,
                    verify=False,
                )
                return search.text(
                    keywords=query,
                    timelimit=timeout,
                    max_results=max_results,
                    backend=backend,
                    region=region
                )
        except DuckDuckGoSearchException as e:
            raise RatelimitException(
                f"Error on DuckDuckGo Search: {e}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"DuckDuckGo Error: {e}"
            ) from e

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RemoteProtocolError),  # Catch HTTP errors and timeouts
        max_tries=5,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: print(
            f"Retrying Google Search: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
    )
    async def _search_google(
        self,
        query: str,
        exact_term: str = None,
        max_results: int = 5,
        use_proxy: bool = True,
        timeout: int = 20,
        headers: dict = None,
        region: str = None,
        country: str = None,
        language: str = None,
        use_primp: bool = False,
        **kwargs
    ):
        if headers:
            headers = {
                **self.headers,
                **headers,
                "Referer": "https://www.google.com/",
            }
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxy = f"http://{proxy}"
                proxies = {
                    "http://": httpx.AsyncHTTPTransport(
                        proxy=f"http://{proxy}"
                    ),
                    "https://": httpx.AsyncHTTPTransport(
                        proxy=f"http://{proxy}"
                    ),
                }
            else:
                self._proxies = None
        args = {
            "q": query,
            "cx": str(GOOGLE_SEARCH_ENGINE_ID),
            "num": str(max_results),
            "key": str(self.google_api_key),
            "hl": "en",             # UI language in English
            "sort": "date",         # Prefer newer content
        }
        if region:
            args["gl"] = region  # Geolocation
        if country:
            args["cr"] = country  # Country restriction
        if language:
            args["hl"] = language  # Language preference
        if exact_term:
            args["exactTerms"] = exact_term
        if use_primp:
            # Use Primp Client instead httpx:
            client = primp.Client(
                headers=headers,
                proxy=proxies,  # Use proxy if enabled
                timeout=timeout,
                cookie_store=False,  # 🚀 Disable cookie persistence
                referer=True,
                impersonate=random.choice(impersonates),
                impersonate_os=random.choice(impersonates_os),
                follow_redirects=True,
                verify=False
            )
            try:
                query = quote(query)
                search_url = f"https://cse.google.com/cse?cx={GOOGLE_SEARCH_ENGINE_ID}#gsc.tab=0&gsc.q={query}&gsc.sort="  # noqa
                response = client.get(
                    search_url,
                    **kwargs
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Google Search API failed with status {response.status_code}: {response.text}"
                    )
                return self._parse_google_cse_results(response.text, max_results)
            except Exception as e:
                print(f"Unexpected error: {e}")
                raise RuntimeError(
                    f"Primp Unexpected error: {e}"
                ) from e
        else:
            t = httpx.Timeout(timeout, connect=5.0, read=20.0, write=5.0, pool=20.0)
            async with httpx.AsyncClient(
                proxy=proxies,
                timeout=t,
            ) as client:
                try:
                    response = await client.get(
                        "https://customsearch.googleapis.com/customsearch/v1",
                        headers=headers,
                        params=args,
                        **kwargs
                    )
                    response.raise_for_status()
                    if response.status_code < 400:
                        return response.json()
                    else:
                        raise RuntimeError(
                            f"Google Search API failed: {response.text}, status: {response.status_code}"
                        )
                except httpx.HTTPStatusError as e:
                    print(f"Search Google: HTTP error: {e.response.status_code} - {e.response.text}")
                    raise
                except httpx.TimeoutException:
                    print("Search Google: Request timed out")
                    raise
                except httpx.RemoteProtocolError:  # ✅ Catch server disconnection error
                    print("Search Google: Server disconnected. Retrying with redirect enabled...")
                    raise
                except Exception as e:
                    print(f"Search Google: Unexpected error: {e}")
                    raise

    def get_httpx_cookies(self, domain: str = None, path: str = '/', cookies: dict = None):
        httpx_cookies = httpx.Cookies()
        if cookies is None:
            cookies = {}
        for key, value in cookies.items():
            httpx_cookies.set(
                key, value,
                domain=domain,
                path=path
            )
        return httpx_cookies

    def _parse_google_cse_results(self, html_content: str, max_results: int):
        """
        Extracts search results from the rendered HTML of `cse.google.com/cse`.

        Args:
            html_content (str): The HTML response from the search.
            max_results (int): Max number of results to return.

        Returns:
            list: List of extracted URLs and titles.
        """
        soup = bs(html_content, "html.parser")
        results = []

        print('CONTENT > ', html_content)

        # Extract results from the dynamically loaded content
        for item in soup.select(".gsc-webResult")[:max_results]:  # Adjust this selector if necessary
            title_tag = item.select_one(".gs-title")
            url_tag = item.select_one(".gs-title a")

            if title_tag and url_tag:
                title = title_tag.get_text(strip=True)
                url = url_tag["href"]
                results.append({"title": title, "url": url})

        return results
    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.TimeoutException),  # Catch HTTP errors and timeouts
        max_tries=3,
        max_time=120,
        jitter=backoff.full_jitter,
        on_backoff=lambda details: logging.warning(
            f"Retrying HTTP Get: attempt {details['tries']} after {details['wait']:0.2f}s"
        ),
        giveup=lambda e: isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in [429, 500, 502, 503, 504]  # pylint: disable=C0301  # noqa
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
        proxies = None
        if use_proxy is True:
            self._proxies = await self.get_proxies()
            if len(self._proxies) == 1:
                proxies = self._proxies[0]
                if not proxies.startswith('http'):
                    proxies = f"http://{proxies}"
            elif len(self._proxies) > 1:
                proxy = random.choice(self._proxies)
                if not proxy.startswith('http'):
                    proxy = f"http://{proxy}"
                proxies = {
                    "http://": httpx.AsyncHTTPTransport(
                        proxy=f"http://{proxy}"
                    ),
                    "https://": httpx.AsyncHTTPTransport(
                        proxy=f"http://{proxy}"
                    ),
                }
            else:
                self._proxies = None

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
            proxy=proxies or None,
            transport=transport,
            headers=headers,
            timeout=timeout,
            http2=kwargs.get('use_http2', True),
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
