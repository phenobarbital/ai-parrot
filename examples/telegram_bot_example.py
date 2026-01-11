"""
Example: Running AI-Parrot agents via Telegram bots.

This example demonstrates how to expose agents via Telegram using
the integrated TelegramBotManager.

Prerequisites:
1. Create a Telegram bot via @BotFather and get the bot token
2. Create env/telegram_bots.yaml with your configuration
3. Run this script

Configuration (env/telegram_bots.yaml):
```yaml
agents:
  MyAgent:
    chatbot_id: my_agent
    welcome_message: "Hello! I'm your AI assistant."
    # bot_token: optional - defaults to MYAGENT_TELEGRAM_TOKEN env var
```
"""
import asyncio
from aiohttp import web
from parrot.manager import BotManager


async def main():
    """Run server with Telegram bot integration."""
    # Create aiohttp application
    app = web.Application()

    # Initialize BotManager (includes Telegram integration)
    manager = BotManager()
    manager.setup(app)

    # Create and start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 5000)

    print("=" * 60)
    print("AI-Parrot with Telegram Bot Integration")
    print("=" * 60)
    print()
    print("Starting server on http://localhost:5000")
    print("Telegram bots will start polling automatically if configured.")
    print()
    print("Configuration file: env/telegram_bots.yaml")
    print("Bot tokens can be set via environment variables:")
    print("  - {AGENT_NAME}_TELEGRAM_TOKEN (e.g., HRAGENT_TELEGRAM_TOKEN)")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)

    await site.start()

    try:
        # Run forever
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        # Cleanup
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
