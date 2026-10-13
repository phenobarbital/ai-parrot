"""Calibrate FEAT-653 voice post-processor thresholds on real field recordings.

Usage (TASK-4256):

    PARROT_TEST_REAL_LLM=1 python packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py \
        --corpus /secure/path/corpus.jsonl --out sdd/state/FEAT-653/calibration --llm google:gemini-2.5-flash \
        --max-requests 400

The corpus is a JSONL manifest (never committed; user data). Each line is
``{"audio": "<path>", "field_type": "email", "locale": "en", "timezone": "America/New_York", "label": "Email",
"expected": "john@gmail.com", "recorded_at": "2026-10-01T14:03:00-04:00"}``. ``recorded_at`` is optional and is the
clock for relative dates; without it DATE / DATETIME items are skipped and counted.

The report holds aggregates only (never transcripts, values, audio paths or user ids).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import REFINABLE_TYPES, NormalizeContext, normalize_spoken
from parrot_formdesigner.audio.value_refiner import LLMValueRefiner, ValueRefiner
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig

logger = logging.getLogger("calibrate_voice_postprocessors")

MIN_ITEMS = 30
LLM_FALSE_ACCEPT_MAX = 0.02
STT_FALSE_ACCEPT_MAX = 0.05
TIMEOUT_CAP_S = 6.0
LLM_THRESHOLDS = [round(0.50 + 0.05 * i, 2) for i in range(10)]  # 0.50 .. 0.95
STT_THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(13)]  # 0.30 .. 0.90
_TEMPORAL = {FieldType.DATE, FieldType.TIME, FieldType.DATETIME}
_RELATIVE_TYPES = {FieldType.DATE, FieldType.DATETIME}


class CorpusItem(BaseModel):
    """One labelled recording."""

    audio: Path
    field_type: FieldType
    locale: str = "en"
    timezone: str | None = None
    label: str
    expected: Any
    recorded_at: datetime | None = None


class ItemOutcome(BaseModel):
    """Per-item measurement (kept in memory only; never written to the report)."""

    family: str
    locale: str
    stt_confidence: float | None = None
    rules_status: str
    rules_correct: bool
    llm_value_correct: bool | None = None  # None: no usable (accepted) LLM value
    llm_confidence: float | None = None
    llm_latency_s: float | None = None


class CalibrationReport(BaseModel):
    """Aggregates per (family, locale) + global curves; JSON-serialisable, no personal data."""

    generated_at: datetime
    items: int
    skipped: int = 0
    groups: dict[str, dict[str, Any]] = Field(default_factory=dict)
    llm_threshold_curve: dict[str, float] = Field(default_factory=dict)  # "0.80" -> false-accept rate
    stt_threshold_curve: dict[str, float] = Field(default_factory=dict)
    llm_latency_s: dict[str, float] = Field(default_factory=dict)  # p50/p95/p99
    llm_samples: int = 0
    stt_samples: int = 0


def _family(field_type: FieldType) -> str:
    if field_type in (FieldType.NUMBER, FieldType.INTEGER):
        return "number"
    if field_type in _TEMPORAL:
        return "temporal"
    return field_type.value


def _same(actual: Any, expected: Any) -> bool:
    """Value equality tolerant of int/float and surrounding whitespace."""
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and not isinstance(actual, bool):
        return float(actual) == float(expected)
    return str(actual).strip() == str(expected).strip()


def load_corpus(path: Path) -> list[CorpusItem]:
    """Read a JSONL corpus; invalid lines are logged with their line number only and skipped."""
    items: list[CorpusItem] = []
    with path.open(encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                items.append(CorpusItem.model_validate_json(line))
            except ValueError:
                logger.warning("corpus line %d is invalid and was skipped", number)
    return items


def _context(item: CorpusItem) -> NormalizeContext:
    """Normalization context with the clock fixed at the recording date."""
    now = item.recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    known = False
    if item.timezone:
        try:
            now = now.astimezone(ZoneInfo(item.timezone))
            known = True
        except Exception:  # noqa: BLE001 — unknown zone: UTC, relative dates need confirmation
            now = now.astimezone(timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return NormalizeContext(lexicon=load_lexicon(item.locale), now=now, timezone_known=known)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


async def _measure(
    item: CorpusItem,
    transcriber: Any,
    refiner: ValueRefiner | None,
    budget: list[int | None],
) -> ItemOutcome | None:
    """Steps 1-4 of the per-item measurement; ``budget`` is a one-element list holding the remaining LLM calls."""
    language = None if item.locale == "en" else item.locale  # mirrors AudioFormWSHandler._do_transcribe
    transcript = await transcriber.transcribe(item.audio, language=language)
    text = getattr(transcript, "text", "") or ""
    ctx = _context(item)
    rules = normalize_spoken(item.field_type, text, ctx=ctx)
    outcome = ItemOutcome(
        family=_family(item.field_type),
        locale=item.locale,
        stt_confidence=getattr(transcript, "confidence", None),
        rules_status=rules.status if rules is not None else "accepted",
        rules_correct=_same(rules.value if rules is not None else text, item.expected),
    )
    remaining = budget[0]
    if refiner is None or item.field_type not in REFINABLE_TYPES or (remaining is not None and remaining <= 0):
        return outcome
    if remaining is not None:
        budget[0] = remaining - 1
    started = time.perf_counter()
    refined = await refiner.refine(
        transcript=text,
        candidate=rules.value if rules is not None else None,
        field_type=item.field_type,
        label=item.label,
        locale=item.locale,
        today=ctx.now.date().isoformat(),
        timezone=item.timezone,
    )
    outcome.llm_latency_s = time.perf_counter() - started
    if refined is not None and refined.value is not None:
        renorm = normalize_spoken(item.field_type, refined.value, ctx=ctx)
        outcome.llm_confidence = refined.confidence
        if renorm is not None and renorm.status == "accepted":
            outcome.llm_value_correct = _same(renorm.value, item.expected)
    return outcome


def _aggregate(outcomes: list[ItemOutcome], skipped: int) -> CalibrationReport:
    groups: dict[str, dict[str, Any]] = {}
    for key in sorted({f"{o.family}/{o.locale}" for o in outcomes}):
        rows = [o for o in outcomes if f"{o.family}/{o.locale}" == key]
        n = len(rows)
        accepted = [o for o in rows if o.rules_status == "accepted"]
        groups[key] = {
            "n": n,
            "rules_accuracy": sum(o.rules_correct for o in rows) / n,
            "accepted_rate": len(accepted) / n,
            "confirm_rate": sum(o.rules_status == "confirm" for o in rows) / n,
            "rejected_rate": sum(o.rules_status == "rejected" for o in rows) / n,
            "rules_false_accept_rate": (
                (sum(not o.rules_correct for o in accepted) / len(accepted)) if accepted else 0.0
            ),
            "llm_n": sum(o.llm_latency_s is not None for o in rows),
        }
    llm_rows = [o for o in outcomes if o.llm_value_correct is not None and o.llm_confidence is not None]
    llm_curve: dict[str, float] = {}
    for t in LLM_THRESHOLDS:
        auto = [o for o in llm_rows if (o.llm_confidence or 0.0) >= t]
        if auto:
            llm_curve[f"{t:.2f}"] = sum(not o.llm_value_correct for o in auto) / len(auto)
    stt_rows = [o for o in outcomes if o.stt_confidence is not None and o.rules_status == "accepted"]
    stt_curve: dict[str, float] = {}
    for t in STT_THRESHOLDS:
        auto = [o for o in stt_rows if (o.stt_confidence or 0.0) >= t]
        if auto:
            stt_curve[f"{t:.2f}"] = sum(not o.rules_correct for o in auto) / len(auto)
    latencies = [o.llm_latency_s for o in outcomes if o.llm_latency_s is not None]
    latency = (
        {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95), "p99": _percentile(latencies, 99)}
        if latencies
        else {}
    )
    return CalibrationReport(
        generated_at=datetime.now(timezone.utc),
        items=len(outcomes),
        skipped=skipped,
        groups=groups,
        llm_threshold_curve=llm_curve,
        stt_threshold_curve=stt_curve,
        llm_latency_s=latency,
        llm_samples=len(llm_rows),
        stt_samples=len(stt_rows),
    )


async def run_calibration(
    items: list[CorpusItem],
    *,
    transcriber: Any,
    refiner: ValueRefiner | None,
    max_requests: int | None = None,
) -> CalibrationReport:
    """Measure every item (see module docstring); returns aggregates only."""
    outcomes: list[ItemOutcome] = []
    skipped = 0
    budget: list[int | None] = [max_requests]
    for item in items:
        if item.field_type in _RELATIVE_TYPES and item.recorded_at is None:
            skipped += 1
            continue
        try:
            outcome = await _measure(item, transcriber, refiner, budget)
        except Exception as exc:  # noqa: BLE001 — one bad recording never aborts the run
            logger.warning("item skipped after %s", type(exc).__name__)
            skipped += 1
            continue
        if outcome is not None:
            outcomes.append(outcome)
    return _aggregate(outcomes, skipped)


def recommend(report: CalibrationReport) -> dict[str, Any]:
    """Apply the decision rule; returns the three defaults (or the spec defaults with a reason)."""
    defaults = VoiceFormConfig()

    def fallback(value: float, why: str) -> dict[str, Any]:
        return {"value": value, "reason": f"{why}; keeping the spec default"}

    out: dict[str, Any] = {}

    if report.llm_samples < MIN_ITEMS:
        out["llm_refine_threshold"] = fallback(
            defaults.llm_refine_threshold, f"only {report.llm_samples} LLM samples (< {MIN_ITEMS})"
        )
    else:
        ok = [float(k) for k, rate in sorted(report.llm_threshold_curve.items()) if rate <= LLM_FALSE_ACCEPT_MAX]
        out["llm_refine_threshold"] = (
            {"value": min(ok), "reason": f"lowest threshold with LLM false-accept <= {LLM_FALSE_ACCEPT_MAX:.0%}"}
            if ok
            else fallback(defaults.llm_refine_threshold, "no threshold reached the LLM false-accept target")
        )

    p95 = report.llm_latency_s.get("p95")
    if report.llm_samples < MIN_ITEMS or p95 is None:
        out["llm_refine_timeout_s"] = fallback(
            defaults.llm_refine_timeout_s, f"only {report.llm_samples} latency samples (< {MIN_ITEMS})"
        )
    else:
        out["llm_refine_timeout_s"] = {
            "value": min(TIMEOUT_CAP_S, max(0.5, math.ceil(p95 * 2) / 2)),
            "reason": f"p95 latency rounded up to 0.5 s, capped at {TIMEOUT_CAP_S:g} s",
        }

    if report.stt_samples < MIN_ITEMS:
        out["stt_confirm_threshold"] = fallback(
            defaults.stt_confirm_threshold, f"only {report.stt_samples} STT samples (< {MIN_ITEMS})"
        )
    else:
        ok = [float(k) for k, rate in sorted(report.stt_threshold_curve.items()) if rate <= STT_FALSE_ACCEPT_MAX]
        out["stt_confirm_threshold"] = (
            {"value": min(ok), "reason": f"lowest threshold with free-form false-accept <= {STT_FALSE_ACCEPT_MAX:.0%}"}
            if ok
            else fallback(defaults.stt_confirm_threshold, "no threshold reached the STT false-accept target")
        )
    return out


def render_markdown(report: CalibrationReport, recommendation: dict[str, Any]) -> str:
    """Human report: per-group table, curves, latency, the recommendation and its reasons (aggregates only)."""
    lines = [
        "# FEAT-653 voice post-processor calibration",
        "",
        f"Generated: {report.generated_at.isoformat()}  ",
        f"Items measured: {report.items} (skipped: {report.skipped})",
        "",
        "## Rules post-processor, per type family and locale",
        "",
        "| group | n | accuracy | accepted | confirm | rejected | false-accept | LLM items |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, g in report.groups.items():
        lines.append(
            f"| {key} | {g['n']} | {g['rules_accuracy']:.1%} | {g['accepted_rate']:.1%} | {g['confirm_rate']:.1%} "
            f"| {g['rejected_rate']:.1%} | {g['rules_false_accept_rate']:.1%} | {g['llm_n']} |"
        )
    lines += ["", f"## LLM false-accept rate by confidence threshold ({report.llm_samples} samples)", ""]
    lines += ["| threshold | false-accept |", "|---|---|"]
    lines += [f"| {k} | {v:.1%} |" for k, v in report.llm_threshold_curve.items()]
    lines += ["", "## LLM latency (seconds)", ""]
    lines += [f"- {k}: {v:.2f}" for k, v in report.llm_latency_s.items()] or ["- no LLM samples"]
    lines += ["", f"## STT false-accept rate by confidence threshold ({report.stt_samples} samples)", ""]
    lines += ["| threshold | false-accept |", "|---|---|"]
    lines += [f"| {k} | {v:.1%} |" for k, v in report.stt_threshold_curve.items()]
    lines += ["", "## Recommendation", "", "| setting | value | reason |", "|---|---|---|"]
    lines += [f"| `{name}` | {rec['value']} | {rec['reason']} |" for name, rec in recommendation.items()]
    lines += [
        "",
        "Decision rule: `llm_refine_threshold` = lowest value with LLM false-accept <= 2 %; `llm_refine_timeout_s` = "
        "p95 latency rounded up to 0.5 s (cap 6 s); `stt_confirm_threshold` = lowest value with free-form "
        "false-accept <= 5 %. A metric with fewer than 30 samples keeps the spec default.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: --corpus, --out, --llm (provider:model, optional), --max-requests, --stt-model, --device."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--llm", default=None, help="provider:model, e.g. google:gemini-2.5-flash")
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--stt-model", default="small")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.llm and os.environ.get("PARROT_TEST_REAL_LLM") != "1":
        logger.error("--llm makes real LLM calls: set PARROT_TEST_REAL_LLM=1 to allow them")
        return 1
    if not args.corpus.is_file():
        logger.error("corpus file not found")
        return 1

    async def _run() -> CalibrationReport:
        from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend  # lazy: heavy

        refiner: ValueRefiner | None = None
        if args.llm:
            from parrot.clients.factory import LLMFactory  # lazy: heavy

            refiner = LLMValueRefiner(LLMFactory.create(args.llm))
        transcriber = FasterWhisperBackend(model_size=args.stt_model, device=args.device)
        try:
            return await run_calibration(
                load_corpus(args.corpus), transcriber=transcriber, refiner=refiner, max_requests=args.max_requests
            )
        finally:
            await transcriber.close()

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — surface a clean exit code to the operator
        logger.error("calibration failed: %s", type(exc).__name__)
        return 1
    recommendation = recommend(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps({"report": json.loads(report.model_dump_json()), "recommendation": recommendation}, indent=2),
        encoding="utf-8",
    )
    (args.out / "report.md").write_text(render_markdown(report, recommendation), encoding="utf-8")
    logger.info("report written to %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
