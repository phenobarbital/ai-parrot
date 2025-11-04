"""Demonstrate structured outputs across multiple LLM clients.

This example shows how to request structured data using both Pydantic models
and Python dataclasses. Each client call attempts to coerce the LLM response
into the requested structure when credentials are available in the environment.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import List, Union

from pydantic import BaseModel

from parrot.clients import (
    ClaudeClient,
    GoogleGenAIClient,
    GroqClient,
    OpenAIClient,
)
from parrot.models import StructuredOutputConfig


class DinnerPlan(BaseModel):
    """Simple structured plan for a dinner menu."""

    appetizer: str
    main_course: str
    dessert: str
    shopping_list: List[str]


@dataclass
class WeatherBrief:
    """Weather summary captured as a dataclass."""

    location: str
    outlook: str
    high_celsius: float
    low_celsius: float


async def run_example(
    name: str,
    client,
    prompt: str,
    structured_output: Union[type, StructuredOutputConfig],
) -> None:
    """Execute a single structured output request and display the result."""
    try:
        async with client:
            response = await client.ask(
                prompt=prompt,
                structured_output=structured_output,
            )
    except Exception as exc:  # pragma: no cover - example level logging
        print(f"[{name}] Request failed: {exc}")
        return

    output = response.structured_output or response.output
    if isinstance(output, WeatherBrief):
        output = asdict(output)

    print(f"\n[{name}] Structured output result:\n{output}\n")


async def main() -> None:
    """Run structured output examples for each supported client."""

    dinner_prompt = (
        "Design a cozy dinner plan for two people including an appetizer, "
        "main course, dessert, and a short shopping list."
    )
    weather_prompt = (
        "Provide tomorrow's weather forecast for Lisbon with a short summary "
        "and the expected high and low temperatures in Celsius."
    )

    await run_example(
        "OpenAI",
        OpenAIClient(),
        dinner_prompt,
        DinnerPlan,
    )

    await run_example(
        "Claude",
        ClaudeClient(),
        dinner_prompt,
        DinnerPlan,
    )

    await run_example(
        "Groq",
        GroqClient(),
        weather_prompt,
        WeatherBrief,
    )

    await run_example(
        "Google",
        GoogleGenAIClient(),
        weather_prompt,
        StructuredOutputConfig(output_type=WeatherBrief),
    )


if __name__ == "__main__":
    asyncio.run(main())
