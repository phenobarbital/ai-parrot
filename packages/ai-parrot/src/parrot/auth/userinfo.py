"""UserInfoService — curated, structured employee profile (FEAT-406).

Single source of truth for a user's curated `EmployeeProfile`, loaded from
`auth.vw_users` via asyncdb and TTL-cached per user. Feeds both (a) PBAC
`EvalContext`/attribute enrichment (TASK-2114) and (b) `UserinfoTool`
(TASK-2113), which exposes it to the LLM as JSON for the session user only.

Coexists, untouched, alongside the existing prose-based `UserInfo` /
`UserProfileKB` knowledge bases (`parrot/stores/kb/user.py`), which flatten
the same `auth.vw_users` view into `<userdata>` "facts" for the system
prompt — those KBs are NOT modified or replaced by this module (spec §1
non-goal: "Migration/removal of UserInfo/UserProfileKB").

See `sdd/specs/pbac-guardrails.spec.md` §3 Module 4.
"""
import logging
from typing import Any

from asyncdb import AsyncDB
from pydantic import BaseModel

from parrot._imports import lazy_import

from ..stores.kb.cache import TTLCache

logger = logging.getLogger(__name__)


class ManagerRef(BaseModel):
    """Nested reference to a user's manager (resolved spec Q6).

    Attributes:
        user_id: The manager's user id.
        display_name: The manager's display name, if known.
        email: The manager's email, if known.
    """
    user_id: int | str
    display_name: str | None = None
    email: str | None = None


class EmployeeProfile(BaseModel):
    """Curated, structured employee profile from `auth.vw_users`.

    The single structured source of truth for PBAC `EvalContext`
    construction and for `UserinfoTool`'s JSON output — replacing ad hoc
    prose-fact flattening for these two consumers (existing KBs are
    unaffected).

    Attributes:
        user_id: The user's unique identifier.
        username: The user's login/username, if known.
        display_name: The user's display name, if known.
        email: The user's email, if known.
        job_code: The user's job code, if known.
        title: The user's job title, if known.
        department_code: The user's department code, if known.
        groups: The user's PBAC/authorization groups.
        programs: The programs the user is enrolled in.
        worker_type: The user's worker type (e.g. "FTE"), if known.
        manager: The user's manager, as a nested `ManagerRef`, or `None`
            if the user has no recorded manager.
    """
    user_id: int | str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    job_code: str | None = None
    title: str | None = None
    department_code: str | None = None
    groups: list[str] = []
    programs: list[str] = []
    worker_type: str | None = None
    manager: ManagerRef | None = None


class UserInfoService:
    """Loads and TTL-caches curated `EmployeeProfile` rows from `auth.vw_users`.

    Mirrors the lazy DSN + `TTLCache` pattern used by
    `parrot.stores.kb.user.UserInfo`/`UserProfileKB` (`stores/kb/user.py`),
    but returns a single structured Pydantic model instead of prose facts.

    Attributes:
        logger: Standard Python logger.
    """

    def __init__(
        self,
        dsn: str | None = None,
        cache_ttl: int = 600,
        cache_max_size: int = 500,
    ) -> None:
        """Initialize the service.

        Args:
            dsn: Optional explicit Postgres DSN. When omitted, lazily
                resolved from `querysource.conf` (same pattern as
                `stores/kb/user.py:25-26`) on first use.
            cache_ttl: TTL (seconds) for cached profiles. Defaults to 600
                (10 minutes), mirroring `stores/kb/user.py:27-30`.
            cache_max_size: Maximum number of cached profiles.
        """
        self._dsn = dsn
        self._db: AsyncDB | None = None
        self._cache = TTLCache(max_size=cache_max_size, default_ttl=cache_ttl)
        self.logger = logging.getLogger(__name__)

    def _get_db(self) -> AsyncDB:
        """Lazily construct the `AsyncDB` connection using the resolved DSN."""
        if self._db is None:
            dsn = self._dsn
            if dsn is None:
                _qs_conf = lazy_import(
                    "querysource.conf", package_name="querysource", extra="db"
                )
                dsn = _qs_conf.default_dsn
            self._db = AsyncDB('pg', dsn=dsn)
        return self._db

    async def _fetch_manager(self, manager_id: Any) -> ManagerRef | None:
        """Resolve a `manager_id` into a `ManagerRef` via a single extra lookup.

        Args:
            manager_id: The manager's user id, or `None`/falsy.

        Returns:
            A `ManagerRef`, or `None` if `manager_id` is absent or the row
            is not found.
        """
        if not manager_id:
            return None
        db = self._get_db()
        async with await db.connection() as conn:  # pylint: disable=E1101
            row = await conn.fetch_one(
                "SELECT user_id, display_name, email FROM auth.vw_users WHERE user_id = $1",
                manager_id,
            )
        if not row:
            return None
        row = dict(row)
        return ManagerRef(
            user_id=row["user_id"],
            display_name=row.get("display_name"),
            email=row.get("email"),
        )

    async def get_profile(self, user_id: Any) -> EmployeeProfile | None:
        """Fetch (or return the cached) curated `EmployeeProfile` for `user_id`.

        Args:
            user_id: The user's unique identifier.

        Returns:
            The `EmployeeProfile`, or `None` if no matching row exists in
            `auth.vw_users` (never raises for a missing row).
        """
        cache_key = str(user_id)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        db = self._get_db()
        async with await db.connection() as conn:  # pylint: disable=E1101
            row = await conn.fetch_one(
                """
                SELECT user_id, display_name, username, email, job_code, title,
                       department_code, worker_type, manager_id, groups, programs
                FROM auth.vw_users WHERE user_id = $1
                """,
                user_id,
            )

        if not row:
            return None

        row = dict(row)
        manager = await self._fetch_manager(row.get("manager_id"))

        profile = EmployeeProfile(
            user_id=row["user_id"],
            username=row.get("username"),
            display_name=row.get("display_name"),
            email=row.get("email"),
            job_code=row.get("job_code"),
            title=row.get("title"),
            department_code=row.get("department_code"),
            groups=list(row.get("groups") or []),
            programs=list(row.get("programs") or []),
            worker_type=row.get("worker_type"),
            manager=manager,
        )
        await self._cache.set(cache_key, profile)
        return profile
