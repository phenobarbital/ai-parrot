"""FEAT-590 spike: measure tiny local tool-calling backends on ai-parrot toolkits.

Standalone harness with no dependency on ``parrot.bots.flows.plan``. It scores
two candidate ``ToolCallDelegate`` backends — a llama.cpp ``llama-server``
(HTTP, ``json_schema``-constrained) and Needle 3 (``cactus-needle``, native,
executed via ``ProcessPoolExecutor`` and ``asyncio.to_thread`` for a latency
comparison) — against a shared set of cases drawn from real ai-parrot tool
schemas (``sdd/state/FEAT-590/spike/cases.jsonl``).

Run with a Python that has ``aiohttp``, ``pydantic`` and (optionally)
``cactus-needle`` installed — see the task's Codebase Contract for why this
must NOT be the shared repo ``.venv`` and NOT ``uv add``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel, Field

logger = logging.getLogger("feat590.spike")


class CaseResult(BaseModel):
    """One case scored against one backend."""

    case_id: str
    backend: str
    exact_match: bool
    abstained: bool
    expected_abstain: bool
    confidence: Optional[float] = None
    latency_ms: float = Field(ge=0.0)
    error: Optional[str] = None


class SpikeReport(BaseModel):
    """Per-backend aggregate metrics."""

    backend: str
    cases: int
    exact_match: float
    abstention_precision: float
    abstention_recall: float
    latency_p50_ms: float
    latency_p95_ms: float


# ---------------------------------------------------------------------------
# llama.cpp backend (HTTP, json_schema oneOf constraint)
# ---------------------------------------------------------------------------


def _namespace_refs(node: Any, prefix: str, hoisted_defs: Dict[str, Any]) -> Any:
    """Rewrite ``$ref: "#/$defs/X"`` -> ``"#/$defs/<prefix>__X"`` recursively, and
    hoist the corresponding ``$defs`` entries (once) into ``hoisted_defs``.

    ``AbstractTool.get_schema()`` parameter schemas carry their OWN top-level
    ``$defs`` (Pydantic's default). Nesting that whole schema several levels
    deep under ``oneOf[i].properties.arguments`` (as a llama.cpp ``json_schema``
    tool-selection grammar requires) leaves the ``$ref`` strings unchanged, but
    they are resolved against the DOCUMENT root — not the nested subschema —
    so an un-rewritten ``#/$defs/X`` 404s once nested. Discovered empirically
    against llama-server b11115: ``cannot resolve $ref #/$defs/X, $defs not
    found`` for every tool with a ``$ref``\ 'd field (e.g. ``entry_type``).
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "$defs" and isinstance(value, dict):
                for def_name, def_schema in value.items():
                    hoisted_defs[f"{prefix}__{def_name}"] = _namespace_refs(def_schema, prefix, hoisted_defs)
                continue
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                out[key] = f"#/$defs/{prefix}__{value[len('#/$defs/'):]}"
                continue
            out[key] = _namespace_refs(value, prefix, hoisted_defs)
        return out
    if isinstance(node, list):
        return [_namespace_refs(item, prefix, hoisted_defs) for item in node]
    return node


def _build_llamacpp_schema(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a oneOf json_schema: one branch per tool's {name,arguments}, plus a decline branch."""
    branches: List[Dict[str, Any]] = []
    hoisted_defs: Dict[str, Any] = {}
    for spec in tools:
        parameters = _namespace_refs(spec.get("parameters", {"type": "object"}), spec["name"], hoisted_defs)
        branches.append(
            {
                "type": "object",
                "properties": {
                    "name": {"const": spec["name"]},
                    "arguments": parameters,
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
        )
    branches.append(
        {
            "type": "object",
            "properties": {"name": {"type": "null"}},
            "required": ["name"],
            "additionalProperties": False,
        }
    )
    schema: Dict[str, Any] = {"oneOf": branches}
    if hoisted_defs:
        schema["$defs"] = hoisted_defs
    return schema


def _system_prompt(tools: List[Dict[str, Any]]) -> str:
    lines = [
        "You are a tool-call proposer. Given an instruction, propose exactly "
        'one call from the tools below, or decline with {"name": null} if '
        "none of them fit. Never invent a tool name or argument key.",
        "Tools:",
    ]
    for spec in tools:
        lines.append(f"- {spec['name']}: {spec.get('description', '')}".strip())
    return "\n".join(lines)


async def probe_llamacpp(session: aiohttp.ClientSession, url: str, case: Dict[str, Any]) -> CaseResult:
    """POST one case to llama-server with a oneOf json_schema; score it."""
    tools = case["tools"]
    schema = _build_llamacpp_schema(tools)
    payload = {
        "messages": [
            {"role": "system", "content": _system_prompt(tools)},
            {"role": "user", "content": case["instruction"]},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "tool_call", "schema": schema, "strict": True},
        },
        "temperature": 0.0,
        "n_predict": 256,
        "logprobs": True,
        "top_logprobs": 1,
    }
    start = time.monotonic()
    try:
        async with session.post(
            f"{url}/v1/chat/completions", json=payload, timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            body = await resp.json()
    except Exception as exc:  # noqa: BLE001 - backend failure is scored, not raised
        latency_ms = (time.monotonic() - start) * 1000.0
        return CaseResult(
            case_id=case["id"],
            backend="llamacpp",
            exact_match=False,
            abstained=False,
            expected_abstain=case["expected"] is None,
            confidence=None,
            latency_ms=latency_ms,
            error=str(exc),
        )
    latency_ms = (time.monotonic() - start) * 1000.0

    confidence: Optional[float] = None
    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
        parsed = json.loads(content)
        logprobs_obj = choice.get("logprobs")
        if logprobs_obj and logprobs_obj.get("content"):
            token_logprobs = [t["logprob"] for t in logprobs_obj["content"] if "logprob" in t]
            if token_logprobs:
                import math

                avg_logprob = sum(token_logprobs) / len(token_logprobs)
                confidence = math.exp(avg_logprob)
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000.0
        return CaseResult(
            case_id=case["id"],
            backend="llamacpp",
            exact_match=False,
            abstained=False,
            expected_abstain=case["expected"] is None,
            confidence=None,
            latency_ms=latency_ms,
            error=f"unparseable response: {exc}",
        )

    proposed_name = parsed.get("name")
    abstained = proposed_name is None
    expected = case["expected"]
    if expected is None:
        exact_match = abstained
    else:
        exact_match = (
            (not abstained) and proposed_name == expected["name"] and parsed.get("arguments") == expected["arguments"]
        )

    return CaseResult(
        case_id=case["id"],
        backend="llamacpp",
        exact_match=exact_match,
        abstained=abstained,
        expected_abstain=expected is None,
        confidence=confidence,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Needle backend (native, executed via to_thread AND ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _make_needle_tool(spec: Dict[str, Any]):
    """Build a dummy Python callable carrying a real ai-parrot ToolSpec as its
    ``_needle_tool`` attribute, so Needle sees the EXACT schema our real
    tools expose via ``AbstractTool.get_schema()`` rather than needle's own
    signature-derived one."""

    def _fn(**kwargs):  # pragma: no cover - never actually invoked
        raise NotImplementedError

    _fn.__name__ = spec["name"]
    _fn._needle_tool = {
        "name": spec["name"],
        "description": spec.get("description", ""),
        "parameters": spec.get("parameters", {"type": "object"}),
    }
    return _fn


def _score_needle_response(case: Dict[str, Any], response: Dict[str, Any], latency_ms: float) -> CaseResult:
    calls = response.get("function_calls") or []
    abstained = len(calls) == 0
    confidence = response.get("confidence")
    expected = case["expected"]
    if expected is None:
        exact_match = abstained
    else:
        exact_match = (
            not abstained
            and calls[0].get("name") == expected["name"]
            and calls[0].get("arguments") == expected["arguments"]
        )
    return CaseResult(
        case_id=case["id"],
        backend="needle",
        exact_match=exact_match,
        abstained=abstained,
        expected_abstain=expected is None,
        confidence=confidence,
        latency_ms=latency_ms,
    )


def _run_needle_case_blocking(case: Dict[str, Any], weights: Optional[str]) -> CaseResult:
    """Build a fresh Needle agent for this case's tool pool and complete() it. Blocking."""
    import needle  # imported lazily; not installed in the shared repo .venv

    tools = [_make_needle_tool(spec) for spec in case["tools"]]
    start = time.monotonic()
    try:
        agent = needle.Needle(tools=tools, weights=weights)
        response = agent.complete(case["instruction"])
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000.0
        return CaseResult(
            case_id=case["id"],
            backend="needle",
            exact_match=False,
            abstained=False,
            expected_abstain=case["expected"] is None,
            confidence=None,
            latency_ms=latency_ms,
            error=str(exc),
        )
    latency_ms = (time.monotonic() - start) * 1000.0
    return _score_needle_response(case, response, latency_ms)


def _needle_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level, picklable ProcessPoolExecutor worker. Returns a CaseResult dump."""
    case = payload["case"]
    weights = payload.get("weights")
    result = _run_needle_case_blocking(case, weights)
    return result.model_dump(mode="json")


async def probe_needle(case: Dict[str, Any], *, weights: Optional[str] = None) -> CaseResult:
    """Run one case through needle.Needle(...).complete() via asyncio.to_thread; blocking."""
    return await asyncio.to_thread(_run_needle_case_blocking, case, weights)


async def probe_needle_via_process_pool(
    executor: ProcessPoolExecutor, case: Dict[str, Any], *, weights: Optional[str] = None
) -> CaseResult:
    """Run one case through Needle inside a persistent ProcessPoolExecutor worker."""
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(executor, _needle_worker, {"case": case, "weights": weights})
    return CaseResult.model_validate(raw)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def summarize(results: List[CaseResult], backend: str) -> SpikeReport:
    """Aggregate CaseResults for one backend."""
    if not results:
        return SpikeReport(
            backend=backend,
            cases=0,
            exact_match=0.0,
            abstention_precision=0.0,
            abstention_recall=0.0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
        )
    n = len(results)
    exact = sum(1 for r in results if r.exact_match) / n

    expected_abstain = [r for r in results if r.expected_abstain]
    predicted_abstain = [r for r in results if r.abstained]
    true_positive_abstain = sum(1 for r in results if r.abstained and r.expected_abstain)
    abstention_precision = (true_positive_abstain / len(predicted_abstain)) if predicted_abstain else 0.0
    abstention_recall = (true_positive_abstain / len(expected_abstain)) if expected_abstain else 0.0

    latencies = sorted(r.latency_ms for r in results)
    p50 = statistics.median(latencies)
    p95_idx = max(0, min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1)))))
    p95 = latencies[p95_idx]

    return SpikeReport(
        backend=backend,
        cases=n,
        exact_match=exact,
        abstention_precision=abstention_precision,
        abstention_recall=abstention_recall,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
    )


async def run_spike(
    cases_path: Path,
    *,
    needle: bool,
    llamacpp_url: Optional[str],
    needle_weights: Optional[str] = None,
    process_pool_timeout_s: float = 60.0,
    skip_process_pool: bool = False,
) -> List[SpikeReport]:
    """Run every case against each enabled backend; return per-backend metrics."""
    raw_text = await asyncio.to_thread(cases_path.read_text)
    cases = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    logger.info("loaded %d cases", len(cases))
    reports: List[SpikeReport] = []

    if llamacpp_url:
        async with aiohttp.ClientSession() as session:
            results = [await probe_llamacpp(session, llamacpp_url, case) for case in cases]
        reports.append(summarize(results, "llamacpp"))
        errors = [r for r in results if r.error]
        if errors:
            logger.warning("llamacpp: %d/%d cases errored, e.g. %s", len(errors), len(results), errors[0].error)

    if needle:
        # (a) asyncio.to_thread — one fresh Needle agent per case, run sequentially
        #     through the default thread-pool executor.
        thread_results: List[CaseResult] = []
        for case in cases:
            thread_results.append(await probe_needle(case, weights=needle_weights))
        reports.append(summarize(thread_results, "needle_to_thread"))
        errors = [r for r in thread_results if r.error]
        if errors:
            logger.warning(
                "needle_to_thread: %d/%d cases errored, e.g. %s", len(errors), len(thread_results), errors[0].error
            )

        # (b) ProcessPoolExecutor — persistent worker pool; each worker pays the
        #     native-library + base-weight load cost once, then reuses it.
        #     Bounded by a hard timeout: a fork()-based pool can deadlock when
        #     the native ctypes library was already loaded in the parent (or,
        #     as observed in the sandboxed spike environment, even cold) — a
        #     hang here must not block the whole spike. See decision.md.
        if skip_process_pool:
            logger.warning("needle_process_pool: SKIPPED by --needle-skip-process-pool (see decision.md)")
            reports.append(summarize([], "needle_process_pool"))
        else:
            try:
                with ProcessPoolExecutor(max_workers=4) as executor:
                    pool_results = await asyncio.wait_for(
                        asyncio.gather(
                            *[probe_needle_via_process_pool(executor, case, weights=needle_weights) for case in cases]
                        ),
                        timeout=process_pool_timeout_s,
                    )
                reports.append(summarize(list(pool_results), "needle_process_pool"))
                errors = [r for r in pool_results if r.error]
                if errors:
                    logger.warning(
                        "needle_process_pool: %d/%d cases errored, e.g. %s",
                        len(errors),
                        len(pool_results),
                        errors[0].error,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "needle_process_pool: TIMED OUT after %ss with no result — recorded as unusable in this "
                    "environment (see decision.md); reporting zero-case metrics",
                    process_pool_timeout_s,
                )
                reports.append(summarize([], "needle_process_pool"))

    return reports


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("sdd/state/FEAT-590/spike/cases.jsonl"))
    parser.add_argument("--needle", action="store_true")
    parser.add_argument("--needle-weights", default=None)
    parser.add_argument("--llamacpp-url", default=None)
    parser.add_argument(
        "--needle-skip-process-pool",
        action="store_true",
        help="Skip the ProcessPoolExecutor comparison (observed to hang in the sandboxed spike environment).",
    )
    parser.add_argument("--out", type=Path, default=None, help="Optional path to dump per-backend metrics as JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    reports = asyncio.run(
        run_spike(
            args.cases,
            needle=args.needle,
            llamacpp_url=args.llamacpp_url,
            needle_weights=args.needle_weights,
            skip_process_pool=args.needle_skip_process_pool,
        )
    )
    dumped = []
    for report in reports:
        logger.info("%s", report.model_dump_json())
        dumped.append(report.model_dump(mode="json"))
    if args.out:
        args.out.write_text(json.dumps(dumped, indent=2))


if __name__ == "__main__":
    main()
