---
id: FW-003
query_id: Q003
type: wiki_query
intent: "Locate the FlowTask PlanogramCompliance component that consumes the pipeline (flowtask namespace)."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-003 — FlowTask `PlanogramCompliance` (as indexed and as on disk) targets the new cycle only: a row without `slots_definition` raises ConfigError

## Summary

The component lives in the sibling repo at `flowtask/components/PlanogramCompliance.py` (955 lines on disk). It
loads the row with `SELECT * FROM <planogram_config_table> WHERE config_name = $1`, rejects inactive rows, and
`_build_planogram_config` raises `ConfigError` when `slots_definition` is absent, pointing at the ai-parrot
migration runbook. It imports `parrot_pipelines.planogram.plan.PlanogramCompliance` as the pipeline, so its
current code targets the perceive/identify/compare cycle only; the sole legacy accommodation is reading
`compliance_results` with a fallback to the `step3_compliance_results` key. `planogram_type` comes from the row,
falling back to the task YAML value and then `product_on_shelves`; `roi_detection_prompt` and
`object_identification_prompt` are still forwarded into `PlanogramConfig`.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 15-24
  symbol: `_MIGRATION_RUNBOOK`
  wiki: `flowtask::file:flowtask/components/PlanogramCompliance.py` (Q002 score 0.83, Q009 score 1.00); decision memory `flowtask::mem-6a7fff7f2208` "PlanogramCompliance homologation with ai-parrot FEAT-574"
  excerpt: |
    from parrot_pipelines.models import PlanogramConfig, EndcapGeometry
    from parrot_pipelines.planogram.plan import PlanogramCompliance as PlanogramPipeline
    # ai-parrot runbook for rows still lacking ``slots_definition`` (FEAT-574).
    _MIGRATION_RUNBOOK = 'ai-parrot docs/pipelines/planogram-cycle-migration.md'

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 250-255
  symbol: `PlanogramCompliance._build_planogram_config`
  wiki: `flowtask::sym:flowtask/components/PlanogramCompliance.py#PlanogramCompliance._build_planogram_config` (Q002 score 1.00)
  excerpt: |
    slots_definition = self._decode_json_column(row, 'slots_definition')
    if slots_definition is None:
        raise ConfigError(
            f"Planogram configuration '{self._planogram_name}' has no slots_definition; "
            f"migrate the row as described in {_MIGRATION_RUNBOOK}"
        )

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 262-289
  symbol: `PlanogramCompliance._build_planogram_config`
  excerpt: |
    planogram_type = row.get('planogram_type') or self._planogram_type
    layout_config = self._decode_json_column(row, 'planogram_config') or {}
    ...
    planogram_config = PlanogramConfig(planogram_id=row.get('planogram_id'), config_name=self._planogram_name,
        planogram_type=planogram_type, planogram_config=layout_config, endcap_geometry=geometry,
        roi_detection_prompt=row.get('roi_detection_prompt') or None,
        object_identification_prompt=row.get('object_identification_prompt') or None, ...
        reference_images=references or {}, slots_definition=slots_definition,
        llm_backend=row.get('llm_backend') or None)

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 214
  symbol: `PlanogramCompliance.get_planogram_config`
  excerpt: |
    if row.get('is_active') is False:
        raise ConfigError(f"Planogram configuration '{self._planogram_name}' is inactive")

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 507-516
  symbol: `PlanogramCompliance._compliance_results`
  excerpt: |
    return result.get('compliance_results') or result.get('step3_compliance_results') or []

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 703-739
  symbol: `PlanogramCompliance._execute_pipeline_on_row`
  excerpt: |
    json_report = json.dumps({
        'overall_compliance_score': ..., 'overall_compliant': ...,
        'strict_compliance_score': ..., 'assessment_status': ..., 'coverage': ...,
        'definition_coverage': ..., 'evidence_quality': ..., 'detected_products': ...,
        'detection_source': ..., 'resolved_backend': ..., 'errors': pipeline_errors,
        'products_found': products_found,
        'step3_compliance_results': [{'shelf_level': ..., 'compliance_status': ..., 'compliance_score': ...,
            'expected_products': ..., 'found_products': ..., 'text_compliance_results': [...], 'assessment': ...}]
    }, indent=2, default=str)

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 847-899
  symbol: `PlanogramCompliance._post_process_results`
  wiki: `flowtask::sym:flowtask/components/PlanogramCompliance.py#PlanogramCompliance._post_process_results`
  excerpt: |
    new_cols = {'overall_compliance_score': 0.0, 'overall_compliant': False, 'planogram_id': None,
        'compliance_analysis': "", 'compliance_analysis_markdown': "", 'compliance_analysis_json': "",
        'overlay_image': None, 'compliance_by_shelf': None, 'detections': None, 'products_found': None,
        'overlay_path': ""}

## Notes

- Result keys READ from the pipeline result: `compliance_results` / `step3_compliance_results`,
  `overall_compliance_score`, `overall_compliant`, `strict_compliance_score`, `assessment_status`, `coverage`,
  `definition_coverage`, `evidence_quality`, `detected_products`, `detection_source`, `resolved_backend`,
  `errors`, `products_found`, `rendered_image`, `overlay_path`, `identified_products` (fallback
  `step2_identified_products`). Columns WRITTEN: the eleven in `_post_process_results` above — the seven seen in
  the 2026-03 logs plus `overlay_image`, `compliance_by_shelf`, `detections`, `products_found`.
- The March logs name the legacy pipeline module (`parrot.pipelines.PlanogramCompliance(plan.py:68) :: Starting
  Pure-LLM Planogram Compliance Pipeline`) and log `Row 0: pipeline result keys=` from
  `PlanogramCompliance.py:426`; in the file on disk that debug call sits around L774-777 — i.e. the component
  changed substantially after the ticket was resolved.
- `flowtask::mem-6a7fff7f2208`: "Since ai-parrot FEAT-574 the row MUST carry slots_definition (JSONB) or the
  component raises ConfigError. LLM precedence: task llm_config (explicit Google client) > task llm_backend > row
  llm_backend > ai-parrot package default ... Directory reference images map to key -> [paths]".
- Deprecated task keys `detection_model` / `confidence_threshold` are "accepted and ignored by the pipeline"
  (component class docstring, parameter table, as shown in the wiki page content).
- This lane read the working tree of `/home/jesuslara/proyectos/flowtask` only; which flowtask branch/version that
  is, and which version production runs, was not checked (no git budget).
- [cross-lane: type=git_log, intent=in /home/jesuslara/proyectos/flowtask, which commit/release introduced the slots_definition requirement in components/PlanogramCompliance.py and is it released]
