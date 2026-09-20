"""Offline tests for examples/planogram/backend_benchmark.py (loaded by file path)."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from parrot_pipelines.models import PlanogramConfig

_SCRIPT = Path(__file__).resolve().parents[4] / "examples" / "planogram" / "backend_benchmark.py"


@pytest.fixture(scope="module")
def bench():
    """The script loaded as a module (Pydantic resolves postponed annotations through sys.modules)."""
    spec = importlib.util.spec_from_file_location("backend_benchmark", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _result(backend: str = "fake:model-a") -> dict:
    """A canned run() result: 2 CV shapes, 1 LLM-added shape; 3 identifications (1 uncertain, 1 llm_added)."""
    return {
        "overall_compliance_score": 0.8,
        "strict_compliance_score": 0.6,
        "coverage": 0.9,
        "evidence_quality": 0.7,
        "assessment_status": "assessed",
        "detection_source": "cv",
        "resolved_backend": backend,
        "errors": [],
        "detections": [
            {
                "shapes": [
                    {"shape_id": "s1", "source": "cv"},
                    {"shape_id": "s2", "source": "cv"},
                    {"shape_id": "a1", "source": "llm_added"},
                ]
            }
        ],
        "identifications": [
            {
                "identifications": [
                    {"shape_id": "s1", "raw_confidence": 0.9, "source": "cv"},
                    {"shape_id": "s2", "raw_confidence": 0.5, "source": "cv", "uncertain": True},
                    {"shape_id": "a1", "raw_confidence": 0.7, "source": "llm_added"},
                ],
                "added": [{"shape_id": "a1", "source": "llm_added"}],
            }
        ],
    }


class FakePipeline:
    """run() returns a canned result dict; raises when configured to."""

    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    async def run(self, image, output_dir=None, **kwargs):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


class RecordingFactory:
    """Builds FakePipelines; records (backend, cache_dir) per build; a backend in ``failing`` always raises."""

    def __init__(self, failing=(), fail_first=False):
        self.failing, self.fail_first, self.builds = set(failing), fail_first, []

    def __call__(self, config, backend, cache_dir):
        self.builds.append((backend, cache_dir))
        if backend in self.failing or (self.fail_first and len(self.builds) == 1):
            return FakePipeline(exc=RuntimeError(f"{backend} rejected the model"))
        return FakePipeline(result=_result(backend))


@pytest.fixture
def photos(tmp_path):
    paths = []
    for name, payload in (("a.jpg", b"photo-a"), ("b.jpg", b"photo-b")):
        path = tmp_path / name
        path.write_bytes(payload)
        paths.append(path)
    return paths


@pytest.fixture
def config():
    return PlanogramConfig(planogram_type="ink_wall", planogram_config={}, slots_definition={"version": "1"})


def test_default_backends(bench):
    assert bench.DEFAULT_BACKENDS == ("google:gemini-3.5-flash", "anthropic:claude-sonnet-5")


def test_check_backend_reports_unparseable_instead_of_raising(bench):
    assert bench.check_backend("not-a-backend") is not None


def test_check_backend_reports_unknown_provider(bench):
    assert "nosuchprovider" in (bench.check_backend("nosuchprovider:some-model") or "")


@pytest.mark.asyncio
async def test_unavailable_backend_is_reported_not_raised(bench, photos, config, tmp_path):
    report = await bench.run_benchmark(photos, config, ["nosuchprovider:x"], repeats=1, out=tmp_path / "out")
    assert report.backends[0].available is False and "nosuchprovider" in report.backends[0].reason
    assert report.results == [] and (tmp_path / "out" / "report.md").is_file()


@pytest.mark.asyncio
async def test_report_columns_and_pinned_metadata(bench, photos, config, tmp_path):
    """repeats=2 → 2 cold + 1 cached run per photo×backend; metadata pinned; aggregates from cold runs only."""
    factory = RecordingFactory()
    report = await bench.run_benchmark(
        photos, config, ["fake:model-a", "fake:model-b"], repeats=2, out=tmp_path / "out", pipeline_factory=factory
    )
    assert len(report.results) == 4
    for entry in report.results:
        assert len(entry.cold_runs) == 2 and len(entry.cached_runs) == 1
        assert all(not r.cached for r in entry.cold_runs) and entry.cached_runs[0].cached
        run = entry.cold_runs[0]
        assert run.compliance_lenient == 0.8 and run.compliance_strict == 0.6
        assert run.coverage == 0.9 and run.evidence_quality == 0.7 and run.assessment_status == "assessed"
        assert "total" in run.durations
    # per photo × backend: 2 cold (no cache) + warm-up + measured cached run sharing one cache dir
    builds_a = [cache for backend, cache in factory.builds if backend == "fake:model-a"]
    assert builds_a[:2] == [None, None] and builds_a[2] is not None and builds_a[2] == builds_a[3]
    meta = report.metadata
    assert meta["images"]["a.jpg"] == hashlib.sha256(b"photo-a").hexdigest()
    assert (
        meta["definition_sha256"] == hashlib.sha256(json.dumps({"version": "1"}, sort_keys=True).encode()).hexdigest()
    )
    assert meta["repeats"] == 2 and meta["requested_backends"] == ["fake:model-a", "fake:model-b"]
    assert meta["parameters"]["llm_concurrency"] == 4 and meta["retry_limits"]["repair_retries"] == 1
    assert meta["prompt_versions"]["IDENTIFY_PROMPT_VERSION"] == "identify-v1"
    assert "ai-parrot-pipelines" in meta["packages"]
    assert meta["resolved_backends"]["fake:model-b"] == ["fake:model-b"]
    agg = report.aggregates["fake:model-a"]
    assert agg["cold_runs"] == 4 and agg["failed_runs"] == 0  # 2 photos × 2 cold — the cached run is excluded
    assert agg["compliance_lenient"]["mean"] == pytest.approx(0.8)
    saved = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert saved["aggregates"]["fake:model-a"]["cold_runs"] == 4


@pytest.mark.asyncio
async def test_failing_run_is_recorded_and_all_failed_backend_is_unavailable(bench, photos, config, tmp_path):
    factory = RecordingFactory(failing={"fake:broken"}, fail_first=True)
    report = await bench.run_benchmark(
        photos[:1], config, ["fake:ok", "fake:broken"], repeats=2, out=tmp_path / "out", pipeline_factory=factory
    )
    ok, broken = report.results
    assert ok.cold_runs[0].failed and "rejected" in ok.cold_runs[0].errors[0]
    assert not ok.cold_runs[1].failed and not ok.cached_runs[0].failed  # the benchmark continued
    statuses = {s.backend: s for s in report.backends}
    assert statuses["fake:ok"].available is True
    assert statuses["fake:broken"].available is False and "every run failed" in statuses["fake:broken"].reason
    assert report.aggregates["fake:ok"]["failed_runs"] == 1


@pytest.mark.asyncio
async def test_markdown_has_disclaimer_and_no_quality_wording(bench, photos, config, tmp_path):
    """report.md first line == bench.DISCLAIMER; 'accuracy' and 'recall' absent (case-insensitive)."""
    factory = RecordingFactory(fail_first=True)
    await bench.run_benchmark(photos, config, ["fake:a"], repeats=1, out=tmp_path / "out", pipeline_factory=factory)
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert markdown.splitlines()[0] == bench.DISCLAIMER
    for text in (markdown, (tmp_path / "out" / "report.json").read_text(encoding="utf-8")):
        assert "accuracy" not in text.lower() and "recall" not in text.lower()


def test_metrics_from_result_counts_sources(bench):
    """2 cv shapes + 1 llm_added (counted once across shapes/identifications/added); confidence stats n=3."""
    metrics = bench._metrics_from_result(_result(), cached=False, durations={"perceive": 0.1})
    assert metrics.n_cv_shapes == 2 and metrics.n_llm_added == 1 and metrics.n_identified == 2
    assert metrics.confidence == {"min": 0.5, "median": 0.7, "mean": pytest.approx(0.7), "max": 0.9, "n": 3}
    assert metrics.durations == {"perceive": 0.1} and metrics.resolved_backend == "fake:model-a"
    assert bench._metrics_from_result({}, cached=True, durations={}).confidence == {"n": 0}


@pytest.mark.asyncio
async def test_instrument_times_type_handler_hooks(bench):
    class Handler:
        async def perceive(self, *args):
            return "p"

        async def identify(self, *args):
            return "i"

        async def compare(self, *args):
            return "c"

    class Pipe:
        _type_handler = Handler()

    durations = {}
    pipe = Pipe()
    bench._instrument(pipe, durations)
    assert await pipe._type_handler.perceive() == "p" and await pipe._type_handler.compare() == "c"
    assert set(durations) == {"perceive", "compare"}
    bench._instrument(FakePipeline(), {})  # no _type_handler → no-op
