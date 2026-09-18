# TASK-3447: Handler hydrates new config columns, drops GoogleGenAIClient, adds assessment metadata

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3443
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 18**, goals G2, G11, G12, G14. `PlanogramComplianceHandler`
(`POST /api/v1/planogram/compliance`) is the production entry point. Today it
hard-codes a Google client (`GoogleGenAIClient(model=DEFAULT_LLM_MODEL)`),
reads only the legacy DB columns and returns no way to tell an *incomplete*
assessment from observed non-compliance. After the `run()` template lands
(TASK-3443) the pipeline resolves its own backend and returns the additive
keys; this task makes the handler use them. The handler stays single-file
upload.

---

## Scope

- `_build_planogram_config` additionally hydrates `slots_definition` and
  `llm_backend` from the row. A JSONB value may arrive as a `str` depending on
  the driver codec — decode it with `json.loads` when it is a string.
- Tolerate `NULL` prompts: pass `None` (not `""`) for
  `roi_detection_prompt` / `object_identification_prompt` when the column is
  null or absent.
- `run_compliance`: remove the lazy `GoogleGenAIClient` import and the
  `llm=` argument; construct `PlanogramCompliance(planogram_config=_config)` so
  the backend is resolved from `llm_backend` / package default. Remove the now
  unused `DEFAULT_LLM_MODEL` import.
- Response gains `assessment_status`, `coverage`, `errors`; the five existing
  keys are unchanged.
- A construction `ValueError` (missing / invalid slots, missing legacy prompts)
  must surface as a **failed job carrying the message** — not a 500. Keep the
  construction **inside** `run_compliance` so `JobManager._run_job` records it.
- Update the two existing tests that patch `GoogleGenAIClient`; add tests for
  the new behaviour.

**NOT in scope**: multi-file upload; the ALTER script / `table.sql` (config
task); any change to `_fetch_planogram_config`'s SQL (`SELECT *` already returns
new columns); SSE / job plumbing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` | MODIFY | hydrate new columns, null prompts, no Google client, additive response keys |
| `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` | MODIFY | drop `GoogleGenAIClient` patches; new tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# handlers/planogram_compliance.py — current header (verified :3-19)
import asyncio, base64, shutil, tempfile, uuid
from pathlib import Path
from typing import Any, Optional
from aiohttp import web
from navigator.views import BaseView
from parrot.conf import PLANOGRAM_FOLDER, DEFAULT_LLM_MODEL          # :16  → becomes: PLANOGRAM_FOLDER only
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry   # :17
from parrot_pipelines.planogram.plan import PlanogramCompliance       # :18
from parrot.handlers.jobs import JobManager, JobStatus                # :19
# to ADD
import json
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py  (362 lines,
#   sha256 459a7c40d19b981aa6357e96c0db16144647b398b3bdbe0cc46a2e1ad8c880f6 at task-writing time)
class PlanogramComplianceHandler(BaseView):                                    # :28
    async def post(self) -> web.Response                                       # :79-194
        # nested: async def run_compliance() -> dict[str, Any]                 # :139-184
        #   :144 from parrot.clients.google import GoogleGenAIClient   (lazy)
        #   :146 llm = GoogleGenAIClient(model=DEFAULT_LLM_MODEL)
        #   :147 pipeline = PlanogramCompliance(planogram_config=_config, llm=llm)
        #   :148-151 result = await pipeline.run(image=_image_path, output_dir=str(_tmp_dir))
        #   :161-166 serialisable = {overall_compliant, overall_compliance_score, rendered_image_base64, content_type}
        #   :168-179 shelf_results via model_dump()/to_dict()/dict/str
        #   :182-184 finally: shutil.rmtree(_tmp_dir)
        # :186 await self.job_manager.execute_job(job.job_id, run_compliance)
    async def _fetch_planogram_config(self, config_name: str) -> Optional[dict]    # :284-294  (SELECT * … LIMIT 1)
    def _build_planogram_config(self, row: dict) -> PlanogramConfig            # :296-333
        # :327 roi_detection_prompt=row.get("roi_detection_prompt", ""),
        # :328 object_identification_prompt=row.get("object_identification_prompt", ""),
        # :331 detection_model=row.get("detection_model", "yolo11l.pt"),

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py
class JobManager:
    async def _run_job(self, job_id, execution_func) -> None                   # :228-272
        # any Exception from execution_func ⇒ job.status = JobStatus.FAILED; job.error = str(exc)   :264-269
        # ⇒ a ValueError raised INSIDE run_compliance already becomes a failed job with its message.

# packages/ai-parrot/tests/handlers/test_planogram_compliance.py  (531 lines)
#   fixture planogram_db_row() -> dict                                          :62-84 (no slots_definition / llm_backend keys)
#   patch("parrot_pipelines.handlers.planogram_compliance.GoogleGenAIClient", …)   :212 and :486  ← REMOVE both
#   patch("parrot_pipelines.handlers.planogram_compliance.PlanogramCompliance", …) :216 and :490  ← keep
#   fake_result dict :468-475; mock_llm_instance / mock_llm_class :481-482  ← REMOVE
```

```python
# Created by TASK-3426 (dependency, via TASK-3443) — parrot_pipelines/models.py PlanogramConfig
roi_detection_prompt: Optional[str] = None
object_identification_prompt: Optional[str] = None
slots_definition: Optional[Union[Dict[str, Any], str, Path]] = None
llm_backend: Optional[str] = None            # "provider:model"; invalid string ⇒ ValidationError
# Created by TASK-3443 (dependency) — run() additive result keys used here
result["assessment_status"]  # "complete" | "inconclusive" | "legacy_unmeasured"
result["coverage"]           # Optional[float]
result["errors"]             # List[str]
```

### Does NOT Exist
- ~~a module-level `GoogleGenAIClient` name in the handler module~~ — the import is lazy inside `run_compliance` (:144). The two test patches target a non-existent attribute; delete them rather than adding `create=True`.
- ~~`planogram_type` / `slots_definition` / `llm_backend` in the `planogram_db_row` fixture~~ — add keys per test, do not assume them.
- ~~`detection_grid` hydration~~ — never read from the row; out of scope.
- ~~a 4xx path for construction errors~~ — the pipeline is built in the background job; the HTTP response is already `202`. Failure is reported through the job (`status="failed"`, `error=<message>`).
- ~~`result["resolved_backend"]` in the HTTP response~~ — not part of the Module 18 contract; do not add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/handlers/test_planogram_compliance.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler.post",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler._build_planogram_config",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager._run_job"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Keep pipeline construction inside `run_compliance` — that is what turns a
  construction `ValueError` into a failed job (`job.py:264-269`) instead of a
  500 from `post()`.
- `json.loads` guard: only when `isinstance(value, str)`; a malformed string
  must raise (it is then caught by the existing `except Exception` at
  `post()` :119-123 → "Failed to build planogram configuration", status 500 —
  acceptable: a corrupt DB value is a server-side data error).

### Key Constraints
- The five existing response keys keep name, type and meaning.
- After this task the handler file must contain neither `GoogleGenAIClient`
  nor `DEFAULT_LLM_MODEL`.
- Run the tests with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src:packages/ai-parrot-server/src`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:228-272` — failure handling
- `packages/ai-parrot/tests/handlers/test_planogram_compliance.py:440-531` — the end-to-end job test to extend

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Edit the imports (`json` in, `DEFAULT_LLM_MODEL` out) — *why*: the literal-free handler is an acceptance criterion of the feature.
2. Replace the client construction in `run_compliance` — *why*: backend selection now belongs to the pipeline (spec §2 "Backend selection").
3. Add the three response keys — *why*: G14, incomplete ≠ non-compliant.
4. Extend `_build_planogram_config` — *why*: G9/G12 columns must reach `PlanogramConfig`.
5. Fix and extend the tests, run the Validation Command.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.conf import PLANOGRAM_FOLDER, DEFAULT_LLM_MODEL' planogram_compliance.py)
# REPLACE line :16 with
from parrot.conf import PLANOGRAM_FOLDER
# and add `import json` after `import base64` (verified: planogram_compliance.py:6, occurrences: 1)

# occurrences: 1 each (verified: grep -c) —
#   '                from parrot.clients.google import GoogleGenAIClient'          :144
#   '                pipeline = PlanogramCompliance(planogram_config=_config, llm=llm)'   :147
# REPLACE lines :142-147 (the FEAT-523 comment, the lazy import, `llm = …`, `pipeline = …`) with
                # FEAT-574: provider/model come from PlanogramConfig.llm_backend or the
                # package default — the handler no longer builds a provider client.
                pipeline = PlanogramCompliance(planogram_config=_config)

# occurrences: 1 (verified: grep -c '                    "content_type": content_type,' planogram_compliance.py)
# AFTER — insert below `                    "content_type": content_type,` (verified: :165)
                    "assessment_status": result.get("assessment_status"),
                    "coverage": result.get("coverage"),
                    "errors": list(result.get("errors") or []),

# occurrences: 1 (verified: grep -c '            roi_detection_prompt=row.get("roi_detection_prompt", ""),' planogram_compliance.py)
# REPLACE lines :327-328 with
            roi_detection_prompt=row.get("roi_detection_prompt") or None,
            object_identification_prompt=row.get("object_identification_prompt") or None,

# occurrences: 1 (verified: grep -c '            detection_model=row.get("detection_model", "yolo11l.pt"),' planogram_compliance.py)
# AFTER — insert below `            detection_model=row.get("detection_model", "yolo11l.pt"),` (verified: :331)
            slots_definition=self._decode_json_column(row.get("slots_definition")),
            llm_backend=row.get("llm_backend") or None,

# AFTER — add as a new method directly below `_build_planogram_config` (it ends at :333)
    @staticmethod
    def _decode_json_column(value: Any) -> Any:
        """Return a JSONB column value as a Python object.

        Args:
            value: dict (decoded by the driver), JSON string, or None.

        Returns:
            The decoded object, or None when the column is NULL/empty.

        Raises:
            ValueError: When a string value is not valid JSON.
        """
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value
```
**Why**: every edit is anchored on a line that occurs exactly once. `or None`
(instead of a `""` default) is what lets the type's construction-time
validation say "prompt missing" for a legacy type, and lets migrated types run
with NULL prompts (G10). `json.JSONDecodeError` is a `ValueError` subclass, so
the docstring's `Raises` holds without extra code.

### `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '"parrot_pipelines.handlers.planogram_compliance.GoogleGenAIClient",' test file → :212, :486)
# FILL IN: disambiguate — site 1 is inside `test_post_valid_request` (the `with (patch(...), patch(...)):`
#   block at :210-221): delete the first `patch(...)` (lines :211-214) and keep the PlanogramCompliance patch.
#   Site 2 is in the end-to-end job test (:481-493): delete `mock_llm_instance`, `mock_llm_class`, `p1`
#   and its `p1.start()` / `p1.stop()` calls; keep `p2`.
# Then extend `fake_result` (:468-475) with:
            "assessment_status": "complete",
            "coverage": 1.0,
            "errors": [],
# and add the new tests listed in the Test Specification at the end of the relevant test classes.
```
**Why**: the patched attribute never existed at module scope (the import is
lazy), so the patches must go — do not paper over them with `create=True`.

### FILL IN checklist
- [ ] test file — remove both `GoogleGenAIClient` patch sites using the surrounding context above
- [ ] new tests — bodies per Test Specification
- [ ] confirm `grep -c "GoogleGenAIClient\|DEFAULT_LLM_MODEL"` on the handler is `0`

---

## Acceptance Criteria

- [ ] Handler module contains neither `GoogleGenAIClient` nor `DEFAULT_LLM_MODEL`.
- [ ] `PlanogramCompliance` is constructed with `planogram_config` only (no `llm=`).
- [ ] `_build_planogram_config` passes `slots_definition` (dict, or decoded from a JSON string) and `llm_backend`; NULL/absent prompts become `None`.
- [ ] Job result keeps `overall_compliant`, `overall_compliance_score`, `rendered_image_base64`, `content_type`, `shelf_results` and adds `assessment_status`, `coverage`, `errors`.
- [ ] A `ValueError` raised by `PlanogramCompliance(...)` yields `JobStatus.FAILED` with the message in `job.error`; the POST still answers `202`.
- [ ] Handler stays single-file upload.
- [ ] `pytest packages/ai-parrot/tests/handlers/test_planogram_compliance.py -q` passes.
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/handlers/test_planogram_compliance.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_planogram_compliance.py  (additions)

def test_build_config_hydrates_new_columns(planogram_db_row, job_manager):
    row = {**planogram_db_row, "slots_definition": {"version": 1, "shelves": []},
           "llm_backend": "anthropic:claude-sonnet-5"}
    config = _make_handler(job_manager)._build_planogram_config(row)
    assert config.slots_definition == {"version": 1, "shelves": []}
    assert config.llm_backend == "anthropic:claude-sonnet-5"


def test_build_config_decodes_json_string(planogram_db_row, job_manager):
    row = {**planogram_db_row, "slots_definition": '{"version": 1, "shelves": []}'}
    assert _make_handler(job_manager)._build_planogram_config(row).slots_definition["version"] == 1


def test_build_config_null_prompts(planogram_db_row, job_manager):
    row = {**planogram_db_row, "roi_detection_prompt": None, "object_identification_prompt": None}
    config = _make_handler(job_manager)._build_planogram_config(row)
    assert config.roi_detection_prompt is None and config.object_identification_prompt is None


def test_handler_module_has_no_google_client():
    import parrot_pipelines.handlers.planogram_compliance as mod
    assert not hasattr(mod, "GoogleGenAIClient") and not hasattr(mod, "DEFAULT_LLM_MODEL")


@pytest.mark.asyncio
async def test_job_result_has_additive_fields(planogram_db_row, job_manager):
    """End-to-end job: result carries assessment_status / coverage / errors + the five legacy keys;
    PlanogramCompliance was called with planogram_config only (assert 'llm' not in call kwargs)."""


@pytest.mark.asyncio
async def test_construction_value_error_fails_job(planogram_db_row, job_manager):
    """PlanogramCompliance mock raises ValueError('slots_definition missing') → POST 202,
    job.status == JobStatus.FAILED and 'slots_definition missing' in job.error."""
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
7. **Move this file** to `tasks/completed/TASK-3447-handler-update.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
