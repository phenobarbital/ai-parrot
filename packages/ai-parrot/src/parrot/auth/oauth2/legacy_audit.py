"""Read-only audit of legacy channel-scoped OAuth2 keys (FEAT-773 M10, U3 cutover metric)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict, Optional, Sequence

from parrot.auth.principal import PrincipalResolver, get_principal_resolver
from parrot.conf import OAUTH2_REDIS_URL

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
    args = parser.parse_args(argv)

    import redis.asyncio

    redis_client = redis.asyncio.from_url(OAUTH2_REDIS_URL)
    providers = args.providers or ["jira", "o365"]
    counts = asyncio.run(audit_legacy_keys(redis_client, get_principal_resolver(), providers=providers))
    lines = ["provider\tchannel\tbound\tunbound\n"]
    for provider in providers:
        for channel in sorted(counts.get(provider, {})):
            channel_counts = counts[provider][channel]
            lines.append(
                f"{provider}\t{channel}\t{channel_counts['bound']}\t{channel_counts['unbound']}\n"
            )
    sys.stdout.write("".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
