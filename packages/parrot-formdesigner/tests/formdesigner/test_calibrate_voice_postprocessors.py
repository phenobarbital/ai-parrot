"""FEAT-653 TASK-4255 — calibration harness (offline: fake transcriber + fake refiner)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from parrot_formdesigner.audio.value_refiner import RefinedValue
from parrot_formdesigner.core.voice import VoiceFormConfig

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibrate_voice_postprocessors.py"


def _load():
    spec = importlib.util.spec_from_file_location("calibrate_voice_postprocessors", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # pydantic resolves postponed annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


class _FakeSTT:
    def __init__(self, texts: dict[str, str], confidence: float = 0.9) -> None:
        self.texts, self.confidence = texts, confidence
        self.languages: list[str | None] = []

    async def transcribe(self, audio_path: Path, language: str | None = None):
        self.languages.append(language)
        return SimpleNamespace(
            text=self.texts[audio_path.name],
            confidence=self.confidence,
            language=language or "en",
            duration_seconds=1.0,
        )


class _FakeRefiner:
    def __init__(self, value: str, confidence: float = 0.9) -> None:
        self.value, self.confidence, self.calls = value, confidence, 0

    async def refine(self, **kwargs) -> RefinedValue:
        self.calls += 1
        return RefinedValue(value=self.value, confidence=self.confidence)


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(r) for r in rows))
    return corpus


async def test_calibration_report_shape(tmp_path: Path) -> None:
    mod = _load()
    rows = [
        {"audio": str(tmp_path / "a.wav"), "field_type": "phone", "label": "Phone", "expected": "0412523573"},
        {"audio": str(tmp_path / "b.wav"), "field_type": "email", "label": "Email", "expected": "john@gmail.com"},
        {"audio": str(tmp_path / "c.wav"), "field_type": "number", "label": "N", "expected": 25},
    ]
    stt = _FakeSTT({"a.wav": "0,4,12,523,573", "b.wav": "john at gmail dot com", "c.wav": "twenty five"})
    refiner = _FakeRefiner("john@gmail.com", 0.95)
    report = await mod.run_calibration(mod.load_corpus(_write(tmp_path, rows)), transcriber=stt, refiner=refiner)
    assert report.items == 3 and report.skipped == 0
    assert set(report.groups) == {"phone/en", "email/en", "number/en"}
    assert all(g["rules_accuracy"] == 1.0 and g["accepted_rate"] == 1.0 for g in report.groups.values())
    # the fake LLM answers an email for every item: only the email item yields a usable (accepted) LLM value
    assert refiner.calls == 3 and report.llm_samples == 1
    assert set(report.llm_latency_s) == {"p50", "p95", "p99"}
    assert report.stt_samples == 3 and report.stt_threshold_curve["0.30"] == 0.0
    assert stt.languages == [None, None, None]  # "en" → no language hint, like the WS handler
    md = mod.render_markdown(report, mod.recommend(report))
    for secret in ("0412523573", "john", "twenty", "a.wav", str(tmp_path)):
        assert secret not in md  # aggregates only
    assert "llm_refine_threshold" in md and "stt_confirm_threshold" in md


async def test_language_hint_and_relative_dates(tmp_path: Path) -> None:
    mod = _load()
    when = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc).isoformat()
    rows = [
        {
            "audio": str(tmp_path / "a.wav"),
            "field_type": "date",
            "locale": "es",
            "timezone": "Europe/Madrid",
            "label": "Fecha",
            "expected": "2026-10-13",
            "recorded_at": when,
        },
        {"audio": str(tmp_path / "b.wav"), "field_type": "date", "label": "Date", "expected": "2026-10-13"},  # no clock
        {"audio": str(tmp_path / "missing.wav"), "field_type": "number", "label": "N", "expected": 1},  # STT failure
    ]
    stt = _FakeSTT({"a.wav": "mañana", "b.wav": "tomorrow"})
    report = await mod.run_calibration(mod.load_corpus(_write(tmp_path, rows)), transcriber=stt, refiner=None)
    assert report.items == 1 and report.skipped == 2
    assert report.groups["temporal/es"]["rules_accuracy"] == 1.0
    assert stt.languages[0] == "es"


async def test_max_requests_budget(tmp_path: Path) -> None:
    mod = _load()
    rows = [
        {"audio": str(tmp_path / f"{i}.wav"), "field_type": "number", "label": "N", "expected": 25} for i in range(5)
    ]
    stt = _FakeSTT({f"{i}.wav": "twenty five" for i in range(5)})
    refiner = _FakeRefiner("25", 0.9)
    report = await mod.run_calibration(
        mod.load_corpus(_write(tmp_path, rows)), transcriber=stt, refiner=refiner, max_requests=2
    )
    assert refiner.calls == 2 and report.llm_samples == 2


def test_load_corpus_skips_invalid_lines(tmp_path: Path) -> None:
    mod = _load()
    corpus = tmp_path / "c.jsonl"
    corpus.write_text('not json\n{"audio": "x.wav", "field_type": "email", "label": "E", "expected": "a@b.io"}\n\n')
    assert len(mod.load_corpus(corpus)) == 1


def test_recommend_falls_back_below_min_items() -> None:
    mod = _load()
    report = mod.CalibrationReport(generated_at=datetime.now(timezone.utc), items=3, llm_samples=3, stt_samples=3)
    rec = mod.recommend(report)
    defaults = VoiceFormConfig()
    assert rec["llm_refine_threshold"]["value"] == defaults.llm_refine_threshold
    assert rec["llm_refine_timeout_s"]["value"] == defaults.llm_refine_timeout_s
    assert rec["stt_confirm_threshold"]["value"] == defaults.stt_confirm_threshold
    assert all("spec default" in r["reason"] for r in rec.values())


def test_recommend_applies_decision_rule() -> None:
    mod = _load()
    report = mod.CalibrationReport(
        generated_at=datetime.now(timezone.utc),
        items=100,
        llm_samples=100,
        stt_samples=100,
        llm_threshold_curve={"0.50": 0.10, "0.80": 0.02, "0.85": 0.01, "0.95": 0.0},
        stt_threshold_curve={"0.30": 0.20, "0.55": 0.05, "0.60": 0.03},
        llm_latency_s={"p50": 0.8, "p95": 2.1, "p99": 9.0},
    )
    rec = mod.recommend(report)
    assert rec["llm_refine_threshold"]["value"] == 0.80
    assert rec["llm_refine_timeout_s"]["value"] == 2.5
    assert rec["stt_confirm_threshold"]["value"] == 0.55
    slow = report.model_copy(update={"llm_latency_s": {"p95": 12.0}})
    assert mod.recommend(slow)["llm_refine_timeout_s"]["value"] == 6.0


def test_main_refuses_llm_without_opt_in(monkeypatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.delenv("PARROT_TEST_REAL_LLM", raising=False)
    corpus = _write(tmp_path, [])
    code = mod.main(["--corpus", str(corpus), "--out", str(tmp_path / "out"), "--llm", "google:x"])
    assert code == 1 and not (tmp_path / "out").exists()
