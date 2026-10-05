"""Lightweight author attribution shared by wiki commands."""

import getpass
import os


def authoring_identity(by: str | None) -> str:
    """Resolve explicit identity, agent environment, then the local user."""
    if by:
        return by
    for env_name in ("CLAUDE_AGENT_ID", "PARROT_AGENT_ID"):
        value = os.environ.get(env_name)
        if value:
            return f"agent:{value}"
    try:
        return f"human:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 -- no user database in some containers
        return "human:unknown"
