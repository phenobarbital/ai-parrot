# FEAT-720 M1 spike — strategy (a) re-measurement

**Run at**: 2026-10-23T02:41:46Z
**Worktree**: `.claude/worktrees/feat-FEAT-720-tests-test-wheel-layout-tech-debt-2--pool/TASK-4590-a3-6f1c2a9e3b7d4e589a41720a0c0de720`
**Base commit**: `d48214e0e`
**pytest**: 9.1.1
**Command**: `pytest <package-test-root> --collect-only -q -p no:randomly`

## 1. Baseline — before any change

| Package test root | rc | items | notes |
|---|---:|---:|---|
| `packages/ai-parrot-advisors/tests` | 0 | 7 | clean |
| `packages/ai-parrot-client-amazon/tests` | 0 | 69 | clean |
| `packages/ai-parrot-client-anthropic/tests` | 0 | 13 | clean |
| `packages/ai-parrot-client-gemma4/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-google/tests` | 0 | 259 | clean |
| `packages/ai-parrot-client-grok/tests` | 0 | 13 | clean |
| `packages/ai-parrot-client-groq/tests` | 0 | 5 | clean |
| `packages/ai-parrot-client-hf/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-jev/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-local/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-meta/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-moonshot/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-nvidia/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-openai/tests` | 0 | 54 | clean |
| `packages/ai-parrot-client-openrouter/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-vllm/tests` | 0 | 1 | clean |
| `packages/ai-parrot-client-zai/tests` | 0 | 1 | clean |
| `packages/ai-parrot-embeddings/tests` | 0 | 214 | clean |
| `packages/ai-parrot-integrations/tests` | 0 | 2,458 | clean |
| `packages/ai-parrot-loaders/tests` | 0 | 421 | clean |
| `packages/ai-parrot-openlit-bridge/tests` | 0 | 8 | clean; control root |
| `packages/ai-parrot-pipelines/tests` | 0 | 853 | clean |
| `packages/ai-parrot-server/tests` | 2 | 3,588 | 5 pre-existing collection errors (network lookup, missing `fakeredis`, and E2E imports) |
| `packages/ai-parrot-tools/tests` | 0 | 6,286 | clean |
| `packages/ai-parrot-visualizations/tests` | 0 | 425 | clean |
| `packages/ai-parrot/tests` | 0 | 25,328 | clean |
| `packages/navrules/tests` | 0 | 144 | clean; control root |
| `packages/parrot-formdesigner/tests` | 0 | 3,899 | clean |

## 2. After strategy (a)

Applied: 25 top-level `packages/*/tests/__init__.py` deleted;
`--import-mode=importlib` appended to the root `addopts`.

| Package test root | rc | items | delta vs baseline |
|---|---:|---:|---|
| `packages/ai-parrot-advisors/tests` | 0 | 7 | 0; clean |
| `packages/ai-parrot-client-amazon/tests` | 0 | 69 | 0; clean |
| `packages/ai-parrot-client-anthropic/tests` | 0 | 13 | 0; clean |
| `packages/ai-parrot-client-gemma4/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-google/tests` | 0 | 259 | 0; clean |
| `packages/ai-parrot-client-grok/tests` | 0 | 13 | 0; clean |
| `packages/ai-parrot-client-groq/tests` | 0 | 5 | 0; clean |
| `packages/ai-parrot-client-hf/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-jev/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-local/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-meta/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-moonshot/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-nvidia/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-openai/tests` | 0 | 54 | 0; clean |
| `packages/ai-parrot-client-openrouter/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-vllm/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-client-zai/tests` | 0 | 1 | 0; clean |
| `packages/ai-parrot-embeddings/tests` | 2 | 197 | -17; 1 new error |
| `packages/ai-parrot-integrations/tests` | 2 | 2,434 | -24; 3 new errors |
| `packages/ai-parrot-loaders/tests` | 2 | 271 | -150; 1 new error |
| `packages/ai-parrot-openlit-bridge/tests` | 0 | 8 | 0; clean control |
| `packages/ai-parrot-pipelines/tests` | 0 | 853 | 0; clean |
| `packages/ai-parrot-server/tests` | 2 | 3,586 | -2; 7 errors, of which 2 are new |
| `packages/ai-parrot-tools/tests` | 2 | 6,216 | -70; 4 new errors |
| `packages/ai-parrot-visualizations/tests` | 0 | 425 | 0; clean |
| `packages/ai-parrot/tests` | 2 | 23,117 | -2,211; 113 new errors |
| `packages/navrules/tests` | 0 | 144 | 0; clean control |
| `packages/parrot-formdesigner/tests` | 2 | 3,662 | -237; 5 new errors |

The after matrix has **129 new collection errors** and loses 2,711 collected items. The three control roots retain
their exact baseline counts.

## 3. New errors, classified

Classes (i)–(vi) are the spec classes. This measurement found class **(vii)**: after the root package is deleted,
pytest derives short module identities from retained nested packages. Whole-tree collection then cannot import those
identities (for example `auth.test_eval_context`, `clients.test_factory_discovery`, and `tools.test_tool_lifecycle`),
although an affected file can collect alone. That class is not covered by (i)–(vi), so it stops the feature.

| Site (path:line) | Class | What broke | Proposed repair |
|---|---|---|---|
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py:11` | (ii) | root-level relative import has no parent package | Rework the helper import without restoring the colliding root package. |
| `packages/ai-parrot-loaders/tests/test_metadata_standardization.py:20` | (ii) | root-level relative import has no parent package | Rework the helper import without restoring the colliding root package. |
| `packages/ai-parrot-tools/tests/test_exports_legacy_mode_pavfix.py:14` | (ii) | root-level relative import has no parent package | Rework the helper import without restoring the colliding root package. |
| `packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py:17` | (iii) | prepend-mode had made `scripts.build_snippet_bundles` importable | Add explicit owning-package path setup in its `conftest.py`. |
| `packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py:11` | (iv) | relative import is now beyond the shortened package ancestry | Preserve a unique parent identity or rewrite the relative import. |
| `packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py:8` | (iv) | relative import is now beyond the shortened package ancestry | Preserve a unique parent identity or rewrite the relative import. |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py:14` | (iv) | relative import is now beyond the shortened package ancestry | Preserve a unique parent identity or rewrite the relative import. |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py:18` | (iv) | relative import is now beyond the shortened package ancestry | Preserve a unique parent identity or rewrite the relative import. |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py:19` | (iv) | relative import is now beyond the shortened package ancestry | Preserve a unique parent identity or rewrite the relative import. |
| `packages/ai-parrot/tests/eval/test_benchmarks_e2e.py:32` | (i) | `tests.eval` no longer names this distribution's test tree | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py:27` | (i) | `tests.handlers` resolved to the repository-root test tree | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/integration/test_jira_wiki_e2e.py:26` | (i) | `tests.fixtures` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/interfaces/jira/conftest.py:3` | (i) | `tests.fixtures.jira_payloads` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py:9` | (i) | `tests.knowledge._support` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py:9` | (i) | `tests.knowledge._support` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py:5` | (i) | `tests.knowledge._support` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py:16` | (i) | `tests.knowledge.wiki._tool_surface` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py:19` | (i) | `tests.knowledge.wiki._tool_surface` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py:14` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py:24` | (i) | `tests.knowledge.wiki.decisions` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_source_manager_event_loop.py:14` | (i) | `tests.knowledge.wiki.test_source_backends` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py:13` | (i) | `tests.knowledge.wiki._tool_surface` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py:11` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py:9` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/loaders/obsidian/conftest.py:6` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/tools/test_obsidian_okf_tools.py:5` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot/tests/tools/test_obsidian_toolkit.py:5` | (i) | `tests.interfaces` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-integrations/tests/agentd/test_e2e.py:32` | (i) | `tests.agentd` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py:18` | (i) | `tests.agentd` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-integrations/tests/agentd/test_service.py:39` | (i) | `tests.agentd` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py:46` | (i) | `tests.scraping` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py:65` | (i) | `tests.business_automation` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/parrot-formdesigner/tests/integration/conftest.py:9` | (i) | `tests.fixtures` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py:32` | (i) | `tests.unit` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/parrot-formdesigner/tests/unit/test_feat302_review_fixes.py:22` | (i) | `tests.unit` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/parrot-formdesigner/tests/unit/test_org_graph_service.py:22` | (i) | `tests.unit` is no longer importable | Rewrite the `tests.*` import to its new stable identity. |
| `packages/ai-parrot-server/tests/mcp/test_agent_mcp_interop.py:26` | (vi) | test package `mcp` shadows the installed `mcp` package | Rename or scope the shadowing test package. |
| `packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py:25` | (vi) | test package `mcp` shadows the installed `mcp` package | Rename or scope the shadowing test package. |
| `packages/ai-parrot-tools/tests/google/conftest.py` | (vi) | test package `google` shadows the installed `google` namespace | Rename or scope the shadowing test package. |
| `packages/ai-parrot/tests/mcp/conftest.py` | (vi) | test package `mcp` shadows the installed `mcp` package | Rename or scope the shadowing test package. |
| `packages/ai-parrot/tests/unit/auth/test_eval_context.py` | (vii) | derived identity `auth.test_eval_context` fails during whole-tree collection | Stop and revise strategy; retained nested packages do not have stable unique identities. |
| `packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py` | (vii) | derived identity `auth.test_pbac_fail_closed` fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/auth/test_permission_context_trace.py` | (vii) | derived identity `auth.test_permission_context_trace` fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/auth/test_system_account.py` | (vii) | derived identity `auth.test_system_account` fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/bots/conftest.py` | (vii) | derived identity `bots.conftest` fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_client_emits_agent_name.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_core_has_no_sdk_pins.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_core_independence.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_emit_round_event.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_extend_path_merges_satellite.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_factory_discovery.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_invoke_budget_exhausted.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/clients/test_tool_error_message.py` | (vii) | derived `clients.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py` | (vii) | derived `handlers.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/handlers/test_artifact_html_serving.py` | (vii) | derived `handlers.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/handlers/test_csp_helper.py` | (vii) | derived `handlers.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/compaction/` | (vii) | derived `memory.compaction` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/test_conversation_turn_attribution.py` | (vii) | derived `memory.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/test_history_ownership.py` | (vii) | derived `memory.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/test_legacy_rekey.py` | (vii) | derived `memory.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/test_redis_history_ttl.py` | (vii) | derived `memory.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/memory/test_render_history.py` | (vii) | derived `memory.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_chart_config_convergence.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_completion_usage_add.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_infographic_display_hints.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_infographic_display_hints_prompt.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_jsbundle.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_output_mode_infographic.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_search_origin_models.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_structured_chart_config_types.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/models/test_template_js_bundles.py` | (vii) | derived `models.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/observability/conftest.py` | (vii) | derived `observability.conftest` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_actions.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_elements.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_init.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_inputs.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_markdown.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_renderer.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_sections.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/cards/test_toggle.py` | (vii) | derived `outputs.cards.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/test_builders_metadata.py` | (vii) | derived `outputs.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/test_formats_infographic_html_renderer.py` | (vii) | derived `outputs.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/test_lowering_optional_propagation.py` | (vii) | derived `outputs.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/outputs/test_recipe_section_descriptor.py` | (vii) | derived `outputs.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_cache.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_llm_helper.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_models.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_ontology_signal.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_rules.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_store_router.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/routing/test_yaml_loader.py` | (vii) | derived `registry.routing.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/test_capabilities_models.py` | (vii) | derived `registry.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/test_events_yaml.py` | (vii) | derived `registry.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/registry/test_no_parrot_tools_import.py` | (vii) | derived `registry.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/rerankers/conftest.py` | (vii) | derived `rerankers.conftest` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/security/test_groundedness_extractors.py` | (vii) | derived `security.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/security/test_groundedness_guardrail.py` | (vii) | derived `security.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/security/test_groundedness_normalize.py` | (vii) | derived `security.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/security/test_groundedness_scorer.py` | (vii) | derived `security.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/storage/test_artifactstore_public_url.py` | (vii) | derived `storage.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/storage/test_overflow_presigned.py` | (vii) | derived `storage.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/stores/conftest.py` | (vii) | derived `stores.conftest` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_adhoc_dataset_adapter.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_enhance_html_check.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_financial_variance.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_sections.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_aux.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_enhance.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_internal_tool_exclusion.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py` | (vii) | derived `tools.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/utils/test_requestcontext_fields.py` | (vii) | derived `utils.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/utils/test_secure_path.py` | (vii) | derived `utils.*` identity fails | Stop and revise strategy. |
| `packages/ai-parrot/tests/utils/test_tty.py` | (vii) | derived `utils.*` identity fails | Stop and revise strategy. |

## 4. Per-class tally

| Class | Round 2 (2026-10-01) | This run | Owning task |
|---|---:|---:|---|
| (i) `from tests.<x>` | 34 files | 27 new collection errors; 34 source files still contain such imports | 4592 / 4593 / 4594 |
| (ii) relative, no parent package | — | 3 | per dist |
| (iii) prepend-mode `sys.path` | — | 1 | per dist |
| (iv) relative imports in test files | 343 / 231 files | 5 errors | expected 0 changes; assumption disproved |
| (v) dotted string targets | 68 | 0 collection errors; 68 latent runtime targets remain | 4592 / 4593 |
| (vi) test packages shadowing installed packages | 1 | 4 errors across 3 shadowing directories | 4594 |
| **(vii) retained nested package identities fail in whole-tree collection** | — | **89** | **new class; spec revision required** |

The class counts sum to all 129 new errors: 27 + 3 + 1 + 5 + 0 + 4 + 89.

## 5. Open question from round 2

**Does `packages/ai-parrot`'s `--collect-only` exit 4 pre-exist strategy (a)?**

No. On current `dev`, the baseline is rc=0 with 25,328 items. Strategy (a) changes that root to rc=2 with 23,117
items and 113 collection errors. The historical exit-4 symptom does not pre-exist the change; its exact return code is
not reproduced today, but its underlying ai-parrot collection breakage is attributable to strategy (a), including the
new class (vii). This is not a separate baseline issue.

`consider_namespace_packages` was not tested or adopted: strategy (a) itself failed its required unchanged-count gate,
and the task requires a spec revision rather than silently extending the strategy.

## 6. Revert confirmation

The 25 empty top-level initializers were restored, `--import-mode=importlib` was removed, and the initializer counts
returned to 25 top-level / 267 total.

```text
$ git status --porcelain
?? sdd/state/FEAT-720/spike-collect.md
```

## 7. Verdict

STRATEGY (a) REFUTED — 129 new collection errors, 2,711 fewer items, and new class (vii) from unstable retained nested-package identities
