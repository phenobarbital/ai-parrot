---
id: F010
query_id: Q010
type: read
intent: Read the MultiQuery and query-manager REST handlers — how slugs are listed/created and how pipelines are submitted.
executed_at: 2026-09-15T02:50:00Z
duration_ms: 3000
parent_id: null
depth: 0
---
# F010 — Slug CRUD is plain QueryModel upserts; MultiQuery REST does per-slug PBAC preflight and strips step keys from filters
## Summary
`QueryManager` (`handlers/manager.py`): `GET` returns one slug (`QueryModel.get(query_slug=...)`), `:meta` (model JSON schema), `:insert` (INSERT SQL), or a paginated list with `default_fields` incl. `program_slug` and equality filters on allowlisted columns; `POST` upserts (`get_model(**data)` → `update` or `insert`) with **no program check**; `PATCH/PUT/DELETE` exist. `QueryHandler.query` (`handlers/multi.py`) runs `_preflight_multiquery` (Guardian `slug:execute` per slug name, `raw_query:execute` if inline SQL) and then `MultiQS(slug, queries, files, query=options, conditions=data, user_session=...)`; before applying leftover body keys as filters it strips `queries, files, Info, Join, Concat, Melt, Merge, Transform, Filter, GroupBy, Output, Processors`. Tenant scoping in the REST layer is therefore PBAC (Guardian policies), not `program_slug` — the toolkit must implement its own program check since it calls the library in-process.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/handlers/manager.py`
  lines: 71-143
  symbol: `QueryManager.get`
  excerpt: |
    default_fields = ["query_slug","description","conditions","is_cached","cache_refresh","program_slug","provider","dwh",...]
    if query_slug: query = await QueryModel.get(query_slug=query_slug, _connection=conn); return self.json_response(query)
    return await self._paginate_list(qp, {"fields": default_fields})
- path: `.venv/lib/python3.12/site-packages/querysource/handlers/manager.py`
  lines: 461-520
  symbol: `QueryManager.post`
  excerpt: |
    qry = self.get_model(**data)                 # QueryModel validation
    slug = await QueryModel.get(_connection=conn, **slug); for k, v in data.items(): setattr(slug, k, v); await slug.update(...)
    except NoDataFound: result = await qry.insert(_connection=conn)
- path: `.venv/lib/python3.12/site-packages/querysource/handlers/multi.py`
  lines: 25-100
  symbol: `QueryHandler._preflight_multiquery`
  excerpt: |
    r = await guardian.filter_resources(resources=slugs, request=request, resource_type=ResourceType.SLUG, action="slug:execute")
    if r.denied: raise web.HTTPNotFound()
- path: `.venv/lib/python3.12/site-packages/querysource/handlers/multi.py`
  lines: 205-230, 314-325
  symbol: `QueryHandler.query`
  excerpt: |
    qs = MultiQS(slug=slug, queries=_queries, files=_files, query=options, conditions=data, user_session=_user_session)
    result, options = await qs.query()
    for _mq_key in ('queries','files','Info','Join','Concat','Melt','Merge','Transform','Filter','GroupBy','Output','Processors'): data.pop(_mq_key, None)
