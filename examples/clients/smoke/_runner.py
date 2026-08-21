"""Shared runner for FEAT-438 (OpenAI-Compatible Client Base) smoke scripts.

Each ``smoke_<provider>.py`` script in this package is a thin, credential-
gated wrapper around :func:`run_smoke`: construct the client via
``LLMFactory.create("provider:model")``, exercise three legs —

1. plain ``ask()``,
2. ``ask()`` with one ``@tool`` registered (verifies the tool wire format
   end-to-end for that provider),
3. ``invoke()`` (verifies the lightweight-model resolution chain — the
   original DeepSeek-404 repro path FEAT-438 exists to kill),

— and print a compact PASS/FAIL summary. No pytest markers: these are
plain scripts, run manually, so a missing credential never blocks CI or a
keyless machine (each script exits 0 with a ``SKIPPED`` message before
touching the network).

Usage (from any one of the ``smoke_*.py`` scripts)::

    python examples/clients/smoke/smoke_openai.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from parrot.clients.factory import LLMFactory
from parrot.tools import tool


@tool
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression and return the result.

    Use this for basic arithmetic. Example: calculator("2 + 2").
    """
    try:
        # Deliberately tiny/safe: smoke scripts only need to prove the
        # tool wire format round-trips, not general-purpose evaluation.
        allowed = set("0123456789+-*/(). ")
        if not set(expression) <= allowed:
            return "Error: unsupported characters in expression"
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


@dataclass
class LegResult:
    """Outcome of a single smoke-test leg (ask / ask+tool / invoke)."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class SmokeResult:
    """Aggregate outcome for one provider's smoke run."""

    provider: str
    model: str
    skipped: bool = False
    skip_reason: str = ""
    legs: list = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.legs) and all(leg.passed for leg in self.legs)


def check_env_vars(env_vars: list[str]) -> str | None:
    """Return the name of the first missing env var, or ``None`` if all set.

    Args:
        env_vars: Env var names where AT LEAST ONE must be set (an
            "any-of" gate — matches how each client resolves its own key,
            e.g. Mantle's ``BEDROCK_MANTLE_API_KEY`` OR ``AWS_NOVA_API_KEY``).

    Returns:
        ``None`` if at least one var is set; otherwise a human-readable
        "no <VAR1>/<VAR2>" message.
    """
    if any(os.getenv(var) for var in env_vars):
        return None
    return f"no {'/'.join(env_vars)}"


async def _run_leg(name: str, coro) -> LegResult:
    try:
        await coro
        return LegResult(name=name, passed=True)
    except Exception as exc:  # noqa: BLE001
        return LegResult(name=name, passed=False, detail=f"{type(exc).__name__}: {exc}")


async def run_smoke(
    *,
    provider: str,
    model: str,
    env_vars: list[str],
    client_kwargs: dict[str, Any] | None = None,
    extra_client_kwargs_factory: Callable[[], dict[str, Any]] | None = None,
) -> SmokeResult:
    """Run the standard ask/ask+tool/invoke smoke sequence for one provider.

    Args:
        provider: The ``LLMFactory`` provider key (e.g. ``"nvidia"``).
        model: The model id to use for all three legs — pick a small,
            cheap model per provider.
        env_vars: Credential env var names; the run is skipped (not
            failed) if none are set.
        client_kwargs: Extra kwargs forwarded to ``LLMFactory.create``
            (e.g. ``region="us-east-1"`` for Bedrock Mantle).
        extra_client_kwargs_factory: Optional callable returning
            additional kwargs computed at call time (e.g. reading an env
            var not covered by ``env_vars``).

    Returns:
        A :class:`SmokeResult` — check ``.skipped`` first, then
        ``.all_passed``.
    """
    missing = check_env_vars(env_vars)
    if missing:
        return SmokeResult(provider=provider, model=model, skipped=True, skip_reason=missing)

    kwargs = dict(client_kwargs or {})
    if extra_client_kwargs_factory:
        kwargs.update(extra_client_kwargs_factory())

    result = SmokeResult(provider=provider, model=model)
    try:
        client = LLMFactory.create(f"{provider}:{model}", **kwargs)
    except Exception as exc:  # noqa: BLE001
        result.legs.append(LegResult(name="construct", passed=False, detail=f"{type(exc).__name__}: {exc}"))
        return result

    async def _ask_plain():
        # max_tokens=64 (not 16): reasoning-heavy models (e.g. Bedrock
        # Mantle's openai.gpt-oss-120b) spend some of the budget on
        # hidden reasoning tokens before any visible content, so a very
        # tight cap can trip the SDK's length-guard before content exists.
        response = await client.ask("Say the single word: ready", max_tokens=64)
        if not getattr(response, "output", None) and not getattr(response, "response", None):
            raise AssertionError("ask() returned an empty response")

    async def _ask_with_tool():
        response = await client.ask(
            "Use the calculator tool to compute 21 + 21, then state the result.",
            tools=[calculator],
            use_tools=True,
            max_tokens=64,
        )
        if response is None:
            raise AssertionError("ask()+tool returned None")

    async def _invoke():
        # The original 404 repro path: invoke() resolves the
        # lightweight-model chain (_lightweight_model -> self.model),
        # which must never silently fall through to an OpenAI gpt-* id
        # for a non-OpenAI provider.
        invoke_result = await client.invoke("Reply with the single word: ready", max_tokens=16)
        if invoke_result is None:
            raise AssertionError("invoke() returned None")

    # AbstractClient requires its async context manager to initialize the
    # per-loop SDK client before ask()/invoke() will work — see
    # AbstractClient.__aenter__ / _ensure_client() in clients/base.py.
    async with client:
        result.legs.append(await _run_leg("ask", _ask_plain()))
        result.legs.append(await _run_leg("ask+tool", _ask_with_tool()))
        result.legs.append(await _run_leg("invoke", _invoke()))
    return result


def print_summary(result: SmokeResult) -> int:
    """Print a compact PASS/FAIL/SKIPPED summary; return a process exit code."""
    header = f"[{result.provider}:{result.model}]"
    if result.skipped:
        print(f"{header} SKIPPED ({result.skip_reason})")
        return 0

    for leg in result.legs:
        status = "PASS" if leg.passed else "FAIL"
        suffix = f" — {leg.detail}" if leg.detail else ""
        print(f"{header} {leg.name:<10} {status}{suffix}")

    return 0 if result.all_passed else 1


def main_for(
    *,
    provider: str,
    model: str,
    env_vars: list[str],
    client_kwargs: dict[str, Any] | None = None,
    extra_client_kwargs_factory: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Standard ``if __name__ == "__main__"`` entrypoint for a smoke script."""

    async def _main() -> int:
        result = await run_smoke(
            provider=provider,
            model=model,
            env_vars=env_vars,
            client_kwargs=client_kwargs,
            extra_client_kwargs_factory=extra_client_kwargs_factory,
        )
        return print_summary(result)

    try:
        exit_code = asyncio.run(_main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        exit_code = 1
    sys.exit(exit_code)
