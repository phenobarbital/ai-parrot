---
id: F018
query_id: Q024, Q003, Q007
type: read
intent: "Follow-up: locate the report markdown renderer and row hydration in the FlowTask PlanogramCompliance component."
executed_at: 2026-11-06T16:05:10Z
duration_ms: 1500
parent_id: F014
depth: 1
lanes: [codebase, wiki]
merged_from: [FC-020, FW-003, FW-006]
---
# F018 — FlowTask builds the report: a shelf prints ✅ only at score 1.0, and rule outcomes are not in the markdown

## Summary

**[F018 · codebase]** The consumer is `flowtask/components/PlanogramCompliance.py` in the sibling repo `/home/jesuslara/proyectos/flowtask` (955 lines, checkout on branch `dev`, file last touched 2026-10-13). `_build_planogram_config` raises `ConfigError` when the row has no `slots_definition`, takes `planogram_type` from the row first and the task YAML second, and loads reference images only when the pipeline says the type uses them. `_create_markdown_report` marks each shelf `✅` only when `compliance_score >= 1.0` (it ignores `compliance_status` and the threshold), prints `Expected Products` / `Found Products`, lists `missing_products` as "Issues", and prints text requirements only if the result has `text_compliance_results`. Per-rule outcomes (`assessment.rule_results`) go only into the JSON report.

**[F018 · wiki]** The component lives in the sibling repo at `flowtask/components/PlanogramCompliance.py` (955 lines on disk). It
loads the row with `SELECT * FROM <planogram_config_table> WHERE config_name = $1`, rejects inactive rows, and
`_build_planogram_config` raises `ConfigError` when `slots_definition` is absent, pointing at the ai-parrot
migration runbook. It imports `parrot_pipelines.planogram.plan.PlanogramCompliance` as the pipeline, so its
current code targets the perceive/identify/compare cycle only; the sole legacy accommodation is reading
`compliance_results` with a fallback to the `step3_compliance_results` key. `planogram_type` comes from the row,
falling back to the task YAML value and then `product_on_shelves`; `roi_detection_prompt` and
`object_identification_prompt` are still forwarded into `PlanogramConfig`.

**[F018 · wiki]** The report shown in the Epson360 UI is built in the FlowTask component, not in ai-parrot:
`PlanogramCompliance._create_markdown_report` prints overall status/score (plus strict score, assessment status
and coverage when present), then one block per `ComplianceResult` — product score, expected/found products,
issues (`missing_products`) and text requirements — then a "Slot Presence" summary and pipeline errors. The
per-shelf tick is now `compliance_score >= 1.0`. The component contains no reference to `rule_results`,
`illumination`, `appearance` or zones, so the ticket's four checks (top present, top correct image, middle
present, bottom present) and the backlit state are not itemised unless the pipeline folds them into the
per-shelf `expected_products` / `found_products` / `missing_products` / `text_compliance_results` fields.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 250-256
  symbol: `PlanogramCompliance._build_planogram_config`
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
  lines: 205-207
  symbol: `PlanogramCompliance.get_planogram_config`
  excerpt: |
    planogram_query = f"SELECT * FROM {self._planogram_config_table} WHERE config_name = $1"
    db = AsyncDB('pg', dsn=default_dsn, server_settings=pg_server_settings('PlanogramCompliance'))
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 538-622
  symbol: `PlanogramCompliance._create_markdown_report`
  wiki: `flowtask::sym:flowtask/components/PlanogramCompliance.py#PlanogramCompliance._create_markdown_report` (Q007 score 0.98)
  excerpt: |
    for shelf_result in shelf_results:
        level = shelf_result.shelf_level.upper()
        status = "✅" if shelf_result.compliance_score >= 1.0 else "❌"
        missing_prods = getattr(shelf_result, 'missing_products', []) or []
        md.append(f"### {level} Shelf: {status}")
        md.append(f"- **Product Score:** {shelf_result.compliance_score:.1%}")
        md.append(f"- **Expected Products:** {', '.join(shelf_result.expected_products)}")
        md.append(f"- **Found Products:** {', '.join(shelf_result.found_products) or 'None'}")
        if missing_prods:
            md.append(f"- **Issues:** {', '.join(missing_prods)}")
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 735-737
  symbol: `(JSON report assembly)`
  excerpt: |
    'assessment': (
        cr.assessment.model_dump(mode='json')
        if getattr(cr, 'assessment', None) is not None else None
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

*From F018:*
- Can the report show a pass mark beside a failing zone? In the March log, yes (`HEADER Shelf: ✅` at 36 %); that renderer has since changed. In the current checkout the mismatch runs the other way: a zone shelf that is COMPLIANT with a lenient score between its threshold (0.8 default, F020) and 1.0 prints `❌` while "Overall Compliance" prints `✅`.
- For zone shelves the markdown heading becomes `### ZONE:ZONE-HEADER-1 Shelf: …` with empty "Expected Products" and "Found Products: None" (F020), so none of the ticket's four checks is named in the report a user reads.
- The two runbook constants disagree: pipeline says `wiki/flows/pipelines/planogram-cycle-migration.md` (F005), FlowTask says `ai-parrot docs/pipelines/planogram-cycle-migration.md`. Neither path was checked for existence.
- Which FlowTask and ai-parrot-pipelines versions run in production is unknown from the code.
- One `git log -1` was run on this file to date it (the lane's git budget is 0; reported in the counters).
- [cross-lane: type=wiki_page, intent=FlowTask PlanogramCompliance component page — confirm the task YAML kwargs (planogram_config_table, planogram_type) and whether a newer renderer exists on another branch]
- [cross-lane: type=git_log, intent=history of flowtask/components/PlanogramCompliance.py _create_markdown_report since 2026-03-17 in the flowtask repo]

*From F018:*
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

*From F018:*
- In the 2026-03-17 backlit log (`source.md`) the report printed `HEADER Shelf: ✅` beside a 36 % product score and
  `Text Score: 100.0%` beside failed text requirements. The current renderer derives the tick from
  `compliance_score >= 1.0` and no longer prints a "Text Score" line, so that particular inconsistency belongs to
  the pre-rewrite component.
- An anchored grep of the on-disk component for `appearance|illumination|rule_results|zone` returned no line.
- Other Q007 hits: `flowtask::sym:tests/components/test_planogram_compliance.py#TestPipelineResult.test_additive_fields_reach_the_reports`
  (1.00), `flowtask::file:sdd/specs/planogram-ink-wall-changes.spec.md` (0.82),
  `file:sdd/tasks/completed/TASK-4008-fact-tag-docs-and-harness.md` (1.00).
- ai-parrot also has a REST consumer: `PlanogramComplianceHandler`
  (`packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` L37-424, symbols lookup);
  not read in this lane.
- [cross-lane: type=read, intent=in stages/compare.py / comparison/projection.py, how zone rule outcomes (zone_present, illumination, appearance, visual_features) are projected into ComplianceResult.expected_products / found_products / missing_products / text_compliance_results that FlowTask renders]
- [citation-check: condensed excerpt] flowtask `PlanogramCompliance.py` lines 262-289, 703-739 and 847-899: excerpts reflow multi-line calls and summarise the column dict; the eleven written columns and the `PlanogramConfig(...)` arguments confirmed by direct read of lines 262-289 and 880-899.
