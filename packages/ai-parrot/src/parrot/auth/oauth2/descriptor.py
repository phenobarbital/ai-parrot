"""Typed OAuth2 provider descriptors (FEAT-773 M3, S10).

Descriptors are data; provider-specific post-exchange behaviour is a Python callable registered by name.
Client credentials never live in a descriptor — they come from navconfig ``OAUTH2_<PROVIDER>_*``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Union

import aiohttp
import yaml
from navconfig import config
from pydantic import BaseModel, Field, ValidationError, model_validator

from parrot.auth.oauth2.events import ConnectionEventPublisher
from parrot.auth.oauth2.registry import OAuth2Provider, register_oauth2_provider
from parrot.auth.oauth2_base import (
    AbstractOAuth2Manager,
    AbstractOAuth2TokenSet,
    CredentialStore,
    InvalidGrantError,
    RefreshTransientError,
)

logger = logging.getLogger(__name__)

_FORBIDDEN_KEYS = frozenset({"client_id", "client_secret", "redirect_uri"})


class RefreshPolicy(BaseModel):
    """Informational refresh facts (R6). A returned refresh_token ALWAYS replaces the stored one."""

    rotating: bool = False
    sliding: bool = False
    refresh_lifetime_s: Optional[int] = None
    access_lifetime_s: Optional[int] = None


class IdentityProbe(BaseModel):
    url: str
    account_id_path: str
    display_name_path: Optional[str] = None
    email_path: Optional[str] = None


class OAuth2ProviderDescriptor(BaseModel):
    model_config = {"hide_input_in_errors": True}

    provider_id: str
    display_name: str
    icon: str = ""
    authorization_url: str
    token_url: str
    revoke_url: Optional[str] = None
    default_scopes: List[str]
    client_type: Literal["confidential", "public"] = "confidential"
    pkce: Literal["required", "optional", "none"] = "required"
    refresh_policy: RefreshPolicy = Field(default_factory=RefreshPolicy)
    identity_probe: Optional[IdentityProbe] = None
    extra_authorize_params: Dict[str, str] = Field(default_factory=dict)
    post_exchange: Optional[str] = None
    pbac_action_namespace: str = "integration"

    @model_validator(mode="before")
    @classmethod
    def _reject_secrets(cls, data: Any) -> Any:
        """Descriptors must never carry client credentials."""
        if isinstance(data, Mapping):
            for key in _FORBIDDEN_KEYS:
                if key in data:
                    raise ValueError(f"descriptor must not include {key}")
        return data


PostExchangeHook = Callable[[Any, Dict[str, Any], "AbstractOAuth2TokenSet"], Awaitable["AbstractOAuth2TokenSet"]]


class PostExchangeHookRegistry:
    """Typed in-code registry of post-exchange hooks (S10). Never imports by path."""

    def __init__(self) -> None:
        self._hooks: Dict[str, PostExchangeHook] = {}

    def register(self, name: str, fn: PostExchangeHook) -> None:
        """Register a callable under a non-empty hook name."""
        if not callable(fn):
            raise TypeError("post-exchange hook must be callable")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("post-exchange hook name must not be empty")
        self._hooks[name] = fn

    def get(self, name: str) -> PostExchangeHook:
        """Return the hook; raise ``KeyError`` naming it when unknown."""
        try:
            return self._hooks[name]
        except KeyError:
            raise KeyError(f"unknown post_exchange hook {name!r}") from None


post_exchange_hooks = PostExchangeHookRegistry()


def load_provider_descriptors(
    source: Union[str, Path, Sequence[Mapping[str, Any]]],
) -> List[OAuth2ProviderDescriptor]:
    """Load descriptors from a YAML file (``OAUTH2_PROVIDERS_FILE``) or mappings.

    Raises:
        ValueError: invalid entry (message names the provider_id) or duplicate provider_id.
    """
    if isinstance(source, (str, Path)):
        try:
            with Path(source).open(encoding="utf-8") as descriptor_file:
                loaded: Any = yaml.safe_load(descriptor_file)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid provider descriptor YAML: {exc}") from exc
    else:
        loaded = source

    if isinstance(loaded, Mapping):
        loaded = loaded.get("providers")
    if not isinstance(loaded, Sequence) or isinstance(loaded, (str, bytes, bytearray)):
        raise ValueError("provider descriptors must be a sequence or a mapping with a providers sequence")

    descriptors: List[OAuth2ProviderDescriptor] = []
    provider_ids = set()
    for index, entry in enumerate(loaded):
        provider_name = entry.get("provider_id", f"#{index}") if isinstance(entry, Mapping) else f"#{index}"
        if not isinstance(entry, Mapping):
            raise ValueError(f"invalid provider descriptor for {provider_name}")
        for forbidden_key in _FORBIDDEN_KEYS:
            if forbidden_key in entry:
                raise ValueError(
                    f"invalid provider descriptor for {provider_name}: descriptor must not include {forbidden_key}"
                )
        try:
            descriptor = OAuth2ProviderDescriptor.model_validate(entry)
        except ValidationError as exc:
            raise ValueError(f"invalid provider descriptor for {provider_name}: {exc}") from exc
        if descriptor.provider_id in provider_ids:
            raise ValueError(f"duplicate provider_id {descriptor.provider_id!r}")
        provider_ids.add(descriptor.provider_id)
        descriptors.append(descriptor)
    return descriptors


class StandardOAuth2Manager(AbstractOAuth2Manager):
    """Descriptor-driven RFC 6749 manager: endpoints, scopes, PKCE, extra params, probe, hook, revoke."""

    def __init__(
        self,
        descriptor: OAuth2ProviderDescriptor,
        *,
        client_id: str,
        client_secret: Optional[str],
        redirect_uri: str,
        hooks: Optional[PostExchangeHookRegistry] = None,
        **manager_kwargs: Any,
    ) -> None:
        self.descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self.authorization_url = descriptor.authorization_url
        self.token_url = descriptor.token_url
        self.default_scopes = list(descriptor.default_scopes)
        self.use_pkce = descriptor.pkce != "none"
        self.require_client_secret = descriptor.client_type == "confidential"
        self._hooks = hooks or post_exchange_hooks
        super().__init__(client_id, redirect_uri, client_secret=client_secret, **manager_kwargs)

    def authorization_url_extra_params(self) -> Dict[str, str]:
        """Return descriptor-defined authorization parameters."""
        return dict(self.descriptor.extra_authorize_params)

    async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
        """Exchange an authorization code at the descriptor token endpoint."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
        }
        if self.require_client_secret:
            data["client_secret"] = self.client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        session = await self._get_session()
        async with session.post(self.token_url, data=data) as response:
            if response.status != 200:
                raise ValueError(f"{self.provider_id} token exchange failed with status {response.status}")
            try:
                payload = await response.json()
            except (aiohttp.ContentTypeError, ValueError) as exc:
                raise ValueError(f"{self.provider_id} token exchange returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{self.provider_id} token exchange returned an invalid response")
        return payload

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh a token and classify provider and transport failures."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        if self.require_client_secret:
            data["client_secret"] = self.client_secret

        try:
            session = await self._get_session()
            async with session.post(self.token_url, data=data) as response:
                status = response.status
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise RuntimeError(f"{self.provider_id} refresh returned invalid JSON") from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RefreshTransientError(f"{self.provider_id} refresh transport error") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"{self.provider_id} refresh returned an invalid response")
        if payload.get("error") == "invalid_grant":
            raise InvalidGrantError(f"{self.provider_id} refresh grant is invalid")
        if status == 429 or status >= 500:
            raise RefreshTransientError(f"{self.provider_id} refresh temporarily unavailable (HTTP {status})")
        if status != 200:
            raise RuntimeError(f"{self.provider_id} refresh failed with status {status}")
        if "access_token" not in payload:
            raise RuntimeError(f"{self.provider_id} refresh response did not contain an access token")
        return payload

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        """Fetch and normalize identity fields using descriptor JSON paths."""
        probe = self.descriptor.identity_probe
        if probe is None:
            return {}

        session = await self._get_session()
        async with session.get(probe.url, headers={"Authorization": f"Bearer {access_token}"}) as response:
            if response.status != 200:
                raise ValueError(f"{self.provider_id} identity probe failed with status {response.status}")
            try:
                document = await response.json()
            except (aiohttp.ContentTypeError, ValueError) as exc:
                raise ValueError(f"{self.provider_id} identity probe returned invalid JSON") from exc

        account_id = _json_path(document, probe.account_id_path)
        if account_id is None:
            raise ValueError(f"identity probe did not contain account id path {probe.account_id_path!r}")
        return {
            "account_id": str(account_id),
            "display_name": _json_path(document, probe.display_name_path),
            "email": _json_path(document, probe.email_path),
        }

    def _build_token_set(
        self,
        token_payload: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> AbstractOAuth2TokenSet:
        """Build a generic token set from an RFC 6749 response and identity."""
        now = time.time()
        scopes = token_payload.get("scope", "")
        if isinstance(scopes, str):
            parsed_scopes = scopes.split()
        elif isinstance(scopes, list):
            parsed_scopes = [str(scope) for scope in scopes]
        else:
            parsed_scopes = []
        return self.token_set_cls(
            access_token=token_payload["access_token"],
            refresh_token=token_payload.get("refresh_token", ""),
            expires_at=now + int(token_payload.get("expires_in", 3600)),
            scopes=parsed_scopes,
            granted_at=now,
            last_refreshed_at=now,
            account_id=identity.get("account_id", ""),
            display_name=identity.get("display_name") or "",
            email=identity.get("email"),
        )

    async def _post_exchange(
        self,
        token_response: Dict[str, Any],
        token_set: AbstractOAuth2TokenSet,
    ) -> AbstractOAuth2TokenSet:
        """Run the named post-exchange hook, when configured."""
        if not self.descriptor.post_exchange:
            return token_set
        hook = self._hooks.get(self.descriptor.post_exchange)
        return await hook(self, token_response, token_set)

    async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
        """Best-effort RFC 7009-style revocation at the descriptor endpoint."""
        if self.descriptor.revoke_url is None:
            return
        token = token_set.refresh_token or token_set.access_token
        data = {
            "token": token,
            "token_type_hint": "refresh_token" if token_set.refresh_token else "access_token",
            "client_id": self.client_id,
        }
        if self.require_client_secret:
            data["client_secret"] = self.client_secret
        try:
            session = await self._get_session()
            async with session.post(self.descriptor.revoke_url, data=data) as response:
                if not 200 <= response.status < 300:
                    self.logger.warning(
                        "%s remote revoke failed with status %s",
                        self.provider_id,
                        response.status,
                    )
        except Exception as exc:  # noqa: BLE001 - remote revocation is explicitly best effort
            self.logger.warning("%s remote revoke transport failure: %s", self.provider_id, type(exc).__name__)


def _json_path(document: Any, path: Optional[str]) -> Any:
    """Resolve a dotted path (integer segments index lists); None when absent."""
    if path is None:
        return None
    current = document
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


class DescriptorOAuth2Provider(OAuth2Provider):
    """Registry entry backed by a descriptor and StandardOAuth2Manager."""

    def __init__(
        self,
        descriptor: OAuth2ProviderDescriptor,
        manager: StandardOAuth2Manager,
        toolkit_factory_fn: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.provider_id = descriptor.provider_id
        self.display_name = descriptor.display_name
        self.icon = descriptor.icon
        self.default_scopes = list(descriptor.default_scopes)
        self.pbac_action_namespace = descriptor.pbac_action_namespace
        self._manager = manager
        self._toolkit_factory_fn = toolkit_factory_fn

    @property
    def manager(self) -> StandardOAuth2Manager:
        """Return the descriptor-backed manager."""
        return self._manager

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        """Return None unless a factory was supplied."""
        return self._toolkit_factory_fn(credential_resolver) if self._toolkit_factory_fn else None


def register_descriptor_providers(
    descriptors: Sequence[OAuth2ProviderDescriptor],
    *,
    app: Any,
    credential_store: Optional[CredentialStore],
    event_publisher: Optional[ConnectionEventPublisher],
) -> List[DescriptorOAuth2Provider]:
    """Build and register configured descriptor providers."""
    providers: List[DescriptorOAuth2Provider] = []
    for descriptor in descriptors:
        key = descriptor.provider_id.upper()
        client_id = config.get(f"OAUTH2_{key}_CLIENT_ID")
        client_secret = config.get(f"OAUTH2_{key}_CLIENT_SECRET")
        redirect_uri = config.get(f"OAUTH2_{key}_REDIRECT_URI")
        if not client_id:
            logger.warning("Skipping OAuth2 provider %s: client id is not configured", descriptor.provider_id)
            continue
        if not redirect_uri:
            logger.warning("Skipping OAuth2 provider %s: redirect URI is not configured", descriptor.provider_id)
            continue
        if descriptor.client_type == "confidential" and not client_secret:
            logger.warning("Skipping OAuth2 provider %s: client secret is not configured", descriptor.provider_id)
            continue

        manager = StandardOAuth2Manager(
            descriptor,
            client_id=str(client_id),
            client_secret=str(client_secret) if client_secret else None,
            redirect_uri=str(redirect_uri),
            app=app,
            credential_store=credential_store,
            event_publisher=event_publisher,
        )
        manager.setup()
        provider = DescriptorOAuth2Provider(descriptor, manager)
        register_oauth2_provider(provider)
        providers.append(provider)
    return providers
