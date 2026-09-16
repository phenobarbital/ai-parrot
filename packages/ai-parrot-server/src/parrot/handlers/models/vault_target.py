"""
Vault protected target for ``users_bots`` sealed columns (FEAT-099).

Lives under ``parrot.handlers.models`` (next to the model it protects) because
the ``parrot`` namespace is shared: ``parrot.vault_targets`` already belongs to
the ai-parrot package (DocumentDB collections).

``UserBotModel`` seals ``mcp_config`` and ``tools_config`` with envelope v2
bound to ``(user_id, chatbot_id, field)``. This target lets
``navigator-vault`` rotate those columns and migrate the legacy in-plaintext
``_ctx`` envelopes: :meth:`UsersBotsTarget.legacy_unwrap` verifies the old
context before the value is re-sealed, so a blob that was already substituted
between rows or columns fails instead of being legitimised.

Quarantine disables the bot (``enabled = false``) and leaves its sealed
columns untouched, so a restore can bring them back.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from uuid import UUID

from navigator_session.vault.targets.postgres import PostgresTarget
from parrot.conf import PARROT_SCHEMA
from ._encrypted_field import (
    USER_BOT_FIELDS,
    USER_BOT_PURPOSE,
    unwrap_legacy_envelope,
    user_bot_context,
)
from parrot.security.credentials_utils import normalize_user_id


class UsersBotsTarget(PostgresTarget):
    """Sealed columns of ``<PARROT_SCHEMA>.users_bots``."""

    name = "navigator.users_bots"
    table = "navigator.users_bots"
    purpose = USER_BOT_PURPOSE
    pk_column = "chatbot_id"
    identity_columns = ("user_id", "chatbot_id")
    encrypted_fields = USER_BOT_FIELDS
    include_field_in_context = True
    key_version_column = None
    touch_column = None
    state_columns = ("enabled",)
    quarantine_assignments = "enabled = false"

    def __init__(self, db_pool: Any, schema: str = PARROT_SCHEMA) -> None:
        self.table = f"{schema}.users_bots"
        self.name = self.table
        super().__init__(db_pool)

    def context_for(self, row: Any, field: str):
        """Same context the model seals with (``user_bot_context``)."""
        identity = row.identity
        return user_bot_context(identity["user_id"], identity["chatbot_id"], field)

    def context_value(self, column: str, value: Any) -> Any:
        if column == "user_id":
            return normalize_user_id(value)
        return None if value is None else str(value)

    def pk_from_json(self, value: Any) -> Any:
        """``chatbot_id`` is a UUID."""
        return value if isinstance(value, UUID) else UUID(str(value))

    def state_from_json(self, column: str, value: Any) -> Any:
        """``enabled`` is a boolean."""
        return None if value is None else bool(value)

    def legacy_unwrap(self, field: str, plaintext: bytes, row: Any) -> bytes:
        """Verify the legacy ``_ctx`` envelope of a v1 blob before re-sealing.

        Raises:
            ValueError: If the envelope is missing/unsupported or its context
                does not match the row being migrated.
        """
        identity = row.identity
        return unwrap_legacy_envelope(
            plaintext,
            user_id=identity["user_id"],
            chatbot_id=identity["chatbot_id"],
            field=field,
        )


def factory(resources: Mapping[str, Any]) -> Optional[UsersBotsTarget]:
    """Entry-point factory: uses ``parrot_db_pool`` when present, else ``db_pool``.

    Returns:
        Target, or ``None`` when no PostgreSQL pool is configured.
    """
    pool = resources.get("parrot_db_pool") or resources.get("db_pool")
    if pool is None:
        return None
    return UsersBotsTarget(pool)
