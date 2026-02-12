"""
CLI Companion for Human-in-the-Loop.

A standalone process that connects to Redis, listens for pending
HITL interactions, and lets the human respond interactively.

Used when agents run as daemon/background services and cannot
access stdin directly. The companion acts as a "chat client"
for the HITL system.

Usage:
    python -m parrot.human.cli_companion --user jesus --redis redis://localhost:6379

Features:
- Shows all pending questions on startup
- Listens for new questions via Redis pub/sub
- Renders questions using Rich (same UI as CLIHumanChannel)
- Sends responses back through Redis queues
"""
import asyncio
import json
from typing import Optional

from navconfig.logging import logging

from .channels.cli import CLIHumanChannel
from .models import HumanInteraction, HumanResponse

try:
    import click

    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False

try:
    from rich.console import Console
    from rich.panel import Panel

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class HITLCompanion:
    """Interactive CLI companion for the HITL daemon channel.

    Connects to Redis, pulls pending interactions, and lets
    the human respond through a Rich-formatted terminal UI.

    The companion is designed to run alongside (or separately from)
    the agent process. Multiple companions can run for different
    users simultaneously.
    """

    def __init__(
        self,
        user_id: str,
        redis_url: str = "redis://localhost:6379",
        queue_prefix: str = "hitl:cli_queue",
    ) -> None:
        self.user_id = user_id
        self.redis_url = redis_url
        self.queue_prefix = queue_prefix
        self.console = Console() if HAS_RICH else None
        self.logger = logging.getLogger(f"HITL.Companion.{user_id}")

        # Interactive CLI channel for rendering and capturing
        self.cli_channel = CLIHumanChannel(
            console=self.console,
            prompt_prefix=f"🧑 {user_id}",
        )

        self._redis = None
        self._running = True

    async def _get_redis(self):
        """Get or create Redis connection."""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
            except ImportError:
                import aioredis  # type: ignore[no-redef]

            self._redis = aioredis.from_url(
                self.redis_url, decode_responses=True
            )
        return self._redis

    async def run(self) -> None:
        """Main loop: process pending + listen for new interactions."""
        redis = await self._get_redis()

        if self.console:
            self.console.print(
                Panel(
                    f"[bold]HITL Companion[/bold]\n"
                    f"User: {self.user_id}\n"
                    f"Redis: {self.redis_url}\n"
                    f"Waiting for agent questions...\n"
                    f"[dim]Ctrl+C to exit[/dim]",
                    border_style="blue",
                )
            )

        # Process any pending interactions first
        await self._process_pending(redis)

        # Then listen for new ones
        pubsub = redis.pubsub()
        await pubsub.subscribe(
            f"{self.queue_prefix}:{self.user_id}:notify"
        )

        try:
            async for message in pubsub.listen():
                if not self._running:
                    break

                if message["type"] != "message":
                    continue

                try:
                    event = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                # Handle notifications
                if "notification" in event:
                    if self.console:
                        self.console.print(
                            f"\n📬 [green]{event['notification']}[/green]"
                        )
                    continue

                # Handle cancellations
                if "cancelled" in event:
                    if self.console:
                        self.console.print(
                            f"\n⚠️ [yellow]"
                            f"{event.get('message', 'Interaction cancelled')}"
                            f"[/yellow]"
                        )
                    continue

                # New interaction available
                source = event.get("source", "agent")
                q_type = event.get("type", "?")
                if self.console:
                    self.console.print(
                        f"\n🔔 [bold]New question from {source}![/bold] "
                        f"(type: {q_type})"
                    )

                await self._process_pending(redis)

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()

    async def _process_pending(self, redis) -> None:
        """Process all pending interactions in the queue."""
        queue_key = f"{self.queue_prefix}:{self.user_id}:pending"

        while True:
            data = await redis.rpop(queue_key)
            if not data:
                break

            try:
                interaction = HumanInteraction.model_validate_json(data)
            except Exception:
                self.logger.exception("Failed to parse interaction")
                continue

            # Use the interactive channel to render and capture
            async def on_response(response: HumanResponse) -> None:
                await redis.lpush(
                    f"{self.queue_prefix}:{self.user_id}:responses",
                    response.model_dump_json(),
                )
                if self.console:
                    self.console.print(
                        "  [green]✅ Response sent[/green]"
                    )

            self.cli_channel._response_callback = on_response
            await self.cli_channel.send_interaction(
                interaction, self.user_id
            )

    async def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._redis:
            await self._redis.close()


async def _run_companion(user_id: str, redis_url: str) -> None:
    """Run the companion (async entry point)."""
    companion = HITLCompanion(user_id=user_id, redis_url=redis_url)
    try:
        await companion.run()
    except KeyboardInterrupt:
        pass
    finally:
        await companion.shutdown()


def main() -> None:
    """CLI entry point."""
    if HAS_CLICK:

        @click.command()
        @click.option("--user", required=True, help="Your user ID")
        @click.option(
            "--redis",
            default="redis://localhost:6379",
            help="Redis URL",
        )
        def cli(user: str, redis: str) -> None:
            """HITL Companion — answer agent questions from your terminal."""
            try:
                asyncio.run(_run_companion(user, redis))
            except KeyboardInterrupt:
                click.echo("\n👋 Bye!")

        cli()
    else:
        # Fallback without click
        import argparse

        parser = argparse.ArgumentParser(
            description="HITL Companion — answer agent questions"
        )
        parser.add_argument("--user", required=True, help="Your user ID")
        parser.add_argument(
            "--redis",
            default="redis://localhost:6379",
            help="Redis URL",
        )
        args = parser.parse_args()
        try:
            asyncio.run(_run_companion(args.user, args.redis))
        except KeyboardInterrupt:
            print("\n👋 Bye!")


if __name__ == "__main__":
    main()
