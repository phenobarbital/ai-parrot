"""Finance CLI - Quick access to deliberation and memo operations.

Usage:
    python -m parrot.finance deliberate --with-history --ticker SPY
    python -m parrot.finance memos list --days 7
    python -m parrot.finance memos show MEMO-ID
    python -m parrot.finance research list --domain equity
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import click

# Lazy imports to speed up CLI startup
def get_memo_store():
    from parrot.finance.memo_store import get_memo_store as _get_memo_store
    return _get_memo_store()


def get_research_memory():
    from parrot.finance.research.memory import (
        FileResearchMemory,
        get_research_memory as _get_research_memory,
        set_research_memory,
    )
    # Try to get existing instance, or create one
    try:
        return _get_research_memory()
    except RuntimeError:
        path = os.getenv("RESEARCH_MEMORY_PATH", "research_memory")
        memory = FileResearchMemory(base_path=path)
        set_research_memory(memory)
        return memory


# ─────────────────────────────────────────────────────────────────────────────
# CLI Group
# ─────────────────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="0.1.0", prog_name="parrot-finance")
def cli():
    """Parrot Finance CLI - Deliberation and memo management."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Deliberate Command
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--with-history", is_flag=True, help="Use research memory history")
@click.option("--ticker", "-t", default=None, help="Filter research by ticker")
@click.option(
    "--domains",
    "-d",
    default="macro,equity,crypto,sentiment,risk",
    help="Comma-separated domains to query",
)
@click.option("--dry-run", is_flag=True, default=True, help="Simulate execution (default)")
@click.option("--live", is_flag=True, help="Execute real trades (DANGEROUS)")
@click.option("--output", "-o", default=None, help="Output file for memo JSON")
def deliberate(
    with_history: bool,
    ticker: Optional[str],
    domains: str,
    dry_run: bool,
    live: bool,
    output: Optional[str],
):
    """Run committee deliberation and generate investment memo.

    Examples:
        # Quick deliberation with recent research
        python -m parrot.finance deliberate --with-history

        # Focus on specific ticker
        python -m parrot.finance deliberate --with-history --ticker SPY

        # Only macro and sentiment
        python -m parrot.finance deliberate --with-history -d macro,sentiment
    """
    asyncio.run(_deliberate_async(with_history, ticker, domains, dry_run, live, output))


async def _deliberate_async(
    with_history: bool,
    ticker: Optional[str],
    domains: str,
    dry_run: bool,
    live: bool,
    output: Optional[str],
):
    from parrot.finance.research.memory import get_latest_research
    from parrot.finance.swarm import CommitteeDeliberation
    from parrot.finance.schemas import (
        ExecutorConstraints,
        MessageBus,
        PortfolioSnapshot,
        ResearchBriefing,
        ResearchItem,
    )
    from parrot.finance.paper_trading.models import ExecutionMode, PaperTradingConfig

    click.echo("🧠 Parrot Finance - Committee Deliberation")
    click.echo("=" * 50)

    # Gather research
    domain_list = [d.strip() for d in domains.split(",")]
    research_data = {}

    if with_history:
        click.echo(f"📚 Loading research from memory for domains: {domain_list}")
        get_research_memory()  # Ensure memory is initialized

        for domain in domain_list:
            try:
                doc = await get_latest_research(domain)
                if doc and "error" not in doc:
                    research_data[domain] = doc
                    # doc is a dict, use .get() for safe access
                    summary = doc.get("summary", str(doc)[:60])
                    click.echo(f"  ✅ {domain}: {summary[:60]}...")
                else:
                    error_msg = doc.get("error", "No research found") if doc else "No research found"
                    click.echo(f"  ⚠️  {domain}: {error_msg}")
            except Exception as e:
                click.echo(f"  ❌ {domain}: Error - {e}")
    else:
        click.echo("⚠️  No --with-history flag. Running with empty research context.")
        click.echo("   Use --with-history to load from research memory.")

    if not research_data:
        click.echo("\n❌ No research data available. Cannot deliberate.")
        click.echo("   Run research crews first or check RESEARCH_MEMORY_PATH.")
        return

    # Configure execution mode
    if live:
        if not click.confirm("⚠️  LIVE MODE: Real trades will be executed. Continue?"):
            click.echo("Aborted.")
            return
        exec_mode = ExecutionMode.LIVE
    else:
        exec_mode = ExecutionMode.DRY_RUN

    _ = PaperTradingConfig(mode=exec_mode)  # Future use for execution

    click.echo(f"\n🎯 Ticker focus: {ticker or 'All assets'}")
    click.echo(f"⚙️  Execution mode: {exec_mode.value}")
    click.echo("\n🔄 Starting deliberation...")

    try:
        # Create message bus and deliberation committee
        from parrot.bots import Agent
        bus = MessageBus()
        committee = CommitteeDeliberation(message_bus=bus, agent_class=Agent)
        await committee.configure()

        # Build briefings from research data
        briefings: dict[str, ResearchBriefing] = {}
        for domain, doc in research_data.items():
            # Convert research doc dict to ResearchBriefing
            items = []
            summary = doc.get("summary", "")
            briefing_data = doc.get("briefing", {})

            # Create a single research item from the summary
            item = ResearchItem(
                source=f"research_memory:{domain}",
                domain=domain,
                title=f"{domain.upper()} Research",
                summary=summary,
                raw_data=briefing_data if isinstance(briefing_data, dict) else {},
            )
            items.append(item)

            briefings[domain] = ResearchBriefing(
                analyst_id=f"analyst_{domain}",
                domain=domain,
                research_items=items,
            )

        # Create minimal portfolio snapshot (paper trading context)
        portfolio = PortfolioSnapshot(
            total_value_usd=10000.0,
            cash_available_usd=10000.0,
            exposure={"cash": 100.0},
        )

        # Use default executor constraints
        constraints = ExecutorConstraints()

        memo = await committee.run_deliberation(
            briefings=briefings,
            portfolio=portfolio,
            constraints=constraints,
        )

        click.echo("\n" + "=" * 50)
        click.echo("✅ DELIBERATION COMPLETE")
        click.echo("=" * 50)
        click.echo(f"\n📝 Memo ID: {memo.id}")
        click.echo(f"📅 Created: {memo.created_at}")
        consensus = memo.final_consensus.value if hasattr(memo.final_consensus, 'value') else memo.final_consensus
        click.echo(f"🎯 Consensus: {consensus}")
        click.echo(f"📊 Recommendations: {len(memo.recommendations)}")

        click.echo("\n📋 Executive Summary:")
        click.echo("-" * 40)
        click.echo(memo.executive_summary[:500] + "..." if len(memo.executive_summary) > 500 else memo.executive_summary)

        if memo.recommendations:
            click.echo("\n💡 Recommendations:")
            for rec in memo.recommendations[:5]:
                signal = rec.signal.value if hasattr(rec.signal, 'value') else rec.signal
                consensus_lvl = rec.consensus_level.value if hasattr(rec.consensus_level, 'value') else rec.consensus_level
                click.echo(f"  • {rec.asset}: {signal} ({consensus_lvl})")
            if len(memo.recommendations) > 5:
                click.echo(f"  ... and {len(memo.recommendations) - 5} more")

        # Save to file if requested
        if output:
            from dataclasses import asdict
            with open(output, "w") as f:
                json.dump(asdict(memo), f, indent=2, default=str)
            click.echo(f"\n💾 Memo saved to: {output}")

        # Store in memo store
        store = get_memo_store()
        await store.store(memo)
        click.echo("💾 Memo persisted to store")

    except Exception as e:
        click.echo(f"\n❌ Deliberation failed: {e}")
        raise click.ClickException(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Memos Commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def memos():
    """Investment memo operations."""
    pass


@memos.command("list")
@click.option("--days", "-d", default=7, help="Number of days to look back")
@click.option("--ticker", "-t", default=None, help="Filter by ticker")
@click.option("--limit", "-n", default=20, help="Max results")
def memos_list(days: int, ticker: Optional[str], limit: int):
    """List recent investment memos."""
    asyncio.run(_memos_list_async(days, ticker, limit))


async def _memos_list_async(days: int, ticker: Optional[str], limit: int):
    store = get_memo_store()
    start = datetime.now(timezone.utc) - timedelta(days=days)

    click.echo(f"📋 Investment Memos (last {days} days)")
    click.echo("=" * 60)

    memos = await store.get_by_date(start)

    if ticker:
        memos = [
            m for m in memos
            if any(r.asset.upper() == ticker.upper() for r in m.recommendations)
        ]

    memos = memos[-limit:]  # Most recent first

    if not memos:
        click.echo("No memos found.")
        return

    for memo in reversed(memos):
        consensus = memo.final_consensus.value if hasattr(memo.final_consensus, 'value') else memo.final_consensus
        tickers = [r.asset for r in memo.recommendations[:3]]
        tickers_str = ", ".join(tickers)
        if len(memo.recommendations) > 3:
            tickers_str += f" +{len(memo.recommendations) - 3}"

        click.echo(f"\n{memo.id}")
        click.echo(f"  📅 {memo.created_at.strftime('%Y-%m-%d %H:%M')}")
        click.echo(f"  🎯 Consensus: {consensus}")
        click.echo(f"  📊 Tickers: {tickers_str}")
        click.echo(f"  📝 {memo.executive_summary[:80]}...")


@memos.command("show")
@click.argument("memo_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def memos_show(memo_id: str, as_json: bool):
    """Show details of a specific memo."""
    asyncio.run(_memos_show_async(memo_id, as_json))


async def _memos_show_async(memo_id: str, as_json: bool):
    store = get_memo_store()
    memo = await store.get(memo_id)

    if not memo:
        raise click.ClickException(f"Memo not found: {memo_id}")

    if as_json:
        from dataclasses import asdict
        click.echo(json.dumps(asdict(memo), indent=2, default=str))
        return

    click.echo(f"📝 Investment Memo: {memo.id}")
    click.echo("=" * 60)
    click.echo(f"📅 Created: {memo.created_at}")
    click.echo(f"⏰ Valid until: {memo.valid_until or 'N/A'}")
    click.echo(f"🎯 Final consensus: {memo.final_consensus.value}")
    click.echo(f"🔄 Deliberation rounds: {memo.deliberation_rounds}")

    click.echo("\n📋 Executive Summary:")
    click.echo("-" * 40)
    click.echo(memo.executive_summary)

    click.echo("\n🌍 Market Conditions:")
    click.echo("-" * 40)
    click.echo(memo.market_conditions)

    if memo.recommendations:
        click.echo(f"\n💡 Recommendations ({len(memo.recommendations)}):")
        click.echo("-" * 40)
        for rec in memo.recommendations:
            signal = rec.signal.value if hasattr(rec.signal, 'value') else rec.signal
            consensus = rec.consensus_level.value if hasattr(rec.consensus_level, 'value') else rec.consensus_level
            click.echo(f"\n  {rec.asset} ({rec.asset_class.value})")
            click.echo(f"    Signal: {signal} | Consensus: {consensus}")
            click.echo(f"    Action: {rec.action}")
            if rec.sizing_pct:
                click.echo(f"    Size: {rec.sizing_pct}%")
            if rec.entry_price_limit:
                click.echo(f"    Entry: ${rec.entry_price_limit}")
            if rec.stop_loss:
                click.echo(f"    Stop: ${rec.stop_loss}")
            if rec.take_profit:
                click.echo(f"    Target: ${rec.take_profit}")

    # Show events
    events = await store.get_events(memo_id=memo_id, limit=10)
    if events:
        click.echo(f"\n📜 Events ({len(events)}):")
        click.echo("-" * 40)
        for event in events:
            click.echo(f"  {event.timestamp.strftime('%H:%M:%S')} - {event.event_type.value}")


# ─────────────────────────────────────────────────────────────────────────────
# Research Commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def research():
    """Research memory operations."""
    pass


@research.command("list")
@click.option("--domain", "-d", default=None, help="Filter by domain")
@click.option("--days", default=7, help="Days to look back")
@click.option("--limit", "-n", default=10, help="Max results")
def research_list(domain: Optional[str], days: int, limit: int):
    """List recent research documents."""
    asyncio.run(_research_list_async(domain, days, limit))


async def _research_list_async(domain: Optional[str], days: int, limit: int):
    from parrot.finance.research.memory import ALL_DOMAINS, get_research_history

    get_research_memory()  # Ensure initialized
    domains = [domain] if domain else ALL_DOMAINS

    click.echo(f"📚 Research Memory (last {days} days)")
    click.echo("=" * 60)

    for d in domains:
        try:
            docs = await get_research_history(d, last_n=limit)
            if docs:
                click.echo(f"\n📁 {d.upper()}")
                for doc in docs:
                    created = doc.created_at.strftime('%Y-%m-%d %H:%M') if doc.created_at else 'N/A'
                    click.echo(f"  • [{created}] {doc.summary[:60]}...")
            else:
                click.echo(f"\n📁 {d.upper()}: No documents")
        except Exception as e:
            click.echo(f"\n📁 {d.upper()}: Error - {e}")


@research.command("show")
@click.argument("domain")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def research_show(domain: str, as_json: bool):
    """Show latest research for a domain."""
    asyncio.run(_research_show_async(domain, as_json))


async def _research_show_async(domain: str, as_json: bool):
    from parrot.finance.research.memory import get_latest_research

    doc = await get_latest_research(domain)

    if not doc:
        raise click.ClickException(f"No research found for domain: {domain}")

    if as_json:
        from dataclasses import asdict
        click.echo(json.dumps(asdict(doc), indent=2, default=str))
        return

    click.echo(f"📚 Latest Research: {domain.upper()}")
    click.echo("=" * 60)
    click.echo(f"📅 Created: {doc.created_at}")
    click.echo(f"🔑 Period: {doc.period_key}")
    click.echo(f"👤 Crew: {doc.crew_id}")

    click.echo("\n📋 Summary:")
    click.echo("-" * 40)
    click.echo(doc.summary)

    if hasattr(doc, 'briefing') and doc.briefing:
        click.echo("\n📊 Briefing Preview:")
        click.echo("-" * 40)
        briefing_str = str(doc.briefing)
        click.echo(briefing_str[:500] + "..." if len(briefing_str) > 500 else briefing_str)


# ─────────────────────────────────────────────────────────────────────────────
# Status Command
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
def status():
    """Show system status and configuration."""
    asyncio.run(_status_async())


async def _status_async():
    click.echo("🤖 Parrot Finance Status")
    click.echo("=" * 50)

    # Memo store
    memo_path = os.getenv("MEMO_STORE_PATH", "investment_memos")
    click.echo(f"\n💾 Memo Store: {memo_path}")

    try:
        store = get_memo_store()
        start = datetime.now(timezone.utc) - timedelta(days=7)
        memos = await store.get_by_date(start)
        click.echo(f"   Memos (7d): {len(memos)}")
    except Exception as e:
        click.echo(f"   ❌ Error: {e}")

    # Research memory
    research_path = os.getenv("RESEARCH_MEMORY_PATH", "research_memory")
    click.echo(f"\n📚 Research Memory: {research_path}")

    try:
        from parrot.finance.research.memory import ALL_DOMAINS
        get_research_memory()  # Ensure initialized
        for domain in ALL_DOMAINS:
            from parrot.finance.research.memory import get_latest_research
            doc = await get_latest_research(domain)
            if doc:
                age = datetime.now(timezone.utc) - doc.created_at
                click.echo(f"   {domain}: {age.total_seconds() / 3600:.1f}h ago")
            else:
                click.echo(f"   {domain}: No data")
    except Exception as e:
        click.echo(f"   ❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
