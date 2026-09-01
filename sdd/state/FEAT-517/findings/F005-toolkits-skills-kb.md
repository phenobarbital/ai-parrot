---
id: F005
query_id: Q006+Q007+Q010+Q011
type: grep
intent: Locate InfographicToolkit, WorkingMemoryToolkit, skill /trigger mechanics, kb attachment.
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F005 — InfographicToolkit, WorkingMemoryToolkit, skill /triggers and kb are all first-class

## Summary

Every remaining named building block exists. `InfographicToolkit(AbstractToolkit)` at `parrot/tools/infographic_toolkit.py:180` (render / render_template / render_data_template, A2UI envelope builders, template engine with eager `template_dirs` validation). `WorkingMemoryToolkit(AbstractToolkit)` at `parrot/tools/working_memory/tool.py:44` (store/get/search/compute_and_store/merge/summarize/import_from_tool over pandas results). Skills: `SkillDefinition.triggers: list[str]` (`skills/models.py:69,101`) drive deterministic `/trigger` activation through `create_skill_trigger_middleware` (`skills/middleware.py`), wired by `SkillRegistryMixin` (`skills/mixin.py:142-188`); agents opt in via `skill_paths` (FinanceReporter) or `enable_skill_registry` (Porygon, loading `agents/porygon/skills/*.md`). KB: `AbstractBot.__init__` accepts `use_kb`, `local_kb`, `kb=[...]` (`bots/abstract.py:287,554-562`) backed by `parrot/stores/kb/` (`KnowledgeBaseStore`), plus `register_kb()` at `abstract.py:1172`; Porygon uses `local_kb=True` with `kb_embedding_model`/`kb_dimension`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 180-345, 402-660, 846-899
  symbol: `InfographicToolkit`
  excerpt: |
    class InfographicToolkit(AbstractToolkit):
        async def render(self, template_name, ...)
        async def render_template(...); async def render_data_template(...)
        def _build_a2ui_envelope(...); def _build_a2ui_envelope_from_layout(...)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 44-650
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(AbstractToolkit):
        async def store(...); async def store_result(...); async def get_stored(...)
        async def search_stored(...); async def compute_and_store(...)
        async def merge_stored(...); async def import_from_tool(...)

- path: `packages/ai-parrot/src/parrot/skills/models.py`
  lines: 64-101
  symbol: `SkillDefinition.triggers`
  excerpt: |
    # "on demand via deterministic /trigger patterns"
    triggers: list[str] = field(default_factory=list)

- path: `packages/ai-parrot/src/parrot/skills/mixin.py`
  lines: 142-188
  symbol: `SkillRegistryMixin._configure_skill_registry`
  excerpt: |
    from .middleware import create_skill_trigger_middleware
    # Register trigger middleware in prompt pipeline.

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 287-288, 554-562, 1172-1176
  symbol: `AbstractBot(use_kb, local_kb, kb=[...])` / `register_kb`
  excerpt: |
    use_kb: bool = False, local_kb: bool = False
    self._kb = kwargs.get('kb', []); KnowledgeBaseStore(...)

- path: `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py`
  symbol: server-side recipe HTTP handlers (publish/replay surface)
