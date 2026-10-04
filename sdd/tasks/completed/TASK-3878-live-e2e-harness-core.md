# TASK-3878: Live E2E harness models, runner and ignore rules

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3871, TASK-3877
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 14** (skeleton `GroundTruth` / `LiveCase` / `run_case` / `compare_ground_truth`) and
§4 **"Live E2E behavior (not the deterministic E2E gate)"**. FEAT-612 needs an opt-in live suite for
three fixtures (`shelves`, `ink-wall`, `backlit-endcap`) that runs the *final* public
`PlanogramCompliance.run()` (TASK-3871) on private local photos and compares it with hand-labelled
ground truth. This task builds the committed, offline-testable core: the schema (`models.py`), the
runner (`runner.py`), the `.gitignore` negations that admit ONLY the harness code and README (AC18),
and an offline unit-test module with synthetic data and fake clients. TASK-3879 adds the pytest live
cases (`conftest.py`, `test_compliance.py`) and the README on top of this runner.

The repository is public: retailer photos, plans, definitions, manifests, ground truth, the vision
cache, renders and reports must stay ignored (spec §4 "Test Data / Fixtures", §7 risk table).

---

## Scope

- Add narrow `.gitignore` negations so exactly `conftest.py`, `models.py`, `runner.py`,
  `test_compliance.py` and `README.md` under `examples/planogram/e2e/` are trackable, and everything
  else there (including subdirectories and stray `*.py`) stays ignored.
- Implement `examples/planogram/e2e/models.py`: `CASE_TYPES`, `GroundTruth`, `LiveCase` (spec skeleton
  fields verbatim) and an additive `LiveManifest` (cases + per-provider required environment variables).
- Implement `examples/planogram/e2e/runner.py`: opt-in / prerequisite helpers, manifest loading,
  a counting client wrapper enforcing the uncached request budget at the client call boundary,
  `run_case`, `ground_truth_assertions`, `compare_ground_truth`, and the JSON-safe projection.
- Write `packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py` covering the
  §4 "live harness offline" row: default opt-out, missing prerequisites, wrong type, malformed
  manifest, missing labels, tolerance bounds, nonfinite scores, cache hit, request-budget exhaustion,
  plus the git-ignore behaviour (AC18) with synthetic filenames.

**NOT in scope**: `examples/planogram/e2e/conftest.py`, `test_compliance.py` and `README.md`
(TASK-3879); any change to `parrot_pipelines` source (TASK-3871 owns `plan.py`, TASK-3877 owns
`migration.py`); docs (TASK-3880); committing any real photo, config, manifest or ground truth;
importing anything from `examples/planogram/pipelines/` or `examples/pipelines/` (ignored, absent in a
worktree — spec §7 risk "Ignored example unavailable in worktree").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | Narrow negations for the five harness files under `examples/planogram/e2e/` |
| `examples/planogram/e2e/models.py` | CREATE | `CASE_TYPES`, `GroundTruth`, `LiveCase`, `LiveManifest` |
| `examples/planogram/e2e/runner.py` | CREATE | Prerequisites, manifest loading, counting client, `run_case`, ground-truth comparison, JSON projection |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py` | CREATE | Offline harness + ignore-rule tests (synthetic data, fake clients) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import LLMFactory  # verified: packages/ai-parrot/src/parrot/clients/factory.py:163 (class), create at :257
from parrot_pipelines.models import PlanogramConfig  # verified: packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:32
from parrot_pipelines.planogram.plan import PlanogramCompliance  # verified: packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:48
from parrot_pipelines.planogram.migration import check_row, PreflightRow  # verified: planogram/migration.py:269, :58
from parrot_pipelines.planogram.contracts import FacingStatus, RenderRecord  # verified: planogram/contracts.py:146, :312
from parrot_pipelines.planogram.identification.identify import IDENTIFY_PROMPT_VERSION  # verified: identification/identify.py:33
from parrot_pipelines.planogram.identification.vision import VisionAdapter, encode_png  # verified: identification/vision.py:131, :100 (test only)
from parrot_pipelines.planogram.backend import ResolvedBackend  # verified: planogram/backend.py:28 (test only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py:257
@staticmethod
def create(llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:48 / :70 / :134
class PlanogramCompliance(AbstractPipeline):
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None, llm_provider=UNSET, llm_model=UNSET, *,
                 cpu_workers: int = 2, llm_concurrency: int = 4, llm_timeout: float = 120.0,
                 vision_cache_dir: Optional[Path] = None, enabled_ocr: bool = False, **kwargs)  # TASK-3871 makes enabled_ocr: bool | None = None
    async def run(self, image, output_dir=None, image_id=None, **kwargs) -> Dict[str, Any]
    # result keys assembled in _assemble (plan.py:352-389): eight legacy keys + position_results,
    # shelf_scores, coverage, assessment_status, strict_compliance_score, evidence_quality,
    # detection_source, ocr_available, resolved_backend, renders (List[RenderRecord]), errors

# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py:45-52
# An injected client instance (not None / not str) is used as-is; resolve_backend reads
# llm.client_name and getattr(llm, "model", None) (planogram/backend.py:86-92).

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py:131-277
class VisionAdapter:
    def __init__(self, client, backend: ResolvedBackend, *, semaphore, cache_dir=None, max_tokens=8192,
                 timeout=120.0, repair_retries=1)  # raises VisionError if client lacks ask_to_image (:158)
    async def ask(self, prompt, images: Sequence[bytes], schema, *, stage: str, prompt_version: str,
                  system_prompt=None) -> T  # :173 — cache hit returns BEFORE any client call (:213-216)
    # the only provider call: self.client.ask_to_image(prompt=..., image=images[0], **kwargs) (:268);
    # any client exception (incl. ours) becomes VisionError (:275)
    # cache files: <cache_dir>/<key>.json (:307, :329)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py:58, :269
class PreflightRow(BaseModel): config_name: str; planogram_type: str; ok: bool; problems: List[str]
def check_row(row: Dict[str, Any]) -> PreflightRow  # row keys: planogram_type, config_name, slots_definition, planogram_config

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class FacingStatus(str, Enum)  # :146 — MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, EMPTY, INFERRED_PRESENT,
                               # OCCUPIED_UNASSIGNED, CONFLICT, NOT_ASSESSED, NOT_VISIBLE
class RuleOutcome(BaseModel): rule_id; assessed: bool; passed: Optional[bool]; ...  # :180
class PositionResult(BaseModel): facing_id; shelf_id; status: FacingStatus; identity: Optional[str]; ...  # :191
class ShelfScore(BaseModel): ...; rule_results: List[RuleOutcome]  # :204, rule_results at :218
class RenderRecord(BaseModel): image_id; rendered_image: Optional[Any] (PIL); overlay_path: Optional[str]  # :312

# packages/ai-parrot-pipelines/tests/conftest.py:46, :62, :159 (shared test fixture)
class FakeVisionClient:  client_name = "fake"; model = None
    def queue(self, method: str, *responses: Any) -> None   # "ask_to_image" | "detect_objects"
    async def ask_to_image(self, prompt: str, image: Any, **kwargs) -> Any  # returns object with .output / .structured_output
@pytest.fixture
def fake_vision_client() -> FakeVisionClient

# Loader pattern for example scripts (nothing under examples/ is a package):
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py:13-26
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 (contracts.py): FacingStatus.EXPECTED_EMPTY, FacingStatus.UNEXPECTED_OCCUPIED
# TASK-3858 (identify.py): IDENTIFY_PROMPT_VERSION becomes "identify-v2-ocr" (same constant name)
# TASK-3871 (plan.py): enabled_ocr: bool | None = None (None = auto); final result assembly (spec §2 "Result assembly")
# TASK-3877 (migration.py): MIGRATED_TYPES = the six registered keys; check_row also validates layout
def check_row(row: dict[str, Any]) -> PreflightRow:
    """Validate type, definition, bindings and layout; unknown types are not silently ready."""
```

### Does NOT Exist
- ~~`examples/planogram/e2e/`~~ — does not exist yet; this task creates it.
- ~~A `__init__.py` under `examples/planogram/`~~ — example folders are not packages; load by file path.
- ~~A request counter or budget in `VisionAdapter`~~ — counting happens in the harness's client wrapper.
- ~~A cache-hit counter in `VisionAdapter`~~ — only a DEBUG log line (vision.py:211); report cache entry counts instead.
- ~~A committed manifest / ground truth / fixture set~~ — none exists; never generate truth from a run.
- ~~`PlanogramCompliance.run(..., max_requests=...)`~~ — no budget parameter; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".gitignore", "action": "MODIFY"},
    {"path": "examples/planogram/e2e/models.py", "action": "CREATE"},
    {"path": "examples/planogram/e2e/runner.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#PreflightRow",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FacingStatus",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RenderRecord",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter.ask",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#encode_png",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py#ResolvedBackend",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#IDENTIFY_PROMPT_VERSION",
    "sym:packages/ai-parrot-pipelines/tests/conftest.py#FakeVisionClient"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Ignore-rule tests: `examples/planogram/tests/test_plancheck_gitignore.py` (`git check-ignore -q`, rc 0 =
  ignored, rc 1 = not ignored, anything else ⇒ `pytest.skip`). Reuse that exact helper shape.
- Loading example scripts by path: `test_backend_benchmark.py:13-26` (`spec_from_file_location`, register in
  `sys.modules` so Pydantic resolves postponed annotations, pop on teardown).

### Key Constraints
- **Sibling import without `sys.path` games.** `runner.py` loads `models.py` by file path under the unique
  module name `planogram_e2e_models` (reusing it when already in `sys.modules`) — *why*: a bare
  `import models` can silently bind to an unrelated top-level `models` module in a shared pytest session.
  `conftest.py` (TASK-3879) will load `runner.py` as `planogram_e2e_runner`; keep both names.
- **Count at the client boundary, never bypass `AbstractClient`** (spec §4). `CountingClient` wraps the
  real client, delegates attributes, and counts `ask_to_image` and `detect_objects` before forwarding.
  Implement `__aenter__`/`__aexit__` returning `self` because `async with client` looks dunders up on the
  type, so `__getattr__` alone would leak an uncounted client. Cache hits never reach the client, so they
  consume no budget by construction.
- Budget exhaustion raises `RequestBudgetExceeded` inside the wrapper; `VisionAdapter` turns it into a
  `VisionError` and the pipeline isolates it per photo, so `run_case` MUST read `counting.exhausted`
  afterwards and record a violation — never report a budget-starved run as a pass.
- Skip vs fail (spec §4): missing opt-in, manifest, photo/config/ground-truth file or credential env var
  ⇒ skip reasons (returned by `missing_prerequisites`, turned into `pytest.skip` by TASK-3879). Invalid
  existing files, wrong planogram type, malformed manifest ⇒ raise (the test fails).
- Validate before any provider initialisation: ground truth, config JSON, `planogram_type` match and
  `check_row` all run BEFORE `_build_client` is called.
- Tolerances are validated, never widened: scores/coverage/tolerance in [0, 1], error budgets ≥ 0, all
  finite. Truth is never generated from or updated by the run under test.
- File I/O inside `run_case` goes through `asyncio.to_thread` (async-first convention; `plan.py:221` uses the
  same idiom). `load_manifest` is sync on purpose: it runs in a sync pytest fixture, never on a loop.
- JSON projection excludes PIL images and raw bytes (reference bytes), converts `Path`/`Enum`, and maps
  nonfinite floats to `null`; render paths are recorded separately in the report.
- Use `logger = logging.getLogger(__name__)`; no `print`. No `requests`/`httpx`.
- Do not hardcode retailer products, SKUs or counts anywhere; tests use generic ids (`f1`, `r1`).

### References in Codebase
- `examples/planogram/tests/test_plancheck_gitignore.py` — ignore-test helper.
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py` — canned `run()` result dicts and loader.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:352-389` — result keys.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.gitignore` — *why*: `examples/**/*.py` (line 20) and `examples/planogram/*` (line 424) ignore the
   harness today, and later tasks cannot commit it without the negations.
2. Create `models.py` — *why*: `runner.py` and the tests validate everything through these models.
3. Create `runner.py` — *why*: TASK-3879's live test only orchestrates; all logic must be offline-testable here.
4. Create the offline test module and run it — *why*: AC16/AC17/AC18 need proof without credentials.
5. Run ruff/black on the three Python files.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -Fxc '!examples/planogram/aws/README.md' .gitignore)
# AFTER — insert below `!examples/planogram/aws/README.md` (verified: .gitignore:453; line 454 is blank)
# FEAT-612: live planogram E2E harness — code + README only. The local manifest, photos,
# configs, definitions, ground truth, vision cache, renders and reports stay ignored.
!examples/planogram/e2e/
examples/planogram/e2e/*
!examples/planogram/e2e/conftest.py
!examples/planogram/e2e/models.py
!examples/planogram/e2e/runner.py
!examples/planogram/e2e/test_compliance.py
!examples/planogram/e2e/README.md
```
**Why**: the parent rule `examples/planogram/*` (verified `.gitignore:424`, `grep -Fxc` = 1) ignores the
directory; `!…/e2e/` re-opens it, `…/e2e/*` re-ignores its content, and five exact-file negations admit
only the harness. Exact names (not `*.py`) keep a private helper script out of git. Placed after the
`aws` block so it follows the file's per-folder convention and wins over `examples/**/*.py` (line 20).
This exact block was simulated with `git check-ignore` in a scratch repo: the five files are admitted,
`manifest.json`, `private/*.jpg`, `cases/*/config.json`, `ground_truth.json`, `cache/*.json`,
`out/*/compliance.json`, `*.png`, `*.pdf`, `local_helper.py` and `__pycache__/` stay ignored.

### `examples/planogram/e2e/models.py` (CREATE) — block 1: module header and ground truth
```python
"""Schema of the planogram live E2E harness (FEAT-612, spec Module 14).

Only this schema is committed. Manifests, photos, configurations and hand-labelled
ground truth are private local files that ``.gitignore`` keeps untracked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The three live cases and the exact planogram type each must exercise (spec §4).
CASE_TYPES: dict[str, str] = {
    "shelves": "product_on_shelves",
    "ink-wall": "ink_wall",
    "backlit-endcap": "endcap_backlit_multitier",
}


class GroundTruth(BaseModel):
    """Human-labelled expectations and tolerances; no generated baseline accepted as truth."""

    model_config = ConfigDict(extra="forbid")

    expected_positions: dict[str, str]
    expected_occupancy: dict[str, Literal["occupied", "empty", "unknown"]]
    expected_rules: dict[str, bool]
    overall_score: float
    score_tolerance: float
    min_coverage: float
    max_identity_errors: int
    max_occupancy_errors: int

    @model_validator(mode="after")
    def _check_labels_and_bounds(self) -> "GroundTruth":
        """Reject empty label sets, nonfinite values, out-of-range scores and negative budgets."""
        # FILL IN: raise ValueError when all three expected_* maps are empty ("no assertions") —
        #   bounded by spec §4 "never accept missing assertions".
        # FILL IN: overall_score, score_tolerance, min_coverage must be math.isfinite and in [0, 1];
        #   max_identity_errors / max_occupancy_errors >= 0 — bounded by spec §4 tolerance validation.
        return self

```
**Why (block 1)**: ground-truth fields are the spec skeleton verbatim; the validator is where "never silently widen tolerances" is enforced.

### `examples/planogram/e2e/models.py` (CREATE) — block 2: cases and manifest (same file, appended)
```python
class LiveCase(BaseModel):
    """Local paths and bounded execution, never committed retailer data."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    planogram_type: Literal["product_on_shelves", "ink_wall", "endcap_backlit_multitier"]
    photos: list[Path]
    config_path: Path
    ground_truth_path: Path
    backend: str
    cache_dir: Path
    output_dir: Path
    max_provider_requests: int = 64
    timeout_seconds: float = 600.0

    @model_validator(mode="after")
    def _check_case(self) -> "LiveCase":
        """case_id ↔ type pairing, explicit provider:model backend, positive finite limits."""
        # FILL IN: case_id must be a CASE_TYPES key and CASE_TYPES[case_id] == planogram_type
        #   (a shelves config cannot satisfy the backlit case) — bounded by spec §4 "exact expected type values".
        # FILL IN: photos non-empty; backend must be "provider:model" with both parts non-blank
        #   (spec §4 "explicit backend/model"); max_provider_requests > 0; timeout_seconds finite and > 0.
        return self


class LiveManifest(BaseModel):
    """The local manifest: cases plus the credential env vars each backend provider needs."""

    model_config = ConfigDict(extra="forbid")

    cases: list[LiveCase]
    required_env: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_namespaces(self) -> "LiveManifest":
        """Unique case ids and no shared cache/output directory between cases."""
        # FILL IN: duplicate case_id, or two cases resolving to the same cache_dir or output_dir
        #   ⇒ ValueError — bounded by spec §7 "concurrent live runs must not share a write namespace".
        return self
```
**Why this shape**: `GroundTruth` and `LiveCase` fields are the spec §3 M14 skeleton verbatim;
`extra="forbid"` turns a typo in a private file into a failure instead of a silently ignored label.
`LiveManifest` is additive (the spec requires "absent backend credentials ⇒ skip" but defines no field
for them): credentials are named per provider, never hardcoded in code.

### `examples/planogram/e2e/runner.py` (CREATE) — block 1: sibling loading and counting client
```python
"""Runner of the planogram live E2E harness (FEAT-612, spec Module 14 and §4 Live E2E behavior)."""

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
    """Load the sibling ``models.py`` by path under a unique module name (reused when loaded)."""
    # FILL IN: return sys.modules[_MODELS_MODULE] if present; else spec_from_file_location(
    #   _MODELS_MODULE, Path(__file__).with_name("models.py")), register in sys.modules BEFORE exec_module.


_models = _load_models()
CASE_TYPES = _models.CASE_TYPES
GroundTruth = _models.GroundTruth
LiveCase = _models.LiveCase
LiveManifest = _models.LiveManifest


class RequestBudgetExceeded(RuntimeError):
    """Raised by CountingClient when a case would exceed its uncached provider-request cap."""


class CountingClient:
    """Wrap the real client; count and cap every provider call made through it."""

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
        """Count one provider call or raise RequestBudgetExceeded (setting ``exhausted``)."""
        # FILL IN: if self.requests >= self.max_requests: set exhausted, log WARNING, raise; else += 1.

    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        self._charge("ask_to_image")
        return await self._client.ask_to_image(prompt=prompt, image=image, **kwargs)

    async def detect_objects(self, *args: Any, **kwargs: Any) -> Any:
        self._charge("detect_objects")
        return await self._client.detect_objects(*args, **kwargs)

```
**Why (block 1)**: the unique module name and the counting wrapper are the two decisions that make the harness safe in a shared pytest session and honest about provider cost.

### `examples/planogram/e2e/runner.py` (CREATE) — block 2: opt-in and prerequisites (same file, appended)
```python
def opt_in_enabled(environ: Mapping[str, str]) -> bool:
    """True only when ``PARROT_TEST_REAL_LLM`` is exactly ``"1"``."""
    return environ.get(OPT_IN_ENV) == "1"


def load_manifest(path: Path) -> LiveManifest:
    """Read and validate the local manifest; relative paths resolve against its directory."""
    # FILL IN: json.loads(path.read_text()); resolve every relative photos/config_path/ground_truth_path/
    #   cache_dir/output_dir against path.parent BEFORE validation; JSON or validation errors propagate
    #   (malformed manifest ⇒ failure, spec §4).


def missing_prerequisites(case: LiveCase, manifest: LiveManifest, environ: Mapping[str, str]) -> list[str]:
    """Return one skip reason per missing photo/config/ground-truth file or credential variable."""
    # FILL IN: provider = case.backend.split(":", 1)[0].lower(); if provider not in manifest.required_env
    #   ⇒ reason "manifest declares no required_env for provider ..."; each unset/blank env var ⇒ reason
    #   naming the variable (never its value). Each non-existent file ⇒ reason naming the path.
```
**Why**: spec §4 requires skips before provider initialisation and counting at the client boundary; this
block holds every decision the live test (TASK-3879) needs, in testable functions.

### `examples/planogram/e2e/runner.py` (CREATE) — block 3: run, compare, project (same file, appended)
```python
def _build_client(case: LiveCase) -> Any:
    """Create the real provider client from the explicit ``provider:model`` backend."""
    return LLMFactory.create(case.backend)


def ground_truth_assertions(result: Mapping[str, Any], truth: GroundTruth) -> list[dict[str, Any]]:
    """Evaluate every labelled expectation; each item is {"check", "passed", "detail"}."""
    # FILL IN: score (finite, |score - truth.overall_score| <= score_tolerance), coverage (finite, not None,
    #   >= min_coverage), identity errors vs expected_positions (missing facing_id counts as an error),
    #   occupancy errors vs expected_occupancy ("unknown" labels skipped; unobserved statuses count as errors),
    #   one assertion per expected_rules entry (missing or assessed=False ⇒ failed). Positions come from
    #   result["position_results"], rules from result["shelf_scores"][*].rule_results; accept objects or dicts.
    #   Occupied statuses: MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, INFERRED_PRESENT,
    #   OCCUPIED_UNASSIGNED, UNEXPECTED_OCCUPIED; empty: EMPTY, EXPECTED_EMPTY; everything else unknown.


def compare_ground_truth(result: Mapping[str, Any], truth: GroundTruth) -> list[str]:
    """Return explicit violations; never silently widen tolerances or accept missing assertions."""
    return [item["detail"] for item in ground_truth_assertions(result, truth) if not item["passed"]]


def to_json_safe(value: Any) -> Any:
    """Project a run() result to JSON: drop PIL images and bytes, stringify Path/Enum, null nonfinite floats."""
    # FILL IN: recurse BaseModel (model_dump() python mode, then recurse), Mapping, list/tuple; Image.Image and
    #   bytes ⇒ None; Path ⇒ str; Enum ⇒ .value; float not finite ⇒ None.


async def run_case(case: LiveCase) -> dict[str, Any]:
    """Run one configured case and save JSON-safe evidence/renders with bounded uncached requests."""
    # FILL IN (order matters — validation before any client exists):
    #   1. truth = GroundTruth.model_validate_json(await asyncio.to_thread(case.ground_truth_path.read_text))
    #   2. config = json.loads(config text); config["planogram_type"] != case.planogram_type ⇒ ValueError
    #      (wrong type fails); resolve relative slots_definition / reference_images paths against config_path.parent.
    #   3. verdict = check_row(config); not verdict.ok ⇒ ValueError listing verdict.problems.
    #   4. counting = CountingClient(_build_client(case), case.max_provider_requests);
    #      pipeline = PlanogramCompliance(planogram_config=PlanogramConfig.model_validate(config),
    #      llm=counting, vision_cache_dir=case.cache_dir) — explicit model, persistent cache.
    #   5. mkdir output/cache dirs; count "*.json" in cache_dir before/after; await asyncio.wait_for(
    #      pipeline.run([str(p) for p in case.photos], output_dir=case.output_dir), case.timeout_seconds);
    #      on TimeoutError record a "timed out" failed assertion and an empty result.
    #   6. assertions = ground_truth_assertions(...); append failed assertions for counting.exhausted.
    #   7. write output_dir/"compliance.json" (to_json_safe(result)) and output_dir/"report.json" with: case_id,
    #      planogram_type, backend, resolved_backend, config sha256, layout_profile (config["planogram_config"]
    #      .get("layout_profile")), photo sha256 by file name, IDENTIFY_PROMPT_VERSION, reference selection
    #      (whatever key TASK-3871's result exposes for it — grep plan.py `_assemble`; null if none), provider
    #      requests / cap / exhausted, cache entries before/after, render overlay paths, errors, assertions.
    #   8. return {"case_id", "violations", "provider_requests", "report_path", "compliance_path"}.
```
**Why this shape**: the spec fixes `run_case(case)` and `compare_ground_truth(result, truth)`; the client
factory stays a module-level function so offline tests can monkeypatch `_build_client` and
`PlanogramCompliance` without a real provider. Timeouts and budget exhaustion are recorded as failed
assertions (with evidence written) rather than raised, so every run leaves a report.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py` (CREATE)
See **Test Specification** below — write that scaffold, completing every `# FILL IN`.

### FILL IN checklist
- [ ] `models.py::GroundTruth._check_labels_and_bounds` — empty labels, finiteness, [0,1] ranges, budgets ≥ 0; spec §4
- [ ] `models.py::LiveCase._check_case` — case/type pairing, explicit backend, positive limits; spec §4
- [ ] `models.py::LiveManifest._check_namespaces` — unique ids, disjoint cache/output dirs; spec §7
- [ ] `runner.py::_load_models`, `CountingClient._charge`, `load_manifest`, `missing_prerequisites`
- [ ] `runner.py::ground_truth_assertions`, `to_json_safe`, `run_case` — AC17, spec §4 report contents

---

## Acceptance Criteria

- [ ] AC18: `git check-ignore` admits exactly the five harness files and keeps synthetic manifest/photo/config/
      definition/ground-truth/cache/render/report names ignored (asserted by the new test module).
- [ ] AC17: models validate case↔type pairing, explicit `provider:model`, 64-request / 600 s defaults, tolerance
      bounds and non-empty labels; malformed manifests fail.
- [ ] AC17: cache hits consume no request budget; exceeding the cap sets `exhausted` and becomes a violation.
- [ ] AC17: `run_case` validates truth, type and `check_row` before creating a client, writes JSON-safe
      `compliance.json` + `report.json` with the §4 report fields, and records timeouts as violations.
- [ ] `compare_ground_truth` counts missing expected ids as errors and flags nonfinite scores.
- [ ] No import from `examples/planogram/pipelines/` or `examples/pipelines/`; no retailer data committed.
- [ ] `ruff check` and `black --check --line-length 120` pass on the three Python files.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py -q`

Also run these gates (kept out of the bullet list because the task-graph linter accepts only pytest bullets):
`ruff check examples/planogram/e2e/models.py examples/planogram/e2e/runner.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py`  
`black --check --line-length 120 examples/planogram/e2e/models.py examples/planogram/e2e/runner.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py`  

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py
"""Offline tests for the planogram live E2E harness (FEAT-612, spec Module 14). Synthetic data only."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
E2E_DIR = REPO_ROOT / "examples" / "planogram" / "e2e"

ADMITTED = [f"examples/planogram/e2e/{n}" for n in
            ("conftest.py", "models.py", "runner.py", "test_compliance.py", "README.md")]
IGNORED = [
    "examples/planogram/e2e/manifest.json",
    "examples/planogram/e2e/private/store_photo.jpg",
    "examples/planogram/e2e/cases/shelves/config.json",
    "examples/planogram/e2e/cases/shelves/definition.json",
    "examples/planogram/e2e/ground_truth.json",
    "examples/planogram/e2e/cache/0123abcd.json",
    "examples/planogram/e2e/out/shelves/compliance.json",
    "examples/planogram/e2e/out/shelves/report.json",
    "examples/planogram/e2e/out/shelves/compliance_render.png",
    "examples/planogram/e2e/plan.pdf",
    "examples/planogram/e2e/local_helper.py",
]


@pytest.fixture(scope="module")
def harness():
    """Load models.py and runner.py by path (examples/ is not a package); pop both on teardown."""
    # FILL IN: load models.py as "planogram_e2e_models" first, then runner.py as "planogram_e2e_runner"
    #   (test_backend_benchmark.py:16-26 pattern); yield the runner module; sys.modules.pop both names.


def _is_ignored(path: str) -> bool: ...  # FILL IN: copy test_plancheck_gitignore.py:_is_ignored with REPO_ROOT


@pytest.mark.parametrize("path", ADMITTED)
def test_gitignore_admits_harness_files(path): ...          # assert not _is_ignored(path)

@pytest.mark.parametrize("path", IGNORED)
def test_gitignore_keeps_private_material_ignored(path): ... # assert _is_ignored(path)

def test_opt_in_default_off(harness): ...
    # opt_in_enabled({}) is False; {"PARROT_TEST_REAL_LLM": "0"} False; "1" True

def test_missing_prerequisites_names_files_and_env(harness, tmp_path): ...
    # case with nonexistent photo/config/truth + required_env {"google": ["FAKE_KEY_VAR"]} and environ {}
    # ⇒ 4 reasons, each naming the path / variable; all present ⇒ []; provider absent from required_env ⇒ 1 reason

def test_live_case_rejects_wrong_type_and_implicit_model(harness, tmp_path): ...
    # LiveCase(case_id="shelves", planogram_type="ink_wall", ...) ⇒ ValidationError;
    # backend="google" (no model) ⇒ ValidationError; defaults 64 and 600.0 on a valid case

def test_malformed_manifest_fails(harness, tmp_path): ...
    # invalid JSON ⇒ json.JSONDecodeError; unknown key ⇒ ValidationError; duplicate case_id or shared
    # output_dir ⇒ ValidationError; relative paths resolve against the manifest directory

def test_ground_truth_missing_labels_and_bounds(harness): ...
    # missing expected_rules key ⇒ ValidationError; all three maps empty ⇒ ValidationError;
    # score_tolerance=1.5, min_coverage=-0.1, max_identity_errors=-1, overall_score=float("nan") ⇒ ValidationError

def test_compare_passes_within_tolerance(harness): ...
    # canned result (dict position_results/shelf_scores) matching truth ± tolerance ⇒ []

def test_compare_flags_nonfinite_and_missing_ids(harness): ...
    # overall_compliance_score=float("nan") ⇒ a violation mentioning the score; expected facing id absent
    # from position_results ⇒ identity error counted (violation when > max_identity_errors); coverage None ⇒ violation

def test_compare_unassessed_rule_is_violation(harness): ...
    # rule_results [{"rule_id": "r1", "assessed": False, "passed": None}] with expected_rules {"r1": True} ⇒ violation

async def test_cache_hit_consumes_no_budget(harness, fake_vision_client, tmp_path): ...
    # VisionAdapter(harness.CountingClient(fake_vision_client, 5), ResolvedBackend(provider="fake", model="m",
    # origin="llm_instance"), semaphore=asyncio.Semaphore(1), cache_dir=tmp_path); queue one '{"value": 1}'
    # answer; ask twice with identical encode_png(...) bytes ⇒ counting.requests == 1

async def test_budget_exhaustion_is_recorded(harness, fake_vision_client): ...
    # CountingClient(max_requests=1): first ask_to_image ok, second raises RequestBudgetExceeded; exhausted is True

async def test_run_case_rejects_wrong_config_type_before_client(harness, tmp_path, monkeypatch): ...
    # config JSON planogram_type "ink_wall" for the shelves case ⇒ ValueError; monkeypatched _build_client
    # that calls pytest.fail proves no client was created

async def test_run_case_writes_json_safe_report(harness, tmp_path, monkeypatch, fake_vision_client): ...
    # monkeypatch harness.check_row ⇒ ok PreflightRow; harness._build_client ⇒ fake_vision_client;
    # harness.PlanogramCompliance ⇒ stub whose run() calls llm.ask_to_image twice and returns a canned result
    # incl. RenderRecord(rendered_image=PIL image) and a nan strict score ⇒ compliance.json/report.json parse
    # with json.loads, contain no PIL repr, report["provider_requests"] == 2, prompt_version present,
    # photo fingerprints keyed by file name

async def test_run_case_timeout_is_a_violation(harness, tmp_path, monkeypatch): ...
    # stub run() awaits asyncio.sleep(10) and timeout_seconds=0.05 ⇒ outcome["violations"] mentions a timeout
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`); new files under
   `examples/planogram/e2e/` are admitted by the `.gitignore` edit, so plain `git add` works — if it
   reports them ignored, the `.gitignore` block is wrong: fix it, never `git add -f`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3878 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean.

