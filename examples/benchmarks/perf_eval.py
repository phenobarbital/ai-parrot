"""Performance benchmark for AI-Parrot agents across LLM providers.

Measures wall-clock latency, memory usage, and token consumption for a simple
Chatbot.ask() call across multiple models.

Usage:
    source .venv/bin/activate
    python examples/benchmarks/perf_eval.py
"""

import asyncio
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import List, Optional

from parrot.bots import Chatbot


MODELS = [
    ("anthropic:claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
    ("google:gemini-3.1-flash-lite", "Gemini Flash Lite"),
    ("xai:grok-4.3", "Grok 4.3"),
    ("nvidia:minimaxai/minimax-m3", "MiniMax M3 (NIM)"),
    ("groq:openai/gpt-oss-120b", "GPT-OSS 120B (Groq)"),
    ("moonshot:kimi-k3", "Kimi K3 (Moonshot)"),
    # ("openai:gpt-5.5", "GPT-5.5"),  # disabled — no credits
]

QUESTIONS = [
    "What is the capital of France?",
    "Explain quantum computing in one sentence.",
    "What is 25 * 47?",
]

NUM_ITERATIONS = 3

SYSTEM_PROMPT = "Be concise, reply with one sentence."


@dataclass
class CallResult:
    model_label: str
    question: str
    time_s: float
    memory_mib: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    error: Optional[str] = None


@dataclass
class ModelResults:
    label: str
    calls: List[CallResult] = field(default_factory=list)

    @property
    def successful_calls(self) -> List[CallResult]:
        return [c for c in self.calls if c.error is None]

    @property
    def avg_time(self) -> float:
        s = self.successful_calls
        return sum(c.time_s for c in s) / len(s) if s else 0.0

    @property
    def min_time(self) -> float:
        s = self.successful_calls
        return min(c.time_s for c in s) if s else 0.0

    @property
    def max_time(self) -> float:
        s = self.successful_calls
        return max(c.time_s for c in s) if s else 0.0

    @property
    def avg_memory(self) -> float:
        s = self.successful_calls
        return sum(c.memory_mib for c in s) / len(s) if s else 0.0

    @property
    def avg_input_tokens(self) -> float:
        s = self.successful_calls
        return sum(c.input_tokens for c in s) / len(s) if s else 0.0

    @property
    def avg_output_tokens(self) -> float:
        s = self.successful_calls
        return sum(c.output_tokens for c in s) / len(s) if s else 0.0

    @property
    def avg_total_tokens(self) -> float:
        s = self.successful_calls
        return sum(c.total_tokens for c in s) / len(s) if s else 0.0


async def benchmark_model(
    provider_model: str, label: str
) -> ModelResults:
    """Run the benchmark for a single model."""
    results = ModelResults(label=label)

    try:
        bot = Chatbot(
            name=f"PerfBench-{label}",
            llm=provider_model,
            system_prompt=SYSTEM_PROMPT,
        )
        await bot.configure()
    except Exception as e:
        print(f"  WARNING: Skipping {label}: {e}")
        return results

    for iteration in range(NUM_ITERATIONS):
        for question in QUESTIONS:
            tracemalloc.reset_peak()
            mem_before = tracemalloc.get_traced_memory()[1]

            t0 = time.perf_counter()
            try:
                response = await bot.ask(
                    question,
                    use_conversation_history=False,
                    use_vector_context=False,
                )
                t1 = time.perf_counter()
                mem_after = tracemalloc.get_traced_memory()[1]

                usage = response.usage if response.usage else None
                results.calls.append(CallResult(
                    model_label=label,
                    question=question,
                    time_s=t1 - t0,
                    memory_mib=(mem_after - mem_before) / (1024 * 1024),
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                ))
            except Exception as e:
                t1 = time.perf_counter()
                results.calls.append(CallResult(
                    model_label=label,
                    question=question,
                    time_s=t1 - t0,
                    memory_mib=0.0,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    error=str(e),
                ))
        print(f"  {label}: iteration {iteration + 1}/{NUM_ITERATIONS} complete")

    return results


def print_detail_table(all_results: List[ModelResults]) -> None:
    """Print per-call detail table."""
    hdr = (
        f"{'Model':<22} {'Question':<45} {'Time (s)':>9} "
        f"{'Mem (MiB)':>10} {'In Tok':>7} {'Out Tok':>8}"
    )
    sep = "-" * len(hdr)

    print("\n" + sep)
    print("  PER-CALL DETAILS")
    print(sep)
    print(hdr)
    print(sep)

    for model_res in all_results:
        for call in model_res.calls:
            q_short = (call.question[:42] + "...") if len(call.question) > 45 else call.question
            if call.error:
                print(
                    f"{call.model_label:<22} {q_short:<45} "
                    f"{'ERROR':>9} {'':>10} {'':>7} {'':>8}"
                )
            else:
                print(
                    f"{call.model_label:<22} {q_short:<45} "
                    f"{call.time_s:>9.3f} {call.memory_mib:>10.3f} "
                    f"{call.input_tokens:>7} {call.output_tokens:>8}"
                )
    print(sep)


def print_summary_table(all_results: List[ModelResults]) -> None:
    """Print per-model summary table."""
    hdr = (
        f"{'Model':<22} {'Avg (s)':>8} {'Min (s)':>8} {'Max (s)':>8} "
        f"{'Mem (MiB)':>10} {'In Tok':>7} {'Out Tok':>8} {'Tot Tok':>8}"
    )
    sep = "=" * len(hdr)

    print("\n" + sep)
    print("  PERFORMANCE SUMMARY")
    print(sep)
    print(hdr)
    print(sep)

    for r in all_results:
        if not r.successful_calls:
            print(f"{r.label:<22} {'(no successful calls)':>60}")
            continue
        print(
            f"{r.label:<22} {r.avg_time:>8.3f} {r.min_time:>8.3f} "
            f"{r.max_time:>8.3f} {r.avg_memory:>10.3f} "
            f"{r.avg_input_tokens:>7.0f} {r.avg_output_tokens:>8.0f} "
            f"{r.avg_total_tokens:>8.0f}"
        )
    print(sep)


async def main() -> None:
    tracemalloc.start()

    print(f"AI-Parrot Performance Benchmark")
    print(f"Models: {len(MODELS)} | Questions: {len(QUESTIONS)} | Iterations: {NUM_ITERATIONS}")
    print(f"Total calls per model: {len(QUESTIONS) * NUM_ITERATIONS}")
    print()

    all_results: List[ModelResults] = []

    for provider_model, label in MODELS:
        print(f"Benchmarking {label} ({provider_model})...")
        result = await benchmark_model(provider_model, label)
        all_results.append(result)
        print()

    print_detail_table(all_results)
    print_summary_table(all_results)

    tracemalloc.stop()


if __name__ == "__main__":
    asyncio.run(main())
