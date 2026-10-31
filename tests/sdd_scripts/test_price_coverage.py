"""FEAT-783 AC-6 — price coverage script."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.price_coverage import coverage, main


def _write_rows(directory: Path) -> None:
    """Write a frozen fixture: two priced attempts, one unpriced attempt, one outcome row."""
    rows = [
        {"kind": "attempt", "backend": "anthropic", "configured_model": "claude-3-5-sonnet", "resolved_model": ""},
        {"kind": "attempt", "backend": "openai", "configured_model": "gpt-5.5", "resolved_model": "gpt-5.5"},
        {"kind": "attempt", "backend": "openai", "configured_model": "no-such-model", "resolved_model": ""},
        {"kind": "outcome", "backend": "openai", "configured_model": "gpt-5.5", "resolved_model": ""},
    ]
    (directory / "FEAT-0.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_coverage_counts_priced_and_unpriced(tmp_path: Path) -> None:
    """Only attempt rows count; the unknown pair is reported with its row count."""
    _write_rows(tmp_path)
    report = coverage(tmp_path)
    assert report["rows"] == 3
    assert report["priced"] == 2
    assert report["ratio"] == 2 / 3
    assert report["unpriced"] == {("openai", "no-such-model"): 1}


def test_coverage_skips_blank_model_and_malformed_lines(tmp_path: Path) -> None:
    """Rows without a model and unparsable lines never inflate the denominator."""
    (tmp_path / "x.jsonl").write_text(
        "not json\n" + json.dumps({"kind": "attempt", "backend": "openai", "configured_model": ""}) + "\n",
        encoding="utf-8",
    )
    assert coverage(tmp_path) == {"rows": 0, "priced": 0, "ratio": 0.0, "unpriced": {}}


def test_main_exit_code_follows_threshold(tmp_path: Path, capsys) -> None:
    """Exit 0 at or above the threshold, 1 below it; stdout is valid JSON."""
    _write_rows(tmp_path)
    assert main(["--rows-dir", str(tmp_path), "--threshold", "0.6"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 3
    assert main(["--rows-dir", str(tmp_path), "--threshold", "0.9"]) == 1
