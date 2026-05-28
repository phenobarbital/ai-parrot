"""OAuth2 provider registry for Telegram bot authentication.

Defines provider configurations (authorization URLs, token endpoints, etc.)
for OAuth2-based login flows. Adding a new provider requires only a new
entry in the OAUTH2_PROVIDERS dict.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class OAuth2ProviderConfig:
    """Configuration for a specific OAuth2 identity provider.

    Attributes:
        name: Provider identifier (e.g. "google", "github").
        authorization_url: URL to redirect the user for authentication.
        token_url: URL to exchange an authorization code for tokens.
        userinfo_url: URL to fetch the authenticated user's profile.
        default_scopes: Default OAuth2 scopes requested if none are
            specified in the bot configuration.
    """

    name: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    default_scopes: list[str] = field(default_factory=list)


OAUTH2_PROVIDERS: Dict[str, OAuth2ProviderConfig] = {
    "google": OAuth2ProviderConfig(
        name="google",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        default_scopes=["openid", "email", "profile"],
    ),
}


def get_provider(name: str) -> OAuth2ProviderConfig:
    """Look up an OAuth2 provider by name.

    Args:
        name: Provider identifier (case-insensitive).

    Returns:
        The matching OAuth2ProviderConfig.

    Raises:
        ValueError: If the provider name is not registered.
    """
    key = name.lower()
    try:
        return OAUTH2_PROVIDERS[key]
    except KeyError:
        available = ", ".join(sorted(OAUTH2_PROVIDERS.keys()))
        raise ValueError(
            f"Unknown OAuth2 provider '{name}'. "
            f"Available providers: {available}"
        )
