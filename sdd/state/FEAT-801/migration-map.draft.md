---
title: FEAT-801 migration map — DRAFT (TASK-5172)
status: draft — pending human approval
generated: 2026-11-05
---

# FEAT-801 migration map (draft for TASK-5172)

Generated mechanically from the TASK-5172 classification rule + `mkdocs.yml` nav + a repo-wide reference scan. **Nothing has been moved.** Items marked `?` / PROPOSED need a decision.

## Totals

- Files under `docs/`: **366**  — stays: **91**, moves (rule): **178**, moves (proposed, not in nav): **97**
- Moving pages referenced from outside `docs/`: **87** (161 referencing files, of which **39 distinct test files** assert/depend on the old path)

## Decisions needed (before executing)

1. **Unlisted pages (98).** mkdocs publishes every `.md` under `docs/` even if absent from `nav`. The rule only says "reachable from nav". Proposed: treat them as technical reference and **move** (marked `moves?`). Alternative: leave them on Pages.
2. **Path-pinned consumers.** Tests/code reference moved paths (see *Consumers*). Either rewrite them to `wiki/<section>/<page>.md` (touches ~dozens of files outside `docs/`, beyond the task's listed files) or treat those pages as local workflow contracts that **stay** (then the AC "technical reference moves" shrinks). Recommend: split TASK-5172 into (a) move + rewrite docs-only consumers, (b) a follow-up that updates test/code consumers, run together in one PR.
3. **`getting-started.md`** proposed to **stay** (CI + `INSTALL.md` link to it).
4. **Unsectioned pages** given a provisional section: `aws_deployment`→operations, `datasetmanager_design`→tools, `whatif_scenarios`→tools, all `dev_loop/*`→sdd-tooling. Confirm.
5. **Non-markdown assets** (docx, html, png, pdf, docker-compose.yml) all **stay** — not nav pages, not wiki content.
6. **Translation (AC-15)** — moving pages detected as predominantly Spanish (heuristic, review manually):
   - `docs/aws_deployment.md`
   - `docs/dev_loop/sdd-execution-optimizations.md`
   - `docs/documentdb.md`
   - `docs/formdesigner-audio-renderer.md`
   - `docs/frontend/agentalk-voice-frontend-guide.md`
   - `docs/frontend/liveavatar-frontend-guide.md`
   - `docs/frontend/liveavatar-fullmode-sveltekit-guide.md`
   - `docs/frontend/liveavatar-phase-c-frontend-guide.md`
   - `docs/frontend/structured-artifacts-frontend-guide.md`
   - `docs/frontend/voicebot-realtime-frontend-guide.md`
   - `docs/guia-fireflies.md`
   - `docs/local_kb.md`
   - `docs/messaging/implement-whatsapp.md`
   - `docs/pandas-agent-capabilities.md`
   - `docs/sdd/GUIDE.md`
   - `docs/wiki/cheatsheet.md`
   - Stays but Spanish: `docs/parrot_roadmap_2026.md` (no translation required).

7. **Hyphenated titles (blocking for the bundle).** `page_name` raises `PageNameError` for any title containing a literal `-` (GitHub would store U+2010 and break `[[links]]`). **139 of the 275 moving pages** (see Appendix A) have such a title (e.g. `AI-Parrot`, `anti-prompt-injection`, `Follow-up`). Each needs a hyphen-free `title:` frontmatter added during the move; this is content editing on top of `git mv` and is the largest hidden cost of TASK-5172.

## Stays on Pages

**non-markdown asset (not a nav page)** (29)
  `FilesystemTransport_Spec.docx`, `Part Order Guide.png`, `agent_service_architecture.mermaid`, `09-ontologic-rag.pdf`, `apprunner.yaml`, `Dockerfile`, `deploy-mcp-aws.sh`, `docker-compose.yml`, `fargate-task-definition.json`, `Dockerfile`, `ai-parrot-wordmark-on-dark.svg`, `parrot-mono-dark.svg`, `parrot-mono-light.svg`, `parrot-transparent.png`, `parrot.svg`, `docker-compose.yml`, `passkey.settings.example`, `flex_program_report (39).html`, `infographic-1775694709159.html`, `infographic-1776263903716.html`, `pandas-agent-capabilities.docx`, `pandas-agent-capabilities.html`, `parrot_delta_mckinsey.docx`, `parrot_roadmap_resumen.docx`, `photo_2026-05-30_02-59-09.jpg`, `AgentCrew_API_Collection.json`, `a2ui-agentdashboard.postman_collection.json`, `lsp-pilot-live-run-summary.json`, `viba-troc-intelligence-system-architecture.pdf`

**classification rule (Pages-resident)** (60)
  `docs/INSTALL.md`, `docs/STYLE_GUIDE.md`, `docs/api-reference` ×10, `docs/chapters` ×7, `docs/config.md`, `docs/decisions` ×9, `docs/examples`, `docs/execution_plan`, `docs/guides` ×6, `docs/index.md`, `docs/parrot_roadmap_2026.md`, `docs/product-analysis`, `docs/sdd`, `docs/superpowers/plans` ×6, `docs/superpowers/specs` ×11, `docs/tools_quick.md`, `docs/web-hitl-frontend-brainstorm.md`

**PROPOSED: user-facing onboarding; referenced by ci.yml and INSTALL.md** (1)
  `docs/getting-started.md`

**@-included by CLAUDE.md** (1)
  `docs/sdd`

## Moves (file → wiki page)

Destination file: `wiki/<section>/<source file name>.md` (kept stable for `git mv` history). The published **wiki page name** is derived by `parrot.sdd.techwiki.naming.page_name(section, page_title)` — i.e. from the page *title* (frontmatter `title:`, else first H1, else stem), **not** from the path. `?` = proposed (not in nav).

### Architecture (`wiki/architecture/`) — 15

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/CLASSES.md` |  |  |
| `docs/FUNCTIONS.md` |  |  |
| `docs/agent_mesh.md` |  |  |
| `docs/agent_service.md` |  |  |
| `docs/architecture/01-mcp-server.md` |  |  |
| `docs/architecture/02-a2a.md` |  |  |
| `docs/architecture/03-toolkits.md` |  |  |
| `docs/architecture/04-interaction-surface.md` |  |  |
| `docs/architecture/05-hardening.md` |  |  |
| `docs/architecture/06-cross-cutting.md` |  |  |
| `docs/architecture/07-agentcrew.md` |  |  |
| `docs/architecture/08-agentsflow-dag.md` |  |  |
| `docs/architecture/09-ontologic-rag.md` |  |  |
| `docs/architecture/10-observability.md` |  | 4 (1 test) |
| `docs/architecture/README.md` |  |  |

### Clients (`wiki/clients/`) — 6

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/clients/bedrock-mantle.md` |  |  |
| `docs/clients/jev.md` |  |  |
| `docs/clients/meta.md` | ? |  |
| `docs/clients/openai-compatible.md` |  |  |
| `docs/clients/per-loop-cache.md` |  | 3 (2 test) |
| `docs/clients/token-budgets.md` | ? |  |

### Bots & Agents (`wiki/bots/`) — 29

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/agent-configure-lifecycle.md` | ? | 2 (1 test) |
| `docs/agent.md` |  |  |
| `docs/agent_config_creation.md` |  | 1 (1 test) |
| `docs/agent_factory_handler.md` |  |  |
| `docs/agent_studio_api.md` | ? | 1 (1 test) |
| `docs/agentd.md` |  | 1 (0 test) |
| `docs/agents/fireflies-insights.md` | ? |  |
| `docs/agents/followup-suggestion-chips.md` | ? |  |
| `docs/agentstudio/db-storage.md` | ? | 1 (1 test) |
| `docs/api/feat-149-ephemeral-agents-api.md` |  |  |
| `docs/cli/parrot-agent.md` | ? | 1 (1 test) |
| `docs/crew_handler.md` |  | 2 (1 test) |
| `docs/database-agent.md` |  |  |
| `docs/features/feat-437-claude-bedrock-sample-agents.md` |  |  |
| `docs/frontend/agentalk-voice-frontend-guide.md` |  |  |
| `docs/frontend/agentdashboard-a2ui-reference.md` | ? | 2 (1 test) |
| `docs/integrations/msagentsdk-semantic-cards.md` |  |  |
| `docs/mcp/agent-as-mcp-server.md` | ? |  |
| `docs/orchestration/agentcrew.md` |  |  |
| `docs/orchestration/agentsflow.md` |  |  |
| `docs/outputs/a2ui-agent-functions.md` |  | 1 (1 test) |
| `docs/pandas-agent-capabilities.md` |  |  |
| `docs/security/agent-security-guardrails.md` | ? |  |
| `docs/spawn_subagent_tool.md` |  |  |
| `docs/testagent.md` |  |  |
| `docs/testing/agentic-e2e.md` | ? |  |
| `docs/uiagent.md` |  |  |
| `docs/web-agent.md` |  |  |
| `docs/web-navigator-agent.md` |  |  |

### Memory (`wiki/memory/`) — 6

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/EXECUTION_MEMORY.md` |  | 1 (0 test) |
| `docs/dream-cycle.md` |  |  |
| `docs/memory/conversation-history-ownership.md` | ? | 1 (0 test) |
| `docs/memory/per-turn-conversation-compaction.md` | ? | 1 (0 test) |
| `docs/memory/recoverable-task-memory.md` | ? |  |
| `docs/memory/task-memory-integration-map.md` | ? |  |

### Knowledge (`wiki/knowledge/`) — 10

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/bookstore-codex.md` | ? |  |
| `docs/bookstore-graph.md` | ? | 1 (0 test) |
| `docs/graphindex.md` |  |  |
| `docs/graphindex/core-seams.md` | ? |  |
| `docs/knowledge/contracts-performance.md` | ? | 1 (1 test) |
| `docs/knowledge/contracts-pilot-acceptance.md` | ? |  |
| `docs/knowledge/contracts.md` | ? | 2 (0 test) |
| `docs/knowledge/manuals.md` | ? |  |
| `docs/local_kb.md` |  |  |
| `docs/pageindex.md` |  |  |

### Tools & Toolkits (`wiki/tools/`) — 30

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/ARXIV_TOOL_README.md` |  |  |
| `docs/datasetmanager_design.md` |  |  |
| `docs/fred_api_tool.md` |  |  |
| `docs/hierarchy_tool.md` |  |  |
| `docs/hooba-toolkit.md` | ? |  |
| `docs/mcp-local-toolkits.md` | ? | 2 (1 test) |
| `docs/multistoresearch-toolkit.md` |  |  |
| `docs/obscura-headless-browser.md` | ? | 1 (1 test) |
| `docs/odoo_toolkit_capabilities.md` |  |  |
| `docs/repl-worker-sandbox.md` |  | 1 (0 test) |
| `docs/research_tools.md` |  |  |
| `docs/sandbox_tool.md` |  |  |
| `docs/sdd/sandbox-setup.md` |  | 2 (0 test) |
| `docs/tool-optimizations.md` | ? |  |
| `docs/tool_clone.md` |  |  |
| `docs/toolbar-api.md` |  |  |
| `docs/toolkits/audio_note_capture.md` |  |  |
| `docs/toolkits/execution_plan_toolkit.md` |  |  |
| `docs/toolkits/host-toolkits.md` | ? |  |
| `docs/toolkits/infographic_authoring.md` |  |  |
| `docs/toolkits/infographic_toolkit.md` |  | 1 (0 test) |
| `docs/tools.md` |  | 1 (0 test) |
| `docs/tools/compression.md` |  | 3 (2 test) |
| `docs/tools/jira-templates.md` | ? |  |
| `docs/tools/odoo-helpdesk.md` | ? |  |
| `docs/tools/querysource-toolkit.md` | ? | 2 (2 test) |
| `docs/tools/readonly-repo-toolkit.md` | ? |  |
| `docs/tools/semantic-layer.md` | ? | 2 (0 test) |
| `docs/tools/workday-worker-history.md` | ? |  |
| `docs/whatif_scenarios.md` |  |  |

### Flows (`wiki/flows/`) — 11

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/DECISION_NODE_USAGE.md` |  |  |
| `docs/executors/docker-executor.md` |  | 1 (0 test) |
| `docs/flows/thales.md` |  |  |
| `docs/heartbeat_manager.md` |  |  |
| `docs/jobmanager.md` |  |  |
| `docs/orchestration/node-types.md` |  |  |
| `docs/orchestrator-conferencing.md` |  |  |
| `docs/pipelines/planogram-compliance-cycle.md` | ? | 1 (0 test) |
| `docs/pipelines/planogram-cycle-migration.md` | ? | 7 (0 test) |
| `docs/pipelines/planogram-perception-spike.md` | ? | 2 (0 test) |
| `docs/scheduler/multi-worker.md` | ? |  |

### Skills (`wiki/skills/`) — 1

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/skills/per-tenant-skills.md` | ? | 1 (0 test) |

### Stores & Loaders (`wiki/stores/`) — 11

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/contextual-embedding.md` |  |  |
| `docs/documentdb.md` |  |  |
| `docs/documentdb_interface.md` |  |  |
| `docs/dynamodb-local.md` |  | 1 (0 test) |
| `docs/lancedb-offline-profile.md` | ? | 1 (0 test) |
| `docs/lancedb-vector-store.md` | ? |  |
| `docs/loaders-metadata.md` |  |  |
| `docs/matryoshka-embeddings.md` |  |  |
| `docs/parent-child-retrieval.md` |  |  |
| `docs/storage-backends.md` |  | 7 (0 test) |
| `docs/vectorstore_handler_api.md` |  |  |

### MCP & A2A (`wiki/mcp/`) — 9

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/a2a_communication.md` |  |  |
| `docs/install-mcp-genmedia.md` |  |  |
| `docs/install_github_mcp.md` |  |  |
| `docs/mcp_session.md` |  |  |
| `docs/roost/README.md` | ? |  |
| `docs/roost/carriers.md` | ? |  |
| `docs/roost/performatives.md` | ? |  |
| `docs/simple_mcp_server.md` |  |  |
| `docs/simple_mcp_server_config.md` |  |  |

### Server & APIs (`wiki/server/`) — 20

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/API_ENDPOINTS.md` |  |  |
| `docs/admin-ui.md` | ? | 3 (0 test) |
| `docs/api/infographic_render.md` |  | 2 (0 test) |
| `docs/events/eventbus-config.md` |  |  |
| `docs/events/eventbus-migration.md` |  |  |
| `docs/events/eventbus-v2.md` |  |  |
| `docs/files/session-file-store.md` | ? |  |
| `docs/frontend/a2ui-dashboard-widget-renderer-guide.md` | ? |  |
| `docs/frontend/liveavatar-frontend-guide.md` |  |  |
| `docs/frontend/liveavatar-fullmode-sveltekit-guide.md` |  |  |
| `docs/frontend/liveavatar-phase-c-frontend-guide.md` |  |  |
| `docs/frontend/structured-artifacts-frontend-guide.md` |  | 1 (1 test) |
| `docs/frontend/voicebot-realtime-frontend-guide.md` |  |  |
| `docs/infographic_handler_api.md` |  | 1 (0 test) |
| `docs/interactive_artifacts_api.md` |  | 1 (0 test) |
| `docs/interfaces/gdrive-filemanager.md` | ? | 1 (1 test) |
| `docs/interfaces/graph-filemanager.md` | ? |  |
| `docs/messaging/implement-whatsapp.md` |  |  |
| `docs/messaging/whatsapp.md` |  |  |
| `docs/report-builder/inventory/P3-parrot-admin-ui.md` | ? |  |

### Integrations (`wiki/integrations/`) — 35

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/WHATSAPP_AUTONOMOUS_ORCHESTRATOR.md` |  |  |
| `docs/audio-form-voice-modes.md` |  | 1 (1 test) |
| `docs/auth/jira-credential-ownership.md` | ? | 2 (1 test) |
| `docs/comm_center.md` |  |  |
| `docs/formdesigner-msteams-renderer.md` | ? | 1 (0 test) |
| `docs/github-reviewer.md` |  |  |
| `docs/guia-fireflies.md` |  |  |
| `docs/hitl-confirmation.md` |  |  |
| `docs/hitl-teams-channel.md` |  |  |
| `docs/integrations/google-oauth2.md` | ? | 1 (1 test) |
| `docs/integrations/knowledge-upload.md` | ? |  |
| `docs/integrations/matrix/BRIDGES.md` | ? | 7 (1 test) |
| `docs/integrations/matrix/CLIENTS.md` | ? | 2 (1 test) |
| `docs/integrations/msteams-connections.md` | ? |  |
| `docs/integrations/office365-oauth2.md` |  | 2 (0 test) |
| `docs/integrations/slack-devloop.md` | ? | 1 (0 test) |
| `docs/integrations/telegram-connections.md` | ? |  |
| `docs/jira-specialist-prompt-layers.md` |  |  |
| `docs/jira-standup.md` | ? |  |
| `docs/jira-transition-actions.md` |  |  |
| `docs/jupyter_mode.md` |  |  |
| `docs/liveavatar-byo-livekit.md` |  |  |
| `docs/migration/feat-202-ai-parrot-integrations.md` |  | 1 (0 test) |
| `docs/msteams.md` |  |  |
| `docs/nova_voice_protocol.md` |  | 2 (0 test) |
| `docs/pr-review-setup.md` |  |  |
| `docs/runbooks/jira-issues-namespace.md` |  |  |
| `docs/telegram_integration.md` |  |  |
| `docs/testing/voicebot-liveavatar-acceptance.md` | ? | 1 (0 test) |
| `docs/testing/voicebot-multiroom-heygen-avatar-acceptance.md` | ? |  |
| `docs/testing/voicebot-multiroom-live-gate.md` | ? | 3 (2 test) |
| `docs/voice/speech-report-tts-backends.md` | ? |  |
| `docs/voice/voicebot-multiroom-heygen-avatar.md` | ? | 1 (0 test) |
| `docs/voice_chat.md` |  |  |
| `docs/whisperx.md` |  |  |

### Outputs & A2UI (`wiki/outputs/`) — 27

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/charts_samples.md` |  |  |
| `docs/design-system.md` | ? |  |
| `docs/formdesigner-audio-renderer.md` |  |  |
| `docs/formdesigner-autonomous-persistence.md` |  |  |
| `docs/formdesigner-conditional-sections.md` |  |  |
| `docs/formdesigner-llm-validation-enforcement.md` | ? |  |
| `docs/formdesigner-orphan-upload-cleanup.md` | ? |  |
| `docs/formdesigner-public-form-controls.md` | ? |  |
| `docs/formdesigner-relational-fields.md` |  | 1 (1 test) |
| `docs/formdesigner-serve-forms.md` | ? |  |
| `docs/formdesigner-unknown-fields-capture.md` | ? |  |
| `docs/formdesigner-validation-audit-trail.md` | ? |  |
| `docs/outputs.md` |  |  |
| `docs/outputs/a2ui-linked-surfaces.md` | ? | 2 (2 test) |
| `docs/outputs/a2ui-v1.md` |  | 4 (0 test) |
| `docs/outputs/infographic-recipes.md` |  | 2 (0 test) |
| `docs/outputs/inline-a2ui-component-routing.md` | ? |  |
| `docs/outputs/metric-registry.md` | ? |  |
| `docs/report-builder/inventory-and-analysis.md` | ? |  |
| `docs/report-builder/inventory/N4-navigator-api-backend.md` | ? |  |
| `docs/report-builder/inventory/P1-parrot-endpoints.md` | ? |  |
| `docs/report-builder/inventory/P2-parrot-components-models.md` | ? |  |
| `docs/report-builder/inventory/P4-parrot-prior-art.md` | ? |  |
| `docs/report-builder/inventory/_admin_bots.md` | ? |  |
| `docs/report-builder/inventory/_core.md` | ? |  |
| `docs/report-builder/inventory/_formdesigner.md` | ? |  |
| `docs/weasyprint-css-support.md` | ? | 2 (1 test) |

### Prompts (`wiki/prompts/`) — 5

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/promptbuilder-variables.md` |  |  |
| `docs/prompts/identity-capability.md` |  |  |
| `docs/prompts/layers-reference.md` |  |  |
| `docs/prompts/output-language.md` | ? | 2 (0 test) |
| `docs/prompts/promptbuilder.md` |  |  |

### Security (`wiki/security/`) — 7

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/auth/connections.md` | ? | 2 (2 test) |
| `docs/auth/delegated-auth-web-deployment.md` | ? |  |
| `docs/groundedness.md` |  |  |
| `docs/security-advisor.md` |  |  |
| `docs/security/onnx-injection-guardrail.md` |  | 2 (0 test) |
| `docs/security/pbac-guardrails.md` |  | 4 (1 test) |
| `docs/user-profile.md` |  |  |

### Operations (`wiki/operations/`) — 11

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/aws_deployment.md` |  |  |
| `docs/bot-cleanup-lifecycle.md` |  |  |
| `docs/business-automation-runbook.md` |  | 1 (0 test) |
| `docs/cli/parrot-login-and-connections.md` | ? | 1 (1 test) |
| `docs/company_info.md` |  |  |
| `docs/configuration/llm-defaults.md` | ? |  |
| `docs/eval/answer-accuracy-metrics.md` | ? |  |
| `docs/install/global-runtime.md` | ? | 1 (0 test) |
| `docs/operations/infographic_csp_and_signed_urls.md` |  |  |
| `docs/runbooks/fireflies-meeting-registry.md` | ? |  |
| `docs/runbooks/wiki-standup.md` | ? | 1 (1 test) |

### Migration (`wiki/migration/`) — 12

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/migration/ai-parrot-finance.md` |  |  |
| `docs/migration/feat-201-ai-parrot-embeddings.md` |  | 1 (0 test) |
| `docs/migration/feat-203-ai-parrot-server.md` |  | 1 (0 test) |
| `docs/migration/feat-223-structured-artifact-contract.md` |  |  |
| `docs/migration/feat-273-a2ui-deprecations.md` |  | 1 (0 test) |
| `docs/migration/feat-315-novaclient.md` |  | 1 (0 test) |
| `docs/migration/feat-421-forms-tenant-in-url.md` |  | 1 (0 test) |
| `docs/migration/feat-446-saas-auth-hardening.md` |  |  |
| `docs/migration/feat-473-structured-a2ui.md` |  |  |
| `docs/migration/feat-523-llm-client-satellites.md` |  |  |
| `docs/migration/gemini-2-5-retirement.md` |  | 1 (1 test) |
| `docs/migration/video-reel-omni-veo-reliability.md` |  | 2 (1 test) |

### SDD Tooling (`wiki/sdd-tooling/`) — 19

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/dev_loop/claude-native-sandbox.md` |  | 4 (1 test) |
| `docs/dev_loop/complementary-research.md` |  |  |
| `docs/dev_loop/dev-flow-model-plan.md` |  | 2 (0 test) |
| `docs/dev_loop/nova-backend.md` |  |  |
| `docs/dev_loop/sdd-coder-orchestrator.md` |  | 2 (0 test) |
| `docs/dev_loop/sdd-compaction-capabilities.md` |  |  |
| `docs/dev_loop/sdd-execution-optimization.md` |  |  |
| `docs/dev_loop/sdd-execution-optimizations.md` |  |  |
| `docs/dev_loop/telemetry-accounting.md` |  |  |
| `docs/dev_loop/validation-runners.md` |  | 1 (1 test) |
| `docs/sdd/ANTIGRAVITY.md` |  |  |
| `docs/sdd/GUIDE.md` |  |  |
| `docs/sdd/PLATFORM.md` |  | 1 (1 test) |
| `docs/sdd/closeout-hooks.md` |  | 1 (0 test) |
| `docs/sdd/decision-audit.md` |  | 1 (0 test) |
| `docs/sdd/ledger-outbox.md` |  | 4 (1 test) |
| `docs/sdd/lsp-pilot-results.md` |  | 2 (2 test) |
| `docs/sdd/lsp-pilot.md` |  | 4 (1 test) |
| `docs/sdd/test-selection-validation-contract.md` |  | 1 (1 test) |

### LLM Wiki (`wiki/wiki/`) — 7

| Source | | Consumers outside docs/ |
|---|---|---|
| `docs/llm-wiki.md` |  |  |
| `docs/wiki-claude-code.md` |  |  |
| `docs/wiki/cheatsheet.md` |  | 1 (1 test) |
| `docs/wiki/inbox.md` |  |  |
| `docs/wiki/lint.md` |  |  |
| `docs/wiki/schema-plane.md` |  | 1 (1 test) |
| `docs/wiki/standup.md` |  |  |

## Consumers that pin a moved path (rewrite or exception)

| Moved page | Referencing file | Kind |
|---|---|---|
| `docs/EXECUTION_MEMORY.md` | `artifacts/plan_execution_memory_integration.md` | doc |
| `docs/admin-ui.md` | `packages/ai-parrot-server/README.md` | doc |
| `docs/admin-ui.md` | `packages/ai-parrot-server/ui/src/lib/features.ts` | code/config |
| `docs/admin-ui.md` | `packages/ai-parrot-server/ui/vite.config.ts` | code/config |
| `docs/agent-configure-lifecycle.md` | `packages/ai-parrot/src/parrot/bots/abstract.py` | code/config |
| `docs/agent-configure-lifecycle.md` | `packages/ai-parrot/tests/bots/test_configure_override_guards.py` | test |
| `docs/agent_config_creation.md` | `packages/ai-parrot-server/tests/test_feat593_docs.py` | test |
| `docs/agent_studio_api.md` | `packages/ai-parrot-server/tests/test_feat593_docs.py` | test |
| `docs/agentd.md` | `examples/agents/claude_code_daemon.yaml` | code/config |
| `docs/agentstudio/db-storage.md` | `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | test |
| `docs/api/infographic_render.md` | `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | code/config |
| `docs/api/infographic_render.md` | `packages/ai-parrot/src/parrot/conf.py` | code/config |
| `docs/architecture/10-observability.md` | `docker/grafana/README.md` | doc |
| `docs/architecture/10-observability.md` | `env/.env.observability.example` | doc |
| `docs/architecture/10-observability.md` | `packages/ai-parrot/src/parrot/observability/README.md` | doc |
| `docs/architecture/10-observability.md` | `packages/ai-parrot/tests/unit/observability/test_env_contract.py` | test |
| `docs/audio-form-voice-modes.md` | `packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py` | test |
| `docs/auth/connections.md` | `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` | test |
| `docs/auth/connections.md` | `packages/ai-parrot/tests/unit/auth/test_legacy_audit.py` | test |
| `docs/auth/jira-credential-ownership.md` | `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | code/config |
| `docs/auth/jira-credential-ownership.md` | `packages/ai-parrot/tests/unit/auth/test_legacy_audit.py` | test |
| `docs/bookstore-graph.md` | `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | code/config |
| `docs/business-automation-runbook.md` | `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` | code/config |
| `docs/cli/parrot-agent.md` | `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` | test |
| `docs/cli/parrot-login-and-connections.md` | `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` | test |
| `docs/clients/per-loop-cache.md` | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | code/config |
| `docs/clients/per-loop-cache.md` | `packages/ai-parrot-client-google/tests/unit/test_client_lifecycle_contract.py` | test |
| `docs/clients/per-loop-cache.md` | `packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py` | test |
| `docs/crew_handler.md` | `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | code/config |
| `docs/crew_handler.md` | `packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py` | test |
| `docs/design/luau-parser-resource-policy.md` | `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau.py` | code/config |
| `docs/design/luau-parser-resource-policy.md` | `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau_guard.py` | code/config |
| `docs/design/luau-parser-resource-policy.md` | `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/project.py` | code/config |
| `docs/design/luau-parser-resource-policy.md` | `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/references.py` | code/config |
| `docs/design/luau-parser-resource-policy.md` | `scripts/benchmarks/luau_parser_limits.py` | code/config |
| `docs/design/luau-parser-resource-policy.md` | `tests/knowledge/wiki/languages/test_luau.py` | test |
| `docs/design/luau-parser-resource-policy.md` | `tests/knowledge/wiki/roblox/test_reference_candidates.py` | test |
| `docs/dev_loop/claude-native-sandbox.md` | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | code/config |
| `docs/dev_loop/claude-native-sandbox.md` | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | code/config |
| `docs/dev_loop/claude-native-sandbox.md` | `packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py` | test |
| `docs/dev_loop/claude-native-sandbox.md` | `pyproject.toml` | code/config |
| `docs/dev_loop/dev-flow-model-plan.md` | `examples/dev_loop/GUIA.md` | doc |
| `docs/dev_loop/dev-flow-model-plan.md` | `examples/dev_loop/README.md` | doc |
| `docs/dev_loop/sdd-coder-orchestrator.md` | `.agent/CONTEXT.md` | doc |
| `docs/dev_loop/sdd-coder-orchestrator.md` | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | code/config |
| `docs/dev_loop/validation-runners.md` | `tests/sdd_scripts/test_feat709_doc_contract.py` | test |
| `docs/dynamodb-local.md` | `docker-compose.dynamodb.yml` | code/config |
| `docs/executors/docker-executor.md` | `Makefile` | doc |
| `docs/formdesigner-msteams-renderer.md` | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` | code/config |
| `docs/formdesigner-relational-fields.md` | `packages/parrot-formdesigner/tests/integration/test_relational_forms.py` | test |
| `docs/frontend/agentdashboard-a2ui-reference.md` | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` | code/config |
| `docs/frontend/agentdashboard-a2ui-reference.md` | `packages/ai-parrot/tests/integration/test_frontend_guide_examples.py` | test |
| `docs/frontend/structured-artifacts-frontend-guide.md` | `packages/ai-parrot/tests/integration/test_frontend_guide_examples.py` | test |
| `docs/infographic_handler_api.md` | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` | code/config |
| `docs/install/global-runtime.md` | `INSTALL.md` | doc |
| `docs/integrations/google-oauth2.md` | `packages/ai-parrot/tests/test_gdrive_docs.py` | test |
| `docs/integrations/matrix/BRIDGES.md` | `docker-compose.matrix.yml` | code/config |
| `docs/integrations/matrix/BRIDGES.md` | `docker/matrix/bridges/discord/config.yaml` | code/config |
| `docs/integrations/matrix/BRIDGES.md` | `docker/matrix/bridges/signal/config.yaml` | code/config |
| `docs/integrations/matrix/BRIDGES.md` | `docker/matrix/bridges/slack/config.yaml` | code/config |
| `docs/integrations/matrix/BRIDGES.md` | `examples/matrix_crew/MATRIX_CREW_GUIDE.md` | doc |
| `docs/integrations/matrix/BRIDGES.md` | `packages/ai-parrot-integrations/tests/test_matrix_swarm_example.py` | test |
| `docs/integrations/matrix/BRIDGES.md` | `scripts/matrix/bootstrap.sh` | doc |
| `docs/integrations/matrix/CLIENTS.md` | `examples/matrix_crew/MATRIX_CREW_GUIDE.md` | doc |
| `docs/integrations/matrix/CLIENTS.md` | `packages/ai-parrot-integrations/tests/test_matrix_swarm_example.py` | test |
| `docs/integrations/office365-oauth2.md` | `examples/agents/oauth/demo_operator.py` | code/config |
| `docs/integrations/office365-oauth2.md` | `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | code/config |
| `docs/integrations/slack-devloop.md` | `examples/dev_loop/README.md` | doc |
| `docs/interactive_artifacts_api.md` | `packages/ai-parrot-server/ui/src/lib/types/agent.ts` | code/config |
| `docs/interfaces/gdrive-filemanager.md` | `packages/ai-parrot/tests/test_gdrive_docs.py` | test |
| `docs/knowledge/contracts-performance.md` | `packages/ai-parrot/tests/knowledge/contracts/test_catalog_performance.py` | test |
| `docs/knowledge/contracts.md` | `agents/README.md` | doc |
| `docs/knowledge/contracts.md` | `artifacts/o365_delta_premerge_review.md` | doc |
| `docs/lancedb-offline-profile.md` | `examples/lancedb_local_agent.py` | code/config |
| `docs/mcp-local-toolkits.md` | `examples/mcp-toolkits.yaml` | code/config |
| `docs/mcp-local-toolkits.md` | `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` | test |
| `docs/memory/conversation-history-ownership.md` | `.agent/CONTEXT.md` | doc |
| `docs/memory/per-turn-conversation-compaction.md` | `.agent/CONTEXT.md` | doc |
| `docs/migration/feat-201-ai-parrot-embeddings.md` | `.agent/CONTEXT.md` | doc |
| `docs/migration/feat-202-ai-parrot-integrations.md` | `packages/ai-parrot-integrations/README.md` | doc |
| `docs/migration/feat-203-ai-parrot-server.md` | `packages/ai-parrot-server/README.md` | doc |
| `docs/migration/feat-273-a2ui-deprecations.md` | `examples/agents/a2ui/README.md` | doc |
| `docs/migration/feat-315-novaclient.md` | `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | code/config |
| `docs/migration/feat-421-forms-tenant-in-url.md` | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | code/config |
| `docs/migration/gemini-2-5-retirement.md` | `packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py` | test |
| `docs/migration/video-reel-omni-veo-reliability.md` | `packages/ai-parrot-client-google/pyproject.toml` | code/config |
| `docs/migration/video-reel-omni-veo-reliability.md` | `packages/ai-parrot-client-google/tests/live/test_reel_smoke.py` | test |
| `docs/nova_voice_protocol.md` | `examples/clients/nova/audio.py` | code/config |
| `docs/nova_voice_protocol.md` | `examples/clients/voice/static/app.js` | doc |
| `docs/obscura-headless-browser.md` | `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | test |
| `docs/outputs/a2ui-agent-functions.md` | `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py` | test |
| `docs/outputs/a2ui-linked-surfaces.md` | `packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py` | test |
| `docs/outputs/a2ui-linked-surfaces.md` | `packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py` | test |
| `docs/outputs/a2ui-v1.md` | `examples/agents/a2ui/README.md` | doc |
| `docs/outputs/a2ui-v1.md` | `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` | code/config |
| `docs/outputs/a2ui-v1.md` | `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` | code/config |
| `docs/outputs/a2ui-v1.md` | `packages/parrot-formdesigner/docs/a2ui-renderer.md` | doc |
| `docs/outputs/infographic-recipes.md` | `agents/flex_dashboard.py` | code/config |
| `docs/outputs/infographic-recipes.md` | `examples/infographic_recipes/budget-variance-daily.yaml` | code/config |
| `docs/pipelines/planogram-compliance-cycle.md` | `packages/ai-parrot-pipelines/README.md` | doc |
| `docs/pipelines/planogram-cycle-migration.md` | `.claude/commands/planogram-migrate.md` | doc |
| `docs/pipelines/planogram-cycle-migration.md` | `examples/planogram/e2e/README.md` | doc |
| `docs/pipelines/planogram-cycle-migration.md` | `packages/ai-parrot-pipelines/README.md` | doc |
| `docs/pipelines/planogram-cycle-migration.md` | `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` | code/config |
| `docs/pipelines/planogram-cycle-migration.md` | `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration_runner.py` | code/config |
| `docs/pipelines/planogram-cycle-migration.md` | `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | code/config |
| `docs/pipelines/planogram-cycle-migration.md` | `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | code/config |
| `docs/pipelines/planogram-perception-spike.md` | `examples/planogram/perception_spike/README.md` | doc |
| `docs/pipelines/planogram-perception-spike.md` | `examples/planogram/perception_spike/run_spike.py` | code/config |
| `docs/prompts/output-language.md` | `packages/ai-parrot/src/parrot/bots/jira_messages.py` | code/config |
| `docs/prompts/output-language.md` | `packages/ai-parrot/src/parrot/bots/prompts/language.py` | code/config |
| `docs/repl-worker-sandbox.md` | `artifacts/logs/feat-500-bootstrap-profile.md` | doc |
| `docs/runbooks/wiki-standup.md` | `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` | test |
| `docs/sdd/PLATFORM.md` | `tests/sdd/test_sdd_fix_docs.py` | test |
| `docs/sdd/closeout-hooks.md` | `sdd/templates/sdd_hooks.example.toml` | code/config |
| `docs/sdd/decision-audit.md` | `sdd/templates/spec.md` | doc |
| `docs/sdd/ledger-outbox.md` | `.agent/workflows/sdd-done.md` | doc |
| `docs/sdd/ledger-outbox.md` | `.agents/skills/sdd-done/SKILL.md` | doc |
| `docs/sdd/ledger-outbox.md` | `.claude/commands/sdd-done.md` | doc |
| `docs/sdd/ledger-outbox.md` | `tests/sdd/test_ledger_workflow_twins.py` | test |
| `docs/sdd/lsp-pilot-results.md` | `packages/ai-parrot-tools/tests/lsp/test_bedrock_mantle_seat.py` | test |
| `docs/sdd/lsp-pilot-results.md` | `packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py` | test |
| `docs/sdd/lsp-pilot.md` | `benchmarks/sdd_lsp/seats/tools.py` | code/config |
| `docs/sdd/lsp-pilot.md` | `examples/lsp-mcp.yaml` | code/config |
| `docs/sdd/lsp-pilot.md` | `packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py` | test |
| `docs/sdd/lsp-pilot.md` | `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml` | code/config |
| `docs/sdd/sandbox-setup.md` | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | code/config |
| `docs/sdd/sandbox-setup.md` | `packages/ai-parrot/src/parrot/self_/doctor.py` | code/config |
| `docs/sdd/test-selection-validation-contract.md` | `tests/sdd_scripts/test_feat699_budget_doc.py` | test |
| `docs/security/onnx-injection-guardrail.md` | `Makefile` | doc |
| `docs/security/onnx-injection-guardrail.md` | `benchmarks/injection_guardrail_latency/compare_models.py` | code/config |
| `docs/security/pbac-guardrails.md` | `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | code/config |
| `docs/security/pbac-guardrails.md` | `packages/ai-parrot/tests/integration/test_pbac_guardrails_e2e.py` | test |
| `docs/security/pbac-guardrails.md` | `policies/tool-business-hours-soft.yaml` | code/config |
| `docs/security/pbac-guardrails.md` | `policies/tool-business-hours.yaml` | code/config |
| `docs/skills/per-tenant-skills.md` | `.agent/CONTEXT.md` | doc |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/__init__.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/artifacts.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/backends/__init__.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/backends/base.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/metrics.py` | code/config |
| `docs/storage-backends.md` | `packages/ai-parrot/src/parrot/storage/overflow.py` | code/config |
| `docs/testing/voicebot-liveavatar-acceptance.md` | `examples/clients/voice/README.md` | doc |
| `docs/testing/voicebot-multiroom-live-gate.md` | `examples/clients/voice/README.md` | doc |
| `docs/testing/voicebot-multiroom-live-gate.md` | `packages/ai-parrot-integrations/tests/voice/test_voice_demo_multibrowser_live.py` | test |
| `docs/testing/voicebot-multiroom-live-gate.md` | `tests/e2e/test_voicebot_multiroom_heygen_avatar.py` | test |
| `docs/toolkits/infographic_toolkit.md` | `examples/agents/a2ui/README.md` | doc |
| `docs/tools.md` | `examples/agents/claude_code_daemon.yaml` | code/config |
| `docs/tools/compression.md` | `packages/ai-parrot/src/parrot/tools/compression/budget.py` | code/config |
| `docs/tools/compression.md` | `packages/ai-parrot/tests/tools/compression/test_budget.py` | test |
| `docs/tools/compression.md` | `packages/ai-parrot/tests/tools/compression/test_docs_examples.py` | test |
| `docs/tools/querysource-toolkit.md` | `packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py` | test |
| `docs/tools/querysource-toolkit.md` | `packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py` | test |
| `docs/tools/semantic-layer.md` | `examples/agents/semantic/mcp_local_agent.py` | code/config |
| `docs/tools/semantic-layer.md` | `packages/ai-parrot-semantic/README.md` | doc |
| `docs/voice/voicebot-multiroom-heygen-avatar.md` | `examples/clients/voice/README.md` | doc |
| `docs/weasyprint-css-support.md` | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/layout-print.css` | code/config |
| `docs/weasyprint-css-support.md` | `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf_print_layout.py` | test |
| `docs/wiki/cheatsheet.md` | `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` | test |
| `docs/wiki/schema-plane.md` | `packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py` | test |

(`CHANGELOG.md` files, `sdd/briefs|tasks|specs|state|ledger` and the packaged `_assets/` copies are excluded: historical or generated.)

## Next steps if approved
- `git mv` per the tables → `wiki/<section>/`; create `wiki/_index.yaml` (block in the task file).
- Rewrite inbound links in retained Pages docs; update `mkdocs.yml` nav; add the notice to `docs/index.md`.
- Update path-pinned consumers per decision 2; run `mkdocs build --strict` (needs mkdocs installed) and `parrot sdd techwiki bundle --dry-run`.

## Appendix A — moving pages whose current title is rejected by `page_name` (needs a hyphen-free `title:`)

| Source | Current title |
|---|---|
| `docs/ARXIV_TOOL_README.md` | ArxivTool for AI-Parrot |
| `docs/FUNCTIONS.md` | Module-level Functions Catalog |
| `docs/admin-ui.md` | Admin UI (FEAT-468) |
| `docs/agents/followup-suggestion-chips.md` | Follow-up Suggestion Chips (FEAT-752) |
| `docs/architecture/03-toolkits.md` | 3. Toolkits for third-party services and Cloud-Security composition |
| `docs/architecture/05-hardening.md` | 5. Hardening — anti-prompt-injection, PBAC and tool gating |
| `docs/architecture/06-cross-cutting.md` | 6. Cross-cutting concerns and reference deployment |
| `docs/architecture/08-agentsflow-dag.md` | 8. AgentsFlow — DAG-first orchestration with per-node FSM |
| `docs/architecture/09-ontologic-rag.md` | 9. Ontologic RAG — graph-first retrieval, intent routing & multi-tenant knowledge |
| `docs/architecture/README.md` | AI-Parrot — Exposure, Interoperability & Hardening Architecture |
| `docs/aws_deployment.md` | AI-Parrot MCP Server - AWS Deployment Guide |
| `docs/bookstore-graph.md` | Bookstore Conceptual Relations — the book graph (FEAT-533) |
| `docs/clients/openai-compatible.md` | OpenAI-Compatible Client Base (`OpenAIBaseClient`) |
| `docs/clients/per-loop-cache.md` | Per-Loop LLM Client Cache |
| `docs/comm_center.md` | CommCenter — Bulk Notification Sender (FEAT-417) |
| `docs/configuration/llm-defaults.md` | Per-component LLM defaults (FEAT-796) |
| `docs/design-system.md` | Backend HTML Design System (FEAT-493) |
| `docs/design/luau-parser-resource-policy.md` | Luau parser resource policy (FEAT-532 TASK-2896) |
| `docs/dev_loop/claude-native-sandbox.md` | Native Claude sandbox for SDD sessions (FEAT-768) |
| `docs/dev_loop/complementary-research.md` | Complementary (collaborative) research partner (FEAT-482) |
| `docs/dev_loop/dev-flow-model-plan.md` | Dev-flow per-seat LLM configuration (`DevFlowModelPlan`) |
| `docs/dev_loop/nova-backend.md` | Dev-loop `nova` backend (AWS Bedrock) |
| `docs/dev_loop/sdd-coder-orchestrator.md` | sdd-worker as orchestrator of parallel sdd-coder seats (FEAT-549) |
| `docs/dev_loop/telemetry-accounting.md` | Dev-flow / dev-loop telemetry accounting |
| `docs/dev_loop/validation-runners.md` | Language-Agnostic Validation Runners (FEAT-709) |
| `docs/dynamodb-local.md` | DynamoDB Local (docker-compose) |
| `docs/eval/answer-accuracy-metrics.md` | Answer-Accuracy Metrics for the Evaluation Harness (FEAT-652) |
| `docs/events/eventbus-migration.md` | EventBus v2 Migration Notes (FEAT-310) |
| `docs/events/eventbus-v2.md` | EventBus v2 — Unified Event Fabric (FEAT-310) |
| `docs/experts/domain-experts.md` | Domain Experts (FEAT-778) |
| `docs/features/feat-437-claude-bedrock-sample-agents.md` | FEAT-437 |
| `docs/features/feat-488-formfield-content-type.md` | FEAT-488 |
| `docs/formdesigner-llm-validation-enforcement.md` | FormBuilder — LLM answer-plausibility enforcement |
| `docs/formdesigner-msteams-renderer.md` | FormDesigner → MS Teams: Adaptive Card renderer and bot submit path (FEAT-551) |
| `docs/formdesigner-orphan-upload-cleanup.md` | FormDesigner — orphan upload cleanup (FEAT-731) |
| `docs/formdesigner-unknown-fields-capture.md` | Form Designer — Unknown-Field Capture Policy for Form Submissions |
| `docs/frontend/agentdashboard-a2ui-reference.md` | AgentDashboard — A2UI v1.0 Technical Reference for `navigator-frontend-next` |
| `docs/frontend/liveavatar-fullmode-sveltekit-guide.md` | Guía Frontend (SvelteKit) — LiveAvatar FULL Mode + VoiceBot (FEAT-248) |
| `docs/frontend/liveavatar-phase-c-frontend-guide.md` | ⚠️ DEPRECATED — Guía Técnica del Avatar Voz-Nativo (LiveAvatar Phase C) para Frontend |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | VoiceBot · VoiceChatHandler · FEAT-245 — Guía de Frontend para Conversación Realtime con Agentes |
| `docs/getting-started.md` | Getting Started with AI-Parrot |
| `docs/graphindex/core-seams.md` | GraphIndex core seams (FEAT-540) |
| `docs/heartbeat_manager.md` | HeartbeatManager — Per-Agent Autonomous Heartbeat Loop |
| `docs/hierarchy_tool.md` | EmployeesTool - Employee Hierarchy Tool for AI-Parrot |
| `docs/hitl-confirmation.md` | HITL Tool-Call Confirmation (FEAT-235) |
| `docs/hitl-teams-channel.md` | Teams HITL Channel Setup Guide (FEAT-205) |
| `docs/install/global-runtime.md` | Global install: the parrot-managed runtime (reference) |
| `docs/integrations/google-oauth2.md` | Google OAuth 2.0 — AI-Parrot Integration |
| `docs/integrations/knowledge-upload.md` | Knowledge upload from chat (FEAT-647) |
| `docs/integrations/matrix/BRIDGES.md` | Matrix Bridges for the AI-Parrot Swarm (FEAT-463) |
| `docs/integrations/matrix/CLIENTS.md` | Matrix Clients for the AI-Parrot Swarm (FEAT-463) |
| `docs/integrations/msagentsdk-semantic-cards.md` | Semantic UI Model → Adaptive Cards (FEAT-303) |
| `docs/integrations/office365-oauth2.md` | Office 365 OAuth 2.0 (Delegated) — AI-Parrot Integration |
| `docs/integrations/slack-devloop.md` | Dev-loop kick-off from Slack (FEAT-555) |
| `docs/jira-specialist-prompt-layers.md` | JiraSpecialist Prompt-Layer Stack |
| `docs/knowledge/contracts-performance.md` | Contracts catalog performance (FEAT-539, AC14) |
| `docs/knowledge/contracts-pilot-acceptance.md` | Contracts pilot acceptance — Bob's twelve cases (FEAT-539, AC15) |
| `docs/knowledge/contracts.md` | Contracts Card & Ontology (FEAT-539) |
| `docs/knowledge/manuals.md` | Procedure Graph — Assembly Manuals (FEAT-601) |
| `docs/lancedb-offline-profile.md` | Fully offline local agent with LanceDB (FEAT-542) |
| `docs/lancedb-vector-store.md` | LanceDB vector, full-text and hybrid store (FEAT-542) |
| `docs/liveavatar-byo-livekit.md` | LiveAvatar over your own LiveKit (Cloud or self-hosted) |
| `docs/llm-wiki.md` | LLM Wiki — an agent-maintained knowledge repository |
| `docs/mcp-local-toolkits.md` | Expose Toolkits as Local MCP (`parrot mcp-local`) |
| `docs/mcp/agent-as-mcp-server.md` | Exposing an AI-Parrot Agent as an MCP Server |
| `docs/memory/per-turn-conversation-compaction.md` | Per-Turn Conversation Compaction |
| `docs/memory/recoverable-task-memory.md` | Recoverable Task Memory (FEAT-538) |
| `docs/memory/task-memory-integration-map.md` | Task Memory — Phase 0 Integration Map (FEAT-538 / TASK-2970) |
| `docs/messaging/implement-whatsapp.md` | WhatsApp Integration - Resumen de Implementación |
| `docs/messaging/whatsapp.md` | WhatsApp Integration for AI-Parrot |
| `docs/migration/feat-201-ai-parrot-embeddings.md` | Migration — FEAT-201: ai-parrot-embeddings |
| `docs/migration/feat-202-ai-parrot-integrations.md` | Migration Guide: FEAT-202 — ai-parrot-integrations |
| `docs/migration/feat-203-ai-parrot-server.md` | Migration — FEAT-203: ai-parrot-server |
| `docs/migration/feat-223-structured-artifact-contract.md` | FEAT-223 — Structured Artifact Contract: Migration Guide |
| `docs/migration/feat-273-a2ui-deprecations.md` | FEAT-273 — Legacy output-mode deprecations → A2UI |
| `docs/migration/feat-315-novaclient.md` | Migration — FEAT-315: Unified NovaClient for all Amazon Nova models |
| `docs/migration/feat-421-forms-tenant-in-url.md` | Migration — FEAT-421: Client-declared tenant in the forms URL |
| `docs/migration/feat-446-saas-auth-hardening.md` | Migration — FEAT-446: SaaS Auth Hardening (S0 of Parrot Research Cloud) |
| `docs/migration/feat-473-structured-a2ui.md` | Migration — FEAT-473: A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP |
| `docs/migration/feat-523-llm-client-satellites.md` | Migration — FEAT-523: PEP 420 LLM Client Extraction |
| `docs/migration/gemini-2-5-retirement.md` | Gemini 2.5 retirement (FEAT-798) |
| `docs/migration/video-reel-omni-veo-reliability.md` | Migration — FEAT-564: Reliable video reels with Gemini Omni and Veo 3.1 |
| `docs/msteams.md` | MS Teams Toolkit for AI-Parrot |
| `docs/multistoresearch-toolkit.md` | MultiStoreSearch Toolkit — Multi-Origin Retrieval for Agents |
| `docs/orchestrator-conferencing.md` | OrchestratorAgent — Multi-Party Conferencing (`confer`) |
| `docs/outputs/a2ui-agent-functions.md` | A2UI Agent Functions Runtime — the v1.0 RPC leg (FEAT-469) |
| `docs/outputs/a2ui-linked-surfaces.md` | A2UI Linked Surfaces (FEAT-598) |
| `docs/outputs/a2ui-v1.md` | A2UI v1.0 Wire (FEAT-470) |
| `docs/outputs/infographic-recipes.md` | Infographic Recipes (FEAT-324) |
| `docs/outputs/inline-a2ui-component-routing.md` | Inline A2UI Component Routing (FEAT-755) |
| `docs/outputs/metric-registry.md` | Metric Definition Registry (FEAT-756) |
| `docs/pageindex.md` | PageIndex — Tree-Based RAG for Document Retrieval |
| `docs/pandas-agent-capabilities.md` | Capacidades de un Agente Analítico AI-Parrot (PandasAgent) |
| `docs/parent-child-retrieval.md` | Parent-Child Retrieval (Small-to-Big) |
| `docs/pipelines/planogram-cycle-migration.md` | Planogram compliance — migrating configurations to the new cycle (FEAT-574, FEAT-612) |
| `docs/pipelines/planogram-perception-spike.md` | Planogram perception spike — FEAT-574 |
| `docs/promptbuilder-variables.md` | PromptBuilder — User-Modifiable Variables |
| `docs/prompts/output-language.md` | Output Language (FEAT-638) |
| `docs/repl-worker-sandbox.md` | PythonREPLTool Sandbox: Worker-Process Execution Model |
| `docs/report-builder/inventory-and-analysis.md` | Report Builder — ai-parrot inventory and analysis |
| `docs/report-builder/inventory/N4-navigator-api-backend.md` | N4 — navigator-api backend inventory (dashboards / widgets / templates / modules / programs) |
| `docs/report-builder/inventory/P1-parrot-endpoints.md` | P1 — ai-parrot HTTP/WS endpoint inventory (report-builder lens) |
| `docs/report-builder/inventory/P2-parrot-components-models.md` | P2 — ai-parrot (Python) UI components, models, renderers, persistence — inventory for a REPORT BUILDER |
| `docs/report-builder/inventory/P3-parrot-admin-ui.md` | P3 — parrot-admin-ui inventory (canvases / A2UI / infographic / builders) |
| `docs/report-builder/inventory/P4-parrot-prior-art.md` | P4 — ai-parrot prior art for a Report Builder (SDD inventory) |
| `docs/report-builder/inventory/_admin_bots.md` | ai-parrot server — Admin / Bots / Studio / misc endpoint inventory |
| `docs/report-builder/inventory/_core.md` | P1 — ai-parrot HTTP/WS endpoint inventory (report-builder lens) |
| `docs/report-builder/inventory/_formdesigner.md` | parrot-formdesigner — HTTP/WS endpoint inventory |
| `docs/roost/README.md` | Roost — local inter-agent sub-protocol |
| `docs/sandbox_tool.md` | gVisor Installation Guide for AI-Parrot Secure Sandbox |
| `docs/scheduler/multi-worker.md` | Scheduler backends in multi-worker deployments |
| `docs/sdd/ANTIGRAVITY.md` | Spec-Driven Development in Google Gemini / Antigravity CLI |
| `docs/sdd/GUIDE.md` | Guía de uso de los comandos `/sdd-*` |
| `docs/sdd/PLATFORM.md` | AI-Parrot Spec-Driven Development (SDD) Platform |
| `docs/sdd/closeout-hooks.md` | `/sdd-done` closeout hooks |
| `docs/sdd/decision-audit.md` | Decision Audit (FEAT-784) |
| `docs/sdd/ledger-outbox.md` | Ledger outbox (FEAT-758) |
| `docs/sdd/lsp-pilot-results.md` | FEAT-580 LSP Pilot — Live Evaluation Results |
| `docs/sdd/lsp-pilot.md` | SDD LSP research pilot (FEAT-580) |
| `docs/sdd/test-selection-validation-contract.md` | Test selection in the SDD flow — the Validation Contract (FEAT-699) |
| `docs/security-advisor.md` | SecurityAdvisor — SOC2-Oriented Read-Only Advisory Agent |
| `docs/security/agent-security-guardrails.md` | Agent Security Guardrails (FEAT-761) |
| `docs/security/onnx-injection-guardrail.md` | ONNX Backend for the Prompt-Injection Guardrail (FEAT-439) |
| `docs/security/pbac-guardrails.md` | PBAC Guardrails — Policy-Driven Tool-Call Denial (FEAT-406) |
| `docs/skills/per-tenant-skills.md` | Per-tenant skills (FEAT-707) |
| `docs/testing/agentic-e2e.md` | Agentic End-to-End Testing (FEAT-581) |
| `docs/testing/voicebot-liveavatar-acceptance.md` | FEAT-536 — VoiceBot Nova Dual Output + LiveAvatar: Real-Live Operational Acceptance |
| `docs/testing/voicebot-multiroom-heygen-avatar-acceptance.md` | FEAT-537 — Nova VoiceBot avatar broadcast: operational acceptance |
| `docs/testing/voicebot-multiroom-live-gate.md` | FEAT-537 — Nova PCM → LiveAvatar LITE → LiveKit multi-subscriber live gate |
| `docs/tool-optimizations.md` | Tool optimizations for Claude Code and Codex (FEAT-543) |
| `docs/toolkits/infographic_authoring.md` | Infographic Authoring for Data Agents (FEAT-326) |
| `docs/tools.md` | AI-Parrot Tools Documentation |
| `docs/tools/compression.md` | Tool-Result Compression Pipeline (FEAT-380) |
| `docs/tools/readonly-repo-toolkit.md` | ReadOnlyRepoToolkit (FEAT-484) |
| `docs/voice/voicebot-multiroom-heygen-avatar.md` | Nova VoiceBot avatar broadcast for multiple browsers (FEAT-537) |
| `docs/voice_chat.md` | 🦜 AI-Parrot Voice Chat |
| `docs/whatif_scenarios.md` | What-If Scenario Analysis |
| `docs/whisperx.md` | WhisperX Setup Guide for AI-Parrot |
| `docs/wiki/schema-plane.md` | Schema Plane — Operator Guide (FEAT-600) |
