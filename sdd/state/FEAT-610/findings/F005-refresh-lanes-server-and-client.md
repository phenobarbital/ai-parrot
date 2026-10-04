---
id: F005
query_id: Q005
type: read
intent: Establish how a client re-fetches a widget (endpoint, payload, auth) and which server endpoints exist
executed_at: 2026-09-28T18:21:06Z
parent_id: null
depth: 0
---
# F005 — Refresh lanes: client→QuerySource direct vs server POST /api/v1/ui/surfaces/{id}/refresh
## Summary
Two lanes exist. (1) Client lane: renderer POSTs `{...conditions, querylimit: min(request.limit ?? 5000, 5000),
refresh?: true}` to `${base}/api/v3/queries/{slug}` (or `/api/v1/{tenant}/queries/{slug}` when `tenant` set)
with the viewer's bearer; 404 ⇒ "unavailable" (never "denied"); MultiQuery payloads are keyed objects and the frame
is selected by `multi_output` → `result` → sole key. (2) Server lane: `POST /api/v1/ui/surfaces/{id}/refresh`
with body `{"params": {...}}` refreshes ALL sources of a PERSISTED surface through `LinkedSurfaceService.refresh`
(owner PermissionContext → QSPrincipal, mandatory `dataplane_guard` else 403), persists with optimistic
concurrency (409 "stale refresh") and returns the updated surface; partial failures go in header
`X-Parrot-Refresh-Warnings`. There is no per-widget/per-source server endpoint and no unauthenticated surface-serving
endpoint beyond ui_surfaces GET (which never executes). The Python executor `execute_sources(sources,
param_overrides=…, pctx=None, guard=None, max_fetch_rows=5000)` is callable in-process and is deterministic (no LLM).
## Citations
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts`
  lines: 42-59
  symbol: `fetchSource`
  excerpt: |
    const cap = opts.maxFetchRows ?? DEFAULT_MAX_FETCH_ROWS;   // 5000
    const body: Record<string, unknown> = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
    if (body.refresh !== true) delete body.refresh;
    payload = await postQuery(queryUrl(opts.baseUrl, src.slug, src.tenant ?? null), body, opts.headers);
- path: `packages/ai-parrot-server/ui/src/lib/api/querysource.ts`
  lines: 22-35
  symbol: `queryUrl`, `postQuery`
  excerpt: |
    return tenant ? `${baseUrl}/api/v1/${encodeURIComponent(tenant)}/queries/${s}` : `${baseUrl}/api/v3/queries/${s}`;
    const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
- path: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
  lines: 94-97, 688-735
  symbol: `RefreshSurfaceRequest`, `UISurfacesHandler._refresh_linked`
  excerpt: |
    class RefreshSurfaceRequest(BaseModel):
        """Body of ``POST /api/v1/ui/surfaces/{id}/refresh``."""
        params: dict[str, Any] = Field(default_factory=dict)
    ...
    outcome = await service.refresh(record.envelope, params=req.params, owner_pctx=owner_pctx)
    except LinkedGuardRequired: ... status=403
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
  lines: 180-215
  symbol: `execute_sources`
  excerpt: |
    async def execute_sources(sources, *, param_overrides=None, pctx=None, guard=None,
                              max_snapshot_rows=None, max_fetch_rows: int = 5000) -> ExecutionOutcome:
        inner = QuerySlugSource(src.slug, prefetch_schema_enabled=False, tenant=src.tenant,
                                is_multiquery=src.is_multiquery, multi_output=src.multi_output, principal=principal)
## Implications
- For a self-contained example, the simplest deterministic "refresh one widget" is a small example-server route that calls `execute_sources({key: src})` in-process (no ui_surfaces DB, no dataplane_guard needed) — or proxy the QuerySource POST; the spec's G3 direction is direct browser→QuerySource with JWT, which needs QuerySource reachable + CORS + auth from the HTML page.
- The 5000-row fetch cap (both lanes) will truncate a ~17k-row grid; the example must set `request.limit` and/or `max_fetch_rows` deliberately or paginate (`limit`/`offset` exist in SourceRequest).
- Using the persisted ui_surfaces refresh lane requires Postgres ui_surfaces table + an app-level `dataplane_guard`; heavy for a standalone example.
