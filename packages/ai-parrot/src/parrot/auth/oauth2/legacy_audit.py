"""Read-only audit of legacy channel-scoped OAuth2 keys (FEAT-773 M10, U3 cutover metric)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from parrot.auth.principal import PrincipalResolver, get_principal_resolver
from parrot.auth.oauth2_base import _legacy_window_open
from parrot.conf import OAUTH2_LEGACY_KEYS_UNTIL, OAUTH2_REDIS_URL

logger = logging.getLogger(__name__)


async def _count_keys(
    resolver: PrincipalResolver,
    keys: Any,
    *,
    prefix: str,
) -> Dict[str, Dict[str, int]]:
    """Count legacy keys yielded by Redis without reading their values."""
    counts: Dict[str, Dict[str, int]] = {}
    async for key in keys:
        if isinstance(key, bytes):
            key = key.decode()
        if not key.startswith(prefix):
            continue

        suffix = key[len(prefix) :]
        parts = suffix.split(":", 1)
        if len(parts) != 2:
            continue
        channel, user_id = parts

        if not channel or not user_id or channel == "nonce":
            continue
        channel_counts = counts.setdefault(channel, {"bound": 0, "unbound": 0})
        bound = await resolver.resolve(channel, user_id) is not None
        channel_counts["bound" if bound else "unbound"] += 1

    return counts


async def audit_legacy_keys(
    redis: Any,
    resolver: PrincipalResolver,
    *,
    providers: Sequence[str],
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return bound and unbound counts by provider and channel.

    Redis is only scanned; values are never read or printed. Legacy OAuth2
    keys use ``oauth2:{provider}:{channel}:{user_id}``, while Jira's older
    layout uses ``jira:oauth:{channel}:{user_id}``.
    """
    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    for provider in providers:
        provider_counts = await _count_keys(
            resolver,
            redis.scan_iter(match=f"oauth2:{provider}:*"),
            prefix=f"oauth2:{provider}:",
        )
        if provider == "jira":
            jira_counts = await _count_keys(
                resolver,
                redis.scan_iter(match="jira:oauth:*"),
                prefix="jira:oauth:",
            )
            for channel, counts in jira_counts.items():
                existing = provider_counts.setdefault(channel, {"bound": 0, "unbound": 0})
                existing["bound"] += counts["bound"]
                existing["unbound"] += counts["unbound"]
        result[provider] = provider_counts
    return result


_UNLINK_BATCH = 500


def _purge_allowed(now: Optional[datetime], force: bool) -> bool:
    """True only after a valid OAUTH2_LEGACY_KEYS_UNTIL has passed (or when forced).

    A missing/blank or unparsable cutoff never grants permission.
    """
    if force:
        return True
    cutoff = (OAUTH2_LEGACY_KEYS_UNTIL or "").strip()
    if not cutoff:
        return False
    try:
        datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError:
        return False
    return not _legacy_window_open(now)


async def purge_legacy_keys(
    redis: Any,
    *,
    channel: str,
    providers: Sequence[str],
    dry_run: bool = True,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Count (and, unless ``dry_run``, UNLINK) legacy keys for one channel. Never reads values.

    Args:
        redis: Async Redis client supporting ``scan_iter`` and ``unlink``.
        channel: Channel whose legacy keys are targeted (e.g. ``telegram``).
        providers: OAuth2 providers to purge.
        dry_run: Only count keys when True (always allowed).
        force: Bypass the cutoff date gate.
        now: Override of the current time (tests).

    Returns:
        Mapping of scan pattern to matched key count.

    Raises:
        PermissionError: before the cutoff (or with a missing/invalid cutoff) unless ``force``.
    """
    if not channel or any(ch in channel for ch in "*?[]:"):
        raise ValueError(f"invalid channel: {channel!r}")
    if not dry_run and not _purge_allowed(now, force):
        raise PermissionError("legacy key purge refused before OAUTH2_LEGACY_KEYS_UNTIL (use --force to override)")
    patterns = []
    if "jira" in providers:
        patterns.append(f"jira:oauth:{channel}:*")
    patterns.extend(f"oauth2:{provider}:{channel}:*" for provider in providers)
    result: Dict[str, int] = {}
    for pattern in patterns:
        count = 0
        batch: list = []
        async for key in redis.scan_iter(match=pattern):
            count += 1
            if not dry_run:
                batch.append(key)
                if len(batch) >= _UNLINK_BATCH:
                    await redis.unlink(*batch)
                    batch = []
        if batch:
            await redis.unlink(*batch)
        result[pattern] = count
        logger.info("legacy purge %s: %d key(s)%s", pattern, count, " (dry run)" if dry_run else "")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the read-only audit and print a table of counts."""
    parser = argparse.ArgumentParser(description="Audit legacy OAuth2 keys before the connections cutover.")
    parser.add_argument(
        "--provider",
        action="append",
        dest="providers",
        default=None,
        help="Provider to audit; may be repeated (default: jira, o365).",
    )
    parser.add_argument("--purge", action="store_true", help="Purge legacy keys for --channel (dry run by default).")
    parser.add_argument("--channel", default=None, help="Channel whose legacy keys are purged (with --purge).")
    parser.add_argument("--confirm", action="store_true", help="Actually delete keys (otherwise dry run).")
    parser.add_argument("--force", action="store_true", help="Bypass the OAUTH2_LEGACY_KEYS_UNTIL date gate.")
    args = parser.parse_args(argv)
    if args.purge and not args.channel:
        parser.error("--purge requires --channel")

    import redis.asyncio

    redis_client = redis.asyncio.from_url(OAUTH2_REDIS_URL)
    providers = args.providers or ["jira", "o365"]
    if args.purge:
        try:
            purged = asyncio.run(
                purge_legacy_keys(
                    redis_client,
                    channel=args.channel,
                    providers=providers,
                    dry_run=not args.confirm,
                    force=args.force,
                )
            )
        except (PermissionError, ValueError) as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write("".join(f"{pattern}\t{count}\n" for pattern, count in purged.items()))
        return 0
    counts = asyncio.run(audit_legacy_keys(redis_client, get_principal_resolver(), providers=providers))
    lines = ["provider\tchannel\tbound\tunbound\n"]
    for provider in providers:
        for channel in sorted(counts.get(provider, {})):
            channel_counts = counts[provider][channel]
            lines.append(f"{provider}\t{channel}\t{channel_counts['bound']}\t{channel_counts['unbound']}\n")
    sys.stdout.write("".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
