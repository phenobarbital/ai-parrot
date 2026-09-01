---
id: F003
query_id: Q004+Q009
type: grep+read
intent: Find existing PandasAgent-based dashboard agents as the reference pattern.
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F003 — FinanceReporter (FEAT-420) is the direct architectural precedent

## Summary

`agents/finance_reporter.py` (326 lines) defines `FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)` — a tier-2 A2UI budget-variance agent. It registers a Postgres dataset on `self._dataset_manager` in an overridden `configure()`, declares recipe sections whose names ARE registered `@infographic_transformer` names, publishes two recipes (`Report` + `Infographic` profiles) via `InfographicAuthoringMixin.publish_recipe`, uses `LayoutSpec` v2 with `KPICard` / `DataTable` components and `{"path": ...}` bindings, and opts into file-based skills via `skill_paths = [SKILLS_DIR]` pointing at `.agent/skills/` (needed for `narrate("budget-narrative")`). Gotchas documented in-file: dataset alias must match transformer input keys 1:1; `TableSource` requires explicit `dataset_sql` for replay; `template_dirs` is validated eagerly by InfographicToolkit. Other PandasAgent users: `agents/porygon.py` (local_kb + SkillRegistryMixin), `examples/budget_variance_infographic.py`, `examples/agents/a2ui/*`.

## Citations

- path: `agents/finance_reporter.py`
  lines: 85-130
  symbol: `FinanceReporter`
  excerpt: |
    @register_agent(name="finance_reporter")
    class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
        agent_id = "finance_reporter"
        llm = "google:gemini-3.5-flash"
        skill_paths: List[Path] = [SKILLS_DIR]   # .agent/skills/
        _DATASET_SQL: ClassVar[dict] = {FINANCE_DATASET: "SELECT ..."}

- path: `agents/finance_reporter.py`
  lines: 153-186
  symbol: `register_datasets` / `configure`
  excerpt: |
    await self._dataset_manager.add_table_source(
        name=FINANCE_DATASET, table="troc.finance_projection", driver="pg",
        description=..., usage_guidance={"do": [...]})

- path: `agents/finance_reporter.py`
  lines: 258-326
  symbol: `dashboard_descriptor`
  excerpt: |
    SectionDescriptor(template=..., mode="data-splice", sections=..., dataset_sql=...,
      layout=LayoutSpec(component="Infographic", sections=[
        {"heading": "Snapshot", "components": [{"component": "KPICard", ...}]}]))

- path: `agents/porygon.py`
  lines: 33-53, 342-343
  symbol: `Porygon`
  excerpt: |
    enable_skill_registry: bool = True  # + local_kb=True, kb_embedding_model=..., kb_dimension=768
    await self._configure_skill_registry()  # loads agents/porygon/skills/*.md

- path: `packages/ai-parrot/src/parrot/bots/mixins/__init__.py`
  symbol: `InfographicAuthoringMixin, NarrativeMixin`
