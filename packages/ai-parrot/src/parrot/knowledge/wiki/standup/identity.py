"""Resolve wiki ownership and G9-safe Jira identity."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.project import StandupConfig, parrot_home

_CACHE_FILENAME = "jira_identity.json"
_CACHE_KEYS = frozenset({"account_id", "display_name", "resolved_at"})


class StandupIdentity(BaseModel):
    """Identity used for personal brief filtering; no persisted email."""

    wiki: str
    jira_account_id: str | None = None
    jira_display_name: str | None = None
    git_email: str | None = Field(default=None, exclude=True)
    aliases: list[str] = Field(default_factory=list)


def _cache_path() -> Path:
    """Return the per-user G9-safe Jira identity cache path."""
    return parrot_home() / _CACHE_FILENAME


def _read_cache(path: Path) -> tuple[str, str] | None:
    """Read one fully formed identity cache without exposing unapproved data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or set(payload) != _CACHE_KEYS:
        return None
    account_id = payload.get("account_id")
    display_name = payload.get("display_name")
    resolved_at = payload.get("resolved_at")
    if not all(isinstance(value, str) and value for value in (account_id, display_name, resolved_at)):
        return None
    return account_id, display_name


def _write_cache(path: Path, account_id: str, display_name: str) -> None:
    """Atomically persist only the G9-safe Jira identity projection."""
    payload = {
        "account_id": account_id,
        "display_name": display_name,
        "resolved_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


async def resolve_identity(cfg: StandupConfig, *, explicit: str | None = None, root: Path) -> StandupIdentity:
    """Resolve configured/cache/probed identity, retaining wiki-only fallback.

    Args:
        cfg: Standup configuration containing configured identity values.
        explicit: Optional ``--me`` value.
        root: Project root retained for the public resolver contract.

    Returns:
        The resolved safe identity. Jira failures intentionally leave its
        Jira fields unset so an offline brief remains deterministic.
    """
    del root
    identity = StandupIdentity(
        wiki=cfg.me.wiki or explicit or authoring_identity(None),
        jira_account_id=cfg.me.jira_account_id,
        jira_display_name=cfg.me.jira_display_name,
        aliases=list(cfg.me.aliases),
    )
    if identity.jira_account_id:
        return identity

    cached = await asyncio.to_thread(_read_cache, _cache_path())
    if cached is not None:
        identity.jira_account_id = cached[0]
        identity.jira_display_name = identity.jira_display_name or cached[1]
        return identity

    from parrot.interfaces.jira import JiraInterface

    jira = JiraInterface()
    if jira.auth_type is None:
        return identity
    try:
        person = await jira.myself()
    except Exception:  # noqa: BLE001 -- Jira is optional for an offline brief
        return identity

    identity.jira_account_id = person.account_id
    identity.jira_display_name = identity.jira_display_name or person.display_name
    await asyncio.to_thread(_write_cache, _cache_path(), person.account_id, person.display_name)
    return identity
