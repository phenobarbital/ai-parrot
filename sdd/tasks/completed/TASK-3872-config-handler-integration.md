# TASK-3872: PlanogramConfig descriptions and handler reference-list hydration

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3871
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (handler skeleton), §2 compatibility policy ("Legacy prompts, detector
model/confidence and `detection_grid` are accepted and ignored for one release"), §6 Corrections
("planogram type examples mention tv_wall — fix model description without inventing a seventh
type"; "reference images already fully hydrate — model permits lists, but handler
`handlers/planogram_compliance.py:312` coerces every value to Path. M11 handles path lists") and §7
Known Risks ("Retained config fields suggest active behavior → mark accepted-but-ignored in model
descriptions"). After TASK-3871 the orchestrator requires a definition and uses reference lists
through the per-run reference bank, so the handler must hydrate path-list references and the model
must document which legacy columns are inert. The HTTP contract and `PlanogramCompliance(planogram_config=...)`
invocation stay byte-for-byte compatible (AC2).

---

## Scope

- `models.py`: rewrite `description=` text only — `planogram_type` (drop `tv_wall`, list the six
  registered keys), `planogram_config` (mention `layout_profile` / `rule_bindings`), `reference_images`
  (reference bank semantics), `slots_definition` (required at runtime; runbook path), and mark
  `roi_detection_prompt`, `object_identification_prompt`, `confidence_threshold`, `detection_model`,
  `detection_grid` as accepted-but-ignored. **No field is added, removed, retyped or re-defaulted.**
- `handlers/planogram_compliance.py`: `_build_planogram_config` hydrates each reference value that
  is a path string OR a list of path strings (JSONB column may also arrive as a JSON string);
  extract the per-path resolution into a static helper `_resolve_reference_path`.
- Tests in `packages/ai-parrot/tests/handlers/test_planogram_compliance.py`: list hydration,
  JSON-string column, descriptions, and the job failing fast (real orchestrator) for an unmigrated row.

**NOT in scope**: removing DB columns or model fields (spec §8: keep one release); orchestrator
changes (TASK-3871); converter/preflight (TASK-3877); docs/runbook text (TASK-3880); any change to
the HTTP request/response shape, job manager usage, or `run()` arguments.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` | MODIFY | Field descriptions only (tv_wall removed; accepted-but-ignored legacy fields) |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` | MODIFY | Path and path-list reference hydration |
| `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` | MODIFY | Hydration, description and fail-fast job tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handlers/planogram_compliance.py (already imported — verified)
from pathlib import Path                                         # :11
from typing import Any, Optional                                 # :12
from parrot.conf import PLANOGRAM_FOLDER                         # :17 (Path; parrot/conf.py:126-128)
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry   # :18
from parrot_pipelines.planogram.plan import PlanogramCompliance  # :19
# test file (already imported — verified)
from parrot.handlers.planogram_compliance import PlanogramComplianceHandler   # test :17 (server proxy → parrot_pipelines.handlers)
from parrot.handlers.jobs.models import Job, JobStatus           # test :18
from parrot.handlers.jobs.job import JobManager                  # test :19
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry   # test :20 (core proxy, star re-export)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py
class PlanogramConfig(BaseModel):                                          # :32
    planogram_type: str = Field(default="product_on_shelves", description="... tv_wall)")   # :44-47 (description :46)
    planogram_config: Dict[str, Any] = Field(description=...)              # :50-52
    roi_detection_prompt: Optional[str] = Field(default=None, description=...)            # :55-57
    object_identification_prompt: Optional[str] = Field(default=None, description=...)    # :60-62
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]] = Field(default_factory=dict, ...)  # :65-71
    confidence_threshold: float = Field(default=0.25, description="YOLO detection confidence threshold")   # :74
    detection_model: str = Field(default="yolo11l.pt", description="YOLO model to use for detection")      # :76
    detection_grid: Optional[DetectionGridConfig] = Field(default=None, description=(...))               # :83-89
    slots_definition: Optional[Union[Dict[str, Any], str, Path]] = Field(default=None, description=...)  # :92-95

# packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py (394 lines)
class PlanogramComplianceHandler(BaseView):
    self.logger = logging.getLogger(self._logger_name)                     # :58
    async def post(self) -> web.Response                                   # :88 (build config :126-133 → 500 on any exception)
        pipeline = PlanogramCompliance(planogram_config=_config)           # :153 (inside the background job)
    def _build_planogram_config(self, row: dict) -> PlanogramConfig         # :307
        reference_images_raw: dict = row.get("reference_images") or {}     # :309
        for name, path_str in reference_images_raw.items(): p = Path(path_str) ...   # :311-318 (coerces EVERY value to Path)
        return PlanogramConfig(..., reference_images=reference_images, ...)           # :334-346
    @staticmethod
    def _decode_json_column(value: Any) -> Any                              # :349 (None/"" → None; str → json.loads)

# packages/ai-parrot/tests/handlers/test_planogram_compliance.py (615 lines)
def planogram_db_row() -> dict                                             # :64 fixture (no slots_definition key)
def _make_handler(job_manager, db_row=None, match_info=None)                # :95
class _MockPart:                                                            # :160
async def _run_job(handler, job_manager, pipeline_class)                    # :552 (always patches PlanogramCompliance)
async def test_construction_value_error_fails_job(planogram_db_row, job_manager)   # :609
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3871 — planogram/plan.py
MIGRATION_RUNBOOK = "docs/pipelines/planogram-cycle-migration.md"
# PlanogramCompliance.__init__ raises ValueError(f"PlanogramConfig {config_name!r} ({ptype}) has no slots_definition;
#   convert it as described in {MIGRATION_RUNBOOK}") BEFORE building any client.
```

### Does NOT Exist
- ~~a `tv_wall` planogram type~~ — not in `PlanogramCompliance._PLANOGRAM_TYPES` (plan.py:61-68); only the description mentions it.
- ~~a `layout_profile` model field / DB column~~ — it is a key inside `planogram_config` (spec §2).
- ~~async `_build_planogram_config`~~ — it stays a sync method with the same signature (spec M11 skeleton).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/models.py",
      "action": "MODIFY"
    },
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
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler._build_planogram_config",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler._decode_json_column",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler.post",
    "sym:packages/ai-parrot/tests/handlers/test_planogram_compliance.py#_run_job",
    "sym:packages/ai-parrot/tests/handlers/test_planogram_compliance.py#_make_handler"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Descriptions only in models.py**: changing a type/default would alter stored-row parsing (spec §8:
  accept-and-ignore for one release). Use one consistent phrase:
  `"Accepted and ignored since ai-parrot-pipelines 1.1.0 (FEAT-612); kept one release for stored rows"`.
- **Six registered keys, no seventh**: `product_on_shelves, ink_wall, endcap_backlit_multitier,
  endcap_no_shelves_promotional, graphic_panel_display, product_counter` — verify against
  `plan.py:61-68` before writing.
- **Hydration rules** (keep existing semantics for single paths): absolute path → as is; relative →
  `PLANOGRAM_FOLDER / p`, and if that does not exist `PLANOGRAM_FOLDER / p.name` (existing :313-317). A
  list value maps element-wise and stays a list (order preserved — the reference bank relies on stable
  list order, spec §2 Stage 2). Empty/None entries are skipped with a `self.logger.warning`; a
  non-string element raises `ValueError` naming the key (the existing `post` handler turns build
  failures into HTTP 500 — unchanged contract).
- The row column may arrive as a JSON string (asyncdb returns JSONB as `str` for some drivers) —
  decode it with the existing `_decode_json_column` (:349) before iterating.
- The `.exists()` check stays synchronous, exactly as today (spec keeps the sync method signature).
- **Fail-fast test uses the real orchestrator**: after TASK-3871 the missing-definition `ValueError` is
  raised before `super().__init__`, so no client is created; still patch
  `PlanogramCompliance._get_llm` defensively so a future reordering cannot reach a real provider.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py:307-346` — code to change
- `packages/ai-parrot/tests/handlers/test_planogram_compliance.py:552-615` — job-run helpers and fail test to mirror
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py:356-365` — how `_get_llm` is patched

---

## Implementation Blueprint

### Steps (in order)
1. Edit the eight `description=` strings in `models.py` — *why*: AC19 precursor and §7 "retained config fields suggest active behavior".
2. Replace `_build_planogram_config`'s reference loop (:308-318) and add `_resolve_reference_path` — *why*: :312 coerces lists to `Path`, breaking list references (§6 Corrections).
3. Add tests; make `_run_job`'s `pipeline_class` optional (None = no patch) — *why*: the fail-fast test must exercise the real `PlanogramCompliance`.
4. Run Validation Commands — *why*: AC2/AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class PlanogramConfig(BaseModel):' packages/ai-parrot-pipelines/src/parrot_pipelines/models.py → :32)
# REPLACE description text only (keep Field defaults/types), at the verified lines:
# :46  planogram_type
        description=(
            "Registered planogram type: product_on_shelves, ink_wall, endcap_backlit_multitier, "
            "endcap_no_shelves_promotional, graphic_panel_display or product_counter"
        ),
# :51  planogram_config
        description=(
            "Planogram configuration dictionary (converted to PlanogramDescription); may carry 'layout_profile' "
            "overrides of the type's default LayoutProfile and 'rule_bindings'"
        )
# :56 roi_detection_prompt, :61 object_identification_prompt, :74 confidence_threshold, :76 detection_model,
# :86-87 detection_grid → each description becomes
#   "<old short purpose>. Accepted and ignored since ai-parrot-pipelines 1.1.0 (FEAT-612); kept one release for stored rows"
# :67-68 reference_images →
#   "Local reference images per catalogue key: a path, a list of paths or a PIL image. Loaded once per run into the "
#   "identification reference bank (opaque labels; never used as expected placement)."
# :94 slots_definition →
#   "Shelves/slots/zones definition (dict or JSON file path). Required at runtime; convert legacy rows as described "
#   "in docs/pipelines/planogram-cycle-migration.md"
```
**Why**: spec §2 compatibility policy + §6 tv_wall correction; one sentence per field keeps
`model_json_schema()` readable for API consumers.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '    def _build_planogram_config(self, row: dict) -> PlanogramConfig:' …/planogram_compliance.py → :307)
# REPLACE lines :308-318 (docstring + reference loop) →
        """Hydrate a PlanogramConfig from a database row dict (single-path or path-list references)."""
        reference_images_raw = self._decode_json_column(row.get("reference_images")) or {}
        reference_images: dict[str, Path | list[Path]] = {}
        for name, value in reference_images_raw.items():
            if isinstance(value, (list, tuple)):
                paths = [self._resolve_reference_path(name, item) for item in value if item]
                if paths:
                    reference_images[name] = paths
                else:
                    self.logger.warning("Planogram reference %r has an empty path list; skipped", name)
            elif value:
                reference_images[name] = self._resolve_reference_path(name, value)
            else:
                self.logger.warning("Planogram reference %r has no path; skipped", name)

# AFTER — insert below the end of _build_planogram_config (before `    @staticmethod` of _decode_json_column, verified :348-349)
    @staticmethod
    def _resolve_reference_path(name: str, value: Any) -> Path:
        """Resolve one reference path: absolute as is, else under PLANOGRAM_FOLDER (full relative path, then basename).

        Args:
            name: Catalogue key (for the error message).
            value: Path string or Path.

        Returns:
            The resolved path.

        Raises:
            ValueError: ``value`` is not a string or Path.
        """
        if not isinstance(value, (str, Path)):
            raise ValueError(f"reference image {name!r}: path must be a string, got {type(value).__name__}")
        path = Path(value)
        if not path.is_absolute():
            resolved = PLANOGRAM_FOLDER / path
            if not resolved.exists():
                resolved = PLANOGRAM_FOLDER / path.name
            path = resolved
        return path
```
**Why**: keeps the single-path resolution byte-identical (moved into a helper) and adds element-wise
lists; `PlanogramConfig.reference_images` already accepts `List[Path]` (models.py:65).

### `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class _MockPart:' packages/ai-parrot/tests/handlers/test_planogram_compliance.py → :160)
# CHANGE _run_job (:552) signature to `async def _run_job(handler, job_manager, pipeline_class=None)` and start the
# patcher only when pipeline_class is not None (both existing callers keep passing a class).
# APPEND the tests from the Test Specification at the end of the file.
```
**Why**: the existing helper always replaces `PlanogramCompliance`; the fail-fast assertion must hit the real one.

### FILL IN checklist
- [ ] Exact description sentences — bounded by "no field/default/type change".
- [ ] Test bodies — AC2/AC10.

---

## Acceptance Criteria

- [ ] `PlanogramConfig.model_fields["planogram_type"].description` names the six registered types and not `tv_wall`; defaults and types of every field are unchanged (compare `PlanogramConfig.model_json_schema()["properties"][f].get("default")` before/after).
- [ ] The five legacy fields' descriptions contain "Accepted and ignored".
- [ ] A row with `{"A": ["/abs/a.jpg", "rel/b.jpg"]}` hydrates to `[Path("/abs/a.jpg"), PLANOGRAM_FOLDER / "rel/b.jpg" | PLANOGRAM_FOLDER / "b.jpg"]`; single-path rows hydrate exactly as before (existing `test_build_planogram_config` passes unchanged).
- [ ] A JSON-string `reference_images` column is decoded; empty entries are skipped.
- [ ] POST for an unmigrated row (no `slots_definition`) returns 202 and the job ends FAILED with an error containing the config name and `planogram-cycle-migration.md` (AC2, AC10).
- [ ] `PlanogramCompliance` is still called with exactly `planogram_config=` (existing `test_job_result_has_additive_fields` passes).
- [ ] `pytest packages/ai-parrot/tests/handlers/test_planogram_compliance.py -q` passes.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/models.py packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py packages/ai-parrot/tests/handlers/test_planogram_compliance.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/models.py packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py packages/ai-parrot/tests/handlers/test_planogram_compliance.py`

## Validation Commands

- `pytest packages/ai-parrot/tests/handlers/test_planogram_compliance.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q`

---

## Test Specification

```python
# appended to packages/ai-parrot/tests/handlers/test_planogram_compliance.py

def test_build_config_hydrates_reference_lists(planogram_db_row, job_manager, tmp_path, monkeypatch):
    import parrot_pipelines.handlers.planogram_compliance as handler_module

    monkeypatch.setattr(handler_module, "PLANOGRAM_FOLDER", tmp_path)
    (tmp_path / "rel").mkdir()
    (tmp_path / "rel" / "b.jpg").write_bytes(b"x")
    row = {**planogram_db_row, "reference_images": {"A": ["/abs/a.jpg", "rel/b.jpg", ""], "B": "c.jpg"}}
    config = _make_handler(job_manager)._build_planogram_config(row)
    assert config.reference_images["A"] == [Path("/abs/a.jpg"), tmp_path / "rel" / "b.jpg"]
    assert config.reference_images["B"] == tmp_path / "c.jpg"


def test_build_config_decodes_json_reference_column(planogram_db_row, job_manager):
    row = {**planogram_db_row, "reference_images": '{"A": ["/abs/a.jpg"]}'}
    assert _make_handler(job_manager)._build_planogram_config(row).reference_images["A"] == [Path("/abs/a.jpg")]


def test_build_config_rejects_non_path_reference(planogram_db_row, job_manager):
    row = {**planogram_db_row, "reference_images": {"A": [42]}}
    with pytest.raises(ValueError, match="'A'"):
        _make_handler(job_manager)._build_planogram_config(row)


def test_model_descriptions_are_current():
    fields = PlanogramConfig.model_fields
    assert "tv_wall" not in fields["planogram_type"].description
    for name in ("roi_detection_prompt", "object_identification_prompt", "confidence_threshold",
                 "detection_model", "detection_grid"):
        assert "Accepted and ignored" in fields[name].description
    assert fields["confidence_threshold"].default == 0.25 and fields["detection_model"].default == "yolo11l.pt"


@pytest.mark.asyncio
async def test_unmigrated_row_fails_job_fast(planogram_db_row, job_manager, monkeypatch):
    """Real orchestrator: no slots_definition → 202, job FAILED naming config + runbook, no provider client."""
    from parrot_pipelines.planogram.plan import PlanogramCompliance

    monkeypatch.setattr(PlanogramCompliance, "_get_llm", lambda self, provider, model, **kw: MagicMock())
    response, job = await _run_job(_make_handler(job_manager, db_row=planogram_db_row), job_manager)
    assert response.status == 202
    assert job.status == JobStatus.FAILED
    assert "BOSE S1 Pro+ Planogram" in job.error and "planogram-cycle-migration.md" in job.error
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
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3872 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean.

