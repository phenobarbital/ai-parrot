"""FEAT-310 emitter-overhead micro-benchmark (spec §5 acceptance evidence).

Measures the wall-clock cost of ``await EventBus.emit(...)`` with a
deliberately SLOW subscriber registered — proving the emitter pays only the
enqueue cost (goal G2), never the handler cost.

FEAT-177 budget: emitter-side overhead < 0.1% of a representative LLM call
latency. Reference figure (documented, same basis as FEAT-177/otel spec):
a typical LLM completion takes ~2 s ⇒ budget = 2 ms (2,000,000 ns × 0.1%).
The otel-observability spec's own hot-path target (~200 µs) is reported as
a stricter secondary line.

Run (NOT a CI gate — evidence generation only)::

    source .venv/bin/activate
    python scripts/bench/feat310_emit_overhead.py \
        | tee artifacts/logs/feat-310-bench-$(date +%Y%m%d).txt
"""
import asyncio
import logging
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "packages/ai-parrot/src")

# Keep evidence output clean AND avoid measuring log-handler I/O.
logging.disable(logging.INFO)

from parrot.core.events import EventBus  # noqa: E402

ITERATIONS = 10_000
WARMUP = 500

# FEAT-177 reference: representative LLM completion latency (seconds).
LLM_REFERENCE_LATENCY_S = 2.0
BUDGET_S = LLM_REFERENCE_LATENCY_S * 0.001  # 0.1% ⇒ 2 ms
OTEL_HOTPATH_TARGET_S = 200e-6              # stricter secondary line


async def main() -> int:
    bus = EventBus(queue_size=ITERATIONS + WARMUP + 1024)

    async def slow_handler(event) -> None:
        # Deliberately slow — must NEVER show up in emitter latency.
        await asyncio.sleep(0.05)

    bus.subscribe("bench.*", slow_handler)

    # Warmup (starts BusCore, primes caches).
    for i in range(WARMUP):
        await bus.emit("bench.warmup", {"i": i})

    samples: list[float] = []
    for i in range(ITERATIONS):
        t0 = time.perf_counter()
        await bus.emit("bench.event", {"i": i})
        samples.append(time.perf_counter() - t0)

    samples.sort()
    mean = statistics.fmean(samples)
    p50 = samples[len(samples) // 2]
    p99 = samples[int(len(samples) * 0.99)]
    p999 = samples[int(len(samples) * 0.999)]
    worst = samples[-1]

    def fmt(seconds: float) -> str:
        return f"{seconds * 1e6:10.2f} µs ({seconds * 1e9:12.0f} ns)"

    print("FEAT-310 emit() overhead benchmark")
    print(f"date               : {datetime.now(timezone.utc).isoformat()}")
    print(f"python             : {sys.version.split()[0]}")
    print(f"iterations         : {ITERATIONS} (warmup {WARMUP})")
    print("handler            : async, sleeps 50 ms per event (slow on purpose)")
    print()
    print(f"mean               : {fmt(mean)}")
    print(f"p50                : {fmt(p50)}")
    print(f"p99                : {fmt(p99)}")
    print(f"p99.9              : {fmt(p999)}")
    print(f"max                : {fmt(worst)}")
    print()
    print(f"FEAT-177 budget    : {fmt(BUDGET_S)}  "
          f"(0.1% of {LLM_REFERENCE_LATENCY_S:.1f}s reference LLM call)")
    print(f"otel hot-path line : {fmt(OTEL_HOTPATH_TARGET_S)}  (~200 µs)")
    print()

    ok_budget = p99 < BUDGET_S
    ok_otel = p99 < OTEL_HOTPATH_TARGET_S
    print(f"p99 within FEAT-177 budget (2 ms) : {'PASS' if ok_budget else 'FAIL'}")
    print(f"p99 within otel line (200 µs)     : {'PASS' if ok_otel else 'FAIL'}")

    # Drain without waiting for every 50 ms handler: short deadline.
    await bus.close()
    return 0 if ok_budget else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
