"""Example: Fireflies → Obsidian → GraphIndex LLM Wiki, with email digests.

Manual one-shot runner for each of :class:`FirefliesWikiAgent`'s three
scheduled operations. In production these run unattended via the agent
scheduler (07:00 / 08:00 / Monday 09:00); this script is for trying them
by hand.

Usage:
    # Everything, in order
    python examples/agents/fireflies_wiki_agent.py

    # One operation at a time
    python examples/agents/fireflies_wiki_agent.py sync
    python examples/agents/fireflies_wiki_agent.py daily
    python examples/agents/fireflies_wiki_agent.py weekly

Requirements:
    - FIREFLIES_API_KEY          Fireflies.ai API token
    - ANTHROPIC_API_KEY          for the agent's Claude Haiku 4.5 client
    - OBSIDIAN_VAULT_PATH        local Obsidian vault
    - FIREFLIES_WIKI_DAILY_RECIPIENTS   comma-separated addresses
    - FIREFLIES_WIKI_WEEKLY_RECIPIENTS  comma-separated addresses

See docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md
"""
import asyncio
import logging
import sys

from agents.fireflies_wiki import FirefliesWikiAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _banner(title: str) -> None:
    """Print a section banner."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def run_sync(agent: FirefliesWikiAgent) -> None:
    """Run the 07:00 operation: sync, summarize, publish to the wiki."""
    _banner("SYNC — Fireflies → Obsidian → summarize → LLM Wiki")
    report = await agent.sync_meetings_to_wiki()

    sync = report.get("sync") or {}
    analysis = report.get("analysis") or {}
    wiki = report.get("wiki") or {}

    print(f"Status:   {report['status']}")
    print(f"Synced:   {sync.get('synced', 0)} new, {sync.get('skipped', 0)} skipped")
    print(f"Analyzed: {len(analysis.get('analyzed', []))} note(s)")
    for note in analysis.get("analyzed", []):
        print(f"   + {note}")
    if wiki.get("ingested"):
        print("Wiki:     ingested")
    else:
        print(f"Wiki:     skipped ({wiki.get('reason')})")
    for err in sync.get("errors", []):
        print(f"   ! {err}")


async def run_daily(agent: FirefliesWikiAgent) -> None:
    """Run the 08:00 operation: email the daily meeting digest."""
    _banner("DAILY DIGEST — bullet summary of the latest meetings")
    result = await agent.email_daily_meeting_digest()
    print(f"Status:   {result['status']}")
    print(f"Meetings: {result['meetings']}")
    print(f"Emailed:  {result['emailed']}")
    if result.get("reason"):
        print(f"Reason:   {result['reason']}")


async def run_weekly(agent: FirefliesWikiAgent) -> None:
    """Run the Monday operation: email last week's cross-meeting insights."""
    _banner("WEEKLY INSIGHTS — themes and open issues from the past week")
    result = await agent.email_weekly_insights()
    print(f"Status:   {result['status']}")
    print(f"Meetings: {result['meetings']}")
    print(f"Emailed:  {result['emailed']}")
    if result.get("reason"):
        print(f"Reason:   {result['reason']}")


async def main() -> None:
    """Configure the agent and run the requested operation(s)."""
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    agent = FirefliesWikiAgent(name="FirefliesWikiExample")
    await agent.configure()

    try:
        if which in ("sync", "all"):
            await run_sync(agent)
        if which in ("daily", "all"):
            await run_daily(agent)
        if which in ("weekly", "all"):
            await run_weekly(agent)
        if which not in ("sync", "daily", "weekly", "all"):
            print(f"Unknown operation {which!r}. Use: sync | daily | weekly | all")
    except Exception as exc:  # noqa: BLE001 — example runner
        logger.error("Agent run failed: %s", exc, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
