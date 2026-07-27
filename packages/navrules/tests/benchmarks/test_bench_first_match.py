"""Benchmark: Rust vs pure-Python first-match on a Fieldsync-like workload.

Runs only with RUN_BENCH=1 (kept out of the default test run):

    RUN_BENCH=1 pytest tests/benchmarks -s
"""
import os
import time
from datetime import datetime, timezone

import pytest

from navrules import (
    HAS_RUST,
    ConditionRule,
    EvalContext,
    Environment,
    Policy,
    RuleSet,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_BENCH") != "1", reason="set RUN_BENCH=1 to run"
    ),
    pytest.mark.skipif(not HAS_RUST, reason="native extension not built"),
]

N_RULES = 1000
N_CONTEXTS = 10_000
SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)


def build_ruleset(backend: str) -> RuleSet:
    rules = []
    for i in range(N_RULES):
        rules.append(
            ConditionRule(
                name=f"rule_{i}",
                priority=N_RULES - i,
                conditions={
                    "ctx.job_code": {"in": [f"JOB{i}", f"JOB{i + 1}"]},
                    "ctx.worked_hours": {"between": [i % 12, (i % 12) + 4]},
                    "env.is_weekend": True,
                },
                result={"payrate": 20.0 + i * 0.01, "code": f"R{i}"},
            )
        )
    rs = RuleSet(
        rules,
        policy=Policy.FIRST_MATCH,
        default={"payrate": 15.0, "code": "BASE"},
        backend=backend,
    )
    rs.compile()
    return rs


def build_contexts() -> list[EvalContext]:
    return [
        EvalContext.from_user(
            {"email": f"u{i}@x.co", "job_code": f"JOB{i % (N_RULES + 1)}"},
            worked_hours=(i % 14) + 0.5,
        )
        for i in range(N_CONTEXTS)
    ]


def test_bench_batch_first_match():
    env = Environment(timestamp=SATURDAY)
    contexts = build_contexts()

    rs_py = build_ruleset("python")
    t0 = time.perf_counter()
    py_results = rs_py.evaluate_batch(contexts, env)
    t_py = time.perf_counter() - t0

    rs_rust = build_ruleset("rust")
    t0 = time.perf_counter()
    rust_results = rs_rust.evaluate_batch(contexts, env)
    t_rust = time.perf_counter() - t0

    assert [r.value for r in py_results] == [r.value for r in rust_results]
    speedup = t_py / t_rust if t_rust else float("inf")
    per_ctx_us = (t_rust / N_CONTEXTS) * 1e6
    print(
        f"\n[bench] {N_RULES} rules x {N_CONTEXTS} contexts | "
        f"python={t_py:.3f}s rust={t_rust:.3f}s "
        f"speedup={speedup:.1f}x rust_per_context={per_ctx_us:.1f}us"
    )
    assert speedup > 1.0


def test_bench_single_evaluate_sync_p99():
    env = Environment(timestamp=SATURDAY)
    rs = build_ruleset("rust")
    ctx = EvalContext.from_user(
        {"email": "u@x.co", "job_code": "NOMATCH"}, worked_hours=9.5
    )
    # worst case: no rule matches -> full scan of N_RULES
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        rs.evaluate_sync(ctx, env)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    p99_ms = samples[int(len(samples) * 0.99)] * 1000
    print(f"\n[bench] evaluate_sync p99={p99_ms:.3f}ms over {N_RULES} rules")
    assert p99_ms < 1.0, f"p99 {p99_ms:.3f}ms exceeds 1ms target"
