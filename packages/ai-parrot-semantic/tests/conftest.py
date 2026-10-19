"""Shared fixtures for ai-parrot-semantic tests: subjects and PBAC guard doubles."""
from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth import DataPlanePolicyGuard, PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def pctx_factory() -> Callable[..., PermissionContext]:
    """Build PermissionContext(UserSession(...)) for subjects A/B."""

    def _make(
        user_id: str = "user-a",
        tenant_id: str = "t1",
        roles: tuple[str, ...] = ("analyst",),
        **metadata: Any,
    ) -> PermissionContext:
        session = UserSession(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=frozenset(roles),
            metadata=dict(metadata),
        )
        return PermissionContext(session=session)

    return _make


def _guard(authorize_side_effect: Any = None) -> MagicMock:
    guard = MagicMock(spec=DataPlanePolicyGuard)
    guard.authorize_source = AsyncMock(side_effect=authorize_side_effect)
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


@pytest.fixture
def allow_all_guard() -> MagicMock:
    """Guard double that authorizes every resource."""
    return _guard()


@pytest.fixture
def deny_table_guard() -> Callable[[str], MagicMock]:
    """Factory: guard double denying `table:read` for one `schema.table`."""

    def _make(table: str) -> MagicMock:
        async def _authorize(ctx: Any, resources: Any) -> None:
            tables = getattr(resources, "tables", None) or []
            for entry in tables:
                if str(entry) == table or str(entry).endswith(f":{table}"):
                    raise AuthorizationRequired(
                        tool_name="dataplane_authz",
                        message=f"table:read denied for {table}",
                    )
            return None

        return _guard(_authorize)

    return _make
