---
id: FC-020
query_id: Q024
type: read
intent: "Follow-up: locate the report markdown renderer and row hydration in the FlowTask PlanogramCompliance component."
executed_at: 2026-11-06T16:05:10Z
duration_ms: 1500
parent_id: FC-016
depth: 1
---

# FC-020 — FlowTask builds the report: a shelf prints ✅ only at score 1.0, and rule outcomes are not in the markdown

## Summary

The consumer is `flowtask/components/PlanogramCompliance.py` in the sibling repo `/home/jesuslara/proyectos/flowtask` (955 lines, checkout on branch `dev`, file last touched 2026-10-13). `_build_planogram_config` raises `ConfigError` when the row has no `slots_definition`, takes `planogram_type` from the row first and the task YAML second, and loads reference images only when the pipeline says the type uses them. `_create_markdown_report` marks each shelf `✅` only when `compliance_score >= 1.0` (it ignores `compliance_status` and the threshold), prints `Expected Products` / `Found Products`, lists `missing_products` as "Issues", and prints text requirements only if the result has `text_compliance_results`. Per-rule outcomes (`assessment.rule_results`) go only into the JSON report.

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
  lines: 261-263
  symbol: `PlanogramCompliance._build_planogram_config`
  excerpt: |
    # DB value takes precedence, the task value is the fallback.
    planogram_type = row.get('planogram_type') or self._planogram_type
    layout_config = self._decode_json_column(row, 'planogram_config') or {}
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 205-207
  symbol: `PlanogramCompliance.get_planogram_config`
  excerpt: |
    planogram_query = f"SELECT * FROM {self._planogram_config_table} WHERE config_name = $1"
    db = AsyncDB('pg', dsn=default_dsn, server_settings=pg_server_settings('PlanogramCompliance'))
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 538-583
  symbol: `PlanogramCompliance._create_markdown_report`
  excerpt: |
    compliance_emoji = "✅" if result.get('overall_compliant', False) else "❌"
    ...
    for shelf_result in shelf_results:
        level = shelf_result.shelf_level.upper()
        status = "✅" if shelf_result.compliance_score >= 1.0 else "❌"
        ...
        md.append(f"### {level} Shelf: {status}")
        md.append(f"- **Product Score:** {shelf_result.compliance_score:.1%}")
        md.append(f"- **Expected Products:** {', '.join(shelf_result.expected_products)}")
        md.append(f"- **Found Products:** {', '.join(shelf_result.found_products) or 'None'}")
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 735-737
  symbol: `(JSON report assembly)`
  excerpt: |
    'assessment': (
        cr.assessment.model_dump(mode='json')
        if getattr(cr, 'assessment', None) is not None else None
- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 24-24
  symbol: `_MIGRATION_RUNBOOK`
  excerpt: |
    _MIGRATION_RUNBOOK = 'ai-parrot docs/pipelines/planogram-cycle-migration.md'

## Notes

- Can the report show a pass mark beside a failing zone? In the March log, yes (`HEADER Shelf: ✅` at 36 %); that renderer has since changed. In the current checkout the mismatch runs the other way: a zone shelf that is COMPLIANT with a lenient score between its threshold (0.8 default, FC-022) and 1.0 prints `❌` while "Overall Compliance" prints `✅`.
- For zone shelves the markdown heading becomes `### ZONE:ZONE-HEADER-1 Shelf: …` with empty "Expected Products" and "Found Products: None" (FC-022), so none of the ticket's four checks is named in the report a user reads.
- The two runbook constants disagree: pipeline says `wiki/flows/pipelines/planogram-cycle-migration.md` (FC-005), FlowTask says `ai-parrot docs/pipelines/planogram-cycle-migration.md`. Neither path was checked for existence.
- Which FlowTask and ai-parrot-pipelines versions run in production is unknown from the code.
- One `git log -1` was run on this file to date it (the lane's git budget is 0; reported in the counters).
- [cross-lane: type=wiki_page, intent=FlowTask PlanogramCompliance component page — confirm the task YAML kwargs (planogram_config_table, planogram_type) and whether a newer renderer exists on another branch]
- [cross-lane: type=git_log, intent=history of flowtask/components/PlanogramCompliance.py _create_markdown_report since 2026-03-17 in the flowtask repo]
