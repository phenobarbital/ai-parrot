"""RBACService — policies ABAC/PBAC (nav-auth format) + RBACContext.

Implementa Module 3 de FEAT-302 (C4 RESUELTO §8):

- **NO** motor RBAC paralelo.
- **NO** columna ``scope`` en ``auth.permissions``.
- **NUNCA** escribe en ``auth.user_permissions``.

Las policies son declarativas, compatibles con el formato YAML del engine
ABAC/PBAC de nav-auth, persistidas como JSONB en ``fieldsync.auth_policies``.
El enforcement autoritativo lo ejecuta nav-auth; este módulo gestiona la
emisión, almacenamiento y compilación de policies, y proyecta el
``RBACContext`` a los handlers para shadow-mode gate-keeping.

``RBACScope`` es vocabulario de alto nivel que se **compila** a una ``Policy``
ABAC antes de persistir:

- ``own``    → subjects.users = [user_id]
- ``team``   → subjects.groups = [team/<program_id>]
- ``client`` → conditions.resource.client_id = (computed)
- ``global`` → sin restricción de subjects/conditions

Ejemplo de policy referencia (§8)::

    Policy(
        name="eng_agents_biz_hours",
        effect="allow",
        description="Engineering agents during business hours",
        resources=["agent:*"],
        actions=["agent:chat"],
        subjects={"groups": ["engineering", "developers"]},
        conditions={"environment": {"is_business_hours": True}},
        priority=20,
        enforcing=False,
    )

Uso::

    svc = RBACService(pool)
    record = await svc.assign_role(
        "user-abc",
        program_id=7,
        codename="edit_form",
        scope=RBACScope.OWN,
        tenant="acme",
    )
    ctx = await svc.resolve("user-abc", program_id=7, tenant="acme")
    ctx.has_permission("edit_form", scope=RBACScope.OWN)   # → True
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RBACScope vocabulary
# ---------------------------------------------------------------------------


class RBACScope(str, Enum):
    """Vocabulary of RBAC scopes that compile to ABAC policies.

    Values:
        OWN: Access restricted to resources owned by the user.
        TEAM: Access to resources owned by the user's team.
        CLIENT: Access to all resources within a client boundary.
        GLOBAL: Unrestricted access within a tenant.
    """

    OWN = "own"
    TEAM = "team"
    CLIENT = "client"
    GLOBAL = "global"


# Scope hierarchy: lower index = narrower scope.
_SCOPE_ORDER = [RBACScope.OWN, RBACScope.TEAM, RBACScope.CLIENT, RBACScope.GLOBAL]


def _scope_level(scope: RBACScope) -> int:
    """Return the numeric level of a scope (0 = narrowest, 3 = widest)."""
    try:
        return _SCOPE_ORDER.index(scope)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Policy model (nav-auth ABAC/PBAC format)
# ---------------------------------------------------------------------------


class Policy(BaseModel):
    """Declarative ABAC/PBAC policy — mirrors the nav-auth YAML format.

    Attributes:
        name: Unique policy identifier (UNIQUE constraint in DB).
        effect: "allow" or "deny".
        description: Human-readable description.
        resources: List of resource patterns (e.g. ``["form:*", "agent:chat"]``).
        actions: List of permitted/denied action patterns.
        subjects: Dict with ``groups`` and/or ``users`` keys.
        conditions: Optional conditions dict (e.g. environment, resource).
        priority: Numeric priority; lower = evaluated first. Default 50.
        enforcing: When False, policy is in shadow mode (log only). Default False.
        tenant: Tenant scope for this policy, or None for global.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    effect: Literal["allow", "deny"] = "allow"
    description: str = ""
    resources: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    subjects: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    priority: int = 50
    enforcing: bool = False
    tenant: str | None = None


# ---------------------------------------------------------------------------
# PermissionRecord — a compiled permission entry
# ---------------------------------------------------------------------------


class PermissionRecord(BaseModel):
    """A compiled permission entry (result of assign_role).

    Attributes:
        user_id: The user this record belongs to.
        codename: Permission code (e.g. "edit_form").
        scope: The ``RBACScope`` the permission was issued with.
        program_id: Program context for the permission.
        policy_name: Name of the generated ``Policy`` in DB.
        tenant: Tenant this record is scoped to.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    codename: str
    scope: RBACScope
    program_id: int
    policy_name: str
    tenant: str


# ---------------------------------------------------------------------------
# RBACContext — runtime permission projection
# ---------------------------------------------------------------------------


class RBACContext(BaseModel):
    """Runtime RBAC context projected for a user in a program.

    Used by handlers for shadow-mode gate-keeping. The authoritative
    enforcement lives in nav-auth.

    Attributes:
        user_id: Authenticated user identifier.
        program_id: Program context.
        permissions: List of ``PermissionRecord`` resolved for this user.
        groups: Group memberships resolved from ``auth.*`` (read-only).
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    program_id: int
    permissions: list[PermissionRecord] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)

    def has_permission(
        self,
        codename: str,
        scope: RBACScope | None = None,
    ) -> bool:
        """Return True if the user has the given permission at the given scope.

        Scope enforcement: a permission issued at scope S grants access
        to scope S' only if S' is at least as narrow as S (i.e.
        ``level(S') <= level(S)``).

        Args:
            codename: Permission codename to check.
            scope: Required scope level. When ``None``, any scope matches.

        Returns:
            True if at least one matching ``PermissionRecord`` is found.
        """
        for rec in self.permissions:
            if rec.codename != codename:
                continue
            if scope is None:
                return True
            # The requested scope must be ≤ the granted scope level
            if _scope_level(scope) <= _scope_level(rec.scope):
                return True
        return False


# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_INSERT_POLICY_SQL = """
INSERT INTO fieldsync.auth_policies (name, policy, tenant, priority, enforcing)
VALUES ($1, $2::jsonb, $3, $4, $5)
ON CONFLICT (name) DO UPDATE
    SET policy    = EXCLUDED.policy,
        tenant    = EXCLUDED.tenant,
        priority  = EXCLUDED.priority,
        enforcing = EXCLUDED.enforcing,
        updated_at = NOW()
RETURNING id, name, policy, tenant, priority, enforcing
"""

_SELECT_POLICY_SQL = """
SELECT id, name, policy, tenant, priority, enforcing
FROM fieldsync.auth_policies
WHERE name = $1
"""

_SELECT_POLICIES_BY_TENANT_SQL = """
SELECT id, name, policy, tenant, priority, enforcing
FROM fieldsync.auth_policies
WHERE tenant = $1
ORDER BY priority, name
"""

_DELETE_POLICY_SQL = """
DELETE FROM fieldsync.auth_policies
WHERE name = $1
"""

# Read-only query against auth.* — NEVER write here
_SELECT_USER_GROUPS_SQL = """
SELECT g.name AS group_name
FROM auth.groups g
JOIN auth.user_groups ug ON ug.group_id = g.id
WHERE ug.user_id = $1
"""

# ---------------------------------------------------------------------------
# Helper: compile scope → Policy
# ---------------------------------------------------------------------------


def _compile_scope_to_policy(
    user_id: str,
    *,
    program_id: int,
    codename: str,
    scope: RBACScope,
    tenant: str,
) -> Policy:
    """Compile a (user_id, codename, scope) triple into a nav-auth ABAC policy.

    Args:
        user_id: The user receiving the permission.
        program_id: Program context for the permission.
        codename: Permission codename.
        scope: RBACScope vocabulary value.
        tenant: Tenant this policy belongs to.

    Returns:
        A ``Policy`` instance ready to persist in ``fieldsync.auth_policies``.
    """
    policy_name = f"user__{user_id}__{codename}__{scope.value}__prog{program_id}"

    subjects: dict[str, Any] = {}
    conditions: dict[str, Any] = {}

    if scope == RBACScope.OWN:
        subjects = {"users": [user_id]}
    elif scope == RBACScope.TEAM:
        subjects = {"groups": [f"team/{program_id}"]}
    elif scope == RBACScope.CLIENT:
        conditions = {"resource": {"program_id": program_id}}
    # GLOBAL: no subjects/conditions restriction

    return Policy(
        name=policy_name,
        effect="allow",
        description=f"Compiled from assign_role: {user_id} / {codename} / {scope.value}",
        resources=["form:*"],
        actions=[codename],
        subjects=subjects,
        conditions=conditions,
        priority=50,
        enforcing=False,
        tenant=tenant,
    )


# ---------------------------------------------------------------------------
# RBACService
# ---------------------------------------------------------------------------


class RBACService:
    """Manage ABAC/PBAC policies in ``fieldsync.auth_policies`` + project context.

    All writes target ``fieldsync.*`` exclusively — NEVER ``auth.*``.
    Auth tables are only read (read-only pool) for group resolution.

    Args:
        pool: asyncpg pool (or fake pool for tests).

    Example::

        svc = RBACService(pool)
        record = await svc.assign_role(
            "user-1", program_id=7, codename="edit_form",
            scope=RBACScope.OWN, tenant="acme"
        )
        ctx = await svc.resolve("user-1", program_id=7, tenant="acme")
        assert ctx.has_permission("edit_form", scope=RBACScope.OWN)
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Policy CRUD
    # ------------------------------------------------------------------

    async def create_policy(self, policy: Policy) -> Policy:
        """Upsert a policy in ``fieldsync.auth_policies``.

        If a policy with the same ``name`` already exists, its content is
        updated (ON CONFLICT DO UPDATE).

        Args:
            policy: ``Policy`` instance to persist.

        Returns:
            The persisted ``Policy`` (reflected from DB row).
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _INSERT_POLICY_SQL,
                policy.name,
                json.dumps(policy.model_dump(mode="json")),
                policy.tenant,
                policy.priority,
                policy.enforcing,
            )
        return self._row_to_policy(row)

    async def get_policy(self, name: str) -> Policy | None:
        """Retrieve a policy by name.

        Args:
            name: Unique policy name.

        Returns:
            ``Policy`` or ``None`` if not found.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_POLICY_SQL, name)
        if row is None:
            return None
        return self._row_to_policy(row)

    async def list_policies(self, *, tenant: str) -> list[Policy]:
        """List all policies for a tenant, ordered by priority.

        Args:
            tenant: Tenant slug to filter by.

        Returns:
            List of ``Policy`` instances (empty if none found).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_POLICIES_BY_TENANT_SQL, tenant)
        return [self._row_to_policy(row) for row in rows]

    async def delete_policy(self, name: str) -> bool:
        """Delete a policy by name.

        Args:
            name: Unique policy name.

        Returns:
            True if the policy was deleted; False if it did not exist.
        """
        async with self._pool.acquire() as conn:
            status = await conn.execute(_DELETE_POLICY_SQL, name)
        # asyncpg returns "DELETE N"
        try:
            deleted_count = int(status.split()[-1])
        except (IndexError, ValueError):
            deleted_count = 0
        return deleted_count > 0

    # ------------------------------------------------------------------
    # Role assignment
    # ------------------------------------------------------------------

    async def assign_role(
        self,
        user_id: str,
        *,
        program_id: int,
        codename: str,
        scope: RBACScope,
        tenant: str,
    ) -> PermissionRecord:
        """Compile (user_id, codename, scope) to a Policy and persist it.

        NEVER writes to ``auth.user_permissions``.
        The compiled policy is stored in ``fieldsync.auth_policies`` (JSONB).

        Args:
            user_id: User to assign the role to.
            program_id: Program context.
            codename: Permission codename.
            scope: ``RBACScope`` level.
            tenant: Tenant this assignment belongs to.

        Returns:
            ``PermissionRecord`` reflecting the persisted policy.
        """
        policy = _compile_scope_to_policy(
            user_id,
            program_id=program_id,
            codename=codename,
            scope=scope,
            tenant=tenant,
        )
        await self.create_policy(policy)
        self.logger.info(
            "assign_role: user=%s codename=%s scope=%s tenant=%s → policy=%s",
            user_id,
            codename,
            scope.value,
            tenant,
            policy.name,
        )
        return PermissionRecord(
            user_id=user_id,
            codename=codename,
            scope=scope,
            program_id=program_id,
            policy_name=policy.name,
            tenant=tenant,
        )

    # ------------------------------------------------------------------
    # Context resolution
    # ------------------------------------------------------------------

    async def resolve(
        self,
        user_id: str,
        *,
        program_id: int,
        tenant: str,
    ) -> RBACContext:
        """Build ``RBACContext`` for a user by reading ``fieldsync.auth_policies``.

        Reads policies from ``fieldsync.auth_policies`` for the tenant.
        Optionally reads group memberships from ``auth.groups`` / ``auth.user_groups``
        (read-only). Falls back to empty groups list if auth tables are unavailable.

        Args:
            user_id: Authenticated user identifier.
            program_id: Program context.
            tenant: Tenant slug.

        Returns:
            ``RBACContext`` with permissions and groups populated.
        """
        policies = await self.list_policies(tenant=tenant)

        permissions: list[PermissionRecord] = []
        for policy in policies:
            # Only include allow policies that target this user
            if policy.effect != "allow":
                continue
            # Check if this policy was compiled for this user
            if policy.name.startswith(f"user__{user_id}__"):
                # Parse scope and codename from policy name:
                # "user__<uid>__<codename>__<scope>__prog<pid>"
                parts = policy.name.split("__")
                if len(parts) >= 4:
                    codename = parts[2]
                    scope_str = parts[3]
                    prog_str = parts[4] if len(parts) > 4 else f"prog{program_id}"
                    try:
                        scope = RBACScope(scope_str)
                        rec_program_id = int(prog_str.replace("prog", ""))
                    except (ValueError, IndexError):
                        continue
                    permissions.append(
                        PermissionRecord(
                            user_id=user_id,
                            codename=codename,
                            scope=scope,
                            program_id=rec_program_id,
                            policy_name=policy.name,
                            tenant=tenant,
                        )
                    )

        # Try to read group memberships (read-only, auth.* best-effort)
        groups: list[str] = []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_USER_GROUPS_SQL, user_id)
            groups = [row["group_name"] for row in rows]
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(
                "resolve: could not read auth.user_groups for %s: %s", user_id, exc
            )

        return RBACContext(
            user_id=user_id,
            program_id=program_id,
            permissions=permissions,
            groups=groups,
        )

    # ------------------------------------------------------------------
    # Revoke all
    # ------------------------------------------------------------------

    async def revoke_all(self, user_id: str, *, tenant: str) -> int:
        """Delete all policies compiled for ``user_id`` in ``tenant``.

        NEVER touches ``auth.user_permissions``.

        Args:
            user_id: User whose compiled policies should be deleted.
            tenant: Tenant scope.

        Returns:
            Number of policies deleted.
        """
        # Fetch matching policies and delete by name (safer than LIKE on JSONB)
        policies = await self.list_policies(tenant=tenant)
        deleted = 0
        for pol in policies:
            if pol.name.startswith(f"user__{user_id}__"):
                ok = await self.delete_policy(pol.name)
                if ok:
                    deleted += 1
        self.logger.info(
            "revoke_all: user=%s tenant=%s → %d policies deleted",
            user_id,
            tenant,
            deleted,
        )
        return deleted

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_policy(row: Any) -> Policy:
        """Deserialise a DB row (from ``fieldsync.auth_policies``) to ``Policy``.

        Args:
            row: asyncpg Record (or compatible dict-like).

        Returns:
            ``Policy`` instance.
        """
        raw = row["policy"]
        if isinstance(raw, str):
            policy_data = json.loads(raw)
        else:
            policy_data = dict(raw)  # asyncpg returns a dict for JSONB

        # Merge DB-level fields (may override JSONB body)
        policy_data["name"] = row["name"]
        policy_data["tenant"] = row["tenant"]
        policy_data["priority"] = row["priority"]
        policy_data["enforcing"] = row["enforcing"]

        return Policy(**{k: v for k, v in policy_data.items() if k in Policy.model_fields})
