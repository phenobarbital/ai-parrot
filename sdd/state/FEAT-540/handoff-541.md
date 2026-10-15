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

## Eager imports found by the gates (NOT fixed here — need an owner)

| Location | Eager import | Effect |
|---|---|---|
| `wiki/schema/models.py:9` | `parrot.bots.database.models.TableMetadata` | `import parrot.knowledge.wiki.cli` loads `parrot.bots` -> `parrot.conf`, navconfig, pandas, ...; fails `wiki.cli` ceiling (xfail) and the sys.meta_path blocker test (xfail) |
| `wiki/schema/producers/ddl.py:12`, `render.py:13`, `service.py:11` | `parrot.bots.database.models` | same family (schema-plane, FEAT-600) |
| `wiki/schema/producers/live.py:9-11` | `parrot.bots.database.toolkits.*` | legal Arango-bound / DB toolkits imported at module level |

## Docs drift (not edited)

`docs/architecture/09-ontologic-rag.md` still names the removed `OntologyGraphStore` / `execute_traversal`
(lines ~48, 241, 249, 270). The current names are `ArangoOntologyGraphStore`, `GraphDocumentStore`,
`OntologyTraversalStore`.
