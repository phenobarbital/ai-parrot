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
    assert coverage(tmp_path) == {"rows": 0, "priced": 0, "ratio": 0.0, "unpriced": {}, "excluded": {}}


def test_coverage_excludes_named_models_and_reports_them(tmp_path: Path) -> None:
    """Excluded models leave the denominator but stay visible in the report."""
    _write_rows(tmp_path)
    report = coverage(tmp_path, exclude_models=["no-such-model"])
    assert (report["rows"], report["priced"], report["ratio"]) == (2, 2, 1.0)
    assert report["unpriced"] == {}
    assert report["excluded"] == {"no-such-model": 1}


def test_main_exit_code_follows_threshold(tmp_path: Path, capsys) -> None:
    """Exit 0 at or above the threshold, 1 below it; stdout is valid JSON."""
    _write_rows(tmp_path)
    assert main(["--rows-dir", str(tmp_path), "--threshold", "0.6"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 3
    assert main(["--rows-dir", str(tmp_path), "--threshold", "0.9"]) == 1


def test_bundled_tables_price_the_published_roster_models() -> None:
    """Every roster model with a published price resolves; unpublished ones stay unpriced (never guessed)."""
    from parrot.observability.cost.calculator import CostCalculator

    calc = CostCalculator()
    priced = [
        ("openai", "gpt-5.6-sol"),
        ("openai", "gpt-5.6-terra"),
        ("openai", "gpt-5.6-luna"),
        ("gemini", "gemini-3.8-flash"),
        ("aws.bedrock", "zai.glm-4.7-flash"),
        ("aws.bedrock", "minimax.minimax-m2.5"),
        ("aws.bedrock", "mistral.devstral-2-123b"),
        ("aws.bedrock", "qwen.qwen3-coder-480b-a35b-instruct"),
        ("anthropic", "claude-fable-5-1"),
        ("anthropic", "claude-opus-5-5"),
        ("anthropic", "claude-sonnet-5-5"),
        ("anthropic", "claude-haiku-5-5"),
    ]
    for provider, model in priced:
        assert calc.cost_usd(provider=provider, model=model, input_tokens=1000, output_tokens=1000) is not None, model
    assert calc.cost_usd(provider="openai", model="gpt-5.3-codex-spark", input_tokens=1, output_tokens=1) is None


def test_anthropic_models_carry_a_cache_creation_tier() -> None:
    """AC-6: every Anthropic entry has `cache_creation_per_1m`, and it is the 1.25x write premium."""
    import json

    from parrot.observability.cost.calculator import _BUNDLED_DIR

    models = json.loads((_BUNDLED_DIR / "anthropic.json").read_text(encoding="utf-8"))["models"]
    assert models
    for name, entry in models.items():
        assert entry["cache_creation_per_1m"] == round(entry["input_per_1m"] * 1.25, 6), name
