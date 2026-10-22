# F005 — Python executor and TS renderer lane (the parity boundary)

- **Query**: Q005/Q007/Q008 (grep + read)
- **Citations**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py:100-290`;
  `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts:61-83`

Python lane (bake/persist/server-refresh):
- `execute_sources` → `_run_source` (executor.py:231): fetch via `QuerySlugSource`,
  then `apply_transform(frame, src.transform, frames=...)` for DSL ops
  (executor.py:287); **`transform.ref` is SKIPPED in Python with a warning**
  (executor.py:284-285) — the asymmetry precedent.
- `dependencies_of` (executor.py:100) orders sources by transform references
  (join/union `with`/`sources`), with per-source failure isolation.

TS lane (renderer dynamic fetch):
- `fetchSource` (fetch.ts:61) builds the URL with
  `queryUrl(baseUrl, slug, tenant, is_multiquery)` from `$lib/api/querysource` —
  **direct to QuerySource, viewer JWT**, `querylimit = min(request.limit, 5000)`.
- `linked/` TS package: `dsl.ts` (TS twin of DSL v1), `ref.ts` (catalogued module
  loader), `scheduler.ts`, `index.ts` (LinkedLane); `parity.test.ts` pins Python↔TS
  frame equality.
- A Python recipe transformer **cannot run in this lane** → a source that declares one
  must fetch rows from a parrot-server endpoint (which executes slug + transformer)
  instead of calling QuerySource directly. That endpoint does not exist today (F003).
