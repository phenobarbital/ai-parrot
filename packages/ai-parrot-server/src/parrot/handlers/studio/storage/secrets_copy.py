"""One-shot DocumentDB → Postgres copy of Studio secrets (spec §2.10). Ciphertexts copied verbatim.

``python -m parrot.handlers.studio.storage.secrets_copy --dsn <dsn> [--dry-run] [--byok] [--vault] [--overrides]``
(no collection flag = all three). Idempotent upserts; the report holds counts only and no value is ever logged.
BYOK ``masked`` is derived by opening the ciphertext (read only, never re-sealed); the ciphertext itself is stored as
read, so it keeps its original keyring ``key_id`` and AAD context.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from navigator_session.vault.envelope import read_header
from pydantic import ValidationError

from parrot.security.credentials_utils import decrypt_credential, llm_key_context
from parrot.security.vault_utils import VAULT_CRED_COLLECTION, get_vault_keyring

from ...toolkit_persistence import COLLECTION as OVERRIDES_COLLECTION
from ...toolkit_persistence import UserToolkitOverride
from .overrides_store import PgToolkitOverrideStore
from .repositories import _fetch_one

logger = logging.getLogger("Parrot.AgentStudio.Storage")

BYOK_COLLECTION = "user_llm_keys"  # byok.py COLLECTION
_BYOK_SQL = (
    "INSERT INTO navigator.ai_user_llm_keys (user_id, provider, api_key_enc, key_id, masked, created_at, updated_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7) "
    "ON CONFLICT (user_id, provider) DO UPDATE SET api_key_enc = EXCLUDED.api_key_enc, "
    "key_id = EXCLUDED.key_id, masked = EXCLUDED.masked, updated_at = EXCLUDED.updated_at RETURNING provider"
)
_VAULT_SQL = (
    "INSERT INTO navigator.ai_user_credentials (user_id, name, credential, created_at, updated_at) "
    "VALUES ($1, $2, $3, $4, $5) "
    "ON CONFLICT (user_id, name) DO UPDATE SET credential = EXCLUDED.credential, updated_at = EXCLUDED.updated_at "
    "RETURNING name"
)


def _when(value: Any) -> datetime:
    """A document timestamp (ISO string or datetime) as an aware datetime; now when absent or unparsable."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _mask(api_key: str) -> str:
    """Same preview as ``byok._mask`` (copied: that module pulls in the whole HTTP layer)."""
    return "*" * len(api_key) if len(api_key) <= 7 else f"{api_key[:3]}…{api_key[-4:]}"


async def _put_byok(pool: Any, doc: dict[str, Any]) -> None:
    user_id, provider, sealed = str(doc["user_id"]), doc["provider"], doc["api_key"]
    key_id = read_header(base64.b64decode(sealed)).key_id
    credential = decrypt_credential(sealed, llm_key_context(user_id, provider), get_vault_keyring())
    created, updated = _when(doc.get("created_at")), _when(doc.get("updated_at") or doc.get("created_at"))
    async with pool.acquire() as conn:
        await _fetch_one(
            conn, _BYOK_SQL, user_id, provider, sealed, key_id, _mask(credential.get("api_key", "")), created, updated
        )


async def _put_vault(pool: Any, doc: dict[str, Any]) -> None:
    created, updated = _when(doc.get("created_at")), _when(doc.get("updated_at") or doc.get("created_at"))
    async with pool.acquire() as conn:
        await _fetch_one(conn, _VAULT_SQL, str(doc["user_id"]), doc["name"], doc["credential"], created, updated)


async def _put_override(pool: Any, doc: dict[str, Any]) -> None:
    await PgToolkitOverrideStore(pool).save(UserToolkitOverride.model_validate(doc))


def _identity(doc: dict[str, Any], field: str) -> tuple[Any, Any]:
    return doc.get("user_id"), doc.get(field)


_PLANS: dict[str, tuple[str, str, Callable[[Any, dict[str, Any]], Awaitable[None]]]] = {
    "byok": (BYOK_COLLECTION, "provider", _put_byok),
    "vault": (VAULT_CRED_COLLECTION, "name", _put_vault),
    "overrides": (OVERRIDES_COLLECTION, "slug", _put_override),
}


async def _copy_one(pool: Any, source: Any, kind: str, dry_run: bool, counts: dict[str, int]) -> None:
    collection, key_field, put = _PLANS[kind]
    for doc in await source.read(collection, {}) or []:
        doc = {k: v for k, v in doc.items() if k != "_id"}
        if dry_run:
            counts[kind] += 1
            continue
        try:
            await put(pool, doc)
            counts[kind] += 1
        except (KeyError, ValueError, ValidationError, TypeError) as exc:
            counts["failed"] += 1
            # identity + exception class only: never the document, the ciphertext or the exception text
            logger.warning("secrets_copy: skipped %s %s: %s", kind, _identity(doc, key_field), type(exc).__name__)
        except Exception as exc:  # pylint: disable=broad-except  # decrypt / keyring / storage failure
            counts["failed"] += 1
            logger.warning("secrets_copy: failed %s %s: %s", kind, _identity(doc, key_field), type(exc).__name__)


async def copy_secrets(
    pool: Any, *, byok: bool, vault: bool, overrides: bool, dry_run: bool, source: Any = None
) -> dict[str, int]:
    """Copy the selected DocumentDB collections into Postgres; returns per-collection counts and ``failed``.

    ``dry_run`` only reads and counts. ``source`` is an async context manager yielding an object with
    ``read(collection, query)`` (default: ``DocumentDb()``).
    """
    if source is None:
        from parrot.interfaces.documentdb import DocumentDb

        source = DocumentDb()
    counts = {"byok": 0, "vault": 0, "overrides": 0, "failed": 0}
    chosen = [kind for kind, on in (("byok", byok), ("vault", vault), ("overrides", overrides)) if on]
    async with source as src:
        for kind in chosen:
            await _copy_one(pool, src, kind, dry_run, counts)
    logger.info("secrets_copy%s: %s", " (dry-run)" if dry_run else "", counts)
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secrets_copy", description="Copy Studio secrets DocumentDB → Postgres.")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true", help="read and count only; write nothing")
    parser.add_argument("--byok", action="store_true", help="copy user_llm_keys")
    parser.add_argument("--vault", action="store_true", help="copy user_credentials")
    parser.add_argument("--overrides", action="store_true", help="copy user_toolkit_configs")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from asyncdb import AsyncPool

    every = not (args.byok or args.vault or args.overrides)
    pool = AsyncPool("pg", dsn=args.dsn)
    await pool.connect()
    try:
        counts = await copy_secrets(
            pool, byok=args.byok or every, vault=args.vault or every, overrides=args.overrides or every,
            dry_run=args.dry_run,
        )
    finally:
        await pool.close()
    print(("would copy" if args.dry_run else "copied") + f": {counts}")
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exit 1 when any document failed to copy."""
    return asyncio.run(_run(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
