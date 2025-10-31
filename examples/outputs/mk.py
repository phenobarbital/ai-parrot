import asyncio
from parrot.bots.agent import Agent
from parrot.outputs import OutputMode


async def example_usage():
    agent = Agent()
    await agent.configure()
    # Example 2: Terminal with Rich Panel
    response = await agent.ask(
        'Explain quantum computing',
        output_mode=OutputMode.MARKDOWN,
        format_kwargs={
            'format': 'terminal',
            'show_panel': True,
            'panel_title': '🔬 Quantum Computing'
        }
    )
    print(response.output)  # Beautiful Rich-formatted output


    # Example 6: Auto-detect (default behavior)
    response = await agent.ask(
        'Explain machine learning',
        output_mode='markdown'
    )
    # Automatically uses:
    # - Rich Panel if in terminal
    # - Panel if in Jupyter and available
    # - IPython Markdown otherwise
    # - Plain text as fallback
    print(response.output)


if __name__ == "__main__":
    asyncio.run(example_usage())
