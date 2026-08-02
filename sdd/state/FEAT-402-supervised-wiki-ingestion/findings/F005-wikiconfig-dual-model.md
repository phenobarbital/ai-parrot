# F005 — `WikiConfig` already models a two-tier LLM cascade + categories

- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:47-135` —
  `WikiConfig`: `lightweight_model` ("fast CoT analysis step") + `model`
  (heavy generation), `page_categories` (Karpathy taxonomy, `models.py:25-45`
  `WikiPageCategory`: SUMMARY/ENTITY/CONCEPT/COMPARISON/OVERVIEW/SYNTHESIS/
  ANSWER), `sync_graph`, `storage_backend`, and a `field_validator` precedent
  (`validate_search_weights`, weights must sum to ~1.0 — same rule the charter
  scoring weights need).
- Implication: charter path + triage thresholds belong here;
  `save_project_config` (cli.py:710) already persists config per project.

Method: direct read.
