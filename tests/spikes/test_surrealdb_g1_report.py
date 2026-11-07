"""Shape of the committed G1 spike report (FEAT-824)."""

from __future__ import annotations

import re
from pathlib import Path

REPORT = Path(__file__).resolve().parents[2] / "sdd" / "state" / "FEAT-824" / "g1" / "report.md"
ROW = re.compile(r"^\| (G1-\d{2}) \| .+? \| (Yes|No) \| (pass|fail|skipped) \|", re.MULTILINE)


def test_report_pins_image_digest_and_sdk() -> None:
    """The report records the server image by digest and the SDK version."""
    text = REPORT.read_text(encoding="utf-8")
    assert re.search(r"\*\*Server Image\*\*: `[^`]+@sha256:[0-9a-f]{64}`", text)
    assert re.search(r"\*\*SDK Version\*\*: `\d+\.\d+\.\d+`", text)


def test_report_has_every_check_once() -> None:
    """All thirteen checks G1-01..G1-13 appear exactly once."""
    ids = [match.group(1) for match in ROW.finditer(REPORT.read_text(encoding="utf-8"))]
    assert ids == [f"G1-{number:02d}" for number in range(1, 14)]


def test_report_verdict_is_consistent_with_blocking_checks() -> None:
    """GO if and only if every blocking check passed."""
    text = REPORT.read_text(encoding="utf-8")
    blocking_ok = all(status == "pass" for _, blocking, status in ROW.findall(text) if blocking == "Yes")
    verdict = re.findall(r"\*\*Verdict: (GO|NO-GO)\*\*\s*$", text)
    assert verdict and verdict[-1] == ("GO" if blocking_ok else "NO-GO")
