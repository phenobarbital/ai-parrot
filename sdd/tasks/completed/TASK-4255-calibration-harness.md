# TASK-4255: Calibration harness for the voice post-processors

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4246, TASK-4247, TASK-4249
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (first half), owner decision §8 Q4: the defaults of `llm_refine_threshold`,
`llm_refine_timeout_s` and `stt_confirm_threshold` must come from a measurement on real field
recordings, not a guess (G9, AC16).

This task builds the re-runnable harness and its offline tests. The actual run on the real corpus
and the default updates are TASK-4256. The harness must be re-runnable because the out-of-scope
STT spec will change the meaning of the STT confidence, and the run will be repeated then.

---

## Scope

- Create `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py` with:
  - `CorpusItem`, `CalibrationReport`;
  - `load_corpus`, `run_calibration`, `recommend`;
  - `render_markdown`, `main`.
- Write `test_calibrate_voice_postprocessors.py`. It loads the script by file path and runs a
  3-item corpus with a fake transcriber and a fake refiner; it never needs real audio or a real
  LLM.

**NOT in scope**: running against the real corpus; changing defaults (TASK-4256); committing any
corpus data.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py` | CREATE | Harness + CLI |
| `packages/parrot-formdesigner/tests/formdesigner/test_calibrate_voice_postprocessors.py` | CREATE | Offline tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.narration.lexicon import load_lexicon                  # lexicon.py:96
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken, REFINABLE_TYPES   # TASK-4245
from parrot_formdesigner.audio.value_refiner import LLMValueRefiner, ValueRefiner, RefinedValue      # TASK-4249
from parrot_formdesigner.core.types import FieldType                                  # core/types.py:16
from parrot_formdesigner.core.voice import VoiceFormConfig                            # core/voice.py:50 (spec defaults for the fallback)
from parrot.voice.transcriber.backend import AbstractTranscriberBackend               # ai-parrot-integrations .../transcriber/backend.py:18
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend      # .../faster_whisper_backend.py:21 (CLI only, lazy import)
from parrot.clients.factory import LLMFactory                                         # packages/ai-parrot/src/parrot/clients/factory.py:163 (CLI only, lazy import)
```

### Existing Signatures to Use
```python
# AbstractTranscriberBackend.transcribe(self, audio_path: Path, language: Optional[str] = None) -> TranscriptionResult
#   result has .text, .language, .confidence (FasterWhisper: info.language_probability), .duration_seconds   # backend.py:39-60
# FasterWhisperBackend(model_size="small", device="cuda", compute_type="float16")   # faster_whisper_backend.py:47-52
# LLMFactory.create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient   # factory.py:257 ("provider:model")
# The WS handler passes language=None for "en" and the locale otherwise (api/audio_ws.py:987) — mirror it exactly
# normalize_spoken(field_type, text, *, ctx) -> NormalizeResult | None (status accepted|confirm|rejected)
# LLMValueRefiner(client).refine(*, transcript, candidate, field_type, label, locale, today, timezone) -> RefinedValue | None
```

### Does NOT Exist
- ~~A committed calibration corpus~~ — user data, passed with `--corpus`, never committed.
- ~~`packages/parrot-formdesigner/scripts/__init__.py`~~ — scripts are not a package; tests load the file with `importlib.util.spec_from_file_location`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_calibrate_voice_postprocessors.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Corpus (JSONL, one item per line)
`{"audio": "<path>", "field_type": "email", "locale": "en", "timezone": "America/New_York",
"label": "Email", "expected": "john@gmail.com", "recorded_at": "2026-10-01T14:03:00-04:00"}`.
`recorded_at` is optional and is the clock for relative dates. Without it, items whose expected
value depends on "today" are skipped and counted.

### Per item
1. Transcribe, passing the language exactly as the WS handler does, and record the STT confidence.
2. Run the rules (`normalize_spoken`) with the clock fixed at `recorded_at`.
3. If a refiner is present and the type is in `REFINABLE_TYPES`, call it untimed and record
   latency, then re-normalize its value.
4. Compare with `expected`.

### Metrics, per (type family, locale)
- n
- rules: exact-match accuracy, accepted / confirm / rejected rates, false-accept rate (accepted
  but wrong)
- LLM, for each threshold in 0.50..0.95 step 0.05: false-accept rate among auto-accepted values
- LLM latency: p50 / p95 / p99
- STT, for each threshold in 0.30..0.90 step 0.05: false-accept rate (STT confidence ≥ t but the
  rules value is wrong)

### `recommend` (decision rule, spec §3 M11)
- `llm_refine_threshold`: the lowest t with LLM false-accept ≤ 2 %.
- `llm_refine_timeout_s`: p95 latency rounded up to 0.5 s, capped at 6 s.
- `stt_confirm_threshold`: the lowest t with free-form false-accept ≤ 5 %.

With fewer than 30 items in total for a metric, keep the spec default (from `VoiceFormConfig()`)
and record the reason.

### Privacy
The report (markdown + JSON) holds aggregates only: no transcripts, values, audio paths or user
ids. Real LLM calls need `PARROT_TEST_REAL_LLM=1` and stop at `--max-requests`.

---

## Implementation Blueprint

### Steps (in order)
1. Models + `load_corpus` — *why*: validated input before anything expensive runs.
2. `run_calibration` — *why*: the measurement, with injectable transcriber/refiner for tests.
3. `recommend` + `render_markdown` — *why*: the decision rule must be reproducible and written down.
4. `main` (argparse) — *why*: the TASK-4256 operator runs it by hand.
5. Offline tests.

### `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py` (CREATE)
```python
"""Calibrate FEAT-653 voice post-processor thresholds on real field recordings.

Usage (TASK-4256):
    PARROT_TEST_REAL_LLM=1 python packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py \
        --corpus /secure/path/corpus.jsonl --out sdd/state/FEAT-653/calibration --llm google:gemini-2.5-flash \
        --max-requests 400

The report holds aggregates only (never transcripts, values, paths or user ids).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    llm_value_correct: bool | None = None
    llm_confidence: float | None = None
    llm_latency_s: float | None = None


class CalibrationReport(BaseModel):
    """Aggregates per (family, locale) + global curves; JSON-serialisable, no personal data."""

    generated_at: datetime
    items: int
    skipped: int = 0
    groups: dict[str, dict[str, Any]] = Field(default_factory=dict)
    llm_threshold_curve: dict[str, float] = Field(default_factory=dict)   # "0.80" -> false-accept rate
    stt_threshold_curve: dict[str, float] = Field(default_factory=dict)
    llm_latency_s: dict[str, float] = Field(default_factory=dict)         # p50/p95/p99
    llm_samples: int = 0
    stt_samples: int = 0


def load_corpus(path: Path) -> list[CorpusItem]:
    """Read a JSONL corpus; invalid lines are logged with their line number only and skipped."""
    # FILL IN: line-by-line CorpusItem.model_validate_json; never log line contents
    raise NotImplementedError


async def run_calibration(
    items: list[CorpusItem],
    *,
    transcriber: Any,
    refiner: ValueRefiner | None,
    max_requests: int | None = None,
) -> CalibrationReport:
    """Measure every item (see module docstring and Implementation Notes); returns aggregates only."""
    # FILL IN: per-item steps 1-4 → ItemOutcome list; aggregate into CalibrationReport (groups, curves, latency
    # percentiles); count skipped; respect max_requests for refiner calls
    raise NotImplementedError


def recommend(report: CalibrationReport) -> dict[str, Any]:
    """Apply the decision rule; returns the three defaults (or the spec defaults with a reason)."""
    defaults = VoiceFormConfig()
    # FILL IN: decision rule from Implementation Notes; return
    # {"llm_refine_threshold": {"value": .., "reason": ..}, "llm_refine_timeout_s": {...}, "stt_confirm_threshold": {...}}
    raise NotImplementedError


def render_markdown(report: CalibrationReport, recommendation: dict[str, Any]) -> str:
    """Human report: per-group table, curves, latency, the recommendation and its reasons."""
    # FILL IN: aggregates only
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI: --corpus, --out, --llm (provider:model, optional), --max-requests, --stt-model, --device."""
    # FILL IN: argparse; refuse an --llm run unless os.environ.get("PARROT_TEST_REAL_LLM") == "1";
    # lazy-import FasterWhisperBackend and LLMFactory here (never at module import); write <out>/report.json
    # and <out>/report.md; print nothing — log with `logger`; return 0/1
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```

### `tests/formdesigner/test_calibrate_voice_postprocessors.py` (CREATE)
```python
"""FEAT-653 TASK-4255 — calibration harness (offline: fake transcriber + fake refiner)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibrate_voice_postprocessors.py"


def _load():
    spec = importlib.util.spec_from_file_location("calibrate_voice_postprocessors", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeSTT:
    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts

    async def transcribe(self, audio_path: Path, language: str | None = None):
        return SimpleNamespace(text=self.texts[audio_path.name], confidence=0.9, language=language or "en",
                               duration_seconds=1.0)


async def test_calibration_report_shape(tmp_path: Path) -> None:
    mod = _load()
    corpus = tmp_path / "corpus.jsonl"
    rows = [
        {"audio": str(tmp_path / "a.wav"), "field_type": "phone", "label": "Phone", "expected": "0412523573"},
        {"audio": str(tmp_path / "b.wav"), "field_type": "email", "label": "Email", "expected": "john@gmail.com"},
        {"audio": str(tmp_path / "c.wav"), "field_type": "number", "label": "N", "expected": 25},
    ]
    corpus.write_text("\n".join(json.dumps(r) for r in rows))
    stt = _FakeSTT({"a.wav": "0,4,12,523,573", "b.wav": "john at gmail dot com", "c.wav": "twenty five"})
    report = await mod.run_calibration(mod.load_corpus(corpus), transcriber=stt, refiner=None)
    assert report.items == 3
    md = mod.render_markdown(report, mod.recommend(report))
    assert "0412523573" not in md and "john" not in md  # aggregates only


def test_recommend_falls_back_below_min_items() -> None:
    # FILL IN: a report with < MIN_ITEMS samples → every recommendation equals VoiceFormConfig() defaults with a reason
    ...


def test_main_refuses_llm_without_opt_in(monkeypatch, tmp_path: Path) -> None:
    # FILL IN: monkeypatch.delenv("PARROT_TEST_REAL_LLM", raising=False); main([... "--llm", "google:x"]) returns 1
    ...
```

### FILL IN checklist
- [ ] `load_corpus`, `run_calibration`, `recommend`, `render_markdown`, `main`
- [ ] the two remaining tests

---

## Acceptance Criteria

- [ ] Offline tests pass with fake STT/refiner; no network, no model download.
- [ ] Report contains aggregates only (asserted).
- [ ] `--llm` without `PARROT_TEST_REAL_LLM=1` is refused.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_calibrate_voice_postprocessors.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4255 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5, sequential fallback loop)
**Date**: 2026-10-12
**Notes**: Re-runnable harness (CorpusItem, run_calibration, recommend, render_markdown, main) with offline tests (fake STT/refiner): shape, privacy (aggregates only), language hint, skipped relative dates, request budget, decision rule, fallback below 30 samples, --llm opt-in refusal. NOT run against a real corpus; TASK-4256 left pending.

**Deviations from spec**: none
