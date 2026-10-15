# FEAT-541 handoff — residual optional framework imports

Residual function-local (lazy) imports of framework modules in the graph tree, verified by grep on the
FEAT-540 integration branch (2026-10-15). All are inside function bodies, so the AST gate (module-level only)
passes. "Absent" = behaviour when the framework/satellite distribution is not installed.

| Module | Import (function-local) | Owner | Behaviour when absent |
|---|---|---|---|
| `wiki/cli.py:4120,4996` | `parrot.clients.detection.detect_coding_agent_llm` | FEAT-541 (LLM provider seam) | ImportError surfaces in the command that needs an LLM; other commands unaffected |
| `wiki/cli.py:4137` | `parrot.clients.factory.LLMFactory` | FEAT-541 | same |
| `wiki/llm_resolve.py:54,64` | `detect_coding_agent_llm`, `LLMFactory` | FEAT-541 | `ProviderNotAvailable` path / ImportError at resolve time |
| `wiki/runtime.py:100` | `parrot.clients.factory.LLMFactory` | FEAT-541 | ImportError when an LLM is requested |
| `wiki/decisions/generation.py:40,81` | `parrot.clients.AbstractClient` (typing), `LLMFactory` | FEAT-541 | ADR generation unavailable |
| `wiki/decisions/service.py:50` | `parrot.clients.AbstractClient` | FEAT-541 | ADR generation unavailable |
| `wiki/documents.py:585` | `parrot.tools.egress` (`EgressBlocked`, `egress_session`) | FEAT-541 (egress acquisition) | remote document acquisition fails with ImportError |
| `wiki/documents.py:688` | `parrot.loaders.ebook` (`ebook_markdown`, `ebook_sections`) | FEAT-541 (ebooks) | ebook ingestion fails with ImportError |
| `wiki/execution.py:227` | `parrot.embeddings.base.EmbeddingModel` | FEAT-541 | embedding steps unavailable |
| `wiki/mcp_server.py:310` | `parrot.tools.obsidian.ObsidianToolkit` | FEAT-541 (Jira/Obsidian) | Obsidian tools not registered / ImportError |
| `wiki/mcp_server.py:392-393` | `parrot_tools.wiki`, `parrot.tools.abstract` | FEAT-541 (framework toolkit factories) | only the `framework` transport needs them; `sdk` transport works |
| `wiki/claude_code/cli.py:190,221,241` | `parrot_tools.tool_optimizations.installation` | FEAT-541 (coding-agent guard installers) | guard install/uninstall/status commands fail with ImportError |
| `wiki/codex/cli.py:122,158,181` | `parrot_tools.tool_optimizations.installation` | FEAT-541 (coding-agent guard installers) | same |
| `graphindex/embed.py:11` | `parrot.embeddings.graphindex.GraphIndexEmbedder` | FEAT-541 | embedding stage unavailable |
| `graphindex/extractors/loader.py:41,200` | `parrot.loaders.ebook` | FEAT-541 (ebooks) | ebook extraction fails |
| `graphindex/factory.py:38,282` | `parrot_tools.graphindex.toolkit.GraphIndexToolkit` | FEAT-541 (framework toolkit factories) | toolkit factory raises ImportError |
| `graphindex/factory.py:308` | `parrot.embeddings.graphindex.attach_hot_index` | FEAT-541 | hot index not attached |
| `graphindex/loader.py:13` | `parrot.loaders.graphindex.GraphIndexLoader` | FEAT-541 | loader unavailable |
| `graphindex/mixin.py:81` | `parrot.conf.AGENTS_DIR` | FEAT-541 | falls to ImportError at agent-dir resolution |
| `graphindex/pg_schema.py:125` | `parrot.conf.default_dsn` | FEAT-541 | explicit dsn required |
| `ontology/validators.py:62` | `parrot.conf.ONTOLOGY_MAX_TRAVERSAL_DEPTH` | FEAT-541 | explicit `max_depth` required |
| `retrieval/pin.py` | none found (no `parrot.*` framework imports in the file) | FEAT-541 | n/a |

## Eager imports found by the gates — FIXED (issue:3c432c97c459)

`TableMetadata`, `Completeness` and `MetadataSource` moved to the framework-free
`parrot/knowledge/wiki/schema/table_metadata.py` (`parrot.bots.database.models` re-exports them, so import
paths are unchanged). `wiki/schema/{models,render,service}.py` and `producers/ddl.py` import from it;
`producers/live.py` now imports the BigQuery/Postgres/SQL toolkits function-locally inside `toolkit_for`
(`SQLToolkit` is TYPE_CHECKING-only). `import parrot.knowledge.wiki.cli` no longer loads `parrot.bots` /
`parrot.conf`; the `wiki.cli` ceiling row and `test_blocker_default_cli_entry_and_plain_ops` are no longer xfail.

## Docs drift — FIXED (issue:0203d753aded)

`docs/architecture/09-ontologic-rag.md` now documents `ArangoOntologyGraphStore` and its typed operations
(`is_reachable`, `get_document_by_id`, `find_by_field`, `search_by_name`, `execute_pattern`, `execute_query`,
private `_execute_aql`) instead of the removed `OntologyGraphStore` / `execute_traversal`.
