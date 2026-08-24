"""AWS Bedrock Agent Example — Amazon Nova Micro

Interactive CLI agent using Amazon Nova Micro on AWS Bedrock via the native
Converse API. Demonstrates tool calling with PythonREPL, calculator,
datetime, and system info.

Usage:
    python examples/agents/aws/agent_nova_micro.py

Environment Variables:
    AWS_DEFAULT_REGION       AWS region (default: us-east-1)
    AWS_ACCESS_KEY_ID        AWS access key (or use IAM role)
    AWS_SECRET_ACCESS_KEY    AWS secret key (or use IAM role)

Note: Amazon Nova text models are served on the `bedrock-runtime` endpoint
(Converse + Invoke) — NOT on Bedrock Mantle. This sample uses the `nova:`
client (`NovaClient`), which composes the Converse text engine with the Nova
voice and image/video generation mixins, and defaults `region_prefix="us"`
so geo-only models resolve out of the box. Pass `region_prefix=None` (or
"eu"/"jp") through `llm_config` for other deployments.

Model facts: text-only (no image or video input) — the cheapest, fastest
Nova tier, intended for simple, high-volume work. Reachable in-region as
`amazon.nova-micro-v1:0` and via the `us.` geo profile; the `nova:` client's
default `region_prefix="us"` resolves it to `us.amazon.nova-micro-v1:0`.
Keep tool schemas small here: a lightweight model degrades faster than the
larger tiers as the tool surface grows.

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
    """Run the Amazon Nova Micro Bedrock agent with an interactive CLI loop."""
    agent = BasicAgent(
        name="NovaMicroAgent",
        llm="nova:nova-micro",
        # Alternative (generic Converse client, no Nova voice/generation mixins;
        # needs the region prefix spelled out because its default is None):
        # llm="bedrock-converse:us.amazon.nova-micro-v1:0",
        tools=[python_repl, calculator, current_datetime, system_info],
        system_prompt=(
            "You are a helpful AI assistant powered by Amazon Nova Micro on AWS Bedrock. "
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

    print("🤖 AWS Bedrock Agent — Amazon Nova Micro (nova)")
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
