"""Typed OAuth2 provider descriptors (FEAT-773 M3, S10).

Descriptors are data; provider-specific post-exchange behaviour is a Python callable registered by name.
Client credentials never live in a descriptor — they come from navconfig ``OAUTH2_<PROVIDER>_*``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from parrot.auth.oauth2_base import AbstractOAuth2TokenSet

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
