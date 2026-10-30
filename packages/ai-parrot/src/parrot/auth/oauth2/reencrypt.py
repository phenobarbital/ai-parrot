"""Identity Vault re-encryption job (FEAT-773 M10, AC-18).

Dry-run by default; never prints token values.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import sys
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    Literal,
    Optional,
    Sequence,
)

logger = logging.getLogger(__name__)

RowClass = Literal["current", "stale", "failed"]


async def reencrypt_identities(
    rows: Iterable[Any],
    lock: Callable[[str, str], AsyncContextManager[Any]],
    *,
    reseal_row: Callable[[Any], Awaitable[None]],
    verify_active: Callable[[Any], bool],
    classify: Callable[[Any], RowClass],
    apply: bool = False,
) -> Dict[str, Dict[str, int]]:
    """Return {provider: {"current", "stale", "resealed", "failed"}}.

    For each row:
    - Acquire the principal lock (provider, user_id)
    - Classify the row (current/stale/failed)
    - If failed: count and continue (never write)
    - If apply and not failed: re-seal the row, then verify with active key only
    - Count resealed on success, failed on verification failure

    Never logs or prints token values.
    """
    counts: Dict[str, Dict[str, int]] = {}

    for row in rows:
        provider = row["auth_provider"]
        user_id = str(row["user_id"])

        # Initialize provider counts if needed
        if provider not in counts:
            counts[provider] = {"current": 0, "stale": 0, "resealed": 0, "failed": 0}

        # Acquire the principal lock
        async with lock(provider, user_id):
            # Classify the row
            cls = classify(row)

            if cls == "failed":
                counts[provider]["failed"] += 1
                logger.warning(
                    "Undecryptable row: provider=%s user_id=%s identity_id=%s",
                    provider,
                    user_id,
                    row.get("identity_id", "unknown"),
                )
                continue

            if cls == "current":
                counts[provider]["current"] += 1
            elif cls == "stale":
                counts[provider]["stale"] += 1

            # Apply re-seal if requested
            if apply:
                try:
                    await reseal_row(row)
                    # Verify with active key only after re-seal
                    verified = verify_active(row)
                    if inspect.isawaitable(verified):
                        verified = await verified
                    if verified:
                        counts[provider]["resealed"] += 1
                    else:
                        counts[provider]["failed"] += 1
                        logger.error(
                            "Re-seal verification failed: provider=%s user_id=%s",
                            provider,
                            user_id,
                        )
                except Exception as exc:
                    counts[provider]["failed"] += 1
                    logger.error(
                        "Re-seal failed: provider=%s user_id=%s error=%s",
                        provider,
                        user_id,
                        type(exc).__name__,
                    )

    return counts


def retirement_allowed(counts: Dict[str, Dict[str, int]], *, provider_filter: Sequence[str]) -> bool:
    """Global key retirement only after a full-store scan with stale == 0 and failed == 0.

    Args:
        counts: Per-provider counts from reencrypt_identities
        provider_filter: Non-empty means this was a filtered run (cannot authorize retirement)

    Returns:
        True only if this was a full-store scan with no stale or failed rows.
    """
    # Provider-filtered runs cannot authorize global retirement
    if provider_filter:
        logger.warning("Provider-filtered scan cannot authorize key retirement")
        return False

    # An empty scan proves nothing: never authorize retirement without scanned rows
    if not any(sum(c.get(k, 0) for k in ('current', 'stale', 'failed')) > 0 for c in counts.values()):
        logger.warning("Key retirement blocked: no rows were scanned")
        return False

    # Check for any stale or failed rows across all providers
    for provider, provider_counts in counts.items():
        if provider_counts.get("stale", 0) > 0:
            logger.warning(
                "Key retirement blocked: provider=%s has stale=%d rows",
                provider,
                provider_counts["stale"],
            )
            return False
        if provider_counts.get("failed", 0) > 0:
            logger.warning(
                "Key retirement blocked: provider=%s has failed=%d rows",
                provider,
                provider_counts["failed"],
            )
            return False

    return True


def _emit(message: str = "") -> None:
    """Write one CLI output line to stdout (the CLI's result channel; not logging)."""
    sys.stdout.write(f"{message}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point: --apply, --provider P (repeatable).

    Bootstraps server helpers lazily (exit 2 when unavailable).
    Never prints token values.
    """
    parser = argparse.ArgumentParser(
        description="Identity Vault re-encryption job (dry-run by default)",
        prog="python -m parrot.auth.oauth2.reencrypt",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually re-seal rows (default: dry-run, counts only)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        action="append",
        dest="providers",
        default=[],
        help="Filter by provider (repeatable, default: all providers)",
    )
    args = parser.parse_args(argv)

    # Lazy import of server helpers - exit 2 if unavailable
    try:
        from parrot.services.identity_credential_sink import (
            fetch_credential_row,
            list_credential_rows,
            reseal_identity_row,
            verify_active_only,
        )
    except ImportError as e:
        logger.error("Server helpers not available: %s", e)
        _emit("Error: server helpers not available. Run from ai-parrot-server environment.")
        return 2

    # Lazy import of Redis and config
    try:
        import redis.asyncio as redis
        from parrot.auth.oauth2_base import _LOCK_KEY_TEMPLATE
        from parrot.conf import OAUTH2_REDIS_URL
        from navigator_auth.identity.crypto import IdentityCipher
    except ImportError as e:
        logger.error("Required dependencies not available: %s", e)
        return 2

    async def run() -> Dict[str, Dict[str, int]]:
        # Create Redis client for locking
        redis_client = redis.from_url(OAUTH2_REDIS_URL)

        # Create cipher for classification and verification
        cipher = IdentityCipher()

        def classify_row(row: Any) -> RowClass:
            """Classify a row based on decryptability.

            - current: decrypts with active key only
            - stale: decrypts with full ring but not active-only
            - failed: cannot decrypt
            """
            # Try active-only first
            if verify_active_only(row, active_cipher=cipher):
                return "current"
            # Try full ring (cipher has full ring by default)
            try:
                for field in ("access_token", "refresh_token", "id_token"):
                    val = row.get(field)
                    if val is not None:
                        cipher.decrypt(
                            val,
                            user_id=row["user_id"],
                            auth_provider=row["auth_provider"],
                            provider_user_id=row.get("provider_user_id", ""),
                            field=field,
                        )
                return "stale"
            except Exception:
                return "failed"

        @asynccontextmanager
        async def principal_lock(provider: str, user_id: str):
            """Acquire the principal refresh lock."""
            lock_key = _LOCK_KEY_TEMPLATE.format(provider=provider, user_id=user_id)
            lock = redis_client.lock(
                lock_key,
                timeout=10,
                blocking_timeout=5,
            )
            acquired = await lock.acquire()
            if not acquired:
                raise RuntimeError(f"could not acquire refresh lock {lock_key}")
            try:
                yield lock
            finally:
                if acquired:
                    try:
                        await lock.release()
                    except Exception:
                        pass

        # Real pool bootstrap (asyncdb "pg" pool on the default DSN); failure aborts the run.
        from asyncdb import AsyncPool
        from parrot.conf import default_dsn

        db_pool = AsyncPool("pg", dsn=default_dsn)
        await db_pool.connect()

        # List credential rows
        rows = await list_credential_rows(db_pool, args.providers)

        async def reseal_wrapper(row: Any) -> None:
            """Wrapper to re-seal a row."""
            await reseal_identity_row(db_pool, row, cipher=cipher)

        async def verify_wrapper(row: Any) -> bool:
            """Re-read the row (fresh ciphertext) and verify it with the active key only."""
            fresh = await fetch_credential_row(db_pool, row["identity_id"])
            return fresh is not None and verify_active_only(fresh, active_cipher=cipher)

        # Run the re-encryption job
        counts = await reencrypt_identities(
            rows,
            principal_lock,
            reseal_row=reseal_wrapper,
            verify_active=verify_wrapper,
            classify=classify_row,
            apply=args.apply,
        )

        try:
            return counts
        finally:
            await redis_client.aclose()
            await db_pool.close()

    # Run the async job
    try:
        counts = asyncio.run(run())
    except Exception as exc:  # setup/pool/lock errors must never look like success
        logger.error("Re-encryption aborted: %s", type(exc).__name__)
        _emit(f"Error: re-encryption aborted ({type(exc).__name__}); key retirement NOT allowed.")
        return 1

    # Print summary (no token values)
    _emit("\nRe-encryption summary:")
    _emit("=" * 50)
    for provider, provider_counts in sorted(counts.items()):
        _emit(f"\n{provider}:")
        _emit(f"  current:  {provider_counts.get('current', 0)}")
        _emit(f"  stale:    {provider_counts.get('stale', 0)}")
        _emit(f"  resealed: {provider_counts.get('resealed', 0)}")
        _emit(f"  failed:   {provider_counts.get('failed', 0)}")

    # Check retirement gate
    can_retire = retirement_allowed(counts, provider_filter=args.providers)
    _emit(f"\nKey retirement allowed: {can_retire}")
    if args.apply and any(c.get('failed', 0) for c in counts.values()):
        return 1

    if not args.apply:
        _emit("\n(Dry-run: no rows were modified)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
