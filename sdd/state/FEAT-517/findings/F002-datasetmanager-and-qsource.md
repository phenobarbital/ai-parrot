---
id: F002
query_id: Q002+Q016
type: grep+read
intent: Locate QuerySource / DatasetManager infra for consuming slugs.
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F002 — DatasetManager toolkit + QSourceTool are the slug-consumption plane

## Summary

Two complementary pieces. (1) `DatasetManager(AbstractToolkit)` at `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:501` (220KB module with `sources/`, `filtering/`, `spatial/` subpackages) is the data catalog: `add_dataset(query_slug=...)` registers a QuerySource slug via `QuerySlugSource` (`sources/query_slug.py`, incl. `MultiQuerySlugSource`), alongside `sql`, `table` (`add_table_source`), `dataframe`, `airtable`, `smartsheet` source kinds; supports `permanent_filter` conditions per dataset. (2) `QSourceTool(AbstractTool)` at `packages/ai-parrot-tools/src/parrot_tools/qsource.py:62` is the LLM-facing tool executing arbitrary slugs/raw SQL via `querysource.queries.qs.QS` with conditions/filters and pandas output.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 966-1091
  symbol: `DatasetManager.add_dataset`
  excerpt: |
    async def add_dataset(self, name, ..., query_slug=None, query=None, table=None,
                          dataframe=None, permanent_filter=None, ...):
        # Exactly one of query_slug, query, table, or dataframe
        elif query_slug is not None:
            from .sources.query_slug import QuerySlugSource
            ... QuerySlugSource(slug=query_slug, permanent_filter=permanent_filter, ...)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 141-183
  symbol: `DatasetEntry`
  excerpt: |
    # source kinds: "dataframe", "query_slug", "sql", "table", "airtable", "smartsheet"

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  symbol: `QuerySlugSource, MultiQuerySlugSource`

- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 62-437
  symbol: `QSourceTool`
  excerpt: |
    class QSourceTool(AbstractTool):
        args_schema = QuerySourceInput  # query_slug | query, conditions, driver,
                                        # return_format: pandas|dict|json|structured

## Notes

For a fixed-slug agent, `DatasetManager.add_dataset(query_slug=...)` per slug (lazy fetch, catalog + usage_guidance) is the pattern; QSourceTool is for ad-hoc LLM-driven queries and is likely unnecessary/riskier here.
