"""
Google Services Client for AI-Parrot.

Simplified async-only implementation using aiogoogle.
Provides unified interface for Google services with credential management
and environment variable replacement.
"""
from __future__ import annotations
from pathlib import Path, PurePath
from typing import Union, List, Dict, Any, Optional
from abc import ABC
import os
import re
import json
import logging
from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ServiceAccountCreds, UserCreds
from navconfig import BASE_DIR, config
from ..exceptions import ConfigError  # pylint: disable=E0611 # noqa
from ..conf import GOOGLE_CREDENTIALS_FILE


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

        # Process scopes
        self.scopes: List[str] = self._process_scopes(scopes or 'all')

        # Credentials
        self._service_account_creds: Optional[ServiceAccountCreds] = None
        self._user_creds: Optional[UserCreds] = None

        # Authentication state
        self._authenticated = False

        # Process credentials
        self._load_credentials(credentials)

        super().__init__(**kwargs)

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
            return

        if isinstance(credentials, str):
            if credentials.lower() == "user":
                # OAuth2 user credentials
                self.auth_type = 'user'
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
            else:
                # JSON string
                try:
                    self.credentials_dict = json.loads(credentials)
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

        elif isinstance(credentials, dict):
            self.credentials_dict = credentials

        else:
            raise ConfigError(
                f"Google: Invalid credentials type: {type(credentials)}"
            )

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

        if self.auth_type == 'service_account':
            # Service account credentials
            if self.credentials_file:
                creds_dict = json.loads(self.credentials_file.read_text())
            elif self.credentials_dict:
                creds_dict = self.credentials_dict
            else:
                raise RuntimeError("Google: No credentials available")

            self._service_account_creds = ServiceAccountCreds(
                scopes=self.scopes,
                **creds_dict
            )
        else:
            # User credentials require interactive login
            pass  # Will be set in interactive_login

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
        port: int = 8080,
        redirect_uri: Optional[str] = None
    ) -> None:
        """
        Perform interactive OAuth2 login for user credentials.

        This opens a browser for the user to authenticate.

        Args:
            scopes: Scopes to request (defaults to self.scopes)
            port: Local server port for OAuth redirect
            redirect_uri: Custom redirect URI

        TODO: Implement OAuth2 flow with aiogoogle
        Reference: https://github.com/omarryhan/aiogoogle/blob/master/examples/auth/oauth2.py

        Implementation steps:
        1. Create OAuth2 manager with client credentials
        2. Get authorization URL
        3. Open browser or display device code
        4. Start local server to receive callback
        5. Exchange code for tokens
        6. Store UserCreds
        """
        self.auth_type = 'user'
        scopes = self._process_scopes(scopes or self.scopes)

        self.logger.info("Starting interactive OAuth2 login...")

        raise NotImplementedError(
            "Interactive login not yet implemented. "
            "See aiogoogle OAuth2 examples for implementation guidance: "
            "https://github.com/omarryhan/aiogoogle/blob/master/examples/auth/oauth2.py"
        )

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
