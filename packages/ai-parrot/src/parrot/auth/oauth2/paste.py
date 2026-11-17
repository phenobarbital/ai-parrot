"""Parse a pasted OAuth redirect URL (moved from parrot_tools/jira_cli.py, FEAT-774 M6)."""

from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import click


def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:
    """Extract (code, state|None) from a pasted redirect URL or bare code.

    Args:
        text: The pasted redirect URL, or a bare authorization code.

    Returns:
        A tuple of the authorization code and the ``state`` parameter (None for a bare code
        or a URL without ``state``).

    Raises:
        click.ClickException: If the redirect carries ``error=`` or no ``code``.
    """
    text = text.strip()
    if text.startswith("http"):
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        if "error" in qs:
            raise click.ClickException(f"Authorization denied: {qs['error'][0]}")
        code = qs.get("code", [None])[0]
        if not code:
            raise click.ClickException("No 'code' parameter in the pasted URL.")
        state = qs.get("state", [None])[0]
        return code, state
    return text, None
