"""Persistence for eligibility rules, and the navrules storage adapter.

Two classes with different audiences. :class:`RuleRepository` is ours — it
inherits :class:`~parrot_saas.db.repository.BaseRepository`, so every statement
goes through helpers that bind ``tenant_id`` as ``$1`` and refuse SQL that does
not mention it. :class:`PostgresRuleStorage` is navrules' — a thin
``AbstractStorage`` bound to one ``(tenant_id, ruleset)`` pair that delegates to
the repository.

Splitting them that way keeps the isolation discipline in one place while still
handing navrules the contract it expects: ``load()`` takes no arguments, because
the scope belongs to the construction rather than the call.

**On why this lives here and not in navrules**: navrules declares
``dependencies = []`` deliberately and its ``storages/`` package is stdlib-only.
Putting ``asyncdb`` inside it would make a pure library database-coupled for
every future consumer. Promoting it to a ``navrules[postgres]`` extra is a
follow-up recorded in ``sdd/proposals/navrules-postgres-storage.brainstorm.md``,
and the condition for doing it is a second consumer.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any, Optional, Sequence

from navrules.storages.abstract import AbstractStorage

from ..db.repository import BaseRepository
from .builder import DEFAULT_RULESET
from .models import Rule, RuleCreate, RuleUpdate

#: Columns selected for a rule, mapped by ``Rule.from_row``.
_RULE_COLUMNS = (
    "rule_id, tenant_id, ruleset, name, priority, enabled, conditions, "
    "result, description, created_at, updated_at"
)

#: Ordering used everywhere rules are read.
#:
#: ``rule_id`` is not decoration. ``RuleSet.compile()`` sorts by priority with a
#: *stable* sort, so two rules of equal priority keep the order they were added
#: in — which, without a deterministic second key here, would be whatever order
#: Postgres happened to return. Two tenants with the same rules would then get
#: different offers.
_RULE_ORDER = "ORDER BY priority DESC, rule_id"


class RuleAlreadyExists(ValueError):
    """A rule with that name already exists in this tenant's ruleset."""


class RuleRepository(BaseRepository):
    """Stored eligibility rules, scoped to a tenant."""

    async def create(self, tenant_id: str, payload: RuleCreate) -> Rule:
        """Store a new rule.

        Args:
            tenant_id: Owning tenant.
            payload: Validated creation payload.

        Returns:
            The stored rule.

        Raises:
            RuleAlreadyExists: If the name is taken in this ruleset.
        """
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('rules')} "
            "(tenant_id, ruleset, name, priority, enabled, conditions, "
            " result, description) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8) "
            "ON CONFLICT (tenant_id, ruleset, name) DO NOTHING "
            f"RETURNING {_RULE_COLUMNS}",
            payload.ruleset,
            payload.name,
            payload.priority,
            payload.enabled,
            json.dumps(payload.conditions),
            json.dumps(payload.result),
            payload.description,
        )
        if row is None:
            raise RuleAlreadyExists(
                f"tenant {tenant_id!r} already has a rule named "
                f"{payload.name!r} in ruleset {payload.ruleset!r}"
            )
        return Rule.from_row(row)

    async def get(self, tenant_id: str, rule_id: str) -> Optional[Rule]:
        """Return one rule by surrogate key."""
        key = _as_uuid(rule_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_RULE_COLUMNS} FROM {self.table('rules')} "
            "WHERE tenant_id = $1 AND rule_id = $2",
            key,
        )
        return Rule.from_row(row) if row else None

    async def list_rules(
        self,
        tenant_id: str,
        *,
        ruleset: str = DEFAULT_RULESET,
        enabled_only: bool = False,
    ) -> Sequence[Rule]:
        """List a tenant's rules in evaluation order.

        Args:
            tenant_id: Owning tenant.
            ruleset: Which ruleset to read.
            enabled_only: Skip disabled rules. The runtime loads with this on;
                the API lists everything, because a rule a tenant disabled is
                still a rule they want to see.

        Returns:
            Rules, highest priority first.
        """
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_RULE_COLUMNS} FROM {self.table('rules')} "
            "WHERE tenant_id = $1 AND ruleset = $2 "
            "  AND ($3::boolean IS NOT TRUE OR enabled) "
            f"{_RULE_ORDER}",
            ruleset,
            enabled_only,
        )
        return [Rule.from_row(row) for row in rows]

    async def update(
        self, tenant_id: str, rule_id: str, patch: RuleUpdate
    ) -> Optional[Rule]:
        """Apply a partial amendment.

        Args:
            tenant_id: Owning tenant.
            rule_id: Surrogate key.
            patch: Fields to change; absent ones are left alone.

        Returns:
            The updated rule, or ``None`` if there is no such rule.
        """
        key = _as_uuid(rule_id)
        if key is None:
            return None
        changes = patch.changes()
        if not changes:
            return await self.get(tenant_id, rule_id)

        assignments: list[str] = []
        params: list[Any] = []
        for index, (field, value) in enumerate(changes.items(), start=3):
            if field in ("conditions", "result"):
                assignments.append(f"{field} = ${index}::jsonb")
                params.append(json.dumps(value))
            else:
                assignments.append(f"{field} = ${index}")
                params.append(value)

        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('rules')} "
            f"SET {', '.join(assignments)}, updated_at = now() "
            "WHERE tenant_id = $1 AND rule_id = $2 "
            f"RETURNING {_RULE_COLUMNS}",
            key,
            *params,
        )
        return Rule.from_row(row) if row else None

    async def delete(self, tenant_id: str, rule_id: str) -> bool:
        """Remove a rule.

        Args:
            tenant_id: Owning tenant.
            rule_id: Surrogate key.

        Returns:
            ``True`` if a rule was removed.
        """
        key = _as_uuid(rule_id)
        if key is None:
            return False
        row = await self.fetch_one(
            tenant_id,
            f"DELETE FROM {self.table('rules')} "
            "WHERE tenant_id = $1 AND rule_id = $2 RETURNING rule_id",
            key,
        )
        return row is not None

    async def seed(
        self,
        tenant_id: str,
        specs: Sequence[dict],
        *,
        ruleset: str = DEFAULT_RULESET,
    ) -> int:
        """Insert starting rules, skipping any name already present.

        Idempotent by name so re-provisioning a tenant does not duplicate its
        ruleset, and so a tenant who edited a seeded rule keeps their version.

        Args:
            tenant_id: Owning tenant.
            specs: Rule specs, e.g. ``DEFAULT_ELIGIBILITY_RULES``.
            ruleset: Which ruleset to seed.

        Returns:
            How many rules were actually inserted.
        """
        inserted = 0
        for spec in specs:
            try:
                await self.create(
                    tenant_id,
                    RuleCreate(
                        name=spec["name"],
                        conditions=spec["conditions"],
                        result=spec.get("result", {}),
                        priority=spec.get("priority", 0),
                        description=spec.get("description", ""),
                        ruleset=ruleset,
                    ),
                )
                inserted += 1
            except RuleAlreadyExists:
                continue
        return inserted


class PostgresRuleStorage(AbstractStorage):
    """navrules storage over :class:`RuleRepository`, bound to one tenant.

    ``AbstractStorage.load()`` takes no arguments, so the tenant and ruleset are
    fixed at construction. That is a better fit than it looks: a storage
    instance is exactly "this tenant's rules", which is what a runtime holds.

    Args:
        repository: The repository to read through.
        tenant_id: Tenant whose rules to load.
        ruleset: Which ruleset to load.
    """

    def __init__(
        self,
        repository: RuleRepository,
        tenant_id: str,
        *,
        ruleset: str = DEFAULT_RULESET,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._tenant_id = tenant_id
        self._ruleset = ruleset

    async def load(self) -> list[dict[str, Any]]:
        """Return enabled rules as specs ``RuleLoader`` accepts.

        Returns:
            One spec dict per enabled rule, in evaluation order.
        """
        rules = await self._repository.list_rules(
            self._tenant_id, ruleset=self._ruleset, enabled_only=True
        )
        return [rule.to_spec() for rule in rules]


def _as_uuid(value: Any) -> Optional[_uuid.UUID]:
    """Convert a surrogate key to a UUID, or ``None`` if it is not one.

    asyncpg infers the parameter type from a ``$n::uuid`` cast and then rejects
    a ``str``, so the conversion happens here; doing it here also turns a
    malformed id from a URL path into a clean miss rather than a driver error.
    """
    if isinstance(value, _uuid.UUID):
        return value
    if not value:
        return None
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


__all__ = ("PostgresRuleStorage", "RuleAlreadyExists", "RuleRepository")
