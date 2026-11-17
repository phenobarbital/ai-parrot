"""Import-time prompt-injection scoring of PageIndex segments (FEAT-840)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.segments import InjectionMark, Segment
from parrot.security.prompt_injection import InjectionScoringEngine, PromptInjectionDetector, ThreatLevel

logger = logging.getLogger("parrot.knowledge.pageindex.injection_scan")

_FLAG_WITHOUT_ENGINE = {ThreatLevel.HIGH, ThreatLevel.CRITICAL}


class ScanReport(BaseModel):
    """Outcome of one document scan."""

    scored_by: str
    scanned: int
    suspects: int
    flagged: int


def _regex_pass(detector: PromptInjectionDetector, segments: list[Segment]) -> list[list[dict[str, Any]]]:
    """Threat lists aligned with ``segments`` (runs in a worker thread)."""
    return [detector.detect_threats(seg.text) for seg in segments]


def _flag(seg: Segment, engine_name: str, score: Optional[float], threats: list[dict[str, Any]]) -> None:
    if "injection" not in seg.flags:
        seg.flags.append("injection")
    seg.injection = InjectionMark(
        engine=engine_name, score=score, threats=[str(t.get("description", "")) for t in threats]
    )


def _regex_verdict(found: list[dict[str, Any]]) -> bool:
    return any(t.get("level") in _FLAG_WITHOUT_ENGINE for t in found)


async def scan_segments(
    segments: list[Segment],
    *,
    detector: PromptInjectionDetector,
    engine: Optional[InjectionScoringEngine],
    threshold: float = 0.98,
    concurrency: int = 4,
) -> ScanReport:
    """Flag suspicious segments in place: regex on all, the ML engine only on regex suspects.

    Never raises because of the engine; text is never modified.
    """
    threats = await asyncio.to_thread(_regex_pass, detector, segments)
    suspects = [i for i, found in enumerate(threats) if found]
    flagged = 0
    if engine is None:
        for i in suspects:
            if _regex_verdict(threats[i]):
                _flag(segments[i], "regex", None, threats[i])
                flagged += 1
        return ScanReport(scored_by="regex", scanned=len(segments), suspects=len(suspects), flagged=flagged)

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def score(i: int) -> tuple[int, Optional[float]]:
        async with semaphore:
            try:
                return i, float(await asyncio.to_thread(engine.score, segments[i].text))
            except Exception as exc:  # noqa: BLE001 - scoring must never abort an import
                logger.warning("injection engine failed on segment %s: %s; keeping regex verdict", segments[i].seq, exc)
                return i, None

    for i, probability in await asyncio.gather(*(score(i) for i in suspects)):
        if probability is None:
            if _regex_verdict(threats[i]):
                _flag(segments[i], "regex", None, threats[i])
                flagged += 1
        elif probability >= threshold:
            _flag(segments[i], engine.engine_name, probability, threats[i])
            flagged += 1
    return ScanReport(scored_by=engine.engine_name, scanned=len(segments), suspects=len(suspects), flagged=flagged)
