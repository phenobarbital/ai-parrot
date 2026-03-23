"""Generate Matrix Application Service registration YAML.

Produces a Synapse/Conduit/Tuwunel-compatible registration file
that must be placed in the homeserver data directory and referenced
in homeserver.yaml under `app_service_config_files`.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import secrets

import yaml


def generate_tokens() -> tuple[str, str]:
    """Generate random AS and HS tokens."""
    return secrets.token_hex(32), secrets.token_hex(32)


def generate_registration(
    as_token: str,
    hs_token: str,
    *,
    bot_localpart: str = "parrot",
    namespace_regex: str = "parrot-.*",
    as_url: str = "http://localhost:9090",
    as_id: str = "ai-parrot",
    output_path: Optional[str] = None,
) -> dict:
    """Generate an AS registration YAML.

    Args:
        as_token: Application Service token (AS → HS auth).
        hs_token: Homeserver token (HS → AS auth).
        bot_localpart: Localpart for the bot user.
        namespace_regex: Regex for the exclusive user namespace.
        as_url: URL where the AS HTTP server listens.
        as_id: Unique identifier for this AS.
        output_path: If provided, write YAML to this path.

    Returns:
        The registration dict.
    """
    registration = {
        "id": as_id,
        "url": as_url,
        "as_token": as_token,
        "hs_token": hs_token,
        "sender_localpart": bot_localpart,
        "rate_limited": False,
        "namespaces": {
            "users": [
                {
                    "exclusive": True,
                    "regex": f"@{namespace_regex}:.*",
                },
            ],
            "rooms": [],
            "aliases": [],
        },
    }

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(registration, f, default_flow_style=False)

    return registration
