# F003 — S0 security claims re-verified (all hold; surface grew)
**Query**: G001, G008, R006 · **Confidence**: high

- `handlers/crew/{handler,execution_handler,execution_history_handler}.py`: **zero** `@is_authenticated()`; only `tool_catalog.py:231` and `special_nodes.py:74` have it.
- Tenant from request, not session: `handler.py:412,512` → `qs.get('tenant') or "global"`; `execution_history_handler.py:144` → `tenant or 'global'` (reads); `execution_handler.py:590-593` requires tenant (rejects to avoid 'global') but does NOT validate ownership; history :178 comment shows mutating actions now demand explicit tenant — partial hardening already began in-tree.
- `handlers/stream.py:385-394` still appends `/bots/*/stream/{sse,ndjson,chunked,ws}` to navigator-auth `exclude_list` (drifted from claimed :383).
- New since brainstorm: tales-research POST handler + durable job progress extend the crew surface (F001) — S0's blast radius is slightly larger than the brainstorm lists.
