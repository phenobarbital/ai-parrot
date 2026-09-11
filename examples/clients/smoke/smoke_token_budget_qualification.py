"""Opt-in strict-qualification probe for question token budgets (FEAT-550, spec §2.5).

Refuses to run without --model, --region/--endpoint, --budget and --i-accept-paid-inference.
Never mutates STRICT_QUALIFICATIONS; writes sanitized findings to artifacts/logs/ and prints
the QualificationKey a reviewer could add by hand if the evidence is accepted.

Usage:
    python examples/clients/smoke/smoke_token_budget_qualification.py \
        --provider bedrock --model claude-haiku-4-5 --region us-east-1 --budget 4000 --i-accept-paid-inference
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from parrot.clients.amazon import BedrockConverseClient, BedrockMantleClient, NovaClient
from parrot.clients.amazon.budget import BedrockBudgetAdapter, MantleBudgetAdapter, fingerprint
from parrot.clients.amazon.budget_qualifications import QualificationKey, installed_sdk_versions, probe_count_tokens_support
from parrot.tools import tool

VARIANTS = ("plain", "tools", "stream", "cache", "schema")


@tool
def get_weather(location: str) -> str:
    """Get the current weather for a given location.

    Args:
        location: The city and state, e.g. San Francisco, CA
    """
    return f"The weather in {location} is sunny and 72 degrees."


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=("bedrock", "nova", "mantle"), required=False)
    p.add_argument("--model")
    p.add_argument("--region")
    p.add_argument("--endpoint", help="Mantle base_url override")
    p.add_argument("--budget", type=int)
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--i-accept-paid-inference", action="store_true")
    return p.parse_args()


def _opted_in(a: argparse.Namespace) -> bool:
    return bool(a.provider and a.model and (a.region or a.endpoint) and a.budget and a.i_accept_paid_inference)


async def _run_variant(client: Any, adapter: Any, variant: str, budget: int) -> dict[str, Any]:
    """One budgeted request; report the ledger's settled totals; note whether the cap was respected."""
    # `token_budget=` on ask()/ask_stream() is the plain int budget amount —
    # `resolve_budget_request()` builds the TokenBudgetPolicy itself
    # (code-reviewer finding, FEAT-550 wrap-up: this used to pass a whole
    # TokenBudgetPolicy instance where an int is required).
    kwargs: dict[str, Any] = {
        "model": client._default_model or "unknown",
        "token_budget": budget,
        "budget_mode": "estimated",
    }

    prompt = "Hello, please reply with exactly one word: 'Acknowledged'."
    
    if variant == "tools":
        kwargs["tools"] = [get_weather]
        prompt = "What is the weather in Seattle, WA?"
    elif variant == "cache":
        # Bedrock Converse cachePoint block if supported
        kwargs["prompt_cache"] = True
        prompt = "This is a long prompt designed to trigger caching. " * 50 + "Please summarize this."
    elif variant == "schema":
        # Mantle response_format
        if hasattr(client, "response_format") or "mantle" in getattr(client, "provider", ""):
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "simple_response",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "reply": {"type": "string"}
                        },
                        "required": ["reply"]
                    }
                }
            }
            prompt = "Reply with JSON containing a 'reply' field set to 'Acknowledged'."
        else:
            return {
                "variant": variant,
                "skipped": True,
                "reason": "Schema variant only supported on Mantle client",
            }

    start_time = time.time()
    try:
        if variant == "stream":
            # Stream request
            chunks = []
            async for chunk in await client.ask_stream(prompt, **kwargs):
                chunks.append(chunk)
            # Reconstruct final message metadata from the stream if available
            # (In our framework, ask_stream returns chunks, and the last chunk or client state holds the report)
            # Let's fetch the report from the client's active budget scope or the last chunk's metadata
            report = None
            if chunks:
                last_chunk = chunks[-1]
                if hasattr(last_chunk, "metadata") and isinstance(last_chunk.metadata, dict):
                    report = last_chunk.metadata.get("token_budget")
            if not report and hasattr(client, "last_budget_report"):
                report = client.last_budget_report
        else:
            # Standard request
            res = await client.ask(prompt, **kwargs)
            report = res.metadata.get("token_budget") if hasattr(res, "metadata") else None

        if not report:
            return {
                "variant": variant,
                "error": "No budget report returned in metadata",
                "passed": False,
            }

        # Read the ledger's real settled totals — `BudgetReport` (see
        # parrot.models.token_budget.BudgetReport) has no per-call
        # "counted estimate" or "last output cap" field to compare against
        # (those live only in the ephemeral per-attempt reservation, not the
        # aggregate report); reading fields that don't exist on the model
        # used to silently return .get()'s default and always report a
        # trivial pass (code-reviewer finding, FEAT-550 wrap-up). This
        # reports the real fields and marks the cap check explicitly
        # unverifiable rather than fabricating a always-True result.
        actual_input = report.get("input_tokens", 0)
        actual_output = report.get("output_tokens", 0)
        overrun = report.get("overrun_tokens", 0)
        cap_respected = None  # not derivable from the aggregate BudgetReport

        # Generate request fingerprint
        # We can construct a dummy payload to get a fingerprint
        dummy_payload = {"model": kwargs["model"], "prompt": prompt}
        if "tools" in kwargs:
            dummy_payload["tools"] = ["get_weather"]
        fp = fingerprint(dummy_payload, route="converse" if "mantle" not in getattr(client, "provider", "") else "chat_completions")

        return {
            "variant": variant,
            "fingerprint": fp,
            "actual_input": actual_input,
            "actual_output": actual_output,
            "overrun_tokens": overrun,
            "cap_respected": cap_respected,
            "method": ",".join(report.get("counting_methods", ())) or "unknown",
            "passed": overrun == 0,
            "latency_ms": int((time.time() - start_time) * 1000),
        }

    except Exception as exc:
        return {
            "variant": variant,
            "error": f"{type(exc).__name__}: {exc}",
            "passed": False,
        }


async def main() -> int:
    a = _parse()
    if not _opted_in(a):
        print("SKIPPED: qualification probe requires --provider --model --region|--endpoint --budget --i-accept-paid-inference")
        return 0

    versions = installed_sdk_versions("botocore", "aiobotocore", "aioboto3", "openai", "tiktoken")
    count_tokens_available = probe_count_tokens_support()

    # Construct client and adapter
    client: Any = None
    adapter: Any = None

    if a.provider == "bedrock":
        client = BedrockConverseClient(region=a.region, model=a.model)
        adapter = BedrockBudgetAdapter()
    elif a.provider == "nova":
        client = NovaClient(region=a.region, model=a.model)
        adapter = BedrockBudgetAdapter()
    elif a.provider == "mantle":
        client = BedrockMantleClient(region=a.region, base_url=a.endpoint, model=a.model)
        adapter = MantleBudgetAdapter()
    else:
        print(f"ERROR: Unknown provider {a.provider}")
        return 1

    selected_variants = [v.strip() for v in a.variants.split(",") if v.strip()]
    results = []

    print(f"Running qualification probe for {a.provider} / {a.model}...")
    async with client:
        for var in selected_variants:
            if var not in VARIANTS:
                continue
            print(f"  Running variant: {var}...")
            res = await _run_variant(client, adapter, var, a.budget)
            results.append(res)

    # Determine if strict qualification is achievable. `count_tokens_available`
    # already gates this False on any SDK without a real CountTokens
    # operation (spec §2.5 — true for the SDKs this probe currently
    # supports); a failed/overrun variant also disqualifies it.
    strict_achievable = count_tokens_available
    for r in results:
        if r.get("skipped"):
            continue
        if not r.get("passed"):
            strict_achievable = False

    findings = {
        "provider": a.provider,
        "model": a.model,
        "endpoint": a.region or a.endpoint,
        "sdk_versions": dict(versions),
        "count_tokens_available": count_tokens_available,
        "results": results,
        "strict_achievable": strict_achievable,
    }

    # Write sanitized findings to artifacts/logs/
    log_dir = Path("artifacts/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    findings_file = log_dir / f"token_budget_qualification_{a.provider}_{a.model.replace('/', '_')}_{timestamp}.json"
    
    with open(findings_file, "w") as f:
        json.dump(findings, f, indent=2)

    print(f"\nFindings written to {findings_file}")
    
    # Print compact PASS/FAIL table
    print("\nVariant Results:")
    print(f"{'Variant':<12} | {'Passed':<6} | {'Actual In':<10} | {'Actual Out':<10} | {'Cap Respected':<13}")
    print("-" * 62)
    for r in results:
        if r.get("skipped"):
            print(f"{r['variant']:<12} | SKIPPED | {r.get('reason', '')}")
            continue
        passed_str = "PASS" if r.get("passed") else "FAIL"
        cap_str = "N/A" if r.get("cap_respected") is None else ("YES" if r.get("cap_respected") else "NO")
        print(f"{r['variant']:<12} | {passed_str:<6} | {r.get('actual_input', 'N/A'):<10} | {r.get('actual_output', 'N/A'):<10} | {cap_str:<13}")

    # Print QualificationKey literal
    print("\nQualification Key for manual registry entry:")
    key = QualificationKey(
        model=a.model,
        endpoint=a.region or a.endpoint or "",
        route="converse" if a.provider != "mantle" else "chat_completions",
        tools="tools" in selected_variants,
        schema="schema" in selected_variants,
        cache="cache" in selected_variants,
        thinking=False,
        stream="stream" in selected_variants,
        sdk_versions=versions,
        count_method="local_estimate" if not count_tokens_available else "count_tokens",
        output_cap_semantics="converse_maxTokens" if a.provider != "mantle" else "max_tokens",
    )
    print(f"QualificationKey(\n    model={key.model!r},\n    endpoint={key.endpoint!r},\n    route={key.route!r},\n    tools={key.tools},\n    schema={key.schema},\n    cache={key.cache},\n    thinking={key.thinking},\n    stream={key.stream},\n    sdk_versions={key.sdk_versions!r},\n    count_method={key.count_method!r},\n    output_cap_semantics={key.output_cap_semantics!r},\n)")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
