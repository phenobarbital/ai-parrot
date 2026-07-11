"""SPK-3 (throwaway): LLM envelope fidelity harness (Claude + Gemini).

Runs the committed prompt set through BOTH clients using the EXISTING structured-output
path (`client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))`),
then classifies each response: parsed-as-CreateSurface, catalog-valid (LLM origin), or a
failure taxonomy class. Writes per-run rows to runs.jsonl and prints per-client validity.

NO client code is changed. Requires live ANTHROPIC + GOOGLE GenAI credentials; if a
provider's credentials are missing it is skipped and the gap is recorded (never fabricate).

Run:  python artifacts/spikes/spk3-envelope-fidelity/spike_fidelity.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

HERE = Path(__file__).parent
PROMPTS = json.loads((HERE / "prompts.json").read_text())
RUNS = HERE / "runs.jsonl"

CLAUDE_MODEL = "claude-3-5-sonnet-latest"
GEMINI_MODEL = "gemini-1.5-pro"
TEMPERATURE = 0.2
MAX_TOKENS = 4096


def check_prompt_set_size_and_diversity() -> None:
    assert len(PROMPTS) >= 20, "need >= 20 prompts"
    cats = {p["category"] for p in PROMPTS}
    assert len(cats) >= 4, "need >= 4 display-UI categories"


def _classify(response) -> tuple[str, str]:
    """Return (outcome_class, detail) for a single response."""
    from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
    from parrot.outputs.a2ui.catalog import CatalogValidationError
    from parrot.outputs.a2ui.models import CreateSurface

    output = getattr(response, "output", None)
    envelope = None
    if isinstance(output, CreateSurface):
        envelope = output
    elif isinstance(output, dict):
        try:
            envelope = CreateSurface.model_validate(output)
        except Exception as exc:  # noqa: BLE001
            return "schema_violation", str(exc)[:160]
    else:
        # client degrades to raw text on parse failure (spec §6)
        return "raw_text_degradation", type(output).__name__

    try:
        validate_envelope(envelope, origin=ProducerOrigin.LLM)
    except CatalogValidationError as exc:
        if exc.action_components:
            return "requires_actions", ",".join(exc.action_components)
        if exc.unknown_components:
            return "unknown_component", ",".join(exc.unknown_components)
        return "other", str(exc)[:160]
    return "catalog_valid", ""


async def _run_client(name, client, model, catalog_instructions, rows):
    from parrot.models.outputs import StructuredOutputConfig
    from parrot.outputs.a2ui.models import CreateSurface

    cfg = StructuredOutputConfig(output_type=CreateSurface)
    system = (
        "You produce ONLY an A2UI v1.0 createSurface envelope for the requested display "
        "UI, using the following catalog components:\n" + catalog_instructions
    )
    for p in PROMPTS:
        try:
            resp = await client.ask(
                p["prompt"], model=model, temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS, system_prompt=system, structured_output=cfg,
            )
            outcome, detail = _classify(resp)
        except Exception as exc:  # noqa: BLE001
            outcome, detail = "call_error", str(exc)[:160]
        rows.append({"client": name, "prompt_id": p["id"], "outcome": outcome, "detail": detail})


async def main() -> None:
    check_prompt_set_size_and_diversity()
    import parrot.outputs.a2ui.catalog.components  # noqa: F401 — register catalog
    from parrot.outputs.a2ui.catalog import catalog_instructions

    instructions = catalog_instructions()
    rows: list[dict] = []
    skipped: list[str] = []

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"):
        from parrot.clients.claude import AnthropicClient

        async with AnthropicClient() as client:  # context mgr per client convention
            await _run_client("claude", client, CLAUDE_MODEL, instructions, rows)
    else:
        skipped.append("claude (no ANTHROPIC_API_KEY)")

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        from parrot.clients.google.client import GoogleGenAIClient

        async with GoogleGenAIClient() as client:
            await _run_client("gemini", client, GEMINI_MODEL, instructions, rows)
    else:
        skipped.append("gemini (no GOOGLE_API_KEY/GEMINI_API_KEY)")

    RUNS.write_text("\n".join(json.dumps(r) for r in rows))
    for name in ("claude", "gemini"):
        client_rows = [r for r in rows if r["client"] == name]
        if not client_rows:
            continue
        valid = sum(1 for r in client_rows if r["outcome"] == "catalog_valid")
        print(f"{name}: {valid}/{len(client_rows)} catalog-valid first-shot")
    if skipped:
        print("SKIPPED (no credentials):", "; ".join(skipped))


if __name__ == "__main__":
    asyncio.run(main())
