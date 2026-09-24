---
id: F001
query_id: Q001/Q023
type: wiki_query+read
intent: Ledger is mounted in mcp_server as a read-only overlay NamespaceHandle — the block to copy for `schema`
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — Ledger is mounted in mcp_server as a read-only overlay NamespaceHandle — the block to copy for `schema`

## Summary

mcp_server.py initialises LedgerService only when find_shared_root(root) is not None (so bare test dirs never grow a .parrot/ledger), then wraps the already-open LedgerStore in a NamespaceHandle(name='ledger', read_only=True) whose WikiNamespaceConfig has store=<dir> and overlay_prefixes=['issue','task','spec','insight']. FederatedWikiStore(store, wiki_name, handles, skipped) becomes read_store; create_structural_tools / create_decision_tools are appended after. Wiki hit: sym:tests/knowledge/wiki/test_ledger_integration.py#_federated (score 1.00) mounts it 'exactly as create_wiki_mcp_server does'.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 154-171
  symbol: `create_wiki_mcp_server`
  excerpt: |
    ledger_service = None … if find_shared_root(root) is not None: … LedgerService.from_root(root)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 178-201
  symbol: `create_wiki_mcp_server`
  excerpt: |
    ledger_config = WikiNamespaceConfig(store=str(ledger_dir), description=…, overlay_prefixes=["issue","task","spec","insight"]) / NamespaceHandle(name="ledger", store=ledger_service.store, config=ledger_config, storage_dir=ledger_dir, read_only=True) / read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 208-225
  symbol: `create_wiki_mcp_server`
  excerpt: |
    create_structural_tools(read_store, root, config); create_decision_tools(read_store, root, config)

## Notes

A second overlay handle is one more append to `handles` before FederatedWikiStore is built.
