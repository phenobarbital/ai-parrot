
import argparse
import asyncio
import os
import json
import time
from typing import List, Optional
from pydantic import BaseModel, Field
from parrot.clients.google.client import GoogleGenAIClient
from parrot.models.google import GoogleModel
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.models.basic import ToolCall

# Default test set: 3 whitelisted + 1 known-fallback model for regression visibility.
DEFAULT_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",            # falls back to two-phase — keep for regression visibility
)

# 1. Define Structured Output Schema
class WeatherReport(BaseModel):
    location: str = Field(..., description="The city and country")
    temperature: float = Field(..., description="Current temperature in Celsius")
    condition: str = Field(..., description="Weather condition (e.g., Sunny, Rainy)")
    summary: str = Field(..., description="A short summary of the weather")

# 2. Define a Mock Tool
class WeatherTool(AbstractTool):
    name = "get_weather"
    description = "Get current weather for a location"

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and country"
                    }
                },
                "required": ["location"]
            }
        }

    async def _execute(self, location: str, **kwargs):
        print(f"DEBUG: WeatherTool._execute called for {location}")
        return {
            "location": location,
            "temperature": 25.5,
            "condition": "Partly Cloudy",
            "humidity": 60
        }


def _is_combined_mode_default(model: str) -> bool:
    """Local helper — mirrors the client's default whitelist without importing private state."""
    return any(
        model.startswith(p)
        for p in GoogleGenAIClient._default_combined_call_prefixes
    )


async def run_one(client: GoogleGenAIClient, model: str, prompt: str) -> None:
    mode = "combined-mode" if _is_combined_mode_default(model) else "two-phase"
    print(f"\n=== {model}  [{mode}] ===")
    print(f"Prompt: {prompt}")
    t0 = time.perf_counter()
    try:
        response = await client.ask(
            prompt=prompt,
            model=model,
            structured_output=WeatherReport,
            use_tools=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  ERROR {type(e).__name__}: {e}  ({elapsed:.2f}s)")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.perf_counter() - t0
    is_weather = isinstance(response.structured_output, WeatherReport)
    print(f"  OK structured_output_is_WeatherReport={is_weather}  "
          f"tool_calls={len(response.tool_calls or [])}  ({elapsed:.2f}s)")
    if is_weather:
        print(f"     -> {response.structured_output}")
    if response.tool_calls:
        for tc in response.tool_calls:
            print(f"     -> tool {tc.name}({tc.arguments}) -> {tc.result}")


async def main(models: list, prompt: str) -> None:
    tool_manager = ToolManager()
    tool_manager.register_tool(WeatherTool())
    client = GoogleGenAIClient(
        api_key=os.environ.get("GOOGLE_API_KEY"),
        tool_manager=tool_manager,
        enable_tools=True,
    )
    for model in models:
        await run_one(client, model, prompt)


if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Please set GOOGLE_API_KEY environment variable")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Exercise combined-mode tool-calling + structured output for Gemini models."
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Model identifier to test. Repeat the flag to test multiple. "
             "If omitted, the default whitelist + gemini-2.5-pro is tested.",
    )
    parser.add_argument(
        "--prompt",
        default="What's the weather like in Madrid, Spain? Please return a structured report.",
    )
    args = parser.parse_args()

    asyncio.run(main(args.models or list(DEFAULT_MODELS), args.prompt))
