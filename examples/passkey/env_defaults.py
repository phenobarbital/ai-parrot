"""Environment defaults for the passkey example.

Imported BEFORE any ``navigator_auth``/``navconfig`` import: those read their
settings at import time. Every value can be overridden from the shell.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PORT = os.environ.get("DEMO_PORT", "5000")

_DEFAULTS = {
    # Local dev stack: docker_postgres_1 (navigator DB, real auth.users) + docker_redis_1
    "DBHOST": "localhost",
    "DBPORT": "5432",
    "DBUSER": "troc_pgdata",
    "DBPWD": "12345678",
    "DBNAME": "navigator",
    "REDIS_AUTH_URL": "redis://localhost:6379/10",
    "CACHE_HOST": "localhost",
    "CACHE_PORT": "6379",
    "CACHEDB": "11",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_DB": "10",
    "REDIS_URL": "redis://localhost:6379/10",
    # Isolation: no database-backed bots and an empty agents directory (the repo's own agents/ is NOT loaded).
    "ENABLE_DATABASE_BOTS": "false",
    "AGENTS_DIR": str(Path(tempfile.gettempdir()) / "parrot-passkey-demo-agents"),
    # Auth: password sign-in plus passkeys
    "AUTHENTICATION_BACKENDS": "navigator_auth.backends.BasicAuth,navigator_auth.backends.PasskeyAuth",
    "PASSKEY_USER_VERIFICATION": "preferred",
    "PASSKEY_LOGIN_OPTIONS_RATE": "0",
    # One entry per EXACT browser origin. localhost counts as a secure context.
    "PASSKEY_RELYING_PARTIES": json.dumps(
        [{"origin": f"http://localhost:{PORT}", "rp_id": "localhost", "rp_name": "AI-Parrot demo"}]
    ),
}


def apply_defaults() -> None:
    """Force the demo settings into navconfig, ahead of any ``parrot``/``navigator_auth`` import.

    ``navconfig`` loads ``env/.env`` and prefers it over ``os.environ``, so a plain ``setdefault`` would
    silently leave a developer's real DB/Redis in charge. ``config.set`` wins over the file; a variable you
    export yourself still wins over these defaults.
    """
    from navconfig import config

    Path(_DEFAULTS["AGENTS_DIR"]).mkdir(parents=True, exist_ok=True)
    for key, value in _DEFAULTS.items():
        value = os.environ.get(f"DEMO_{key}", value)
        os.environ[key] = value
        config.set(key, value)
