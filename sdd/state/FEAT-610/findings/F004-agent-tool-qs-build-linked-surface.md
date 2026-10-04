---
id: F004
query_id: Q004
type: read
intent: Understand what the agent-side tool needs and produces
executed_at: 2026-09-28T18:21:06Z
parent_id: null
depth: 0
---
# F004 — Agent tool qs_build_linked_surface is single-component, single-source
## Summary
`QuerysourceToolkit.build_linked_surface` (LLM name `qs_build_linked_surface`, prefix `qs`) takes ONE
`component` dict (Chart|DataTable|KPICard without binding), one `slug`, optional `request`/`tenant`/`refresh`/
`transform`/`target_key`/`surface_id`, runs describe → validate placeholders/filter → reject `@` values →
derive conditions (forced_conditions become `locked`) → ONE mandatory execution via `execute_sources(pctx=None,
guard=None)` → `builders.build_linked_surface`. Returns FEAT-473 dual emission `{"a2ui_envelope", "artifacts"}`
(artifact type `a2ui_linked_surface`). The toolkit needs only QuerySource installed/configured (`dsn` optional →
`_qs.default_dsn()`), optional `programs` allowlist and `forced_conditions`; `auto_open=True`. A multi-widget
dashboard is NOT produced by the tool; it requires calling the pure builder `build_linked_surface(components, sources,
frames, surface_id=…)` directly with several sources/frames (or composing several tool outputs).
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 339-418
  symbol: `QuerysourceToolkit.build_linked_surface`
  excerpt: |
    async def build_linked_surface(self, slug: str, component: dict[str, Any], request: dict[str, Any] | None = None,
        tenant: str | None = None, snapshot: bool = True, surface_id: str | None = None,
        target_key: str | None = None, refresh: dict[str, Any] | None = None,
        transform: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
        execution = await execute_sources({key: source}, pctx=None, guard=None)
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 77-101
  symbol: `QuerysourceToolkit.__init__`
  excerpt: |
    def __init__(self, programs: list[str] | None = None, allow_write: bool = False, ...
                 max_rows: int = 200, forced_conditions: dict[str, Any] | None = None,
                 dsn: str | None = None, multiquery_timeout: float = 600.0, **kwargs: Any) -> None:
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 514-523
  symbol: `build_linked_surface`
  excerpt: |
    def build_linked_surface(components: Sequence[dict[str, Any]], sources: Mapping[str, "LinkedDataSource"],
        frames: Mapping[str, "pd.DataFrame"], *, surface_id: str, snapshot: bool = True,
        max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface:
## Implications
- FEAT-610 needs either a new multi-component tool/helper (e.g. a dashboard composer over `build_linked_surface` + `execute_sources`) or the agent calls the tool N times and the example merges envelopes — merging is not supported by any existing helper.
- Default `target_key` = slug with non-word chars → `_`; several widgets on the same slug need explicit distinct `target_key`s.
- The snapshot is capped at 500 rows (`snapshot_truncated`), so the ~17k-row grid will always need a live fetch.
