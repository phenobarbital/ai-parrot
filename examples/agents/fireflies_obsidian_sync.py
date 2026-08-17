"""Example: Fireflies.ai → Obsidian Vault Sync Agent

Demonstrates syncing meeting transcripts from Fireflies.ai into a local
Obsidian vault with optional LLM-powered summarization.

Usage:
    # 1. Manual sync
    python examples/agents/fireflies_obsidian_sync.py

    # 2. Or schedule via /schedule
    /schedule create fireflies-sync \
        --cron "0 */8 * * *" \
        --command "agent FirefliesObsidianAgent sync"

Requirements:
    - FIREFLIES_API_KEY environment variable set
    - Local Obsidian vault path
"""

import asyncio
import logging
from parrot.agents.obsidian import FirefliesObsidianAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the sync agent."""

    # Initialize agent
    agent = FirefliesObsidianAgent(
        name="FirefliesObsidianSync",
        vault_path="~/vaults/notes",  # Change to your vault path
        # fireflies_token="your-token" or set FIREFLIES_API_KEY env var
    )

    try:
        # PHASE 1: Deterministic sync (no LLM)
        logger.info("=" * 60)
        logger.info("PHASE 1: Syncing latest Fireflies transcripts...")
        logger.info("=" * 60)

        sync_report = await agent.sync_fireflies_transcripts(
            limit=10,  # Fetch latest 10 transcripts
            skip_existing=True,  # Skip already-synced meetings
        )

        print("\n✅ Sync Report:")
        print(f"   Status: {sync_report['status']}")
        print(f"   Synced: {sync_report['synced']} meetings")
        print(f"   Skipped: {sync_report['skipped']} (already synced)")
        if sync_report["errors"]:
            print(f"   Errors: {len(sync_report['errors'])}")
            for error in sync_report["errors"]:
                print(f"     - {error}")

        # PHASE 2: Optional LLM-powered summarization
        # Auto-detect and analyze the first synced meeting
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Analyzing meetings with LLM...")
        logger.info("=" * 60)

        if sync_report["synced"] > 0:
            # Get the first synced note to analyze
            existing_notes = await agent._get_existing_meeting_titles()
            if existing_notes:
                # Pick the first one
                recent_note = list(existing_notes)[0]

                analysis = await agent.summarize_transcript(
                    note_title=recent_note,
                    granularity="standard",  # minimal | standard | detailed
                )

                print("\n✅ Analysis Report:")
                print(f"   Note: {recent_note}")
                print(f"   Status: {analysis['status']}")
                if analysis["status"] == "ok":
                    print(f"   Summary: {analysis['summary'][:100]}...")
                    print(f"   Follow-ups: {len(analysis['follow_ups'])}")
                    print(f"   Insights: {len(analysis['insights'])}")

    except Exception as e:
        logger.error(
            f"Agent failed: {e}",
            exc_info=True
        )

    finally:
        # Optional: cleanup
        pass


if __name__ == "__main__":
    asyncio.run(main())
