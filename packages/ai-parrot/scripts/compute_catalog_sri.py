#!/usr/bin/env python3
"""Compute SRI (sha384) hashes for every CDN asset in the interactive catalog.

Reads the ``url`` / ``css_url`` fields from
``parrot/tools/interactive/catalog/libraries/*.md`` and prints the matching
``sha384-<base64>`` integrity value for each. Run from anywhere; requires
outbound network access.

Usage::

    python packages/ai-parrot/scripts/compute_catalog_sri.py

Paste each printed value into the corresponding ``sri_hash`` / ``css_sri_hash``
frontmatter field. See ``catalog/SRI.md`` for context.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import urllib.request
from pathlib import Path

import frontmatter  # type: ignore[import-untyped]

CATALOG = (
    Path(__file__).resolve().parent.parent
    / "src" / "parrot" / "tools" / "interactive" / "catalog" / "libraries"
)


def sri_for(url: str) -> str:
    """Return the ``sha384-<base64>`` SRI value for the bytes served at ``url``."""
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        data = resp.read()
    digest = hashlib.sha384(data).digest()
    return "sha384-" + base64.b64encode(digest).decode()


def main() -> int:
    """Print SRI hashes for all catalog CDN assets; return a process exit code."""
    if not CATALOG.is_dir():
        print(f"catalog libraries dir not found: {CATALOG}", file=sys.stderr)
        return 1
    for md in sorted(CATALOG.glob("*.md")):
        post = frontmatter.load(str(md))
        for field in ("url", "css_url"):
            url = post.get(field)
            if not url:
                continue
            try:
                print(f"{md.name} [{field}] {url}\n  {sri_for(url)}")
            except Exception as exc:  # noqa: BLE001
                print(f"{md.name} [{field}] {url}\n  ERROR: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
