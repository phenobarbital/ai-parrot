"""Demonstrate structured outputs across multiple LLM clients.

This example shows how to request structured data using both Pydantic models
and Python dataclasses. Each client call attempts to coerce the LLM response
into the requested structure when credentials are available in the environment.
"""
from __future__ import annotations
from typing import List, Union
import asyncio
from dataclasses import dataclass, asdict
from pydantic import BaseModel
from parrot.tools.google import GoogleSearchTool
from parrot.clients import (
    ClaudeClient,
    GoogleGenAIClient,
    GroqClient,
    OpenAIClient,
)
from parrot.models import StructuredOutputConfig, OutputFormat


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

@dataclass
class MovieReview:
    """A movie review with structured information."""
    title: str
    rating: float
    pros: List[str]
    cons: List[str]
    recommendation: str


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
            output = response.structured_output or response.output
            if isinstance(output, WeatherBrief):
                output = asdict(output)

            print(f"\n[{name}] Structured output result:\n{output}\n")

            # Movie review example output
            structured_config = StructuredOutputConfig(
                output_type=MovieReview,
                format=OutputFormat.JSON
            )
            result = await client.ask(
                prompt="Review the movie 'The Matrix' with pros, cons, and rating",
                structured_output=structured_config
            )
            if result.structured_output:
                review = result.structured_output
                print(f"Title: {review.title}")
                print(f"Rating: {review.rating}")
                print(f"Pros: {', '.join(review.pros)}")
                print(f"Cons: {', '.join(review.cons)}")
                print(f"Recommendation: {review.recommendation}")
    except Exception as exc:  # pragma: no cover - example level logging
        print(f"[{name}] Request failed: {exc}")
        return

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
        OpenAIClient(tools=[GoogleSearchTool()]),
        dinner_prompt,
        DinnerPlan,
    )

    await run_example(
        "Claude",
        ClaudeClient(tools=[GoogleSearchTool()]),
        dinner_prompt,
        DinnerPlan,
    )

    await run_example(
        "Groq",
        GroqClient(tools=[GoogleSearchTool()]),
        weather_prompt,
        WeatherBrief,
    )

    await run_example(
        "Google",
        GoogleGenAIClient(tools=[GoogleSearchTool()]),
        weather_prompt,
        StructuredOutputConfig(output_type=WeatherBrief),
    )


if __name__ == "__main__":
    asyncio.run(main())
