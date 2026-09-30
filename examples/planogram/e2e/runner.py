"""Runner of the planogram live E2E harness (FEAT-612)."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import math
import sys
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image
from pydantic import BaseModel

from parrot.clients.factory import LLMFactory
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.contracts import FacingStatus
from parrot_pipelines.planogram.identification.identify import IDENTIFY_PROMPT_VERSION
from parrot_pipelines.planogram.migration import check_row
from parrot_pipelines.planogram.plan import PlanogramCompliance

logger = logging.getLogger(__name__)
OPT_IN_ENV = "PARROT_TEST_REAL_LLM"
MANIFEST_ENV = "PLANOGRAM_E2E_MANIFEST"
_MODELS_MODULE = "planogram_e2e_models"


def _load_models() -> ModuleType:
    """Load sibling models under a unique module name."""
    if _MODELS_MODULE in sys.modules:
        return sys.modules[_MODELS_MODULE]
    path = Path(__file__).with_name("models.py")
    spec = importlib.util.spec_from_file_location(_MODELS_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODELS_MODULE] = module
    spec.loader.exec_module(module)
    return module


_models = _load_models()
CASE_TYPES = _models.CASE_TYPES
GroundTruth = _models.GroundTruth
LiveCase = _models.LiveCase
LiveManifest = _models.LiveManifest


class RequestBudgetExceeded(RuntimeError):
    """Raised when a case would exceed its uncached provider-request cap."""


class CountingClient:
    """Wrap a client and cap every provider call at the client boundary."""

    def __init__(self, client: Any, max_requests: int) -> None:
        self._client = client
        self.max_requests = max_requests
        self.requests = 0
        self.exhausted = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def __aenter__(self) -> "CountingClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def _charge(self, method: str) -> None:
        """Count a call or raise after setting the exhaustion marker."""
        if self.requests >= self.max_requests:
            self.exhausted = True
            logger.warning("provider request budget exhausted at %d calls (%s)", self.requests, method)
            raise RequestBudgetExceeded(f"provider request budget exhausted at {self.max_requests} calls")
        self.requests += 1

    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        self._charge("ask_to_image")
        return await self._client.ask_to_image(prompt=prompt, image=image, **kwargs)

    async def detect_objects(self, *args: Any, **kwargs: Any) -> Any:
        self._charge("detect_objects")
        return await self._client.detect_objects(*args, **kwargs)


def opt_in_enabled(environ: Mapping[str, str]) -> bool:
    """Return true only for the exact opt-in value ``1``."""
    return environ.get(OPT_IN_ENV) == "1"


def load_manifest(path: Path) -> LiveManifest:
    """Load a manifest and resolve all paths relative to its directory."""
    payload = json.loads(path.read_text())
    base = path.parent
    for case in payload.get("cases", []):
        for key in ("photos", "config_path", "ground_truth_path", "cache_dir", "output_dir"):
            if key not in case:
                continue
            values = case[key] if key == "photos" else [case[key]]
            resolved = [str((base / value).resolve()) if not Path(value).is_absolute() else value for value in values]
            case[key] = resolved if key == "photos" else resolved[0]
    return LiveManifest.model_validate(payload)


def missing_prerequisites(case: LiveCase, manifest: LiveManifest, environ: Mapping[str, str]) -> list[str]:
    """Return skip reasons for missing local inputs or credentials."""
    reasons = [
        f"missing file: {path}"
        for path in [*case.photos, case.config_path, case.ground_truth_path]
        if not path.exists()
    ]
    provider = case.backend.split(":", 1)[0].lower()
    variables = manifest.required_env.get(provider)
    if variables is None:
        reasons.append(f"manifest declares no required_env for provider {provider}")
    else:
        reasons.extend(
            f"missing required environment variable: {name}" for name in variables if not environ.get(name, "").strip()
        )
    return reasons


def _value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, Mapping) else getattr(item, key, default)


def ground_truth_assertions(result: Mapping[str, Any], truth: GroundTruth) -> list[dict[str, Any]]:
    """Evaluate every labelled expectation and return explicit assertion records."""
    assertions: list[dict[str, Any]] = []
    score = result.get("overall_compliance_score")
    score_ok = (
        isinstance(score, (int, float))
        and math.isfinite(score)
        and abs(score - truth.overall_score) <= truth.score_tolerance
    )
    assertions.append(
        {"check": "overall_score", "passed": score_ok, "detail": f"overall score {score!r} outside expected range"}
    )
    coverage = result.get("coverage")
    coverage_ok = isinstance(coverage, (int, float)) and math.isfinite(coverage) and coverage >= truth.min_coverage
    assertions.append(
        {
            "check": "coverage",
            "passed": coverage_ok,
            "detail": f"coverage {coverage!r} below minimum {truth.min_coverage}",
        }
    )

    positions = {_value(item, "facing_id"): item for item in result.get("position_results", [])}
    identity_errors = 0
    for facing_id, expected in truth.expected_positions.items():
        actual = _value(positions.get(facing_id), "identity") if facing_id in positions else None
        if actual != expected:
            identity_errors += 1
    identity_ok = identity_errors <= truth.max_identity_errors
    assertions.append(
        {
            "check": "identity_errors",
            "passed": identity_ok,
            "detail": f"identity errors {identity_errors} exceed {truth.max_identity_errors}",
        }
    )

    occupied = {
        FacingStatus.MATCH.value,
        FacingStatus.MISPLACED.value,
        FacingStatus.VARIANT_UNRESOLVED.value,
        FacingStatus.MISMATCH.value,
        FacingStatus.INFERRED_PRESENT.value,
        FacingStatus.OCCUPIED_UNASSIGNED.value,
        "unexpected_occupied",
    }
    empty = {FacingStatus.EMPTY.value, "expected_empty"}
    occupancy_errors = 0
    for facing_id, expected in truth.expected_occupancy.items():
        if expected == "unknown":
            continue
        status = _value(positions.get(facing_id), "status")
        status = status.value if isinstance(status, Enum) else status
        actual = "occupied" if status in occupied else "empty" if status in empty else "unknown"
        if actual != expected:
            occupancy_errors += 1
    occupancy_ok = occupancy_errors <= truth.max_occupancy_errors
    assertions.append(
        {
            "check": "occupancy_errors",
            "passed": occupancy_ok,
            "detail": f"occupancy errors {occupancy_errors} exceed {truth.max_occupancy_errors}",
        }
    )

    rules: dict[str, Any] = {}
    for shelf in result.get("shelf_scores", []):
        for rule in _value(shelf, "rule_results", []) or []:
            rules[_value(rule, "rule_id")] = rule
    for rule_id, expected in truth.expected_rules.items():
        observed = rules.get(rule_id)
        passed = (
            observed is not None
            and bool(_value(observed, "assessed", False))
            and _value(observed, "passed") is expected
        )
        assertions.append(
            {
                "check": f"rule:{rule_id}",
                "passed": passed,
                "detail": f"rule {rule_id} did not meet expected result {expected}",
            }
        )
    return assertions


def compare_ground_truth(result: Mapping[str, Any], truth: GroundTruth) -> list[str]:
    """Return all failed ground-truth assertion details."""
    return [item["detail"] for item in ground_truth_assertions(result, truth) if not item["passed"]]


def to_json_safe(value: Any) -> Any:
    """Project pipeline output to JSON-safe values."""
    if isinstance(value, BaseModel):
        return to_json_safe(value.model_dump(mode="python"))
    if isinstance(value, Image.Image) or isinstance(value, bytes):
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_config_paths(config: dict[str, Any], base: Path) -> dict[str, Any]:
    """Resolve path-valued config fields against the config file directory."""
    resolved = dict(config)
    if isinstance(resolved.get("slots_definition"), str):
        path = Path(resolved["slots_definition"])
        if not path.is_absolute():
            resolved["slots_definition"] = str((base / path).resolve())
    refs = resolved.get("reference_images")
    if isinstance(refs, dict):
        resolved["reference_images"] = {
            key: (
                [str((base / Path(item)).resolve()) if not Path(item).is_absolute() else item for item in value]
                if isinstance(value, list)
                else (
                    str((base / Path(value)).resolve())
                    if isinstance(value, str) and not Path(value).is_absolute()
                    else value
                )
            )
            for key, value in refs.items()
        }
    return resolved


def _build_client(case: LiveCase) -> Any:
    """Create a real provider client from the explicit backend."""
    return LLMFactory.create(case.backend)


async def run_case(case: LiveCase) -> dict[str, Any]:
    """Run one case, persisting JSON-safe evidence and a bounded request report."""
    truth = GroundTruth.model_validate_json(await asyncio.to_thread(case.ground_truth_path.read_text))
    raw_config = json.loads(await asyncio.to_thread(case.config_path.read_text))
    if raw_config.get("planogram_type") != case.planogram_type:
        raise ValueError(f"config planogram_type {raw_config.get('planogram_type')!r} does not match case")
    config = _resolve_config_paths(raw_config, case.config_path.parent)
    preflight_config = dict(config)
    slots_definition = preflight_config.get("slots_definition")
    if isinstance(slots_definition, str) and await asyncio.to_thread(Path(slots_definition).is_file):
        preflight_config["slots_definition"] = json.loads(await asyncio.to_thread(Path(slots_definition).read_text))
    verdict = check_row(preflight_config)
    if not verdict.ok:
        raise ValueError("invalid planogram config: " + "; ".join(verdict.problems))

    case.cache_dir.mkdir(parents=True, exist_ok=True)
    case.output_dir.mkdir(parents=True, exist_ok=True)
    counting = CountingClient(_build_client(case), case.max_provider_requests)
    pipeline = PlanogramCompliance(
        planogram_config=PlanogramConfig.model_validate(config), llm=counting, vision_cache_dir=case.cache_dir
    )
    before = len(list(case.cache_dir.glob("*.json")))
    result: Mapping[str, Any] = {}
    timed_out = False
    try:
        result = await asyncio.wait_for(
            pipeline.run([str(path) for path in case.photos], output_dir=case.output_dir), case.timeout_seconds
        )
    except asyncio.TimeoutError:
        timed_out = True
    after = len(list(case.cache_dir.glob("*.json")))
    assertions = ground_truth_assertions(result, truth) if not timed_out else []
    if timed_out:
        assertions.append({"check": "timeout", "passed": False, "detail": f"timed out after {case.timeout_seconds}s"})
    if counting.exhausted:
        assertions.append({"check": "request_budget", "passed": False, "detail": "provider request budget exhausted"})
    safe_result = to_json_safe(result)
    compliance_path = case.output_dir / "compliance.json"
    report_path = case.output_dir / "report.json"
    compliance_path.write_text(json.dumps(safe_result, indent=2, sort_keys=True, allow_nan=False))
    render_paths = []
    for render in result.get("renders", []) if isinstance(result, Mapping) else []:
        overlay_path = _value(render, "overlay_path")
        if overlay_path:
            render_paths.append(overlay_path)
    report = {
        "case_id": case.case_id,
        "planogram_type": case.planogram_type,
        "backend": case.backend,
        "resolved_backend": result.get("resolved_backend"),
        "config_sha256": await asyncio.to_thread(_sha256, case.config_path),
        "layout_profile": config.get("planogram_config", {}).get("layout_profile"),
        "photo_sha256": {path.name: _sha256(path) for path in case.photos},
        "prompt_version": IDENTIFY_PROMPT_VERSION,
        "reference_selection": result.get("reference_selection"),
        "provider_requests": counting.requests,
        "provider_request_cap": case.max_provider_requests,
        "exhausted": counting.exhausted,
        "cache_entries_before": before,
        "cache_entries_after": after,
        "render_paths": render_paths,
        "errors": result.get("errors", []) if isinstance(result, Mapping) else [],
        "assertions": assertions,
    }
    report_path.write_text(json.dumps(to_json_safe(report), indent=2, sort_keys=True, allow_nan=False))
    return {
        "case_id": case.case_id,
        "violations": [item["detail"] for item in assertions if not item["passed"]],
        "provider_requests": counting.requests,
        "report_path": report_path,
        "compliance_path": compliance_path,
    }
