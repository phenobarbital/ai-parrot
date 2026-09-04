"""Example: Fireflies.ai → Obsidian Vault Sync Agent

Demonstrates syncing meeting transcripts from Fireflies.ai into a local
Obsidian vault with optional LLM-powered summarization.

Usage:
    # 1. Manual sync
    python examples/agents/fireflies_obsidian_sync.py

    # 2. Or schedule via /schedule
    /schedule create fireflies-sync --cron "0 */8 * * *" --command "agent FirefliesObsidianAgent sync"

Requirements:
    - FIREFLIES_API_KEY environment variable set
    - Local Obsidian vault path
"""

import asyncio
import logging
import os

from parrot.clients.openai.codex_agent import CodexAgentRunOptions
from parrot.agents.obsidian import FirefliesObsidianAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the sync agent."""

    llm = os.getenv("PARROT_FIREFLIES_LLM")
    agent_kwargs = {
        "name": "FirefliesObsidianSync",
        "vault_path": os.getenv("OBSIDIAN_VAULT_PATH", "~/vaults/notes"),
        # fireflies_token="your-token" or set FIREFLIES_API_KEY env var
    }
    if llm:
        agent_kwargs["llm"] = llm
        llm_provider, _, llm_model = llm.partition(":")
        if llm_provider in {"openai-codex", "codex-agent", "codex-code"}:
            backend = os.getenv("PARROT_CODEX_BACKEND", "cli")
            agent_kwargs["llm_kwargs"] = {
                "backend": backend,
                "run_options": CodexAgentRunOptions(
                    backend=backend,
                    model=llm_model or "",
                    sandbox="read-only",
                    approval_policy="never",
                    expose_parrot_tools=False,
                    ephemeral=True,
                ),
            }

    # Initialize agent
    agent = FirefliesObsidianAgent(**agent_kwargs)

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

        # PHASE 2: LLM-powered summarization
        # Summarize EVERY meeting note that has no Analysis section yet —
        # both the ones just synced and any backlog from previous runs.
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Analyzing meetings with LLM...")
        logger.info("=" * 60)

        max_notes = os.getenv("PARROT_FIREFLIES_MAX_ANALYSIS")
        report = await agent.summarize_pending_transcripts(
            granularity="standard",  # minimal | standard | detailed
            limit=int(max_notes) if max_notes else None,
        )

        print("\n✅ Analysis Report:")
        print(f"   Status: {report['status']}")
        print(f"   Analyzed: {len(report['analyzed'])}")
        for note_title in report["analyzed"]:
            print(f"     + {note_title}")
        print(f"   Already analyzed: {len(report['skipped'])}")
        if report["errors"]:
            print(f"   Errors: {len(report['errors'])}")
            for failure in report["errors"]:
                print(f"     - {failure['note']}: {failure['error']}")

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
