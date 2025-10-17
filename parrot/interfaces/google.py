"""
Google Services Client for AI-Parrot.

Simplified async-only implementation using aiogoogle.
Provides unified interface for Google services with credential management
and environment variable replacement.
"""
from __future__ import annotations
import contextlib
from pathlib import Path, PurePath
from typing import Union, List, Dict, Any, Optional, Callable
from abc import ABC
import asyncio
import os
import re
import json
import logging
from contextlib import suppress
from urllib.parse import urlparse
import webbrowser
from aiohttp import web
from redis import asyncio as aioredis
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.core.driver_cache import DriverCacheManager
from webdriver_manager.chrome import ChromeDriverManager
from playwright.async_api import async_playwright
from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ServiceAccountCreds, UserCreds
from aiogoogle.auth.utils import create_secret
from navconfig import BASE_DIR, config
from ..exceptions import ConfigError  # pylint: disable=E0611 # noqa
from ..conf import GOOGLE_CREDENTIALS_FILE, REDIS_HISTORY_URL


# ============================================================================
# Default Scopes for Google Services
# ============================================================================

DEFAULT_SCOPES = {
    # Google Drive
    'drive': [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive.metadata.readonly'
    ],
    # Google Sheets
    'sheets': [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/spreadsheets.readonly'
    ],
    # Google Docs
    'docs': [
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/documents.readonly'
    ],
    # Google Calendar
    'calendar': [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/calendar.readonly',
        'https://www.googleapis.com/auth/calendar.events'
    ],
    # Google Cloud Storage
    'storage': [
        'https://www.googleapis.com/auth/devstorage.full_control',
        'https://www.googleapis.com/auth/devstorage.read_only',
        'https://www.googleapis.com/auth/devstorage.read_write'
    ],
    # Gmail
    'gmail': [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.compose'
    ],
    # Google Search
    'search': [
        'https://www.googleapis.com/auth/cse'
    ]
}

# Combined scopes for full access
DEFAULT_SCOPES['all'] = list(set(
    DEFAULT_SCOPES['drive'] +
    DEFAULT_SCOPES['sheets'] +
    DEFAULT_SCOPES['docs'] +
    DEFAULT_SCOPES['calendar'] +
    DEFAULT_SCOPES['storage']
))


# ============================================================================
# Credentials Interface Mixin
# ============================================================================

class CredentialsInterface:
    """
    Mixin for processing credentials with environment variable replacement.

    Handles ${VAR_NAME} patterns in credential dictionaries.
    """

    ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def processing_credentials(self) -> None:
        """
        Process credentials dictionary and replace environment variables.

        Replaces ${VAR_NAME} patterns with values from environment variables.
        Works with both navconfig and os.environ.
        """
        if not hasattr(self, 'credentials_dict') or not self.credentials_dict:  # pylint: disable=E0203 # noqa
            return

        self.credentials_dict = self._replace_env_vars(self.credentials_dict)

    def _replace_env_vars(self, obj: Any) -> Any:
        """
        Recursively replace environment variables in strings.

        Args:
            obj: Object to process (dict, list, str, or other)

        Returns:
            Processed object with environment variables replaced
        """
        if isinstance(obj, dict):
            return {k: self._replace_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._replace_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            return self._replace_env_var_string(obj)
        return obj

    def _replace_env_var_string(self, value: str) -> str:
        """
        Replace environment variables in a string.

        Args:
            value: String potentially containing ${VAR} patterns

        Returns:
            String with variables replaced
        """
        def replacer(match):
            var_name = match.group(1)
            # Try navconfig first, then os.environ
            if hasattr(config, 'get'):
                env_value = config.get(var_name)
                if env_value is not None:
                    return env_value
            return os.environ.get(var_name, match.group(0))

        return self.ENV_VAR_PATTERN.sub(replacer, value)


# ============================================================================
# Google Client
# ============================================================================

class GoogleClient(CredentialsInterface, ABC):
    """
    Google Services Client for AI-Parrot.

    Async-only implementation using aiogoogle for:
    - Google Drive (file management)
    - Google Sheets (spreadsheets)
    - Google Docs (documents)
    - Google Calendar (events)
    - Google Cloud Storage (buckets)
    - Gmail (email)
    - Google Custom Search

    Features:
    - Service account and user credentials support
    - Environment variable replacement in credentials
    - Full async/await support via aiogoogle
    - OAuth2 interactive login support (framework ready)
    - Credential caching

    Authentication Methods:
    1. Service Account (recommended for server apps):
       - Use JSON key file
       - Use JSON string
       - Use dictionary

    2. User Credentials (OAuth2):
       - Interactive browser login (TODO: implement)
       - Cached credentials

    Example:
        # Service account from file
        client = GoogleClient(credentials="path/to/key.json")
        await client.initialize()

        # Service account from dict with env vars
        client = GoogleClient(credentials={
            "type": "service_account",
            "project_id": "${GCP_PROJECT_ID}",
            "private_key": "${GCP_PRIVATE_KEY}",
            ...
        })
        await client.initialize()

        # Context manager (recommended)
        async with GoogleClient(credentials="key.json", scopes="drive") as client:
            result = await client.execute_api_call(...)
    """

    def __init__(
        self,
        credentials: Optional[Union[str, dict, Path]] = None,
        scopes: Optional[Union[List[str], str]] = None,
        user_creds_cache_file: Optional[Union[str, Path]] = None,
        **kwargs
    ):
        """
        Initialize Google Client.

        Args:
            credentials: Credentials (file path, dict, "user" for OAuth)
            scopes: Service scopes (e.g., ["drive", "sheets"] or "all")
            **kwargs: Additional arguments
        """
        self.logger = logging.getLogger(f'Parrot.Interfaces.{self.__class__.__name__}')

        # Credential storage
        self.credentials_file: Optional[PurePath] = None
        self.credentials_str: Optional[str] = None
        self.credentials_dict: Optional[dict] = None
        self.auth_type: str = 'service_account'  # or 'user'
        self._oauth_client_config: Optional[Dict[str, Any]] = None
        self._client_credentials_source: Optional[str] = None
        self.redis_url: str = kwargs.get(
            "redis_url", REDIS_HISTORY_URL or "redis://localhost:6379/0"
        )
        self.redis: Optional[aioredis.Redis] = None
        try:
            self.redis = aioredis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
        except Exception as e:
            self.logger.warning(
                "Google: Redis unavailable (%s); falling back to file cache only.", e
            )
        self.user_creds_ttl: int = int(kwargs.get("user_creds_ttl", 75 * 24 * 3600)) # 75 days


        # Process scopes
        self.scopes: List[str] = self._process_scopes(scopes or 'all')

        # Credentials
        self._service_account_creds: Optional[ServiceAccountCreds] = None
        self._user_creds: Optional[UserCreds] = None
        self._user_creds_payload: Optional[Dict[str, Any]] = None

        # Authentication state
        self._authenticated = False

        # User credential cache
        if isinstance(user_creds_cache_file, (str, Path)):
            self.user_creds_cache_file: Optional[Path] = Path(user_creds_cache_file).expanduser().resolve()
        else:
            # Default cache location inside env directory
            self.user_creds_cache_file = BASE_DIR.joinpath('env', 'google', 'user_creds.json')

        # Process credentials
        self._load_credentials(credentials)
        super().__init__()

    async def __aenter__(self) -> GoogleClient:
        await self.ensure_interactive_session()
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _process_scopes(self, scopes: Union[List[str], str]) -> List[str]:
        """
        Process scope specification into full scope URLs.

        Args:
            scopes: Scope names or URLs

        Returns:
            List of full scope URLs
        """
        if isinstance(scopes, str):
            # Single scope name or "all"
            if scopes in DEFAULT_SCOPES:
                return DEFAULT_SCOPES[scopes].copy()
            scopes = [scopes]

        # Expand scope names to URLs
        result = []
        for scope in scopes:
            if scope.startswith('https://'):
                result.append(scope)
            elif scope in DEFAULT_SCOPES:
                result.extend(DEFAULT_SCOPES[scope])
            else:
                self.logger.warning(f"Unknown scope: {scope}")

        return list(set(result))  # Remove duplicates

    def _redis_cache_key(self, client_id: Optional[str], user_hint: Optional[str], scopes: list[str]) -> str:
        # Use OAuth client_id + (optional) user email hint + stable scopes hash
        sid = (client_id or "unknown").strip()
        u = (user_hint or "").strip()
        scopes_key = "|".join(sorted(scopes))
        return f"google:oauth:{sid}:{u}:{hash(scopes_key)}"

    async def _save_user_creds_to_redis(self, creds: dict, client_id: Optional[str], user_hint: Optional[str], scopes: list[str]) -> None:
        if not self.redis:
            return
        key = self._redis_cache_key(client_id, user_hint, scopes)
        try:
            await self.redis.set(key, json.dumps(creds, default=str), ex=self.user_creds_ttl)
            self.logger.info("Google: saved user credentials to Redis cache")
            self._user_creds_payload = creds.copy()
        except Exception as e:
            self.logger.warning("Google: failed to save creds to Redis: %s", e)

    async def _load_user_creds_from_redis(self, client_id: Optional[str], user_hint: Optional[str], scopes: list[str]) -> bool:
        if not self.redis:
            return False
        key = self._redis_cache_key(client_id, user_hint, scopes)
        try:
            blob = await self.redis.get(key)
            if not blob:
                return False
            data = json.loads(blob)
            scopes2 = data.get("scopes", scopes)
            if isinstance(scopes2, str):
                scopes2 = [scopes2]
            d = data.copy()
            d.pop("scopes", None)
            self._user_creds = UserCreds(scopes=scopes2, **d)
            self._user_creds_payload = data
            self._service_account_creds = None
            self._authenticated = True
            self._client_credentials_source = f"redis:{key}"
            self.logger.info("Google: loaded user credentials from Redis cache")
            return True
        except Exception as e:
            self.logger.warning("Google: failed to load creds from Redis: %s", e)
            return False

    def _load_credentials(
        self,
        credentials: Optional[Union[str, dict, Path]]
    ) -> None:
        """
        Load and validate credentials.

        Args:
            credentials: Credentials specification
        """
        if credentials is None:
            if not GOOGLE_CREDENTIALS_FILE.exists():
                raise RuntimeError(
                    "Google: No credentials provided and GOOGLE_CREDENTIALS_FILE not found."
                )
            self.credentials_file = GOOGLE_CREDENTIALS_FILE
            self._client_credentials_source = f"file:{self.credentials_file}"
            try:
                self.credentials_dict = json.loads(self.credentials_file.read_text())
                self._set_auth_type_from_dict(self.credentials_dict)
            except json.JSONDecodeError:
                # Keep lazy loading for malformed files; will raise during initialize
                self.logger.debug("Google: Could not parse default credentials file on load.")
            return

        if isinstance(credentials, str):
            if credentials.lower() == "user":
                # OAuth2 user credentials
                self.auth_type = 'user'
                self._client_credentials_source = 'user:prompt'
                return
            elif credentials.endswith(".json"):
                # JSON file path
                self.credentials_file = Path(credentials).resolve()
                if not self.credentials_file.exists():
                    # Try BASE_DIR
                    self.credentials_file = BASE_DIR.joinpath(credentials).resolve()
                    if not self.credentials_file.exists():
                        raise ConfigError(
                            f"Google: Credentials file not found: {credentials}"
                        )
                try:
                    self.credentials_dict = json.loads(self.credentials_file.read_text())
                    self._set_auth_type_from_dict(self.credentials_dict)
                    self._client_credentials_source = f"file:{self.credentials_file}"
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        f"Google: Invalid JSON in credentials file: {self.credentials_file}"
                    ) from exc
            else:
                # JSON string
                try:
                    self.credentials_dict = json.loads(credentials)
                    self._set_auth_type_from_dict(self.credentials_dict)
                    self._client_credentials_source = 'string:json'
                except json.JSONDecodeError as e:
                    raise ConfigError(
                        "Google: Invalid JSON credentials string"
                    ) from e

        elif isinstance(credentials, (Path, PurePath)):
            self.credentials_file = Path(credentials).resolve()
            if not self.credentials_file.exists():
                raise ConfigError(
                    f"Google: Credentials file not found: {self.credentials_file}"
                )
            try:
                self.credentials_dict = json.loads(self.credentials_file.read_text())
                self._set_auth_type_from_dict(self.credentials_dict)
                self._client_credentials_source = f"file:{self.credentials_file}"
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    f"Google: Invalid JSON in credentials file: {self.credentials_file}"
                ) from exc

        elif isinstance(credentials, dict):
            self.credentials_dict = credentials
            self._set_auth_type_from_dict(self.credentials_dict)
            self._client_credentials_source = 'dict:provided'

        else:
            raise ConfigError(
                f"Google: Invalid credentials type: {type(credentials)}"
            )

    def _set_auth_type_from_dict(self, data: Optional[Dict[str, Any]]) -> None:
        """Determine authentication type based on credentials dictionary."""
        if not data:
            return

        if data.get('type') == 'service_account':
            self.auth_type = 'service_account'
            self._oauth_client_config = None
            return

        if (oauth_config := self._extract_oauth_client_config(data)):
            self.auth_type = 'user'
            self._oauth_client_config = oauth_config
        else:
            self._oauth_client_config = None

    @staticmethod
    def _extract_oauth_client_config(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Extract OAuth client configuration from credentials dictionary."""
        if not data or not isinstance(data, dict):
            return None

        if data.get('type') == 'service_account':
            return None

        for key in ('installed', 'web'):
            value = data.get(key)
            if isinstance(value, dict) and 'client_id' in value:
                return value

        if 'client_id' in data and ('auth_uri' in data or 'token_uri' in data):
            return data

        return None

    def _get_oauth_client_config(self) -> Dict[str, Any]:
        """Resolve OAuth client credentials for interactive login."""
        if self._oauth_client_config:
            return self._oauth_client_config

        candidates: List[Dict[str, Any]] = []

        if isinstance(self.credentials_dict, dict):
            candidates.append(self.credentials_dict)

        if self.credentials_file and Path(self.credentials_file).exists():
            try:
                candidates.append(json.loads(Path(self.credentials_file).read_text()))
            except json.JSONDecodeError:
                self.logger.debug(
                    "Google: Failed to parse credentials file %s for OAuth config.",
                    self.credentials_file
                )

        default_file = GOOGLE_CREDENTIALS_FILE
        if default_file and default_file.exists():
            if not self.credentials_file or Path(self.credentials_file).resolve() != default_file.resolve():
                try:
                    candidates.append(json.loads(default_file.read_text()))
                except json.JSONDecodeError:
                    self.logger.debug(
                        "Google: Failed to parse default credentials file %s for OAuth config.",
                        default_file
                    )

        for candidate in candidates:
            if (oauth_config := self._extract_oauth_client_config(candidate)):
                self._oauth_client_config = oauth_config
                return oauth_config

        raise ConfigError(
            "Google: OAuth client credentials not found. Provide OAuth client JSON for user authentication."
        )

    def _prepare_user_creds(
        self,
        creds: Dict[str, Any],
        scopes: List[str]
    ) -> Dict[str, Any]:
        """Prepare user credential payload for storage and UserCreds construction."""
        allowed_keys = [
            'access_token', 'refresh_token', 'expires_in', 'expires_at',
            'token_type', 'token_uri', 'token_info_uri', 'revoke_uri', 'id_token_jwt'
        ]
        sanitized = {key: creds.get(key) for key in allowed_keys if creds.get(key) is not None}

        id_token = creds.get('id_token')
        if isinstance(id_token, (dict, str)):
            sanitized['id_token'] = id_token

        sanitized['scopes'] = scopes
        return sanitized

    def _export_active_user_creds(self, scopes: List[str]) -> Dict[str, Any]:
        """Return the sanitized credential payload for the active user session."""
        if not self._user_creds:
            raise RuntimeError("Google: No active user credentials to export")

        payload: Dict[str, Any]
        if self._user_creds_payload:
            payload = self._user_creds_payload.copy()
        else:
            payload = dict(self._user_creds)
        payload['scopes'] = scopes
        return self._prepare_user_creds(payload, scopes)

    def _save_user_creds_to_cache(self, creds: Dict[str, Any]) -> None:
        """Persist user credentials to cache for subsequent sessions."""
        if not self.user_creds_cache_file:
            return

        try:
            self.user_creds_cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.user_creds_cache_file.write_text(json.dumps(creds, indent=2, default=str))
        except Exception as cache_error:  # pragma: no cover - defensive
            self.logger.warning(
                "Google: Failed to cache user credentials: %s",
                cache_error
            )

    def _load_cached_user_creds(self) -> bool:
        """Load cached user credentials if available."""
        if not self.user_creds_cache_file or not self.user_creds_cache_file.exists():
            return False

        try:
            cached = json.loads(self.user_creds_cache_file.read_text())
            scopes = cached.get('scopes', self.scopes)
            if isinstance(scopes, str):
                scopes = [scopes]
            creds_kwargs = cached.copy()
            creds_kwargs.pop('scopes', None)
            self._user_creds = UserCreds(scopes=scopes, **creds_kwargs)
            self._user_creds_payload = cached
            self._client_credentials_source = f"cache:{self.user_creds_cache_file}"
            return True
        except Exception as cache_error:  # pragma: no cover - defensive
            self.logger.warning(
                "Google: Failed to load cached user credentials: %s",
                cache_error
            )
            return False

    def load_cached_user_credentials(self) -> bool:
        """Public helper for loading cached user credentials."""
        return self._load_cached_user_creds()

    def set_credentials(self, credentials: Optional[Union[str, dict, Path]]) -> None:
        """Public helper to update credentials after initialization."""
        self._load_credentials(credentials)
        self._authenticated = False

    @property
    def active_credentials(self) -> Optional[Union[ServiceAccountCreds, UserCreds]]:
        """Return whichever credential set is currently active."""
        return self._service_account_creds or self._user_creds

    @property
    def credentials_source(self) -> Optional[str]:
        """Return the source the client used to obtain credentials."""
        return self._client_credentials_source

    @property
    def is_authenticated(self) -> bool:
        """Expose authentication status for callers."""
        return self._authenticated

    def using_service_account(self) -> bool:
        """Return True if the client is configured for service-account credentials."""
        return self.auth_type == 'service_account' and self._service_account_creds is not None

    def using_user_credentials(self) -> bool:
        """Return True if the client is configured for end-user OAuth credentials."""
        return self.auth_type == 'user' and self._user_creds is not None

    async def initialize(self) -> GoogleClient:
        """
        Initialize the client and authenticate.

        Returns:
            Self for method chaining
        """
        if self._authenticated:
            return self

        # Process environment variables in credentials
        self.processing_credentials()
        if self.auth_type != 'service_account':
            # user creds: try Redis first
            client_id = None
            try:
                oauth_cfg = self._get_oauth_client_config()  # you already have this
                client_id = oauth_cfg.get("client_id")
            except Exception:
                pass

            # Optional user hint from config/env (email), else None
            user_hint = (self.credentials_dict or {}).get("user_email") or os.environ.get("GOOGLE_USER_HINT")

            if not self._user_creds:
                loaded = await self._load_user_creds_from_redis(client_id, user_hint, self.scopes)
                if not loaded:
                    # Fall back to file cache
                    if not self._load_cached_user_creds():
                        raise RuntimeError(
                            "Google: User credentials not available. Run interactive_login() first."
                        )

        elif self.auth_type == 'service_account':
            # Service account credentials
            if self.credentials_dict:
                creds_dict = self.credentials_dict
            elif self.credentials_file:
                creds_dict = json.loads(self.credentials_file.read_text())
            else:
                raise RuntimeError("Google: No credentials available")

            self._service_account_creds = ServiceAccountCreds(
                scopes=self.scopes,
                **creds_dict
            )
            self._user_creds = None
            self._user_creds_payload = None
            if not self._client_credentials_source:
                self._client_credentials_source = 'service_account:runtime'
        else:
            # User credentials require interactive login
            self._service_account_creds = None
            if not self._user_creds and not self._load_cached_user_creds():
                raise RuntimeError(
                    "Google: User credentials not available. Run interactive_login() first."
                )

        self._authenticated = True
        self.logger.info("Google Client initialized")
        return self

    async def execute_api_call(
        self,
        service_name: str,
        api_name: str,
        method_chain: str,
        version: str = None,
        **kwargs
    ) -> Any:
        """
        Execute a Google API call.

        Args:
            service_name: Service name (drive, sheets, docs, calendar, storage, gmail)
            api_name: API resource name (e.g., 'files', 'spreadsheets', 'events')
            method_chain: Method to call (e.g., 'list', 'get', 'create')
            version: API version (defaults based on service)
            **kwargs: Method parameters

        Returns:
            API response

        Example:
            # List Drive files
            files = await client.execute_api_call(
                'drive', 'files', 'list',
                pageSize=10,
                fields='files(id, name)'
            )

            # Get spreadsheet
            sheet = await client.execute_api_call(
                'sheets', 'spreadsheets', 'get',
                version='v4',
                spreadsheetId='abc123'
            )
        """
        if not self._authenticated:
            await self.initialize()

        # Default versions
        version_map = {
            'drive': 'v3',
            'sheets': 'v4',
            'docs': 'v1',
            'calendar': 'v3',
            'storage': 'v1',
            'gmail': 'v1',
            'customsearch': 'v1'
        }

        if version is None:
            version = version_map.get(service_name, 'v1')

        async with Aiogoogle(
            service_account_creds=self._service_account_creds,
            user_creds=self._user_creds
        ) as aiogoogle:
            # Discover the API
            api = await aiogoogle.discover(service_name, version)

            # Navigate to the resource
            resource = getattr(api, api_name)
            # Get the method
            method = getattr(resource, method_chain)
            # Execute the request
            if self._service_account_creds:
                result = await aiogoogle.as_service_account(method(**kwargs))
            else:
                result = await aiogoogle.as_user(method(**kwargs))

            return result

    async def get_drive_client(self, version: str = 'v3') -> Dict[str, Any]:
        """Get Google Drive client config."""
        return {'service': 'drive', 'version': version}

    async def get_sheets_client(self, version: str = 'v4') -> Dict[str, Any]:
        """Get Google Sheets client config."""
        return {'service': 'sheets', 'version': version}

    async def get_docs_client(self, version: str = 'v1') -> Dict[str, Any]:
        """Get Google Docs client config."""
        return {'service': 'docs', 'version': version}

    async def get_calendar_client(self, version: str = 'v3') -> Dict[str, Any]:
        """Get Google Calendar client config."""
        return {'service': 'calendar', 'version': version}

    async def get_storage_client(self, version: str = 'v1') -> Dict[str, Any]:
        """Get Google Cloud Storage client config."""
        return {'service': 'storage', 'version': version}

    async def get_gmail_client(self, version: str = 'v1') -> Dict[str, Any]:
        """Get Gmail client config."""
        return {'service': 'gmail', 'version': version}

    async def search(
        self,
        query: str,
        cse_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Perform a Google Custom Search.

        Args:
            query: Search query
            cse_id: Custom Search Engine ID
            **kwargs: Additional search parameters

        Returns:
            Search results
        """
        if not (cse_id := cse_id or os.environ.get('GOOGLE_SEARCH_ENGINE_ID')):
            raise RuntimeError(
                "Google Custom Search requires cse_id parameter or "
                "GOOGLE_SEARCH_ENGINE_ID environment variable"
            )

        return await self.execute_api_call(
            'customsearch',
            'cse',
            'list',
            q=query,
            cx=cse_id,
            **kwargs
        )

    async def interactive_login(
        self,
        scopes: Optional[Union[List[str], str]] = None,
        port: int = 5050,
        redirect_uri: Optional[str] = None,
        open_browser: bool = True,
        browser: str = "system",
        login_callback: Optional[Callable[[str], Optional[bool]]] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Perform interactive OAuth2 login for user credentials.

        This opens a browser for the user to authenticate.

        Args:
            scopes: Scopes to request (defaults to self.scopes)
            port: Local server port for OAuth redirect
            redirect_uri: Custom redirect URI
            open_browser: When True, launch a Playwright browser to complete login
            login_callback: Optional callback invoked with the authorization URL
            timeout: Seconds to wait for the authentication flow to complete
        """

        self.auth_type = 'user'
        scopes_list = self._process_scopes(scopes or self.scopes)
        self.processing_credentials()

        try:
            await self.ensure_interactive_session(scopes_list)
        except Exception as cached_error:  # pragma: no cover - defensive reuse path
            self.logger.debug(
                "Google: cached interactive session unavailable: %s",
                cached_error
            )
        else:
            if self._user_creds:
                self.logger.info(
                    "Google: reusing cached credentials for interactive login request"
                )
                return self._export_active_user_creds(scopes_list)

        oauth_client_config = self._get_oauth_client_config()
        redirect_uri = redirect_uri or oauth_client_config.get('redirect_uri')
        if not redirect_uri:
            redirect_uris = oauth_client_config.get('redirect_uris', [])
            if redirect_uris:
                redirect_uri = redirect_uris[0]
        if not redirect_uri:
            redirect_uri = f"http://localhost:{port}/callback/aiogoogle"

        parsed_redirect = urlparse(redirect_uri)
        callback_host = parsed_redirect.hostname or 'localhost'
        callback_port = parsed_redirect.port or port
        callback_path = parsed_redirect.path or '/'
        if not callback_path.startswith('/'):
            callback_path = f'/{callback_path}'

        client_creds = {
            'client_id': oauth_client_config['client_id'],
            'client_secret': oauth_client_config.get('client_secret'),
            'scopes': scopes_list,
            'redirect_uri': redirect_uri
        }

        aiogoogle_client = Aiogoogle(client_creds=client_creds)
        if not aiogoogle_client.oauth2.is_ready(client_creds):
            raise ConfigError("Google: OAuth client configuration is incomplete for interactive login")

        state = create_secret()
        authorization_url = aiogoogle_client.oauth2.authorization_url(
            client_creds=client_creds,
            state=state,
            access_type="offline",
            include_granted_scopes=True,
            prompt="consent"
        )

        # Provide URL via callback or console
        if login_callback:
            try:
                login_callback(authorization_url)
            except Exception as callback_error:  # pragma: no cover - defensive
                self.logger.warning(
                    "Login callback raised an exception: %s",
                    callback_error
                )
        self.logger.info("Authorize Google access by visiting: %s", authorization_url)
        print("\n" + "=" * 60)
        print("Open the following URL in your browser to authenticate:")
        print(authorization_url)
        print("=" * 60 + "\n")

        login_event = asyncio.Event()
        result_container: Dict[str, Any] = {}
        error_container: Dict[str, Any] = {}

        routes = web.RouteTableDef()

        @routes.get(callback_path)
        async def oauth_callback(request):  # type: ignore[unused-variable]
            if request.query.get('error'):
                error_container['error'] = request.query.get('error_description') or request.query.get('error')
                login_event.set()
                return web.json_response({'status': 'error', **error_container}, status=400)

            if not request.query.get('code'):
                login_event.set()
                error_container['error'] = 'Missing authorization code'
                return web.Response(text="Missing authorization code", status=400)

            returned_state = request.query.get('state')
            if returned_state != state:
                login_event.set()
                error_container['error'] = 'State mismatch during OAuth2 callback'
                return web.Response(text="State mismatch", status=400)

            try:
                full_user_creds = await aiogoogle_client.oauth2.build_user_creds(
                    grant=request.query.get('code'),
                    client_creds=client_creds
                )
                result_container['creds'] = full_user_creds
                login_event.set()
                return web.Response(
                    text="Authentication complete. You may close this window.",
                    content_type='text/plain'
                )
            except Exception as auth_error:  # pragma: no cover - defensive
                error_container['error'] = str(auth_error)
                login_event.set()
                return web.Response(
                    text=f"Authentication failed: {auth_error}",
                    status=500
                )

        app = web.Application()
        app.add_routes(routes)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=callback_host, port=callback_port)
        await site.start()

        playwright_task: Optional[asyncio.Task] = None
        if open_browser:
            if browser == "system":
                webbrowser.open(authorization_url, new=1, autoraise=True)
            elif browser == "playwright":
                try:
                    async def launch_browser():
                        try:
                            async with async_playwright() as playwright:
                                browser = await playwright.chromium.launch(channel="chrome", headless=False)
                                page = await browser.new_page()
                                try:
                                    await page.goto(authorization_url, wait_until="load")
                                    await login_event.wait()
                                finally:
                                    with suppress(Exception):
                                        await page.close()
                                    with suppress(Exception):
                                        await browser.close()
                        except asyncio.CancelledError:  # pragma: no cover - cancellation support
                            raise
                        except Exception as browser_error:  # pragma: no cover - defensive
                            self.logger.warning(
                                "Playwright interactive session failed: %s",
                                browser_error
                            )

                    playwright_task = asyncio.create_task(launch_browser())
                except ImportError:
                    self.logger.warning(
                        "Playwright is not installed; open the authorization URL manually."
                    )
            elif browser == "selenium":
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options

                    def launch_selenium_browser():
                        try:
                            options = Options()
                            options.add_argument("--disable-infobars")
                            options.add_argument("--disable-extensions")
                            driver = webdriver.Chrome(options=options)
                            driver.get(authorization_url)
                            # Wait until login_event is set
                            while not login_event.is_set():
                                asyncio.sleep(1)
                        except Exception as selenium_error:  # pragma: no cover - defensive
                            self.logger.warning(
                                "Selenium interactive session failed: %s",
                                selenium_error
                            )
                        finally:
                            with suppress(Exception):
                                driver.quit()

                    loop = asyncio.get_event_loop()
                    playwright_task = loop.run_in_executor(None, launch_selenium_browser)
                except ImportError:
                    self.logger.warning(
                        "Selenium is not installed; open the authorization URL manually."
                    )
            else:
                self.logger.warning("Unknown browser=%s, falling back to system browser", browser)
                webbrowser.open(authorization_url, new=1, autoraise=True)

        try:
            await asyncio.wait_for(login_event.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "Google interactive login timed out. Try again and ensure the browser completes authentication."
            ) from exc
        finally:
            if playwright_task:
                playwright_task.cancel()
                with suppress(Exception):
                    await playwright_task
            await runner.cleanup()

        if error_container.get('error'):
            raise RuntimeError(f"Google interactive login failed: {error_container['error']}")

        if 'creds' not in result_container:
            raise RuntimeError("Google interactive login did not return credentials")

        sanitized_creds = self._prepare_user_creds(result_container['creds'], scopes_list)
        creds_for_instance = sanitized_creds.copy()
        scopes_for_user = creds_for_instance.pop('scopes', scopes_list)
        self._user_creds = UserCreds(scopes=scopes_for_user, **creds_for_instance)
        self._service_account_creds = None
        self._authenticated = True
        self._client_credentials_source = 'user:interactive'
        self._user_creds_payload = sanitized_creds.copy()

        self._save_user_creds_to_cache(sanitized_creds)
        client_id = oauth_client_config.get('client_id')

        self.logger.info("Google interactive login completed successfully")
        user_hint = sanitized_creds.get("id_token", {}) if isinstance(sanitized_creds.get("id_token"), dict) else None
        if isinstance(user_hint, dict):
            # try extracting email if present
            user_hint = user_hint.get("email")
        await self._save_user_creds_to_redis(sanitized_creds, client_id, user_hint, scopes_list)
        return sanitized_creds

    async def close(self) -> None:
        """Clean up resources."""
        self._authenticated = False
        self.logger.info("Google Client closed")

    async def __aenter__(self) -> GoogleClient:
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        return (
            f"GoogleClient("
            f"auth_type={self.auth_type}, "
            f"authenticated={self._authenticated})"
        )

    async def ensure_interactive_session(self, scopes: Optional[Union[List[str], str]] = None) -> None:
        """Ensure we have usable user creds in memory; load from Redis/file cache if possible."""
        scopes_list = self._process_scopes(scopes or self.scopes)
        if self._user_creds:
            return

        client_id = None
        with contextlib.suppress(Exception):
            oauth_cfg = self._get_oauth_client_config()
            client_id = oauth_cfg.get("client_id")

        user_hint = (self.credentials_dict or {}).get("user_email") or os.environ.get("GOOGLE_USER_HINT")

        loaded = await self._load_user_creds_from_redis(client_id, user_hint, scopes_list)
        if not loaded and not self._load_cached_user_creds():
                raise RuntimeError("Google: no cached session; call interactive_login()")

        # Optionally probe a trivial endpoint to trigger refresh if needed:
        try:
            async with Aiogoogle(user_creds=self._user_creds) as ag:
                # a lightweight no-op call: get token info endpoint
                _ = await ag.oauth2.get_user_info()  # if scopes include openid/profile; otherwise skip
        except Exception as e:
            # If this fails due to expired token & bad refresh, force re-login
            raise RuntimeError(
                "Google: cached session expired; run interactive_login() again"
            ) from e



# ============================================================================
# Helper Functions
# ============================================================================

def create_google_client(
    credentials: Optional[Union[str, dict, Path]] = None,
    scopes: Optional[Union[List[str], str]] = None,
    **kwargs
) -> GoogleClient:
    """
    Factory function to create a GoogleClient.

    Args:
        credentials: Credentials specification
        scopes: Service scopes
        **kwargs: Additional GoogleClient arguments

    Returns:
        GoogleClient instance
    """
    return GoogleClient(
        credentials=credentials,
        scopes=scopes,
        **kwargs
    )
