"""AWS Bedrock Agent Example — Kimi K2.5

Interactive CLI agent using Moonshot AI's Kimi K2.5 on AWS Bedrock via the
Bedrock Mantle OpenAI-compatible endpoint. Demonstrates tool calling with
PythonREPL, calculator, datetime, and system info.

Usage:
    python examples/agents/aws/agent_kimi_k25.py

Environment Variables:
    AWS_BEDROCK_MANTLE_URL   Bedrock Mantle base URL (region-specific)
                             e.g. https://bedrock-mantle.us-east-1.api.aws/v1
    AWS_DEFAULT_REGION       AWS region (default: us-east-1)
    AWS_ACCESS_KEY_ID        AWS access key (or use IAM role)
    AWS_SECRET_ACCESS_KEY    AWS secret key (or use IAM role)

Note: Kimi K2.5 uses the SAME id — "moonshotai.kimi-k2.5" — on both the
Mantle and the bedrock-runtime endpoints. "moonshotai." is a vendor
namespace with no geo or global inference profile, so the id is passed
through verbatim and is never region-prefixed. This is Kimi on *Bedrock*;
for Moonshot's own API use the `moonshot:` client instead.

Model facts: 256K context, 16K max output tokens, multimodal (text + image
input, 3 MB max image payload); client-side tool calling supported on both
endpoints (server-side tool calling is not).

See examples/agents/aws/README.md for full setup instructions.
"""
import asyncio
import ast
import os
import platform
from datetime import datetime, timezone

from parrot.bots.agent import BasicAgent
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools import tool

EXIT_WORDS = ["exit", "quit", "bye"]

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

python_repl = PythonREPLTool()


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely and return the result.

    Use this for arithmetic calculations, algebra, or any numeric computation.
    Example: calculator("2 ** 100"), calculator("(3 + 4) * 7 / 2")
    """
    try:
        try:
            result = ast.literal_eval(expression)
        except (ValueError, SyntaxError):
            safe_globals: dict = {"__builtins__": {}}
            safe_locals: dict = {}
            result = eval(expression, safe_globals, safe_locals)  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Error evaluating expression: {exc}"


@tool
def current_datetime() -> str:
    """Get the current date and time in UTC.

    Returns an ISO-8601 formatted string with timezone offset.
    """
    return datetime.now(timezone.utc).isoformat()


@tool
def system_info() -> str:
    """Get system information: Python version, platform, and working directory.

    Useful for debugging environment issues or understanding the execution context.
    """
    return (
        f"Python: {platform.python_version()}\n"
        f"Platform: {platform.platform()}\n"
        f"Working directory: {os.getcwd()}"
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run the Kimi K2.5 Bedrock Mantle agent with an interactive CLI loop."""
    agent = BasicAgent(
        name="KimiK25Agent",
        llm="bedrock-mantle:moonshotai.kimi-k2.5",
        # Alternative (native Converse API on the bedrock-runtime endpoint):
        # llm="bedrock-converse:kimi-k2.5",
        tools=[python_repl, calculator, current_datetime, system_info],
        system_prompt=(
            "You are a helpful AI assistant powered by Kimi K2.5 on AWS Bedrock. "
            "You have access to tools for running Python code, doing math, checking "
            "the current time, and inspecting system information. "
            "Use tools when they help you give a more accurate or complete answer."
        ),
    )

    try:
        await agent.configure()
    except Exception as exc:
        print(f"❌ Failed to configure agent: {exc}")
        print("   See examples/agents/aws/README.md for setup instructions.")
        return

    print("🤖 AWS Bedrock Agent — Kimi K2.5 (bedrock-mantle)")
    print("   Tools: python_repl, calculator, current_datetime, system_info")
    print("   Type 'exit', 'quit', or 'bye' to quit.\n")

    while True:
        try:
            query = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() in EXIT_WORDS:
            print("Goodbye!")
            break

        response = await agent.invoke(query)
        print(f"Agent > {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
