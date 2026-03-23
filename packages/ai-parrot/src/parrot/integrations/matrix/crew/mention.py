"""Matrix mention parsing and formatting utilities.

Handles both plain-text ``@localpart`` mentions and Matrix HTML pill mentions
(``<a href="https://matrix.to/#/@user:server">name</a>``).
"""
import re
from typing import Optional


# Matches plain text @mention at start or after whitespace
_PLAIN_MENTION_RE = re.compile(r"@(\w[\w.-]*)(?:\s|$|:)")

# Matches Matrix pill mention: href="https://matrix.to/#/@localpart:server"
_PILL_MENTION_RE = re.compile(
    r'href="https://matrix\.to/#/@([\w][\w.-]*):([^"]+)"'
)


def parse_mention(body: str, server_name: str) -> Optional[str]:
    """Extract the agent localpart from a Matrix message body.

    Handles two formats:
    - Plain text: ``"@analyst what is AAPL?"`` → ``"analyst"``
    - Matrix pill HTML:
      ``<a href="https://matrix.to/#/@analyst:server">analyst</a>``
      → ``"analyst"``

    Args:
        body: Message body (may be plain text or contain HTML pill markup).
        server_name: Server domain name used to validate pill mentions.

    Returns:
        The localpart (e.g. ``"analyst"``) or ``None`` if no valid mention
        was found.
    """
    # Try pill mention first (higher specificity)
    pill_match = _PILL_MENTION_RE.search(body)
    if pill_match:
        localpart = pill_match.group(1)
        server = pill_match.group(2)
        if server == server_name:
            return localpart
        # Mention is for a different server — ignore
        return None

    # Try plain text mention
    plain_match = _PLAIN_MENTION_RE.search(body)
    if plain_match:
        return plain_match.group(1)

    return None


def format_reply(agent_mxid: str, display_name: str, text: str) -> str:
    """Format a reply with the agent's identity prepended.

    Args:
        agent_mxid: Full Matrix ID of the agent (e.g. ``"@analyst:server"``).
        display_name: Human-readable display name of the agent.
        text: Response text to format.

    Returns:
        Formatted string with the display name header followed by the text.
    """
    return f"{display_name}\n{text}"


def build_pill(mxid: str, display_name: str) -> str:
    """Build a Matrix "pill" HTML mention link.

    Produces a clickable user mention compatible with Matrix clients that
    support rich text (formatted_body).

    Args:
        mxid: Full Matrix ID (e.g. ``"@analyst:example.com"``).
        display_name: Display name shown inside the pill link.

    Returns:
        HTML anchor element, e.g.
        ``'<a href="https://matrix.to/#/@analyst:example.com">Financial Analyst</a>'``
    """
    return f'<a href="https://matrix.to/#/{mxid}">{display_name}</a>'
