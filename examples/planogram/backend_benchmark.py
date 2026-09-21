"""Descriptive, unlabelled backend comparison for the planogram cycle (FEAT-574).

Reports confidence distributions, evidence quality, coverage, compliance, object counts, errors and
per-stage duration per backend. No ground truth, no pass bar, not a quality measurement.

Usage: python examples/planogram/backend_benchmark.py --photos a.jpg b.jpg --config config.json --out bench/
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import logging
import statistics
import sys
import tempfile
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from parrot_pipelines.models import PlanogramConfig

logger = logging.getLogger("backend_benchmark")
DEFAULT_BACKENDS = ("google:gemini-3.5-flash", "anthropic:claude-sonnet-5")
DISCLAIMER = "Descriptive, unlabelled comparison — not a quality measurement."
_PACKAGES = ("ai-parrot-pipelines", "ai-parrot", "opencv-python-headless", "numpy", "rapidocr", "onnxruntime")
_STAGES = ("perceive", "identify", "compare")
# PlanogramCompliance / VisionAdapter defaults the default factory runs with (pinned in the metadata).
_PARAMETERS = {"cpu_workers": 2, "llm_concurrency": 4, "llm_timeout": 120.0, "repair_retries": 1}
_SCALAR_METRICS = ("evidence_quality", "coverage", "compliance_lenient", "compliance_strict")
_COUNT_METRICS = ("n_cv_shapes", "n_identified", "n_llm_added")


class RunMetrics(BaseModel):
    """One pipeline run."""

    cached: bool
    failed: bool = False
    confidence: Dict[str, float] = Field(default_factory=dict)  # min / median / mean / max / n
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
    durations: Dict[str, float] = Field(default_factory=dict)  # perceive / identify / compare / total (seconds)
    resolved_backend: Optional[str] = None


class PhotoBackendResult(BaseModel):
    """All runs of one backend over one photo."""

    photo: str
    backend: str
    cold_runs: List[RunMetrics] = Field(default_factory=list)
    cached_runs: List[RunMetrics] = Field(default_factory=list)


class BackendStatus(BaseModel):
    """Execution-time availability of one requested backend."""

    backend: str
    available: bool
    reason: Optional[str] = None


class BenchmarkReport(BaseModel):
    """The whole benchmark: pinned metadata, availability, per-run metrics and cold-only aggregates."""

    metadata: Dict[str, Any] = Field(default_factory=dict)
    backends: List[BackendStatus] = Field(default_factory=list)
    results: List[PhotoBackendResult] = Field(default_factory=list)
    aggregates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # backend → cold-only aggregates


def check_backend(backend: str) -> Optional[str]:
    """Return None when ``backend`` is usable now, else a human-readable reason. Never raises.

    Args:
        backend: A ``"provider:model"`` string.

    Returns:
        ``None`` when available, otherwise why not.
    """
    try:
        from parrot.clients.factory import LLMFactory  # lazy: keeps the script importable offline

        provider, model = LLMFactory.parse_llm_string(backend)
        if not provider or not model:
            return f"'{backend}' is not a provider:model string"
        client = LLMFactory.create(backend)
    except (ImportError, ValueError) as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - credentials/config errors at construction are also "unavailable"
        return f"{type(exc).__name__}: {exc}"
    return None if hasattr(client, "ask_to_image") else f"{provider} client has no ask_to_image"


PipelineFactory = Callable[[PlanogramConfig, str, Optional[Path]], Any]


def _default_factory(config: PlanogramConfig, backend: str, cache_dir: Optional[Path]) -> Any:
    """Build the real pipeline for one backend."""
    from parrot_pipelines.planogram import PlanogramCompliance

    return PlanogramCompliance(planogram_config=config, llm=backend, vision_cache_dir=cache_dir)


def _instrument(pipeline: Any, durations: Dict[str, float]) -> None:
    """Wrap the type handler's perceive/identify/compare hooks with perf_counter accumulators.

    No-op for pipelines without a ``_type_handler`` (fakes in tests).
    """
    handler = getattr(pipeline, "_type_handler", None)
    if handler is None:
        return
    for name in _STAGES:
        hook = getattr(handler, name, None)
        if hook is None:
            continue

        @functools.wraps(hook)
        async def timed(*args: Any, _hook: Any = hook, _name: str = name, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return await _hook(*args, **kwargs)
            finally:
                durations[_name] = durations.get(_name, 0.0) + time.perf_counter() - started

        setattr(handler, name, timed)


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict or an object."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _source(item: Any) -> str:
    """The observation source as a plain string (enum or str)."""
    value = _get(item, "source")
    return str(getattr(value, "value", value) or "")


def _flatten(items: Iterable[Any], nested_key: str) -> List[Any]:
    """Per-image containers (``{nested_key: [...]}``) are flattened; bare items pass through."""
    flat: List[Any] = []
    for item in items or []:
        nested = _get(item, nested_key)
        if isinstance(nested, list):
            flat.extend(nested)
        else:
            flat.append(item)
    return flat


def _confidence_stats(values: List[float]) -> Dict[str, float]:
    """min / median / mean / max / n of the model-reported confidences (raw, unmodified)."""
    if not values:
        return {"n": 0}
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "max": max(values),
        "n": len(values),
    }


def _metrics_from_result(result: Dict[str, Any], *, cached: bool, durations: Dict[str, float]) -> RunMetrics:
    """Map a run() result dict to RunMetrics (tolerates objects or dicts for detections/identifications).

    Args:
        result: The ``PlanogramCompliance.run()`` result.
        cached: Whether the run used a warm vision cache.
        durations: Per-stage seconds (plus ``total``).

    Returns:
        The run's metrics — raw counts and distributions, never a quality ratio.
    """
    shapes = _flatten(result.get("detections") or [], "shapes")
    containers = result.get("identifications") or []
    identifications = _flatten(containers, "identifications")
    added = [shape for container in containers for shape in (_get(container, "added") or [])]
    llm_added_ids = {_get(i, "shape_id") for i in identifications if _source(i) == "llm_added"}
    llm_added_ids |= {_get(s, "shape_id") for s in added}
    llm_added_ids |= {_get(s, "shape_id") for s in shapes if _source(s) == "llm_added"}
    confidences = [float(c) for c in (_get(i, "raw_confidence") for i in identifications) if c is not None]
    return RunMetrics(
        cached=cached,
        confidence=_confidence_stats(confidences),
        evidence_quality=result.get("evidence_quality"),
        coverage=result.get("coverage"),
        compliance_lenient=result.get("overall_compliance_score"),
        compliance_strict=result.get("strict_compliance_score"),
        assessment_status=result.get("assessment_status"),
        detection_source=result.get("detection_source"),
        n_cv_shapes=sum(1 for s in shapes if _source(s) == "cv"),
        n_identified=sum(1 for i in identifications if not _get(i, "uncertain", False)),
        n_llm_added=len(llm_added_ids),
        errors=[str(e) for e in result.get("errors") or []],
        durations=dict(durations),
        resolved_backend=result.get("resolved_backend"),
    )


async def _one_run(
    factory: PipelineFactory,
    config: PlanogramConfig,
    backend: str,
    photo: Path,
    *,
    cache_dir: Optional[Path],
    cached: bool,
) -> RunMetrics:
    """Build a fresh pipeline and run it once; a failure is recorded, never raised."""
    durations: Dict[str, float] = {}
    started = time.perf_counter()
    try:
        pipeline = factory(config, backend, cache_dir)
        _instrument(pipeline, durations)
        with tempfile.TemporaryDirectory(prefix="planogram-bench-") as output_dir:
            result = await pipeline.run(image=photo, output_dir=output_dir)
    except Exception as exc:  # noqa: BLE001 - one failing run never aborts the benchmark
        durations["total"] = time.perf_counter() - started
        logger.warning("%s on %s failed: %s", backend, photo.name, exc)
        return RunMetrics(cached=cached, failed=True, errors=[f"{type(exc).__name__}: {exc}"], durations=durations)
    durations["total"] = time.perf_counter() - started
    return _metrics_from_result(result or {}, cached=cached, durations=durations)


async def run_benchmark(
    photos: Sequence[Path],
    config: PlanogramConfig,
    backends: Sequence[str],
    *,
    repeats: int = 3,
    out: Path,
    pipeline_factory: Optional[PipelineFactory] = None,
) -> BenchmarkReport:
    """Run every available backend over every photo and write report.json / report.md into ``out``.

    Args:
        photos: Photo paths.
        config: The planogram configuration shared by every backend.
        backends: ``"provider:model"`` strings.
        repeats: Cold runs per backend × photo.
        out: Output directory for the reports.
        pipeline_factory: Test seam; defaults to building ``PlanogramCompliance``.

    Returns:
        The report (also written to disk).
    """
    factory = pipeline_factory or _default_factory
    photos = [Path(p) for p in photos]
    report = BenchmarkReport(metadata=await _pin_metadata(photos, config, backends, repeats))
    for backend in backends:
        reason = None if pipeline_factory else check_backend(backend)
        status = BackendStatus(backend=backend, available=reason is None, reason=reason)
        report.backends.append(status)
        if reason is not None:
            logger.warning("backend %s unavailable: %s", backend, reason)
            continue
        entries: List[PhotoBackendResult] = []
        for photo in photos:
            entry = PhotoBackendResult(photo=photo.name, backend=backend)
            for _ in range(repeats):
                entry.cold_runs.append(await _one_run(factory, config, backend, photo, cache_dir=None, cached=False))
            with tempfile.TemporaryDirectory(prefix="planogram-bench-cache-") as cache:
                await _one_run(factory, config, backend, photo, cache_dir=Path(cache), cached=True)  # warm-up
                entry.cached_runs.append(
                    await _one_run(factory, config, backend, photo, cache_dir=Path(cache), cached=True)
                )
            entries.append(entry)
            report.results.append(entry)
        runs = [run for entry in entries for run in (*entry.cold_runs, *entry.cached_runs)]
        if runs and all(run.failed for run in runs):
            status.available = False
            status.reason = f"every run failed: {runs[0].errors[0] if runs[0].errors else 'unknown error'}"
            logger.warning("backend %s unavailable: %s", backend, status.reason)
        resolved = sorted({run.resolved_backend for run in runs if run.resolved_backend})
        report.metadata.setdefault("resolved_backends", {})[backend] = resolved
    report.aggregates = _aggregate(report.results)
    await asyncio.to_thread(_write_reports, report, Path(out))
    return report


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _definition_hash(config: PlanogramConfig) -> Optional[str]:
    """sha256 of the slots definition (file bytes when it is a path, sorted-keys JSON otherwise)."""
    definition = getattr(config, "slots_definition", None)
    if definition is None:
        return None
    if isinstance(definition, (str, Path)) and Path(definition).is_file():
        return _sha256_file(Path(definition))
    return hashlib.sha256(json.dumps(definition, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _prompt_versions() -> Dict[str, str]:
    """Every *_PROMPT_VERSION constant of the identification stage that exists."""
    versions: Dict[str, str] = {}
    for module, name in (
        ("parrot_pipelines.planogram.identification.identify", "IDENTIFY_PROMPT_VERSION"),
        ("parrot_pipelines.planogram.identification.detector", "DETECT_PROMPT_VERSION"),
        ("parrot_pipelines.planogram.identification.verify", "VERIFY_PROMPT_VERSION"),
    ):
        try:
            versions[name] = getattr(__import__(module, fromlist=[name]), name)
        except (ImportError, AttributeError) as exc:
            versions[name] = f"unavailable ({type(exc).__name__})"
    return versions


def _package_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for package in _PACKAGES:
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


async def _pin_metadata(
    photos: Sequence[Path], config: PlanogramConfig, backends: Sequence[str], repeats: int
) -> Dict[str, Any]:
    """Everything needed to reproduce the run (pinned before any run starts)."""

    def collect() -> Dict[str, Any]:
        return {
            "disclaimer": DISCLAIMER,
            "images": {p.name: _sha256_file(p) for p in photos},
            "definition_sha256": _definition_hash(config),
            "prompt_versions": _prompt_versions(),
            "requested_backends": list(backends),
            "parameters": dict(_PARAMETERS),
            "concurrency": {"benchmark": "sequential", "llm_concurrency": _PARAMETERS["llm_concurrency"]},
            "retry_limits": {"repair_retries": _PARAMETERS["repair_retries"]},
            "packages": _package_versions(),
            "repeats": repeats,
            "cached_runs_per_photo": 1,
            "planogram_type": getattr(config, "planogram_type", None),
            "config_name": getattr(config, "config_name", None),
            "python": sys.version.split()[0],
        }

    return await asyncio.to_thread(collect)


def _mean_stdev(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"mean": None, "stdev": None, "n": 0}
    return {
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "n": len(values),
    }


def _aggregate(results: Sequence[PhotoBackendResult]) -> Dict[str, Dict[str, Any]]:
    """Per backend, over COLD runs only: mean + stdev per metric, failures and statuses."""
    by_backend: Dict[str, List[RunMetrics]] = {}
    for entry in results:
        by_backend.setdefault(entry.backend, []).extend(entry.cold_runs)
    aggregates: Dict[str, Dict[str, Any]] = {}
    for backend, runs in by_backend.items():
        ok = [run for run in runs if not run.failed]
        summary: Dict[str, Any] = {"cold_runs": len(runs), "failed_runs": len(runs) - len(ok)}
        for metric in (*_SCALAR_METRICS, *_COUNT_METRICS):
            summary[metric] = _mean_stdev([float(v) for v in (getattr(r, metric) for r in ok) if v is not None])
        summary["confidence_median"] = _mean_stdev([r.confidence["median"] for r in ok if "median" in r.confidence])
        summary["durations"] = {
            stage: _mean_stdev([r.durations[stage] for r in ok if stage in r.durations])
            for stage in (*_STAGES, "total")
        }
        statuses: Dict[str, int] = {}
        for run in ok:
            statuses[str(run.assessment_status)] = statuses.get(str(run.assessment_status), 0) + 1
        summary["assessment_status"] = statuses
        summary["errors"] = sum(len(r.errors) for r in runs)
        aggregates[backend] = summary
    return aggregates


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _ms(stat: Dict[str, Any]) -> str:
    if not stat or stat.get("mean") is None:
        return "—"
    return f"{stat['mean']:.3f} ± {stat['stdev']:.3f}"


def _markdown(report: BenchmarkReport) -> str:
    lines = [DISCLAIMER, "", "# Planogram backend benchmark", ""]
    lines += [
        "Counts, model-reported confidence and compliance scores below are descriptive only: there is",
        "no ground truth and no pass bar.",
        "",
        "## Backends",
        "",
    ]
    for status in report.backends:
        state = "available" if status.available else f"unavailable — {status.reason}"
        lines.append(f"- `{status.backend}`: {state}")
    lines += ["", "## Aggregates (cold runs only, mean ± stdev)", ""]
    header = [
        "backend",
        "cold runs",
        "failed",
        "evidence quality",
        "coverage",
        "compliance (lenient)",
        "compliance (strict)",
        "median confidence",
        "CV shapes",
        "identified",
        "LLM-added",
        "perceive s",
        "identify s",
        "compare s",
        "total s",
    ]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for backend, agg in report.aggregates.items():
        row = [
            f"`{backend}`",
            str(agg["cold_runs"]),
            str(agg["failed_runs"]),
            *(_ms(agg[m]) for m in _SCALAR_METRICS),
            _ms(agg["confidence_median"]),
            *(_ms(agg[m]) for m in _COUNT_METRICS),
            *(_ms(agg["durations"][s]) for s in (*_STAGES, "total")),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Per photo", ""]
    header = [
        "photo",
        "backend",
        "run",
        "status",
        "evidence quality",
        "coverage",
        "lenient",
        "strict",
        "confidence min/median/max (n)",
        "CV",
        "identified",
        "LLM-added",
        "total s",
        "errors",
    ]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for entry in report.results:
        runs = [(f"cold {i}", r) for i, r in enumerate(entry.cold_runs, 1)] + [("cached", r) for r in entry.cached_runs]
        for label, run in runs:
            conf = run.confidence
            conf_text = (
                f"{_fmt(conf.get('min'))}/{_fmt(conf.get('median'))}/{_fmt(conf.get('max'))} "
                f"({int(conf.get('n', 0))})"
            )
            status = "failed" if run.failed else _fmt(run.assessment_status)
            row = [
                entry.photo,
                f"`{entry.backend}`",
                label,
                status,
                _fmt(run.evidence_quality),
                _fmt(run.coverage),
                _fmt(run.compliance_lenient),
                _fmt(run.compliance_strict),
                conf_text,
                str(run.n_cv_shapes),
                str(run.n_identified),
                str(run.n_llm_added),
                _fmt(run.durations.get("total")),
                "; ".join(run.errors).replace("|", "/") or "—",
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Pinned metadata", "", "```json", json.dumps(report.metadata, indent=2, default=str), "```", ""]
    return "\n".join(lines)


def _write_reports(report: BenchmarkReport, out: Path) -> None:
    """Blocking: write report.json and report.md (first line = DISCLAIMER)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (out / "report.md").write_text(_markdown(report), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
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
