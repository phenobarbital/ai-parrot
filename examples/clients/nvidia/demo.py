"""Code generation on Nvidia NIM with the Z.ai GLM model, timed and metered.

Demonstrates ``NvidiaClient`` driving ``z-ai/glm-5.2`` (:attr:`NvidiaModel.GLM_5_2`)
through a code-generation task, then reports wall-clock timing and token usage.

GLM-5.2 is reasoning-capable, so the example enables Nvidia's ``enable_thinking``
flag: the model reasons before emitting code. That reasoning is billed as
completion tokens, which is exactly why the token report below separates prompt
from completion tokens and derives a throughput figure — with thinking on, the
completion count is much higher than the visible answer alone suggests.

Run it::

    export NVIDIA_API_KEY=nvapi-...          # never hardcode the key
    python examples/clients/nvidia/demo.py

    # a much faster model — recommended for a first run
    python examples/clients/nvidia/demo.py --model STEPFUN_STEP_3_7_FLASH

    # omit GLM's enable_thinking flag
    python examples/clients/nvidia/demo.py --no-thinking

    # a paid/self-hosted NIM endpoint with no 40 rpm cap
    python examples/clients/nvidia/demo.py --paid-tier

Be warned about GLM-5.2's latency: with thinking enabled, a task this size was
measured running past 15 minutes without completing. It is the interesting model
to *read* about, not the one to wait on. Use
``--model STEPFUN_STEP_3_7_FLASH`` for a run that finishes in ~75s. ``--model``
takes any :class:`NvidiaModel` member name or a raw ``vendor/model`` slug.

Notes:
    - ``AIMessage.code`` is populated only by the Gemini response factory, so on
      the Nvidia path it stays ``None``. This example extracts fenced code
      blocks from the response text itself.
    - ``NvidiaClient`` defaults to ``free_tier=True``, throttling to 40 rpm to
      respect Nvidia's free-endpoint quota. A single call never waits, but the
      report prints the limiter state so the effect is visible.
    - ``--no-thinking`` only omits GLM's ``chat_template_kwargs`` flag. Models
      that reason unconditionally — ``step-3.7-flash`` among them — keep
      reasoning either way, and their chain of thought is billed as completion
      tokens. Measured on this task: 10,776 characters of hidden reasoning
      against a 1,730-character visible answer.
    - Because of that, ``--max-tokens`` defaults to 16384 (matching Nvidia's own
      reference snippet). Set it too low and the cap is consumed entirely by
      reasoning, so the provider bills the tokens and returns ``content=None``
      — the example detects and explains that case rather than printing nothing.
    - Nvidia's reference snippet also sets ``top_p`` and ``seed``, but
      ``OpenAIClient.ask()`` has a fixed signature with no ``**kwargs``, so
      passing them raises ``TypeError``. Only ``max_tokens`` and ``temperature``
      are forwardable through ``ask()``.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time

from navconfig import config
from parrot.clients.nvidia import NvidiaClient
from parrot.models.nvidia import NvidiaModel

from parrot.models import AIMessage

#: The code-generation task handed to the model.
TASK = """\
Write a single Python function `merge_intervals(intervals)` that merges a list
of possibly-overlapping closed integer intervals.

Requirements:
- Signature: `def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:`
- Return the merged intervals sorted ascending by start.
- Treat intervals as closed, so (1, 2) and (3, 4) do NOT merge, but (1, 3) and
  (3, 5) DO merge into (1, 5).
- Raise ValueError if any interval has start > end.
- Include a Google-style docstring and full type hints.
- Return ONLY one ```python fenced code block, no prose before or after.
"""

FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code_blocks(text: str) -> list[str]:
    """Pull fenced code blocks out of a model response.

    ``AIMessage.code`` is only filled in by the Gemini factory, so for Nvidia
    responses the fenced blocks have to be recovered from the text.

    Args:
        text: Raw response text from the model.

    Returns:
        The contents of each fenced block, in order. Empty when the model
        answered without fencing.
    """
    return [block.strip() for block in FENCE_RE.findall(text or "")]


def response_text(message: AIMessage) -> str:
    """Return the model's textual answer from an ``AIMessage``.

    ``output`` is typed ``Any`` and carries the structured value when structured
    output was requested, so fall back to ``response`` for the plain text.

    Args:
        message: The message returned by ``NvidiaClient.ask``.

    Returns:
        The response text, or an empty string when neither field holds text.
    """
    for candidate in (message.response, message.output):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def reasoning_text(message: AIMessage) -> str:
    """Recover hidden reasoning text from the raw provider payload.

    Reasoning models return their chain of thought in ``reasoning_content``
    alongside (or instead of) ``content``. Those tokens are billed as completion
    tokens, so a token report that ignores them is misleading.

    Args:
        message: The message whose ``raw_response`` should be inspected.

    Returns:
        The reasoning text, or an empty string when the provider sent none.
    """
    raw = message.raw_response
    if not isinstance(raw, dict):
        return ""
    for choice in raw.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        payload = choice.get("message")
        if not isinstance(payload, dict):
            continue
        for key in ("reasoning_content", "reasoning"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def format_duration(seconds: float | None) -> str:
    """Render a duration for the report, tolerating ``None``.

    Args:
        seconds: Duration in seconds, or ``None`` when the provider omitted it.

    Returns:
        A human-readable duration, or ``"n/a"``.
    """
    if seconds is None:
        return "n/a"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def print_timing(elapsed: float, message: AIMessage) -> None:
    """Print the timing breakdown for one completion.

    Three clocks are reported because they answer different questions:
    ``elapsed`` is what the caller waited (including any rate-limit throttling),
    ``response_time`` is what the client measured around the SDK call, and the
    ``usage.*_time`` fields are whatever the provider chose to report.

    Args:
        elapsed: Wall-clock seconds measured around the ``ask`` call.
        message: The resulting message, read for its timing fields.
    """
    usage = message.usage
    print("\n--- timing ---")
    print(f"  wall clock (caller)      : {format_duration(elapsed)}")
    print(f"  AIMessage.response_time  : {format_duration(message.response_time)}")
    print(f"  usage.queue_time         : {format_duration(usage.queue_time)}")
    print(f"  usage.prompt_time        : {format_duration(usage.prompt_time)}")
    print(f"  usage.completion_time    : {format_duration(usage.completion_time)}")
    print(f"  usage.total_time         : {format_duration(usage.total_time)}")

    provider_times = (
        usage.queue_time,
        usage.prompt_time,
        usage.completion_time,
        usage.total_time,
    )
    if all(value is None for value in provider_times):
        print(
            "  (Nvidia's OpenAI-compatible responses carry no server-side timing\n"
            "   breakdown — those fields are populated by providers like Groq.\n"
            "   Wall clock is the only trustworthy number here.)"
        )


def print_usage(elapsed: float, message: AIMessage) -> None:
    """Print token usage plus a derived throughput figure.

    Args:
        elapsed: Wall-clock seconds measured around the ``ask`` call, used as
            the denominator for output throughput.
        message: The resulting message, read for its usage counters.
    """
    usage = message.usage
    print("\n--- token usage ---")
    print(f"  prompt tokens            : {usage.prompt_tokens:>8,}")
    print(f"  completion tokens        : {usage.completion_tokens:>8,}")
    print(f"  total tokens             : {usage.total_tokens:>8,}")

    # Prefer the provider's own generation time; fall back to wall clock.
    basis = usage.completion_time or elapsed
    if usage.completion_tokens and basis:
        print(f"  output throughput        : {usage.completion_tokens / basis:>8.1f} tok/s")

    if usage.estimated_cost is not None:
        print(f"  estimated cost           : ${usage.estimated_cost:.6f}")
    if usage.extra_usage:
        print(f"  extra usage              : {usage.extra_usage}")

    # Reasoning models bill their hidden chain of thought as completion tokens,
    # so report it — otherwise the completion count looks inexplicably large
    # relative to the visible answer.
    reasoning = reasoning_text(message)
    if reasoning:
        visible = len(response_text(message))
        print(
            f"  hidden reasoning         : {len(reasoning):>8,} chars "
            f"(billed in completion tokens; visible answer is {visible:,} chars)"
        )

    if usage.total_tokens == 0:
        print("  (all counters zero — this provider did not return a usage block)")


def print_limiter_state(client: NvidiaClient, elapsed: float) -> None:
    """Print the free-tier rate-limiter state, if the client has one.

    The occupancy figure needs context to avoid reading as a bug: the window
    *slides*, so a slot consumed at the start of a call that ran longer than
    the window has already aged out by the time this prints. Zero occupancy
    after a slow call is correct, not a missed count.

    Args:
        client: The client that just served a request.
        elapsed: Wall-clock seconds the request took, used to explain an
            occupancy that has already decayed to zero.
    """
    print("\n--- rate limit ---")
    limiter = client._rate_limiter
    if limiter is None:
        print("  free_tier=False — no throttling applied")
        return

    used = limiter.current_usage()
    print(f"  free_tier=True — {limiter.limit} requests / {limiter.window:g}s")
    print(f"  slots used in window     : {used}/{limiter.limit}")
    if used == 0 and elapsed > limiter.window:
        print(
            f"  (this call took {elapsed:.1f}s, longer than the {limiter.window:g}s "
            "window, so its slot already aged out — expected, not a missed count)"
        )


def resolve_model(name: str) -> str:
    """Resolve a CLI model argument to a NIM slug.

    Accepts either an :class:`NvidiaModel` member name (``GLM_5_2``) or a raw
    slug (``z-ai/glm-5.2``), so the example works with catalog models that have
    no enum member yet.

    Args:
        name: Member name or raw ``vendor/model`` slug.

    Returns:
        The resolved slug.

    Raises:
        SystemExit: If ``name`` is neither a known member nor slug-shaped.
    """
    try:
        return NvidiaModel[name.upper()].value
    except KeyError:
        pass
    if "/" in name:
        return name
    known = ", ".join(sorted(m.name for m in NvidiaModel))
    raise SystemExit(
        f"unknown model {name!r}: pass a vendor/model slug or one of: {known}"
    )


async def generate_code(
    *,
    model: str,
    enable_thinking: bool,
    free_tier: bool,
    max_tokens: int,
    temperature: float,
) -> tuple[AIMessage, float]:
    """Run the code-generation task against a NIM-hosted model.

    Note:
        Nvidia's reference snippet for these models also sets ``top_p`` and
        ``seed``, but ``OpenAIClient.ask()`` has a fixed signature with no
        ``**kwargs``, so those two raise ``TypeError`` here and are omitted.
        To use them, call ``client.client.chat.completions.create(...)``
        directly — the rate limiter only covers ``ask``/``ask_stream``, so a
        direct SDK call bypasses the free-tier throttle.

    Args:
        model: NIM model slug to generate with.
        enable_thinking: Forward Nvidia's reasoning flags so the model reasons
            before answering. This drives GLM's ``chat_template_kwargs``; models
            that reason unconditionally (e.g. ``step-3.7-flash``) do so
            regardless of this flag.
        free_tier: Throttle to Nvidia's 40 rpm free-endpoint quota.
        max_tokens: Upper bound on generated tokens. Reasoning models need
            headroom — too low a cap truncates before any code is emitted.
        temperature: Sampling temperature.

    Returns:
        A tuple of the resulting message and the wall-clock seconds elapsed.
    """
    # ``async with`` is required: ask() does not initialize the SDK client
    # itself, so without entering the context self.client stays None.
    async with NvidiaClient(model=model, free_tier=free_tier) as client:
        started = time.perf_counter()
        message = await client.ask(
            TASK,
            enable_thinking=enable_thinking,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        elapsed = time.perf_counter() - started

        print(f"\nmodel    : {message.model}")
        print(f"provider : {message.provider}")
        print(f"finish   : {message.finish_reason or message.stop_reason or 'n/a'}")

        print_timing(elapsed, message)
        print_usage(elapsed, message)
        print_limiter_state(client, elapsed)

    return message, elapsed


def report_code(message: AIMessage) -> int:
    """Print the generated code and report whether it is syntactically valid.

    Compiling the block is a cheap, honest check: it proves the model returned
    parseable Python without executing anything it wrote.

    Args:
        message: The message holding the model's answer.

    Returns:
        Process exit status — ``0`` when a compilable block was produced.
    """
    text = response_text(message)
    blocks = extract_code_blocks(text)

    print("\n--- generated code ---")
    if not blocks:
        # The common cause is a max_tokens cap swallowed whole by hidden
        # reasoning: the provider bills the tokens and returns content=None.
        # Diagnose that specifically rather than printing a bare empty string.
        truncated = (message.finish_reason or message.stop_reason) == "length"
        if not text and truncated:
            print(
                "  empty answer: generation hit the max_tokens cap before any\n"
                "  visible content was emitted."
            )
            if reasoning_text(message):
                print(
                    "  All completion tokens went into hidden reasoning — this\n"
                    "  model reasons unconditionally, and --no-thinking does not\n"
                    "  stop it (that flag only drives GLM's chat_template_kwargs)."
                )
            print("  Re-run with a larger --max-tokens.")
            return 1
        print("  no fenced code block found. Raw response follows:\n")
        print(text or "  (empty response)")
        return 1

    code = blocks[0]
    print(code)

    try:
        compile(code, "<generated>", "exec")
    except SyntaxError as exc:
        print(f"\n  NOT valid Python: {exc}")
        return 1
    print("\n  compiles cleanly (not executed)")
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line options.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model",
        default="GLM_5_2",
        help=(
            "NvidiaModel member name or raw vendor/model slug "
            "(default: GLM_5_2; try STEPFUN_STEP_3_7_FLASH for a fast run)"
        ),
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help=(
            "omit GLM's enable_thinking flag; note models that reason "
            "unconditionally (e.g. step-3.7-flash) are unaffected"
        ),
    )
    parser.add_argument(
        "--paid-tier",
        action="store_true",
        help="disable the 40 rpm free-tier throttle (paid/self-hosted NIM)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=16384,
        help=(
            "generation cap. Default 16384 matches Nvidia's own reference "
            "snippet; reasoning models need this much headroom or the cap is "
            "consumed by hidden reasoning and no answer is emitted"
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help=(
            "sampling temperature. Default 1.0 follows Nvidia's reference "
            "snippet; reasoning models degrade at 0.0, so prefer 1.0 here even "
            "though code generation usually favours determinism"
        ),
    )
    return parser.parse_args()


async def main() -> int:
    """Entry point.

    Returns:
        Process exit status.
    """
    args = parse_args()

    if not config.get("NVIDIA_API_KEY"):
        print("NVIDIA_API_KEY is not set. Export it and re-run:")
        print("    export NVIDIA_API_KEY=nvapi-...")
        return 2

    model = resolve_model(args.model)
    enable_thinking = not args.no_thinking
    print(f"model          : {model}")
    print(f"thinking       : {enable_thinking}")
    print(f"free_tier      : {not args.paid_tier}")
    print(f"max_tokens     : {args.max_tokens}")
    print(f"temperature    : {args.temperature}")
    print("\nasking...")

    message, _ = await generate_code(
        model=model,
        enable_thinking=enable_thinking,
        free_tier=not args.paid_tier,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    return report_code(message)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
