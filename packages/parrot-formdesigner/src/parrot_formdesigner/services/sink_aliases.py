"""Tenant-scoped connection-alias allowlist for submission sinks.

A form's `persistence:` block names a connection **alias**, never a raw
DSN, path, or credential. This module is the operator-controlled
allowlist that maps an alias -> a credential source, resolved through
:func:`parrot_formdesigner.core.auth._get_env` (navconfig first, then
``os.environ``). It is wired explicitly at app construction (an aiohttp
app key — see TASK-2429) and is intentionally NOT runtime-mutable or
DB-backed: it is a security control.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from parrot_formdesigner.core.auth import _get_env


@dataclass(frozen=True)
class _AliasEntry:
    """Internal record for one registered alias.

    Attributes:
        tenant: The tenant this alias is scoped to.
        dsn_env: Name of the env var holding a DSN, if this alias resolves
            a database connection.
        base_dir: Base directory this alias is scoped to, if this alias
            resolves a filesystem location.
        credentials_env: Name of the env var holding opaque credentials
            (e.g. a Google service-account JSON blob), if applicable.
    """

    tenant: str
    dsn_env: str | None = None
    base_dir: str | None = None
    credentials_env: str | None = None


class SinkAliasRegistry:
    """Tenant-scoped allowlist mapping alias -> credential source.

    Wired as an aiohttp app key in ``api/routes.py`` (spec section 8,
    resolved). Resolution delegates to
    :func:`parrot_formdesigner.core.auth._get_env` (navconfig, then
    ``os.environ``); this registry never reads ``os.environ`` directly and
    never logs a resolved credential value.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._aliases: dict[str, _AliasEntry] = {}

    def register(
        self,
        alias: str,
        *,
        tenant: str,
        dsn_env: str | None = None,
        base_dir: str | None = None,
        credentials_env: str | None = None,
    ) -> None:
        """Register an alias for a tenant.

        Args:
            alias: The connection alias name a `FormSchema` may reference.
            tenant: Tenant this alias is scoped to.
            dsn_env: Name of the env var holding a DSN.
            base_dir: Base directory for a filesystem-backed alias.
            credentials_env: Name of the env var holding opaque credentials.
        """
        self._aliases[alias] = _AliasEntry(
            tenant=tenant,
            dsn_env=dsn_env,
            base_dir=base_dir,
            credentials_env=credentials_env,
        )
        self.logger.info(
            "Registered sink alias %r for tenant %r", alias, tenant
        )

    def is_allowed(self, alias: str, *, tenant: str) -> bool:
        """Return whether ``alias`` is registered and scoped to ``tenant``.

        Args:
            alias: The connection alias to check.
            tenant: The tenant requesting to use the alias.

        Returns:
            True if ``alias`` is registered under ``tenant``, else False.
        """
        entry = self._aliases.get(alias)
        return entry is not None and entry.tenant == tenant

    def _require(self, alias: str, *, tenant: str) -> _AliasEntry:
        """Return the entry for ``alias``, enforcing tenant scoping.

        Args:
            alias: The connection alias to resolve.
            tenant: The tenant requesting to use the alias.

        Returns:
            The internal alias entry.

        Raises:
            ValueError: If ``alias`` is unknown, or registered under a
                different tenant.
        """
        entry = self._aliases.get(alias)
        if entry is None:
            raise ValueError(f"Unknown sink alias: {alias!r}")
        if entry.tenant != tenant:
            raise ValueError(
                f"Sink alias {alias!r} is not registered for tenant {tenant!r}"
            )
        return entry

    def resolve_dsn(self, alias: str, *, tenant: str) -> str:
        """Resolve the DSN for a registered database alias.

        Args:
            alias: The connection alias to resolve.
            tenant: The tenant requesting to use the alias.

        Returns:
            The resolved DSN string.

        Raises:
            ValueError: If the alias is unknown, cross-tenant, has no
                ``dsn_env`` configured, or the env var is unset.
        """
        entry = self._require(alias, tenant=tenant)
        if entry.dsn_env is None:
            raise ValueError(f"Sink alias {alias!r} has no DSN configured")
        return _get_env(entry.dsn_env)

    def resolve_base_dir(self, alias: str, *, tenant: str) -> Path:
        """Resolve the base directory for a registered filesystem alias.

        Args:
            alias: The connection alias to resolve.
            tenant: The tenant requesting to use the alias.

        Returns:
            The alias's configured base directory as a ``Path``.

        Raises:
            ValueError: If the alias is unknown, cross-tenant, or has no
                ``base_dir`` configured.
        """
        entry = self._require(alias, tenant=tenant)
        if entry.base_dir is None:
            raise ValueError(f"Sink alias {alias!r} has no base_dir configured")
        return Path(entry.base_dir)

    def resolve_credentials(self, alias: str, *, tenant: str) -> str:
        """Resolve opaque credentials for a registered alias.

        Args:
            alias: The connection alias to resolve.
            tenant: The tenant requesting to use the alias.

        Returns:
            The resolved credentials string (e.g. a path or JSON blob name).

        Raises:
            ValueError: If the alias is unknown, cross-tenant, has no
                ``credentials_env`` configured, or the env var is unset.
        """
        entry = self._require(alias, tenant=tenant)
        if entry.credentials_env is None:
            raise ValueError(
                f"Sink alias {alias!r} has no credentials configured"
            )
        return _get_env(entry.credentials_env)

    def contain(self, alias: str, *, tenant: str, relative_path: str) -> Path:
        """Resolve ``relative_path`` against the alias's base dir, safely.

        Joins ``relative_path`` onto the alias's base directory and
        rejects any result whose resolved real path escapes that base
        directory (including via a symlink).

        Args:
            alias: The filesystem-backed connection alias.
            tenant: The tenant requesting to use the alias.
            relative_path: Path relative to the alias's base directory.

        Returns:
            The resolved, contained absolute path.

        Raises:
            ValueError: If the alias is unknown/cross-tenant, or the
                resolved path escapes the base directory.
        """
        base = self.resolve_base_dir(alias, tenant=tenant).resolve()
        candidate = (base / relative_path).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError(
                f"Path {relative_path!r} escapes the base directory for "
                f"alias {alias!r}"
            )
        return candidate
