"""One-shot DocumentDB → Postgres copy of Studio secrets (spec §2.10). Ciphertexts copied verbatim.

``STUDIO_PG_DSN=<dsn> python -m parrot.handlers.studio.storage.secrets_copy [--dry-run] [--overwrite] [--byok] [--vault]
[--overrides]`` (no collection flag = all three). The DSN comes from the environment, never argv (argv shows up in
process listings). The default is INSERT-ONLY (``ON CONFLICT DO NOTHING``): rows already in Postgres are never touched, so
a re-run after cutover cannot clobber newer user edits. ``--overwrite`` updates an existing row only when the source
``updated_at`` is strictly newer. Every BYOK key and vault credential is opened (read-only) with the keyring, in a dry-run
as in a real run, so both report the same ``failed`` count. The report holds counts only; no value or DSN is ever logged.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from navigator_session.vault.envelope import read_header

from parrot.security.credentials_utils import (
    credential_context,
    decrypt_credential,
    llm_key_context,
)
from parrot.security.vault_utils import VAULT_CRED_COLLECTION, get_vault_keyring

from ...toolkit_persistence import COLLECTION as OVERRIDES_COLLECTION
from ...toolkit_persistence import UserToolkitOverride
from .overrides_store import _timestamp
from .repositories import _fetch_one

logger = logging.getLogger("Parrot.AgentStudio.Storage")

DSN_ENV = "STUDIO_PG_DSN"
BYOK_COLLECTION = "user_llm_keys"  # byok.py COLLECTION
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_BYOK_INSERT = (
    "INSERT INTO navigator.ai_user_llm_keys (user_id, provider, api_key_enc, key_id, masked, created_at, updated_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (user_id, provider) "
)
_BYOK_UPDATE = (
    "DO UPDATE SET api_key_enc = EXCLUDED.api_key_enc, key_id = EXCLUDED.key_id, masked = EXCLUDED.masked, "
    "updated_at = EXCLUDED.updated_at WHERE EXCLUDED.updated_at > navigator.ai_user_llm_keys.updated_at "
)
_VAULT_INSERT = (
    "INSERT INTO navigator.ai_user_credentials (user_id, name, credential, created_at, updated_at) "
    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id, name) "
)
_VAULT_UPDATE = (
    "DO UPDATE SET credential = EXCLUDED.credential, updated_at = EXCLUDED.updated_at "
    "WHERE EXCLUDED.updated_at > navigator.ai_user_credentials.updated_at "
)
_OVERRIDE_INSERT = (
    "INSERT INTO navigator.ai_user_toolkit_overrides (user_id, agent_ref, slug, params, secret_refs, updated_at) "
    "VALUES ($1, $2, $3, $4::text::jsonb, $5::text::jsonb, $6) ON CONFLICT (user_id, agent_ref, slug) "
)
_OVERRIDE_UPDATE = (
    "DO UPDATE SET params = EXCLUDED.params, secret_refs = EXCLUDED.secret_refs, updated_at = EXCLUDED.updated_at "
    "WHERE EXCLUDED.updated_at > navigator.ai_user_toolkit_overrides.updated_at "
)
_NOTHING = "DO NOTHING "


def _sql(insert: str, update: str, overwrite: bool) -> str:
    """Insert-only by default; with ``overwrite`` an existing row is updated only when the source is newer."""
    return insert + (update if overwrite else _NOTHING) + "RETURNING 1 AS written"


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


def _stamps(doc: dict[str, Any]) -> tuple[datetime, datetime]:
    return _when(doc.get("created_at")), _when(doc.get("updated_at") or doc.get("created_at"))


def _need_keyring(keyring: Any) -> Any:
    if keyring is None:
        raise RuntimeError("vault keyring unavailable")
    return keyring


def _check_byok(doc: dict[str, Any], keyring: Any) -> tuple[Any, ...]:
    """Open the key (read-only) and build the row; raises when the document cannot be opened."""
    user_id, provider, sealed = str(doc["user_id"]), doc["provider"], doc["api_key"]
    key_id = read_header(base64.b64decode(sealed)).key_id
    credential = decrypt_credential(sealed, llm_key_context(user_id, provider), _need_keyring(keyring))
    created, updated = _stamps(doc)
    return user_id, provider, sealed, key_id, _mask(credential.get("api_key", "")), created, updated


def _check_vault(doc: dict[str, Any], keyring: Any) -> tuple[Any, ...]:
    user_id, name, sealed = str(doc["user_id"]), doc["name"], doc["credential"]
    decrypt_credential(sealed, credential_context(user_id, name), _need_keyring(keyring))
    created, updated = _stamps(doc)
    return user_id, name, sealed, created, updated


def _check_override(doc: dict[str, Any], keyring: Any) -> tuple[Any, ...]:
    override = UserToolkitOverride.model_validate(doc)
    dumped = override.model_dump(mode="json")
    return (
        override.user_id, override.agent_id, override.slug, json.dumps(dumped["params"]),
        json.dumps(dumped["secret_refs"]), _timestamp(override.updated_at),
    )


async def _write(pool: Any, sql: str, row: tuple[Any, ...]) -> bool:
    """Run the guarded upsert; ``True`` only when a row was inserted or updated."""
    async with pool.acquire() as conn:
        return await _fetch_one(conn, sql, *row) is not None


def _identity(doc: dict[str, Any], field: str) -> tuple[Any, Any]:
    return doc.get("user_id"), doc.get(field)


_PLANS: dict[str, tuple[str, str, Callable[[dict[str, Any], Any], tuple[Any, ...]], str, str]] = {
    "byok": (BYOK_COLLECTION, "provider", _check_byok, _BYOK_INSERT, _BYOK_UPDATE),
    "vault": (VAULT_CRED_COLLECTION, "name", _check_vault, _VAULT_INSERT, _VAULT_UPDATE),
    "overrides": (OVERRIDES_COLLECTION, "slug", _check_override, _OVERRIDE_INSERT, _OVERRIDE_UPDATE),
}


async def _copy_doc(pool: Any, kind: str, doc: dict[str, Any], keyring: Any, flags: tuple[bool, bool]) -> str:
    """One document: ``copied``, ``skipped`` (already in Postgres and not strictly newer) or ``dry`` (checked only)."""
    dry_run, overwrite = flags
    _, _, check, insert, update = _PLANS[kind]
    row = check(doc, keyring)
    if dry_run:
        return "dry"
    return "copied" if await _write(pool, _sql(insert, update, overwrite), row) else "skipped"


async def _copy_one(
    pool: Any, source: Any, kind: str, keyring: Any, flags: tuple[bool, bool], counts: dict[str, int]
) -> None:
    collection, key_field = _PLANS[kind][:2]
    for doc in await source.read(collection, {}) or []:
        doc = {k: v for k, v in doc.items() if k != "_id"}
        if flags[1] and not doc.get("updated_at"):
            doc["updated_at"] = _EPOCH.isoformat()  # undated sources are never "newer"
        try:
            outcome = await _copy_doc(pool, kind, doc, keyring, flags)
        except Exception as exc:  # pylint: disable=broad-except  # malformed doc, decrypt, keyring or storage failure
            counts["failed"] += 1
            # identity + exception class only: never the document, the ciphertext or the exception text
            logger.warning("secrets_copy: failed %s %s: %s", kind, _identity(doc, key_field), type(exc).__name__)
            continue
        counts["skipped" if outcome == "skipped" else kind] += 1


def _resolve_keyring() -> Any:
    """The vault keyring, or ``None`` (with one clear, value-free error) when it is not configured."""
    try:
        return get_vault_keyring()
    except RuntimeError as exc:
        logger.error(
            "secrets_copy: vault keyring unavailable (%s); set VAULT_MASTER_KEY_v{N} and VAULT_ACTIVE_KEY_ID. "
            "BYOK keys and vault credentials cannot be opened and are counted as failed.", type(exc).__name__,
        )
        return None


async def copy_secrets(
    pool: Any, *, byok: bool, vault: bool, overrides: bool, dry_run: bool, overwrite: bool = False, source: Any = None
) -> dict[str, int]:
    """Copy the selected DocumentDB collections into Postgres; returns per-collection counts, ``skipped``, ``failed``.

    Insert-only unless ``overwrite`` (then an existing row is updated only by a strictly newer source ``updated_at``);
    ``skipped`` counts documents left untouched for that reason. ``dry_run`` writes nothing but opens every key and
    credential, so it reports the ``failed`` count a real run would. ``source`` is an async context manager yielding an
    object with ``read(collection, query)`` (default: ``DocumentDb()``).
    """
    if source is None:
        from parrot.interfaces.documentdb import DocumentDb

        source = DocumentDb()
    counts = {"byok": 0, "vault": 0, "overrides": 0, "skipped": 0, "failed": 0}
    chosen = [kind for kind, on in (("byok", byok), ("vault", vault), ("overrides", overrides)) if on]
    keyring = _resolve_keyring() if byok or vault else None
    async with source as src:
        for kind in chosen:
            await _copy_one(pool, src, kind, keyring, (dry_run, overwrite), counts)
    logger.info("secrets_copy%s: %s", " (dry-run)" if dry_run else "", counts)
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="secrets_copy", description=f"Copy Studio secrets DocumentDB → Postgres (DSN from ${DSN_ENV})."
    )
    parser.add_argument("--dsn", help=argparse.SUPPRESS)  # rejected: argv leaks into process listings
    parser.add_argument("--dry-run", action="store_true", help="write nothing, but open every key/credential")
    parser.add_argument("--overwrite", action="store_true", help="update existing rows when the source is newer")
    parser.add_argument("--byok", action="store_true", help="copy user_llm_keys")
    parser.add_argument("--vault", action="store_true", help="copy user_credentials")
    parser.add_argument("--overrides", action="store_true", help="copy user_toolkit_configs")
    return parser


async def _run(args: argparse.Namespace, dsn: str) -> int:
    from asyncdb import AsyncPool

    every = not (args.byok or args.vault or args.overrides)
    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    try:
        counts = await copy_secrets(
            pool, byok=args.byok or every, vault=args.vault or every, overrides=args.overrides or every,
            dry_run=args.dry_run, overwrite=args.overwrite,
        )
    finally:
        await pool.close()
    print(("would copy" if args.dry_run else "copied") + f": {counts}")
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exit 1 when any document failed, 2 on a usage error (``--dsn`` given or no DSN in env)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.dsn:
        parser.error(f"--dsn is not accepted (argv leaks into process listings); set ${DSN_ENV} instead")
    dsn = os.environ.get(DSN_ENV, "")
    if not dsn:
        parser.error(f"set ${DSN_ENV} to the PostgreSQL DSN of the Studio database")
    return asyncio.run(_run(args, dsn))


if __name__ == "__main__":
    sys.exit(main())
