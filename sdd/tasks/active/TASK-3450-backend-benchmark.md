# TASK-3450: Unlabelled backend benchmark script

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3419, TASK-3444, TASK-3446
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 21**, goal G16, brainstorm "Perception spike and backend
benchmark". The user picks the default vision backend from a **descriptive,
unlabelled** comparison of `google:gemini-3.5-flash` vs
`anthropic:claude-sonnet-5`: same photos, same configuration, each backend
driving the whole perceive → identify → compare run. There is **no ground
truth and no pass bar**; the report must never call its counts or the models'
self-reported confidence "accuracy" or "recall".

Both migrated types must exist for the benchmark to be meaningful (InkWall from
TASK-3444, the fully migrated ProductOnShelves from TASK-3446). The script
lives under `examples/planogram/`; TASK-3419 adds the `.gitignore` negation that
makes `examples/planogram/backend_benchmark.py` trackable.

---

## Scope

- Pydantic report models: `RunMetrics`, `PhotoBackendResult`, `BackendStatus`,
  `BenchmarkReport` (with the pinned `metadata`).
- `check_backend(backend) -> Optional[str]` — execution-time availability:
  unparseable string, provider not installed (`ImportError` from
  `LLMFactory.create`), or a client without `ask_to_image` ⇒ reason string;
  available ⇒ `None`. **Unavailable backends are reported, never raised.**
- `async run_benchmark(photos, config, backends, *, repeats=3, out) -> BenchmarkReport`:
  for every available backend × photo: `repeats` **cold** runs (vision cache
  disabled) + **one cached** re-run pair reported separately; metrics per run:
  raw-confidence distribution (min / median / mean / max / n), evidence
  quality, coverage, compliance lenient + strict, assessment status, object
  counts (CV shapes / identified / LLM-added), errors, per-stage duration
  (perceive / identify / compare / total).
- Pinned metadata: definition hash, image hashes, prompt/schema versions,
  provider/model ids (requested **and** resolved), parameters, package
  versions, concurrency and retry limits, repeats.
- Writes `report.json` and `report.md` into `out`; aggregates per backend.
- CLI (`argparse`). Offline test with an injected fake pipeline factory.

**NOT in scope**: labelled data, IoU matching or any precision/recall
computation (that is the perception spike); choosing the default backend;
changing `run()` to emit timings (the script instruments the three hooks
itself); committing any photo or report produced from private photos.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/backend_benchmark.py` | CREATE | benchmark CLI + `run_benchmark` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py` | CREATE | offline tests (fake pipeline factory) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field
from parrot.clients.factory import LLMFactory                 # verified: packages/ai-parrot/src/parrot/clients/factory.py:163
from parrot_pipelines.models import PlanogramConfig           # verified: parrot_pipelines/models.py:29
from parrot_pipelines.planogram import PlanogramCompliance    # verified: planogram/__init__.py:16-18 (lazy __getattr__)
from importlib import metadata as importlib_metadata          # stdlib — package versions
# created by dependency tasks
from parrot_pipelines.planogram.identification.identify import IDENTIFY_PROMPT_VERSION   # TASK-3438 (via TASK-3444)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                                                   # :163
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]                      # :174  ("provider:model" → split(":", 1))
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient      # :257
        # non-str ⇒ ValueError :286; unknown / not-installed provider ⇒ ImportError :296-299

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py
class PlanogramCompliance(AbstractPipeline):                                         # :24
    self._type_handler                                                               # :69 — the resolved type composable
```

```python
# Created by TASK-3443 (dependency, via TASK-3444) — PlanogramCompliance, spec §3 Module 15
def __init__(self, planogram_config: PlanogramConfig, llm: Any = None, llm_provider=UNSET, llm_model=UNSET, *,
             cpu_workers: int = 2, llm_concurrency: int = 4, llm_timeout: float = 120.0,
             vision_cache_dir: Optional[Path] = None, **kwargs: Any)
    # `llm` may be a client instance OR a "provider:model" string (spec §2 "Backend selection")
async def run(self, image, output_dir=None, image_id=None, **kwargs) -> Dict[str, Any]
    # additive result keys read here: "detections" (shapes; each has .source / ["source"]), "identifications"
    #   (each has raw_confidence, source), "coverage", "evidence_quality", "overall_compliance_score",
    #   "strict_compliance_score", "assessment_status", "detection_source", "resolved_backend", "errors"
# Created by TASK-3442 (dependency) — hooks on the type handler (async): perceive, identify, compare
# Created by TASK-3421 (dependency): ObservationSource values "cv" | "llm_added" | "llm" | "legacy_llm"
# Created by TASK-3419 (dependency): the `!examples/planogram/backend_benchmark.py` negation in .gitignore
```

### Does NOT Exist
- ~~timing keys in the `run()` result~~ — none; instrument `pipeline._type_handler.perceive / identify / compare` from the script.
- ~~labelled ground truth for any example photo~~ — none; do not compute or print precision/recall/accuracy.
- ~~a "model availability" API on the clients~~ — availability = parse + `LLMFactory.create` + `hasattr(client, "ask_to_image")`; a model rejected by the provider at call time shows up as run `errors` and is summarised as `unavailable` only when **every** run of that backend failed.
- ~~`examples.planogram` as an importable package~~ — tests load the script by file path.
- ~~a vision-cache "stats" API~~ — cold vs cached is controlled by the script (`vision_cache_dir=None` vs a directory), not measured from the adapter.
- ~~prompt-version constants other than `IDENTIFY_PROMPT_VERSION`~~ — *(unverified — check before use)*: grep the identification package for other `*_PROMPT_VERSION` names and pin those that exist.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/backend_benchmark.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.parse_llm_string",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Dependency injection for testability: `run_benchmark(..., pipeline_factory=None)`
  — the default factory builds the real `PlanogramCompliance`; the test passes
  a fake whose `run()` returns canned result dicts. Signature stays
  compatible with the spec skeleton (the extra argument is keyword-only with a default).
- Hashes: `hashlib.sha256` over file bytes (photos) and over
  `json.dumps(definition, sort_keys=True)` (definition; when
  `config.slots_definition` is a path, hash the file bytes). Read files through
  `asyncio.to_thread`.
- Wording guard: the Markdown report starts with the fixed line
  `Descriptive, unlabelled comparison — not a quality measurement.` and the words
  "accuracy" and "recall" appear nowhere in generated output (a test enforces it).

### Key Constraints
- Runs are sequential per backend (one pipeline at a time) so durations are not
  polluted by the benchmark's own concurrency; concurrency *inside* a run is
  the pipeline's `llm_concurrency` and is pinned in the metadata.
- A failing run is recorded (`errors`, `failed=True`) and the benchmark continues.
- No `print`; `logging` + `sys.stdout.write` for the final report path.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- spec §3 Module 21 — report columns and pinning list (authoritative)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` — result keys (after TASK-3443)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create the models and `check_backend` — *why*: "unavailable is reported, not raised" is the first acceptance test.
2. Add `_instrument` and `_metrics_from_result` — *why*: per-stage duration has no source in the `run()` result, so the script must time the hooks itself.
3. Add `run_benchmark` (cold repeats, then the cached pair) and the report writers — *why*: cold and cached numbers must never be mixed in one aggregate.
4. Add the CLI; write tests; run the Validation Command.
5. Confirm `git check-ignore examples/planogram/backend_benchmark.py` prints nothing.

### `examples/planogram/backend_benchmark.py` (CREATE) — part 1
```python
"""Descriptive, unlabelled backend comparison for the planogram cycle (FEAT-574).

Reports confidence distributions, evidence quality, coverage, compliance, object counts, errors and
per-stage duration per backend. No ground truth, no pass bar, not a quality measurement.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import statistics
import sys
import tempfile
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parrot_pipelines.models import PlanogramConfig

logger = logging.getLogger("backend_benchmark")
DEFAULT_BACKENDS = ("google:gemini-3.5-flash", "anthropic:claude-sonnet-5")
DISCLAIMER = "Descriptive, unlabelled comparison — not a quality measurement."
_PACKAGES = ("ai-parrot-pipelines", "ai-parrot", "opencv-python-headless", "numpy", "rapidocr", "onnxruntime")


class RunMetrics(BaseModel):
    """One pipeline run."""

    cached: bool
    failed: bool = False
    confidence: Dict[str, float] = Field(default_factory=dict)   # min / median / mean / max / n
    evidence_quality: Optional[float] = None
    coverage: Optional[float] = None
    compliance_lenient: Optional[float] = None
    compliance_strict: Optional[float] = None
    assessment_status: Optional[str] = None
    detection_source: Optional[str] = None
    n_cv_shapes: int = 0
    n_identified: int = 0
    n_llm_added: int = 0
    errors: List[str] = Field(default_factory=list)
    durations: Dict[str, float] = Field(default_factory=dict)    # perceive / identify / compare / total (seconds)
    resolved_backend: Optional[str] = None


class PhotoBackendResult(BaseModel):
    photo: str
    backend: str
    cold_runs: List[RunMetrics] = Field(default_factory=list)
    cached_runs: List[RunMetrics] = Field(default_factory=list)


class BackendStatus(BaseModel):
    backend: str
    available: bool
    reason: Optional[str] = None


class BenchmarkReport(BaseModel):
    metadata: Dict[str, Any] = Field(default_factory=dict)
    backends: List[BackendStatus] = Field(default_factory=list)
    results: List[PhotoBackendResult] = Field(default_factory=list)
    aggregates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)   # backend → cold-only aggregates


def check_backend(backend: str) -> Optional[str]:
    """Return None when ``backend`` is usable now, else a human-readable reason. Never raises."""
    try:
        from parrot.clients.factory import LLMFactory  # lazy: keeps the script importable offline

        provider, model = LLMFactory.parse_llm_string(backend)
        if not provider or not model:
            return f"'{backend}' is not a provider:model string"
        client = LLMFactory.create(backend)
    except (ImportError, ValueError) as exc:
        return str(exc)
    except Exception as exc:  # credentials/config errors at construction are also "unavailable"
        return f"{type(exc).__name__}: {exc}"
    return None if hasattr(client, "ask_to_image") else f"{provider} client has no ask_to_image"
```
**Why this shape**: report columns are the Module 21 list, one field each.
`check_backend` converts every construction failure into a reason string —
that is the "reported explicitly, not raised" contract.

### same file — part 2
```python
PipelineFactory = Callable[[PlanogramConfig, str, Optional[Path]], Any]


def _default_factory(config: PlanogramConfig, backend: str, cache_dir: Optional[Path]) -> Any:
    from parrot_pipelines.planogram import PlanogramCompliance

    return PlanogramCompliance(planogram_config=config, llm=backend, vision_cache_dir=cache_dir)


def _instrument(pipeline: Any, durations: Dict[str, float]) -> None:
    """Wrap the type handler's perceive/identify/compare hooks with perf_counter accumulators."""
    # FILL IN: for name in ("perceive", "identify", "compare"): wrap getattr(pipeline._type_handler, name)
    #   with an async wrapper adding elapsed seconds to durations[name] — bounded by: no-op when the
    #   pipeline has no _type_handler (fake pipelines in tests).


def _metrics_from_result(result: Dict[str, Any], *, cached: bool, durations: Dict[str, float]) -> RunMetrics:
    """Map a run() result dict to RunMetrics (tolerates objects or dicts for detections/identifications)."""
    # FILL IN: confidence stats from identifications[*].raw_confidence (statistics.median/mean; empty ⇒ {"n": 0});
    #   n_cv_shapes = detections with source "cv"; n_llm_added = identifications/detections with source
    #   "llm_added"; n_identified = identifications not marked uncertain — bounded by: never derive a
    #   quality ratio from these counts.
    raise NotImplementedError


async def run_benchmark(photos: Sequence[Path], config: PlanogramConfig, backends: Sequence[str], *,
                        repeats: int = 3, out: Path,
                        pipeline_factory: Optional[PipelineFactory] = None) -> BenchmarkReport:
    """Run every available backend over every photo and write report.json / report.md into ``out``."""
    factory = pipeline_factory or _default_factory
    report = BenchmarkReport(metadata=await _pin_metadata(photos, config, backends, repeats))
    for backend in backends:
        reason = None if pipeline_factory else check_backend(backend)
        report.backends.append(BackendStatus(backend=backend, available=reason is None, reason=reason))
        if reason is not None:
            logger.warning("backend %s unavailable: %s", backend, reason)
            continue
        for photo in photos:
            entry = PhotoBackendResult(photo=photo.name, backend=backend)
            # FILL IN: `repeats` cold runs → factory(config, backend, None); then ONE warm-up + ONE measured
            #   run sharing a tempfile.TemporaryDirectory() cache → entry.cached_runs gets only the measured
            #   one. Each run: durations = {}; _instrument(...); t0 = time.perf_counter(); try run(image=photo,
            #   output_dir=<temp dir>) except Exception → RunMetrics(cached=…, failed=True, errors=[str(exc)]).
            #   Bounded by: sequential execution; a failed run never aborts the loop.
            report.results.append(entry)
        # FILL IN: every run of this backend failed ⇒ flip its BackendStatus to available=False with the
        #   first error as reason.
    report.aggregates = _aggregate(report.results)      # FILL IN: cold runs ONLY; mean + stdev per metric
    await asyncio.to_thread(_write_reports, report, out)
    return report
```
**Why**: `run_benchmark`'s positional/keyword signature is fixed by spec Module
21; `pipeline_factory` is an additive keyword-only test seam. Cold repeats come
first and are the only input to `aggregates`, so cache hits can never flatter
a backend's duration.

### same file — part 3 (helpers + CLI)
```python
async def _pin_metadata(photos: Sequence[Path], config: PlanogramConfig, backends: Sequence[str],
                        repeats: int) -> Dict[str, Any]:
    """Everything needed to reproduce the run."""
    # FILL IN: image sha256 per photo; definition sha256 (file bytes when slots_definition is a path, else
    #   sorted-keys JSON); prompt/schema versions (IDENTIFY_PROMPT_VERSION + any other *_PROMPT_VERSION that
    #   exists); requested backends; parameters (cpu_workers, llm_concurrency, llm_timeout, repair retries —
    #   the PlanogramCompliance defaults 2 / 4 / 120.0 / 1); package versions via importlib_metadata.version
    #   (PackageNotFoundError ⇒ "not installed"); repeats; planogram_type; config_name.
    raise NotImplementedError


def _aggregate(results: Sequence[PhotoBackendResult]) -> Dict[str, Dict[str, Any]]:
    raise NotImplementedError  # FILL IN — cold runs only


def _write_reports(report: BenchmarkReport, out: Path) -> None:
    """Blocking: write report.json and report.md (first line = DISCLAIMER)."""
    raise NotImplementedError  # FILL IN — bounded by: the words "accuracy" / "recall" never appear


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=DISCLAIMER)
    parser.add_argument("--photos", type=Path, nargs="+", required=True)
    parser.add_argument("--config", type=Path, required=True, help="PlanogramConfig JSON")
    parser.add_argument("--backends", nargs="+", default=list(DEFAULT_BACKENDS))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    config = PlanogramConfig.model_validate(json.loads(args.config.read_text(encoding="utf-8")))
    asyncio.run(run_benchmark(args.photos, config, args.backends, repeats=args.repeats, out=args.out))
    sys.stdout.write(f"{args.out / 'report.md'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why**: metadata is pinned **before** any run so an aborted benchmark still
says what it was measuring.

### FILL IN checklist
- [ ] `_instrument` — async wrappers, no-op for fakes
- [ ] `_metrics_from_result` — confidence stats, three counts, dict/object tolerance
- [ ] `run_benchmark` — cold repeats + cached pair, failure isolation, all-failed ⇒ unavailable
- [ ] `_pin_metadata` — full pin list of spec Module 21
- [ ] `_aggregate` — cold only, mean + stdev
- [ ] `_write_reports` — JSON + Markdown, disclaimer first, forbidden words absent
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Default backends are `google:gemini-3.5-flash` and `anthropic:claude-sonnet-5`.
- [ ] An unavailable backend (not installed, unparseable, no `ask_to_image`, or every run failed) appears in `report.backends` with `available=False` and a reason; nothing is raised.
- [ ] Per photo and aggregated: confidence distribution, evidence quality, coverage, lenient + strict compliance, object counts (CV / identified / LLM-added), errors, per-stage duration.
- [ ] Cold runs and cached runs are reported separately; aggregates use cold runs only; `repeats` cold runs per backend × photo.
- [ ] Metadata pins definition + image hashes, prompt/schema versions, requested and resolved provider/model ids, parameters, package versions, concurrency, retry limits, repeats.
- [ ] Generated `report.md` starts with the disclaimer and contains neither "accuracy" nor "recall" (case-insensitive).
- [ ] One failing run is recorded and the benchmark continues.
- [ ] `git check-ignore examples/planogram/backend_benchmark.py` prints nothing; no photo or report is committed.
- [ ] No `print`; `ruff check examples/planogram/backend_benchmark.py` passes.
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py -q` passes offline.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py
"""Offline tests for examples/planogram/backend_benchmark.py (loaded by file path)."""
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "examples" / "planogram" / "backend_benchmark.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("backend_benchmark", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePipeline:
    """run() returns a canned result dict; raises when configured to."""
    def __init__(self, result=None, exc=None): self.result, self.exc, self.calls = result, exc, 0
    async def run(self, image, output_dir=None, **kwargs):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def test_check_backend_reports_unparseable_instead_of_raising(bench):
    assert bench.check_backend("not-a-backend") is not None


def test_check_backend_reports_unknown_provider(bench):
    assert "nosuchprovider" in (bench.check_backend("nosuchprovider:some-model") or "")


@pytest.mark.asyncio
async def test_report_columns_and_pinned_metadata(bench, tmp_path):
    """repeats=2 → 2 cold + 1 cached run per photo×backend; metadata has image/definition hashes,
    package versions, repeats, parameters; aggregates computed from cold runs only."""


@pytest.mark.asyncio
async def test_failing_run_is_recorded_and_all_failed_backend_is_unavailable(bench, tmp_path): ...


@pytest.mark.asyncio
async def test_markdown_has_disclaimer_and_no_quality_wording(bench, tmp_path):
    """report.md first line == bench.DISCLAIMER; 'accuracy' and 'recall' absent (case-insensitive)."""


def test_metrics_from_result_counts_sources(bench):
    """2 cv detections + 1 llm_added identification → n_cv_shapes=2, n_llm_added=1; confidence stats n=…"""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3450-backend-benchmark.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
