# ai-parrot

<!-- Auto-generated OKF bundle index. Do not edit. -->

## [A2AAgentConnection](entities/class:parrot.a2a.client.A2AAgentConnection.md)

Represents a connection to a remote A2A agent.

## [A2AClient](entities/class:parrot.a2a.client.A2AClient.md)

Client for communicating with remote A2A agents.

## [A2ARemoteAgentInput](entities/class:parrot.a2a.client.A2ARemoteAgentInput.md)

Input schema for A2A remote agent tool.

## [A2ARemoteAgentTool](entities/class:parrot.a2a.client.A2ARemoteAgentTool.md)

Wraps a remote A2A agent as a tool that can be used by local agents.

## [A2ARemoteSkillTool](entities/class:parrot.a2a.client.A2ARemoteSkillTool.md)

Wraps a specific skill from a remote A2A agent as a tool.

## [A2AEndpoint](entities/class:parrot.a2a.mesh.A2AEndpoint.md)

Configuration for an A2A endpoint before discovery.

## [A2AMeshDiscovery](entities/class:parrot.a2a.mesh.A2AMeshDiscovery.md)

Centralized discovery service for remote A2A agents.

## [AgentStatus](entities/class:parrot.a2a.mesh.AgentStatus.md)

Status of an agent in the mesh.

## [DiscoveryStats](entities/class:parrot.a2a.mesh.DiscoveryStats.md)

Statistics about mesh discovery operations.

## [HealthCheckStrategy](entities/class:parrot.a2a.mesh.HealthCheckStrategy.md)

Strategy for health checking agents.

## [A2AClientMixin](entities/class:parrot.a2a.mixin.A2AClientMixin.md)

Mixin to add A2A client capabilities to any AbstractBot.

## [A2AError](entities/class:parrot.a2a.models.A2AError.md)

A2A JSON-RPC error object.

## [APIKeySecurityScheme](entities/class:parrot.a2a.models.APIKeySecurityScheme.md)

API key security scheme.

## [AgentCapabilities](entities/class:parrot.a2a.models.AgentCapabilities.md)

Capabilities supported by an agent.

## [AgentCard](entities/class:parrot.a2a.models.AgentCard.md)

Self-describing manifest for an agent (A2A v1.0 structure).

## [AgentCardSignature](entities/class:parrot.a2a.models.AgentCardSignature.md)

A JWS signature over the AgentCard (v1.0). Signing itself is out of scope.

## [AgentConfig](entities/class:parrot.a2a.models.AgentConfig.md)

Configuration for an A2A agent.

## [AgentExtension](entities/class:parrot.a2a.models.AgentExtension.md)

A protocol extension declared by an agent (v1.0).

## [AgentInterface](entities/class:parrot.a2a.models.AgentInterface.md)

v1.0 AgentCard interface entry.

## [AgentProvider](entities/class:parrot.a2a.models.AgentProvider.md)

Organization that provides the agent (v1.0).

## [AgentSkill](entities/class:parrot.a2a.models.AgentSkill.md)

A capability exposed by an agent (maps to a tool).

## [Artifact](entities/class:parrot.a2a.models.Artifact.md)

Output produced by an agent.

## [AuthenticationInfo](entities/class:parrot.a2a.models.AuthenticationInfo.md)

Authentication details for a push notification webhook (v1.0).

## [HTTPAuthSecurityScheme](entities/class:parrot.a2a.models.HTTPAuthSecurityScheme.md)

HTTP authentication security scheme (Bearer/Basic).

## [Message](entities/class:parrot.a2a.models.Message.md)

Communication unit between agents.

## [MutualTlsSecurityScheme](entities/class:parrot.a2a.models.MutualTlsSecurityScheme.md)

Mutual TLS security scheme.

## [OAuth2SecurityScheme](entities/class:parrot.a2a.models.OAuth2SecurityScheme.md)

OAuth 2.0 security scheme.

## [OpenIdConnectSecurityScheme](entities/class:parrot.a2a.models.OpenIdConnectSecurityScheme.md)

OpenID Connect security scheme.

## [Part](entities/class:parrot.a2a.models.Part.md)

Atomic content unit.

## [RegisteredAgent](entities/class:parrot.a2a.models.RegisteredAgent.md)

Definition about a Registered Agent.

## [Role](entities/class:parrot.a2a.models.Role.md)

Message role — v1.0.0 ProtoJSON values.

## [SecurityRequirement](entities/class:parrot.a2a.models.SecurityRequirement.md)

A security requirement: a map of scheme name -> required scopes.

## [SecurityScheme](entities/class:parrot.a2a.models.SecurityScheme.md)

Base security scheme (v1.0 securitySchemes entry).

## [SendMessageConfiguration](entities/class:parrot.a2a.models.SendMessageConfiguration.md)

Configuration accompanying a `SendMessage` request (v1.0).

## [Task](entities/class:parrot.a2a.models.Task.md)

Unit of work with lifecycle.

## [TaskPushNotificationConfig](entities/class:parrot.a2a.models.TaskPushNotificationConfig.md)

Configuration for a task's push-notification webhook (v1.0).

## [TaskState](entities/class:parrot.a2a.models.TaskState.md)

Task lifecycle states — v1.0.0 ProtoJSON values.

## [TaskStatus](entities/class:parrot.a2a.models.TaskStatus.md)

Current status of a task.

## [A2AOrchestrator](entities/class:parrot.a2a.orchestrator.A2AOrchestrator.md)

Hybrid orchestrator combining rule-based routing with LLM decision-making.

## [AgentExecutionResult](entities/class:parrot.a2a.orchestrator.AgentExecutionResult.md)

Result from a single agent execution.

## [AgentSelection](entities/class:parrot.a2a.orchestrator.AgentSelection.md)

Single agent selection from LLM.

## [LLMDecisionStrategy](entities/class:parrot.a2a.orchestrator.LLMDecisionStrategy.md)

Strategy for LLM-based agent selection.

## [OrchestrationMode](entities/class:parrot.a2a.orchestrator.OrchestrationMode.md)

Mode of orchestration.

## [OrchestrationPlan](entities/class:parrot.a2a.orchestrator.OrchestrationPlan.md)

Complete orchestration plan from LLM.

## [OrchestrationResult](entities/class:parrot.a2a.orchestrator.OrchestrationResult.md)

Complete result from orchestration.

## [OrchestratorStats](entities/class:parrot.a2a.orchestrator.OrchestratorStats.md)

Statistics for the orchestrator.

## [PushNotificationStore](entities/class:parrot.a2a.push_notifications.PushNotificationStore.md)

In-memory store for :class:`TaskPushNotificationConfig` objects.

## [A2AProxyRouter](entities/class:parrot.a2a.router.A2AProxyRouter.md)

Proxy/Gateway for routing requests to A2A agents without LLM processing.

## [LoadBalanceStrategy](entities/class:parrot.a2a.router.LoadBalanceStrategy.md)

Strategy for load balancing across multiple target agents.

## [ProxyStats](entities/class:parrot.a2a.router.ProxyStats.md)

Statistics for the proxy router.

## [RoutingResult](entities/class:parrot.a2a.router.RoutingResult.md)

Result of a routing decision.

## [RoutingRule](entities/class:parrot.a2a.router.RoutingRule.md)

Defines a routing rule for matching requests to agents.

## [RoutingStrategy](entities/class:parrot.a2a.router.RoutingStrategy.md)

Strategy for selecting target agent.

## [A2ASecurityMiddleware](entities/class:parrot.a2a.security.A2ASecurityMiddleware.md)

Security middleware for A2AServer.

## [AuthScheme](entities/class:parrot.a2a.security.AuthScheme.md)

Supported authentication schemes for A2A communication.

## [CallerIdentity](entities/class:parrot.a2a.security.CallerIdentity.md)

Represents the authenticated identity of a calling agent.

## [CredentialProvider](entities/class:parrot.a2a.security.CredentialProvider.md)

Abstract base for credential storage and retrieval.

## [InMemoryCredentialProvider](entities/class:parrot.a2a.security.InMemoryCredentialProvider.md)

In-memory credential provider for development and testing.

## [JWTAuthenticator](entities/class:parrot.a2a.security.JWTAuthenticator.md)

JWT-based authentication for A2A communication.

## [MTLSAuthenticator](entities/class:parrot.a2a.security.MTLSAuthenticator.md)

Mutual TLS (mTLS) authentication for A2A communication.

## [RedisCredentialProvider](entities/class:parrot.a2a.security.RedisCredentialProvider.md)

Redis-based credential provider for distributed systems.

## [SecureA2AClient](entities/class:parrot.a2a.security.SecureA2AClient.md)

Wrapper for A2AClient with automatic authentication.

## [SecurityPolicy](entities/class:parrot.a2a.security.SecurityPolicy.md)

Security policy for an agent, endpoint, or skill.

## [A2AEnabledMixin](entities/class:parrot.a2a.server.A2AEnabledMixin.md)

Mixin to add A2A server capabilities to an agent class.

## [A2AServer](entities/class:parrot.a2a.server.A2AServer.md)

Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.

## [ProductCatalog](entities/class:parrot.advisors.catalog.catalog.ProductCatalog.md)

Product catalog with hybrid search capabilities.

## [ProductSearchResult](entities/class:parrot.advisors.catalog.catalog.ProductSearchResult.md)

Enhanced search result with product-specific fields.

## [CSVLoader](entities/class:parrot.advisors.catalog.loaders.CSVLoader.md)

Loader for CSV product data.

## [JSONMarkdownLoader](entities/class:parrot.advisors.catalog.loaders.JSONMarkdownLoader.md)

Loader for JSON files with embedded markdown descriptions.

## [LoadResult](entities/class:parrot.advisors.catalog.loaders.LoadResult.md)

Result of a load operation.

## [ProductLoader](entities/class:parrot.advisors.catalog.loaders.ProductLoader.md)

Base loader for product data.

## [SeparateMarkdownLoader](entities/class:parrot.advisors.catalog.loaders.SeparateMarkdownLoader.md)

Loader for JSON specs + separate markdown files.

## [QuestionGenerator](entities/class:parrot.advisors.generator.QuestionGenerator.md)

Generates discriminant questions for a product catalog using LLM analysis.

## [SelectionStateManager](entities/class:parrot.advisors.manager.SelectionStateManager.md)

Manages selection state with Redis persistence and Memento pattern.

## [ProductAdvisorMixin](entities/class:parrot.advisors.mixin.ProductAdvisorMixin.md)

Mixin that adds product selection wizard capabilities to any Bot/Agent.

## [FeatureType](entities/class:parrot.advisors.models.FeatureType.md)

Types of product features for filtering logic.

## [ProductDimensions](entities/class:parrot.advisors.models.ProductDimensions.md)

Physical dimensions (for space-based filtering).

## [ProductFeature](entities/class:parrot.advisors.models.ProductFeature.md)

A single product feature/specification.

## [ProductSpec](entities/class:parrot.advisors.models.ProductSpec.md)

Complete product specification.

## [AnswerOption](entities/class:parrot.advisors.questions.AnswerOption.md)

A single answer option for choice-type questions.

## [AnswerType](entities/class:parrot.advisors.questions.AnswerType.md)

Type of expected answer from user.

## [CatalogAnalysis](entities/class:parrot.advisors.questions.CatalogAnalysis.md)

Complete analysis of a product catalog.

## [DiscriminantQuestion](entities/class:parrot.advisors.questions.DiscriminantQuestion.md)

A question designed to filter/discriminate between products.

## [FeatureAnalysis](entities/class:parrot.advisors.questions.FeatureAnalysis.md)

Analysis of a single feature across the catalog.

## [FeatureAnalyzer](entities/class:parrot.advisors.questions.FeatureAnalyzer.md)

Analyzes a product catalog to identify discriminating features.

## [GeneratedQuestion](entities/class:parrot.advisors.questions.GeneratedQuestion.md)

Schema for LLM-generated question (subset of DiscriminantQuestion).

## [QuestionCategory](entities/class:parrot.advisors.questions.QuestionCategory.md)

Categories of discriminant questions.

## [QuestionGenerationResponse](entities/class:parrot.advisors.questions.QuestionGenerationResponse.md)

Complete response from LLM question generation.

## [QuestionSet](entities/class:parrot.advisors.questions.QuestionSet.md)

Complete set of discriminant questions for a catalog.

## [ValueMapping](entities/class:parrot.advisors.questions.ValueMapping.md)

Maps user responses to filter criteria.

## [SelectionHistory](entities/class:parrot.advisors.state.SelectionHistory.md)

Memento Caretaker: Manages state history for undo/redo.

## [SelectionPhase](entities/class:parrot.advisors.state.SelectionPhase.md)

Phases of the product selection wizard.

## [SelectionState](entities/class:parrot.advisors.state.SelectionState.md)

Current state of product selection.

## [StateSnapshot](entities/class:parrot.advisors.state.StateSnapshot.md)

Memento: Immutable snapshot of SelectionState.

## [BaseAdvisorTool](entities/class:parrot.advisors.tools.base.BaseAdvisorTool.md)

Base class for Product Advisor tools.

## [ProductAdvisorToolArgs](entities/class:parrot.advisors.tools.base.ProductAdvisorToolArgs.md)

Base args schema with common fields for advisor tools.

## [CompareProductsArgs](entities/class:parrot.advisors.tools.compare.CompareProductsArgs.md)

Arguments for comparing products.

## [CompareProductsTool](entities/class:parrot.advisors.tools.compare.CompareProductsTool.md)

Generates a detailed side-by-side comparison of products.

## [ApplyCriteriaArgs](entities/class:parrot.advisors.tools.criteria.ApplyCriteriaArgs.md)

Arguments for applying criteria from user's answer.

## [ApplyCriteriaTool](entities/class:parrot.advisors.tools.criteria.ApplyCriteriaTool.md)

Applies the user's answer to filter products and update selection state.

## [ShowProductImageArgs](entities/class:parrot.advisors.tools.image.ShowProductImageArgs.md)

Arguments for showing product image.

## [ShowProductImageTool](entities/class:parrot.advisors.tools.image.ShowProductImageTool.md)

Show product image without speaking the URL.

## [GetNextQuestionArgs](entities/class:parrot.advisors.tools.question.GetNextQuestionArgs.md)

Arguments for getting the next question.

## [GetNextQuestionTool](entities/class:parrot.advisors.tools.question.GetNextQuestionTool.md)

Returns the next optimal question to ask the user.

## [RecommendProductArgs](entities/class:parrot.advisors.tools.recommend.RecommendProductArgs.md)

Arguments for generating a recommendation.

## [RecommendProductTool](entities/class:parrot.advisors.tools.recommend.RecommendProductTool.md)

Generates a final product recommendation based on collected criteria.

## [GetProductDetailsTool](entities/class:parrot.advisors.tools.search.GetProductDetailsTool.md)

Get detailed information about a specific product.

## [SearchProductsArgs](entities/class:parrot.advisors.tools.search.SearchProductsArgs.md)

Arguments for searching products.

## [SearchProductsTool](entities/class:parrot.advisors.tools.search.SearchProductsTool.md)

Search for products by name, category, or keywords.

## [StartSelectionArgs](entities/class:parrot.advisors.tools.start.StartSelectionArgs.md)

Arguments for starting a product selection session.

## [StartSelectionTool](entities/class:parrot.advisors.tools.start.StartSelectionTool.md)

Initiates a new product selection wizard session.

## [GetCurrentStateArgs](entities/class:parrot.advisors.tools.state.GetCurrentStateArgs.md)

Arguments for getting current state.

## [GetCurrentStateTool](entities/class:parrot.advisors.tools.state.GetCurrentStateTool.md)

Returns the current state of the product selection process.

## [RedoSelectionTool](entities/class:parrot.advisors.tools.undo.RedoSelectionTool.md)

Re-applies a previously undone action.

## [UndoSelectionArgs](entities/class:parrot.advisors.tools.undo.UndoSelectionArgs.md)

Arguments for undo operation.

## [UndoSelectionTool](entities/class:parrot.advisors.tools.undo.UndoSelectionTool.md)

Reverts the product selection to a previous state.

## [BookFlightSchema](entities/class:parrot.agents.demo.BookFlightSchema.md)

Arguments for the BookFlightTool.

## [BookFlightTool](entities/class:parrot.agents.demo.BookFlightTool.md)

Demo tool that books a flight — or raises an interrupt on invalid input.

## [HITLDemoAgent](entities/class:parrot.agents.demo.HITLDemoAgent.md)

Travel Concierge — demonstrates the web HITL (Human-in-the-Loop) flow.

## [AgentAccessDenied](entities/class:parrot.auth.agent_guard.AgentAccessDenied.md)

Raised by ``enforce_agent_access`` when PBAC denies bot resolution.

## [AuditEntry](entities/class:parrot.auth.audit.AuditEntry.md)

Single credential invocation record.

## [AuditLedger](entities/class:parrot.auth.audit.AuditLedger.md)

DEPRECATED log-based audit ledger.

## [CredentialBroker](entities/class:parrot.auth.broker.CredentialBroker.md)

Surface-agnostic per-user credential broker.

## [CredentialBrokerConfigError](entities/class:parrot.auth.broker.CredentialBrokerConfigError.md)

Raised by :meth:`CredentialBroker.from_config` in strict mode when a

## [CredentialResolverFactory](entities/class:parrot.auth.broker.CredentialResolverFactory.md)

Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.

## [ConfirmationConfig](entities/class:parrot.auth.confirmation.ConfirmationConfig.md)

Configurable defaults for the confirmation subsystem.

## [ConfirmationDecision](entities/class:parrot.auth.confirmation.ConfirmationDecision.md)

Result of ConfirmationGuard.confirm().

## [ConfirmationGuard](entities/class:parrot.auth.confirmation.ConfirmationGuard.md)

The Governor: asks a human to confirm each marked tool call.

## [ConfirmationWindowStore](entities/class:parrot.auth.confirmation.ConfirmationWindowStore.md)

Abstract window persistence for the confirmation subsystem.

## [InMemoryConfirmationWindowStore](entities/class:parrot.auth.confirmation.InMemoryConfirmation-9af8c942.md)

asyncio.Lock-guarded dict-backed window store with TTL expiry.

## [UserContext](entities/class:parrot.auth.context.UserContext.md)

Channel-agnostic identity snapshot for a single end user.

## [CredentialRequired](entities/class:parrot.auth.credentials.CredentialRequired.md)

Raised by the tool-loop seam when the broker returns :class:`NeedsAuth`.

## [CredentialResolver](entities/class:parrot.auth.credentials.CredentialResolver.md)

Resolves credentials for a given channel/user pair.

## [NeedsAuth](entities/class:parrot.auth.credentials.NeedsAuth.md)

Surface-neutral miss signal from the broker.

## [OAuthCredentialResolver](entities/class:parrot.auth.credentials.OAuthCredentialResolver.md)

Resolves credentials from an OAuth 2.0 token store.

## [ProviderCredentialConfig](entities/class:parrot.auth.credentials.ProviderCredentialConfig.md)

Declarative per-provider credential config (AgentDefinition / manifest).

## [ResolvedCredential](entities/class:parrot.auth.credentials.ResolvedCredential.md)

Credential material returned by the broker on a successful resolution.

## [StaticCredentialResolver](entities/class:parrot.auth.credentials.StaticCredentialResolver.md)

Returns a fixed :class:`StaticCredentials` instance.

## [StaticCredentials](entities/class:parrot.auth.credentials.StaticCredentials.md)

Credential bundle for non-OAuth (legacy) toolkit modes.

## [DataPlanePolicyGuard](entities/class:parrot.auth.dataplane_guard.DataPlanePolicyGuard.md)

Data-plane authorization guard for driver / table / source resources.

## [DatasetPolicyGuard](entities/class:parrot.auth.dataset_guard.DatasetPolicyGuard.md)

PBAC enforcement for DatasetManager.

## [AuthorizationRequired](entities/class:parrot.auth.exceptions.AuthorizationRequired.md)

Raised when a toolkit needs user authorization before operating.

## [Grant](entities/class:parrot.auth.grants.Grant.md)

A bounded-window approval record.

## [GrantConfig](entities/class:parrot.auth.grants.GrantConfig.md)

Configurable defaults for the grant subsystem.

## [GrantGuard](entities/class:parrot.auth.grants.GrantGuard.md)

The Governor: decides allow / approve / deny for a tool call.

## [GrantStore](entities/class:parrot.auth.grants.GrantStore.md)

Abstract interface for grant persistence.

## [GuardDecision](entities/class:parrot.auth.grants.GuardDecision.md)

Result of GrantGuard.authorize().

## [InMemoryGrantStore](entities/class:parrot.auth.grants.InMemoryGrantStore.md)

Dict-backed grant store with TTL expiry and periodic cleanup.

## [CanonicalIdentityMapper](entities/class:parrot.auth.identity.CanonicalIdentityMapper.md)

Maps raw per-surface identity data to a single canonical vault key.

## [JiraOAuthManager](entities/class:parrot.auth.jira_oauth.JiraOAuthManager.md)

OAuth 2.0 (3LO) lifecycle manager for Jira Cloud.

## [JiraTokenSet](entities/class:parrot.auth.jira_oauth.JiraTokenSet.md)

Per-user Jira OAuth 2.0 token set persisted in Redis.

## [PolicyRuleConfig](entities/class:parrot.auth.models.PolicyRuleConfig.md)

Simple policy rule format for bot-level declaration.

## [O365OAuthManager](entities/class:parrot.auth.o365_oauth.O365OAuthManager.md)

Microsoft Identity Platform OAuth 2.0 (PKCE + client_secret).

## [O365TokenSet](entities/class:parrot.auth.o365_oauth.O365TokenSet.md)

Office 365 token set extension.

## [JiraOAuth2Provider](entities/class:parrot.auth.oauth2.jira_provider.JiraOAuth2Provider.md)

OAuth2 provider for Atlassian Jira Cloud (3LO flow).

## [MCPOAuth2Provider](entities/class:parrot.auth.oauth2.mcp_provider.MCPOAuth2Provider.md)

OAuth2 provider for an MCP server connection.

## [AuthRequiredEnvelope](entities/class:parrot.auth.oauth2.models.AuthRequiredEnvelope.md)

Single-body response returned by ``AgentTalk`` when a tool raises

## [ConnectInitRequest](entities/class:parrot.auth.oauth2.models.ConnectInitRequest.md)

Request body for ``POST .../integrations/{agent_id}/{provider}/connect``.

## [ConnectInitResponse](entities/class:parrot.auth.oauth2.models.ConnectInitResponse.md)

Response for the connect-init endpoint.

## [DisconnectResponse](entities/class:parrot.auth.oauth2.models.DisconnectResponse.md)

Response for the disconnect endpoint.

## [EnableResponse](entities/class:parrot.auth.oauth2.models.EnableResponse.md)

Response for the confirm-enable endpoint.

## [IntegrationDescriptor](entities/class:parrot.auth.oauth2.models.IntegrationDescriptor.md)

Describes one OAuth2-capable integration for the menu listing.

## [UserAgentToolkitRow](entities/class:parrot.auth.oauth2.models.UserAgentToolkitRow.md)

Per-``(user, agent, toolkit)`` enablement record stored in

## [UsersIntegrationRow](entities/class:parrot.auth.oauth2.models.UsersIntegrationRow.md)

Durable credential record stored in the ``users_integrations`` collection.

## [O365DeviceCodeCredentialResolver](entities/class:parrot.auth.oauth2.o365_devicecode_provider.O-044cb7c7.md)

Device-code (headless) credential resolver for O365 (FEAT-266).

## [O365OAuth2Provider](entities/class:parrot.auth.oauth2.o365_provider.O365OAuth2Provider.md)

OAuth2 provider for Microsoft Office 365 (delegated / 3LO).

## [OAuth2Provider](entities/class:parrot.auth.oauth2.registry.OAuth2Provider.md)

Abstract base class for an OAuth2-capable provider.

## [OAuth2ProviderRegistry](entities/class:parrot.auth.oauth2.registry.OAuth2ProviderRegistry.md)

In-memory singleton registry of :class:`OAuth2Provider` instances.

## [IntegrationsService](entities/class:parrot.auth.oauth2.service.IntegrationsService.md)

Orchestrates OAuth2 provider registry, persistence, and PBAC checks.

## [WorkIQOAuth2Provider](entities/class:parrot.auth.oauth2.workiq_provider.WorkIQOAut-96ba5eb3.md)

OAuth2 provider for Work IQ (Microsoft) — Entra delegated OBO flow.

## [WorkIQOBOCredentialResolver](entities/class:parrot.auth.oauth2.workiq_provider.WorkIQOBOC-6bf78fe6.md)

Credential resolver that exchanges an Entra assertion for a Work IQ OBO token.

## [AbstractOAuth2Manager](entities/class:parrot.auth.oauth2_base.AbstractOAuth2Manager.md)

OAuth 2.0 lifecycle manager — provider-agnostic base.

## [AbstractOAuth2TokenSet](entities/class:parrot.auth.oauth2_base.AbstractOAuth2TokenSet.md)

Provider-agnostic OAuth 2.0 token set.

## [PermissionContext](entities/class:parrot.auth.permission.PermissionContext.md)

Request-scoped wrapper grouping session with extra context.

## [UserSession](entities/class:parrot.auth.permission.UserSession.md)

Minimal session carrying identity and role claims.

## [AbstractPermissionResolver](entities/class:parrot.auth.resolver.AbstractPermissionResolver.md)

Pluggable resolver for tool permission checks.

## [AllowAllResolver](entities/class:parrot.auth.resolver.AllowAllResolver.md)

Resolver that allows all tool executions.

## [DefaultPermissionResolver](entities/class:parrot.auth.resolver.DefaultPermissionResolver.md)

Reference RBAC implementation with LRU-cached role expansion.

## [DenyAllResolver](entities/class:parrot.auth.resolver.DenyAllResolver.md)

Resolver that denies all tool executions.

## [PBACPermissionResolver](entities/class:parrot.auth.resolver.PBACPermissionResolver.md)

PBAC-backed permission resolver — Layer 2 safety net.

## [RlsPredicate](entities/class:parrot.auth.rls_registry.RlsPredicate.md)

A rendered RLS predicate ready for injection.

## [RlsRegistry](entities/class:parrot.auth.rls_registry.RlsRegistry.md)

In-memory registry mapping ``(driver, table)`` to predicate templates.

## [RlsRule](entities/class:parrot.auth.rls_registry.RlsRule.md)

Registry entry: template predicate keyed by ``(driver, table)``.

## [AgentInstaller](entities/class:parrot.autonomous.deploy.installer.AgentInstaller.md)

Generates gunicorn, supervisord, and systemd configs for an agent.

## [DefaultHeartbeatStrategy](entities/class:parrot.autonomous.heartbeat.DefaultHeartbeatStrategy.md)

Acts when ``has_pending_work()`` returns True, or every *N* ticks.

## [HeartbeatConfig](entities/class:parrot.autonomous.heartbeat.HeartbeatConfig.md)

Configuration for a single agent's heartbeat loop.

## [HeartbeatManager](entities/class:parrot.autonomous.heartbeat.HeartbeatManager.md)

Manages per-agent async heartbeat loops.

## [HeartbeatState](entities/class:parrot.autonomous.heartbeat.HeartbeatState.md)

Runtime state for a single agent's heartbeat loop.

## [HeartbeatStrategy](entities/class:parrot.autonomous.heartbeat.HeartbeatStrategy.md)

Pluggable assess step for the heartbeat loop.

## [AgentLedgerState](entities/class:parrot.autonomous.ledger.AgentLedgerState.md)

Read projection of an agent's recent ledger activity.

## [EventLedger](entities/class:parrot.autonomous.ledger.EventLedger.md)

Abstract interface for the persistent event ledger.

## [InMemoryLedgerBackend](entities/class:parrot.autonomous.ledger.InMemoryLedgerBackend.md)

In-memory ``EventLedger`` implementation for use in tests and CI.

## [IncompleteExecution](entities/class:parrot.autonomous.ledger.IncompleteExecution.md)

An execution that was opened (Before*) but never closed (After*/Failed*).

## [LedgerConfig](entities/class:parrot.autonomous.ledger.LedgerConfig.md)

Configuration for the ledger recorder and backend.

## [LedgerEvent](entities/class:parrot.autonomous.ledger.LedgerEvent.md)

Pydantic wrapper for a single persisted lifecycle event.

## [LedgerRecorder](entities/class:parrot.autonomous.ledger.LedgerRecorder.md)

Subscribe to the global lifecycle registry and persist all events.

## [PostgresLedgerBackend](entities/class:parrot.autonomous.ledger.PostgresLedgerBackend.md)

Postgres append-only implementation of ``EventLedger``.

## [AutonomousOrchestrator](entities/class:parrot.autonomous.orchestrator.AutonomousOrchestrator.md)

Unified orchestrator for autonomous agent and crew execution.

## [ExecutionRequest](entities/class:parrot.autonomous.orchestrator.ExecutionRequest.md)

Represents a request to execute an agent or crew.

## [ExecutionResult](entities/class:parrot.autonomous.orchestrator.ExecutionResult.md)

Result of an execution request.

## [ExecutionTarget](entities/class:parrot.autonomous.orchestrator.ExecutionTarget.md)

Type of execution target.

## [RedisJobInjector](entities/class:parrot.autonomous.redis_jobs.RedisJobInjector.md)

Permite inyectar jobs dinámicamente desde cualquier proceso.

## [AgentTriggerConfig](entities/class:parrot.autonomous.scheduler.AgentTriggerConfig.md)

Configuración de trigger para un agente autónomo.

## [AutonomousJob](entities/class:parrot.autonomous.scheduler.AutonomousJob.md)

Representa un job autónomo en cualquier modo.

## [TriggerMode](entities/class:parrot.autonomous.scheduler.TriggerMode.md)

Cómo se dispara la ejecución de un agente.

## [AbstractTransport](entities/class:parrot.autonomous.transport.base.AbstractTransport.md)

Abstract base for all multi-agent transports.

## [ChannelManager](entities/class:parrot.autonomous.transport.filesystem.channe-1cfdfd2f.md)

Broadcast channels using JSONL append-only files.

## [CrewCLI](entities/class:parrot.autonomous.transport.filesystem.cli.CrewCLI.md)

Read-only CLI view into the FilesystemTransport state.

## [FilesystemTransportConfig](entities/class:parrot.autonomous.transport.filesystem.config-38e46e55.md)

Pydantic v2 configuration for the FilesystemTransport.

## [ActivityFeed](entities/class:parrot.autonomous.transport.filesystem.feed.A-48d521d2.md)

Global append-only JSONL event log for the FilesystemTransport.

## [FilesystemHook](entities/class:parrot.autonomous.transport.filesystem.hook.F-965cee22.md)

Hook connecting agents to FilesystemTransport.

## [InboxManager](entities/class:parrot.autonomous.transport.filesystem.inbox.-9b050ceb.md)

Point-to-point message delivery between agents using the filesystem.

## [AgentRegistry](entities/class:parrot.autonomous.transport.filesystem.regist-a954371a.md)

Agent presence registry using JSON files on the filesystem.

## [ReservationManager](entities/class:parrot.autonomous.transport.filesystem.reserv-32ebf85d.md)

Cooperative resource reservation using JSON files on the filesystem.

## [FilesystemTransport](entities/class:parrot.autonomous.transport.filesystem.transp-2f04d9de.md)

Multi-agent transport over the local filesystem.

## [WebhookEndpoint](entities/class:parrot.autonomous.webhooks.WebhookEndpoint.md)

Configuración de un endpoint webhook.

## [WebhookListener](entities/class:parrot.autonomous.webhooks.WebhookListener.md)

Listener HTTP para triggers externos.

## [AgentDispatcher](entities/class:parrot.bots._types.AgentDispatcher.md)

Duck-typed async callable that dispatches a named agent.

## [A2AAgent](entities/class:parrot.bots.a2a_agent.A2AAgent.md)

An AI-Parrot Agent with A2A capabilities.

## [AbstractBot](entities/class:parrot.bots.abstract.AbstractBot.md)

AbstractBot.

## [Agent](entities/class:parrot.bots.agent.Agent.md)

A general-purpose agent with no additional tools.

## [BasicAgent](entities/class:parrot.bots.agent.BasicAgent.md)

Represents an Agent in Navigator.

## [BaseBot](entities/class:parrot.bots.base.BaseBot.md)

Base Bot implementation providing concrete implementations of

## [BasicBot](entities/class:parrot.bots.basic.BasicBot.md)

Represents an BasicBot in Navigator.

## [Chatbot](entities/class:parrot.bots.chatbot.Chatbot.md)

Represents an Bot (Chatbot, Agent) in Navigator.

## [DatasetResult](entities/class:parrot.bots.data.DatasetResult.md)

A single named dataset in a multi-dataset response.

## [PandasAgent](entities/class:parrot.bots.data.PandasAgent.md)

A specialized agent for data analysis using pandas DataFrames.

## [PandasAgentResponse](entities/class:parrot.bots.data.PandasAgentResponse.md)

Structured response for PandasAgent operations.

## [PandasMetadata](entities/class:parrot.bots.data.PandasMetadata.md)

Metadata information for PandasAgent responses.

## [PandasTable](entities/class:parrot.bots.data.PandasTable.md)

Tabular data structure for PandasAgent responses.

## [SummaryStat](entities/class:parrot.bots.data.SummaryStat.md)

Single summary statistic for a DataFrame column.

## [DatabaseAgent](entities/class:parrot.bots.database.agent.DatabaseAgent.md)

Unified database agent backed by BasicAgent + QueryResponse structured output.

## [CacheManager](entities/class:parrot.bots.database.cache.CacheManager.md)

Manages namespaced cache partitions with shared Redis + vector store.

## [CachePartition](entities/class:parrot.bots.database.cache.CachePartition.md)

Namespaced cache partition with the same API as ``SchemaMetadataCache``.

## [CachePartitionConfig](entities/class:parrot.bots.database.cache.CachePartitionConfig.md)

Configuration for a single cache partition.

## [SchemaMetadataCache](entities/class:parrot.bots.database.cache.SchemaMetadataCache.md)

Backward-compatible wrapper around ``CachePartition``.

## [Completeness](entities/class:parrot.bots.database.models.Completeness.md)

Completeness level of a cached TableMetadata entry.

## [DatabaseResponse](entities/class:parrot.bots.database.models.DatabaseResponse.md)

Component-based database response.

## [OutputComponent](entities/class:parrot.bots.database.models.OutputComponent.md)

Flags for different response components - allows combinations.

## [OutputFormat](entities/class:parrot.bots.database.models.OutputFormat.md)

Defines the desired format of the response.

## [QueryDataset](entities/class:parrot.bots.database.models.QueryDataset.md)

Result dataset for a single executed query.

## [QueryExecutionRequest](entities/class:parrot.bots.database.models.QueryExecutionRequest.md)

Structured input for query execution.

## [QueryExecutionResponse](entities/class:parrot.bots.database.models.QueryExecutionResponse.md)

Structured output from query execution.

## [QueryIntent](entities/class:parrot.bots.database.models.QueryIntent.md)

Defines the user's query intents for comprehensive database operations.

## [QueryResponse](entities/class:parrot.bots.database.models.QueryResponse.md)

Structured LLM output for DatabaseAgent.ask().

## [RouteDecision](entities/class:parrot.bots.database.models.RouteDecision.md)

Query routing decision for schema-centric operations.

## [SchemaMetadata](entities/class:parrot.bots.database.models.SchemaMetadata.md)

Metadata for a single schema (client).

## [TableMetadata](entities/class:parrot.bots.database.models.TableMetadata.md)

Enhanced table metadata for large-scale operations.

## [UserRole](entities/class:parrot.bots.database.models.UserRole.md)

Define user roles with specific output preferences.

## [DSLRetryHandler](entities/class:parrot.bots.database.retries.DSLRetryHandler.md)

Elasticsearch DSL-specific retry handler (stub for future use).

## [FluxRetryHandler](entities/class:parrot.bots.database.retries.FluxRetryHandler.md)

InfluxDB Flux-specific retry handler (stub for future use).

## [QueryRetryConfig](entities/class:parrot.bots.database.retries.QueryRetryConfig.md)

Configuration for query retry mechanism.

## [RetryContext](entities/class:parrot.bots.database.retries.RetryContext.md)

Payload returned by SQLToolkit.execute_query on a retryable error.

## [RetryHandler](entities/class:parrot.bots.database.retries.RetryHandler.md)

Base retry handler for any database toolkit.

## [SQLRetryHandler](entities/class:parrot.bots.database.retries.SQLRetryHandler.md)

SQL-specific retry handler with error learning.

## [SchemaQueryRouter](entities/class:parrot.bots.database.router.SchemaQueryRouter.md)

Routes queries with multi-schema awareness and "show me" pattern recognition.

## [DatabaseAgentToolkit](entities/class:parrot.bots.database.toolkits._internal.Datab-c08d9668.md)

Internal helper toolkit for DatabaseAgent.

## [DatabaseToolkit](entities/class:parrot.bots.database.toolkits.base.DatabaseToolkit.md)

Abstract base class for all database toolkits.

## [DatabaseToolkitConfig](entities/class:parrot.bots.database.toolkits.base.DatabaseTo-f33c46b6.md)

Configuration passed to toolkit constructors.

## [BigQueryToolkit](entities/class:parrot.bots.database.toolkits.bigquery.BigQueryToolkit.md)

BigQuery-specific toolkit.

## [DocumentDBToolkit](entities/class:parrot.bots.database.toolkits.documentdb.Docu-d03125c2.md)

DocumentDB/MongoDB toolkit with MQL support.

## [ElasticToolkit](entities/class:parrot.bots.database.toolkits.elastic.ElasticToolkit.md)

Elasticsearch toolkit with DSL query support.

## [InfluxDBToolkit](entities/class:parrot.bots.database.toolkits.influx.InfluxDBToolkit.md)

InfluxDB toolkit with Flux query language support.

## [PostgresToolkit](entities/class:parrot.bots.database.toolkits.postgres.PostgresToolkit.md)

PostgreSQL-specific toolkit with first-class CRUD tools.

## [SQLToolkit](entities/class:parrot.bots.database.toolkits.sql.SQLToolkit.md)

Common SQL operations with overridable dialect hooks.

## [DocumentAgent](entities/class:parrot.bots.document.DocumentAgent.md)

A specialized agent for document processing - converting Word docs to Markdown,

## [DynamicValueProvider](entities/class:parrot.bots.dynamic_values.DynamicValueProvider.md)

Registry for dynamic value functions

## [BuilderOutput](entities/class:parrot.bots.factory.contracts.BuilderOutput.md)

Specialist-to-orchestrator handoff payload.

## [BuilderType](entities/class:parrot.bots.factory.contracts.BuilderType.md)

Specialist builders the orchestrator can delegate to.

## [FactoryRequest](entities/class:parrot.bots.factory.contracts.FactoryRequest.md)

User-facing input to the orchestrator.

## [FactoryResult](entities/class:parrot.bots.factory.contracts.FactoryResult.md)

Terminal output of an orchestrator run.

## [FactoryStatus](entities/class:parrot.bots.factory.contracts.FactoryStatus.md)

Terminal states for a factory run.

## [HITLCheckpoint](entities/class:parrot.bots.factory.contracts.HITLCheckpoint.md)

Named human-in-the-loop checkpoints in the factory flow.

## [ProvisioningRecord](entities/class:parrot.bots.factory.contracts.ProvisioningRecord.md)

Side-effect produced by a builder while drafting the definition.

## [RouterDecision](entities/class:parrot.bots.factory.contracts.RouterDecision.md)

First-stage output: which specialist the orchestrator wants to invoke.

## [AgentFactoryOrchestrator](entities/class:parrot.bots.factory.orchestrator.AgentFactory-49ea75ad.md)

Orchestrate router → specialist → finalize with HITL gates.

## [A2AOrchestratorAgent](entities/class:parrot.bots.flows.agents.a2a_orchestrator.A2A-c1484633.md)

An orchestrator agent that supports both local and remote A2A agents.

## [DiscoverA2AAgentsInput](entities/class:parrot.bots.flows.agents.a2a_orchestrator.Dis-870d6540.md)

Input schema for ListAvailableA2AAgentsTool.

## [ListAvailableA2AAgentsTool](entities/class:parrot.bots.flows.agents.a2a_orchestrator.Lis-150034de.md)

Tool that discovers available A2A agents from specified endpoints.

## [EmployeeDataAgent](entities/class:parrot.bots.flows.agents.hr.EmployeeDataAgent.md)

Agent specialized in employee profile and organizational data.

## [HRAgentFactory](entities/class:parrot.bots.flows.agents.hr.HRAgentFactory.md)

Factory for creating HR-specific agent orchestration systems.

## [RAGHRAgent](entities/class:parrot.bots.flows.agents.hr.RAGHRAgent.md)

HR Agent with RAG capabilities using the existing vector store system.

## [OrchestratorAgent](entities/class:parrot.bots.flows.agents.orchestrator.Orchest-d4a667eb.md)

An orchestrator agent that can coordinate multiple specialized agents.

## [AgentNotFoundError](entities/class:parrot.bots.flows.core.context.AgentNotFoundError.md)

Raised when ``FlowContext.resolve_agent`` cannot find the requested agent.

## [FlowContext](entities/class:parrot.bots.flows.core.context.FlowContext.md)

Execution state tracker for a single flow/crew run.

## [AgentTaskMachine](entities/class:parrot.bots.flows.core.fsm.AgentTaskMachine.md)

Finite State Machine describing the lifecycle of a single node execution.

## [TransitionCondition](entities/class:parrot.bots.flows.core.fsm.TransitionCondition.md)

Predefined conditions that can trigger a flow transition.

## [AgentNode](entities/class:parrot.bots.flows.core.node.AgentNode.md)

A graph node that wraps an ``AgentLike`` agent and an FSM.

## [EndNode](entities/class:parrot.bots.flows.core.node.EndNode.md)

Virtual exit-point node for flow/crew DAGs.

## [Node](entities/class:parrot.bots.flows.core.node.Node.md)

Abstract base for all flow/crew nodes (frozen Pydantic).

## [StartNode](entities/class:parrot.bots.flows.core.node.StartNode.md)

Virtual entry-point node for flow/crew DAGs.

## [FlowResult](entities/class:parrot.bots.flows.core.result.FlowResult.md)

Standardised result from a flow/crew execution.

## [NodeExecutionInfo](entities/class:parrot.bots.flows.core.result.NodeExecutionInfo.md)

Execution metadata for a single node in a flow/crew run.

## [NodeResult](entities/class:parrot.bots.flows.core.result.NodeResult.md)

Per-node execution record for storage and vectorization.

## [ResultStorage](entities/class:parrot.bots.flows.core.storage.backends.base.-52d1ae37.md)

Abstract pluggable backend for crew/flow execution result persistence.

## [DocumentDbResultStorage](entities/class:parrot.bots.flows.core.storage.backends.docum-49fd1f89.md)

Default backend — preserves the legacy DocumentDB write path.

## [PostgresResultStorage](entities/class:parrot.bots.flows.core.storage.backends.postg-e084363d.md)

Persist crew/flow execution results to Postgres (one row per execution).

## [RedisResultStorage](entities/class:parrot.bots.flows.core.storage.backends.redis-b01e984e.md)

Persist crew/flow execution results to Redis (one key per execution).

## [CrewExecutionDocument](entities/class:parrot.bots.flows.core.storage.document.CrewE-83811ca8.md)

Deterministic, LLM-free consolidated record of one crew execution.

## [ExecutionMemory](entities/class:parrot.bots.flows.core.storage.memory.ExecutionMemory.md)

In-memory storage for execution history.

## [VectorStoreMixin](entities/class:parrot.bots.flows.core.storage.mixin.VectorStoreMixin.md)

Mixin to add FAISS vector store capabilities to ExecutionMemory.

## [PersistenceMixin](entities/class:parrot.bots.flows.core.storage.persistence.Pe-947a5cbd.md)

Pluggable persistence for crew/flow execution results.

## [SynthesisMixin](entities/class:parrot.bots.flows.core.storage.synthesis.Synt-ca83036e.md)

Mixin that adds LLM-based result synthesis to crew/flow orchestrators.

## [FlowTransition](entities/class:parrot.bots.flows.core.transition.FlowTransition.md)

Conditional edge between two nodes in a flow/crew DAG.

## [AgentLike](entities/class:parrot.bots.flows.core.types.AgentLike.md)

Structural protocol for any object that can act as an agent node.

## [FlowStatus](entities/class:parrot.bots.flows.core.types.FlowStatus.md)

Overall execution status for a flow/crew run.

## [AgentCrew](entities/class:parrot.bots.flows.crew.crew.AgentCrew.md)

Enhanced AgentCrew supporting multiple execution modes.

## [CrewAgentNode](entities/class:parrot.bots.flows.crew.nodes.CrewAgentNode.md)

Crew-specific node wrapping an agent with dependency metadata.

## [TemplateResolutionError](entities/class:parrot.bots.flows.crew.tool_node.TemplateReso-fdfdb495.md)

A template placeholder references a node with no stored result.

## [ToolLike](entities/class:parrot.bots.flows.crew.tool_node.ToolLike.md)

Structural protocol for any object usable as a ToolNode tool.

## [ToolNode](entities/class:parrot.bots.flows.crew.tool_node.ToolNode.md)

Deterministic tool-caller crew node (no LLM involved).

## [ToolNodeExecutionError](entities/class:parrot.bots.flows.crew.tool_node.ToolNodeExec-4e2a5810.md)

The wrapped tool reported failure (``ToolResult.success == False``).

## [BaseAction](entities/class:parrot.bots.flows.flow.actions.BaseAction.md)

Abstract base class for all flow lifecycle actions.

## [LogAction](entities/class:parrot.bots.flows.flow.actions.LogAction.md)

Log a message with template variables.

## [MetricAction](entities/class:parrot.bots.flows.flow.actions.MetricAction.md)

Emit a metric.

## [NotifyAction](entities/class:parrot.bots.flows.flow.actions.NotifyAction.md)

Send a notification to a channel.

## [SetContextAction](entities/class:parrot.bots.flows.flow.actions.SetContextAction.md)

Extract a value from the result and set it in the shared context.

## [TransformAction](entities/class:parrot.bots.flows.flow.actions.TransformAction.md)

Transform the result using a safe expression.

## [ValidateAction](entities/class:parrot.bots.flows.flow.actions.ValidateAction.md)

Validate the result against a JSON schema.

## [WebhookAction](entities/class:parrot.bots.flows.flow.actions.WebhookAction.md)

Make an HTTP webhook call.

## [CELPredicateEvaluator](entities/class:parrot.bots.flows.flow.cel_evaluator.CELPredi-fdf7a74f.md)

Evaluate CEL expression strings as flow transition predicates.

## [EdgeDefinition](entities/class:parrot.bots.flows.flow.definition.EdgeDefinition.md)

Definition of an edge (transition) between nodes.

## [FlowDefinition](entities/class:parrot.bots.flows.flow.definition.FlowDefinition.md)

Complete definition of an AgentsFlow workflow.

## [FlowMetadata](entities/class:parrot.bots.flows.flow.definition.FlowMetadata.md)

Flow-level configuration and defaults.

## [LogActionDef](entities/class:parrot.bots.flows.flow.definition.LogActionDef.md)

Log a message with template variables.

## [MetricActionDef](entities/class:parrot.bots.flows.flow.definition.MetricActionDef.md)

Emit a metric.

## [NodeDefinition](entities/class:parrot.bots.flows.flow.definition.NodeDefinition.md)

Definition of a node in the flow.

## [NodePosition](entities/class:parrot.bots.flows.flow.definition.NodePosition.md)

UI position hint for visual flow builders (SvelteFlow compatible).

## [NotifyActionDef](entities/class:parrot.bots.flows.flow.definition.NotifyActionDef.md)

Send a notification to a channel.

## [SetContextActionDef](entities/class:parrot.bots.flows.flow.definition.SetContextActionDef.md)

Extract a value from result and set in shared context.

## [TransformActionDef](entities/class:parrot.bots.flows.flow.definition.TransformActionDef.md)

Transform result using a safe expression.

## [ValidateActionDef](entities/class:parrot.bots.flows.flow.definition.ValidateActionDef.md)

Validate result against a JSON schema.

## [WebhookActionDef](entities/class:parrot.bots.flows.flow.definition.WebhookActionDef.md)

Make an HTTP webhook call.

## [AgentsFlow](entities/class:parrot.bots.flows.flow.flow.AgentsFlow.md)

DAG executor consuming ``parrot.bots.flows.core`` primitives.

## [CompletionEvent](entities/class:parrot.bots.flows.flow.flow.CompletionEvent.md)

Event pushed to the scheduler's completion queue when a node finishes.

## [DecisionNode](entities/class:parrot.bots.flows.flow.flow.DecisionNode.md)

Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.

## [FlowEdge](entities/class:parrot.bots.flows.flow.flow.FlowEdge.md)

Programmatic transition edge between two nodes.

## [InteractiveDecisionFlowNode](entities/class:parrot.bots.flows.flow.flow.InteractiveDecisi-05fb9b9f.md)

DAG-executor wrapper for the CLI-blocking interactive decision node.

## [SynthesisNode](entities/class:parrot.bots.flows.flow.flow.SynthesisNode.md)

In-graph result synthesis using the ``synthesize_results`` util.

## [FlowLoader](entities/class:parrot.bots.flows.flow.loader.FlowLoader.md)

Load, save, and materialize FlowDefinition instances.

## [ApprovalDecision](entities/class:parrot.bots.flows.flow.nodes.ApprovalDecision.md)

Approval gate decision schema.

## [BinaryDecision](entities/class:parrot.bots.flows.flow.nodes.BinaryDecision.md)

Binary YES/NO decision schema.

## [DecisionFlowNode](entities/class:parrot.bots.flows.flow.nodes.DecisionFlowNode.md)

Decision orchestrator node for AgentsFlow workflows.

## [DecisionMode](entities/class:parrot.bots.flows.flow.nodes.DecisionMode.md)

Operating mode for decision-making process.

## [DecisionNodeConfig](entities/class:parrot.bots.flows.flow.nodes.DecisionNodeConfig.md)

Configuration for DecisionFlowNode.

## [DecisionResult](entities/class:parrot.bots.flows.flow.nodes.DecisionResult.md)

Structured result from a decision node.

## [DecisionType](entities/class:parrot.bots.flows.flow.nodes.DecisionType.md)

Types of decisions the node can make.

## [EscalationPolicy](entities/class:parrot.bots.flows.flow.nodes.EscalationPolicy.md)

Defines when and how to escalate to HITL.

## [InteractiveDecisionNode](entities/class:parrot.bots.flows.flow.nodes.InteractiveDecisionNode.md)

A Flow node that asks the user a multiple-choice question in the CLI.

## [MultiChoiceDecision](entities/class:parrot.bots.flows.flow.nodes.MultiChoiceDecision.md)

Multi-option choice decision schema.

## [VoteWeight](entities/class:parrot.bots.flows.flow.nodes.VoteWeight.md)

Pre-defined vote weighting strategies.

## [FlowLifecycleAdapter](entities/class:parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter.md)

Node-event listener that emits typed FEAT-176 lifecycle events.

## [ResultAgent](entities/class:parrot.bots.flows.result_agent.ResultAgent.md)

Internal agent that renders a crew's ExecutionMemory into a crew_report infographic.

## [ResultRetrievalTool](entities/class:parrot.bots.flows.tools.ResultRetrievalTool.md)

Retrieval Tool for flows (AgentCrew, AgentsFlow).

## [Discrepancy](entities/class:parrot.bots.github_reviewer.Discrepancy.md)

Single mismatch between the PR and the Jira acceptance criteria.

## [GitHubReviewer](entities/class:parrot.bots.github_reviewer.GitHubReviewer.md)

Reviews GitHub PRs against linked Jira ticket acceptance criteria.

## [PRReviewResult](entities/class:parrot.bots.github_reviewer.PRReviewResult.md)

LLM-produced summary of a PR review.

## [WeeklyActivitySummary](entities/class:parrot.bots.github_reviewer.WeeklyActivitySummary.md)

Structured input to the templated/LLM renderer for the weekly digest.

## [WeeklyLLMSummarizationError](entities/class:parrot.bots.github_reviewer.WeeklyLLMSummariz-91cb4839.md)

Raised when the LLM summarizer fails; caller falls back to templated output.

## [HRAgent](entities/class:parrot.bots.hrbot.HRAgent.md)

Represents an Human Resources agent in Navigator.

## [DailyStandupConfig](entities/class:parrot.bots.jira_specialist.DailyStandupConfig.md)

Configuration for the daily standup workflow.

## [Developer](entities/class:parrot.bots.jira_specialist.Developer.md)

A developer in the team with Jira + Telegram mappings.

## [HistoryEvent](entities/class:parrot.bots.jira_specialist.HistoryEvent.md)

History of Events.

## [HistoryItem](entities/class:parrot.bots.jira_specialist.HistoryItem.md)

Model representing a history item.

## [JiraSpecialist](entities/class:parrot.bots.jira_specialist.JiraSpecialist.md)

Base class for Jira specialist agents.

## [JiraTicket](entities/class:parrot.bots.jira_specialist.JiraTicket.md)

Model representing a Jira Ticket.

## [JiraTicketDetail](entities/class:parrot.bots.jira_specialist.JiraTicketDetail.md)

Detailed Jira Ticket model with history.

## [JiraTicketResponse](entities/class:parrot.bots.jira_specialist.JiraTicketResponse.md)

Model representing a Jira Ticket Response.

## [KBOutput](entities/class:parrot.bots.kb.KBOutput.md)

Structured output model for KB selection.

## [KBSelected](entities/class:parrot.bots.kb.KBSelected.md)

Model for a selected KB.

## [KBSelector](entities/class:parrot.bots.kb.KBSelector.md)

Add KB selection capabilities to a bot.

## [MCPAgent](entities/class:parrot.bots.mcp.MCPAgent.md)

An agent with MCP (Model Context Protocol) capabilities.

## [PromptMiddleware](entities/class:parrot.bots.middleware.PromptMiddleware.md)

Single transformation step in the prompt pipeline.

## [PromptPipeline](entities/class:parrot.bots.middleware.PromptPipeline.md)

Ordered chain of prompt transformations applied before LLM call.

## [IntentRouterMixin](entities/class:parrot.bots.mixins.intent_router.IntentRouterMixin.md)

Mixin that adds intent-based routing to any Bot or Agent.

## [ProductReport](entities/class:parrot.bots.product.ProductReport.md)

ProductReport is an agent designed to generate detailed product reports using LLMs and various tools.

## [LayerPriority](entities/class:parrot.bots.prompts.layers.LayerPriority.md)

Execution order. Lower = rendered first in the prompt.

## [PromptLayer](entities/class:parrot.bots.prompts.layers.PromptLayer.md)

Single composable prompt layer.

## [RenderPhase](entities/class:parrot.bots.prompts.layers.RenderPhase.md)

When a layer's variables get resolved.

## [CacheableSegment](entities/class:parrot.bots.prompts.segments.CacheableSegment.md)

One chunk of the system prompt with a cache-eligibility flag.

## [BrowserConfigSchema](entities/class:parrot.bots.scraper.models.BrowserConfigSchema.md)

Schema for browser configuration

## [ScrapingPlanSchema](entities/class:parrot.bots.scraper.models.ScrapingPlanSchema.md)

Complete scraping plan with steps, selectors, and config

## [ScrapingSelectorSchema](entities/class:parrot.bots.scraper.models.ScrapingSelectorSchema.md)

Schema for content extraction selector

## [ScrapingStepSchema](entities/class:parrot.bots.scraper.models.ScrapingStepSchema.md)

Schema for a single scraping step

## [ScrapingAgent](entities/class:parrot.bots.scraper.scraper.ScrapingAgent.md)

Intelligent web scraping agent that uses LLM to:

## [WebSearchAgent](entities/class:parrot.bots.search.WebSearchAgent.md)

An agent specialized in performing web searches.

## [LocalKBMixin](entities/class:parrot.bots.stores.local.LocalKBMixin.md)

Mixin to add local markdown KB support to agents.

## [VoiceBot](entities/class:parrot.bots.voice.VoiceBot.md)

Bot with native voice interaction capabilities.

## [LazyGroup](entities/class:parrot.cli.LazyGroup.md)

Click group that imports subcommands on first invocation.

## [ConversationTurn](entities/class:parrot.cli.commands.ConversationTurn.md)

A single turn in the conversation history (used by ``/export``).

## [SlashCommand](entities/class:parrot.cli.commands.SlashCommand.md)

A registered slash command.

## [SlashCommandDispatcher](entities/class:parrot.cli.commands.SlashCommandDispatcher.md)

Dispatches slash commands in the agent REPL.

## [AgentLoadError](entities/class:parrot.cli.loaders.AgentLoadError.md)

Raised when an agent cannot be loaded.

## [ServerAgentProxy](entities/class:parrot.cli.loaders.ServerAgentProxy.md)

Proxy agent interactions to a running AI-Parrot server via HTTP.

## [StandaloneAgentLoader](entities/class:parrot.cli.loaders.StandaloneAgentLoader.md)

Load agents from the in-process AgentRegistry.

## [ResponseRenderer](entities/class:parrot.cli.renderer.ResponseRenderer.md)

Renders AIMessage responses to the terminal via Rich.

## [AgentREPL](entities/class:parrot.cli.repl.AgentREPL.md)

Interactive REPL for agent conversation.

## [REPLConfig](entities/class:parrot.cli.repl.REPLConfig.md)

Configuration for an agent REPL session.

## [AWSWorkspaceBackend](entities/class:parrot.clients.anthropic_backends.AWSWorkspaceBackend.md)

Backend strategy for Claude-on-AWS (``AsyncAnthropicAWS``).

## [AnthropicBackendProtocol](entities/class:parrot.clients.anthropic_backends.AnthropicBa-b6c960d7.md)

Structural protocol for Anthropic backend strategies.

## [BedrockBackend](entities/class:parrot.clients.anthropic_backends.BedrockBackend.md)

Backend strategy for AWS Bedrock (``AsyncAnthropicBedrock``).

## [DirectBackend](entities/class:parrot.clients.anthropic_backends.DirectBackend.md)

Backend strategy for the direct Anthropic API (``AsyncAnthropic``).

## [AbstractClient](entities/class:parrot.clients.base.AbstractClient.md)

Abstract base Class for LLM models.

## [BatchRequest](entities/class:parrot.clients.base.BatchRequest.md)

Data structure for batch request.

## [MessageResponse](entities/class:parrot.clients.base.MessageResponse.md)

Response structure for LLM messages.

## [RetryConfig](entities/class:parrot.clients.base.RetryConfig.md)

Configuration for MAX_TOKENS retry behavior.

## [StreamingRetryConfig](entities/class:parrot.clients.base.StreamingRetryConfig.md)

Configuration for streaming retry behavior.

## [TokenRetryMixin](entities/class:parrot.clients.base.TokenRetryMixin.md)

Mixin class to add token retry functionality to any LLM client.

## [BedrockConverseClient](entities/class:parrot.clients.bedrock.BedrockConverseClient.md)

Client for AWS Bedrock's native Converse API.

## [AnthropicClient](entities/class:parrot.clients.claude.AnthropicClient.md)

Client for interacting with the Anthropic API using the official SDK.

## [ClaudeAgentClient](entities/class:parrot.clients.claude_agent.ClaudeAgentClient.md)

Dispatch tasks to a Claude Code agent via ``claude-agent-sdk``.

## [ClaudeAgentRunOptions](entities/class:parrot.clients.claude_agent.ClaudeAgentRunOptions.md)

Run-time options forwarded to ``claude_agent_sdk.ClaudeAgentOptions``.

## [LLMFactory](entities/class:parrot.clients.factory.LLMFactory.md)

Factory for creating LLM client instances from string specifications.

## [Gemma4Client](entities/class:parrot.clients.gemma4.Gemma4Client.md)

Client for Google Gemma 4 multimodal instruction-tuned models.

## [Gemma4Model](entities/class:parrot.clients.gemma4.Gemma4Model.md)

Supported Gemma 4 model variants.

## [GoogleAnalysis](entities/class:parrot.clients.google.analysis.GoogleAnalysis.md)

Mixin class for Google Generative AI analysis capabilities.

## [GoogleGenAIClient](entities/class:parrot.clients.google.client.GoogleGenAIClient.md)

Client for interacting with Google's Generative AI, with support for parallel function calling.

## [GoogleGeneration](entities/class:parrot.clients.google.generation.GoogleGeneration.md)

Mixin class for Google Generative AI generation capabilities (Image, Video, Audio).

## [OpenAIClient](entities/class:parrot.clients.gpt.OpenAIClient.md)

Client for interacting with OpenAI's API.

## [GrokClient](entities/class:parrot.clients.grok.GrokClient.md)

Client for interacting with xAI's Grok models.

## [GrokModel](entities/class:parrot.clients.grok.GrokModel.md)

Grok model versions (xAI API, July 2026).

## [GroqClient](entities/class:parrot.clients.groq.GroqClient.md)

Client for interacting with Groq's API.

## [TransformersClient](entities/class:parrot.clients.hf.TransformersClient.md)

Client for interacting with HuggingFace transformers micro-LLMs.

## [TransformersModel](entities/class:parrot.clients.hf.TransformersModel.md)

Enum for supported transformer models.

## [GeminiLiveClient](entities/class:parrot.clients.live.GeminiLiveClient.md)

Client for Gemini Live API voice interactions.

## [LiveCompletionUsage](entities/class:parrot.clients.live.LiveCompletionUsage.md)

Usage tracking for Gemini Live API responses.

## [LiveToolAdapter](entities/class:parrot.clients.live.LiveToolAdapter.md)

Adapter to convert AI-Parrot AbstractTool instances to Gemini Live API

## [LiveToolCall](entities/class:parrot.clients.live.LiveToolCall.md)

Represents a tool call from Gemini Live API.

## [LiveVoiceResponse](entities/class:parrot.clients.live.LiveVoiceResponse.md)

Response from GeminiLiveClient voice interaction.

## [VoiceTurnMetadata](entities/class:parrot.clients.live.VoiceTurnMetadata.md)

Metadata for a single voice turn/response.

## [LocalLLMClient](entities/class:parrot.clients.localllm.LocalLLMClient.md)

Client for local/self-hosted OpenAI-compatible LLM servers.

## [LLMConfig](entities/class:parrot.clients.models.LLMConfig.md)

Resolved LLM configuration.

## [NovaSonicClient](entities/class:parrot.clients.nova_sonic.NovaSonicClient.md)

Experimental Amazon Nova 2 Sonic bidirectional speech-to-speech client.

## [NvidiaClient](entities/class:parrot.clients.nvidia.NvidiaClient.md)

Client for Nvidia NIM's OpenAI-compatible API gateway.

## [OpenRouterClient](entities/class:parrot.clients.openrouter.OpenRouterClient.md)

Client for OpenRouter's multi-model API gateway.

## [vLLMClient](entities/class:parrot.clients.vllm.vLLMClient.md)

vLLM client with vLLM-specific features.

## [ZaiClient](entities/class:parrot.clients.zai.ZaiClient.md)

Client for Z.ai chat completions using the official ``zai-sdk`` package.

## [Event](entities/class:parrot.core.events.evb.Event.md)

Representa un evento en el bus.

## [EventBus](entities/class:parrot.core.events.evb.EventBus.md)

Bus de eventos con soporte para patrones glob y Redis como backend.

## [EventPriority](entities/class:parrot.core.events.evb.EventPriority.md)

Priority levels for events in the event bus.

## [EventSubscription](entities/class:parrot.core.events.evb.EventSubscription.md)

Subscripción a un patrón de eventos.

## [LifecycleEvent](entities/class:parrot.core.events.lifecycle.base.LifecycleEvent.md)

Read-only base class for every lifecycle event.

## [AgentConfiguredEvent](entities/class:parrot.core.events.lifecycle.events.agent.Age-8f3d3ec7.md)

Emitted at the end of AbstractBot.configure().

## [AgentInitializedEvent](entities/class:parrot.core.events.lifecycle.events.agent.Age-077653c1.md)

Emitted at the end of AbstractBot.__init__.

## [AgentStatusChangedEvent](entities/class:parrot.core.events.lifecycle.events.agent.Age-1a320a83.md)

Emitted when the agent's status property changes.

## [ToolManagerReadyEvent](entities/class:parrot.core.events.lifecycle.events.agent.Too-6f90e844.md)

Emitted after the ToolManager is fully populated.

## [AfterClientCallEvent](entities/class:parrot.core.events.lifecycle.events.client.Af-564911f9.md)

Emitted after a successful LLM API call completes.

## [BeforeClientCallEvent](entities/class:parrot.core.events.lifecycle.events.client.Be-bbd47e38.md)

Emitted just before an LLM API call is made.

## [ClientCallFailedEvent](entities/class:parrot.core.events.lifecycle.events.client.Cl-f54ab13e.md)

Emitted when an LLM API call raises an exception.

## [ClientStreamChunkEvent](entities/class:parrot.core.events.lifecycle.events.client.Cl-88921b60.md)

Emitted for each chunk received during a streaming response.

## [PromptCacheAppliedEvent](entities/class:parrot.core.events.lifecycle.events.client.Pr-43a9de10.md)

Emitted when prompt caching is applied to an LLM call.

## [PromptCacheSkippedEvent](entities/class:parrot.core.events.lifecycle.events.client.Pr-328a616f.md)

Emitted when prompt caching is skipped.

## [FlowCompletedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Flow-e9f798d9.md)

Emitted after the scheduler loop ends and the result is aggregated.

## [FlowStartedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Flow-ff7b3d92.md)

Emitted when ``AgentsFlow.run_flow()`` begins dispatching.

## [NodeCompletedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Node-0c2fe6cc.md)

Emitted when a node's ``execute()`` returns successfully.

## [NodeFailedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Node-f96dc1e8.md)

Emitted when a node fails after exhausting its retry budget.

## [NodeSkippedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Node-e5242433.md)

Emitted when OR-join skip-propagation marks a node as never-run.

## [NodeStartedEvent](entities/class:parrot.core.events.lifecycle.events.flow.Node-eddd0f80.md)

Emitted when the scheduler dispatches a node.

## [AfterInvokeEvent](entities/class:parrot.core.events.lifecycle.events.invoke.Af-7cca13d7.md)

Emitted after a successful agent invocation completes.

## [BeforeInvokeEvent](entities/class:parrot.core.events.lifecycle.events.invoke.Be-84b14859.md)

Emitted just before an agent invocation begins.

## [InvokeFailedEvent](entities/class:parrot.core.events.lifecycle.events.invoke.In-887706fe.md)

Emitted when an agent invocation raises an unhandled exception.

## [MessageAddedEvent](entities/class:parrot.core.events.lifecycle.events.message.M-de6fe1d5.md)

Emitted when a message is added to the conversation history.

## [AfterToolCallEvent](entities/class:parrot.core.events.lifecycle.events.tool.Afte-e5c8a1ae.md)

Emitted after AbstractTool._execute() completes successfully.

## [BeforeToolCallEvent](entities/class:parrot.core.events.lifecycle.events.tool.Befo-183c9a73.md)

Emitted just before AbstractTool._execute() is called.

## [ToolCallFailedEvent](entities/class:parrot.core.events.lifecycle.events.tool.Tool-6dfda3e9.md)

Emitted when AbstractTool._execute() raises an exception.

## [SubscriberErrorEvent](entities/class:parrot.core.events.lifecycle.meta.SubscriberErrorEvent.md)

Emitted to the global registry when a subscriber raises.

## [EventEmitterMixin](entities/class:parrot.core.events.lifecycle.mixin.EventEmitterMixin.md)

Mixin providing a uniform ``self.events: EventRegistry`` interface.

## [EventProvider](entities/class:parrot.core.events.lifecycle.provider.EventProvider.md)

Bundles multiple subscriber callbacks for batch registration.

## [EventRegistry](entities/class:parrot.core.events.lifecycle.registry.EventRegistry.md)

Typed lifecycle event dispatcher.

## [LoggingSubscriber](entities/class:parrot.core.events.lifecycle.subscribers.logg-3f2b5da7.md)

EventProvider that logs every ``LifecycleEvent`` at a configurable level.

## [OpenTelemetrySubscriber](entities/class:parrot.core.events.lifecycle.subscribers.open-c036619c.md)

EventProvider that maps lifecycle events to OpenTelemetry spans.

## [WebhookSubscriber](entities/class:parrot.core.events.lifecycle.subscribers.webh-574e9bba.md)

EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint.

## [TraceContext](entities/class:parrot.core.events.lifecycle.trace.TraceContext.md)

W3C Trace Context for OpenTelemetry-compatible distributed tracing.

## [HumanInteractionInterrupt](entities/class:parrot.core.exceptions.HumanInteractionInterrupt.md)

Raised when an agent tool requests human interaction to continue.

## [BaseHook](entities/class:parrot.core.hooks.base.BaseHook.md)

Abstract base for all external hooks in AutonomousOrchestrator.

## [HookRegistry](entities/class:parrot.core.hooks.base.HookRegistry.md)

Registry for external hook implementations.

## [MessagingHook](entities/class:parrot.core.hooks.base.MessagingHook.md)

Interface for messaging-channel hooks (e.g. matrix, telegram).

## [BaseBrokerHook](entities/class:parrot.core.hooks.brokers.base.BaseBrokerHook.md)

Abstract base for message-queue / stream broker hooks.

## [MQTTBrokerHook](entities/class:parrot.core.hooks.brokers.mqtt.MQTTBrokerHook.md)

Subscribes to MQTT topics using gmqtt.

## [RabbitMQBrokerHook](entities/class:parrot.core.hooks.brokers.rabbitmq.RabbitMQBrokerHook.md)

Consumes messages from a RabbitMQ queue.

## [RedisBrokerHook](entities/class:parrot.core.hooks.brokers.redis.RedisBrokerHook.md)

Consumes messages from a Redis Stream.

## [SQSBrokerHook](entities/class:parrot.core.hooks.brokers.sqs.SQSBrokerHook.md)

Consumes messages from an AWS SQS queue.

## [FileUploadHook](entities/class:parrot.core.hooks.file_upload.FileUploadHook.md)

Exposes an HTTP POST/PUT endpoint that accepts file uploads.

## [FileWatchdogHook](entities/class:parrot.core.hooks.file_watchdog.FileWatchdogHook.md)

Monitors a directory for file changes and emits HookEvents.

## [GitHubWebhookHook](entities/class:parrot.core.hooks.github_webhook.GitHubWebhookHook.md)

Receives GitHub webhook POST requests via an aiohttp route.

## [IMAPWatchdogHook](entities/class:parrot.core.hooks.imap.IMAPWatchdogHook.md)

Monitors an IMAP mailbox for new emails using aioimaplib.

## [JiraWebhookHook](entities/class:parrot.core.hooks.jira_webhook.JiraWebhookHook.md)

Receives Jira webhook POST requests via an aiohttp route.

## [HookManager](entities/class:parrot.core.hooks.manager.HookManager.md)

Manages registration, startup, and shutdown of all external hooks.

## [MatrixHook](entities/class:parrot.core.hooks.matrix.MatrixHook.md)

Compatibility shim for MatrixHook.

## [MSTeamsHook](entities/class:parrot.core.hooks.messaging.MSTeamsHook.md)

Receives MS Teams Activity POSTs via Bot Framework webhook.

## [TelegramHook](entities/class:parrot.core.hooks.messaging.TelegramHook.md)

Receives Telegram messages via webhook and fires HookEvents.

## [WhatsAppHook](entities/class:parrot.core.hooks.messaging.WhatsAppHook.md)

Receives WhatsApp webhook POSTs from Meta Cloud API.

## [HookableAgent](entities/class:parrot.core.hooks.mixins.HookableAgent.md)

Mixin that adds hook support to any agent or integration handler.

## [BrokerHookConfig](entities/class:parrot.core.hooks.models.BrokerHookConfig.md)

Configuration for message broker hooks (Redis, RabbitMQ, MQTT, SQS).

## [FileUploadHookConfig](entities/class:parrot.core.hooks.models.FileUploadHookConfig.md)

Configuration for HTTP file upload hook.

## [FileWatchdogHookConfig](entities/class:parrot.core.hooks.models.FileWatchdogHookConfig.md)

Configuration for file-system watchdog hook.

## [FilesystemHookConfig](entities/class:parrot.core.hooks.models.FilesystemHookConfig.md)

Configuration for FilesystemTransport hook.

## [GitHubWebhookConfig](entities/class:parrot.core.hooks.models.GitHubWebhookConfig.md)

Configuration for GitHub webhook receiver.

## [HookEvent](entities/class:parrot.core.hooks.models.HookEvent.md)

Unified event emitted by any hook into the orchestrator.

## [HookType](entities/class:parrot.core.hooks.models.HookType.md)

Supported hook types.

## [IMAPHookConfig](entities/class:parrot.core.hooks.models.IMAPHookConfig.md)

Configuration for IMAP mailbox monitoring hook.

## [JiraWebhookConfig](entities/class:parrot.core.hooks.models.JiraWebhookConfig.md)

Configuration for Jira webhook receiver.

## [MatrixHookConfig](entities/class:parrot.core.hooks.models.MatrixHookConfig.md)

Configuration for Matrix protocol hook.

## [MessagingHookConfig](entities/class:parrot.core.hooks.models.MessagingHookConfig.md)

Configuration for messaging platform hooks (Telegram, WhatsApp, MS Teams).

## [PostgresHookConfig](entities/class:parrot.core.hooks.models.PostgresHookConfig.md)

Configuration for PostgreSQL LISTEN/NOTIFY hook.

## [SchedulerHookConfig](entities/class:parrot.core.hooks.models.SchedulerHookConfig.md)

Configuration for the APScheduler-based hook.

## [SharePointHookConfig](entities/class:parrot.core.hooks.models.SharePointHookConfig.md)

Configuration for SharePoint webhook hook.

## [TransitionAction](entities/class:parrot.core.hooks.models.TransitionAction.md)

A single transition-to-action mapping.

## [TransitionActionType](entities/class:parrot.core.hooks.models.TransitionActionType.md)

Supported action types for Jira transition handlers.

## [WhatsAppRedisHookConfig](entities/class:parrot.core.hooks.models.WhatsAppRedisHookConfig.md)

Configuration for WhatsApp Redis Bridge hook.

## [PostgresListenHook](entities/class:parrot.core.hooks.postgres.PostgresListenHook.md)

Listens to a PostgreSQL channel via LISTEN/NOTIFY and emits HookEvents.

## [SchedulerHook](entities/class:parrot.core.hooks.scheduler.SchedulerHook.md)

Periodically fires events using APScheduler (cron or interval).

## [SharePointHook](entities/class:parrot.core.hooks.sharepoint.SharePointHook.md)

Subscribes to SharePoint changes via Microsoft Graph API.

## [WhatsAppRedisHook](entities/class:parrot.core.hooks.whatsapp_redis.WhatsAppRedisHook.md)

WhatsApp message listener via Redis Pub/Sub.

## [HandoffTool](entities/class:parrot.core.tools.handoff.HandoffTool.md)

Tool for handing off task execution to a human user.

## [HandoffToolSchema](entities/class:parrot.core.tools.handoff.HandoffToolSchema.md)

Arguments for the HandoffTool.

## [AuthenticatedUser](entities/class:parrot.core.ws_auth.AuthenticatedUser.md)

Represents an authenticated user from a JWT token.

## [TokenValidator](entities/class:parrot.core.ws_auth.TokenValidator.md)

JWT Token validator.

## [EmbeddingModel](entities/class:parrot.embeddings.base.EmbeddingModel.md)

Abstract base class for embedding models.

## [EmbeddingModelEntry](entities/class:parrot.embeddings.catalog.EmbeddingModelEntry.md)

Validation schema for a single catalog entry.

## [GoogleEmbeddingModel](entities/class:parrot.embeddings.google.GoogleEmbeddingModel.md)

A wrapper class for Google Embedding models using the Gemini API.

## [ModelType](entities/class:parrot.embeddings.huggingface.ModelType.md)

Enumerator for different model types used in embeddings.

## [SentenceTransformerModel](entities/class:parrot.embeddings.huggingface.SentenceTransformerModel.md)

A wrapper class for HuggingFace sentence-transformers embeddings.

## [MatryoshkaConfig](entities/class:parrot.embeddings.matryoshka.MatryoshkaConfig.md)

Operator-supplied Matryoshka truncation configuration.

## [EmbeddingBackend](entities/class:parrot.embeddings.multimodal.base.EmbeddingBackend.md)

Runtime backend for multimodal inference.

## [EmbeddingResult](entities/class:parrot.embeddings.multimodal.base.EmbeddingResult.md)

Return type for all embed_* methods.

## [MultimodalEmbedding](entities/class:parrot.embeddings.multimodal.base.MultimodalEmbedding.md)

Modality-aware embedding provider ABC.

## [QuantizationMode](entities/class:parrot.embeddings.multimodal.base.QuantizationMode.md)

Post-processing quantization mode for vector storage.

## [UFormEmbedding](entities/class:parrot.embeddings.multimodal.uform.UFormEmbedding.md)

UForm-backed multimodal embedding provider.

## [OpenAIEmbeddingModel](entities/class:parrot.embeddings.openai.OpenAIEmbeddingModel.md)

A wrapper class for OpenAI Embedding models.

## [LateChunkingProcessor](entities/class:parrot.embeddings.processor.LateChunkingProcessor.md)

Processor for handling late chunking of documents using embeddings.

## [EmbeddingRegistry](entities/class:parrot.embeddings.registry.EmbeddingRegistry.md)

Process-wide singleton for embedding model caching with LRU eviction.

## [RegistryStats](entities/class:parrot.embeddings.registry.RegistryStats.md)

Statistics exposed by the EmbeddingRegistry.

## [DatasetLoader](entities/class:parrot.eval.datasets.DatasetLoader.md)

Abstract loader that reads a benchmark file into an ``EvalDataset``.

## [HFDatasetLoader](entities/class:parrot.eval.datasets.HFDatasetLoader.md)

Reserved stub for Hugging Face dataset ingest.

## [JSONLDatasetLoader](entities/class:parrot.eval.datasets.JSONLDatasetLoader.md)

Load an ``EvalDataset`` from a JSONL file.

## [YAMLDatasetLoader](entities/class:parrot.eval.datasets.YAMLDatasetLoader.md)

Load an ``EvalDataset`` from a YAML file.

## [AbstractEvaluator](entities/class:parrot.eval.evaluators.base.AbstractEvaluator.md)

Abstract base for evaluators that combine one or more metrics.

## [Metric](entities/class:parrot.eval.evaluators.base.Metric.md)

Abstract base for a single evaluation metric.

## [StateBasedEvaluator](entities/class:parrot.eval.evaluators.state_based.StateBasedEvaluator.md)

Evaluator for state-based (τ-bench style) agent tasks.

## [StateMatch](entities/class:parrot.eval.evaluators.state_based.StateMatch.md)

Subset-match metric comparing final state to ``goal_state``.

## [EvalRolloutCompleted](entities/class:parrot.eval.events.EvalRolloutCompleted.md)

Emitted after a (task, attempt) rollout completes successfully.

## [EvalRolloutFailed](entities/class:parrot.eval.events.EvalRolloutFailed.md)

Emitted when a (task, attempt) rollout raises an exception.

## [EvalRolloutStarted](entities/class:parrot.eval.events.EvalRolloutStarted.md)

Emitted just before a (task, attempt) rollout begins.

## [EvalRunCompleted](entities/class:parrot.eval.events.EvalRunCompleted.md)

Emitted when ``EvalRunner.run()`` finishes (whether or not all tasks

## [EvalRunStarted](entities/class:parrot.eval.events.EvalRunStarted.md)

Emitted when ``EvalRunner.run()`` begins.

## [EvalDataset](entities/class:parrot.eval.models.EvalDataset.md)

A named collection of evaluation tasks.

## [EvalResult](entities/class:parrot.eval.models.EvalResult.md)

Evaluation outcome for a single (task, attempt) pair.

## [EvalTask](entities/class:parrot.eval.models.EvalTask.md)

A single evaluation task (input + ground-truth expectation).

## [MetricScore](entities/class:parrot.eval.models.MetricScore.md)

Score for a single metric on one attempt.

## [TokenUsage](entities/class:parrot.eval.models.TokenUsage.md)

Aggregated token counts for a trajectory attempt.

## [ToolCallRecord](entities/class:parrot.eval.models.ToolCallRecord.md)

Record of a single tool invocation during a trajectory turn.

## [Trajectory](entities/class:parrot.eval.models.Trajectory.md)

Full record of one agent attempt on a task.

## [TurnRecord](entities/class:parrot.eval.models.TurnRecord.md)

A single conversational turn in a trajectory.

## [ConversationalRollout](entities/class:parrot.eval.rollout.ConversationalRollout.md)

Multi-turn rollout that loops ``bot.conversation()`` against a simulator.

## [LLMUserSimulator](entities/class:parrot.eval.rollout.LLMUserSimulator.md)

User simulator backed by an LLM (``AbstractClient.ask()``).

## [RolloutStrategy](entities/class:parrot.eval.rollout.RolloutStrategy.md)

Abstract strategy for driving an agent through a task.

## [SingleTurnRollout](entities/class:parrot.eval.rollout.SingleTurnRollout.md)

One-shot rollout: a single ``bot.ask()`` call.

## [UserSimulator](entities/class:parrot.eval.rollout.UserSimulator.md)

Abstract user-side simulator for conversational rollouts.

## [EvalReport](entities/class:parrot.eval.runner.EvalReport.md)

Aggregated results of one evaluation run.

## [EvalRunConfig](entities/class:parrot.eval.runner.EvalRunConfig.md)

Configuration for a single evaluation run.

## [EvalRunner](entities/class:parrot.eval.runner.EvalRunner.md)

Orchestrates an evaluation run across all tasks in a dataset.

## [ExecResult](entities/class:parrot.eval.sandbox.base.ExecResult.md)

Result of a command executed inside a sandbox.

## [NoopSandbox](entities/class:parrot.eval.sandbox.base.NoopSandbox.md)

No-operation sandbox for agents that do not mutate external state.

## [NoopSandboxProvider](entities/class:parrot.eval.sandbox.base.NoopSandboxProvider.md)

Provider that always returns a fresh ``NoopSandbox``.

## [Sandbox](entities/class:parrot.eval.sandbox.base.Sandbox.md)

Abstract execution environment for agent evaluation.

## [SandboxProvider](entities/class:parrot.eval.sandbox.base.SandboxProvider.md)

Factory that acquires and releases ``Sandbox`` instances.

## [SandboxSpec](entities/class:parrot.eval.sandbox.base.SandboxSpec.md)

Configuration for a sandbox instance.

## [FakeJiraClient](entities/class:parrot.eval.sandbox.fakes.FakeJiraClient.md)

In-memory Jira client backed by a ``DictStateBackend``.

## [FakeRawConnection](entities/class:parrot.eval.sandbox.fakes.FakeRawConnection.md)

Fake asyncpg connection that routes CRUD SQL to a ``DictStateBackend``.

## [FakeTableMetadata](entities/class:parrot.eval.sandbox.fakes.FakeTableMetadata.md)

Minimal table metadata stub used by ``DatabaseToolkitBinder``.

## [StaticResolver](entities/class:parrot.eval.sandbox.fakes.StaticResolver.md)

Credential resolver that always returns a pre-built ``FakeJiraClient``.

## [DatabaseToolkitBinder](entities/class:parrot.eval.sandbox.state.DatabaseToolkitBinder.md)

Binder for ``DatabaseToolkit`` (``PostgresToolkit``) subclasses.

## [DictStateBackend](entities/class:parrot.eval.sandbox.state.DictStateBackend.md)

In-memory ``{collection: {entity_id: {field: value}}}`` store.

## [InMemoryStateSandbox](entities/class:parrot.eval.sandbox.state.InMemoryStateSandbox.md)

State-based sandbox that owns a ``DictStateBackend``.

## [InMemoryStateSandboxProvider](entities/class:parrot.eval.sandbox.state.InMemoryStateSandboxProvider.md)

Provider that provisions a fresh ``InMemoryStateSandbox`` per attempt.

## [JiraToolkitBinder](entities/class:parrot.eval.sandbox.state.JiraToolkitBinder.md)

Binder for ``JiraToolkit``.

## [StateBackend](entities/class:parrot.eval.sandbox.state.StateBackend.md)

Abstract resettable world-state store.

## [ToolkitBinder](entities/class:parrot.eval.sandbox.state.ToolkitBinder.md)

Abstract binder that wires a StateBackend into a concrete toolkit.

## [EvalReportSink](entities/class:parrot.eval.sink.EvalReportSink.md)

Abstract persistence sink for ``EvalReport`` objects.

## [PostgresEvalSink](entities/class:parrot.eval.sink.PostgresEvalSink.md)

Persist ``EvalReport`` objects to Postgres via asyncpg.

## [ConfigError](entities/class:parrot.exceptions.ConfigError.md)

Raised for configuration-related errors.

## [DriverError](entities/class:parrot.exceptions.DriverError.md)

Raised for errors related to driver operations.

## [InvokeError](entities/class:parrot.exceptions.InvokeError.md)

Raised when an ``invoke()`` call fails.

## [ParrotError](entities/class:parrot.exceptions.ParrotError.md)

Base class for Parrot exceptions.

## [SpeechGenerationError](entities/class:parrot.exceptions.SpeechGenerationError.md)

Raised for errors related to speech generation.

## [ToolError](entities/class:parrot.exceptions.ToolError.md)

Raised for errors related to tool operations.

## [AbstractCodeReviewDispatcher](entities/class:parrot.flows.dev_loop.code_review.AbstractCod-b0115bd2.md)

ABC for all code review dispatchers.

## [ClaudeCodeReviewDispatcher](entities/class:parrot.flows.dev_loop.code_review.ClaudeCodeR-d2568294.md)

Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.

## [CodeReviewDispatcherFactory](entities/class:parrot.flows.dev_loop.code_review.CodeReviewD-cbc21c6b.md)

Factory for creating code review dispatchers.

## [CodexCodeReviewDispatcher](entities/class:parrot.flows.dev_loop.code_review.CodexCodeRe-d4d6f2c0.md)

Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.

## [GeminiCodeReviewDispatcher](entities/class:parrot.flows.dev_loop.code_review.GeminiCodeR-fb00b66c.md)

Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.

## [ClaudeCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.ClaudeCodeDispatcher.md)

Thin orchestration class over :class:`ClaudeAgentClient`.

## [CodexCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.CodexCodeDispatcher.md)

Thin orchestration class over ``codex exec --json``.

## [DevLoopCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.DevLoopCodeDispatcher.md)

Shared dispatch contract consumed by dev-loop code-agent nodes.

## [DispatchExecutionError](entities/class:parrot.flows.dev_loop.dispatcher.DispatchExec-bb945e4a.md)

Raised when the Claude Code session fails before producing a result.

## [DispatchOutputValidationError](entities/class:parrot.flows.dev_loop.dispatcher.DispatchOutp-a87bd9b8.md)

Raised when the final ResultMessage payload fails to validate.

## [GeminiCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.GeminiCodeDispatcher.md)

Thin orchestration class over ``gemini --output-format stream-json``.

## [GrokCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.GrokCodeDispatcher.md)

Local coding-agent loop tailored for Grok client and Grok Build model.

## [LLMCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.LLMCodeDispatcher.md)

Local coding-agent loop for OpenAI-compatible LLM clients.

## [ZaiCodeDispatcher](entities/class:parrot.flows.dev_loop.dispatcher.ZaiCodeDispatcher.md)

Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.

## [FlowEventPublisher](entities/class:parrot.flows.dev_loop.flow.FlowEventPublisher.md)

Publishes AgentsFlow node-lifecycle events to ``flow:{run_id}:flow``.

## [ClaudeCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.ClaudeCodeDispatchProfile.md)

Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.

## [ClaudeCodeReviewProfile](entities/class:parrot.flows.dev_loop.models.ClaudeCodeReviewProfile.md)

Review profile for the Claude Code review dispatcher (FEAT-270).

## [CodeReviewFinding](entities/class:parrot.flows.dev_loop.models.CodeReviewFinding.md)

A single finding from the code review (FEAT-270).

## [CodeReviewVerdict](entities/class:parrot.flows.dev_loop.models.CodeReviewVerdict.md)

Extended verdict emitted by all code review dispatchers (FEAT-270).

## [CodexCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.CodexCodeDispatchProfile.md)

Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.

## [CodexCodeReviewProfile](entities/class:parrot.flows.dev_loop.models.CodexCodeReviewProfile.md)

Review profile for the Codex code review dispatcher (FEAT-270).

## [CriterionResult](entities/class:parrot.flows.dev_loop.models.CriterionResult.md)

Result of running a single acceptance criterion in QA.

## [DevelopmentOutput](entities/class:parrot.flows.dev_loop.models.DevelopmentOutput.md)

Structured output from the ``sdd-worker`` dispatch.

## [DispatchEvent](entities/class:parrot.flows.dev_loop.models.DispatchEvent.md)

Envelope for stream-json events published to Redis.

## [FlowtaskCriterion](entities/class:parrot.flows.dev_loop.models.FlowtaskCriterion.md)

Run a Flowtask YAML/JSON pipeline and assert its exit code.

## [GeminiCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.GeminiCodeDispatchProfile.md)

Declarative profile consumed by ``GeminiCodeDispatcher.dispatch()``.

## [GeminiCodeReviewProfile](entities/class:parrot.flows.dev_loop.models.GeminiCodeReviewProfile.md)

Review profile for the Gemini code review dispatcher (FEAT-270).

## [GrokCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.GrokCodeDispatchProfile.md)

Declarative profile consumed by ``GrokCodeDispatcher.dispatch()``.

## [LLMCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.LLMCodeDispatchProfile.md)

Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.

## [LogSource](entities/class:parrot.flows.dev_loop.models.LogSource.md)

A pointer to a log location that ``ResearchNode`` will fetch.

## [ManualCriterion](entities/class:parrot.flows.dev_loop.models.ManualCriterion.md)

Human-readable acceptance statement that the QA subagent must NOT run.

## [QAReport](entities/class:parrot.flows.dev_loop.models.QAReport.md)

Structured output from the ``sdd-qa`` dispatch.

## [RepoSpec](entities/class:parrot.flows.dev_loop.models.RepoSpec.md)

A git repository the dev-loop run operates on.

## [ResearchOutput](entities/class:parrot.flows.dev_loop.models.ResearchOutput.md)

Structured output from the ``sdd-research`` dispatch.

## [RevisionBrief](entities/class:parrot.flows.dev_loop.models.RevisionBrief.md)

Input to a revision-mode run (no new PR; update an existing one).

## [ShellCriterion](entities/class:parrot.flows.dev_loop.models.ShellCriterion.md)

Run an allow-listed shell command and assert its exit code.

## [WorkBrief](entities/class:parrot.flows.dev_loop.models.WorkBrief.md)

User-facing input contract for the dev-loop flow.

## [ZaiCodeDispatchProfile](entities/class:parrot.flows.dev_loop.models.ZaiCodeDispatchProfile.md)

Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

## [DevLoopNode](entities/class:parrot.flows.dev_loop.nodes.base.DevLoopNode.md)

Base node for the dev-loop flow (FEAT-129 / FEAT-132).

## [BugIntakeNode](entities/class:parrot.flows.dev_loop.nodes.bug_intake.BugIntakeNode.md)

Bug-specific intake hook — emits ``flow.bug_brief_validated`` event.

## [DevLoopCloseNode](entities/class:parrot.flows.dev_loop.nodes.close.DevLoopCloseNode.md)

Terminal node — Jira summary comment + transition, then end the flow.

## [DeploymentHandoffNode](entities/class:parrot.flows.dev_loop.nodes.deployment_handof-e12a960d.md)

Fifth (success-path) node — handles PR creation and Jira handoff.

## [DevelopmentNode](entities/class:parrot.flows.dev_loop.nodes.development.Devel-b9d1703b.md)

Third node — dispatches the implementation phase to ``sdd-worker``.

## [FailureHandlerNode](entities/class:parrot.flows.dev_loop.nodes.failure_handler.F-1b868dd7.md)

Terminal failure node — comment + transition + reassign on Jira.

## [IntentClassifierNode](entities/class:parrot.flows.dev_loop.nodes.intent_classifier-357aa990.md)

Validates a :class:`WorkBrief` and routes by ``kind``.

## [QANode](entities/class:parrot.flows.dev_loop.nodes.qa.QANode.md)

Fourth node — runs deterministic acceptance verification.

## [ResearchNode](entities/class:parrot.flows.dev_loop.nodes.research.ResearchNode.md)

Second node — Jira + log fetch + sdd-research dispatch.

## [RevisionHandoffNode](entities/class:parrot.flows.dev_loop.nodes.revision_handoff.-b181bb3d.md)

Revision-path handoff — push existing branch + comment existing PR.

## [DevLoopRunner](entities/class:parrot.flows.dev_loop.runner.DevLoopRunner.md)

Hosts dev-loop flow runs behind a global concurrency cap.

## [FlowStreamMultiplexer](entities/class:parrot.flows.dev_loop.streaming.FlowStreamMultiplexer.md)

Merge events from a flow stream and many dispatch streams.

## [RevisionWebhookHandler](entities/class:parrot.flows.dev_loop.webhook.RevisionWebhookHandler.md)

React to ``github.pr_comment`` / ``github.pr_review`` events.

## [FormCache](entities/class:parrot.forms.cache.FormCache.md)

In-memory TTL cache for FormSchema with optional Redis backend.

## [ConditionOperator](entities/class:parrot.forms.constraints.ConditionOperator.md)

Operators for field conditions in dependency rules.

## [DependencyRule](entities/class:parrot.forms.constraints.DependencyRule.md)

Rule controlling conditional visibility/behavior of a field or section.

## [FieldCondition](entities/class:parrot.forms.constraints.FieldCondition.md)

A single condition referencing another field's value.

## [FieldConstraints](entities/class:parrot.forms.constraints.FieldConstraints.md)

Constraints applied to a form field for validation.

## [JsonSchemaExtractor](entities/class:parrot.forms.extractors.jsonschema.JsonSchemaExtractor.md)

Converts JSON Schema dicts into FormSchema instances.

## [PydanticExtractor](entities/class:parrot.forms.extractors.pydantic.PydanticExtractor.md)

Extracts FormSchema from Pydantic v2 BaseModel classes.

## [ToolExtractor](entities/class:parrot.forms.extractors.tool.ToolExtractor.md)

Extracts FormSchema from AbstractTool.args_schema.

## [YamlExtractor](entities/class:parrot.forms.extractors.yaml.YamlExtractor.md)

Parses YAML form definitions into FormSchema instances.

## [FieldOption](entities/class:parrot.forms.options.FieldOption.md)

A single option in a select or multi-select field.

## [OptionsSource](entities/class:parrot.forms.options.OptionsSource.md)

Dynamic options source configuration for fetching options at runtime.

## [FormRegistry](entities/class:parrot.forms.registry.FormRegistry.md)

Thread-safe registry for FormSchema objects.

## [FormStorage](entities/class:parrot.forms.registry.FormStorage.md)

Abstract base class for form persistence backends.

## [AdaptiveCardRenderer](entities/class:parrot.forms.renderers.adaptive_card.Adaptive-2839db19.md)

Renders FormSchema as Adaptive Card JSON for MS Teams.

## [AbstractFormRenderer](entities/class:parrot.forms.renderers.base.AbstractFormRenderer.md)

Abstract base for form renderers.

## [HTML5Renderer](entities/class:parrot.forms.renderers.html5.HTML5Renderer.md)

Renders FormSchema as an HTML5 <form> fragment.

## [JsonSchemaRenderer](entities/class:parrot.forms.renderers.jsonschema.JsonSchemaRenderer.md)

Renders FormSchema as a structural JSON Schema with x- extensions.

## [FormField](entities/class:parrot.forms.schema.FormField.md)

A single field within a form section.

## [FormSchema](entities/class:parrot.forms.schema.FormSchema.md)

The canonical representation of a complete form.

## [FormSection](entities/class:parrot.forms.schema.FormSection.md)

A logical grouping of fields within a form.

## [FormSubsection](entities/class:parrot.forms.schema.FormSubsection.md)

A visual sub-grouping of fields within a section.

## [RenderedForm](entities/class:parrot.forms.schema.RenderedForm.md)

Output of a form renderer.

## [SubmitAction](entities/class:parrot.forms.schema.SubmitAction.md)

Defines what happens when a form is submitted.

## [PostgresFormStorage](entities/class:parrot.forms.storage.PostgresFormStorage.md)

Persist FormSchema objects in a PostgreSQL table using asyncpg.

## [FieldSizeHint](entities/class:parrot.forms.style.FieldSizeHint.md)

Size hints for individual form fields.

## [FieldStyleHint](entities/class:parrot.forms.style.FieldStyleHint.md)

Per-field style customization hints.

## [LayoutType](entities/class:parrot.forms.style.LayoutType.md)

Available layout modes for form rendering.

## [StyleSchema](entities/class:parrot.forms.style.StyleSchema.md)

Presentation style configuration for a form.

## [CreateFormInput](entities/class:parrot.forms.tools.create_form.CreateFormInput.md)

Input schema for the create_form tool.

## [CreateFormTool](entities/class:parrot.forms.tools.create_form.CreateFormTool.md)

Create a FormSchema from a natural language prompt using an LLM.

## [DatabaseFormInput](entities/class:parrot.forms.tools.database_form.DatabaseFormInput.md)

Input schema for DatabaseFormTool.

## [DatabaseFormTool](entities/class:parrot.forms.tools.database_form.DatabaseFormTool.md)

Load a form definition from PostgreSQL into a FormSchema.

## [RequestFormInput](entities/class:parrot.forms.tools.request_form.RequestFormInput.md)

Input schema for the request_form tool.

## [RequestFormTool](entities/class:parrot.forms.tools.request_form.RequestFormTool.md)

Platform-agnostic tool that requests a form to collect missing parameters.

## [FieldType](entities/class:parrot.forms.types.FieldType.md)

Supported form field types.

## [FormValidator](entities/class:parrot.forms.validators.FormValidator.md)

Platform-agnostic validator for FormSchema data.

## [ValidationResult](entities/class:parrot.forms.validators.ValidationResult.md)

Result of validating a form submission.

## [AgentTalk](entities/class:parrot.handlers.agent.AgentTalk.md)

AgentTalk Handler - Universal agent conversation interface.

## [PausedEnvelope](entities/class:parrot.handlers.agent.PausedEnvelope.md)

HTTP-200 structured reply returned by AgentTalk when a SUSPEND tool raises

## [AgentTranscribeOnly](entities/class:parrot.handlers.agent_voice.AgentTranscribeOnly.md)

Transcribe-only endpoint for Mode B internal STT (FEAT-249 TASK-1608).

## [AgentVoiceTalk](entities/class:parrot.handlers.agent_voice.AgentVoiceTalk.md)

Voice-capable REST handler: audio → STT → text agent → TTS → audio.

## [AgentHandler](entities/class:parrot.handlers.agents.abstract.AgentHandler.md)

Abstract class for chatbot/agent handlers.

## [JobWSManager](entities/class:parrot.handlers.agents.abstract.JobWSManager.md)

Extends the generic WebSocketManager with one helper that sends

## [RedisWriter](entities/class:parrot.handlers.agents.abstract.RedisWriter.md)

RedisWriter class.

## [DataAnalystHandler](entities/class:parrot.handlers.agents.data.DataAnalystHandler.md)

Handler for creating in-memory empty PandasAgent instances.

## [EphemeralUserAgentHandler](entities/class:parrot.handlers.agents.ephemeral.EphemeralUse-8228561d.md)

Handler for the ephemeral user agent lifecycle.

## [AgentFactoryHandler](entities/class:parrot.handlers.agents.factory.AgentFactoryHandler.md)

POST /api/v1/agents/factory — create a new agent via the factory.

## [AgentSharingHandler](entities/class:parrot.handlers.agents.sharing.AgentSharingHandler.md)

Stub handler for ephemeral agent sharing.

## [UserAgentHandler](entities/class:parrot.handlers.agents.users.UserAgentHandler.md)

CRUD handler for per-user bots.

## [ArtifactDetailView](entities/class:parrot.handlers.artifacts.ArtifactDetailView.md)

Detail operations on a single artifact.

## [ArtifactListView](entities/class:parrot.handlers.artifacts.ArtifactListView.md)

List and create artifacts for a thread.

## [ArtifactPublicHTMLView](entities/class:parrot.handlers.artifacts.ArtifactPublicHTMLView.md)

Public HTML serving endpoint for infographic artifacts.

## [AvatarSessionView](entities/class:parrot.handlers.avatar.AvatarSessionView.md)

Authenticated entrypoint for the avatar start/stop actions.

## [AvatarViewersView](entities/class:parrot.handlers.avatar.AvatarViewersView.md)

Authenticated endpoint to mint extra subscribe-only viewer tokens (Mode C).

## [FullmodeAvatarsView](entities/class:parrot.handlers.avatar_fullmode.FullmodeAvatarsView.md)

Authenticated entrypoint for GET /api/v1/avatar/avatars.

## [FullmodeStartView](entities/class:parrot.handlers.avatar_fullmode.FullmodeStartView.md)

Authenticated entrypoint for POST .../fullmode/{agent_id}/start.

## [FullmodeStopView](entities/class:parrot.handlers.avatar_fullmode.FullmodeStopView.md)

Authenticated entrypoint for POST .../fullmode/{agent_id}/stop.

## [FullmodeTranscriptView](entities/class:parrot.handlers.avatar_fullmode.FullmodeTranscriptView.md)

Authenticated entrypoint for GET /api/v1/avatar/session/{session_id}/transcript.

## [FullmodeVoicesView](entities/class:parrot.handlers.avatar_fullmode.FullmodeVoicesView.md)

Authenticated entrypoint for GET /api/v1/avatar/voices.

## [ChatbotFeedbackHandler](entities/class:parrot.handlers.bots.ChatbotFeedbackHandler.md)

ChatbotFeedbackHandler.

## [ChatbotHandler](entities/class:parrot.handlers.bots.ChatbotHandler.md)

Unified agent management handler.

## [ChatbotSharingQuestion](entities/class:parrot.handlers.bots.ChatbotSharingQuestion.md)

ChatbotSharingQuestion.

## [ChatbotUsageHandler](entities/class:parrot.handlers.bots.ChatbotUsageHandler.md)

ChatbotUsageHandler.

## [FeedbackTypeHandler](entities/class:parrot.handlers.bots.FeedbackTypeHandler.md)

FeedbackTypeHandler.

## [PromptLibraryManagement](entities/class:parrot.handlers.bots.PromptLibraryManagement.md)

PromptLibraryManagement.

## [ToolList](entities/class:parrot.handlers.bots.ToolList.md)

ToolList — returns all registered tools, PBAC-filtered when PDP configured.

## [UserPromptsManagement](entities/class:parrot.handlers.bots.UserPromptsManagement.md)

Per-user prompt library.

## [BotHandler](entities/class:parrot.handlers.chat.BotHandler.md)

BotHandler.

## [BotManagement](entities/class:parrot.handlers.chat.BotManagement.md)

BotManagement.

## [ChatHandler](entities/class:parrot.handlers.chat.ChatHandler.md)

ChatHandler.

## [ChatInteractionHandler](entities/class:parrot.handlers.chat_interaction.ChatInteract-6354d2e2.md)

Manage persisted chat interactions.

## [BotConfigHandler](entities/class:parrot.handlers.config_handler.BotConfigHandler.md)

REST API Handler for BotConfig CRUD operations.

## [CredentialsHandler](entities/class:parrot.handlers.credentials.CredentialsHandler.md)

CRUD handler for user database credentials.

## [CrewExecutionHandler](entities/class:parrot.handlers.crew.execution_handler.CrewEx-de97629f.md)

REST API Handler for running Crew execution and monitoring.

## [CrewExecutionHistoryHandler](entities/class:parrot.handlers.crew.execution_history_handle-34ed54a8.md)

REST API Handler for saved crew execution history, replay, and scheduling.

## [CrewHandler](entities/class:parrot.handlers.crew.handler.CrewHandler.md)

REST API Handler for AgentCrew CRUD operations.

## [CrewJob](entities/class:parrot.handlers.crew.models.CrewJob.md)

Represents an asynchronous crew execution job.

## [CrewJobResponse](entities/class:parrot.handlers.crew.models.CrewJobResponse.md)

Response when creating a new job.

## [CrewJobStatusResponse](entities/class:parrot.handlers.crew.models.CrewJobStatusResponse.md)

Response for job status check.

## [CrewListResponse](entities/class:parrot.handlers.crew.models.CrewListResponse.md)

Response for listing crews.

## [CrewQueryRequest](entities/class:parrot.handlers.crew.models.CrewQueryRequest.md)

Request to query a crew.

## [ExecutionDetail](entities/class:parrot.handlers.crew.models.ExecutionDetail.md)

Full execution record with payload, extending :class:`ExecutionSummary`.

## [ExecutionFilter](entities/class:parrot.handlers.crew.models.ExecutionFilter.md)

Filters for listing saved executions.

## [ExecutionSummary](entities/class:parrot.handlers.crew.models.ExecutionSummary.md)

Summary of a saved execution for list responses.

## [JobStatus](entities/class:parrot.handlers.crew.models.JobStatus.md)

Status of async job execution.

## [PaginatedResponse](entities/class:parrot.handlers.crew.models.PaginatedResponse.md)

Paginated list response.

## [ReplayRequest](entities/class:parrot.handlers.crew.models.ReplayRequest.md)

Request body for replaying a saved execution.

## [ScheduleRequest](entities/class:parrot.handlers.crew.models.ScheduleRequest.md)

Request body for scheduling a saved execution.

## [CrewRedis](entities/class:parrot.handlers.crew.redis_persistence.CrewRedis.md)

Redis-based persistence for AgentsCrew definitions.

## [CrewNotFoundError](entities/class:parrot.handlers.crew.saved_execution_service.-f6df2dfb.md)

The crew referenced by a saved execution no longer exists (or no

## [ExecutionNotFoundError](entities/class:parrot.handlers.crew.saved_execution_service.-7e270946.md)

The requested execution record doesn't exist (or isn't owned by the

## [ReplayValidationError](entities/class:parrot.handlers.crew.saved_execution_service.-80a705ec.md)

The replay/schedule request fails validation for reasons other than

## [SavedExecutionError](entities/class:parrot.handlers.crew.saved_execution_service.-fa6bdf94.md)

Base exception for SavedExecutionService errors.

## [SavedExecutionService](entities/class:parrot.handlers.crew.saved_execution_service.-f42d2748.md)

Orchestration layer for execution history, replay, and scheduling.

## [SchedulerUnavailableError](entities/class:parrot.handlers.crew.saved_execution_service.-4d9f1d9f.md)

No ``scheduler_manager`` is configured on the service.

## [CrewSpecialNodeCatalogHandler](entities/class:parrot.handlers.crew.special_nodes.CrewSpecia-eb2e4046.md)

Returns the curated special-node catalog for the crew builder UI.

## [CrewToolCatalogHandler](entities/class:parrot.handlers.crew.tool_catalog.CrewToolCat-0d546710.md)

Returns the curated tool catalog for the crew builder UI.

## [DashboardHandler](entities/class:parrot.handlers.dashboard_handler.DashboardHandler.md)

REST API Handler for Dashboard CRUD operations.

## [DashboardTabHandler](entities/class:parrot.handlers.dashboard_handler.DashboardTabHandler.md)

REST API Handler for Dashboard Tab CRUD operations.

## [DatabaseDriversHandler](entities/class:parrot.handlers.database.helpers.DatabaseDriv-57862343.md)

Return the list of supported database drivers.

## [DatabaseFormatsHandler](entities/class:parrot.handlers.database.helpers.DatabaseForm-c9bbb310.md)

Return the list of available ``OutputFormat`` values.

## [DatabaseIntentsHandler](entities/class:parrot.handlers.database.helpers.DatabaseInte-cb4f306d.md)

Return the list of available ``QueryIntent`` values.

## [DatabaseRolesHandler](entities/class:parrot.handlers.database.helpers.DatabaseRolesHandler.md)

Return the list of available ``UserRole`` values.

## [DatabaseSchemasHandler](entities/class:parrot.handlers.database.helpers.DatabaseSche-ce62c994.md)

Return cached schema metadata from a running ``DatabaseAgent``.

## [DatasetFilterEnvelope](entities/class:parrot.handlers.dataset_filter_handler.Datase-b1143fab.md)

Typed AgenTalk pass-through envelope for common-field filter requests.

## [DatasetFilterHandler](entities/class:parrot.handlers.dataset_filter_handler.Datase-748f69e6.md)

aiohttp handler for common-field filter endpoints.

## [DatasetManagerHandler](entities/class:parrot.handlers.datasets.DatasetManagerHandler.md)

HTTP handler for managing a user's DatasetManager via REST API.

## [DeepLinkResumeHandler](entities/class:parrot.handlers.deeplink.DeepLinkResumeHandler.md)

Web resume handler for A2UI deep links.

## [GoogleGeneration](entities/class:parrot.handlers.google_generation.GoogleGeneration.md)

Class-based HTTP view to expose Google generation methods.

## [GoogleGenerationHelper](entities/class:parrot.handlers.google_generation.GoogleGener-c0c3871c.md)

Helper for metadata and schema discovery used by :class:`GoogleGeneration`.

## [InfographicTalk](entities/class:parrot.handlers.infographic.InfographicTalk.md)

Dedicated HTTP handler for bot.get_infographic() plus template/theme

## [IntegrationsHandler](entities/class:parrot.handlers.integrations.IntegrationsHandler.md)

Aiohttp class-based view for the OAuth2 integrations API.

## [JobManager](entities/class:parrot.handlers.jobs.job.JobManager.md)

Manages asynchronous job execution for crew operations.

## [AsyncJobManagerMixin](entities/class:parrot.handlers.jobs.mixin.AsyncJobManagerMixin.md)

Async-native mixin for aiohttp views with job manager functionality.

## [JobManagerMixin](entities/class:parrot.handlers.jobs.mixin.JobManagerMixin.md)

Mixin class to add job manager functionality to any BaseView.

## [Job](entities/class:parrot.handlers.jobs.models.Job.md)

Represents an asynchronous execution job.

## [JobStatus](entities/class:parrot.handlers.jobs.models.JobStatus.md)

Status of async job execution.

## [RedisJobStore](entities/class:parrot.handlers.jobs.redis_store.RedisJobStore.md)

Async Redis-backed store for background Job objects.

## [AgentKnowledgeHandler](entities/class:parrot.handlers.knowledge.AgentKnowledgeHandler.md)

Manage an agent's PageIndex / GraphIndex documents over REST.

## [LLMClient](entities/class:parrot.handlers.llm.LLMClient.md)

LLMClient Handler - Interface for direct LLM interaction.

## [LyriaMusicHandler](entities/class:parrot.handlers.lyria_music.LyriaMusicHandler.md)

REST handler for Lyria music generation.

## [MCPActiveHandler](entities/class:parrot.handlers.mcp_helper.MCPActiveHandler.md)

HTTP handler that returns the currently active MCP servers in the session.

## [MCPHelperHandler](entities/class:parrot.handlers.mcp_helper.MCPHelperHandler.md)

HTTP handler for MCP server catalog listing and activation.

## [MCPServerItemHandler](entities/class:parrot.handlers.mcp_helper.MCPServerItemHandler.md)

HTTP handler for deactivating a specific MCP server.

## [MCPPersistenceService](entities/class:parrot.handlers.mcp_persistence.MCPPersistenceService.md)

Handles saving and loading user MCP server configurations in DocumentDB.

## [MediaGen](entities/class:parrot.handlers.mediagen.MediaGen.md)

REST handler for image and video generation.

## [BotModel](entities/class:parrot.handlers.models.bots.BotModel.md)

Unified Bot Model combining chatbot and agent functionality.

## [ChatbotFeedback](entities/class:parrot.handlers.models.bots.ChatbotFeedback.md)

ChatbotFeedback.

## [ChatbotUsage](entities/class:parrot.handlers.models.bots.ChatbotUsage.md)

ChatbotUsage.

## [FeedbackType](entities/class:parrot.handlers.models.bots.FeedbackType.md)

FeedbackType.

## [PromptCategory](entities/class:parrot.handlers.models.bots.PromptCategory.md)

Prompt Category.

## [PromptLibrary](entities/class:parrot.handlers.models.bots.PromptLibrary.md)

PromptLibrary.

## [CredentialDocument](entities/class:parrot.handlers.models.credentials.CredentialDocument.md)

DocumentDB storage model for a user credential.

## [CredentialPayload](entities/class:parrot.handlers.models.credentials.CredentialPayload.md)

Input model for creating/updating a user database credential.

## [CredentialResponse](entities/class:parrot.handlers.models.credentials.CredentialResponse.md)

Response model for a single credential returned by the API.

## [UnderstandingRequest](entities/class:parrot.handlers.models.understanding.Understa-48ee1919.md)

Request body for the image/video understanding endpoint.

## [UnderstandingResponse](entities/class:parrot.handlers.models.understanding.Understa-1e1a1665.md)

Serialised subset of AIMessage returned to callers.

## [UserBotModel](entities/class:parrot.handlers.models.users_bots.UserBotModel.md)

Per-user bot definition.

## [UserPrompts](entities/class:parrot.handlers.models.users_prompts.UserPrompts.md)

Per-user prompt definition.

## [PrintPDFHandler](entities/class:parrot.handlers.print_pdf.PrintPDFHandler.md)

Converts HTML to PDF and returns the PDF as a binary response.

## [ProgramsUserHandler](entities/class:parrot.handlers.programs.ProgramsUserHandler.md)

ProgramsUserHandler.

## [PromptTunerHandler](entities/class:parrot.handlers.prompt.PromptTunerHandler.md)

Runtime system-prompt fine-tuning console.

## [SchedulerCallbacksHandler](entities/class:parrot.handlers.scheduler.SchedulerCallbacksHandler.md)

List supported scheduler callbacks and scheduler types.

## [SchedulerCatalogHelper](entities/class:parrot.handlers.scheduler.SchedulerCatalogHelper.md)

Helper for scheduler metadata exposed through REST endpoints.

## [SchedulerJobsHandler](entities/class:parrot.handlers.scheduler.SchedulerJobsHandler.md)

CRUD handler for scheduler jobs persisted in APScheduler and Postgres.

## [ScrapingHandler](entities/class:parrot.handlers.scraping.handler.ScrapingHandler.md)

Class-based HTTP view for /api/v1/scraping/.

## [ScrapingInfoHandler](entities/class:parrot.handlers.scraping.info.ScrapingInfoHandler.md)

Method-based handler serving reference data for the Scraping UI.

## [ActionInfo](entities/class:parrot.handlers.scraping.models.ActionInfo.md)

Description of a single browser action type for the UI.

## [CrawlRequest](entities/class:parrot.handlers.scraping.models.CrawlRequest.md)

Request body for POST /api/v1/scraping/crawl.

## [DriverTypeInfo](entities/class:parrot.handlers.scraping.models.DriverTypeInfo.md)

Available driver type and its supported browsers.

## [PlanCreateRequest](entities/class:parrot.handlers.scraping.models.PlanCreateRequest.md)

Request body for POST /api/v1/scraping/plans (create a new plan via LLM).

## [PlanSaveRequest](entities/class:parrot.handlers.scraping.models.PlanSaveRequest.md)

Request body for PUT /api/v1/scraping/plans/{name} (save/update a plan).

## [ScrapeRequest](entities/class:parrot.handlers.scraping.models.ScrapeRequest.md)

Request body for POST /api/v1/scraping/scrape.

## [StrategyInfo](entities/class:parrot.handlers.scraping.models.StrategyInfo.md)

Crawl strategy description for the UI.

## [DirectSpatialRequest](entities/class:parrot.handlers.spatial_filter_handler.Direct-2479df24.md)

Request body for the direct (deterministic) spatial filter path.

## [NLSpatialRequest](entities/class:parrot.handlers.spatial_filter_handler.NLSpat-07e58868.md)

Request body for the NL→spec synthesis spatial filter path.

## [NLSpatialSynthesizer](entities/class:parrot.handlers.spatial_filter_handler.NLSpat-73f84243.md)

Thin synthesizer: natural language → SpatialFilterSpec.

## [SpatialFilterEnvelope](entities/class:parrot.handlers.spatial_filter_handler.Spatia-2f493eb7.md)

Typed AgenTalk pass-through envelope for spatial filter requests.

## [SpatialFilterHandler](entities/class:parrot.handlers.spatial_filter_handler.Spatia-4236af6d.md)

aiohttp handler for spatial filter endpoints.

## [VectorStoreHandler](entities/class:parrot.handlers.stores.handler.VectorStoreHandler.md)

REST API for vector store lifecycle management.

## [VectorStoreHelper](entities/class:parrot.handlers.stores.helpers.VectorStoreHelper.md)

Public metadata endpoints for vector store configuration.

## [StreamHandler](entities/class:parrot.handlers.stream.StreamHandler.md)

Streaming Endpoints for Parrot LLM Responses.

## [BotConfigTestHandler](entities/class:parrot.handlers.testing_handler.BotConfigTestHandler.md)

Handler for testing agent configurations via ephemeral sessions.

## [ThreadDetailView](entities/class:parrot.handlers.threads.ThreadDetailView.md)

Detail operations on a single conversation thread.

## [ThreadListView](entities/class:parrot.handlers.threads.ThreadListView.md)

List and create conversation threads.

## [ToolCatalogHandler](entities/class:parrot.handlers.tools_catalog.ToolCatalogHandler.md)

Read-only handler that returns the global tool registry as JSON.

## [UnderstandingHandler](entities/class:parrot.handlers.understanding.UnderstandingHandler.md)

REST handler for image and video understanding.

## [UserSocketManager](entities/class:parrot.handlers.user.UserSocketManager.md)

WebSocket Manager with Redis PubSub integration for per-user interactions.

## [UserObjectsHandler](entities/class:parrot.handlers.user_objects.UserObjectsHandler.md)

Manages session-scoped ToolManager and DatasetManager instances.

## [VideoReelHandler](entities/class:parrot.handlers.video_reel.VideoReelHandler.md)

REST handler for video reel generation using background jobs.

## [HITLResponseBody](entities/class:parrot.handlers.web_hitl.HITLResponseBody.md)

Request body for ``POST /api/v1/agents/hitl/respond``.

## [HITLResponseHandler](entities/class:parrot.handlers.web_hitl.HITLResponseHandler.md)

HTTP handler for ``POST /api/v1/agents/hitl/respond``.

## [SuspendingWebHumanTool](entities/class:parrot.handlers.web_hitl.SuspendingWebHumanTool.md)

WebHumanTool variant wired for stateless REST suspend/resume (FEAT-204).

## [WebHumanTool](entities/class:parrot.handlers.web_hitl.WebHumanTool.md)

A :class:`~parrot.human.tool.HumanTool` that auto-resolves manager

## [ActionBackend](entities/class:parrot.human.actions.backends.base.ActionBackend.md)

Abstract base class for concrete escalation action backends.

## [ActionBackendError](entities/class:parrot.human.actions.backends.base.ActionBackendError.md)

Base exception raised by any ActionBackend on failure.

## [EmailBackendError](entities/class:parrot.human.actions.backends.base.EmailBackendError.md)

Raised when the email backend fails to send a message.

## [NotifyBackendError](entities/class:parrot.human.actions.backends.base.NotifyBackendError.md)

Raised when the async-notify backend fails to deliver a notification.

## [WebhookBackendError](entities/class:parrot.human.actions.backends.base.WebhookBackendError.md)

Raised when the webhook backend fails to post to the endpoint.

## [ZammadBackendError](entities/class:parrot.human.actions.backends.base.ZammadBackendError.md)

Raised when the Zammad backend fails to create a ticket.

## [EmailBackend](entities/class:parrot.human.actions.backends.email.EmailBackend.md)

Send an escalation email via async-notify's email provider.

## [NotifyBackend](entities/class:parrot.human.actions.backends.notify_provider-fcfcd955.md)

Sends an escalation notification through any async-notify provider.

## [WebhookBackend](entities/class:parrot.human.actions.backends.webhook.WebhookBackend.md)

Posts an escalation payload to a configurable webhook endpoint.

## [ZammadBackend](entities/class:parrot.human.actions.backends.zammad.ZammadBackend.md)

Creates a support ticket in a Zammad instance.

## [EscalationAction](entities/class:parrot.human.actions.base.EscalationAction.md)

Abstract base for escalation logic that triggers external systems.

## [NotifyAction](entities/class:parrot.human.actions.notify.NotifyAction.md)

Dispatches one-way escalation notifications to a backend.

## [TicketAction](entities/class:parrot.human.actions.ticket.TicketAction.md)

Dispatches ticket-creation escalation actions to Zammad (V1).

## [ChannelRegistry](entities/class:parrot.human.channels.ChannelRegistry.md)

Registry for HumanChannel implementations.

## [HumanChannel](entities/class:parrot.human.channels.base.HumanChannel.md)

Abstraction over a communication channel with humans.

## [CLIDaemonHumanChannel](entities/class:parrot.human.channels.cli.CLIDaemonHumanChannel.md)

CLI channel for when the agent runs as a daemon/background service.

## [CLIHumanChannel](entities/class:parrot.human.channels.cli.CLIHumanChannel.md)

Interactive CLI channel for Human-in-the-Loop.

## [TeamsHitlConfig](entities/class:parrot.human.channels.teams.TeamsHitlConfig.md)

Boot configuration for the shared HITL bot identity.

## [TeamsHumanChannel](entities/class:parrot.human.channels.teams.TeamsHumanChannel.md)

Teams Human Channel for HITL interactions.

## [TelegramHumanChannel](entities/class:parrot.human.channels.telegram.TelegramHumanChannel.md)

Telegram channel for Human-in-the-Loop interactions.

## [WebHumanChannel](entities/class:parrot.human.channels.web.WebHumanChannel.md)

Human channel that delivers interactions via WebSocket.

## [HITLCompanion](entities/class:parrot.human.cli_companion.HITLCompanion.md)

Interactive CLI companion for the HITL daemon channel.

## [RejectIntentDetector](entities/class:parrot.human.escalation_intent.RejectIntentDetector.md)

Detects escalation intent from free-text user responses.

## [HitlChainExhaustedEvent](entities/class:parrot.human.events.HitlChainExhaustedEvent.md)

Emitted when the escalation chain terminates after exhausting all tiers.

## [HitlTierActionExecutedEvent](entities/class:parrot.human.events.HitlTierActionExecutedEvent.md)

Emitted after a NOTIFY or TICKET action completes successfully.

## [HitlTierActionFailedEvent](entities/class:parrot.human.events.HitlTierActionFailedEvent.md)

Emitted when an action raises an exception or returns ``error=True``.

## [HitlTierAdvancedEvent](entities/class:parrot.human.events.HitlTierAdvancedEvent.md)

Emitted when the escalation cursor moves from one tier to another.

## [HitlTierEnteredEvent](entities/class:parrot.human.events.HitlTierEnteredEvent.md)

Emitted when the escalation cursor enters a tier for the first time.

## [HumanInteractionManager](entities/class:parrot.human.manager.HumanInteractionManager.md)

Orchestrates the full lifecycle of human interactions.

## [BusinessHours](entities/class:parrot.human.models.BusinessHours.md)

Defines a business-hours window for an escalation tier.

## [ChoiceOption](entities/class:parrot.human.models.ChoiceOption.md)

A selectable option presented to the human.

## [ConsensusMode](entities/class:parrot.human.models.ConsensusMode.md)

How to consolidate responses when multiple humans are involved.

## [EscalationActionType](entities/class:parrot.human.models.EscalationActionType.md)

Actions performed when escalating to a tier.

## [EscalationPolicy](entities/class:parrot.human.models.EscalationPolicy.md)

A series of tiered levels for escalating human-in-the-loop requests.

## [EscalationTier](entities/class:parrot.human.models.EscalationTier.md)

Definition of a single level in an escalation policy.

## [HumanInteraction](entities/class:parrot.human.models.HumanInteraction.md)

Represents a request for human input.

## [HumanResponse](entities/class:parrot.human.models.HumanResponse.md)

Response from a human to an interaction.

## [InteractionResult](entities/class:parrot.human.models.InteractionResult.md)

Consolidated result of an interaction after consensus evaluation.

## [InteractionStatus](entities/class:parrot.human.models.InteractionStatus.md)

Lifecycle status of a human interaction.

## [InteractionType](entities/class:parrot.human.models.InteractionType.md)

Type of interaction requested from the human.

## [Severity](entities/class:parrot.human.models.Severity.md)

Declared criticality of a human-interaction request.

## [TimeoutAction](entities/class:parrot.human.models.TimeoutAction.md)

Action to take when an interaction times out.

## [WaitStrategy](entities/class:parrot.human.models.WaitStrategy.md)

Strategy that controls how HumanTool waits for the human response.

## [HumanDecisionNode](entities/class:parrot.human.node.HumanDecisionNode.md)

Pseudo-agent that pauses an AgentsFlow for human input.

## [SuspendedExecution](entities/class:parrot.human.suspended_store.SuspendedExecution.md)

Tool-loop state blob for a suspended HITL interaction.

## [SuspendedExecutionStore](entities/class:parrot.human.suspended_store.SuspendedExecutionStore.md)

Redis-backed store for :class:`SuspendedExecution` blobs.

## [HumanTool](entities/class:parrot.human.tool.HumanTool.md)

Tool that pauses agent execution to request human input.

## [HumanToolInput](entities/class:parrot.human.tool.HumanToolInput.md)

Input schema for the HumanTool.

## [A2AAgentConfig](entities/class:parrot.integrations.a2a.models.A2AAgentConfig.md)

Configuration for a single agent exposed via the A2A protocol.

## [ChannelDeepLinkResume](entities/class:parrot.integrations.a2ui_resume.ChannelDeepLinkResume.md)

Shared per-channel deep-link resume flow for Telegram / MS Teams.

## [OAuth2ProviderConfig](entities/class:parrot.integrations.core.auth.oauth2_provider-b821c0ca.md)

Configuration for a specific OAuth2 identity provider.

## [PostAuthProvider](entities/class:parrot.integrations.core.auth.post_auth.PostA-2332c8aa.md)

Protocol for secondary authentication providers.

## [PostAuthRegistry](entities/class:parrot.integrations.core.auth.post_auth.PostA-113fdc08.md)

Registry mapping provider names to ``PostAuthProvider`` instances.

## [InMemoryStateStore](entities/class:parrot.integrations.core.state.InMemoryStateStore.md)

Simple in-memory key-value store with TTL support.

## [IntegrationStateManager](entities/class:parrot.integrations.core.state.IntegrationStateManager.md)

Manages state for chat integrations (Telegram, MS Teams, Slack, Matrix).

## [AvatarWebSocket](entities/class:parrot.integrations.liveavatar.avatar_ws.Avat-547eb93c.md)

WebSocket bridge that pushes PCM audio frames to the LiveAvatar media server.

## [LiveAvatarClient](entities/class:parrot.integrations.liveavatar.client.LiveAvatarClient.md)

Async HTTP client for the LiveAvatar LITE API.

## [AvatarSessionHandle](entities/class:parrot.integrations.liveavatar.models.AvatarS-03bc126b.md)

Runtime handle for a LiveAvatar LITE session.

## [FullModeConfig](entities/class:parrot.integrations.liveavatar.models.FullModeConfig.md)

FULL mode configuration (extends LITE config with voice/language fields).

## [FullModeSessionHandle](entities/class:parrot.integrations.liveavatar.models.FullMod-6b3fcaaf.md)

Runtime handle for a LiveAvatar FULL mode session.

## [LiveAvatarConfig](entities/class:parrot.integrations.liveavatar.models.LiveAvatarConfig.md)

Configuration for the LiveAvatar LITE API.

## [LiveKitRoomTokens](entities/class:parrot.integrations.liveavatar.models.LiveKit-46edf108.md)

Viewer and agent JWT tokens for a LiveKit Cloud room.

## [StructuredOutputMessage](entities/class:parrot.integrations.liveavatar.models.Structu-1516efdd.md)

Output-bridge contract for structured ai-parrot outputs (FEAT-249, relocated).

## [OutputBridge](entities/class:parrot.integrations.liveavatar.output_bridge.-b267b9b4.md)

Publishes structured ai-parrot outputs to the AgentChat UI WS channel.

## [RedisBroadcastForwarder](entities/class:parrot.integrations.liveavatar.output_transpo-103d33b8.md)

``UserSocketManager``-compatible sink that forwards broadcasts over Redis.

## [RoomAudioPublisher](entities/class:parrot.integrations.liveavatar.room_audio_pub-b20d482d.md)

Headless LiveKit participant that publishes a Supertonic audio track.

## [LiveKitRoomManager](entities/class:parrot.integrations.liveavatar.room_manager.L-e7b891f3.md)

Mint LiveKit Cloud room tokens for the BYO transport.

## [SpeakableFlattener](entities/class:parrot.integrations.liveavatar.speakable.Spea-8c5335e1.md)

Incremental markdown→speakable-text flattener with sentence segmentation.

## [AvatarTurnSpeaker](entities/class:parrot.integrations.liveavatar.speaker.Avatar-97fd5aa6.md)

Speak one chat turn through an already-started LiveAvatar session.

## [AvatarVoiceProvider](entities/class:parrot.integrations.liveavatar.voice_provider-edc61229.md)

Lazily-built, shared Supertonic→PCM provider for avatar speech.

## [VoiceAvatarSession](entities/class:parrot.integrations.liveavatar.voice_session.-97774f69.md)

Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream.

## [IntegrationBotManager](entities/class:parrot.integrations.manager.IntegrationBotManager.md)

Manages bot integrations for exposed agents.

## [MatrixA2ATransport](entities/class:parrot.integrations.matrix.a2a_transport.Matr-6d3cfd61.md)

A2A transport layer using Matrix as the message bus.

## [MatrixAppService](entities/class:parrot.integrations.matrix.appservice.MatrixAppService.md)

Matrix Application Service for AI-Parrot.

## [MatrixClientWrapper](entities/class:parrot.integrations.matrix.client.MatrixClientWrapper.md)

Async wrapper around mautrix Client for AI-Parrot operations.

## [CollaborativeConfig](entities/class:parrot.integrations.matrix.crew.config.Collab-36d0a41c.md)

Configuration for collaborative multi-agent investigation sessions.

## [MatrixCrewAgentEntry](entities/class:parrot.integrations.matrix.crew.config.Matrix-cbb47c53.md)

Configuration for a single agent in the Matrix crew.

## [MatrixCrewConfig](entities/class:parrot.integrations.matrix.crew.config.Matrix-634854a0.md)

Root configuration for a Matrix multi-agent crew.

## [MatrixCoordinator](entities/class:parrot.integrations.matrix.crew.coordinator.M-93de815e.md)

Manages the pinned status board in the general room.

## [MatrixCrewAgentWrapper](entities/class:parrot.integrations.matrix.crew.crew_wrapper.-d3fa8b40.md)

Per-agent handler for incoming Matrix crew messages.

## [DelegationRequest](entities/class:parrot.integrations.matrix.crew.delegation.De-f907c82c.md)

Represents a request to delegate a task to another agent.

## [HybridDelegator](entities/class:parrot.integrations.matrix.crew.delegation.Hy-0825cd01.md)

Orchestrates hybrid tool delegation in a Matrix room.

## [MatrixAgentCard](entities/class:parrot.integrations.matrix.crew.registry.Matr-5466af8e.md)

Agent identity and runtime status for a Matrix crew.

## [MatrixCrewRegistry](entities/class:parrot.integrations.matrix.crew.registry.Matr-d443fb94.md)

Thread-safe in-memory registry tracking agent status in a Matrix crew.

## [MatrixCollaborativeSession](entities/class:parrot.integrations.matrix.crew.session.Matri-137e9e30.md)

Stateful session managing one collaborative investigation in a Matrix room.

## [AgentRoundResult](entities/class:parrot.integrations.matrix.crew.session_model-b0aa6924.md)

Result from one agent for one investigation round.

## [CollaborativeSessionState](entities/class:parrot.integrations.matrix.crew.session_model-fe94dc4d.md)

Full state of a collaborative investigation session.

## [SessionPhase](entities/class:parrot.integrations.matrix.crew.session_model-ba0efea7.md)

Phase in the collaborative session lifecycle.

## [MatrixCrewTransport](entities/class:parrot.integrations.matrix.crew.transport.Mat-4fbe45cd.md)

Top-level orchestrator for a Matrix multi-agent crew.

## [AgentCardEventContent](entities/class:parrot.integrations.matrix.events.AgentCardEv-4a34bea4.md)

Content of m.parrot.agent_card state event.

## [ParrotEventType](entities/class:parrot.integrations.matrix.events.ParrotEventType.md)

Matrix event type constants for AI-Parrot.

## [ResultEventContent](entities/class:parrot.integrations.matrix.events.ResultEventContent.md)

Content of m.parrot.result message event.

## [StatusEventContent](entities/class:parrot.integrations.matrix.events.StatusEventContent.md)

Content of m.parrot.status message event.

## [TaskEventContent](entities/class:parrot.integrations.matrix.events.TaskEventContent.md)

Content of m.parrot.task message event.

## [MatrixHook](entities/class:parrot.integrations.matrix.hook.MatrixHook.md)

Matrix message listener via mautrix-python.

## [MatrixAppServiceConfig](entities/class:parrot.integrations.matrix.models.MatrixAppSe-04a7be11.md)

Configuration for Matrix Application Service mode.

## [MatrixStreamHandler](entities/class:parrot.integrations.matrix.streaming.MatrixSt-89e08d76.md)

Handles streaming LLM output to a Matrix room via message edits.

## [FirefliesCredentialResolver](entities/class:parrot.integrations.mcp.fireflies_a2a.Firefli-d4fbda4c.md)

Per-user static API key resolver for the Fireflies.ai MCP server.

## [IntegrationBotConfig](entities/class:parrot.integrations.models.IntegrationBotConfig.md)

Root configuration for all Bot Integrations.

## [ParrotM365Agent](entities/class:parrot.integrations.msagentsdk.agent.ParrotM365Agent.md)

Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.

## [BFTokenServiceResolver](entities/class:parrot.integrations.msagentsdk.auth.BFTokenSe-5021bc94.md)

Resolves per-user tokens from the Bot Framework Token Service.

## [CardRenderError](entities/class:parrot.integrations.msagentsdk.cards.CardRenderError.md)

Raised when a `SemanticUIResult` cannot be rendered within limits.

## [MSAgentIntegrationConfig](entities/class:parrot.integrations.msagentsdk.models.MSAgent-b1e1d2c4.md)

Configuration for a full-featured Microsoft Agents SDK bot exposed via

## [MSAgentSDKConfig](entities/class:parrot.integrations.msagentsdk.models.MSAgentSDKConfig.md)

Configuration for a single agent exposed via Microsoft 365 Agents SDK.

## [MsaConversationRefStore](entities/class:parrot.integrations.msagentsdk.resume.MsaConv-6cb5443c.md)

Async store for :class:`MsaConversationReference` records.

## [MsaConversationReference](entities/class:parrot.integrations.msagentsdk.resume.MsaConv-4ca27e3f.md)

Minimal conversation reference for MSAgentSDK proactive resume.

## [DetailPayload](entities/class:parrot.integrations.msagentsdk.semantic.DetailPayload.md)

An entity-detail result payload.

## [MetricsPayload](entities/class:parrot.integrations.msagentsdk.semantic.MetricsPayload.md)

A metrics/KPI result payload.

## [SemanticUIResult](entities/class:parrot.integrations.msagentsdk.semantic.Seman-93f1484e.md)

Card-oriented semantic description of an agent result.

## [StatusPayload](entities/class:parrot.integrations.msagentsdk.semantic.StatusPayload.md)

A status/error result payload.

## [TablePayload](entities/class:parrot.integrations.msagentsdk.semantic.TablePayload.md)

A tabular result payload.

## [UIAction](entities/class:parrot.integrations.msagentsdk.semantic.UIAction.md)

A card action button.

## [UIField](entities/class:parrot.integrations.msagentsdk.semantic.UIField.md)

A single labeled field, used by :class:`DetailPayload`.

## [UIMetric](entities/class:parrot.integrations.msagentsdk.semantic.UIMetric.md)

A single KPI/metric entry, used by :class:`MetricsPayload`.

## [MSAgentSDKWrapper](entities/class:parrot.integrations.msagentsdk.wrapper.MSAgen-c6bb3d72.md)

ai-parrot integration wrapper for the Microsoft 365 Agents SDK.

## [Adapter](entities/class:parrot.integrations.msteams.adapter.Adapter.md)

Handler for Bot Configuration.

## [MSTeamsCommandRouter](entities/class:parrot.integrations.msteams.commands.MSTeamsC-a3ea17db.md)

Detects and routes text commands in ``on_message_activity``.

## [AgentCommandHandler](entities/class:parrot.integrations.msteams.commands.agent_co-7341d1ca.md)

Core agent commands for MS Teams.

## [FormDialogFactory](entities/class:parrot.integrations.msteams.dialogs.factory.F-82acd91f.md)

Factory to create WaterfallDialogs from FormSchemas.

## [FormOrchestrator](entities/class:parrot.integrations.msteams.dialogs.orchestra-f7a560ef.md)

Orchestrates the form-based interaction flow.

## [PendingExecution](entities/class:parrot.integrations.msteams.dialogs.orchestra-73d8222d.md)

Tracks a pending tool execution after form completion.

## [ProcessResult](entities/class:parrot.integrations.msteams.dialogs.orchestra-0b709cce.md)

Result of processing a message.

## [BaseFormDialog](entities/class:parrot.integrations.msteams.dialogs.presets.b-0544b63d.md)

Base class for all form dialog presets.

## [ConversationalFormDialog](entities/class:parrot.integrations.msteams.dialogs.presets.c-1612f746.md)

Conversational form using native BotBuilder prompts.

## [SimpleFormDialog](entities/class:parrot.integrations.msteams.dialogs.presets.s-11044b79.md)

Single Adaptive Card containing all form fields.

## [WizardFormDialog](entities/class:parrot.integrations.msteams.dialogs.presets.w-1c2c12d4.md)

Multi-step wizard dialog with one section per step.

## [WizardWithSummaryDialog](entities/class:parrot.integrations.msteams.dialogs.presets.w-06d0bc9c.md)

Multi-step wizard with a final summary/confirmation step.

## [GraphClient](entities/class:parrot.integrations.msteams.graph.GraphClient.md)

Async Microsoft Graph client for the Teams HITL channel.

## [ResolvedTeamsUser](entities/class:parrot.integrations.msteams.graph.ResolvedTeamsUser.md)

Result of a successful Graph email-to-AAD resolution.

## [MessageHandler](entities/class:parrot.integrations.msteams.handler.MessageHandler.md)

Interface for handling messages sent by Bot.

## [HitlBotConfig](entities/class:parrot.integrations.msteams.hitl_adapter.HitlBotConfig.md)

Minimal bot configuration shim for the HITL adapter.

## [HitlCloudAdapter](entities/class:parrot.integrations.msteams.hitl_adapter.Hitl-2e363b89.md)

CloudAdapter configured for the shared HITL bot identity.

## [TeamsCardRenderer](entities/class:parrot.integrations.msteams.hitl_cards.TeamsC-9367ecb7.md)

Pure renderer: :class:`~parrot.human.models.HumanInteraction` → Adaptive Card dict.

## [MSTeamsAgentConfig](entities/class:parrot.integrations.msteams.models.MSTeamsAgentConfig.md)

Configuration for a single agent exposed via MS Teams.

## [MSTeamsOAuthNotifier](entities/class:parrot.integrations.msteams.oauth_callback.MS-ac73a29f.md)

Send a proactive message to a Teams user after a successful Jira OAuth callback.

## [ConversationReferenceStore](entities/class:parrot.integrations.msteams.proactive.Convers-d873c9f8.md)

Redis-backed store for Bot Framework ``ConversationReference`` objects.

## [ProactiveDeliveryError](entities/class:parrot.integrations.msteams.proactive.Proacti-17ea70fe.md)

Raised when a proactive send fails fatally (cold-create + org-install).

## [ProactiveMessenger](entities/class:parrot.integrations.msteams.proactive.Proacti-38459ff4.md)

Orchestrates proactive 1:1 messaging via the Bot Framework.

## [SentActivityStore](entities/class:parrot.integrations.msteams.proactive.SentAct-b1521c6c.md)

Redis-backed map of sent HITL activities.

## [AudioAttachment](entities/class:parrot.integrations.msteams.voice.models.Audi-2164c2a3.md)

Parsed audio attachment from MS Teams.

## [DebugMemoryStorage](entities/class:parrot.integrations.msteams.wrapper.DebugMemoryStorage.md)

Class DebugMemoryStorage in parrot.integrations.msteams.wrapper

## [MSTeamsAgentWrapper](entities/class:parrot.integrations.msteams.wrapper.MSTeamsAg-56ea26f0.md)

Wraps an Agent for MS Teams integration.

## [ChartData](entities/class:parrot.integrations.parser.ChartData.md)

Metadata for a generated chart.

## [ParsedResponse](entities/class:parrot.integrations.parser.ParsedResponse.md)

Structured response content extracted from AIMessage.

## [SlackAssistantHandler](entities/class:parrot.integrations.slack.assistant.SlackAssi-7b45c41b.md)

Handles Slack's Agents & AI Apps events.

## [SlackCommandRouter](entities/class:parrot.integrations.slack.commands.SlackCommandRouter.md)

Routes slash commands to registered async handler functions.

## [EventDeduplicator](entities/class:parrot.integrations.slack.dedup.EventDeduplicator.md)

In-memory event deduplication with TTL.

## [EventDeduplicatorProtocol](entities/class:parrot.integrations.slack.dedup.EventDeduplic-7f230edd.md)

Protocol for event deduplication backends.

## [RedisEventDeduplicator](entities/class:parrot.integrations.slack.dedup.RedisEventDeduplicator.md)

Redis-backed deduplication for multi-instance deployments.

## [ActionRegistry](entities/class:parrot.integrations.slack.interactive.ActionRegistry.md)

Registry for Block Kit action handlers.

## [SlackInteractiveHandler](entities/class:parrot.integrations.slack.interactive.SlackIn-101618f4.md)

Handles all interactive payloads from Slack Block Kit.

## [SlackAgentConfig](entities/class:parrot.integrations.slack.models.SlackAgentConfig.md)

Configuration for a single agent exposed via Slack.

## [SlackOAuthNotifier](entities/class:parrot.integrations.slack.oauth_callback.Slac-7b8e66ef.md)

Push a DM confirmation to a Slack user after a successful Jira OAuth callback.

## [SlackSocketHandler](entities/class:parrot.integrations.slack.socket_handler.Slac-8b7c885d.md)

Handle Slack events via Socket Mode (WebSocket connection).

## [SlackAgentWrapper](entities/class:parrot.integrations.slack.wrapper.SlackAgentWrapper.md)

Wrap an AI-Parrot agent for Slack Events and slash commands.

## [AbstractAuthStrategy](entities/class:parrot.integrations.telegram.auth.AbstractAuthStrategy.md)

Base class for Telegram authentication strategies.

## [AzureAuthStrategy](entities/class:parrot.integrations.telegram.auth.AzureAuthStrategy.md)

Navigator Azure AD SSO strategy.

## [BasicAuthStrategy](entities/class:parrot.integrations.telegram.auth.BasicAuthStrategy.md)

Navigator Basic Auth strategy.

## [CompositeAuthStrategy](entities/class:parrot.integrations.telegram.auth.CompositeAu-8914b1c9.md)

Multi-method auth router.

## [NavigatorAuthClient](entities/class:parrot.integrations.telegram.auth.NavigatorAuthClient.md)

Authenticate Telegram users against Navigator API.

## [OAuth2AuthStrategy](entities/class:parrot.integrations.telegram.auth.OAuth2AuthStrategy.md)

OAuth2 Authorization Code strategy with PKCE.

## [TelegramUserSession](entities/class:parrot.integrations.telegram.auth.TelegramUserSession.md)

Cached identity for a Telegram user within a chat session.

## [CallbackContext](entities/class:parrot.integrations.telegram.callbacks.CallbackContext.md)

Context object passed to @telegram_callback handlers.

## [CallbackData](entities/class:parrot.integrations.telegram.callbacks.CallbackData.md)

Encode/decode callback_data for Telegram InlineKeyboardButtons.

## [CallbackMetadata](entities/class:parrot.integrations.telegram.callbacks.Callba-b4e43e05.md)

Metadata stored on a method decorated with @telegram_callback.

## [CallbackRegistry](entities/class:parrot.integrations.telegram.callbacks.Callba-2d0a86c9.md)

Discovers and stores @telegram_callback handlers from an agent.

## [CallbackResult](entities/class:parrot.integrations.telegram.callbacks.CallbackResult.md)

Result returned by a @telegram_callback handler.

## [AgentCard](entities/class:parrot.integrations.telegram.crew.agent_card.AgentCard.md)

Identity and capability descriptor for an agent in the crew.

## [AgentSkill](entities/class:parrot.integrations.telegram.crew.agent_card.-271697cd.md)

Describes a single capability of an agent.

## [CrewAgentEntry](entities/class:parrot.integrations.telegram.crew.config.Crew-a7b03414.md)

Configuration for a single agent in the crew.

## [TelegramCrewConfig](entities/class:parrot.integrations.telegram.crew.config.Tele-66e5a135.md)

Root configuration for a multi-agent crew in a Telegram supergroup.

## [CoordinatorBot](entities/class:parrot.integrations.telegram.crew.coordinator-c1ac7a64.md)

Non-agent bot that manages the pinned registry message.

## [CrewAgentWrapper](entities/class:parrot.integrations.telegram.crew.crew_wrappe-0227e959.md)

Per-agent wrapper that handles @mention messages in a crew supergroup.

## [DataPayload](entities/class:parrot.integrations.telegram.crew.payload.DataPayload.md)

Manages file exchange between agents in a Telegram crew.

## [CrewRegistry](entities/class:parrot.integrations.telegram.crew.registry.Cr-6eb4b328.md)

Thread-safe in-memory registry tracking active agents in the crew.

## [TelegramCrewTransport](entities/class:parrot.integrations.telegram.crew.transport.T-593efb4c.md)

Orchestrator for a multi-agent crew in a Telegram supergroup.

## [BotMentionedFilter](entities/class:parrot.integrations.telegram.filters.BotMenti-e14810d2.md)

Filter that matches messages where the bot is @mentioned.

## [CommandInGroupFilter](entities/class:parrot.integrations.telegram.filters.CommandI-aa6386ef.md)

Filter that matches commands directed at this bot in groups.

## [TelegramHumanTool](entities/class:parrot.integrations.telegram.human_tool.Teleg-6dd6e146.md)

A :class:`HumanTool` that auto-resolves manager + target from Telegram context.

## [TelegramOAuthNotifier](entities/class:parrot.integrations.telegram.jira_commands.Te-8c5ad6e1.md)

Push a confirmation message to the originating Telegram chat after

## [TelegramBotManager](entities/class:parrot.integrations.telegram.manager.Telegram-1a78d996.md)

Manages Telegram bot lifecycle for exposed agents.

## [TelegramMCPPersistenceService](entities/class:parrot.integrations.telegram.mcp_persistence.-c07615d2.md)

CRUD for the ``telegram_user_mcp_configs`` DocumentDB collection.

## [TelegramMCPPublicParams](entities/class:parrot.integrations.telegram.mcp_persistence.-a2ee1ce2.md)

Non-secret subset of an /add_mcp payload safe to persist in DocumentDB.

## [UserTelegramMCPConfig](entities/class:parrot.integrations.telegram.mcp_persistence.-2b3e046c.md)

Persisted non-secret config for a /add_mcp HTTP server.

## [PostAuthAction](entities/class:parrot.integrations.telegram.models.PostAuthAction.md)

Configuration for a secondary authentication action to chain after

## [TelegramAgentConfig](entities/class:parrot.integrations.telegram.models.TelegramA-6da8eb0e.md)

Configuration for a single agent exposed via Telegram.

## [TelegramBotsConfig](entities/class:parrot.integrations.telegram.models.TelegramBotsConfig.md)

Root configuration for all Telegram bots.

## [OperatorCommandsMixin](entities/class:parrot.integrations.telegram.operator_command-422ce64d.md)

Operator-only Telegram commands for the autonomous harness.

## [JiraPostAuthProvider](entities/class:parrot.integrations.telegram.post_auth_jira.J-b9c96115.md)

Secondary auth provider for Atlassian Jira (OAuth2 3LO).

## [TelegramAgentWrapper](entities/class:parrot.integrations.telegram.wrapper.Telegram-da833651.md)

Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.

## [WhatsAppBridgeConfig](entities/class:parrot.integrations.whatsapp.bridge_config.Wh-327310bc.md)

Configuration for WhatsApp Bridge wrapper (whatsmeow-based).

## [WhatsAppBridgeWrapper](entities/class:parrot.integrations.whatsapp.bridge_wrapper.W-a5c98b39.md)

Wraps an AI-Parrot Agent for WhatsApp Bridge integration.

## [WhatsAppUserSession](entities/class:parrot.integrations.whatsapp.handler.WhatsApp-0de5d0fd.md)

Per-user session tracking for WhatsApp conversations.

## [WhatsAppAgentConfig](entities/class:parrot.integrations.whatsapp.models.WhatsAppA-30d86aff.md)

Configuration for a single agent exposed via WhatsApp Business API.

## [WhatsAppAgentWrapper](entities/class:parrot.integrations.whatsapp.wrapper.WhatsApp-8a6d69d8.md)

Wraps an AI-Parrot Agent for WhatsApp integration.

## [AWSInterface](entities/class:parrot.interfaces.aws.AWSInterface.md)

Base interface for AWS services using aioboto3.

## [CredentialsInterface](entities/class:parrot.interfaces.credentials.CredentialsInterface.md)

Abstract Base Class for handling credentials and environment variables.

## [DBInterface](entities/class:parrot.interfaces.database.DBInterface.md)

Interface for relational database operations using AsyncDB.

## [PandasDataframe](entities/class:parrot.interfaces.dataframes.PandasDataframe.md)

Mock interface for Pandas Dataframe compatibility.

## [DocumentConverterInterface](entities/class:parrot.interfaces.doc_converter.DocumentConve-5ef3542b.md)

Wraps Docling's DocumentConverter with async support and configurable options.

## [DocumentDb](entities/class:parrot.interfaces.documentdb.DocumentDb.md)

Interface for managing DocumentDB connections using asyncdb "documentdb" driver.

## [FailedWrite](entities/class:parrot.interfaces.documentdb.FailedWrite.md)

Represents a failed write operation for later retry or inspection.

## [FlowtaskInterface](entities/class:parrot.interfaces.flowtask.FlowtaskInterface.md)

Interface for managing Flowtask DAG tasks.

## [JobInfo](entities/class:parrot.interfaces.flowtask.JobInfo.md)

Lightweight info about a queued/running job.

## [TaskCodeFormat](entities/class:parrot.interfaces.flowtask.TaskCodeFormat.md)

Supported formats for ad-hoc task definitions.

## [TaskCodeRequest](entities/class:parrot.interfaces.flowtask.TaskCodeRequest.md)

Request model for submitting an ad-hoc task from a JSON/YAML string.

## [TaskExecutionRequest](entities/class:parrot.interfaces.flowtask.TaskExecutionRequest.md)

Request model for executing a Flowtask task.

## [TaskResult](entities/class:parrot.interfaces.flowtask.TaskResult.md)

Response model for a completed task execution.

## [TaskStatus](entities/class:parrot.interfaces.flowtask.TaskStatus.md)

Possible statuses of a Flowtask task/job.

## [WorkerTaskRequest](entities/class:parrot.interfaces.flowtask.WorkerTaskRequest.md)

Request model for dispatching a task to a Flowtask worker.

## [CredentialsInterface](entities/class:parrot.interfaces.google.CredentialsInterface.md)

Mixin for processing credentials with environment variable replacement.

## [GoogleClient](entities/class:parrot.interfaces.google.GoogleClient.md)

Google Services Client for AI-Parrot.

## [Employee](entities/class:parrot.interfaces.hierarchy.Employee.md)

Employee Information

## [EmployeeHierarchyManager](entities/class:parrot.interfaces.hierarchy.EmployeeHierarchyManager.md)

Hierarchy Manager using ArangoDB to store employees and their reporting structure.

## [ComponentError](entities/class:parrot.interfaces.http.ComponentError.md)

Base class for component errors.

## [HTTPService](entities/class:parrot.interfaces.http.HTTPService.md)

HTTPService.

## [ImagePlugin](entities/class:parrot.interfaces.images.plugins.abstract.ImagePlugin.md)

ImagePlugin is a base class for image processing plugins.

## [AnalysisPlugin](entities/class:parrot.interfaces.images.plugins.analisys.Ana-d5418ad6.md)

Plugin for analyzing images.

## [ClassificationPlugin](entities/class:parrot.interfaces.images.plugins.classify.Cla-8829bcc3.md)

ClassificationPlugin is a plugin for performing image classification.

## [ImageCategory](entities/class:parrot.interfaces.images.plugins.classify.Ima-a755b66b.md)

Enumeration for retail image categories.

## [ImageClassification](entities/class:parrot.interfaces.images.plugins.classify.Ima-9e3eb4e9.md)

Schema for classifying a retail image.

## [ClassifyBase](entities/class:parrot.interfaces.images.plugins.classifybase-c00727d7.md)

ClassifyBase is an Abstract base class for performing image classification.

## [DetectionPlugin](entities/class:parrot.interfaces.images.plugins.detect.Detec-6e5cee3c.md)

DetectionPlugin is a plugin for performing image detection.

## [EXIFPlugin](entities/class:parrot.interfaces.images.plugins.exif.EXIFPlugin.md)

EXIFPlugin is a plugin for extracting EXIF data from images.

## [ImageHashPlugin](entities/class:parrot.interfaces.images.plugins.hash.ImageHashPlugin.md)

ImageHashPlugin is a plugin for generating perceptual hashes of images.

## [VisionTransformerPlugin](entities/class:parrot.interfaces.images.plugins.vision.Visio-07e93d61.md)

VisionTransformerPlugin is a plugin for generating vector representations of images.

## [YOLOPlugin](entities/class:parrot.interfaces.images.plugins.yolo.YOLOPlugin.md)

YOLOPlugin is a plugin for performing object detection using the YOLO (You Only Look Once) model.

## [ZeroShotDetectionPlugin](entities/class:parrot.interfaces.images.plugins.zerodetect.Z-202b570d.md)

ZeroShotDetectionPlugin is a plugin for performing zero-shot object detection using the Grounding DINO model.

## [MSALCacheTokenCredential](entities/class:parrot.interfaces.o365.MSALCacheTokenCredential.md)

TokenCredential that uses an MSAL client application with a serialized cache.

## [MSALTokenCredential](entities/class:parrot.interfaces.o365.MSALTokenCredential.md)

Custom TokenCredential that uses MSAL tokens for azure-identity compatibility.

## [O365Client](entities/class:parrot.interfaces.o365.O365Client.md)

O365Client - Migrated to Microsoft Graph SDK

## [JsonRpcRequest](entities/class:parrot.interfaces.odoointerface.JsonRpcRequest.md)

JSON-RPC 2.0 request payload.

## [JsonRpcResponse](entities/class:parrot.interfaces.odoointerface.JsonRpcResponse.md)

JSON-RPC 2.0 response payload.

## [OdooAuthenticationError](entities/class:parrot.interfaces.odoointerface.OdooAuthentic-cbbb7fce.md)

Raised when authentication fails (invalid credentials or False uid).

## [OdooConfig](entities/class:parrot.interfaces.odoointerface.OdooConfig.md)

Configuration for Odoo JSON-RPC connection.

## [OdooConnectionError](entities/class:parrot.interfaces.odoointerface.OdooConnectionError.md)

Raised on network or connection failures.

## [OdooError](entities/class:parrot.interfaces.odoointerface.OdooError.md)

Base exception for Odoo JSON-RPC errors.

## [OdooInterface](entities/class:parrot.interfaces.odoointerface.OdooInterface.md)

Async interface for Odoo ERP via JSON-RPC 2.0.

## [OdooRPCError](entities/class:parrot.interfaces.odoointerface.OdooRPCError.md)

Raised when Odoo returns a JSON-RPC error response.

## [OneDriveClient](entities/class:parrot.interfaces.onedrive.OneDriveClient.md)

OneDrive Client - Migrated to Microsoft Graph SDK

## [RSSInterface](entities/class:parrot.interfaces.rss.RSSInterface.md)

RSSInterface.

## [RSSContentInterface](entities/class:parrot.interfaces.rss_content.RSSContentInterface.md)

Extends RSSInterface to fetch and summarize content from linked pages.

## [SharepointClient](entities/class:parrot.interfaces.sharepoint.SharepointClient.md)

SharePoint Client - Migrated to Microsoft Graph SDK

## [NoProxyAsyncTransport](entities/class:parrot.interfaces.soap.NoProxyAsyncTransport.md)

Zeep AsyncTransport subclass that:

## [SOAPClient](entities/class:parrot.interfaces.soap.SOAPClient.md)

SOAPClient

## [ToolInterface](entities/class:parrot.interfaces.tools.ToolInterface.md)

Interface for tool management in bot implementations.

## [VectorInterface](entities/class:parrot.interfaces.vector.VectorInterface.md)

Interface for vector store management and search operations.

## [TicketCreatePayload](entities/class:parrot.interfaces.zammad.TicketCreatePayload.md)

Payload for creating a Zammad ticket.

## [TicketUpdatePayload](entities/class:parrot.interfaces.zammad.TicketUpdatePayload.md)

Payload for updating a Zammad ticket.

## [UserCreatePayload](entities/class:parrot.interfaces.zammad.UserCreatePayload.md)

Payload for creating a Zammad user.

## [ZammadAuthError](entities/class:parrot.interfaces.zammad.ZammadAuthError.md)

Raised when authentication fails (401 response).

## [ZammadConfig](entities/class:parrot.interfaces.zammad.ZammadConfig.md)

Configuration for Zammad API connection.

## [ZammadConnectionError](entities/class:parrot.interfaces.zammad.ZammadConnectionError.md)

Raised on network or connection failures.

## [ZammadError](entities/class:parrot.interfaces.zammad.ZammadError.md)

Base exception for Zammad REST API errors.

## [ZammadInterface](entities/class:parrot.interfaces.zammad.ZammadInterface.md)

Async interface for Zammad REST API v1.

## [AnalyticsResult](entities/class:parrot.knowledge.graphindex.analytics.AnalyticsResult.md)

Results from graph analytics computation.

## [DismissedInsights](entities/class:parrot.knowledge.graphindex.analytics.Dismiss-aaea7988.md)

Tracks dismissed insight IDs. Session-scoped (not persisted to DB).

## [KnowledgeGaps](entities/class:parrot.knowledge.graphindex.analytics.KnowledgeGaps.md)

Aggregated knowledge gap report.

## [SurpriseFactors](entities/class:parrot.knowledge.graphindex.analytics.SurpriseFactors.md)

Decomposed explanation of why a connection is surprising.

## [GraphAssembler](entities/class:parrot.knowledge.graphindex.assemble.GraphAssembler.md)

Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.

## [CommunitiesResult](entities/class:parrot.knowledge.graphindex.communities.Commu-ea80048f.md)

Full Louvain partition + per-community metadata.

## [Community](entities/class:parrot.knowledge.graphindex.communities.Community.md)

A single community in the partition.

## [GraphIndexEmbedder](entities/class:parrot.knowledge.graphindex.embed.GraphIndexEmbedder.md)

Batch-embed UniversalNode summaries and manage vector indices.

## [GraphExportCategory](entities/class:parrot.knowledge.graphindex.export_html.Graph-2238bc01.md)

A community category (an ECharts legend entry + colour).

## [GraphExportEdge](entities/class:parrot.knowledge.graphindex.export_html.Graph-3574cd87.md)

A single directed edge in the export payload / ECharts ``links``.

## [GraphExportNode](entities/class:parrot.knowledge.graphindex.export_html.Graph-c0b11ba9.md)

A single node in the export payload / ECharts ``graph`` series.

## [GraphExportPayload](entities/class:parrot.knowledge.graphindex.export_html.Graph-46d348d9.md)

The complete, serializable graph export.

## [CodeExtractor](entities/class:parrot.knowledge.graphindex.extractors.code.C-fd4683d7.md)

Extract code structure from Python source files using tree-sitter.

## [LoaderExtractor](entities/class:parrot.knowledge.graphindex.extractors.loader-f898be0f.md)

Extract document structure from ai-parrot-loaders output.

## [OdooCodeExtractor](entities/class:parrot.knowledge.graphindex.extractors.odoo_c-7dcbf755.md)

Extract Odoo model structure on top of the generic code extractor.

## [SkillExtractor](entities/class:parrot.knowledge.graphindex.extractors.skill.-a949845f.md)

Extract Skill nodes from SKILL.md files.

## [GraphIndexLoader](entities/class:parrot.knowledge.graphindex.loader.GraphIndexLoader.md)

Build a GraphIndex graph from a list of files.

## [GraphIndexPersistence](entities/class:parrot.knowledge.graphindex.persist.GraphInde-b3b2fcc4.md)

Persists GraphIndex nodes, edges, and embeddings to ArangoDB + pgvector.

## [SQLitePersistence](entities/class:parrot.knowledge.graphindex.persist_sqlite.SQ-372c4da7.md)

Per-tenant SQLite persistence backend for GraphIndex.

## [ResolutionConfig](entities/class:parrot.knowledge.graphindex.resolve.ResolutionConfig.md)

Configuration for cross-domain resolution.

## [BudgetConfig](entities/class:parrot.knowledge.graphindex.retriever.BudgetConfig.md)

Token budget for Phase 4 result assembly.

## [ExpansionConfig](entities/class:parrot.knowledge.graphindex.retriever.ExpansionConfig.md)

Configuration for the graph expansion phase (Phase 2).

## [GraphExpandedRetriever](entities/class:parrot.knowledge.graphindex.retriever.GraphEx-ded60aba.md)

4-phase graph-expanded retrieval pipeline.

## [GraphRetrievalResult](entities/class:parrot.knowledge.graphindex.retriever.GraphRe-b779a72c.md)

Complete result of a graph-expanded retrieval query.

## [ScoredNode](entities/class:parrot.knowledge.graphindex.retriever.ScoredNode.md)

A retrieval candidate with decomposed scores.

## [BuildResult](entities/class:parrot.knowledge.graphindex.schema.BuildResult.md)

Outcome of a full ``GraphIndexBuilder.build()`` run.

## [EdgeKind](entities/class:parrot.knowledge.graphindex.schema.EdgeKind.md)

Semantic category of a directed graph edge.

## [GraphProjectionReport](entities/class:parrot.knowledge.graphindex.schema.GraphProje-0183eb45.md)

Summary of a completed GraphIndex OKF projection run (FEAT-239).

## [IngestResult](entities/class:parrot.knowledge.graphindex.schema.IngestResult.md)

Outcome of an incremental ``GraphIndexBuilder.ingest_document()`` run.

## [NodeKind](entities/class:parrot.knowledge.graphindex.schema.NodeKind.md)

Semantic category of a graph node.

## [Provenance](entities/class:parrot.knowledge.graphindex.schema.Provenance.md)

How a node or edge was created.

## [SourceConfig](entities/class:parrot.knowledge.graphindex.schema.SourceConfig.md)

Configuration describing what to index in a pipeline run.

## [UniversalEdge](entities/class:parrot.knowledge.graphindex.schema.UniversalEdge.md)

A directed edge in the GraphIndex knowledge graph.

## [UniversalNode](entities/class:parrot.knowledge.graphindex.schema.UniversalNode.md)

A node in the GraphIndex knowledge graph.

## [SignalRelevance](entities/class:parrot.knowledge.graphindex.signals.SignalRelevance.md)

Decomposed pairwise relevance result.

## [SignalRelevanceConfig](entities/class:parrot.knowledge.graphindex.signals.SignalRel-b17d4304.md)

Configuration for the five-signal relevance scorer.

## [SQLiteGraphReader](entities/class:parrot.knowledge.graphindex.sqlite_reader.SQL-8efd0e23.md)

Read-only navigator over a per-tenant SQLite GraphIndex artefact.

## [ConceptFrontmatter](entities/class:parrot.knowledge.okf.frontmatter.ConceptFrontmatter.md)

Pydantic v2 model for the deterministic frontmatter projection.

## [ConceptType](entities/class:parrot.knowledge.okf.ontology.ConceptType.md)

Controlled ontological vocabulary for OKF node types.

## [RelatesTo](entities/class:parrot.knowledge.okf.ontology.RelatesTo.md)

A typed edge in the knowledge graph.

## [RelationType](entities/class:parrot.knowledge.okf.ontology.RelationType.md)

Typed edge vocabulary (OKF-superset).

## [SourceProvenance](entities/class:parrot.knowledge.okf.ontology.SourceProvenance.md)

Per-node provenance, citable.

## [AuthorizationChecker](entities/class:parrot.knowledge.ontology.authorization.Autho-26aaae50.md)

Evaluates declarative authorization rules against resolved entities.

## [OntologyCache](entities/class:parrot.knowledge.ontology.cache.OntologyCache.md)

Redis cache for ontology pipeline results.

## [CascadeAlert](entities/class:parrot.knowledge.ontology.concept_catalog.mod-0f62a256.md)

Notification emitted to the operational service when a Concept is deprecated.

## [ConceptRow](entities/class:parrot.knowledge.ontology.concept_catalog.mod-d2504d29.md)

Represents a row in the ontology_concept Postgres table.

## [IsaEdgeRow](entities/class:parrot.knowledge.ontology.concept_catalog.mod-f128c9e9.md)

Represents a row in the ontology_concept_isa Postgres table.

## [ConceptCatalogReconciler](entities/class:parrot.knowledge.ontology.concept_catalog.rec-ad2c47bc.md)

Detect drift between Postgres and ArangoDB for a tenant's concept catalog.

## [ReconciliationReport](entities/class:parrot.knowledge.ontology.concept_catalog.rec-a9d5ca0c.md)

Summary of one reconciliation run for a tenant.

## [ConceptCatalogService](entities/class:parrot.knowledge.ontology.concept_catalog.ser-4adc3fd8.md)

Operational truth for per-tenant Concept entities and is_a edges.

## [ConceptCatalogSyncWorker](entities/class:parrot.knowledge.ontology.concept_catalog.wor-0fee16c9.md)

Drain ``ontology_concept_outbox``, sync to ArangoDB, publish invalidation.

## [ConceptEmbeddingPipeline](entities/class:parrot.knowledge.ontology.concept_embedding.C-56d83746.md)

Idempotent, hash-based embedding sync for ontology Concept instances.

## [ConceptSyncResult](entities/class:parrot.knowledge.ontology.concept_embedding.C-7360a1d1.md)

Summary of a single ``ConceptEmbeddingPipeline.sync()`` run.

## [DiscoveryResult](entities/class:parrot.knowledge.ontology.discovery.DiscoveryResult.md)

Result of a relation discovery operation.

## [DiscoveryStats](entities/class:parrot.knowledge.ontology.discovery.DiscoveryStats.md)

Statistics for a discovery run.

## [RelationDiscovery](entities/class:parrot.knowledge.ontology.discovery.RelationDiscovery.md)

Discover and create relationships between entities in the graph.

## [EntityAmbiguityError](entities/class:parrot.knowledge.ontology.entity_resolver.Ent-d0d9a279.md)

Raised when multiple candidates match and the strategy is ``ask_user``

## [EntityNotFoundError](entities/class:parrot.knowledge.ontology.entity_resolver.Ent-98baf31c.md)

Raised when no candidates match a required entity extraction rule.

## [EntityResolver](entities/class:parrot.knowledge.ontology.entity_resolver.Ent-c71c6677.md)

Extracts named-entity mentions from a query and resolves them to graph

## [AQLValidationError](entities/class:parrot.knowledge.ontology.exceptions.AQLValid-1e9adda6.md)

Raised when LLM-generated AQL fails safety validation.

## [CycleError](entities/class:parrot.knowledge.ontology.exceptions.CycleError.md)

Raised when an is_a edge would create a cycle in the concept DAG.

## [DataSourceValidationError](entities/class:parrot.knowledge.ontology.exceptions.DataSour-78ec5d40.md)

Raised by ExtractDataSource.validate() when the source schema doesn't match.

## [DryRunFailedError](entities/class:parrot.knowledge.ontology.exceptions.DryRunFailedError.md)

Raised when a schema overlay dry-run fails validation.

## [FrameworkOverrideError](entities/class:parrot.knowledge.ontology.exceptions.Framewor-a0ec1af6.md)

Raised when an overlay attempts to mutate a framework entity, relation, or pattern.

## [InvalidTransitionError](entities/class:parrot.knowledge.ontology.exceptions.InvalidT-da0b7228.md)

Raised when a state-machine transition is not permitted.

## [OntologyError](entities/class:parrot.knowledge.ontology.exceptions.OntologyError.md)

Base exception for all ontology-related errors.

## [OntologyIntegrityError](entities/class:parrot.knowledge.ontology.exceptions.Ontology-d1c0dc9f.md)

Raised during post-merge integrity validation.

## [OntologyMergeError](entities/class:parrot.knowledge.ontology.exceptions.Ontology-12502566.md)

Raised during YAML merge when rules are violated.

## [SynonymConflictError](entities/class:parrot.knowledge.ontology.exceptions.SynonymC-c7d8363d.md)

Raised when a synonym conflicts with an existing approved concept synonym.

## [UnknownDataSourceError](entities/class:parrot.knowledge.ontology.exceptions.UnknownD-da5f2e05.md)

Raised by DataSourceFactory when a source name cannot be resolved.

## [OntologyGraphStore](entities/class:parrot.knowledge.ontology.graph_store.Ontolog-508f1038.md)

ArangoDB wrapper for ontology graph operations.

## [UpsertResult](entities/class:parrot.knowledge.ontology.graph_store.UpsertResult.md)

Result of a batch upsert operation.

## [IntentDecision](entities/class:parrot.knowledge.ontology.intent.IntentDecision.md)

Structured output from LLM intent classification.

## [OntologyIntentResolver](entities/class:parrot.knowledge.ontology.intent.OntologyInte-91ae2e99.md)

Resolve user queries into graph traversal intents.

## [OntologyMerger](entities/class:parrot.knowledge.ontology.merger.OntologyMerger.md)

Merge multiple ontology YAML layers into a single MergedOntology.

## [OntologyRAGMixin](entities/class:parrot.knowledge.ontology.mixin.OntologyRAGMixin.md)

Mixin that adds Ontological Graph RAG capabilities to any agent.

## [OntologyParser](entities/class:parrot.knowledge.ontology.parser.OntologyParser.md)

Load and validate ontology YAML files against Pydantic schema models.

## [DiffResult](entities/class:parrot.knowledge.ontology.refresh.DiffResult.md)

Result of computing delta between new and existing data.

## [OntologyRefreshPipeline](entities/class:parrot.knowledge.ontology.refresh.OntologyRef-033fab3f.md)

CRON-triggered pipeline that keeps the ontology graph in sync.

## [RefreshReport](entities/class:parrot.knowledge.ontology.refresh.RefreshReport.md)

Report from a full refresh pipeline run.

## [AuthorizationRule](entities/class:parrot.knowledge.ontology.schema.AuthorizationRule.md)

Single declarative authorization rule for an intent pattern.

## [AuthorizationSpec](entities/class:parrot.knowledge.ontology.schema.AuthorizationSpec.md)

Declarative authorization specification for a traversal pattern.

## [ContextEnvelope](entities/class:parrot.knowledge.ontology.schema.ContextEnvelope.md)

Wraps EnrichedContext with state-specific fields for non-happy paths.

## [DiscoveryConfig](entities/class:parrot.knowledge.ontology.schema.DiscoveryConfig.md)

Configuration for how relations are discovered in source data.

## [DiscoveryRule](entities/class:parrot.knowledge.ontology.schema.DiscoveryRule.md)

Rule for discovering relationships between entities in source data.

## [EnrichedContext](entities/class:parrot.knowledge.ontology.schema.EnrichedContext.md)

Enriched context returned by the ontology pipeline.

## [EntityDef](entities/class:parrot.knowledge.ontology.schema.EntityDef.md)

Definition of a vertex collection (entity) in the ontology.

## [EntityExtractionRule](entities/class:parrot.knowledge.ontology.schema.EntityExtractionRule.md)

Rule describing how to extract and resolve a named entity from a query.

## [MergedOntology](entities/class:parrot.knowledge.ontology.schema.MergedOntology.md)

Fully resolved ontology after merging all YAML layers.

## [OntologyDefinition](entities/class:parrot.knowledge.ontology.schema.OntologyDefinition.md)

Root model for a single ontology YAML layer.

## [PropertyDef](entities/class:parrot.knowledge.ontology.schema.PropertyDef.md)

Single property definition for an entity.

## [RelationDef](entities/class:parrot.knowledge.ontology.schema.RelationDef.md)

Definition of an edge collection (relation) in the ontology.

## [ResolvedIntent](entities/class:parrot.knowledge.ontology.schema.ResolvedIntent.md)

Result of intent resolution.

## [TenantContext](entities/class:parrot.knowledge.ontology.schema.TenantContext.md)

Runtime context for a specific tenant.

## [ToolCallSpec](entities/class:parrot.knowledge.ontology.schema.ToolCallSpec.md)

Specification for a tool invocation after graph traversal.

## [TraversalPattern](entities/class:parrot.knowledge.ontology.schema.TraversalPattern.md)

Predefined graph traversal pattern for a known query type.

## [DryRunCheck](entities/class:parrot.knowledge.ontology.schema_overlay.mode-c41a9c2b.md)

Result of a single validation step within a dry-run.

## [DryRunReport](entities/class:parrot.knowledge.ontology.schema_overlay.mode-19a393aa.md)

Result of a schema overlay dry-run validation.

## [SchemaOverlayRow](entities/class:parrot.knowledge.ontology.schema_overlay.mode-b32a985e.md)

Represents a row in the ontology_schema_overlay Postgres table.

## [SchemaOverlayService](entities/class:parrot.knowledge.ontology.schema_overlay.serv-2ce942e1.md)

Operational truth for per-tenant schema overlays.

## [SchemaOverlaySyncWorker](entities/class:parrot.knowledge.ontology.schema_overlay.work-ced49c50.md)

Drain ``ontology_schema_outbox`` and publish cache invalidation.

## [TenantOntologyManager](entities/class:parrot.knowledge.ontology.tenant.TenantOntologyManager.md)

Resolve and cache merged ontology per tenant.

## [RenderError](entities/class:parrot.knowledge.ontology.tool_dispatcher.RenderError.md)

Raised when Jinja2 template rendering fails (e.g., ``StrictUndefined``).

## [ToolCallDispatcher](entities/class:parrot.knowledge.ontology.tool_dispatcher.Too-6fbdded8.md)

Renders and invokes a tool call specified by a ``ToolCallSpec``.

## [NodeContentStore](entities/class:parrot.knowledge.pageindex.content_store.Node-cbc0ae76.md)

On-disk per-node markdown content store with a bounded LRU cache.

## [NodeEmbeddingStore](entities/class:parrot.knowledge.pageindex.embedding_store.No-cc84849c.md)

Two-tier content-addressed embedding cache for PageIndex trees.

## [HybridPageIndexSearch](entities/class:parrot.knowledge.pageindex.hybrid_search.Hybr-ed972757.md)

BM25 + LLM-walk + dense-cosine hybrid retrieval wrapping a single tree.

## [IngestedMarkdown](entities/class:parrot.knowledge.pageindex.ingest.IngestedMarkdown.md)

Structured output of the Step-2 markdown generator.

## [TwoStepIngester](entities/class:parrot.knowledge.pageindex.ingest.TwoStepIngester.md)

Drive the two-step ingest pipeline against an LLM adapter.

## [PageIndexLLMAdapter](entities/class:parrot.knowledge.pageindex.llm_adapter.PageIn-190e61f5.md)

Wraps any AbstractClient for PageIndex-compatible LLM calls.

## [PageIndexLoader](entities/class:parrot.knowledge.pageindex.loader.PageIndexLoader.md)

Build a PageIndex tree from a list of files.

## [ExportReport](entities/class:parrot.knowledge.pageindex.okf.bundle.ExportReport.md)

Result of an OKF bundle export operation.

## [ImportReport](entities/class:parrot.knowledge.pageindex.okf.bundle.ImportReport.md)

Result of an OKF bundle import operation.

## [KnowledgeGraph](entities/class:parrot.knowledge.pageindex.okf.graph.KnowledgeGraph.md)

In-memory adjacency graph keyed by concept_id.

## [LintFinding](entities/class:parrot.knowledge.pageindex.okf.lint.LintFinding.md)

A single lint finding.

## [LintReport](entities/class:parrot.knowledge.pageindex.okf.lint.LintReport.md)

Structured knowledge base lint report.

## [MigrationReport](entities/class:parrot.knowledge.pageindex.okf.migrate.MigrationReport.md)

Report produced by ``okf_migrate()``.

## [ProjectionReport](entities/class:parrot.knowledge.pageindex.okf.projection.Pro-eb7557ad.md)

Report returned by project_sidecars().

## [OKFToolkit](entities/class:parrot.knowledge.pageindex.okf.tools.OKFToolkit.md)

Stateful container for OKF read tools.

## [PageIndexRetriever](entities/class:parrot.knowledge.pageindex.retriever.PageInde-99f3eb93.md)

Tree-search retriever using an LLM to navigate a PageIndex tree.

## [DocDescription](entities/class:parrot.knowledge.pageindex.schemas.DocDescription.md)

A one-sentence document description.

## [GeneratedTocItem](entities/class:parrot.knowledge.pageindex.schemas.GeneratedTocItem.md)

A TOC entry generated by LLM from document content (no-TOC mode).

## [PageIndexDetection](entities/class:parrot.knowledge.pageindex.schemas.PageIndexDetection.md)

Result of detecting page numbers within a table of contents.

## [PageIndexNode](entities/class:parrot.knowledge.pageindex.schemas.PageIndexNode.md)

A node in the PageIndex tree structure.

## [PageIndexTree](entities/class:parrot.knowledge.pageindex.schemas.PageIndexTree.md)

Top-level PageIndex document representation.

## [PhysicalIndexFix](entities/class:parrot.knowledge.pageindex.schemas.PhysicalIndexFix.md)

Result of finding the correct physical index for a section.

## [TitleAppearanceCheck](entities/class:parrot.knowledge.pageindex.schemas.TitleAppea-2de62513.md)

Result of checking if a section title appears on a specific page.

## [TitleStartCheck](entities/class:parrot.knowledge.pageindex.schemas.TitleStartCheck.md)

Result of checking if a section starts at the beginning of a page.

## [TocCompletionCheck](entities/class:parrot.knowledge.pageindex.schemas.TocCompletionCheck.md)

Result of checking whether a TOC extraction is complete.

## [TocDetectionResult](entities/class:parrot.knowledge.pageindex.schemas.TocDetectionResult.md)

Result of checking whether a page contains a table of contents.

## [TocItem](entities/class:parrot.knowledge.pageindex.schemas.TocItem.md)

A single entry in a parsed table of contents.

## [TocJson](entities/class:parrot.knowledge.pageindex.schemas.TocJson.md)

Full table of contents in structured JSON form.

## [TreeSearchResult](entities/class:parrot.knowledge.pageindex.schemas.TreeSearchResult.md)

Result of an LLM tree search over a PageIndex tree.

## [JSONTreeStore](entities/class:parrot.knowledge.pageindex.store.JSONTreeStore.md)

File-system backed registry of PageIndex trees.

## [PageIndexToolkit](entities/class:parrot.knowledge.pageindex.toolkit.PageIndexToolkit.md)

Toolkit exposing search / retrieve / insert tools over PageIndex trees.

## [ConfigLoader](entities/class:parrot.knowledge.pageindex.utils.ConfigLoader.md)

Load PageIndex configuration from YAML with user overrides.

## [FlatMatrixSearch](entities/class:parrot.knowledge.pageindex.vector_walk.FlatMa-37383dbe.md)

Brute-force cosine similarity search over a node embedding submatrix.

## [WikiBookkeeper](entities/class:parrot.knowledge.wiki.bookkeeper.WikiBookkeeper.md)

Manages index.md and log.md bookkeeping files for a wiki.

## [PackedContext](entities/class:parrot.knowledge.wiki.context.PackedContext.md)

A budgeted, LLM-ready packing of wiki search results.

## [WikiExportReport](entities/class:parrot.knowledge.wiki.export.WikiExportReport.md)

Result of an OKF bundle export.

## [InMemoryWikiStore](entities/class:parrot.knowledge.wiki.file_store.InMemoryWikiStore.md)

RAM-indexed wiki store persisted as an OKF markdown directory.

## [IngestReport](entities/class:parrot.knowledge.wiki.ingest.IngestReport.md)

Result of a single wiki ingest run.

## [WikiIngestOrchestrator](entities/class:parrot.knowledge.wiki.ingest.WikiIngestOrchestrator.md)

Orchestrates the full source-to-wiki-page ingest pipeline.

## [SourceManifestEntry](entities/class:parrot.knowledge.wiki.models.SourceManifestEntry.md)

Tracks an ingested source document in the wiki's source manifest.

## [WikiConfig](entities/class:parrot.knowledge.wiki.models.WikiConfig.md)

Configuration for a single wiki instance.

## [WikiLintReport](entities/class:parrot.knowledge.wiki.models.WikiLintReport.md)

Extended lint report combining OKF checks with wiki-specific checks.

## [WikiPageCategory](entities/class:parrot.knowledge.wiki.models.WikiPageCategory.md)

Karpathy's wiki page type taxonomy.

## [WikiSearchResult](entities/class:parrot.knowledge.wiki.models.WikiSearchResult.md)

Unified wiki search result.

## [WikiCombinedSearch](entities/class:parrot.knowledge.wiki.search.WikiCombinedSearch.md)

Unified search across PageIndex and GraphIndex.

## [SourceCollectionManager](entities/class:parrot.knowledge.wiki.sources.SourceCollectionManager.md)

Manages the raw-source collection for a single wiki instance.

## [BaseWikiStore](entities/class:parrot.knowledge.wiki.store.BaseWikiStore.md)

Contract for wiki retrieval-plane backends.

## [SQLiteWikiStore](entities/class:parrot.knowledge.wiki.store.SQLiteWikiStore.md)

Async single-file SQLite retrieval plane for one wiki.

## [WikiPageRecord](entities/class:parrot.knowledge.wiki.store.WikiPageRecord.md)

A single wiki page row in the retrieval plane.

## [LLMWikiToolkit](entities/class:parrot.knowledge.wiki.toolkit.LLMWikiToolkit.md)

Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.

## [AbstractLoader](entities/class:parrot.loaders.abstract.AbstractLoader.md)

Base class for all loaders.

## [BaseTextSplitter](entities/class:parrot.loaders.splitters.base.BaseTextSplitter.md)

Base class for all text splitters

## [TextChunk](entities/class:parrot.loaders.splitters.base.TextChunk.md)

Represents a chunk of text with metadata

## [MarkdownTextSplitter](entities/class:parrot.loaders.splitters.md.MarkdownTextSplitter.md)

Markdown-aware splitter backed by the Rust crate. Never cuts inside

## [SemanticTextSplitter](entities/class:parrot.loaders.splitters.semantic.SemanticTextSplitter.md)

Sentence/paragraph-aware splitter backed by the Rust crate. Never

## [TokenTextSplitter](entities/class:parrot.loaders.splitters.token.TokenTextSplitter.md)

Text splitter that splits based on token count using various tokenizers.

## [EphemeralAgentStatus](entities/class:parrot.manager.ephemeral.EphemeralAgentStatus.md)

Live warm-up state for an ephemeral user bot.

## [EphemeralRegistry](entities/class:parrot.manager.ephemeral.EphemeralRegistry.md)

In-memory registry of active ephemeral bots.

## [BotManager](entities/class:parrot.manager.manager.BotManager.md)

BotManager.

## [MCPToolAdapter](entities/class:parrot.mcp.adapter.MCPToolAdapter.md)

Adapts AI-Parrot AbstractTool to MCP tool format.

## [ChromeManager](entities/class:parrot.mcp.chrome.ChromeManager.md)

Manages a headless Chrome instance for MCP tools.

## [AuthCredential](entities/class:parrot.mcp.client.AuthCredential.md)

Type-safe credential container with validation.

## [AuthScheme](entities/class:parrot.mcp.client.AuthScheme.md)

Type-safe authentication schemes.

## [MCPAuthHandler](entities/class:parrot.mcp.client.MCPAuthHandler.md)

Handles various authentication types for MCP servers.

## [MCPClientConfig](entities/class:parrot.mcp.client.MCPClientConfig.md)

Complete configuration for external MCP server connection.

## [MCPConnectionError](entities/class:parrot.mcp.client.MCPConnectionError.md)

MCP connection related errors.

## [MCPRateLimitError](entities/class:parrot.mcp.client.MCPRateLimitError.md)

Raised when an MCP server rejects a request with a rate-limit error.

## [AuthMethod](entities/class:parrot.mcp.config.AuthMethod.md)

Authentication method for MCP server.

## [MCPServerConfig](entities/class:parrot.mcp.config.MCPServerConfig.md)

Configuration for MCP server.

## [TransportConfig](entities/class:parrot.mcp.config.TransportConfig.md)

Configuration for a single MCP transport (used by ParrotMCPServer).

## [MCPSessionManager](entities/class:parrot.mcp.context.MCPSessionManager.md)

Manages session lifecycle and retry logic for MCP connections.

## [ReadonlyContext](entities/class:parrot.mcp.context.ReadonlyContext.md)

Immutable context passed to tool operations.

## [TransientMCPError](entities/class:parrot.mcp.context.TransientMCPError.md)

Transient MCP errors that should be retried.

## [ToolPredicate](entities/class:parrot.mcp.filtering.ToolPredicate.md)

Protocol for tool filtering logic.

## [MCPClient](entities/class:parrot.mcp.integration.MCPClient.md)

Complete MCP client with stdio and HTTP transport support.

## [MCPEnabledMixin](entities/class:parrot.mcp.integration.MCPEnabledMixin.md)

Mixin to add complete MCP capabilities to agents.

## [MCPToolProxy](entities/class:parrot.mcp.integration.MCPToolProxy.md)

Proxy tool that wraps an individual MCP tool.

## [MCPValidationError](entities/class:parrot.mcp.integration.MCPValidationError.md)

Raised when an MCP HTTP server fails the handshake validation check.

## [InMemoryTokenStore](entities/class:parrot.mcp.oauth.InMemoryTokenStore.md)

Simple in-memory token store (not persistent).

## [NetSuiteM2MAuth](entities/class:parrot.mcp.oauth.NetSuiteM2MAuth.md)

OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT assertion.

## [RedisTokenStore](entities/class:parrot.mcp.oauth.RedisTokenStore.md)

Redis-based token store.

## [TokenStore](entities/class:parrot.mcp.oauth.TokenStore.md)

Abstract token store interface.

## [VaultTokenStore](entities/class:parrot.mcp.oauth.VaultTokenStore.md)

Vault-backed token store that encrypts OAuth tokens using AES-GCM.

## [MCPOAuth2Config](entities/class:parrot.mcp.oauth2_config.MCPOAuth2Config.md)

OAuth2 configuration for a single MCP server connection.

## [MCPOAuth2GrantType](entities/class:parrot.mcp.oauth2_config.MCPOAuth2GrantType.md)

OAuth2 grant types supported for MCP server authentication.

## [MCPOAuth2Preset](entities/class:parrot.mcp.oauth2_config.MCPOAuth2Preset.md)

Pre-built OAuth2 configuration template for a known MCP provider.

## [VaultMCPTokenStorage](entities/class:parrot.mcp.oauth2_storage.VaultMCPTokenStorage.md)

MCP SDK ``TokenStorage`` adapter backed by AI-Parrot's Vault.

## [APIKeyRecord](entities/class:parrot.mcp.oauth_server.APIKeyRecord.md)

Record for an issued API key.

## [APIKeyStore](entities/class:parrot.mcp.oauth_server.APIKeyStore.md)

In-memory API key store with session logging.

## [ClientRegistry](entities/class:parrot.mcp.oauth_server.ClientRegistry.md)

Minimal in-memory Dynamic Client Registration (RFC 7591) registry.

## [ExternalOAuthValidator](entities/class:parrot.mcp.oauth_server.ExternalOAuthValidator.md)

Validates tokens against external OAuth2 servers using RFC 7662 introspection.

## [OAuthAuthorizationServer](entities/class:parrot.mcp.oauth_server.OAuthAuthorizationServer.md)

In-memory OAuth 2.0 authorization server for MCP transports.

## [OAuthClient](entities/class:parrot.mcp.oauth_server.OAuthClient.md)

Class OAuthClient in parrot.mcp.oauth_server

## [OAuthRoutesMixin](entities/class:parrot.mcp.oauth_server.OAuthRoutesMixin.md)

Shared OAuth/DCR utilities for HTTP and SSE transports.

## [ParrotMCPServer](entities/class:parrot.mcp.parrot_server.ParrotMCPServer.md)

Manage lifecycle of multiple MCP servers (multi-transport) attached to an aiohttp app.

## [ActivateMCPServerRequest](entities/class:parrot.mcp.registry.ActivateMCPServerRequest.md)

Request body for the POST (activate) endpoint.

## [MCPParamType](entities/class:parrot.mcp.registry.MCPParamType.md)

Type hint for an MCP server parameter.

## [MCPServerDescriptor](entities/class:parrot.mcp.registry.MCPServerDescriptor.md)

Catalog entry describing a single pre-built MCP server helper.

## [MCPServerParam](entities/class:parrot.mcp.registry.MCPServerParam.md)

Describes a single parameter accepted by an MCP server helper.

## [MCPServerRegistry](entities/class:parrot.mcp.registry.MCPServerRegistry.md)

Catalog of pre-built MCP server helpers available for user activation.

## [UserMCPServerConfig](entities/class:parrot.mcp.registry.UserMCPServerConfig.md)

Persisted configuration for a user-activated MCP server.

## [MCPResource](entities/class:parrot.mcp.resources.MCPResource.md)

Represents an MCP Resource.

## [MCPServer](entities/class:parrot.mcp.server.MCPServer.md)

Main MCP server class that chooses transport.

## [SimpleMCPServer](entities/class:parrot.mcp.simple_server.SimpleMCPServer.md)

A simplified MCP Server implementation for exposing a single tool or function.

## [MCPServerBase](entities/class:parrot.mcp.transports.base.MCPServerBase.md)

Base class for MCP servers.

## [GrpcMCPConfig](entities/class:parrot.mcp.transports.grpc_session.GrpcMCPConfig.md)

Configuration for gRPC MCP transport.

## [GrpcMCPSession](entities/class:parrot.mcp.transports.grpc_session.GrpcMCPSession.md)

MCP session for gRPC transport with optional protobuf messages.

## [HttpMCPServer](entities/class:parrot.mcp.transports.http.HttpMCPServer.md)

MCP server using HTTP transport.

## [HttpMCPSession](entities/class:parrot.mcp.transports.http.HttpMCPSession.md)

MCP session for HTTP/SSE transport using aiohttp.

## [MCPConnectionError](entities/class:parrot.mcp.transports.quic.MCPConnectionError.md)

MCP connection error.

## [MCPSerializer](entities/class:parrot.mcp.transports.quic.MCPSerializer.md)

Handles serialization/deserialization of MCP messages.

## [QuicMCPClientProtocol](entities/class:parrot.mcp.transports.quic.QuicMCPClientProtocol.md)

QUIC protocol handler for MCP client connections.

## [QuicMCPConfig](entities/class:parrot.mcp.transports.quic.QuicMCPConfig.md)

Unified QUIC configuration.

## [QuicMCPServer](entities/class:parrot.mcp.transports.quic.QuicMCPServer.md)

QUIC/HTTP3 MCP Server with WebTransport support.

## [QuicMCPServerProtocol](entities/class:parrot.mcp.transports.quic.QuicMCPServerProtocol.md)

QUIC protocol handler for MCP server connections.

## [QuicMCPSession](entities/class:parrot.mcp.transports.quic.QuicMCPSession.md)

MCP session over QUIC/HTTP3 with WebTransport.

## [SerializationFormat](entities/class:parrot.mcp.transports.quic.SerializationFormat.md)

Supported serialization formats for MCP messages.

## [SseMCPServer](entities/class:parrot.mcp.transports.sse.SseMCPServer.md)

MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients.

## [SseMCPSession](entities/class:parrot.mcp.transports.sse.SseMCPSession.md)

MCP session using SSE (Server-Sent Events) for transport.

## [StdioMCPServer](entities/class:parrot.mcp.transports.stdio.StdioMCPServer.md)

MCP server using stdio transport.

## [StdioMCPSession](entities/class:parrot.mcp.transports.stdio.StdioMCPSession.md)

MCP session for stdio transport.

## [UnixMCPServer](entities/class:parrot.mcp.transports.unix.UnixMCPServer.md)

MCP server using Unix socket transport.

## [UnixMCPSession](entities/class:parrot.mcp.transports.unix.UnixMCPSession.md)

MCP session for Unix socket transport.

## [WebSocketConnection](entities/class:parrot.mcp.transports.websocket.WebSocketConnection.md)

Represents an active WebSocket connection with session info.

## [WebSocketMCPServer](entities/class:parrot.mcp.transports.websocket.WebSocketMCPServer.md)

MCP server using WebSocket transport for bidirectional communication.

## [WebSocketMCPSession](entities/class:parrot.mcp.transports.websocket.WebSocketMCPSession.md)

MCP client session for WebSocket transport.

## [ConversationHistory](entities/class:parrot.memory.abstract.ConversationHistory.md)

Manages conversation history for a session - replaces ConversationSession.

## [ConversationMemory](entities/class:parrot.memory.abstract.ConversationMemory.md)

Abstract base class for conversation memory storage.

## [ConversationTurn](entities/class:parrot.memory.abstract.ConversationTurn.md)

Represents a single turn in a conversation.

## [AnswerMemory](entities/class:parrot.memory.agent.AnswerMemory.md)

Store and retrieve question/answer interactions by turn identifier.

## [CacheMixin](entities/class:parrot.memory.cache.CacheMixin.md)

Mixin to add caching capabilities using Redis.

## [AbstractEpisodeBackend](entities/class:parrot.memory.episodic.backends.abstract.Abst-162c0eb8.md)

Protocol defining the storage backend interface for episodes.

## [FAISSBackend](entities/class:parrot.memory.episodic.backends.faiss.FAISSBackend.md)

FAISS-based backend for local development without PostgreSQL.

## [PgVectorBackend](entities/class:parrot.memory.episodic.backends.pgvector.PgVe-8e1f2012.md)

PostgreSQL + pgvector backend for episodic memory.

## [RedisVectorBackend](entities/class:parrot.memory.episodic.backends.redis_vector.-4a41a5dc.md)

Redis Stack (RediSearch) backend for episodic memory vector search.

## [EpisodeRedisCache](entities/class:parrot.memory.episodic.cache.EpisodeRedisCache.md)

Redis-based hot cache for episodic memory.

## [EpisodeEmbeddingProvider](entities/class:parrot.memory.episodic.embedding.EpisodeEmbed-e2388c83.md)

Lazy-loading sentence-transformers embedding provider.

## [EpisodicMemoryMixin](entities/class:parrot.memory.episodic.mixin.EpisodicMemoryMixin.md)

Mixin that adds automatic episodic memory to bots.

## [EpisodeCategory](entities/class:parrot.memory.episodic.models.EpisodeCategory.md)

Category classification for an episode.

## [EpisodeOutcome](entities/class:parrot.memory.episodic.models.EpisodeOutcome.md)

Outcome classification for an episode.

## [EpisodeSearchResult](entities/class:parrot.memory.episodic.models.EpisodeSearchResult.md)

An episodic memory with a similarity score from search.

## [EpisodicMemory](entities/class:parrot.memory.episodic.models.EpisodicMemory.md)

A single episodic memory record.

## [MemoryNamespace](entities/class:parrot.memory.episodic.models.MemoryNamespace.md)

Hierarchical namespace for isolating episodes.

## [ReflectionResult](entities/class:parrot.memory.episodic.models.ReflectionResult.md)

Result of LLM or heuristic reflection on an episode.

## [HybridBM25Strategy](entities/class:parrot.memory.episodic.recall.HybridBM25Strategy.md)

Recall strategy that fuses BM25 lexical scores with semantic similarity.

## [RecallStrategy](entities/class:parrot.memory.episodic.recall.RecallStrategy.md)

Protocol for pluggable recall strategies.

## [SemanticOnlyStrategy](entities/class:parrot.memory.episodic.recall.SemanticOnlyStrategy.md)

Recall strategy that delegates directly to backend.search_similar().

## [ReflectionEngine](entities/class:parrot.memory.episodic.reflection.ReflectionEngine.md)

LLM-powered reflection engine with heuristic fallback.

## [HeuristicScorer](entities/class:parrot.memory.episodic.scoring.HeuristicScorer.md)

Heuristic importance scorer based on outcome and error type.

## [ImportanceScorer](entities/class:parrot.memory.episodic.scoring.ImportanceScorer.md)

Protocol for pluggable importance scoring strategies.

## [ValueScorer](entities/class:parrot.memory.episodic.scoring.ValueScorer.md)

Heuristic interaction value scorer ported from AgentCoreMemory.

## [EpisodicMemoryStore](entities/class:parrot.memory.episodic.store.EpisodicMemoryStore.md)

Main orchestrator for episodic memory operations.

## [EpisodicMemoryToolkit](entities/class:parrot.memory.episodic.tools.EpisodicMemoryToolkit.md)

Toolkit exposing episodic memory as agent-callable tools.

## [FileConversationMemory](entities/class:parrot.memory.file.FileConversationMemory.md)

File-based implementation of conversation memory.

## [InMemoryConversation](entities/class:parrot.memory.mem.InMemoryConversation.md)

In-memory implementation of conversation memory.

## [RedisConversation](entities/class:parrot.memory.redis.RedisConversation.md)

Redis-based conversation memory with proper encoding handling.

## [ContextAssembler](entities/class:parrot.memory.unified.context.ContextAssembler.md)

Assembles context from multiple sources within a token budget.

## [SkillRegistry](entities/class:parrot.memory.unified.manager.SkillRegistry.md)

Structural protocol for skill registries.

## [UnifiedMemoryManager](entities/class:parrot.memory.unified.manager.UnifiedMemoryManager.md)

Coordinates episodic memory, skill registry, and conversation memory.

## [LongTermMemoryMixin](entities/class:parrot.memory.unified.mixin.LongTermMemoryMixin.md)

Single opt-in mixin for long-term memory in any bot/agent.

## [MemoryConfig](entities/class:parrot.memory.unified.models.MemoryConfig.md)

Configuration for UnifiedMemoryManager.

## [MemoryContext](entities/class:parrot.memory.unified.models.MemoryContext.md)

Assembled context from all memory subsystems.

## [AgentExpertise](entities/class:parrot.memory.unified.routing.AgentExpertise.md)

Registry entry for an agent's domain expertise.

## [CrossDomainRouter](entities/class:parrot.memory.unified.routing.CrossDomainRouter.md)

Routes memory queries to relevant agent namespaces for multi-agent sharing.

## [CompletionUsage](entities/class:parrot.models.basic.CompletionUsage.md)

Unified completion usage tracking across different LLM providers.

## [ModelConfig](entities/class:parrot.models.basic.ModelConfig.md)

Model configuration for session-scoped LLM setup.

## [OutputFormat](entities/class:parrot.models.basic.OutputFormat.md)

Supported output formats for structured responses.

## [ToolCall](entities/class:parrot.models.basic.ToolCall.md)

Unified tool call representation.

## [ToolConfig](entities/class:parrot.models.basic.ToolConfig.md)

Tool configuration for session-scoped ToolManager setup.

## [ClaudeModel](entities/class:parrot.models.claude.ClaudeModel.md)

Enum for Claude models.

## [BrandComplianceResult](entities/class:parrot.models.compliance.BrandComplianceResult.md)

Result of brand logo compliance checking

## [ComplianceResult](entities/class:parrot.models.compliance.ComplianceResult.md)

Final compliance check result

## [ComplianceStatus](entities/class:parrot.models.compliance.ComplianceStatus.md)

Possible compliance statuses for shelf checks

## [TextComplianceResult](entities/class:parrot.models.compliance.TextComplianceResult.md)

Result of text compliance checking

## [TextMatcher](entities/class:parrot.models.compliance.TextMatcher.md)

N-gram + fuzzy text matcher for planogram text compliance.

## [ConferenceResult](entities/class:parrot.models.conference.ConferenceResult.md)

Aggregated outcome of a multi-party conference.

## [ConferenceRound](entities/class:parrot.models.conference.ConferenceRound.md)

State of one cross-pollination + vote round.

## [PeerVote](entities/class:parrot.models.conference.PeerVote.md)

Structured vote of an agent after seeing the anonymous peer answers.

## [AgentExecutionInfo](entities/class:parrot.models.crew.AgentExecutionInfo.md)

Information about an agent's execution in a crew workflow.

## [AgentResult](entities/class:parrot.models.crew.AgentResult.md)

Captures a single agent execution with full context

## [CrewResult](entities/class:parrot.models.crew.CrewResult.md)

Standardized result from crew execution.

## [VectorStoreProtocol](entities/class:parrot.models.crew.VectorStoreProtocol.md)

Protocol for vector store implementations

## [AgentDefinition](entities/class:parrot.models.crew_definition.AgentDefinition.md)

Definition of an agent in a crew.

## [CrewDefinition](entities/class:parrot.models.crew_definition.CrewDefinition.md)

Complete definition of an AgentCrew.

## [ExecutionMode](entities/class:parrot.models.crew_definition.ExecutionMode.md)

Execution modes for AgentCrew.

## [FlowRelation](entities/class:parrot.models.crew_definition.FlowRelation.md)

Defines a dependency relationship between agents in flow mode.

## [ToolNodeDefinition](entities/class:parrot.models.crew_definition.ToolNodeDefinition.md)

Definition of a deterministic tool-execution node in a crew.

## [DatasetAction](entities/class:parrot.models.datasets.DatasetAction.md)

Actions that can be performed on a dataset.

## [DatasetDeleteResponse](entities/class:parrot.models.datasets.DatasetDeleteResponse.md)

Response model for DELETE /datasets/{agent_id}.

## [DatasetErrorResponse](entities/class:parrot.models.datasets.DatasetErrorResponse.md)

Error response model for dataset operations.

## [DatasetListResponse](entities/class:parrot.models.datasets.DatasetListResponse.md)

Response model for GET /datasets/{agent_id}.

## [DatasetPatchRequest](entities/class:parrot.models.datasets.DatasetPatchRequest.md)

Request model for PATCH /datasets/{agent_id}.

## [DatasetQueryRequest](entities/class:parrot.models.datasets.DatasetQueryRequest.md)

Request model for POST /datasets/{agent_id} (add query).

## [DatasetUploadResponse](entities/class:parrot.models.datasets.DatasetUploadResponse.md)

Response model for PUT /datasets/{agent_id}.

## [AdvertisementEndcap](entities/class:parrot.models.detections.AdvertisementEndcap.md)

Configuration for advertisement endcap

## [AisleConfig](entities/class:parrot.models.detections.AisleConfig.md)

Configuration for aisle-specific settings

## [BoundingBox](entities/class:parrot.models.detections.BoundingBox.md)

Normalized bounding box coordinates

## [BrandDetectionConfig](entities/class:parrot.models.detections.BrandDetectionConfig.md)

Configuration for brand detection parameters

## [CategoryDetectionConfig](entities/class:parrot.models.detections.CategoryDetectionConfig.md)

Configuration for product category detection

## [Detection](entities/class:parrot.models.detections.Detection.md)

Generic detection result

## [DetectionBox](entities/class:parrot.models.detections.DetectionBox.md)

Bounding box from object detection

## [Detections](entities/class:parrot.models.detections.Detections.md)

Collection of detections in an image

## [IdentificationResponse](entities/class:parrot.models.detections.IdentificationResponse.md)

Response from product identification

## [IdentifiedProduct](entities/class:parrot.models.detections.IdentifiedProduct.md)

Product identified by LLM using reference images

## [PlanogramConfigBuilder](entities/class:parrot.models.detections.PlanogramConfigBuilder.md)

Builder class for easier construction of planogram configurations

## [PlanogramDescription](entities/class:parrot.models.detections.PlanogramDescription.md)

Comprehensive, configurable planogram description

## [PlanogramDescriptionFactory](entities/class:parrot.models.detections.PlanogramDescriptionFactory.md)

Factory class for creating PlanogramDescription objects from dictionaries

## [SectionRegion](entities/class:parrot.models.detections.SectionRegion.md)

Normalized x/y ratio boundaries defining a sub-region within a shelf.

## [ShelfConfig](entities/class:parrot.models.detections.ShelfConfig.md)

Configuration for a single shelf

## [ShelfProduct](entities/class:parrot.models.detections.ShelfProduct.md)

Configuration for products expected on a shelf

## [ShelfRegion](entities/class:parrot.models.detections.ShelfRegion.md)

Detected shelf region

## [ShelfSection](entities/class:parrot.models.detections.ShelfSection.md)

A named sub-section within a shelf, defining a region and expected products.

## [TextRequirement](entities/class:parrot.models.detections.TextRequirement.md)

Text requirement for promotional materials

## [VideoGenInput](entities/class:parrot.models.generation.VideoGenInput.md)

Structured input for VEO video generation with all supported parameters.

## [VideoGenerationPrompt](entities/class:parrot.models.generation.VideoGenerationPrompt.md)

Input schema for generating video content with VEO models (handler-facing).

## [VideoResolution](entities/class:parrot.models.generation.VideoResolution.md)

Supported video resolutions for VEO models.

## [AspectRatio](entities/class:parrot.models.google.AspectRatio.md)

Supported aspect ratios for Gemini Image Generation.

## [ConversationalScriptConfig](entities/class:parrot.models.google.ConversationalScriptConfig.md)

Configuration for generating a conversational script with fictional characters.

## [FictionalSpeaker](entities/class:parrot.models.google.FictionalSpeaker.md)

Configuration for a fictional character in the generated script.

## [GoogleModel](entities/class:parrot.models.google.GoogleModel.md)

Enum for Google AI models.

## [GoogleVoiceModel](entities/class:parrot.models.google.GoogleVoiceModel.md)

Available models for Gemini Live API.

## [ImageResolution](entities/class:parrot.models.google.ImageResolution.md)

Supported resolutions for Gemini Image Generation.

## [LyriaModel](entities/class:parrot.models.google.LyriaModel.md)

Available Lyria models for music generation.

## [MusicBatchRequest](entities/class:parrot.models.google.MusicBatchRequest.md)

Request payload for Lyria batch music generation (Vertex AI).

## [MusicBatchResponse](entities/class:parrot.models.google.MusicBatchResponse.md)

Response from Lyria batch API.

## [MusicGenerationRequest](entities/class:parrot.models.google.MusicGenerationRequest.md)

Request payload for Lyria music generation.

## [MusicGenre](entities/class:parrot.models.google.MusicGenre.md)

Music Genres supported by Lyria.

## [MusicMood](entities/class:parrot.models.google.MusicMood.md)

Music Moods/Descriptions supported by Lyria.

## [TTSVoice](entities/class:parrot.models.google.TTSVoice.md)

Google TTS voices.

## [VertexAIModel](entities/class:parrot.models.google.VertexAIModel.md)

Enum for Vertex AI models.

## [VideoReelRequest](entities/class:parrot.models.google.VideoReelRequest.md)

Request configuration for generating a complete video reel.

## [VideoReelScene](entities/class:parrot.models.google.VideoReelScene.md)

Configuration for a single scene in a video reel.

## [VoiceProfile](entities/class:parrot.models.google.VoiceProfile.md)

Represents a single pre-built generative voice, mapping its name

## [VoiceRegistry](entities/class:parrot.models.google.VoiceRegistry.md)

A comprehensive registry for managing and querying available voice profiles.

## [GroqModel](entities/class:parrot.models.groq.GroqModel.md)

Description for Enabled Groq models.

## [AccordionBlock](entities/class:parrot.models.infographic.AccordionBlock.md)

Collapsible accordion sections with optional nested block content.

## [AccordionItem](entities/class:parrot.models.infographic.AccordionItem.md)

A single collapsible item within an AccordionBlock.

## [BlockType](entities/class:parrot.models.infographic.BlockType.md)

Available infographic block types.

## [BulletListBlock](entities/class:parrot.models.infographic.BulletListBlock.md)

Ordered or unordered list of items.

## [BulletListStyle](entities/class:parrot.models.infographic.BulletListStyle.md)

Visual style variants for BulletListBlock.

## [CalloutBlock](entities/class:parrot.models.infographic.CalloutBlock.md)

Alert/info/warning box.

## [CalloutLevel](entities/class:parrot.models.infographic.CalloutLevel.md)

Severity/type for callout blocks.

## [ChartBlock](entities/class:parrot.models.infographic.ChartBlock.md)

Chart specification block. Frontend renders using its preferred library.

## [ChartDataSeries](entities/class:parrot.models.infographic.ChartDataSeries.md)

A single data series for chart rendering.

## [ChartType](entities/class:parrot.models.infographic.ChartType.md)

Supported chart types for ChartBlock.

## [ChecklistBlock](entities/class:parrot.models.infographic.ChecklistBlock.md)

Visual checkbox-style list with optional checked/unchecked state.

## [ChecklistItem](entities/class:parrot.models.infographic.ChecklistItem.md)

A single item in a ChecklistBlock.

## [ColumnDef](entities/class:parrot.models.infographic.ColumnDef.md)

Column definition for TableBlock with optional styling.

## [DividerBlock](entities/class:parrot.models.infographic.DividerBlock.md)

Visual separator between sections.

## [HeroCardBlock](entities/class:parrot.models.infographic.HeroCardBlock.md)

Key metric card with value, label, and optional trend indicator.

## [ImageBlock](entities/class:parrot.models.infographic.ImageBlock.md)

Image reference block.

## [InfographicResponse](entities/class:parrot.models.infographic.InfographicResponse.md)

Structured infographic output returned by get_infographic().

## [JSBundle](entities/class:parrot.models.infographic.JSBundle.md)

Declarative JavaScript bundle attached to an InfographicTemplate.

## [ProgressBlock](entities/class:parrot.models.infographic.ProgressBlock.md)

Progress/completion indicators.

## [ProgressItem](entities/class:parrot.models.infographic.ProgressItem.md)

A single progress indicator.

## [QuoteBlock](entities/class:parrot.models.infographic.QuoteBlock.md)

Highlighted quote or testimonial.

## [SummaryBlock](entities/class:parrot.models.infographic.SummaryBlock.md)

Rich text summary paragraph.

## [TabPane](entities/class:parrot.models.infographic.TabPane.md)

A single tab pane within a TabViewBlock.

## [TabViewBlock](entities/class:parrot.models.infographic.TabViewBlock.md)

Tabbed navigation block containing multiple content panes.

## [TableBlock](entities/class:parrot.models.infographic.TableBlock.md)

Tabular data block.

## [TableStyle](entities/class:parrot.models.infographic.TableStyle.md)

Visual style variants for TableBlock.

## [ThemeConfig](entities/class:parrot.models.infographic.ThemeConfig.md)

CSS variable configuration for infographic HTML themes.

## [ThemeRegistry](entities/class:parrot.models.infographic.ThemeRegistry.md)

Registry for infographic HTML themes.

## [TimelineBlock](entities/class:parrot.models.infographic.TimelineBlock.md)

Chronological sequence of events.

## [TimelineEvent](entities/class:parrot.models.infographic.TimelineEvent.md)

A single event in a timeline.

## [TitleBlock](entities/class:parrot.models.infographic.TitleBlock.md)

Main title/subtitle header block.

## [TrendDirection](entities/class:parrot.models.infographic.TrendDirection.md)

Trend direction for hero card metrics.

## [BlockSpec](entities/class:parrot.models.infographic_templates.BlockSpec.md)

Specification for a single block slot in a template.

## [InfographicTemplate](entities/class:parrot.models.infographic_templates.Infograph-c57eddc6.md)

Defines the structure and block order for an infographic layout.

## [InfographicTemplateRegistry](entities/class:parrot.models.infographic_templates.Infograph-d9a68ef9.md)

Registry of available infographic templates.

## [InteractiveRenderResult](entities/class:parrot.models.interactive.InteractiveRenderResult.md)

Envelope returned by ``InteractiveToolkit.render`` (return_direct=True).

## [LibraryEntry](entities/class:parrot.models.interactive.LibraryEntry.md)

A single vetted JavaScript library the LLM may use in an artifact.

## [ScaffoldTemplate](entities/class:parrot.models.interactive.ScaffoldTemplate.md)

A deterministic HTML skeleton with named slots for the enhance pass.

## [LocalLLMModel](entities/class:parrot.models.localllm.LocalLLMModel.md)

Common local LLM model identifiers.

## [NvidiaModel](entities/class:parrot.models.nvidia.NvidiaModel.md)

Nvidia NIM-hosted model identifiers.

## [DeprecationInfo](entities/class:parrot.models.openai.DeprecationInfo.md)

Structured deprecation metadata for a single OpenAI model ID.

## [OpenAIModel](entities/class:parrot.models.openai.OpenAIModel.md)

Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS).

## [OpenRouterModel](entities/class:parrot.models.openrouter.OpenRouterModel.md)

Common OpenRouter model identifiers.

## [OpenRouterUsage](entities/class:parrot.models.openrouter.OpenRouterUsage.md)

Cost and usage information from OpenRouter generation responses.

## [ProviderPreferences](entities/class:parrot.models.openrouter.ProviderPreferences.md)

OpenRouter provider routing preferences.

## [BoundingBox](entities/class:parrot.models.outputs.BoundingBox.md)

Represents a detected object with its location and details.

## [ImageGenerationPrompt](entities/class:parrot.models.outputs.ImageGenerationPrompt.md)

Input schema for generating an image.

## [MapColumn](entities/class:parrot.models.outputs.MapColumn.md)

Per-column contract for a map layer (same vocabulary as TableColumn).

## [MapLayer](entities/class:parrot.models.outputs.MapLayer.md)

One layer per dataset — data schema + presentation schema (FEAT-221).

## [MapQuery](entities/class:parrot.models.outputs.MapQuery.md)

Echoed spatial filter query — carries the originating search parameters (FEAT-221).

## [MapViewport](entities/class:parrot.models.outputs.MapViewport.md)

Map viewport hints — computed from feature bounds (FEAT-221).

## [ObjectDetectionResult](entities/class:parrot.models.outputs.ObjectDetectionResult.md)

A list of all prominent items detected in the image.

## [OutputMode](entities/class:parrot.models.outputs.OutputMode.md)

Output mode enumeration

## [OutputType](entities/class:parrot.models.outputs.OutputType.md)

Types of outputs that can be rendered

## [ProductReview](entities/class:parrot.models.outputs.ProductReview.md)

Structured product review response.

## [SentimentAnalysis](entities/class:parrot.models.outputs.SentimentAnalysis.md)

Structured sentiment analysis response.

## [SpeakerConfig](entities/class:parrot.models.outputs.SpeakerConfig.md)

Configuration for a single speaker in speech generation.

## [SpeechGenerationPrompt](entities/class:parrot.models.outputs.SpeechGenerationPrompt.md)

Input schema for generating speech from text.

## [StructuredChartConfig](entities/class:parrot.models.outputs.StructuredChartConfig.md)

Library-agnostic chart configuration mirroring the frontend AppChartConfig.

## [StructuredMapConfig](entities/class:parrot.models.outputs.StructuredMapConfig.md)

Framework-agnostic map configuration for FEAT-221.

## [StructuredOutputConfig](entities/class:parrot.models.outputs.StructuredOutputConfig.md)

Configuration for structured output parsing.

## [StructuredTableConfig](entities/class:parrot.models.outputs.StructuredTableConfig.md)

Framework-agnostic table configuration for FEAT-218.

## [TableColumn](entities/class:parrot.models.outputs.TableColumn.md)

Per-column contract for a structured table output.

## [VideoGenerationPrompt](entities/class:parrot.models.outputs.VideoGenerationPrompt.md)

Input schema for generating video content.

## [AIMessage](entities/class:parrot.models.responses.AIMessage.md)

Unified AI message response that can handle various output types.

## [AIMessageFactory](entities/class:parrot.models.responses.AIMessageFactory.md)

Factory to create AIMessage from different provider responses.

## [AgentResponse](entities/class:parrot.models.responses.AgentResponse.md)

AgentResponse is a model that defines the structure of the response for Any Parrot agent.

## [InvokeResult](entities/class:parrot.models.responses.InvokeResult.md)

Lightweight result from a stateless invoke() call.

## [MessageResponse](entities/class:parrot.models.responses.MessageResponse.md)

Response structure for LLM messages.

## [SourceDocument](entities/class:parrot.models.responses.SourceDocument.md)

Enhanced source document information similar to Parrot's format.

## [StreamChunk](entities/class:parrot.models.responses.StreamChunk.md)

Represents a chunk in a streaming response.

## [AgentStatus](entities/class:parrot.models.status.AgentStatus.md)

Status of an Agent.

## [SearchResult](entities/class:parrot.models.stores.SearchResult.md)

Data model for a single document returned from a vector search.

## [StoreConfig](entities/class:parrot.models.stores.StoreConfig.md)

Vector Store configuration dataclass.

## [StoreType](entities/class:parrot.models.stores.StoreType.md)

DB Store type — source of truth for store identifiers.

## [VLLMBatchRequest](entities/class:parrot.models.vllm.VLLMBatchRequest.md)

Batch request model for vLLM batch processing.

## [VLLMBatchResponse](entities/class:parrot.models.vllm.VLLMBatchResponse.md)

Batch response model for vLLM batch processing.

## [VLLMConfig](entities/class:parrot.models.vllm.VLLMConfig.md)

Configuration for vLLM client.

## [VLLMGuidedParams](entities/class:parrot.models.vllm.VLLMGuidedParams.md)

Guided decoding parameters for constrained generation.

## [VLLMLoRARequest](entities/class:parrot.models.vllm.VLLMLoRARequest.md)

LoRA adapter configuration for vLLM requests.

## [VLLMSamplingParams](entities/class:parrot.models.vllm.VLLMSamplingParams.md)

Extended sampling parameters for vLLM.

## [VLLMServerInfo](entities/class:parrot.models.vllm.VLLMServerInfo.md)

vLLM server information model.

## [AudioFormat](entities/class:parrot.models.voice.AudioFormat.md)

Audio formats for voice sessions.

## [VoiceConfig](entities/class:parrot.models.voice.VoiceConfig.md)

Configuration for Audio Sessions

## [ZaiModel](entities/class:parrot.models.zai.ZaiModel.md)

Z.ai GLM chat model identifiers.

## [FileType](entities/class:parrot.notifications.FileType.md)

File types for smart handling.

## [NotificationConfig](entities/class:parrot.notifications.NotificationConfig.md)

Configuration for sending notifications.

## [NotificationMixin](entities/class:parrot.notifications.NotificationMixin.md)

Mixin to provide notification capabilities to agents.

## [NotificationProvider](entities/class:parrot.notifications.NotificationProvider.md)

Supported notification providers.

## [ObservabilityConfig](entities/class:parrot.observability.config.ObservabilityConfig.md)

Single global configuration for the parrot.observability stack.

## [CostCalculator](entities/class:parrot.observability.cost.calculator.CostCalculator.md)

Stateless USD cost calculator using bundled or overridden pricing tables.

## [ConfigurationError](entities/class:parrot.observability.errors.ConfigurationError.md)

Raised when ``setup_telemetry`` receives an invalid or conflicting configuration.

## [ParrotTelemetryProvider](entities/class:parrot.observability.provider.ParrotTelemetryProvider.md)

Bundles trace + metrics subscribers for one-call registration.

## [AbstractLogger](entities/class:parrot.observability.recorders.base.AbstractLogger.md)

Abstract base for pluggable usage/token/cost recorders.

## [LoggingUsageRecorder](entities/class:parrot.observability.recorders.logging_record-c16de09e.md)

Record usage by emitting one structured log line per LLM call.

## [UsageRecord](entities/class:parrot.observability.recorders.models.UsageRecord.md)

Normalized usage/token/cost record for one LLM API call.

## [PrometheusUsageRecorder](entities/class:parrot.observability.recorders.prometheus_rec-19d05503.md)

Record usage as Prometheus counters/histograms exposed over HTTP.

## [UsageRecordingSubscriber](entities/class:parrot.observability.recorders.subscriber.Usa-47b2da35.md)

Build ``UsageRecord``s from LLM-call events and fan out to recorders.

## [MetricsSubscriber](entities/class:parrot.observability.subscribers.metrics.Metr-3b762b42.md)

OTel counter and histogram subscriber for LLM / tool / invoke events.

## [GenAIOpenTelemetrySubscriber](entities/class:parrot.observability.subscribers.trace.GenAIO-e5b45911.md)

Rich OTel span subscriber implementing GenAI Semantic Conventions.

## [DeepLink](entities/class:parrot.outputs.a2ui.artifacts.DeepLink.md)

A single-use, TTL-bound deep link that resumes the originating channel.

## [RenderedArtifact](entities/class:parrot.outputs.a2ui.artifacts.RenderedArtifact.md)

A baked, self-contained rendered output ready for delivery (spec §2, G5).

## [BakeError](entities/class:parrot.outputs.a2ui.baking.BakeError.md)

Raised when an envelope cannot be fully baked (e.g. unresolvable pointer).

## [BasicNode](entities/class:parrot.outputs.a2ui.catalog.base.BasicNode.md)

A node in a lowered A2UI *Basic Catalog* tree.

## [CatalogError](entities/class:parrot.outputs.a2ui.catalog.base.CatalogError.md)

Base class for catalog errors.

## [CatalogValidationError](entities/class:parrot.outputs.a2ui.catalog.base.CatalogValid-7b2bcfe3.md)

Raised when an envelope fails catalog allowlist / ``requires_actions`` checks.

## [ComponentContractError](entities/class:parrot.outputs.a2ui.catalog.base.ComponentCon-6c2cb74c.md)

Raised when a component class violates the registration contract.

## [ComponentDefinition](entities/class:parrot.outputs.a2ui.catalog.base.ComponentDefinition.md)

Metadata describing a registered catalog component (spec §2 Data Models).

## [ProducerOrigin](entities/class:parrot.outputs.a2ui.catalog.base.ProducerOrigin.md)

Origin of an envelope, controlling ``requires_actions`` enforcement.

## [RegisteredComponent](entities/class:parrot.outputs.a2ui.catalog.base.RegisteredComponent.md)

A catalog entry: the component's definition plus its implementing class.

## [CardComponent](entities/class:parrot.outputs.a2ui.catalog.components.card.C-43e0aac9.md)

The ``Card`` catalog component (display-only).

## [ChartComponent](entities/class:parrot.outputs.a2ui.catalog.components.chart.-6c31575a.md)

The ``Chart`` catalog component (display-only, ``requires_actions=False``).

## [DataTableComponent](entities/class:parrot.outputs.a2ui.catalog.components.datata-cea3cc95.md)

The ``DataTable`` catalog component (display-only, ``requires_actions=False``).

## [FormComponent](entities/class:parrot.outputs.a2ui.catalog.components.form.F-a5ca729e.md)

The ``Form`` catalog component (action-bearing; schema-only in v1).

## [InfographicComponent](entities/class:parrot.outputs.a2ui.catalog.components.infogr-3460c7a7.md)

The ``Infographic`` composite catalog component (display-only).

## [KPICardComponent](entities/class:parrot.outputs.a2ui.catalog.components.kpicar-89c24f5e.md)

The ``KPICard`` catalog component (display-only).

## [MapComponent](entities/class:parrot.outputs.a2ui.catalog.components.map.Ma-2d0aa48d.md)

The ``Map`` catalog component (display-only, ``requires_actions=False``).

## [ReportComponent](entities/class:parrot.outputs.a2ui.catalog.components.report-bf488579.md)

The ``Report`` composite catalog component (display-only).

## [TimelineComponent](entities/class:parrot.outputs.a2ui.catalog.components.timeli-9879f361.md)

The ``Timeline`` catalog component (display-only).

## [DeepLinkError](entities/class:parrot.outputs.a2ui.deeplink.DeepLinkError.md)

Base class for deep-link errors.

## [DeepLinkExpiredError](entities/class:parrot.outputs.a2ui.deeplink.DeepLinkExpiredError.md)

Raised when a token is missing, expired, or already consumed (single-use).

## [DeepLinkService](entities/class:parrot.outputs.a2ui.deeplink.DeepLinkService.md)

Mints and consumes single-use, TTL-bound deep-link tokens.

## [ResumePayload](entities/class:parrot.outputs.a2ui.deeplink.ResumePayload.md)

Server-side payload restored when a deep link is consumed.

## [A2UIMessageBase](entities/class:parrot.outputs.a2ui.models.A2UIMessageBase.md)

Base for every A2UI v1.0 wire message.

## [Action](entities/class:parrot.outputs.a2ui.models.Action.md)

``action`` — a user-originated action from a component (schema only in v1).

## [ActionResponse](entities/class:parrot.outputs.a2ui.models.ActionResponse.md)

``actionResponse`` — an agent's response to a prior ``action`` (schema only).

## [CallFunction](entities/class:parrot.outputs.a2ui.models.CallFunction.md)

``callFunction`` — an agent invokes a named client-side function (schema only).

## [Component](entities/class:parrot.outputs.a2ui.models.Component.md)

A single node in an A2UI component adjacency list.

## [CreateSurface](entities/class:parrot.outputs.a2ui.models.CreateSurface.md)

``createSurface`` — create a UI surface, optionally with inline content.

## [UpdateComponents](entities/class:parrot.outputs.a2ui.models.UpdateComponents.md)

``updateComponents`` — replace/extend a surface's component adjacency list.

## [UpdateDataModel](entities/class:parrot.outputs.a2ui.models.UpdateDataModel.md)

``updateDataModel`` — patch a surface's data model.

## [ProducerResult](entities/class:parrot.outputs.a2ui.producer.ProducerResult.md)

Outcome of :func:`generate_envelope`.

## [AbstractA2UIRenderer](entities/class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer.md)

Abstract base for every A2UI renderer (spec §2 New Public Interfaces).

## [RendererCapabilities](entities/class:parrot.outputs.a2ui.renderers.RendererCapabilities.md)

Declared capabilities of an A2UI renderer (spec §2 Data Models).

## [AdaptiveCardsRenderer](entities/class:parrot.outputs.a2ui_renderers.adaptive_cards.-a26b2c36.md)

Basic-tree → Adaptive Card JSON renderer (display subset, no actions).

## [EChartsRenderer](entities/class:parrot.outputs.a2ui_renderers.echarts.EChartsRenderer.md)

Chart-component → ECharts option JSON renderer (+ optional vendored HTML wrap).

## [FoliumMapRenderer](entities/class:parrot.outputs.a2ui_renderers.folium_map.Foli-8161550a.md)

Deterministic Map-component → folium HTML renderer.

## [PDFRenderer](entities/class:parrot.outputs.a2ui_renderers.pdf.PDFRenderer.md)

weasyprint-backed PDF renderer (SSR-HTML → static SVG charts → PDF).

## [SSRHTMLRenderer](entities/class:parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer.md)

Static, self-contained HTML renderer for A2UI envelopes.

## [Renderer](entities/class:parrot.outputs.formats.Renderer.md)

Protocol for output renderers.

## [AltairRenderer](entities/class:parrot.outputs.formats.altair.AltairRenderer.md)

Renderer for Altair/Vega-Lite charts

## [ApplicationRenderer](entities/class:parrot.outputs.formats.application.ApplicationRenderer.md)

Renderer that wraps the Agent Response into a standalone Application.

## [BaseRenderer](entities/class:parrot.outputs.formats.base.BaseRenderer.md)

Base class for output renderers.

## [RenderError](entities/class:parrot.outputs.formats.base.RenderError.md)

Structured error information from rendering.

## [RenderResult](entities/class:parrot.outputs.formats.base.RenderResult.md)

Structured result from rendering operation.

## [CardRenderer](entities/class:parrot.outputs.formats.card.CardRenderer.md)

Renderer for metric cards with comparison data.

## [BaseChart](entities/class:parrot.outputs.formats.chart.BaseChart.md)

Base class for chart renderers - extends BaseRenderer with chart-specific methods

## [EChartsRenderer](entities/class:parrot.outputs.formats.echarts.EChartsRenderer.md)

Renderer for Apache ECharts (JSON Configuration)

## [AbstractAppGenerator](entities/class:parrot.outputs.formats.generators.abstract.Ab-da243ea9.md)

Abstract base class for Application Generators.

## [PanelGenerator](entities/class:parrot.outputs.formats.generators.panel.PanelGenerator.md)

Generates a single-file Panel application.

## [StreamlitGenerator](entities/class:parrot.outputs.formats.generators.streamlit.S-b5267116.md)

Generates a single-file Streamlit application.

## [TerminalGenerator](entities/class:parrot.outputs.formats.generators.terminal.Te-7d35c74a.md)

Generates a Rich Console Dashboard.

## [HTMLRenderer](entities/class:parrot.outputs.formats.html.HTMLRenderer.md)

Renderer for HTML output using Panel or simple HTML fallback

## [InfographicRenderer](entities/class:parrot.outputs.formats.infographic.InfographicRenderer.md)

Renderer for structured infographic output.

## [InfographicHTMLRenderer](entities/class:parrot.outputs.formats.infographic_html.Infog-d451974b.md)

Renders InfographicResponse as a self-contained HTML5 document.

## [Jinja2Renderer](entities/class:parrot.outputs.formats.jinja2.Jinja2Renderer.md)

Renders the output using a Jinja2 template.

## [JSONRenderer](entities/class:parrot.outputs.formats.json.JSONRenderer.md)

Renderer for JSON output.

## [FoliumRenderer](entities/class:parrot.outputs.formats.map.FoliumRenderer.md)

Renderer for Folium maps with support for DataFrames and GeoJSON

## [MarkdownRenderer](entities/class:parrot.outputs.formats.markdown.MarkdownRenderer.md)

Renderer for Markdown output.

## [MatplotlibRenderer](entities/class:parrot.outputs.formats.matplotlib.MatplotlibRenderer.md)

Renderer for Matplotlib charts

## [CoordinateValidator](entities/class:parrot.outputs.formats.mixins.emaps.Coordinat-e4e5c522.md)

Validates and transforms geographic coordinates for ECharts

## [EChartsGeoBuilder](entities/class:parrot.outputs.formats.mixins.emaps.EChartsGeoBuilder.md)

Helper class to build ECharts geo configurations programmatically

## [EChartsMapsMixin](entities/class:parrot.outputs.formats.mixins.emaps.EChartsMapsMixin.md)

Mixin class to add geo/map capabilities to EChartsRenderer

## [PlotlyRenderer](entities/class:parrot.outputs.formats.plotly.PlotlyRenderer.md)

Renderer for Plotly charts

## [SeabornRenderer](entities/class:parrot.outputs.formats.seaborn.SeabornRenderer.md)

Renderer for Seaborn charts (rendered as static images).

## [SlackRenderer](entities/class:parrot.outputs.formats.slack.SlackRenderer.md)

Renderer for Slack output — returns plain text / markdown.

## [StructuredOutputBase](entities/class:parrot.outputs.formats.structured_base.Struct-01cf6e8c.md)

Mixin providing the shared contract for all structured-output renderers.

## [StructuredChartRenderer](entities/class:parrot.outputs.formats.structured_chart.Struc-055b974a.md)

Library-agnostic chart renderer for the STRUCTURED_CHART output mode.

## [StructuredMapRenderer](entities/class:parrot.outputs.formats.structured_map.Structu-ece0131d.md)

Library-agnostic map renderer for the STRUCTURED_MAP output mode (FEAT-221).

## [StructuredTableRenderer](entities/class:parrot.outputs.formats.structured_table.Struc-a2aee679.md)

Library-agnostic table renderer for the STRUCTURED_TABLE output mode.

## [TableRenderer](entities/class:parrot.outputs.formats.table.TableRenderer.md)

Renderer for Tables supporting Rich (Terminal), HTML (Simple), and Grid.js.

## [TemplateReportRenderer](entities/class:parrot.outputs.formats.template_report.Templa-907f217b.md)

Renders AI output using Jinja2 templates via the TemplateEngine.

## [WhatsAppRenderer](entities/class:parrot.outputs.formats.whatsapp.WhatsAppRenderer.md)

Renderer for WhatsApp output — returns plain text.

## [YAMLRenderer](entities/class:parrot.outputs.formats.yaml.YAMLRenderer.md)

Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback

## [OutputFormatter](entities/class:parrot.outputs.formatter.OutputFormatter.md)

Formatter for AI responses supporting multiple output modes.

## [OutputRetryConfig](entities/class:parrot.outputs.formatter.OutputRetryConfig.md)

Configuration for LLM-based output retry on parsing failures.

## [OutputRetryResult](entities/class:parrot.outputs.formatter.OutputRetryResult.md)

Result from an output retry attempt.

## [ReportTemplate](entities/class:parrot.outputs.templates.ReportTemplate.md)

Defines a report template structure.

## [TemplateRegistry](entities/class:parrot.outputs.templates.TemplateRegistry.md)

Registry of available templates.

## [TemplateSection](entities/class:parrot.outputs.templates.TemplateSection.md)

Defines a fillable section in the template.

## [PluginImporter](entities/class:parrot.plugins.importer.PluginImporter.md)

A custom importer to load plugins from a specified directory.

## [CapabilityEntry](entities/class:parrot.registry.capabilities.models.CapabilityEntry.md)

A registered capability in the semantic index.

## [IntentRouterConfig](entities/class:parrot.registry.capabilities.models.IntentRouterConfig.md)

Configuration for the IntentRouter.

## [ResourceType](entities/class:parrot.registry.capabilities.models.ResourceType.md)

Type of resource registered in the capability index.

## [RouterCandidate](entities/class:parrot.registry.capabilities.models.RouterCandidate.md)

A scored match from capability search.

## [RoutingDecision](entities/class:parrot.registry.capabilities.models.RoutingDecision.md)

The router's selected strategy and candidates.

## [RoutingTrace](entities/class:parrot.registry.capabilities.models.RoutingTrace.md)

Full trace of a routing session.

## [RoutingType](entities/class:parrot.registry.capabilities.models.RoutingType.md)

Strategy the intent router can select.

## [TraceEntry](entities/class:parrot.registry.capabilities.models.TraceEntry.md)

One step in the routing trace.

## [CapabilityRegistry](entities/class:parrot.registry.capabilities.registry.Capabil-8fd42986.md)

Semantic resource index for intent routing.

## [AgentFactory](entities/class:parrot.registry.registry.AgentFactory.md)

Protocol for agent factory callable.

## [AgentRegistry](entities/class:parrot.registry.registry.AgentRegistry.md)

Central registry for managing Bo/Agent discovery and registration.

## [BotConfig](entities/class:parrot.registry.registry.BotConfig.md)

Configuration for the bot in config-based discovery.

## [BotMetadata](entities/class:parrot.registry.registry.BotMetadata.md)

Metadata about a discovered Bot or Agent.

## [PromptConfig](entities/class:parrot.registry.registry.PromptConfig.md)

Declarative prompt layer configuration from YAML.

## [DecisionCache](entities/class:parrot.registry.routing.cache.DecisionCache.md)

Asyncio-safe LRU cache for :class:`~parrot.registry.routing.StoreRoutingDecision`.

## [EmbeddingIntentRouter](entities/class:parrot.registry.routing.embedding_router.Embe-cce421f1.md)

Deterministic, embedding-based output-mode router. No cloud LLM.

## [RouteScore](entities/class:parrot.registry.routing.embedding_router.RouteScore.md)

Result of :meth:`EmbeddingIntentRouter.route`.

## [StoreFallbackPolicy](entities/class:parrot.registry.routing.models.StoreFallbackPolicy.md)

What the router does when no store scores above ``confidence_floor``.

## [StoreRouterConfig](entities/class:parrot.registry.routing.models.StoreRouterConfig.md)

Full configuration for ``StoreRouter``.

## [StoreRoutingDecision](entities/class:parrot.registry.routing.models.StoreRoutingDecision.md)

Complete output of ``StoreRouter.route()``.

## [StoreRule](entities/class:parrot.registry.routing.models.StoreRule.md)

One heuristic rule that maps a query pattern to a preferred store.

## [StoreScore](entities/class:parrot.registry.routing.models.StoreScore.md)

One ranked store entry within a ``StoreRoutingDecision``.

## [OntologyPreAnnotator](entities/class:parrot.registry.routing.ontology_signal.Ontol-26ebc4b4.md)

Adapter that exposes ``OntologyIntentResolver`` as a simple annotator.

## [NoSuitableStoreError](entities/class:parrot.registry.routing.store_router.NoSuitab-3cd9e823.md)

Raised by ``StoreRouter.execute`` when ``fallback_policy=RAISE``

## [StoreRouter](entities/class:parrot.registry.routing.store_router.StoreRouter.md)

Store-level router activated via ``AbstractBot.configure_store_router()``.

## [BotConfigStorage](entities/class:parrot.registry.storage.BotConfigStorage.md)

Redis-backed CRUD storage for BotConfig agent definitions.

## [AbstractReranker](entities/class:parrot.rerankers.abstract.AbstractReranker.md)

Abstract base class for relevance rerankers.

## [LLMReranker](entities/class:parrot.rerankers.llm.LLMReranker.md)

Debug reranker that uses an LLM to score query-passage pairs.

## [LocalCrossEncoderReranker](entities/class:parrot.rerankers.local.LocalCrossEncoderReranker.md)

In-process cross-encoder reranker using HuggingFace models.

## [RerankedDocument](entities/class:parrot.rerankers.models.RerankedDocument.md)

A SearchResult enriched with reranker scoring.

## [RerankerConfig](entities/class:parrot.rerankers.models.RerankerConfig.md)

Construction configuration for LocalCrossEncoderReranker.

## [BaseSchedulerCallback](entities/class:parrot.scheduler.functions.BaseSchedulerCallback.md)

Base class for scheduler callbacks executed after successful jobs.

## [CreateFileCallback](entities/class:parrot.scheduler.functions.CreateFileCallback.md)

Class CreateFileCallback in parrot.scheduler.functions

## [SaveDataCallback](entities/class:parrot.scheduler.functions.SaveDataCallback.md)

Class SaveDataCallback in parrot.scheduler.functions

## [SendEmailReportCallback](entities/class:parrot.scheduler.functions.SendEmailReportCallback.md)

Class SendEmailReportCallback in parrot.scheduler.functions

## [SendNotifyReportCallback](entities/class:parrot.scheduler.functions.SendNotifyReportCallback.md)

Class SendNotifyReportCallback in parrot.scheduler.functions

## [AgentSchedulerManager](entities/class:parrot.scheduler.manager.AgentSchedulerManager.md)

Manager for scheduling agent operations using APScheduler.

## [ScheduleType](entities/class:parrot.scheduler.manager.ScheduleType.md)

Schedule execution types.

## [SchedulerHandler](entities/class:parrot.scheduler.manager.SchedulerHandler.md)

HTTP handler for schedule management.

## [AgentSchedule](entities/class:parrot.scheduler.models.AgentSchedule.md)

Database model for storing agent schedules.

## [AbstractKMSSigner](entities/class:parrot.security.audit_ledger.AbstractKMSSigner.md)

Injectable signing/verification backend for :class:`AuditLedger`.

## [AuditLedger](entities/class:parrot.security.audit_ledger.AuditLedger.md)

Append-only, KMS-signed credential-invocation ledger.

## [AuditLedgerEntry](entities/class:parrot.security.audit_ledger.AuditLedgerEntry.md)

Append-only, KMS-signed record of a credentialed tool invocation.

## [AzureKeyVaultSigner](entities/class:parrot.security.audit_ledger.AzureKeyVaultSigner.md)

Azure Key Vault backed KMS signer for production environments.

## [LocalHMACSigner](entities/class:parrot.security.audit_ledger.LocalHMACSigner.md)

HMAC-SHA256 signer for local development and testing.

## [CommandRule](entities/class:parrot.security.command_sanitizer.CommandRule.md)

Per-command security rule for argument-level restrictions.

## [CommandSanitizer](entities/class:parrot.security.command_sanitizer.CommandSanitizer.md)

Multi-layered command sanitizer for shell / agent tool integration.

## [CommandSecurityError](entities/class:parrot.security.command_sanitizer.CommandSecurityError.md)

Raised when a command fails security validation.

## [CommandVerdict](entities/class:parrot.security.command_sanitizer.CommandVerdict.md)

Result of command validation.

## [SecurityLevel](entities/class:parrot.security.command_sanitizer.SecurityLevel.md)

Security policy levels.

## [SecurityPolicy](entities/class:parrot.security.command_sanitizer.SecurityPolicy.md)

Configurable security policy for command execution.

## [ValidationResult](entities/class:parrot.security.command_sanitizer.ValidationResult.md)

Immutable result of command validation.

## [PromptInjectionDetector](entities/class:parrot.security.prompt_injection.PromptInject-4bb0d560.md)

Detects and mitigates prompt injection attempts in user questions.

## [PromptInjectionException](entities/class:parrot.security.prompt_injection.PromptInject-6e568d65.md)

Raised when a critical prompt injection is detected in strict mode.

## [SecurityEventLogger](entities/class:parrot.security.prompt_injection.SecurityEventLogger.md)

Logs security events with session tracking.

## [ThreatLevel](entities/class:parrot.security.prompt_injection.ThreatLevel.md)

Severity levels for detected threats.

## [PythonCodeSanitizer](entities/class:parrot.security.python_sanitizer.PythonCodeSanitizer.md)

Allowlist-first AST gate for Python code.

## [PythonExecutionPolicy](entities/class:parrot.security.python_sanitizer.PythonExecutionPolicy.md)

Policy controlling the ``PythonCodeSanitizer`` allowlist-first gate.

## [QueryLanguage](entities/class:parrot.security.query_validator.QueryLanguage.md)

Supported query languages.

## [QueryValidator](entities/class:parrot.security.query_validator.QueryValidator.md)

Validates queries based on query language.

## [OutputScrubber](entities/class:parrot.security.redaction.OutputScrubber.md)

Policy-driven output scrubber for tool results and egress text.

## [ScrubPolicy](entities/class:parrot.security.redaction.ScrubPolicy.md)

Policy controlling OutputScrubber behaviour.

## [AgentService](entities/class:parrot.services.agent_service.AgentService.md)

Standalone asyncio runtime for autonomous AI agents.

## [AgentServiceClient](entities/class:parrot.services.client.AgentServiceClient.md)

Async client for submitting tasks to a running AgentService.

## [DeliveryRouter](entities/class:parrot.services.delivery.DeliveryRouter.md)

Routes task results to the appropriate delivery channel.

## [HeartbeatScheduler](entities/class:parrot.services.heartbeat.HeartbeatScheduler.md)

Schedules periodic agent heartbeats via APScheduler.

## [IdentityMappingService](entities/class:parrot.services.identity_mapping.IdentityMapp-db6b9280.md)

CRUD service for ``auth.user_identities`` records.

## [AgentServiceConfig](entities/class:parrot.services.models.AgentServiceConfig.md)

Top-level configuration for AgentService.

## [AgentTask](entities/class:parrot.services.models.AgentTask.md)

A task to be executed by an agent.

## [DeliveryChannel](entities/class:parrot.services.models.DeliveryChannel.md)

Supported delivery channels for task results.

## [DeliveryConfig](entities/class:parrot.services.models.DeliveryConfig.md)

Channel-specific delivery parameters.

## [HeartbeatConfig](entities/class:parrot.services.models.HeartbeatConfig.md)

Configuration for periodic agent heartbeats.

## [TaskPriority](entities/class:parrot.services.models.TaskPriority.md)

Task priority levels (lower = higher priority).

## [TaskResult](entities/class:parrot.services.models.TaskResult.md)

Result of an agent task execution.

## [TaskStatus](entities/class:parrot.services.models.TaskStatus.md)

Task lifecycle states.

## [RedisTaskListener](entities/class:parrot.services.redis_listener.RedisTaskListener.md)

Listens for incoming tasks on a Redis Stream using consumer groups.

## [TaskQueue](entities/class:parrot.services.task_queue.TaskQueue.md)

Priority-aware async task queue.

## [VaultTokenSync](entities/class:parrot.services.vault_token_sync.VaultTokenSync.md)

Persist OAuth tokens in the encrypted user vault.

## [WhatsAppConfigHandler](entities/class:parrot.services.whatsapp.WhatsAppConfigHandler.md)

Authenticated endpoints for WhatsApp bridge management.

## [WhatsAppQRHandler](entities/class:parrot.services.whatsapp.WhatsAppQRHandler.md)

Authenticated endpoints for QR code authentication.

## [WorkerPool](entities/class:parrot.services.worker_pool.WorkerPool.md)

Limits concurrent agent executions using an asyncio semaphore.

## [AnthropicWizard](entities/class:parrot.setup.providers.anthropic.AnthropicWizard.md)

Wizard for Anthropic (Claude) credential collection.

## [GoogleWizard](entities/class:parrot.setup.providers.google.GoogleWizard.md)

Wizard for Google (Gemini) credential collection.

## [OpenAIWizard](entities/class:parrot.setup.providers.openai.OpenAIWizard.md)

Wizard for OpenAI credential collection.

## [OpenRouterWizard](entities/class:parrot.setup.providers.openrouter.OpenRouterWizard.md)

Wizard for OpenRouter credential collection.

## [XAIWizard](entities/class:parrot.setup.providers.xai.XAIWizard.md)

Wizard for xAI (Grok) credential collection.

## [AgentConfig](entities/class:parrot.setup.wizard.AgentConfig.md)

Collected configuration for agent scaffolding.

## [BaseClientWizard](entities/class:parrot.setup.wizard.BaseClientWizard.md)

Abstract base class for provider-specific credential wizards.

## [ProviderConfig](entities/class:parrot.setup.wizard.ProviderConfig.md)

Collected configuration for a single LLM provider.

## [WizardResult](entities/class:parrot.setup.wizard.WizardResult.md)

Full result of a completed setup wizard run.

## [WizardRunner](entities/class:parrot.setup.wizard.WizardRunner.md)

Orchestrates the full ``parrot setup`` wizard pipeline.

## [SkillFileRegistry](entities/class:parrot.skills.file_registry.SkillFileRegistry.md)

Filesystem-based skill registry with eager loading.

## [SkillsDirectoryLoader](entities/class:parrot.skills.loader.SkillsDirectoryLoader.md)

Discover and load skills from one or more filesystem directories.

## [SkillRegistryHooks](entities/class:parrot.skills.mixin.SkillRegistryHooks.md)

Hook functions for skill registry integration.

## [SkillRegistryMixin](entities/class:parrot.skills.mixin.SkillRegistryMixin.md)

Mixin to add skill registry capabilities to AbstractBot.

## [ContentType](entities/class:parrot.skills.models.ContentType.md)

How the version content is stored.

## [DeprecateSkillArgs](entities/class:parrot.skills.models.DeprecateSkillArgs.md)

Arguments for deprecating a skill.

## [ExtractedSkill](entities/class:parrot.skills.models.ExtractedSkill.md)

LLM-extracted skill from conversation.

## [ReadSkillArgs](entities/class:parrot.skills.models.ReadSkillArgs.md)

Arguments for reading a skill.

## [SearchSkillArgs](entities/class:parrot.skills.models.SearchSkillArgs.md)

Arguments for searching skills.

## [Skill](entities/class:parrot.skills.models.Skill.md)

A versioned skill/knowledge document.

## [SkillCategory](entities/class:parrot.skills.models.SkillCategory.md)

Categories for organizing skills.

## [SkillDefinition](entities/class:parrot.skills.models.SkillDefinition.md)

Parsed skill from a .md file with YAML frontmatter.

## [SkillMetadata](entities/class:parrot.skills.models.SkillMetadata.md)

Searchable metadata for a skill.

## [SkillSearchResult](entities/class:parrot.skills.models.SkillSearchResult.md)

Result from skill search.

## [SkillSource](entities/class:parrot.skills.models.SkillSource.md)

Origin of the skill.

## [SkillStatus](entities/class:parrot.skills.models.SkillStatus.md)

Lifecycle status of a skill.

## [SkillVersion](entities/class:parrot.skills.models.SkillVersion.md)

A single immutable version of a skill.

## [SkillVersionsArgs](entities/class:parrot.skills.models.SkillVersionsArgs.md)

Arguments for listing skill versions.

## [UploadSkillArgs](entities/class:parrot.skills.models.UploadSkillArgs.md)

Arguments for uploading/updating a skill.

## [SkillRegistry](entities/class:parrot.skills.store.SkillRegistry.md)

Git-like versioned skill registry.

## [DocumentSkillArgs](entities/class:parrot.skills.tools.DocumentSkillArgs.md)

Arguments for documenting a new skill.

## [LoadSkillArgs](entities/class:parrot.skills.tools.LoadSkillArgs.md)

Arguments for loading a skill's full content on demand.

## [ReadSkillAssetArgs](entities/class:parrot.skills.tools.ReadSkillAssetArgs.md)

Arguments for reading a bundled asset of a composite skill.

## [ReadSkillToolArgs](entities/class:parrot.skills.tools.ReadSkillToolArgs.md)

Arguments for reading a skill.

## [SaveLearnedSkillArgs](entities/class:parrot.skills.tools.SaveLearnedSkillArgs.md)

Arguments for saving a learned skill as a .md file.

## [SkillFileToolkit](entities/class:parrot.skills.tools.SkillFileToolkit.md)

Unified toolkit for file-based skills, sharing one ``SkillFileRegistry``.

## [SkillRegistryToolkit](entities/class:parrot.skills.tools.SkillRegistryToolkit.md)

Unified toolkit for the DB-backed skill registry, sharing one store.

## [UpdateSkillArgs](entities/class:parrot.skills.tools.UpdateSkillArgs.md)

Arguments for updating an existing skill.

## [ArtifactStore](entities/class:parrot.storage.artifacts.ArtifactStore.md)

Artifact CRUD operations against the configured storage backend.

## [ConversationBackend](entities/class:parrot.storage.backends.base.ConversationBackend.md)

Abstract storage backend for conversations, threads, turns, and artifacts.

## [ConversationDynamoDB](entities/class:parrot.storage.backends.dynamodb.ConversationDynamoDB.md)

Domain wrapper around DynamoDB for conversation storage.

## [ConversationMongoBackend](entities/class:parrot.storage.backends.mongodb.ConversationM-80d4a0f4.md)

Async MongoDB implementation of ConversationBackend.

## [ConversationPostgresBackend](entities/class:parrot.storage.backends.postgres.Conversation-8c341fec.md)

Async PostgreSQL implementation of ConversationBackend.

## [ConversationSQLiteBackend](entities/class:parrot.storage.backends.sqlite.ConversationSQ-936b19b0.md)

Async SQLite implementation of ConversationBackend.

## [ChatStorage](entities/class:parrot.storage.chat.ChatStorage.md)

Unified chat persistence with Redis hot cache and DynamoDB cold storage.

## [InstrumentedBackend](entities/class:parrot.storage.instrumented.InstrumentedBackend.md)

Wraps any ConversationBackend and records per-method latency + errors.

## [NoopStorageMetrics](entities/class:parrot.storage.metrics.NoopStorageMetrics.md)

Default metrics implementation — records nothing.

## [StorageMetrics](entities/class:parrot.storage.metrics.StorageMetrics.md)

Protocol for storage-backend metric collection.

## [Artifact](entities/class:parrot.storage.models.Artifact.md)

Full artifact with definition payload.

## [ArtifactCreator](entities/class:parrot.storage.models.ArtifactCreator.md)

Who created the artifact.

## [ArtifactSummary](entities/class:parrot.storage.models.ArtifactSummary.md)

Lightweight artifact reference for thread metadata.

## [ArtifactType](entities/class:parrot.storage.models.ArtifactType.md)

Type of artifact produced by an agent or user.

## [CanvasBlock](entities/class:parrot.storage.models.CanvasBlock.md)

Individual block within a canvas tab.

## [CanvasBlockType](entities/class:parrot.storage.models.CanvasBlockType.md)

Type of block within a canvas tab.

## [CanvasDefinition](entities/class:parrot.storage.models.CanvasDefinition.md)

Complete canvas tab artifact definition.

## [ChatMessage](entities/class:parrot.storage.models.ChatMessage.md)

Represents a single chat message (one direction: user OR assistant).

## [Conversation](entities/class:parrot.storage.models.Conversation.md)

Conversation metadata — one document per session in DocumentDB.

## [MessageRole](entities/class:parrot.storage.models.MessageRole.md)

Role of the message sender.

## [Source](entities/class:parrot.storage.models.Source.md)

A source/reference returned by the agent.

## [ThreadMetadata](entities/class:parrot.storage.models.ThreadMetadata.md)

Conversation thread metadata stored in DynamoDB.

## [ToolCall](entities/class:parrot.storage.models.ToolCall.md)

A single tool invocation within a turn.

## [OverflowStore](entities/class:parrot.storage.overflow.OverflowStore.md)

Generic artifact overflow store backed by any FileManagerInterface.

## [S3OverflowManager](entities/class:parrot.storage.s3_overflow.S3OverflowManager.md)

Back-compat subclass: OverflowStore bound to S3FileManager.

## [EmbeddedFinding](entities/class:parrot.storage.security_reports.models.EmbeddedFinding.md)

A single security finding embedded in a ReportRef.

## [ReportFilter](entities/class:parrot.storage.security_reports.models.ReportFilter.md)

Query filter for the security report store.

## [ReportKind](entities/class:parrot.storage.security_reports.models.ReportKind.md)

Fractal kind hierarchy: raw scans and aggregated summaries share the same shape.

## [ReportRef](entities/class:parrot.storage.security_reports.models.ReportRef.md)

Canonical metadata record for any security report.

## [SeverityBreakdown](entities/class:parrot.storage.security_reports.models.Severi-981f8401.md)

Count container for findings by severity level.

## [PostgresS3SecurityReportStore](entities/class:parrot.storage.security_reports.store.Postgre-130e65e3.md)

Postgres (metadata) + S3/FileManager (content) catalog implementation.

## [SecurityReportStore](entities/class:parrot.storage.security_reports.store.Securit-aea4b3ef.md)

Protocol for the security report catalog persistence layer.

## [AbstractStore](entities/class:parrot.stores.abstract.AbstractStore.md)

AbstractStore class.

## [ArangoDBStore](entities/class:parrot.stores.arango.ArangoDBStore.md)

ArangoDB Vector Store with native graph support.

## [BigQueryStore](entities/class:parrot.stores.bigquery.BigQueryStore.md)

A BigQuery vector store implementation for storing and searching embeddings.

## [SemanticVectorCache](entities/class:parrot.stores.cache.SemanticVectorCache.md)

A class to handle caching of semantic vectors using Redis.

## [EmptyStore](entities/class:parrot.stores.empty.EmptyStore.md)

Empty Store reference, used on bots without Vector Store Support.

## [FAISSStore](entities/class:parrot.stores.faiss_store.FAISSStore.md)

An in-memory FAISS vector store implementation, completely independent of Langchain.

## [AbstractKnowledgeBase](entities/class:parrot.stores.kb.abstract.AbstractKnowledgeBase.md)

Base class for all knowledge bases.

## [CacheEntry](entities/class:parrot.stores.kb.cache.CacheEntry.md)

Cache entry with TTL support.

## [TTLCache](entities/class:parrot.stores.kb.cache.TTLCache.md)

Thread-safe TTL cache with memory management.

## [ChatbotSettings](entities/class:parrot.stores.kb.doc.ChatbotSettings.md)

Knowledge Base for chatbot-specific settings.

## [DocumentMetadata](entities/class:parrot.stores.kb.doc.DocumentMetadata.md)

Knowledge Base for document metadata and indexing.

## [UserContext](entities/class:parrot.stores.kb.doc.UserContext.md)

Knowledge Base for user context and session data.

## [EmployeeHierarchyKB](entities/class:parrot.stores.kb.hierarchy.EmployeeHierarchyKB.md)

Knowledge Base what provides employee hierarchy context.

## [LocalKB](entities/class:parrot.stores.kb.local.LocalKB.md)

Local Knowledge Base that loads markdown and text documents from a local directory.

## [RedisKnowledgeBase](entities/class:parrot.stores.kb.redis.RedisKnowledgeBase.md)

Generic Redis-based Knowledge Base with CRUD operations.

## [KnowledgeBaseStore](entities/class:parrot.stores.kb.store.KnowledgeBaseStore.md)

Lightweight in-memory store for validated facts.

## [SessionStateKB](entities/class:parrot.stores.kb.user.SessionStateKB.md)

KB that retrieves from session state.

## [UserInfo](entities/class:parrot.stores.kb.user.UserInfo.md)

Class to manage user information.

## [UserPreferences](entities/class:parrot.stores.kb.user.UserPreferences.md)

KB for user preferences stored in Redis.

## [UserProfileKB](entities/class:parrot.stores.kb.user.UserProfileKB.md)

KB that queries database for user information.

## [MilvusStore](entities/class:parrot.stores.milvus.MilvusStore.md)

A Milvus vector store implementation using pymilvus MilvusClient.

## [DistanceStrategy](entities/class:parrot.stores.models.DistanceStrategy.md)

Enumerator of the Distance strategies for calculating distances

## [Document](entities/class:parrot.stores.models.Document.md)

A simple document model for adding data to the vector store.

## [AbstractParentSearcher](entities/class:parrot.stores.parents.abstract.AbstractParentSearcher.md)

Composable strategy for fetching parent documents by ID.

## [InTableParentSearcher](entities/class:parrot.stores.parents.in_table.InTableParentSearcher.md)

Fetch parents from the same vector table by metadata filter.

## [Base](entities/class:parrot.stores.postgres.Base.md)

Class Base in parrot.stores.postgres

## [PgVectorStore](entities/class:parrot.stores.postgres.PgVectorStore.md)

A PostgreSQL vector store implementation using pgvector, completely independent of Langchain.

## [ChunkInfo](entities/class:parrot.stores.utils.chunking.ChunkInfo.md)

Information about a document chunk

## [LateChunkingProcessor](entities/class:parrot.stores.utils.chunking.LateChunkingProcessor.md)

Late Chunking processor integrated with PgVectorStore.

## [JinjaConfig](entities/class:parrot.template.engine.JinjaConfig.md)

Configuration for the async Jinja2 Environment.

## [TemplateEngine](entities/class:parrot.template.engine.TemplateEngine.md)

Async-only Jinja2 template engine with:

## [AbstractTool](entities/class:parrot.tools.abstract.AbstractTool.md)

Abstract base class for all tools in the ai-parrot framework.

## [AbstractToolArgsSchema](entities/class:parrot.tools.abstract.AbstractToolArgsSchema.md)

Base schema for tool arguments.

## [ToolResult](entities/class:parrot.tools.abstract.ToolResult.md)

Standardized tool result format.

## [AgentContext](entities/class:parrot.tools.agent.AgentContext.md)

Context passed between agents in orchestration.

## [AgentTool](entities/class:parrot.tools.agent.AgentTool.md)

Wraps any BasicAgent/AbstractBot as a tool for use by other agents.

## [QuestionInput](entities/class:parrot.tools.agent.QuestionInput.md)

Input schema for AgentTool - defines the question parameter.

## [AbstractDatabaseSource](entities/class:parrot.tools.databasequery.base.AbstractDatabaseSource.md)

Abstract base class for all database source implementations.

## [ColumnMeta](entities/class:parrot.tools.databasequery.base.ColumnMeta.md)

Metadata for a single database column or field.

## [MetadataResult](entities/class:parrot.tools.databasequery.base.MetadataResult.md)

Result of a metadata discovery operation.

## [QueryResult](entities/class:parrot.tools.databasequery.base.QueryResult.md)

Result of a multi-row query execution.

## [RowResult](entities/class:parrot.tools.databasequery.base.RowResult.md)

Result of a single-row fetch operation.

## [TableMeta](entities/class:parrot.tools.databasequery.base.TableMeta.md)

Metadata for a single database table, collection, or measurement.

## [ValidationResult](entities/class:parrot.tools.databasequery.base.ValidationResult.md)

Result of a query validation operation.

## [AtlasSource](entities/class:parrot.tools.databasequery.sources.atlas.AtlasSource.md)

MongoDB Atlas database source.

## [BigQuerySource](entities/class:parrot.tools.databasequery.sources.bigquery.B-ae467c39.md)

Google BigQuery database source.

## [ClickHouseSource](entities/class:parrot.tools.databasequery.sources.clickhouse-279012e4.md)

ClickHouse OLAP database source.

## [DocumentDBSource](entities/class:parrot.tools.databasequery.sources.documentdb-af827f75.md)

AWS DocumentDB database source.

## [DuckDBSource](entities/class:parrot.tools.databasequery.sources.duckdb.DuckDBSource.md)

DuckDB embedded analytical database source.

## [ElasticSource](entities/class:parrot.tools.databasequery.sources.elastic.El-3f6ae872.md)

Elasticsearch/OpenSearch database source.

## [InfluxSource](entities/class:parrot.tools.databasequery.sources.influx.InfluxSource.md)

InfluxDB time-series database source.

## [MongoSource](entities/class:parrot.tools.databasequery.sources.mongodb.MongoSource.md)

MongoDB database source.

## [MSSQLSource](entities/class:parrot.tools.databasequery.sources.mssql.MSSQLSource.md)

Microsoft SQL Server database source with stored procedure support.

## [MySQLSource](entities/class:parrot.tools.databasequery.sources.mysql.MySQLSource.md)

MySQL/MariaDB database source.

## [OracleSource](entities/class:parrot.tools.databasequery.sources.oracle.OracleSource.md)

Oracle Database source.

## [PostgresSource](entities/class:parrot.tools.databasequery.sources.postgres.P-dac89ec0.md)

PostgreSQL database source.

## [SQLiteSource](entities/class:parrot.tools.databasequery.sources.sqlite.SQLiteSource.md)

SQLite database source.

## [DatabaseQueryArgs](entities/class:parrot.tools.databasequery.tool.DatabaseQueryArgs.md)

Arguments schema for DatabaseQueryTool.

## [DatabaseQueryTool](entities/class:parrot.tools.databasequery.tool.DatabaseQueryTool.md)

Multi-language Database Query Tool for executing queries across multiple database systems.

## [DriverInfo](entities/class:parrot.tools.databasequery.tool.DriverInfo.md)

Driver metadata wrapper preserved for back-compat (FEAT-105).

## [DatabaseQueryToolkit](entities/class:parrot.tools.databasequery.toolkit.DatabaseQu-ab565c4a.md)

Multi-database toolkit — discover schema, validate queries, execute.

## [ComputedColumnDef](entities/class:parrot.tools.dataset_manager.computed.Compute-9107ac25.md)

Definition of a computed column applied post-materialization.

## [CellRegion](entities/class:parrot.tools.dataset_manager.excel_analyzer.CellRegion.md)

A rectangular region within a sheet.

## [DetectedTable](entities/class:parrot.tools.dataset_manager.excel_analyzer.D-e42010a3.md)

A table discovered within a sheet.

## [ExcelStructureAnalyzer](entities/class:parrot.tools.dataset_manager.excel_analyzer.E-5126b8b5.md)

Core analysis engine for Excel workbooks.

## [SheetAnalysis](entities/class:parrot.tools.dataset_manager.excel_analyzer.S-48f3ddbc.md)

Complete structural analysis of one sheet.

## [FilterCompiler](entities/class:parrot.tools.dataset_manager.filtering.compil-fc15959f.md)

Stateless compiler that translates FilterCondition to SQL or pandas.

## [FilterCondition](entities/class:parrot.tools.dataset_manager.filtering.contra-4c1d0e85.md)

A single applied condition within a filter request.

## [FilterDefinition](entities/class:parrot.tools.dataset_manager.filtering.contra-38ef133f.md)

A declarative common-field filter definition stored on a DatasetManager.

## [FilterResult](entities/class:parrot.tools.dataset_manager.filtering.contra-b2d0699c.md)

Records the per-run outcome of ``DatasetManager.apply_filters``.

## [ValuesSource](entities/class:parrot.tools.dataset_manager.filtering.contra-f368eaf3.md)

Specifies where to obtain the distinct values for a frontend combo.

## [AirtableSource](entities/class:parrot.tools.dataset_manager.sources.airtable-3ccd564e.md)

Datasource backed by an Airtable table.

## [AuthorizingDataSource](entities/class:parrot.tools.dataset_manager.sources.authoriz-4a75e36d.md)

Decorator that wraps a DataSource with authorization + RLS enforcement.

## [DataSource](entities/class:parrot.tools.dataset_manager.sources.base.DataSource.md)

Abstract base for all data sources.

## [CompositeDataSource](entities/class:parrot.tools.dataset_manager.sources.composit-ff70adb8.md)

Virtual DataSource that JOINs existing datasets on demand.

## [JoinSpec](entities/class:parrot.tools.dataset_manager.sources.composit-cccbeed2.md)

Specification for joining two datasets.

## [DeltaTableSource](entities/class:parrot.tools.dataset_manager.sources.deltatab-26455108.md)

DataSource for Delta Lake tables via asyncdb's delta driver.

## [IcebergSource](entities/class:parrot.tools.dataset_manager.sources.iceberg.-1a982a20.md)

DataSource for Apache Iceberg tables via asyncdb's iceberg driver.

## [InMemorySource](entities/class:parrot.tools.dataset_manager.sources.memory.I-84464712.md)

Wraps an already-loaded pd.DataFrame as a DataSource.

## [MongoSource](entities/class:parrot.tools.dataset_manager.sources.mongo.MongoSource.md)

DataSource for MongoDB/DocumentDB collections via asyncdb's mongo driver.

## [MultiQuerySlugSource](entities/class:parrot.tools.dataset_manager.sources.query_sl-261b381f.md)

DataSource backed by multiple QuerySource slugs whose results are merged.

## [QuerySlugSource](entities/class:parrot.tools.dataset_manager.sources.query_sl-ce6de740.md)

DataSource backed by a single QuerySource slug.

## [PhysicalResources](entities/class:parrot.tools.dataset_manager.sources.resolver-1ec2dfd5.md)

Resolved physical resources for a DataSource.

## [ReadOnlyViolation](entities/class:parrot.tools.dataset_manager.sources.resolver-b3612143.md)

Raised when a SQL statement is not read-only (DML/DDL detected).

## [SmartsheetSource](entities/class:parrot.tools.dataset_manager.sources.smartshe-fd544db1.md)

Datasource backed by a Smartsheet sheet.

## [SQLQuerySource](entities/class:parrot.tools.dataset_manager.sources.sql.SQLQ-e8a9fcae.md)

DataSource backed by a user-provided SQL template with {param} interpolation.

## [TableSource](entities/class:parrot.tools.dataset_manager.sources.table.TableSource.md)

DataSource for a database table with INFORMATION_SCHEMA schema prefetch.

## [CompiledQuery](entities/class:parrot.tools.dataset_manager.spatial.compiler-0381fdfa.md)

Immutable result of SpatialCompiler.compile().

## [SpatialCompiler](entities/class:parrot.tools.dataset_manager.spatial.compiler-00c7697d.md)

Stateless spatial filter compiler and executor.

## [DatasetSpatialProfile](entities/class:parrot.tools.dataset_manager.spatial.contract-d0121d4b.md)

Describes how a specific dataset exposes its geometry.

## [SpatialFeatureCollection](entities/class:parrot.tools.dataset_manager.spatial.contract-192e4a05.md)

GeoJSON FeatureCollection returned by DatasetManager.spatial_filter.

## [SpatialFilterSpec](entities/class:parrot.tools.dataset_manager.spatial.contract-0aab22dc.md)

Describes a spatial radius filter request.

## [SpatialLayerResult](entities/class:parrot.tools.dataset_manager.spatial.contract-082fee01.md)

Per-dataset slice of a spatial filter result (FEAT-221 G4).

## [SpatialResult](entities/class:parrot.tools.dataset_manager.spatial.contract-b3a9cc6f.md)

Versioned per-dataset result returned by spatial_filter (FEAT-221 G4).

## [DatasetEntry](entities/class:parrot.tools.dataset_manager.tool.DatasetEntry.md)

Lifecycle wrapper around a DataSource.

## [DatasetInfo](entities/class:parrot.tools.dataset_manager.tool.DatasetInfo.md)

Schema for dataset information exposed to LLM.

## [DatasetManager](entities/class:parrot.tools.dataset_manager.tool.DatasetManager.md)

Dataset Catalog and toolkit for managing DataFrames and Queries.

## [FileEntry](entities/class:parrot.tools.dataset_manager.tool.FileEntry.md)

A file loaded into DatasetManager (not a DataFrame).

## [ExcelIntelligenceToolkit](entities/class:parrot.tools.excel_intelligence.ExcelIntellig-179e1127.md)

Toolkit for intelligent Excel file analysis.

## [AbstractToolExecutor](entities/class:parrot.tools.executors.abstract.AbstractToolExecutor.md)

Pluggable transport that runs a tool somewhere other than here.

## [ToolExecutionEnvelope](entities/class:parrot.tools.executors.abstract.ToolExecutionEnvelope.md)

The wire-format payload describing a single remote tool invocation.

## [K8sToolExecutor](entities/class:parrot.tools.executors.k8s.K8sToolExecutor.md)

Runs the envelope inside an ephemeral Kubernetes Job.

## [LocalToolExecutor](entities/class:parrot.tools.executors.local.LocalToolExecutor.md)

Executor that runs the tool in the current Python process.

## [QworkerToolExecutor](entities/class:parrot.tools.executors.qworker.QworkerToolExecutor.md)

Dispatch tool execution to the Qworker service.

## [FileManagerFactory](entities/class:parrot.tools.filemanager.FileManagerFactory.md)

Factory for creating file managers.

## [FileManagerTool](entities/class:parrot.tools.filemanager.FileManagerTool.md)

Tool for AI agents to interact with file systems.

## [FileManagerToolArgs](entities/class:parrot.tools.filemanager.FileManagerToolArgs.md)

Arguments schema for FileManagerTool.

## [FileManagerToolkit](entities/class:parrot.tools.filemanager.FileManagerToolkit.md)

Toolkit for AI agents to interact with file systems — preferred API.

## [InfographicRenderResult](entities/class:parrot.tools.infographic_toolkit.InfographicR-44ebb32e.md)

Envelope returned by InfographicToolkit.render (return_direct=True).

## [InfographicToolkit](entities/class:parrot.tools.infographic_toolkit.InfographicToolkit.md)

Toolkit that produces frozen, multi-dataset HTML infographic artifacts.

## [InfographicValidationError](entities/class:parrot.tools.infographic_toolkit.InfographicV-9ff6ec09.md)

Structured error raised by the validation pipeline.

## [InteractiveCatalogRegistry](entities/class:parrot.tools.interactive.catalog_registry.Int-62d20b58.md)

Eager-loading registry of catalog libraries and scaffold templates.

## [InteractiveToolkit](entities/class:parrot.tools.interactive_toolkit.InteractiveToolkit.md)

Toolkit producing self-contained interactive HTML artifacts.

## [InteractiveValidationError](entities/class:parrot.tools.interactive_toolkit.InteractiveV-d5ad28e5.md)

Structured error raised by the interactive render pipeline.

## [JiraConnectTool](entities/class:parrot.tools.jira_connect_tool.JiraConnectTool.md)

Placeholder tool returning the Jira OAuth authorization URL.

## [ToJsonArgs](entities/class:parrot.tools.json_tool.ToJsonArgs.md)

Class ToJsonArgs in parrot.tools.json_tool

## [ToJsonTool](entities/class:parrot.tools.json_tool.ToJsonTool.md)

Tool to convert data to JSON using datamodel.parsers.json.

## [ToolDefinition](entities/class:parrot.tools.manager.ToolDefinition.md)

Data structure for tool definition.

## [ToolFormat](entities/class:parrot.tools.manager.ToolFormat.md)

Enum for different tool format requirements by LLM providers.

## [ToolManager](entities/class:parrot.tools.manager.ToolManager.md)

Unified tool manager for handling tools across AbstractBot and AbstractClient.

## [ToolNameCollisionError](entities/class:parrot.tools.manager.ToolNameCollisionError.md)

Raised when two toolkits try to register the same tool name.

## [ToolSchemaAdapter](entities/class:parrot.tools.manager.ToolSchemaAdapter.md)

Adapter class to convert tool schemas between different LLM provider formats.

## [MCPToolManagerMixin](entities/class:parrot.tools.mcp_mixin.MCPToolManagerMixin.md)

Mixin to add MCP capabilities to ToolManager.

## [OpenAPIToolkit](entities/class:parrot.tools.openapitoolkit.OpenAPIToolkit.md)

Toolkit that dynamically generates tools from OpenAPI specifications.

## [PythonPandasTool](entities/class:parrot.tools.pythonpandas.PythonPandasTool.md)

Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.

## [PythonREPLArgs](entities/class:parrot.tools.pythonrepl.PythonREPLArgs.md)

Arguments schema for PythonREPLTool.

## [PythonREPLTool](entities/class:parrot.tools.pythonrepl.PythonREPLTool.md)

Python REPL Tool with pre-loaded data science libraries and enhanced capabilities.

## [ToolkitRegistry](entities/class:parrot.tools.registry.ToolkitRegistry.md)

Registry for supported toolkits with lazy loading.

## [ReminderToolkit](entities/class:parrot.tools.reminder.ReminderToolkit.md)

LLM-facing tools to schedule, list, and cancel one-time reminders.

## [SpawnSubAgentInput](entities/class:parrot.tools.spawn.SpawnSubAgentInput.md)

Input schema for SpawnSubAgentTool.

## [SpawnSubAgentTool](entities/class:parrot.tools.spawn.SpawnSubAgentTool.md)

Spawn an ephemeral sub-agent to execute a single task.

## [StubCredentialedTool](entities/class:parrot.tools.stub_credentialed_tool.StubCrede-48f1a09a.md)

Minimal credentialed echo tool for A2A bridge integration tests.

## [AbstractToolkit](entities/class:parrot.tools.toolkit.AbstractToolkit.md)

Abstract base class for creating toolkits - collections of related tools.

## [ToolkitTool](entities/class:parrot.tools.toolkit.ToolkitTool.md)

A specialized AbstractTool that wraps a method from a toolkit.

## [VectorSearchArgs](entities/class:parrot.tools.vectorstoresearch.VectorSearchArgs.md)

Arguments schema for VectorStoreSearchTool.

## [VectorStoreSearchTool](entities/class:parrot.tools.vectorstoresearch.VectorStoreSearchTool.md)

A tool for performing similarity search on vector stores.

## [CatalogEntry](entities/class:parrot.tools.working_memory.internals.CatalogEntry.md)

Metadata and data container for a stored DataFrame in the catalog.

## [GenericEntry](entities/class:parrot.tools.working_memory.internals.GenericEntry.md)

Catalog entry for non-DataFrame data.

## [OperationExecutor](entities/class:parrot.tools.working_memory.internals.Operati-ccd20947.md)

Executes OperationSpecInput against DataFrames from the catalog.

## [ShapeLimit](entities/class:parrot.tools.working_memory.internals.ShapeLimit.md)

Maximum shape constraint for summaries returned to the LLM.

## [WorkingMemoryCatalog](entities/class:parrot.tools.working_memory.internals.Working-6da94b83.md)

In-memory catalog of DataFrames and generic entries.

## [AggFunc](entities/class:parrot.tools.working_memory.models.AggFunc.md)

Aggregation function options for AGGREGATE, PIVOT, WINDOW, and SUMMARIZE operations.

## [ComputeAndStoreInput](entities/class:parrot.tools.working_memory.models.ComputeAnd-3ef214f5.md)

Input for executing a declarative operation and storing the result.

## [DropStoredInput](entities/class:parrot.tools.working_memory.models.DropStoredInput.md)

Input for removing a stored DataFrame.

## [EntryType](entities/class:parrot.tools.working_memory.models.EntryType.md)

Discriminator for catalog entry types.

## [FilterSpec](entities/class:parrot.tools.working_memory.models.FilterSpec.md)

A single filter condition.

## [GetResultInput](entities/class:parrot.tools.working_memory.models.GetResultInput.md)

Input for retrieving a stored generic result.

## [GetStoredInput](entities/class:parrot.tools.working_memory.models.GetStoredInput.md)

Input for retrieving a summary of a stored DataFrame.

## [ImportFromToolInput](entities/class:parrot.tools.working_memory.models.ImportFromToolInput.md)

Input for importing a DataFrame from another tool's namespace.

## [JoinHow](entities/class:parrot.tools.working_memory.models.JoinHow.md)

Join type options for JOIN and MERGE operations.

## [JoinOnSpec](entities/class:parrot.tools.working_memory.models.JoinOnSpec.md)

Join key specification.

## [ListStoredInput](entities/class:parrot.tools.working_memory.models.ListStoredInput.md)

Input for listing all stored entries.

## [ListToolDataFramesInput](entities/class:parrot.tools.working_memory.models.ListToolDa-8f203b89.md)

Input for listing DataFrames available in other tools.

## [MergeStoredInput](entities/class:parrot.tools.working_memory.models.MergeStoredInput.md)

Input for merging multiple stored DataFrames.

## [OperationSpecInput](entities/class:parrot.tools.working_memory.models.OperationSpecInput.md)

Declarative operation specification — the DSL contract.

## [OperationType](entities/class:parrot.tools.working_memory.models.OperationType.md)

Allowed deterministic operations the agent can request.

## [RecallInteractionInput](entities/class:parrot.tools.working_memory.models.RecallInte-e65bd728.md)

Input for recalling a Q&A interaction from AnswerMemory.

## [SaveInteractionInput](entities/class:parrot.tools.working_memory.models.SaveIntera-8c980a65.md)

Input for saving a Q&A interaction to AnswerMemory.

## [SearchStoredInput](entities/class:parrot.tools.working_memory.models.SearchStoredInput.md)

Input for searching stored entries by key/description substring or type.

## [StoreInput](entities/class:parrot.tools.working_memory.models.StoreInput.md)

Input for storing a DataFrame directly.

## [StoreResultInput](entities/class:parrot.tools.working_memory.models.StoreResultInput.md)

Input for storing a generic (non-DataFrame) result into working memory.

## [SummarizeStoredInput](entities/class:parrot.tools.working_memory.models.SummarizeS-ac6b3f91.md)

Input for merging + aggregating stored DataFrames.

## [TestAsyncMethods](entities/class:parrot.tools.working_memory.tests.TestAsyncMethods.md)

Tests the async tool methods that AbstractToolkit will discover.

## [TestErrorHandling](entities/class:parrot.tools.working_memory.tests.TestErrorHandling.md)

Class TestErrorHandling in parrot.tools.working_memory.tests

## [TestFullWorkflow](entities/class:parrot.tools.working_memory.tests.TestFullWorkflow.md)

Class TestFullWorkflow in parrot.tools.working_memory.tests

## [TestImportFromTool](entities/class:parrot.tools.working_memory.tests.TestImportFromTool.md)

Class TestImportFromTool in parrot.tools.working_memory.tests

## [TestMergeAndSummarize](entities/class:parrot.tools.working_memory.tests.TestMergeAn-d7a7962d.md)

Class TestMergeAndSummarize in parrot.tools.working_memory.tests

## [TestPydanticValidation](entities/class:parrot.tools.working_memory.tests.TestPydanti-e41e3216.md)

Ensures the DSL contract rejects malformed inputs.

## [TestAutoInjection](entities/class:parrot.tools.working_memory.tests.test_answer-7606244d.md)

BasicAgent._inject_answer_memory_into_toolkits auto-wires answer_memory.

## [TestRecallByQuery](entities/class:parrot.tools.working_memory.tests.test_answer-d45bfb27.md)

recall_interaction() with substring query lookup.

## [TestRecallByTurnId](entities/class:parrot.tools.working_memory.tests.test_answer-6b07110d.md)

recall_interaction() with exact turn_id lookup.

## [TestRecallValidation](entities/class:parrot.tools.working_memory.tests.test_answer-4a53d23a.md)

recall_interaction() must require at least one of turn_id or query.

## [TestSaveInteraction](entities/class:parrot.tools.working_memory.tests.test_answer-8d329080.md)

save_interaction() tool method.

## [TestBackwardCompat](entities/class:parrot.tools.working_memory.tests.test_generi-a2c0b000.md)

Existing DataFrame tools must be unaffected by FEAT-074 changes.

## [TestCatalogGenericEntries](entities/class:parrot.tools.working_memory.tests.test_generi-0176def8.md)

WorkingMemoryCatalog with generic entries.

## [TestDetectEntryType](entities/class:parrot.tools.working_memory.tests.test_generi-eb325302.md)

Auto-detection heuristic for Python objects.

## [TestDropGeneric](entities/class:parrot.tools.working_memory.tests.test_generi-b1436a4c.md)

drop_stored() works for GenericEntry.

## [TestEntryType](entities/class:parrot.tools.working_memory.tests.test_generi-2080690a.md)

Verify the EntryType enum has all expected values.

## [TestGenericEntrySummary](entities/class:parrot.tools.working_memory.tests.test_generi-60f38324.md)

Type-aware compact_summary for each EntryType.

## [TestGetResult](entities/class:parrot.tools.working_memory.tests.test_generi-345b7e70.md)

get_result() async tool method.

## [TestListMixed](entities/class:parrot.tools.working_memory.tests.test_generi-2ac7e40c.md)

list_stored() with both DataFrame and generic entries.

## [TestSearchStored](entities/class:parrot.tools.working_memory.tests.test_generi-58e8030f.md)

search_stored() async tool method.

## [TestStoreResult](entities/class:parrot.tools.working_memory.tests.test_generi-e3520c9b.md)

store_result() async tool method.

## [TestAnswerMemoryRoundtrip](entities/class:parrot.tools.working_memory.tests.test_integr-e999ac28.md)

Save interaction → recall → import → get_result → verify content.

## [TestBackwardCompatFull](entities/class:parrot.tools.working_memory.tests.test_integr-801eb4cb.md)

Existing TestFullWorkflow-style operations must be unaffected.

## [TestFuzzyRecallRoundtrip](entities/class:parrot.tools.working_memory.tests.test_integr-cf54a1c0.md)

Save 3 interactions → query by substring → import → verify.

## [TestMixedWorkflow](entities/class:parrot.tools.working_memory.tests.test_integr-b37fcf00.md)

Store DataFrame + generic entries together, list, retrieve, drop.

## [TestGating](entities/class:parrot.tools.working_memory.tests.test_thread-4bfef13c.md)

Class TestGating in parrot.tools.working_memory.tests.test_thread_offload

## [TestOffloadRouting](entities/class:parrot.tools.working_memory.tests.test_thread-04e12a68.md)

Class TestOffloadRouting in parrot.tools.working_memory.tests.test_thread_offload

## [TestAsyncMethods](entities/class:parrot.tools.working_memory.tests.test_workin-7bc5321e.md)

Tests the async tool methods that AbstractToolkit will discover.

## [TestErrorHandling](entities/class:parrot.tools.working_memory.tests.test_workin-2a755ed6.md)

Class TestErrorHandling in parrot.tools.working_memory.tests.test_working_memory

## [TestFullWorkflow](entities/class:parrot.tools.working_memory.tests.test_workin-d326914a.md)

Class TestFullWorkflow in parrot.tools.working_memory.tests.test_working_memory

## [TestImportFromTool](entities/class:parrot.tools.working_memory.tests.test_workin-600946f7.md)

Class TestImportFromTool in parrot.tools.working_memory.tests.test_working_memory

## [TestIntegration](entities/class:parrot.tools.working_memory.tests.test_workin-34e589ae.md)

Class TestIntegration in parrot.tools.working_memory.tests.test_working_memory

## [TestMergeAndSummarize](entities/class:parrot.tools.working_memory.tests.test_workin-192b0bf0.md)

Class TestMergeAndSummarize in parrot.tools.working_memory.tests.test_working_memory

## [TestPydanticValidation](entities/class:parrot.tools.working_memory.tests.test_workin-13610d02.md)

Ensures the DSL contract rejects malformed inputs.

## [WorkingMemoryToolkit](entities/class:parrot.tools.working_memory.tool.WorkingMemoryToolkit.md)

Intermediate result store for long-running analytical operations.

## [WorkIQTool](entities/class:parrot.tools.workiq_tool.WorkIQTool.md)

Work IQ MCP credential adapter — queries the Work IQ MCP server via OBO auth.

## [RequestContext](entities/class:parrot.utils.helpers.RequestContext.md)

RequestContext.

## [JsonLdItem](entities/class:parrot.utils.jsonld_extractors.JsonLdItem.md)

A single structured item extracted from a JSON-LD block.

## [BotConfig](entities/class:parrot.voice.handler.BotConfig.md)

Configuration for VoiceBot creation.

## [VoiceChatHandler](entities/class:parrot.voice.handler.VoiceChatHandler.md)

WebSocket handler for voice chat with authentication support.

## [WebSocketConnection](entities/class:parrot.voice.handler.WebSocketConnection.md)

Represents an active WebSocket connection with auth state.

## [AudioFormat](entities/class:parrot.voice.models.AudioFormat.md)

Supported audio formats for voice streaming.

## [SessionState](entities/class:parrot.voice.models.SessionState.md)

Voice session states.

## [VoiceChunk](entities/class:parrot.voice.models.VoiceChunk.md)

Represents a chunk of audio data in a voice stream.

## [VoiceConfig](entities/class:parrot.voice.models.VoiceConfig.md)

Configuration for voice sessions.

## [VoiceMessage](entities/class:parrot.voice.models.VoiceMessage.md)

Represents a complete voice message in a conversation.

## [VoiceProvider](entities/class:parrot.voice.models.VoiceProvider.md)

Supported voice providers.

## [VoiceResponse](entities/class:parrot.voice.models.VoiceResponse.md)

Response from a voice interaction.

## [AbstractTranscriberBackend](entities/class:parrot.voice.transcriber.backend.AbstractTran-ef5b7ffe.md)

Abstract base class for transcription backends.

## [FasterWhisperBackend](entities/class:parrot.voice.transcriber.faster_whisper_backe-53cf95c9.md)

Local GPU-accelerated transcription using Faster Whisper.

## [TranscriberBackend](entities/class:parrot.voice.transcriber.models.TranscriberBackend.md)

Available transcription backends.

## [TranscriptionResult](entities/class:parrot.voice.transcriber.models.TranscriptionResult.md)

Result of voice transcription.

## [VoiceTranscriberConfig](entities/class:parrot.voice.transcriber.models.VoiceTranscriberConfig.md)

Configuration for voice transcription.

## [MoonshineSTTBackend](entities/class:parrot.voice.transcriber.moonshine_backend.Mo-218a5602.md)

Sub-second speech-to-text backend using the Moonshine ONNX models.

## [OpenAIWhisperBackend](entities/class:parrot.voice.transcriber.openai_backend.OpenA-9bd52294.md)

Cloud-based transcription using OpenAI Whisper API.

## [VoiceTranscriber](entities/class:parrot.voice.transcriber.transcriber.VoiceTranscriber.md)

Voice transcription service.

## [AbstractTTSBackend](entities/class:parrot.voice.tts.backend.AbstractTTSBackend.md)

Abstract base class for text-to-speech synthesis backends.

## [GoogleTTSBackend](entities/class:parrot.voice.tts.google_backend.GoogleTTSBackend.md)

TTS backend that wraps ``GoogleGenAIClient.generate_speech``.

## [SynthesisResult](entities/class:parrot.voice.tts.models.SynthesisResult.md)

Result of a text-to-speech synthesis call.

## [TTSConfig](entities/class:parrot.voice.tts.models.TTSConfig.md)

Configuration for text-to-speech synthesis.

## [SupertonicTTSBackend](entities/class:parrot.voice.tts.supertonic_backend.Supertoni-7283847c.md)

TTS backend that wraps the Supertonic ONNX speech model.

## [Style](entities/class:parrot.voice.tts.supertonic_inference.Style.md)

A speaker style: the two conditioning tensors Supertonic consumes.

## [SupertonicONNXBackend](entities/class:parrot.voice.tts.supertonic_inference.Superto-fa2b41ee.md)

:class:`SupertonicTTSBackend` wired for the real Supertonic-3 weights.

## [SupertonicPipeline](entities/class:parrot.voice.tts.supertonic_inference.Superto-96532e58.md)

Runs the Supertonic-3 four-graph pipeline and returns raw PCM.

## [UnicodeProcessor](entities/class:parrot.voice.tts.supertonic_inference.UnicodeProcessor.md)

Codepoint-based text tokeniser for Supertonic.

## [VoiceSynthesizer](entities/class:parrot.voice.tts.synthesizer.VoiceSynthesizer.md)

Text-to-speech synthesis service.

## [AudioFormWSHandler](entities/class:parrot_formdesigner.api.audio_ws.AudioFormWSHandler.md)

WebSocket handler for interactive audio form sessions.

## [FormAPIHandler](entities/class:parrot_formdesigner.api.handlers.FormAPIHandler.md)

Serves JSON REST API endpoints for form management.

## [AddField](entities/class:parrot_formdesigner.api.operations.AddField.md)

Insert a new field into an existing section.

## [AddSection](entities/class:parrot_formdesigner.api.operations.AddSection.md)

Insert a new section. Optional ``position`` indexes the section list.

## [DuplicateField](entities/class:parrot_formdesigner.api.operations.DuplicateField.md)

Duplicate a field within the same (or another) section.

## [MoveField](entities/class:parrot_formdesigner.api.operations.MoveField.md)

Move a field across (or within) sections.

## [OperationError](entities/class:parrot_formdesigner.api.operations.OperationError.md)

Per-op apply failure carried back to the HTTP layer.

## [OperationsEnvelope](entities/class:parrot_formdesigner.api.operations.OperationsEnvelope.md)

Top-level body shape for ``PATCH .../operations``.

## [RemoveField](entities/class:parrot_formdesigner.api.operations.RemoveField.md)

Remove a field from a section.

## [UpdateField](entities/class:parrot_formdesigner.api.operations.UpdateField.md)

Apply RFC 7396 merge-patch to a single field.

## [UpdateFormMeta](entities/class:parrot_formdesigner.api.operations.UpdateFormMeta.md)

Apply RFC 7396 merge-patch to the form-level meta.

## [UpdateSectionMeta](entities/class:parrot_formdesigner.api.operations.UpdateSectionMeta.md)

Apply RFC 7396 merge-patch to a section's metadata.

## [AudioAnswer](entities/class:parrot_formdesigner.audio.models.AudioAnswer.md)

An answer to a single audio question.

## [AudioFormManifest](entities/class:parrot_formdesigner.audio.models.AudioFormManifest.md)

Session manifest returned by AudioFormRenderer.render().

## [AudioQuestion](entities/class:parrot_formdesigner.audio.models.AudioQuestion.md)

A single question in the audio form session.

## [AudioSessionConfig](entities/class:parrot_formdesigner.audio.models.AudioSessionConfig.md)

Configuration for an audio form session.

## [AudioSessionState](entities/class:parrot_formdesigner.audio.models.AudioSessionState.md)

Server-side state for an active audio form session.

## [VoiceMode](entities/class:parrot_formdesigner.audio.models.VoiceMode.md)

How a question participates in the audio form flow.

## [FieldControlMetadata](entities/class:parrot_formdesigner.controls.registry.FieldCo-dab72ae6.md)

Metadata describing a single form-control entry for the toolbar.

## [ApiKeyAuth](entities/class:parrot_formdesigner.core.auth.ApiKeyAuth.md)

API key authentication resolved from an environment variable.

## [BearerAuth](entities/class:parrot_formdesigner.core.auth.BearerAuth.md)

Bearer token authentication resolved from an environment variable.

## [NoAuth](entities/class:parrot_formdesigner.core.auth.NoAuth.md)

No authentication — default, backward-compatible.

## [ConditionOperator](entities/class:parrot_formdesigner.core.constraints.ConditionOperator.md)

Operators for field conditions in dependency rules.

## [DependencyOperation](entities/class:parrot_formdesigner.core.constraints.Dependen-8e3c58ca.md)

An operation that computes or assigns a value from referenced field values.

## [DependencyRule](entities/class:parrot_formdesigner.core.constraints.DependencyRule.md)

Rule controlling conditional visibility/behavior of a field or section.

## [FieldCondition](entities/class:parrot_formdesigner.core.constraints.FieldCondition.md)

A single condition referencing another field's value.

## [FieldConstraints](entities/class:parrot_formdesigner.core.constraints.FieldConstraints.md)

Constraints applied to a form field for validation.

## [PostDependency](entities/class:parrot_formdesigner.core.constraints.PostDependency.md)

A forward dependency: how a field's answered value affects a later field.

## [EventResolution](entities/class:parrot_formdesigner.core.events.EventResolution.md)

Return value of a form lifecycle event handler.

## [FormEventAbort](entities/class:parrot_formdesigner.core.events.FormEventAbort.md)

Cancels a ``before*`` lifecycle event with a typed user-facing response.

## [FormEventBinding](entities/class:parrot_formdesigner.core.events.FormEventBinding.md)

Declaración por-formulario de un binding evento → handler.

## [FormEventContext](entities/class:parrot_formdesigner.core.events.FormEventContext.md)

Payload passed to a form lifecycle event handler.

## [FormEventsConfig](entities/class:parrot_formdesigner.core.events.FormEventsConfig.md)

Mapa declarado por-formulario de event → binding.

## [VisitEventContext](entities/class:parrot_formdesigner.core.events.VisitEventContext.md)

Payload passed to a visit lifecycle event handler (FEAT-329).

## [FieldOption](entities/class:parrot_formdesigner.core.options.FieldOption.md)

A single option in a select or multi-select field.

## [OptionsSource](entities/class:parrot_formdesigner.core.options.OptionsSource.md)

Dynamic options source configuration for fetching options at runtime.

## [PartialFormData](entities/class:parrot_formdesigner.core.partial.PartialFormData.md)

Ephemeral partial form answer cache entry.

## [FormField](entities/class:parrot_formdesigner.core.schema.FormField.md)

A single field within a form section.

## [FormMetadataField](entities/class:parrot_formdesigner.core.schema.FormMetadataField.md)

Declared contextual metadata captured on every form submission.

## [FormSchema](entities/class:parrot_formdesigner.core.schema.FormSchema.md)

The canonical representation of a complete form.

## [FormSection](entities/class:parrot_formdesigner.core.schema.FormSection.md)

A logical grouping of fields within a form.

## [FormSubsection](entities/class:parrot_formdesigner.core.schema.FormSubsection.md)

A visual sub-grouping of fields within a section.

## [FormType](entities/class:parrot_formdesigner.core.schema.FormType.md)

Discriminator for the form's structural type.

## [RenderWarning](entities/class:parrot_formdesigner.core.schema.RenderWarning.md)

Warning emitted when a renderer uses degraded fallback for a field type.

## [RenderedForm](entities/class:parrot_formdesigner.core.schema.RenderedForm.md)

Output of a form renderer.

## [SubmitAction](entities/class:parrot_formdesigner.core.schema.SubmitAction.md)

Defines what happens when a form is submitted.

## [FieldSizeHint](entities/class:parrot_formdesigner.core.style.FieldSizeHint.md)

Size hints for individual form fields.

## [FieldStyleHint](entities/class:parrot_formdesigner.core.style.FieldStyleHint.md)

Per-field style customization hints.

## [LayoutType](entities/class:parrot_formdesigner.core.style.LayoutType.md)

Available layout modes for form rendering.

## [StyleSchema](entities/class:parrot_formdesigner.core.style.StyleSchema.md)

Presentation style configuration for a form.

## [FieldType](entities/class:parrot_formdesigner.core.types.FieldType.md)

Supported form field types.

## [JsonSchemaExtractor](entities/class:parrot_formdesigner.extractors.jsonschema.Jso-d85cc9af.md)

Converts JSON Schema dicts into FormSchema instances.

## [PydanticExtractor](entities/class:parrot_formdesigner.extractors.pydantic.Pydan-7b7f066c.md)

Extracts FormSchema from Pydantic v2 BaseModel classes.

## [ToolExtractor](entities/class:parrot_formdesigner.extractors.tool.ToolExtractor.md)

Extracts FormSchema from AbstractTool.args_schema.

## [YamlExtractor](entities/class:parrot_formdesigner.extractors.yaml.YamlExtractor.md)

Parses YAML form definitions into FormSchema instances.

## [AdaptiveCardRenderer](entities/class:parrot_formdesigner.renderers.adaptive_card.A-28604cc6.md)

Renders FormSchema as Adaptive Card JSON for MS Teams.

## [AudioFormRenderer](entities/class:parrot_formdesigner.renderers.audio.AudioFormRenderer.md)

Renders a FormSchema as an AudioFormManifest (sequential questions).

## [AbstractFormRenderer](entities/class:parrot_formdesigner.renderers.base.AbstractFo-3de21820.md)

Abstract base for form renderers.

## [FallbackRenderer](entities/class:parrot_formdesigner.renderers.base.FallbackRenderer.md)

Concrete fallback emitter — degraded representation.

## [FieldRenderer](entities/class:parrot_formdesigner.renderers.base.FieldRenderer.md)

Per-target field renderer. One concrete impl per (FieldType, output target).

## [AudioFieldRenderer](entities/class:parrot_formdesigner.renderers.fields.audio.Au-24c301f0.md)

HTML5 field renderer for FieldType.AUDIO fields.

## [HTML5Renderer](entities/class:parrot_formdesigner.renderers.html5.HTML5Renderer.md)

Renders FormSchema as an HTML5 <form> fragment.

## [JsonSchemaRenderer](entities/class:parrot_formdesigner.renderers.jsonschema.Json-4f7aea49.md)

Renders FormSchema as a structural JSON Schema with x- extensions.

## [PdfRenderer](entities/class:parrot_formdesigner.renderers.pdf.PdfRenderer.md)

Render a ``FormSchema`` as a fillable PDF (AcroForm).

## [FormActionCallback](entities/class:parrot_formdesigner.renderers.telegram.models-322c470d.md)

Callback data for form-level actions (submit, cancel).

## [FormFieldCallback](entities/class:parrot_formdesigner.renderers.telegram.models-815776b8.md)

Compact callback data for inline form field selections.

## [TelegramFormPayload](entities/class:parrot_formdesigner.renderers.telegram.models-0c7f316b.md)

Output of TelegramRenderer.render(), stored in RenderedForm.content.

## [TelegramFormStep](entities/class:parrot_formdesigner.renderers.telegram.models-60f9d336.md)

A single step in an inline keyboard form conversation.

## [TelegramRenderMode](entities/class:parrot_formdesigner.renderers.telegram.models-8cb12938.md)

Rendering mode for Telegram forms.

## [TelegramRenderer](entities/class:parrot_formdesigner.renderers.telegram.render-2644d4fe.md)

Renders FormSchema as Telegram interactions.

## [FormFilling](entities/class:parrot_formdesigner.renderers.telegram.router-4b88ce85.md)

FSM state for an active form conversation.

## [TelegramFormRouter](entities/class:parrot_formdesigner.renderers.telegram.router-fe3ff672.md)

aiogram Router that handles form conversations.

## [XFormsRenderer](entities/class:parrot_formdesigner.renderers.xforms.XFormsRenderer.md)

Render a ``FormSchema`` as an XForms 1.1 (W3C) document.

## [AuthContext](entities/class:parrot_formdesigner.services.auth_context.AuthContext.md)

Runtime auth context constructed by the aiohttp handler per request.

## [AbstractBlobStorage](entities/class:parrot_formdesigner.services.blob_storage.Abs-977a5d34.md)

Abstract async blob storage.

## [BlobMetadata](entities/class:parrot_formdesigner.services.blob_storage.BlobMetadata.md)

Metadata associated with a persisted blob.

## [BlobRejectedError](entities/class:parrot_formdesigner.services.blob_storage.Blo-a7e53a90.md)

Raised by ``AbstractBlobStorage.pre_persist_hook`` to abort a ``put``.

## [GCSBlobStorage](entities/class:parrot_formdesigner.services.blob_storage.GCS-bb9ecb20.md)

GCS blob storage backed by ``navigator.utils.file.gcs.GCSFileManager``.

## [LocalBlobStorage](entities/class:parrot_formdesigner.services.blob_storage.Loc-abb045d4.md)

Local filesystem blob storage backed by ``LocalFileManager``.

## [PrePersistContext](entities/class:parrot_formdesigner.services.blob_storage.Pre-39562730.md)

Context passed to ``AbstractBlobStorage.pre_persist_hook`` before writing.

## [S3BlobStorage](entities/class:parrot_formdesigner.services.blob_storage.S3B-3465d7ce.md)

S3 blob storage backed by ``navigator.utils.file.s3.S3FileManager``.

## [TempBlobStorage](entities/class:parrot_formdesigner.services.blob_storage.Tem-0b43194e.md)

Ephemeral blob storage backed by ``TempFileManager``.

## [FormCache](entities/class:parrot_formdesigner.services.cache.FormCache.md)

In-memory TTL cache for FormSchema with optional Redis backend.

## [FieldsyncSchemaManager](entities/class:parrot_formdesigner.services.fieldsync_schema-30309ea5.md)

Apply the canonical ``fieldsync`` DDL to a Postgres database.

## [FormVersionService](entities/class:parrot_formdesigner.services.form_version.For-7ef73e10.md)

Immutable semver publishing service for ``FormSchema`` objects.

## [VersionMeta](entities/class:parrot_formdesigner.services.form_version.VersionMeta.md)

Metadata record for a published form version.

## [ForwardResult](entities/class:parrot_formdesigner.services.forwarder.ForwardResult.md)

Result of a submission forwarding attempt.

## [SubmissionForwarder](entities/class:parrot_formdesigner.services.forwarder.Submis-1ee87fa0.md)

Forward form submission data to configured SubmitAction endpoints.

## [MetadataCallbackInput](entities/class:parrot_formdesigner.services.metadata_callbac-44ee7b1a.md)

Payload delivered to a registered metadata-callback coroutine.

## [MetadataCallbackOutput](entities/class:parrot_formdesigner.services.metadata_callbac-74a4561e.md)

Return value from a registered metadata-callback coroutine.

## [MetadataResolutionError](entities/class:parrot_formdesigner.services.metadata_enriche-1111cafe.md)

Raised when a required metadata field cannot be resolved.

## [OptionsLoader](entities/class:parrot_formdesigner.services.options_loader.O-f3805ab6.md)

Async service that fetches and caches ``FieldOption`` lists.

## [OrgGraph](entities/class:parrot_formdesigner.services.org_graph.OrgGraph.md)

Full organizational graph for a tenant.

## [OrgGraphService](entities/class:parrot_formdesigner.services.org_graph.OrgGraphService.md)

Build in-memory org-graph trees from navigator-auth + networkninja.

## [OrgNode](entities/class:parrot_formdesigner.services.org_graph.OrgNode.md)

A single node in the organizational hierarchy.

## [PartialSaveStore](entities/class:parrot_formdesigner.services.partial_saves.Pa-25c290dd.md)

Redis-backed ephemeral storage for partial form answers.

## [DuplicateAccountingCodeError](entities/class:parrot_formdesigner.services.project_service.-be84f690.md)

Raised when ``(client_id, accounting_code)`` already exists.

## [Project](entities/class:parrot_formdesigner.services.project_service.Project.md)

A project stored in ``fieldsync.projects``.

## [ProjectNotFoundError](entities/class:parrot_formdesigner.services.project_service.-9f581004.md)

Raised when a project lookup returns no row.

## [ProjectService](entities/class:parrot_formdesigner.services.project_service.-adc93116.md)

CRUD service for ``fieldsync.projects`` and Workday mappings.

## [WorkdayCostCenterMapping](entities/class:parrot_formdesigner.services.project_service.-3626fc84.md)

Mapping from an internal project to a Workday cost center code.

## [QuestionBankService](entities/class:parrot_formdesigner.services.question_bank.Qu-9a66e143.md)

Tenant-scoped service for managing reusable field definitions.

## [ReusableField](entities/class:parrot_formdesigner.services.question_bank.Re-08f4891a.md)

A single entry in the tenant's QuestionBank.

## [ReusableFieldRef](entities/class:parrot_formdesigner.services.question_bank.Re-3f262d24.md)

A reference to a ``ReusableField`` with optional field-level overrides.

## [PermissionRecord](entities/class:parrot_formdesigner.services.rbac.PermissionRecord.md)

A compiled permission entry (result of assign_role).

## [Policy](entities/class:parrot_formdesigner.services.rbac.Policy.md)

Declarative ABAC/PBAC policy — mirrors the nav-auth YAML format.

## [RBACContext](entities/class:parrot_formdesigner.services.rbac.RBACContext.md)

Runtime RBAC context projected for a user in a program.

## [RBACScope](entities/class:parrot_formdesigner.services.rbac.RBACScope.md)

Vocabulary of RBAC scopes that compile to ABAC policies.

## [RBACService](entities/class:parrot_formdesigner.services.rbac.RBACService.md)

Manage ABAC/PBAC policies in ``fieldsync.auth_policies`` + project context.

## [FormAlreadyExistsError](entities/class:parrot_formdesigner.services.registry.FormAlr-547f857f.md)

Raised when registering a form whose ``form_id`` is already taken.

## [FormRegistry](entities/class:parrot_formdesigner.services.registry.FormRegistry.md)

Thread-safe, multi-tenant registry for FormSchema objects.

## [FormStorage](entities/class:parrot_formdesigner.services.registry.FormStorage.md)

Abstract base class for form persistence backends.

## [RemoteResponseResolver](entities/class:parrot_formdesigner.services.remote_response_-359bc77c.md)

Resolve REMOTE_RESPONSE fields by calling an external API.

## [RemoteResponseResult](entities/class:parrot_formdesigner.services.remote_response_-5264e57d.md)

Result of a ``RemoteResponseResolver.resolve()`` call.

## [RemoteResponseSpec](entities/class:parrot_formdesigner.services.remote_response_-7ee7fe8f.md)

Configuration for a REMOTE_RESPONSE field embedded in ``FormField.meta``.

## [AdditionalArg](entities/class:parrot_formdesigner.services.rest_field_resol-c6fe19c5.md)

Extra argument forwarded alongside the uploaded content.

## [CallbackRestFieldSpec](entities/class:parrot_formdesigner.services.rest_field_resol-cf2f9d6a.md)

Spec for mode='callback': invokes a pre-registered Python coroutine.

## [ConfigurationError](entities/class:parrot_formdesigner.services.rest_field_resol-a798a12c.md)

Raised when resolver cannot determine the internal base URL.

## [InternalRestFieldSpec](entities/class:parrot_formdesigner.services.rest_field_resol-f01ccc08.md)

Spec for mode='internal': calls a relative path on the running server.

## [RemoteRestFieldSpec](entities/class:parrot_formdesigner.services.rest_field_resol-44445fe9.md)

Spec for mode='remote': calls an absolute external URL.

## [RestCallbackInput](entities/class:parrot_formdesigner.services.rest_field_resol-40adec3f.md)

Payload delivered to a registered callback coroutine.

## [RestCallbackOutput](entities/class:parrot_formdesigner.services.rest_field_resol-935f265f.md)

Return value from a registered callback coroutine.

## [RestFieldResolver](entities/class:parrot_formdesigner.services.rest_field_resol-6081ca4b.md)

Dispatch FieldType.REST field uploads by mode.

## [RestFieldResult](entities/class:parrot_formdesigner.services.rest_field_resol-701fc078.md)

Output of ``RestFieldResolver.resolve()``.

## [RuleEvaluator](entities/class:parrot_formdesigner.services.rule_evaluator.R-658e96ee.md)

Authoritative server-side rule evaluator for FormSchema conditional sections.

## [RuleResolution](entities/class:parrot_formdesigner.services.rule_evaluator.R-6f45637d.md)

Result of evaluating all conditional-section rules for a form submission.

## [PostgresFormStorage](entities/class:parrot_formdesigner.services.storage.Postgres-6fe71642.md)

Persist FormSchema objects in a PostgreSQL table using asyncpg.

## [FormSubmission](entities/class:parrot_formdesigner.services.submissions.Form-a3c0538f.md)

Record of a single form data submission.

## [FormSubmissionStorage](entities/class:parrot_formdesigner.services.submissions.Form-1cb46fd2.md)

Persist form submissions in a PostgreSQL table.

## [FormValidator](entities/class:parrot_formdesigner.services.validators.FormValidator.md)

Platform-agnostic validator for FormSchema data.

## [ValidationResult](entities/class:parrot_formdesigner.services.validators.Valid-451080c7.md)

Result of validating a form submission.

## [DuplicateVenueError](entities/class:parrot_formdesigner.services.venue_service.Du-ba9241dd.md)

Raised when a UNIQUE constraint on a site/location is violated.

## [Location](entities/class:parrot_formdesigner.services.venue_service.Location.md)

A concrete work point inside a Site — a kiosk or any spot in the store.

## [LocationNotFoundError](entities/class:parrot_formdesigner.services.venue_service.Lo-4c40eacc.md)

Raised when a location lookup returns no row.

## [Site](entities/class:parrot_formdesigner.services.venue_service.Site.md)

An intermediate work-area grouping inside a Store.

## [SiteNotFoundError](entities/class:parrot_formdesigner.services.venue_service.Si-ccc54bfb.md)

Raised when a site lookup returns no row.

## [VenueService](entities/class:parrot_formdesigner.services.venue_service.Ve-7878244d.md)

CRUD service for ``fieldsync.sites`` and ``fieldsync.locations``.

## [WorkdayIdentitySyncAdapter](entities/class:parrot_formdesigner.services.workday_sync.Wor-ccd93e44.md)

Stub de sincronización de identidades hacia Workday.

## [CreateFormInput](entities/class:parrot_formdesigner.tools.create_form.CreateFormInput.md)

Input schema for the create_form tool.

## [CreateFormTool](entities/class:parrot_formdesigner.tools.create_form.CreateFormTool.md)

Create a FormSchema from a natural language prompt using an LLM.

## [DatabaseFormInput](entities/class:parrot_formdesigner.tools.database_form.Datab-af32b63d.md)

Input schema for DatabaseFormTool — service-aware.

## [DatabaseFormTool](entities/class:parrot_formdesigner.tools.database_form.Datab-a0a83fb1.md)

Load a form definition from a configured form-source service into a FormSchema.

## [EditToolkit](entities/class:parrot_formdesigner.tools.edit_toolkit.EditToolkit.md)

Toolkit exposing FormSchema inspection and mutation as LLM-callable tools.

## [RequestFormInput](entities/class:parrot_formdesigner.tools.request_form.Reques-75470bea.md)

Input schema for the request_form tool.

## [RequestFormTool](entities/class:parrot_formdesigner.tools.request_form.RequestFormTool.md)

Platform-agnostic tool that requests a form to collect missing parameters.

## [AbstractFormService](entities/class:parrot_formdesigner.tools.services.abstract.A-3fc0cb16.md)

Strategy interface for sourcing a FormSchema from any origin.

## [ImportDiffEntry](entities/class:parrot_formdesigner.tools.services.networknin-bc2b325d.md)

Per-field entry in an ImportDiffReport.

## [ImportDiffReport](entities/class:parrot_formdesigner.tools.services.networknin-847ef745.md)

Aggregate report for a single networkninja form import.

## [NetworkninjaFormService](entities/class:parrot_formdesigner.tools.services.networknin-7d7ce2fd.md)

NetworkNinja PostgreSQL form-source service.

## [FormPageHandler](entities/class:parrot_formdesigner.ui.handlers.FormPageHandler.md)

Serves HTML pages for the form builder UI.

## [TelegramWebAppHandler](entities/class:parrot_formdesigner.ui.telegram.TelegramWebAppHandler.md)

Serves forms as Telegram WebApps and handles REST fallback submissions.

## [AudioLoader](entities/class:parrot_loaders.audio.AudioLoader.md)

Generating transcripts from local Audio.

## [BasePDF](entities/class:parrot_loaders.basepdf.BasePDF.md)

Base Abstract loader for all PDF-file Loaders.

## [BaseVideoLoader](entities/class:parrot_loaders.basevideo.BaseVideoLoader.md)

Generating Video transcripts from Videos.

## [CSVLoader](entities/class:parrot_loaders.csv.CSVLoader.md)

CSV Loader that creates one JSON Document per row using pandas.

## [DatabaseLoader](entities/class:parrot_loaders.database.DatabaseLoader.md)

Load rows from a database table as RAG Documents.

## [DocumentConverterLoader](entities/class:parrot_loaders.doc_converter.DocumentConverterLoader.md)

Load PDF, DOCX, and PPTX files using Docling and return Document objects.

## [MSWordLoader](entities/class:parrot_loaders.docx.MSWordLoader.md)

Load Microsoft Docx as Parrot Documents.

## [EpubLoader](entities/class:parrot_loaders.epubloader.EpubLoader.md)

EPUB loader that extracts clean Markdown (or plain text) from chapters/sections.

## [ExcelLoader](entities/class:parrot_loaders.excel.ExcelLoader.md)

Excel loader that converts an Excel workbook (or DataFrame) into Documents.

## [APIDataSource](entities/class:parrot_loaders.extractors.api_source.APIDataSource.md)

Base class for REST API data extraction.

## [ExtractDataSource](entities/class:parrot_loaders.extractors.base.ExtractDataSource.md)

Abstract base class for structured data extraction.

## [ExtractedRecord](entities/class:parrot_loaders.extractors.base.ExtractedRecord.md)

A single extracted record with its raw data and metadata.

## [ExtractionResult](entities/class:parrot_loaders.extractors.base.ExtractionResult.md)

Result of an extraction operation.

## [CSVDataSource](entities/class:parrot_loaders.extractors.csv_source.CSVDataSource.md)

Extract structured records from CSV files.

## [DataSourceFactory](entities/class:parrot_loaders.extractors.factory.DataSourceFactory.md)

Resolve source names to ExtractDataSource implementations.

## [JSONDataSource](entities/class:parrot_loaders.extractors.json_source.JSONDataSource.md)

Extract structured records from JSON files or arrays.

## [RecordsDataSource](entities/class:parrot_loaders.extractors.records_source.Reco-7a817a76.md)

Wrap an in-memory list[dict] as a data source.

## [SQLDataSource](entities/class:parrot_loaders.extractors.sql_source.SQLDataSource.md)

Extract structured records from SQL queries.

## [FilePlugin](entities/class:parrot_loaders.files.abstract.FilePlugin.md)

FilePlugin is a base class for Open Files.

## [HTMLFile](entities/class:parrot_loaders.files.html.HTMLFile.md)

A class to handle HTML files asynchronously.

## [TextFile](entities/class:parrot_loaders.files.text.TextFile.md)

A class to handle text files asynchronously.

## [HTMLLoader](entities/class:parrot_loaders.html.HTMLLoader.md)

Loader for HTML files to convert into Parrot Documents.

## [ImageLoader](entities/class:parrot_loaders.image.ImageLoader.md)

OCR-based image loader with layout-aware text extraction.

## [ImageUnderstandingLoader](entities/class:parrot_loaders.imageunderstanding.ImageUnders-5ece73f0.md)

Image analysis loader using Google GenAI for understanding image content.

## [MarkdownLoader](entities/class:parrot_loaders.markdown.MarkdownLoader.md)

Universal Document Loader using MarkItDown library.

## [OCRBackend](entities/class:parrot_loaders.ocr.base.OCRBackend.md)

Protocol for OCR backends.

## [EasyOCRBackend](entities/class:parrot_loaders.ocr.easyocr_backend.EasyOCRBackend.md)

OCR backend using EasyOCR with optional GPU acceleration.

## [HeuristicLayoutAnalyzer](entities/class:parrot_loaders.ocr.layout.HeuristicLayoutAnalyzer.md)

Geometry-based layout analyzer that requires no ML model.

## [LayoutLMv3Analyzer](entities/class:parrot_loaders.ocr.layoutlm.LayoutLMv3Analyzer.md)

Semantic layout analyzer using LayoutLMv3 token classification.

## [LayoutLine](entities/class:parrot_loaders.ocr.models.LayoutLine.md)

A horizontal line of text blocks at approximately the same y-coordinate.

## [LayoutResult](entities/class:parrot_loaders.ocr.models.LayoutResult.md)

Complete layout analysis result for a single image.

## [OCRBlock](entities/class:parrot_loaders.ocr.models.OCRBlock.md)

A single text region detected by OCR.

## [PaddleOCRBackend](entities/class:parrot_loaders.ocr.paddle.PaddleOCRBackend.md)

OCR backend using PaddleOCR.

## [TesseractBackend](entities/class:parrot_loaders.ocr.tesseract.TesseractBackend.md)

OCR backend using Tesseract via pytesseract.

## [PDFLoader](entities/class:parrot_loaders.pdf.PDFLoader.md)

Advanced PDF Loader using PyMuPDF (fitz).

## [PDFMarkdownLoader](entities/class:parrot_loaders.pdfmark.PDFMarkdownLoader.md)

Loader for PDF files converted content to markdown.

## [PDFTablesLoader](entities/class:parrot_loaders.pdftables.PDFTablesLoader.md)

Specialized loader for extracting tables from PDF files.

## [PowerPointLoader](entities/class:parrot_loaders.ppt.PowerPointLoader.md)

Enhanced PowerPoint loader with multiple backends.

## [QAFileLoader](entities/class:parrot_loaders.qa.QAFileLoader.md)

Question and Answers File based on Excel, coverted to Parrot Documents.

## [TextLoader](entities/class:parrot_loaders.txt.TextLoader.md)

Loader for Text-based Files.

## [VideoLoader](entities/class:parrot_loaders.video.VideoLoader.md)

Generating Video transcripts from URL Videos.

## [VideoLocalLoader](entities/class:parrot_loaders.videolocal.VideoLocalLoader.md)

Generating Video transcripts from local Videos.

## [VideoUnderstandingLoader](entities/class:parrot_loaders.videounderstanding.VideoUnders-5d2bfd53.md)

Video analysis loader using Google GenAI for understanding video content.

## [VimeoLoader](entities/class:parrot_loaders.vimeo.VimeoLoader.md)

Loader for Vimeo videos.

## [WebDriverPool](entities/class:parrot_loaders.web.WebDriverPool.md)

Async WebDriver pool for efficient browser management.

## [WebLoader](entities/class:parrot_loaders.web.WebLoader.md)

Load web pages and extract HTML + Markdown + structured bits (videos/nav/tables).

## [WebScrapingLoader](entities/class:parrot_loaders.webscraping.WebScrapingLoader.md)

Load web pages via WebScrapingToolkit and convert to Documents.

## [YoutubeLoader](entities/class:parrot_loaders.youtube.YoutubeLoader.md)

Loader for Youtube videos.

## [AbstractPipeline](entities/class:parrot_pipelines.abstract.AbstractPipeline.md)

Abstract base class for all pipelines.

## [AbstractDetector](entities/class:parrot_pipelines.detector.AbstractDetector.md)

Abstract base class for all detectors.

## [PlanogramComplianceHandler](entities/class:parrot_pipelines.handlers.planogram_complianc-39bde4a6.md)

REST handler for planogram compliance analysis with async job support.

## [EndcapGeometry](entities/class:parrot_pipelines.models.EndcapGeometry.md)

Configurable endcap geometry parameters

## [PlanogramConfig](entities/class:parrot_pipelines.models.PlanogramConfig.md)

Complete configuration for planogram analysis pipeline.

## [GridDetector](entities/class:parrot_pipelines.planogram.grid.detector.GridDetector.md)

Orchestrates parallel per-cell LLM detection calls.

## [HorizontalBands](entities/class:parrot_pipelines.planogram.grid.horizontal_ba-f04f8ffc.md)

Grid strategy that decomposes the ROI into horizontal shelf bands.

## [CellResultMerger](entities/class:parrot_pipelines.planogram.grid.merger.CellRe-3f25144b.md)

Merges per-cell detection results into a unified product list.

## [DetectionGridConfig](entities/class:parrot_pipelines.planogram.grid.models.Detect-04458a74.md)

Configuration for detection grid decomposition.

## [GridCell](entities/class:parrot_pipelines.planogram.grid.models.GridCell.md)

A single cell in the detection grid.

## [GridType](entities/class:parrot_pipelines.planogram.grid.models.GridType.md)

Supported grid decomposition strategies.

## [AbstractGridStrategy](entities/class:parrot_pipelines.planogram.grid.strategy.Abst-6afc9e96.md)

Base class for grid decomposition strategies.

## [NoGrid](entities/class:parrot_pipelines.planogram.grid.strategy.NoGrid.md)

Default grid strategy — no decomposition.

## [PlanogramCompliancePipeline](entities/class:parrot_pipelines.planogram.legacy.PlanogramCo-7e7383b0.md)

Pipeline for planogram compliance checking.

## [RetailDetector](entities/class:parrot_pipelines.planogram.legacy.RetailDetector.md)

Reference-guided Phase-1 detector.

## [PlanogramCompliance](entities/class:parrot_pipelines.planogram.plan.PlanogramCompliance.md)

Pure-LLM Planogram Compliance Pipeline with Composable Delegation.

## [AbstractPlanogramType](entities/class:parrot_pipelines.planogram.types.abstract.Abs-6f05e6c7.md)

Contract for planogram type composables.

## [EndcapBacklitMultitier](entities/class:parrot_pipelines.planogram.types.endcap_backl-242cdca3.md)

Planogram type for backlit multi-tier endcap displays.

## [EndcapNoShelvesPromotional](entities/class:parrot_pipelines.planogram.types.endcap_no_sh-b090afc3.md)

Planogram type for shelf-less promotional endcap displays.

## [GraphicPanelDisplay](entities/class:parrot_pipelines.planogram.types.graphic_pane-9e807c62.md)

Composable type for graphic-panel / signage endcap compliance.

## [ProductCounter](entities/class:parrot_pipelines.planogram.types.product_coun-3aa409d2.md)

Planogram type for product-on-counter/podium displays.

## [ProductOnShelves](entities/class:parrot_pipelines.planogram.types.product_on_s-b851120a.md)

Planogram type for product-on-shelves displays.

## [ArangoDBSearchTool](entities/class:parrot_tools.arangodbsearch.ArangoDBSearchTool.md)

ArangoDB Vector Search Tool.

## [ArangoSearchArgs](entities/class:parrot_tools.arangodbsearch.ArangoSearchArgs.md)

Arguments schema for ArangoDB search operations.

## [SearchType](entities/class:parrot_tools.arangodbsearch.SearchType.md)

Supported search types.

## [ArxivSearchArgsSchema](entities/class:parrot_tools.arxiv_tool.ArxivSearchArgsSchema.md)

Schema for arXiv search arguments.

## [ArxivTool](entities/class:parrot_tools.arxiv_tool.ArxivTool.md)

Tool for searching academic papers on arXiv.org.

## [CloudWatchToolkit](entities/class:parrot_tools.aws.cloudwatch.CloudWatchToolkit.md)

Toolkit for querying AWS CloudWatch logs and metrics.

## [DescribeAlarmsInput](entities/class:parrot_tools.aws.cloudwatch.DescribeAlarmsInput.md)

Input for listing CloudWatch alarms.

## [GetLogEventsInput](entities/class:parrot_tools.aws.cloudwatch.GetLogEventsInput.md)

Input for getting log events from a specific stream.

## [GetMetricsInput](entities/class:parrot_tools.aws.cloudwatch.GetMetricsInput.md)

Input for retrieving CloudWatch metric statistics.

## [ListLogGroupsInput](entities/class:parrot_tools.aws.cloudwatch.ListLogGroupsInput.md)

Input for listing CloudWatch log groups.

## [ListLogStreamsInput](entities/class:parrot_tools.aws.cloudwatch.ListLogStreamsInput.md)

Input for listing log streams in a log group.

## [LogSummaryInput](entities/class:parrot_tools.aws.cloudwatch.LogSummaryInput.md)

Input for getting summarized log events.

## [PutMetricDataInput](entities/class:parrot_tools.aws.cloudwatch.PutMetricDataInput.md)

Input for publishing custom metric data.

## [QueryLogsInput](entities/class:parrot_tools.aws.cloudwatch.QueryLogsInput.md)

Input for CloudWatch Logs Insights query.

## [CreateSnapshotInput](entities/class:parrot_tools.aws.documentdb.CreateSnapshotInput.md)

Input for creating a manual DocumentDB cluster snapshot.

## [DescribeEventsInput](entities/class:parrot_tools.aws.documentdb.DescribeEventsInput.md)

Input for listing DocumentDB operational events.

## [DocumentDBToolkit](entities/class:parrot_tools.aws.documentdb.DocumentDBToolkit.md)

Toolkit for managing AWS DocumentDB clusters, instances, and snapshots.

## [DownloadLogInput](entities/class:parrot_tools.aws.documentdb.DownloadLogInput.md)

Input for downloading DocumentDB log file content.

## [GetClusterDetailsInput](entities/class:parrot_tools.aws.documentdb.GetClusterDetailsInput.md)

Input for getting DocumentDB cluster details.

## [GetInstanceDetailsInput](entities/class:parrot_tools.aws.documentdb.GetInstanceDetailsInput.md)

Input for getting DocumentDB instance details.

## [ListClusterInstancesInput](entities/class:parrot_tools.aws.documentdb.ListClusterInstancesInput.md)

Input for listing instances in a DocumentDB cluster.

## [ListClustersInput](entities/class:parrot_tools.aws.documentdb.ListClustersInput.md)

Input for listing DocumentDB clusters.

## [ListLogFilesInput](entities/class:parrot_tools.aws.documentdb.ListLogFilesInput.md)

Input for listing available DB log files.

## [ListSnapshotsInput](entities/class:parrot_tools.aws.documentdb.ListSnapshotsInput.md)

Input for listing DocumentDB cluster snapshots.

## [RebootInstanceInput](entities/class:parrot_tools.aws.documentdb.RebootInstanceInput.md)

Input for rebooting a DocumentDB instance.

## [StartClusterInput](entities/class:parrot_tools.aws.documentdb.StartClusterInput.md)

Input for starting a DocumentDB cluster.

## [StopClusterInput](entities/class:parrot_tools.aws.documentdb.StopClusterInput.md)

Input for stopping a DocumentDB cluster.

## [DescribeInstancesInput](entities/class:parrot_tools.aws.ec2.DescribeInstancesInput.md)

Input for describing specific EC2 instances.

## [EC2Toolkit](entities/class:parrot_tools.aws.ec2.EC2Toolkit.md)

Toolkit for inspecting AWS EC2 instances, security groups, and networking.

## [FindPublicSecurityGroupsInput](entities/class:parrot_tools.aws.ec2.FindPublicSecurityGroupsInput.md)

Input for finding security groups with public access.

## [FindResourceByIPInput](entities/class:parrot_tools.aws.ec2.FindResourceByIPInput.md)

Input for finding AWS resources by IP address.

## [ListInstancesInput](entities/class:parrot_tools.aws.ec2.ListInstancesInput.md)

Input for listing EC2 instances.

## [ListRouteTablesInput](entities/class:parrot_tools.aws.ec2.ListRouteTablesInput.md)

Input for listing route tables.

## [ListSecurityGroupsInput](entities/class:parrot_tools.aws.ec2.ListSecurityGroupsInput.md)

Input for listing EC2 security groups.

## [ListSubnetsInput](entities/class:parrot_tools.aws.ec2.ListSubnetsInput.md)

Input for listing subnets.

## [ListVPCsInput](entities/class:parrot_tools.aws.ec2.ListVPCsInput.md)

Input for listing VPCs.

## [ECRToolkit](entities/class:parrot_tools.aws.ecr.ECRToolkit.md)

Toolkit for inspecting AWS ECR repositories and container images.

## [GetImageScanFindingsInput](entities/class:parrot_tools.aws.ecr.GetImageScanFindingsInput.md)

Input for getting vulnerability scan findings.

## [GetRepositoryPolicyInput](entities/class:parrot_tools.aws.ecr.GetRepositoryPolicyInput.md)

Input for getting an ECR repository IAM policy.

## [ListRepositoriesInput](entities/class:parrot_tools.aws.ecr.ListRepositoriesInput.md)

Input for listing ECR repositories.

## [ListRepositoryImagesInput](entities/class:parrot_tools.aws.ecr.ListRepositoryImagesInput.md)

Input for listing images in an ECR repository.

## [DescribeTasksInput](entities/class:parrot_tools.aws.ecs.DescribeTasksInput.md)

Input for describing specific ECS tasks.

## [ECSToolkit](entities/class:parrot_tools.aws.ecs.ECSToolkit.md)

Toolkit for inspecting AWS ECS/Fargate resources.

## [GetFargateLogsInput](entities/class:parrot_tools.aws.ecs.GetFargateLogsInput.md)

Input for fetching Fargate task logs from CloudWatch.

## [ListClustersInput](entities/class:parrot_tools.aws.ecs.ListClustersInput.md)

Input for listing ECS clusters.

## [ListServicesInput](entities/class:parrot_tools.aws.ecs.ListServicesInput.md)

Input for listing ECS services in a cluster.

## [ListTasksInput](entities/class:parrot_tools.aws.ecs.ListTasksInput.md)

Input for listing ECS tasks with optional filters.

## [DescribeClusterInput](entities/class:parrot_tools.aws.eks.DescribeClusterInput.md)

Input for describing an EKS cluster.

## [DescribeFargateProfileInput](entities/class:parrot_tools.aws.eks.DescribeFargateProfileInput.md)

Input for describing an EKS Fargate profile.

## [DescribeNodegroupInput](entities/class:parrot_tools.aws.eks.DescribeNodegroupInput.md)

Input for describing an EKS nodegroup.

## [EKSToolkit](entities/class:parrot_tools.aws.eks.EKSToolkit.md)

Toolkit for inspecting AWS EKS Kubernetes clusters.

## [ListClustersInput](entities/class:parrot_tools.aws.eks.ListClustersInput.md)

Input for listing EKS clusters.

## [ListFargateProfilesInput](entities/class:parrot_tools.aws.eks.ListFargateProfilesInput.md)

Input for listing EKS Fargate profiles.

## [ListNodegroupsInput](entities/class:parrot_tools.aws.eks.ListNodegroupsInput.md)

Input for listing EKS nodegroups.

## [ListPodsInput](entities/class:parrot_tools.aws.eks.ListPodsInput.md)

Input for listing Kubernetes pods in an EKS cluster.

## [GetFindingDetailsInput](entities/class:parrot_tools.aws.guardduty.GetFindingDetailsInput.md)

Input for getting detailed finding information.

## [GetFindingsStatisticsInput](entities/class:parrot_tools.aws.guardduty.GetFindingsStatisticsInput.md)

Input for getting finding statistics.

## [GuardDutyToolkit](entities/class:parrot_tools.aws.guardduty.GuardDutyToolkit.md)

Toolkit for inspecting AWS GuardDuty detectors and findings.

## [ListDetectorsInput](entities/class:parrot_tools.aws.guardduty.ListDetectorsInput.md)

Input for listing GuardDuty detectors.

## [ListFindingsInput](entities/class:parrot_tools.aws.guardduty.ListFindingsInput.md)

Input for listing GuardDuty findings.

## [ListIPSetsInput](entities/class:parrot_tools.aws.guardduty.ListIPSetsInput.md)

Input for listing GuardDuty IP sets.

## [ListThreatIntelSetsInput](entities/class:parrot_tools.aws.guardduty.ListThreatIntelSetsInput.md)

Input for listing GuardDuty threat intel sets.

## [FindAccessKeyInput](entities/class:parrot_tools.aws.iam.FindAccessKeyInput.md)

Input for finding the owner of an access key.

## [GetPolicyDetailsInput](entities/class:parrot_tools.aws.iam.GetPolicyDetailsInput.md)

Input for getting IAM policy details.

## [GetRoleInput](entities/class:parrot_tools.aws.iam.GetRoleInput.md)

Input for getting IAM role details.

## [GetUserInput](entities/class:parrot_tools.aws.iam.GetUserInput.md)

Input for getting IAM user details.

## [IAMToolkit](entities/class:parrot_tools.aws.iam.IAMToolkit.md)

Toolkit for inspecting AWS IAM roles, users, policies, and access keys.

## [ListActiveAccessKeysInput](entities/class:parrot_tools.aws.iam.ListActiveAccessKeysInput.md)

Input for listing all active access keys.

## [ListRolesInput](entities/class:parrot_tools.aws.iam.ListRolesInput.md)

Input for listing IAM roles.

## [ListUsersInput](entities/class:parrot_tools.aws.iam.ListUsersInput.md)

Input for listing IAM users.

## [AggregateFindingsInput](entities/class:parrot_tools.aws.inspector.AggregateFindingsInput.md)

Input for aggregating Inspector v2 findings.

## [CreateFindingsReportInput](entities/class:parrot_tools.aws.inspector.CreateFindingsReportInput.md)

Input for creating an async Inspector findings report in S3.

## [CreateSbomExportInput](entities/class:parrot_tools.aws.inspector.CreateSbomExportInput.md)

Input for creating an async SBOM export in S3.

## [GetEcrImageFindingsInput](entities/class:parrot_tools.aws.inspector.GetEcrImageFindingsInput.md)

Input for getting Inspector findings for a specific ECR image.

## [GetSecurityPostureInput](entities/class:parrot_tools.aws.inspector.GetSecurityPostureInput.md)

Input for computing the account-level Inspector security posture.

## [InspectorToolkit](entities/class:parrot_tools.aws.inspector.InspectorToolkit.md)

Stateless toolkit wrapping Amazon Inspector v2 (inspector2).

## [ListCoverageInput](entities/class:parrot_tools.aws.inspector.ListCoverageInput.md)

Input for listing Inspector v2 coverage resources.

## [ListFindingsInput](entities/class:parrot_tools.aws.inspector.ListFindingsInput.md)

Input for listing Inspector v2 findings.

## [ListTopVulnerableResourcesInput](entities/class:parrot_tools.aws.inspector.ListTopVulnerableR-e62a9ea5.md)

Input for listing the most vulnerable resources by weighted severity.

## [CreateFunctionInput](entities/class:parrot_tools.aws.lambda_func.CreateFunctionInput.md)

Input for creating a new Lambda function.

## [DeleteFunctionInput](entities/class:parrot_tools.aws.lambda_func.DeleteFunctionInput.md)

Input for deleting a Lambda function.

## [GetFunctionInput](entities/class:parrot_tools.aws.lambda_func.GetFunctionInput.md)

Input for getting Lambda function details.

## [InvokeFunctionInput](entities/class:parrot_tools.aws.lambda_func.InvokeFunctionInput.md)

Input for invoking a Lambda function.

## [LambdaToolkit](entities/class:parrot_tools.aws.lambda_func.LambdaToolkit.md)

Toolkit for managing and invoking AWS Lambda functions.

## [ListFunctionsInput](entities/class:parrot_tools.aws.lambda_func.ListFunctionsInput.md)

Input for listing Lambda functions.

## [UpdateFunctionCodeInput](entities/class:parrot_tools.aws.lambda_func.UpdateFunctionCodeInput.md)

Input for updating the code of a Lambda function.

## [CreateSnapshotInput](entities/class:parrot_tools.aws.rds.CreateSnapshotInput.md)

Input for creating a manual DB snapshot.

## [DescribeEventsInput](entities/class:parrot_tools.aws.rds.DescribeEventsInput.md)

Input for listing RDS operational events.

## [DownloadLogFilteredInput](entities/class:parrot_tools.aws.rds.DownloadLogFilteredInput.md)

Input for downloading and filtering RDS log file content by severity.

## [DownloadLogInput](entities/class:parrot_tools.aws.rds.DownloadLogInput.md)

Input for downloading RDS log file content.

## [GetInstanceDetailsInput](entities/class:parrot_tools.aws.rds.GetInstanceDetailsInput.md)

Input for getting RDS instance details.

## [ListInstancesInput](entities/class:parrot_tools.aws.rds.ListInstancesInput.md)

Input for listing RDS instances.

## [ListLogFilesInput](entities/class:parrot_tools.aws.rds.ListLogFilesInput.md)

Input for listing available DB log files.

## [ListSnapshotsInput](entities/class:parrot_tools.aws.rds.ListSnapshotsInput.md)

Input for listing RDS snapshots.

## [PerformanceInsightsInput](entities/class:parrot_tools.aws.rds.PerformanceInsightsInput.md)

Input for fetching Performance Insights metrics.

## [RDSToolkit](entities/class:parrot_tools.aws.rds.RDSToolkit.md)

Toolkit for managing AWS RDS instances, snapshots, logs, and diagnostics.

## [RebootInstanceInput](entities/class:parrot_tools.aws.rds.RebootInstanceInput.md)

Input for rebooting an RDS instance.

## [StartInstanceInput](entities/class:parrot_tools.aws.rds.StartInstanceInput.md)

Input for starting an RDS instance.

## [StopInstanceInput](entities/class:parrot_tools.aws.rds.StopInstanceInput.md)

Input for stopping an RDS instance.

## [CreateHostedZoneInput](entities/class:parrot_tools.aws.route53.CreateHostedZoneInput.md)

Input for creating a new hosted zone.

## [GetHostedZoneDetailsInput](entities/class:parrot_tools.aws.route53.GetHostedZoneDetailsInput.md)

Input for getting hosted zone details.

## [ListHealthChecksInput](entities/class:parrot_tools.aws.route53.ListHealthChecksInput.md)

Input for listing Route53 health checks.

## [ListHostedZonesInput](entities/class:parrot_tools.aws.route53.ListHostedZonesInput.md)

Input for listing Route53 hosted zones.

## [ListResourceRecordSetsInput](entities/class:parrot_tools.aws.route53.ListResourceRecordSetsInput.md)

Input for listing DNS records in a hosted zone.

## [ListTrafficPoliciesInput](entities/class:parrot_tools.aws.route53.ListTrafficPoliciesInput.md)

Input for listing Route53 traffic policies.

## [Route53Toolkit](entities/class:parrot_tools.aws.route53.Route53Toolkit.md)

Toolkit for managing AWS Route53 hosted zones, DNS records and health checks.

## [AnalyzeBucketSecurityInput](entities/class:parrot_tools.aws.s3.AnalyzeBucketSecurityInput.md)

Input for analyzing S3 bucket security configuration.

## [FindPublicBucketsInput](entities/class:parrot_tools.aws.s3.FindPublicBucketsInput.md)

Input for finding publicly accessible S3 buckets.

## [GetBucketDetailsInput](entities/class:parrot_tools.aws.s3.GetBucketDetailsInput.md)

Input for getting detailed S3 bucket information.

## [ListBucketsInput](entities/class:parrot_tools.aws.s3.ListBucketsInput.md)

Input for listing S3 buckets.

## [S3Toolkit](entities/class:parrot_tools.aws.s3.S3Toolkit.md)

Toolkit for inspecting and analyzing AWS S3 buckets.

## [GetFindingsInput](entities/class:parrot_tools.aws.securityhub.GetFindingsInput.md)

Input for getting SecurityHub findings.

## [GetSecurityScoreInput](entities/class:parrot_tools.aws.securityhub.GetSecurityScoreInput.md)

Input for getting the account security score.

## [ListFailedStandardsInput](entities/class:parrot_tools.aws.securityhub.ListFailedStandardsInput.md)

Input for listing failed security standards.

## [SecurityHubToolkit](entities/class:parrot_tools.aws.securityhub.SecurityHubToolkit.md)

Toolkit for inspecting AWS SecurityHub findings and compliance.

## [EntitiesQueryResponse](entities/class:parrot_tools.backstage.models.EntitiesQueryResponse.md)

Paginated entity query response.

## [Entity](entities/class:parrot_tools.backstage.models.Entity.md)

Backstage catalog entity.

## [EntityFacet](entities/class:parrot_tools.backstage.models.EntityFacet.md)

A single facet value with its count.

## [EntityFacetsResponse](entities/class:parrot_tools.backstage.models.EntityFacetsResponse.md)

Response from entity-facets endpoint.

## [EntityMeta](entities/class:parrot_tools.backstage.models.EntityMeta.md)

Backstage entity metadata.

## [EntityRelation](entities/class:parrot_tools.backstage.models.EntityRelation.md)

Relationship between entities.

## [Location](entities/class:parrot_tools.backstage.models.Location.md)

Backstage catalog location.

## [LocationResponse](entities/class:parrot_tools.backstage.models.LocationResponse.md)

Response from location registration.

## [BackstageCatalogToolkit](entities/class:parrot_tools.backstage.toolkit.BackstageCatalogToolkit.md)

Toolkit for reading entries from a Backstage.io software catalog.

## [BingSearchArgs](entities/class:parrot_tools.bingsearch.BingSearchArgs.md)

Arguments for the Bing Search Tool.

## [BingSearchTool](entities/class:parrot_tools.bingsearch.BingSearchTool.md)

Tool to execute web searches using the Bing Search API.

## [BloombergTool](entities/class:parrot_tools.bloomberg.BloombergTool.md)

Tool for fetching news from Bloomberg RSS feeds.

## [BloombergToolArgsSchema](entities/class:parrot_tools.bloomberg.BloombergToolArgsSchema.md)

Schema for Bloomberg tool arguments.

## [BreakEvenAnalysisTool](entities/class:parrot_tools.breakeven.BreakEvenAnalysisTool.md)

Find threshold values for target metrics.

## [BreakEvenInput](entities/class:parrot_tools.breakeven.BreakEvenInput.md)

Input schema for BreakEvenAnalysisTool.

## [ToolCache](entities/class:parrot_tools.cache.ToolCache.md)

Redis-backed cache for tool/toolkit API responses.

## [CalculatorArgs](entities/class:parrot_tools.calculator.tool.CalculatorArgs.md)

Arguments for calculator operations.

## [CalculatorTool](entities/class:parrot_tools.calculator.tool.CalculatorTool.md)

Advanced calculator tool with dynamically loaded operations.

## [ChartFormat](entities/class:parrot_tools.chart.ChartFormat.md)

Output format for charts.

## [ChartStyle](entities/class:parrot_tools.chart.ChartStyle.md)

Visual styling configuration for charts.

## [ChartTool](entities/class:parrot_tools.chart.ChartTool.md)

Tool for generating charts from structured data.

## [ChartType](entities/class:parrot_tools.chart.ChartType.md)

Supported chart types.

## [GenerateChartInput](entities/class:parrot_tools.chart.GenerateChartInput.md)

Input schema for chart generation.

## [ScanComparator](entities/class:parrot_tools.cloudsploit.comparator.ScanComparator.md)

Compares two CloudSploit scan results to track security posture changes.

## [EcrScanCollector](entities/class:parrot_tools.cloudsploit.ecr_collector.EcrSca-9d89c1b3.md)

Aggregate ECR vulnerability scan findings across many repos.

## [CloudSploitExecutor](entities/class:parrot_tools.cloudsploit.executor.CloudSploitExecutor.md)

Executes CloudSploit scans via Docker or direct CLI.

## [CloudProvider](entities/class:parrot_tools.cloudsploit.models.CloudProvider.md)

Supported cloud providers for CloudSploit scans.

## [CloudSploitConfig](entities/class:parrot_tools.cloudsploit.models.CloudSploitConfig.md)

Configuration for CloudSploit execution.

## [ComparisonReport](entities/class:parrot_tools.cloudsploit.models.ComparisonReport.md)

Result of comparing two CloudSploit scans.

## [ComplianceFramework](entities/class:parrot_tools.cloudsploit.models.ComplianceFramework.md)

Supported compliance frameworks for filtered scans.

## [EcrCollectionPlan](entities/class:parrot_tools.cloudsploit.models.EcrCollectionPlan.md)

Plan for ``collect_ecr_findings``. Loaded from a YAML file at runtime.

## [EcrCollectionResult](entities/class:parrot_tools.cloudsploit.models.EcrCollectionResult.md)

Top-level container — mirrors the JSON output of collect_ecr_findings.js.

## [EcrRepoFindings](entities/class:parrot_tools.cloudsploit.models.EcrRepoFindings.md)

Aggregated findings for a single (repo, tag) pair.

## [EcrRepoPlan](entities/class:parrot_tools.cloudsploit.models.EcrRepoPlan.md)

One ECR repository plus its tag priority order.

## [EcrScanFinding](entities/class:parrot_tools.cloudsploit.models.EcrScanFinding.md)

One vulnerability finding from ECR Basic Scanning.

## [EcrSeverity](entities/class:parrot_tools.cloudsploit.models.EcrSeverity.md)

ECR / vulnerability scan severities (distinct from SeverityLevel).

## [ScanFinding](entities/class:parrot_tools.cloudsploit.models.ScanFinding.md)

A single finding from a CloudSploit scan.

## [ScanResult](entities/class:parrot_tools.cloudsploit.models.ScanResult.md)

Full scan result container.

## [ScanSummary](entities/class:parrot_tools.cloudsploit.models.ScanSummary.md)

Aggregated summary of a CloudSploit scan.

## [SeverityLevel](entities/class:parrot_tools.cloudsploit.models.SeverityLevel.md)

CloudSploit finding severity levels.

## [ScanResultParser](entities/class:parrot_tools.cloudsploit.parser.ScanResultParser.md)

Parses CloudSploit JSON output into typed ScanResult objects.

## [ReportGenerator](entities/class:parrot_tools.cloudsploit.reports.ReportGenerator.md)

Generates HTML and PDF reports from CloudSploit scan results.

## [CloudSploitToolkit](entities/class:parrot_tools.cloudsploit.toolkit.CloudSploitToolkit.md)

Cloud Security Posture Management toolkit powered by CloudSploit.

## [CodeToolkit](entities/class:parrot_tools.code_toolkit.CodeToolkit.md)

Toolkit for delegating coding tasks to Codex-compatible providers.

## [CodexProvider](entities/class:parrot_tools.code_toolkit.CodexProvider.md)

Coding provider backed by the experimental OpenAI Codex SDK.

## [CodingProvider](entities/class:parrot_tools.code_toolkit.CodingProvider.md)

Provider protocol implemented by coding backends.

## [CodingTask](entities/class:parrot_tools.code_toolkit.CodingTask.md)

Artifact describing a coding task to execute against a repository.

## [CodingTaskInput](entities/class:parrot_tools.code_toolkit.CodingTaskInput.md)

Shared input fields for code toolkit tools.

## [CodingTaskResult](entities/class:parrot_tools.code_toolkit.CodingTaskResult.md)

Structured result returned by coding providers.

## [ExplainPatchInput](entities/class:parrot_tools.code_toolkit.ExplainPatchInput.md)

Input for explaining an existing patch or diff.

## [MinimaxProvider](entities/class:parrot_tools.code_toolkit.MinimaxProvider.md)

Coding provider backed by Nvidia-hosted Minimax-compatible models.

## [ExecutionResult](entities/class:parrot_tools.codeinterpreter.executor.ExecutionResult.md)

Result from code execution in isolated environment

## [IsolatedExecutor](entities/class:parrot_tools.codeinterpreter.executor.IsolatedExecutor.md)

Manages isolated Python code execution using Docker containers.

## [SubprocessExecutor](entities/class:parrot_tools.codeinterpreter.executor.Subproc-0210a8b8.md)

Fallback executor using subprocess with basic restrictions.

## [ClassInfo](entities/class:parrot_tools.codeinterpreter.internals.ClassInfo.md)

Information about a class

## [FileOperationsTool](entities/class:parrot_tools.codeinterpreter.internals.FileOp-4d0602f3.md)

Tool for file operations (reading, writing, organizing outputs).

## [FunctionInfo](entities/class:parrot_tools.codeinterpreter.internals.FunctionInfo.md)

Information about a function

## [ImportInfo](entities/class:parrot_tools.codeinterpreter.internals.ImportInfo.md)

Information about an import

## [PythonExecutionTool](entities/class:parrot_tools.codeinterpreter.internals.Python-eba05196.md)

Tool for executing Python code in isolated environment.

## [StaticAnalysisTool](entities/class:parrot_tools.codeinterpreter.internals.Static-e208d18b.md)

Tool for performing static analysis on Python code.

## [BaseCodeResponse](entities/class:parrot_tools.codeinterpreter.models.BaseCodeResponse.md)

Modelo base para todas las respuestas del CodeInterpreterTool

## [BugIssue](entities/class:parrot_tools.codeinterpreter.models.BugIssue.md)

Issue o bug potencial identificado

## [ClassComponent](entities/class:parrot_tools.codeinterpreter.models.ClassComponent.md)

Información sobre una clase identificada en el código

## [CodeAnalysisResponse](entities/class:parrot_tools.codeinterpreter.models.CodeAnaly-6a912bb4.md)

Respuesta completa para operación de análisis de código

## [CodeFlowStep](entities/class:parrot_tools.codeinterpreter.models.CodeFlowStep.md)

Paso individual en el flujo de ejecución

## [CodeReference](entities/class:parrot_tools.codeinterpreter.models.CodeReference.md)

Referencias a ubicaciones específicas en código fuente

## [ComplexityMetrics](entities/class:parrot_tools.codeinterpreter.models.ComplexityMetrics.md)

Métricas de complejidad del código

## [ConceptExplanation](entities/class:parrot_tools.codeinterpreter.models.ConceptExplanation.md)

Explicación de un concepto técnico utilizado

## [CoverageGap](entities/class:parrot_tools.codeinterpreter.models.CoverageGap.md)

Brecha en cobertura de tests

## [DebugResponse](entities/class:parrot_tools.codeinterpreter.models.DebugResponse.md)

Respuesta completa para operación de detección de bugs

## [Dependency](entities/class:parrot_tools.codeinterpreter.models.Dependency.md)

Información sobre una dependencia externa

## [DocstringFormat](entities/class:parrot_tools.codeinterpreter.models.DocstringFormat.md)

Formatos soportados de docstrings

## [DocumentationResponse](entities/class:parrot_tools.codeinterpreter.models.Documenta-06442937.md)

Respuesta completa para operación de generación de documentación

## [DocumentedElement](entities/class:parrot_tools.codeinterpreter.models.DocumentedElement.md)

Elemento individual que ha sido documentado

## [ExecutionStatus](entities/class:parrot_tools.codeinterpreter.models.ExecutionStatus.md)

Estados posibles de ejecución

## [ExplanationResponse](entities/class:parrot_tools.codeinterpreter.models.Explanati-ac1f69c5.md)

Respuesta completa para operación de explicación de código

## [FunctionComponent](entities/class:parrot_tools.codeinterpreter.models.FunctionComponent.md)

Información sobre una función identificada en el código

## [GeneratedTest](entities/class:parrot_tools.codeinterpreter.models.GeneratedTest.md)

Información sobre un test generado

## [OperationType](entities/class:parrot_tools.codeinterpreter.models.OperationType.md)

Tipos de operaciones soportadas por el CodeInterpreterTool

## [QualityObservation](entities/class:parrot_tools.codeinterpreter.models.QualityObservation.md)

Observación sobre calidad del código

## [Severity](entities/class:parrot_tools.codeinterpreter.models.Severity.md)

Niveles de severidad para issues detectados

## [TestGenerationResponse](entities/class:parrot_tools.codeinterpreter.models.TestGener-d4cb3bdf.md)

Respuesta completa para operación de generación de tests

## [TestType](entities/class:parrot_tools.codeinterpreter.models.TestType.md)

Tipos de tests generados

## [CodeInterpreterArgs](entities/class:parrot_tools.codeinterpreter.tool.CodeInterpreterArgs.md)

Input schema for CodeInterpreterTool.

## [CodeInterpreterTool](entities/class:parrot_tools.codeinterpreter.tool.CodeInterpreterTool.md)

Agent-as-Tool for comprehensive Python code analysis.

## [CompanyInfo](entities/class:parrot_tools.company_info.tool.CompanyInfo.md)

Structured output model for company information.

## [CompanyInfoToolkit](entities/class:parrot_tools.company_info.tool.CompanyInfoToolkit.md)

Toolkit for scraping company information from multiple platforms.

## [CompanyInput](entities/class:parrot_tools.company_info.tool.CompanyInput.md)

Input model for company scraping tools.

## [GoogleSearchResult](entities/class:parrot_tools.company_info.tool.GoogleSearchResult.md)

Result from Google site search.

## [ResearchCompanyInput](entities/class:parrot_tools.company_info.tool.ResearchCompanyInput.md)

Input model for the `research_company` aggregate tool.

## [SourceConfig](entities/class:parrot_tools.company_info.tool.SourceConfig.md)

Internal per-source search configuration.

## [CompositeScoreInput](entities/class:parrot_tools.composite_score.CompositeScoreInput.md)

Input schema for CompositeScoreTool.

## [CompositeScoreTool](entities/class:parrot_tools.composite_score.CompositeScoreTool.md)

Tool for computing composite technical scores for asset ranking.

## [ComputerAgent](entities/class:parrot_tools.computer.agent.ComputerAgent.md)

Agent configured for vision-based browser automation via computer-use.

## [AsyncComputerBackend](entities/class:parrot_tools.computer.backend.AsyncComputerBackend.md)

Async Playwright wrapper implementing the computer-use action interface.

## [ComputerTask](entities/class:parrot_tools.computer.models.ComputerTask.md)

A reusable sequence of natural-language instructions.

## [ComputerUseConfig](entities/class:parrot_tools.computer.models.ComputerUseConfig.md)

Configuration for the ComputerUse tool type in GoogleGenAIClient.

## [EnvState](entities/class:parrot_tools.computer.models.EnvState.md)

State returned after each computer-use action.

## [LoopResult](entities/class:parrot_tools.computer.models.LoopResult.md)

Result of a loop execution.

## [TaskResult](entities/class:parrot_tools.computer.models.TaskResult.md)

Result of a single task execution.

## [ComputerInteractionToolkit](entities/class:parrot_tools.computer.toolkit.ComputerInterac-9541a239.md)

AbstractToolkit for vision-based browser automation via computer-use.

## [CorrelationAnalysisArgs](entities/class:parrot_tools.correlationanalysis.CorrelationA-192999a8.md)

Arguments schema for Correlation Analysis.

## [CorrelationAnalysisTool](entities/class:parrot_tools.correlationanalysis.CorrelationA-1df8cf5c.md)

Tool for analyzing correlations between a key column and other columns in a DataFrame.

## [CorrelationMethod](entities/class:parrot_tools.correlationanalysis.CorrelationMethod.md)

Available correlation methods.

## [OutputFormat](entities/class:parrot_tools.correlationanalysis.OutputFormat.md)

Available output formats.

## [CSVExportArgs](entities/class:parrot_tools.csv_export.CSVExportArgs.md)

Arguments schema for CSV export.

## [CSVExportTool](entities/class:parrot_tools.csv_export.CSVExportTool.md)

CSV Export Tool for exporting structured data to CSV files.

## [DataFrameToCSVTool](entities/class:parrot_tools.csv_export.DataFrameToCSVTool.md)

Simplified CSV tool focused on DataFrame export.

## [AbstractSchemaManagerTool](entities/class:parrot_tools.database.abstract.AbstractSchema-172b76f4.md)

Abstract base for database-specific schema management tools.

## [SchemaSearchArgs](entities/class:parrot_tools.database.abstract.SchemaSearchArgs.md)

Arguments for schema search tool.

## [SchemaMetadataCache](entities/class:parrot_tools.database.cache.SchemaMetadataCache.md)

Two-tier caching: LRU (hot data) + Optional Vector Store (cold/searchable data).

## [SchemaMetadata](entities/class:parrot_tools.database.models.SchemaMetadata.md)

Metadata for a single schema (client).

## [TableMetadata](entities/class:parrot_tools.database.models.TableMetadata.md)

Enhanced table metadata for large-scale operations.

## [DatabaseFlavor](entities/class:parrot_tools.db.DatabaseFlavor.md)

Supported database flavors.

## [DatabaseTool](entities/class:parrot_tools.db.DatabaseTool.md)

Unified Database Tool that handles the complete database interaction pipeline:

## [DatabaseToolArgs](entities/class:parrot_tools.db.DatabaseToolArgs.md)

Arguments for the unified database tool.

## [OutputFormat](entities/class:parrot_tools.db.OutputFormat.md)

Supported output formats.

## [QueryType](entities/class:parrot_tools.db.QueryType.md)

Supported query types.

## [QueryValidationResult](entities/class:parrot_tools.db.QueryValidationResult.md)

Result of query validation.

## [SchemaMetadata](entities/class:parrot_tools.db.SchemaMetadata.md)

Metadata for a database schema.

## [DuckDuckGoToolkit](entities/class:parrot_tools.ddgo.DuckDuckGoToolkit.md)

DuckDuckGo Search Toolkit providing comprehensive search capabilities.

## [ImageSearchArgs](entities/class:parrot_tools.ddgo.ImageSearchArgs.md)

Arguments for image search.

## [NewsSearchArgs](entities/class:parrot_tools.ddgo.NewsSearchArgs.md)

Arguments for news search.

## [VideoSearchArgs](entities/class:parrot_tools.ddgo.VideoSearchArgs.md)

Arguments for video search.

## [WebSearchArgs](entities/class:parrot_tools.ddgo.WebSearchArgs.md)

Arguments for web search.

## [DdgSearchTool](entities/class:parrot_tools.ddgsearch.DdgSearchTool.md)

Tool for performing web searches using DuckDuckGo.

## [DfToHtmlArgs](entities/class:parrot_tools.dftohtml.DfToHtmlArgs.md)

Arguments schema for DataFrame to HTML conversion.

## [DfToHtmlTool](entities/class:parrot_tools.dftohtml.DfToHtmlTool.md)

Tool for converting pandas DataFrames to styled HTML tables.

## [DocumentConverterTool](entities/class:parrot_tools.doc_converter.DocumentConverterTool.md)

Convert documents (PDF, DOCX, PPTX) to structured JSON or Markdown using Docling.

## [DocumentConverterToolArgs](entities/class:parrot_tools.doc_converter.DocumentConverterToolArgs.md)

Arguments for DocumentConverterTool.

## [ComposeGenerator](entities/class:parrot_tools.docker.compose.ComposeGenerator.md)

Generates docker-compose YAML from Pydantic models.

## [DockerConfig](entities/class:parrot_tools.docker.config.DockerConfig.md)

Configuration for Docker executor.

## [DockerExecutor](entities/class:parrot_tools.docker.executor.DockerExecutor.md)

Async executor for Docker CLI commands.

## [ComposeGenerateInput](entities/class:parrot_tools.docker.models.ComposeGenerateInput.md)

Input for generating a docker-compose file.

## [ComposeServiceDef](entities/class:parrot_tools.docker.models.ComposeServiceDef.md)

Definition of a single service in a docker-compose file.

## [ContainerInfo](entities/class:parrot_tools.docker.models.ContainerInfo.md)

Information about a Docker container.

## [ContainerRunInput](entities/class:parrot_tools.docker.models.ContainerRunInput.md)

Input for docker_run operation.

## [DockerBuildInput](entities/class:parrot_tools.docker.models.DockerBuildInput.md)

Input for docker_build operation.

## [DockerExecInput](entities/class:parrot_tools.docker.models.DockerExecInput.md)

Input for docker_exec operation.

## [DockerOperationResult](entities/class:parrot_tools.docker.models.DockerOperationResult.md)

Result of a Docker operation.

## [ImageInfo](entities/class:parrot_tools.docker.models.ImageInfo.md)

Information about a Docker image.

## [PortMapping](entities/class:parrot_tools.docker.models.PortMapping.md)

Port mapping for a container.

## [PruneResult](entities/class:parrot_tools.docker.models.PruneResult.md)

Result of a Docker prune operation.

## [VolumeMapping](entities/class:parrot_tools.docker.models.VolumeMapping.md)

Volume mapping for a container.

## [DockerToolkit](entities/class:parrot_tools.docker.toolkit.DockerToolkit.md)

Toolkit for managing Docker containers and compose stacks.

## [AbstractDocumentTool](entities/class:parrot_tools.document.AbstractDocumentTool.md)

Abstract base class for document generation tools.

## [DocumentGenerationArgs](entities/class:parrot_tools.document.DocumentGenerationArgs.md)

Base arguments schema for document generation tools.

## [DocumentMetadata](entities/class:parrot_tools.document.DocumentMetadata.md)

Metadata for generated documents.

## [EdaReportArgs](entities/class:parrot_tools.edareport.EdaReportArgs.md)

Arguments schema for EDA Report generation.

## [EdaReportPresets](entities/class:parrot_tools.edareport.EdaReportPresets.md)

Predefined configuration presets for different use cases.

## [EdaReportTool](entities/class:parrot_tools.edareport.EdaReportTool.md)

Tool for generating comprehensive EDA reports using ydata_profiling.

## [ElasticsearchOperation](entities/class:parrot_tools.elasticsearch.ElasticsearchOperation.md)

Available Elasticsearch operations

## [ElasticsearchTool](entities/class:parrot_tools.elasticsearch.ElasticsearchTool.md)

Tool for querying Elasticsearch/OpenSearch indices and analyzing logs.

## [ElasticsearchToolArgs](entities/class:parrot_tools.elasticsearch.ElasticsearchToolArgs.md)

Arguments schema for Elasticsearch operations

## [EmployeeAction](entities/class:parrot_tools.employees.EmployeeAction.md)

Available employee hierarchy actions.

## [EmployeesTool](entities/class:parrot_tools.employees.EmployeesTool.md)

Employee Hierarchy Tool for querying organizational structure.

## [EmployeesToolArgsSchema](entities/class:parrot_tools.employees.EmployeesToolArgsSchema.md)

Arguments schema for EmployeesTool.

## [EpsonProductToolkit](entities/class:parrot_tools.epson.EpsonProductToolkit.md)

Toolkit for managing Epson-related operations.

## [ProductInfo](entities/class:parrot_tools.epson.ProductInfo.md)

Schema for the product information returned by the query.

## [ProductInput](entities/class:parrot_tools.epson.ProductInput.md)

Input schema for querying Epson product information.

## [DataFrameToExcelTool](entities/class:parrot_tools.excel.DataFrameToExcelTool.md)

Simplified Excel tool that focuses purely on DataFrame export.

## [ExcelArgs](entities/class:parrot_tools.excel.ExcelArgs.md)

Arguments schema for Excel/ODS Document generation.

## [ExcelTool](entities/class:parrot_tools.excel.ExcelTool.md)

Microsoft Excel/OpenDocument Spreadsheet Generation Tool.

## [FileReaderTool](entities/class:parrot_tools.file_reader.FileReaderTool.md)

Tool that reads a file and returns its textual representation.

## [FileReaderToolArgs](entities/class:parrot_tools.file_reader.FileReaderToolArgs.md)

Arguments for :class:`FileReaderTool`.

## [FlowtaskCodeExecutionInput](entities/class:parrot_tools.flowtask.tool.FlowtaskCodeExecutionInput.md)

Input schema for code_execution tool.

## [FlowtaskComponentInput](entities/class:parrot_tools.flowtask.tool.FlowtaskComponentInput.md)

Input schema for component_call tool.

## [FlowtaskListTasksInput](entities/class:parrot_tools.flowtask.tool.FlowtaskListTasksInput.md)

Input schema for list_tasks tool (task discovery).

## [FlowtaskRemoteExecutionInput](entities/class:parrot_tools.flowtask.tool.FlowtaskRemoteExec-1a84842e.md)

Input schema for remote_execution tool.

## [FlowtaskTaskExecutionInput](entities/class:parrot_tools.flowtask.tool.FlowtaskTaskExecutionInput.md)

Input schema for task_execution tool.

## [FlowtaskTaskServiceInput](entities/class:parrot_tools.flowtask.tool.FlowtaskTaskServiceInput.md)

Input schema for task_service tool (synchronous REST execution).

## [FlowtaskToolkit](entities/class:parrot_tools.flowtask.tool.FlowtaskToolkit.md)

Toolkit for executing Flowtask components and tasks dynamically.

## [TaskCodeFormat](entities/class:parrot_tools.flowtask.tool.TaskCodeFormat.md)

Format of the task code.

## [FredAPITool](entities/class:parrot_tools.fred_api.FredAPITool.md)

Tool for fetching economic data from the Federal Reserve Economic Data (FRED) API.

## [FredToolArgsSchema](entities/class:parrot_tools.fred_api.FredToolArgsSchema.md)

Schema for FredAPITool arguments.

## [AddConversationMessageInput](entities/class:parrot_tools.gigsmart.schemas.AddConversation-92fb6cdd.md)

Input for add_conversation_message tool.

## [AddOrganizationLocationInput](entities/class:parrot_tools.gigsmart.schemas.AddOrganization-076e28f3.md)

Input for add_organization_location tool.

## [AddOrganizationPositionInput](entities/class:parrot_tools.gigsmart.schemas.AddOrganization-c55eff9c.md)

Input for add_organization_position tool.

## [ApproveTimesheetInput](entities/class:parrot_tools.gigsmart.schemas.ApproveTimesheetInput.md)

Input for approve_timesheet tool.

## [GetEngagementInput](entities/class:parrot_tools.gigsmart.schemas.GetEngagementInput.md)

Input for get_engagement tool.

## [GetGigInput](entities/class:parrot_tools.gigsmart.schemas.GetGigInput.md)

Input for get_gig tool.

## [GetGigSummaryInput](entities/class:parrot_tools.gigsmart.schemas.GetGigSummaryInput.md)

Input for get_gig_summary tool.

## [GetOrganizationInput](entities/class:parrot_tools.gigsmart.schemas.GetOrganizationInput.md)

Input for get_organization tool.

## [GetPositionInput](entities/class:parrot_tools.gigsmart.schemas.GetPositionInput.md)

Input for get_position tool.

## [GetTimesheetInput](entities/class:parrot_tools.gigsmart.schemas.GetTimesheetInput.md)

Input for get_timesheet tool.

## [ListEngagementStatesInput](entities/class:parrot_tools.gigsmart.schemas.ListEngagementS-816b41ba.md)

Input for list_engagement_states tool.

## [ListEngagementsInput](entities/class:parrot_tools.gigsmart.schemas.ListEngagementsInput.md)

Input for list_engagements tool.

## [ListGigsInput](entities/class:parrot_tools.gigsmart.schemas.ListGigsInput.md)

Input for list_gigs tool.

## [ListLocationsInput](entities/class:parrot_tools.gigsmart.schemas.ListLocationsInput.md)

Input for list_locations tool.

## [ListOrganizationsInput](entities/class:parrot_tools.gigsmart.schemas.ListOrganizationsInput.md)

Input for list_organizations tool.

## [ListPositionsInput](entities/class:parrot_tools.gigsmart.schemas.ListPositionsInput.md)

Input for list_positions tool.

## [ListTimesheetsInput](entities/class:parrot_tools.gigsmart.schemas.ListTimesheetsInput.md)

Input for list_timesheets tool.

## [PlaceAutocompleteInput](entities/class:parrot_tools.gigsmart.schemas.PlaceAutocompleteInput.md)

Input for place_autocomplete tool.

## [PostShiftInput](entities/class:parrot_tools.gigsmart.schemas.PostShiftInput.md)

Input for post_shift tool.

## [RemoveTimesheetDisputeInput](entities/class:parrot_tools.gigsmart.schemas.RemoveTimesheet-aea453be.md)

Input for remove_timesheet_dispute tool.

## [SearchGigsInput](entities/class:parrot_tools.gigsmart.schemas.SearchGigsInput.md)

Input for search_gigs tool.

## [TransitionEngagementInput](entities/class:parrot_tools.gigsmart.schemas.TransitionEngag-077a400c.md)

Input for transition_engagement tool.

## [TransitionGigInput](entities/class:parrot_tools.gigsmart.schemas.TransitionGigInput.md)

Input for transition_gig tool.

## [GigSmartToolkit](entities/class:parrot_tools.gigsmart.toolkit.GigSmartToolkit.md)

LLM toolkit for interacting with the GigSmart staffing platform API.

## [AddPRCommentInput](entities/class:parrot_tools.gittoolkit.AddPRCommentInput.md)

Input payload for ``add_pr_comment``.

## [ComparePRVersionsInput](entities/class:parrot_tools.gittoolkit.ComparePRVersionsInput.md)

Input payload for ``compare_pr_versions``.

## [CompareVersionsResult](entities/class:parrot_tools.gittoolkit.CompareVersionsResult.md)

Return payload for ``compare_pr_versions``.

## [ContributorStats](entities/class:parrot_tools.gittoolkit.ContributorStats.md)

Aggregated stats for a single contributor across the repository's history.

## [ContributorWeek](entities/class:parrot_tools.gittoolkit.ContributorWeek.md)

One week's slice of a contributor's activity.

## [CreatePullRequestInput](entities/class:parrot_tools.gittoolkit.CreatePullRequestInput.md)

Input payload for ``create_pull_request``.

## [FileContentResult](entities/class:parrot_tools.gittoolkit.FileContentResult.md)

Return payload for ``get_file_content_at_ref``.

## [GeneratePatchInput](entities/class:parrot_tools.gittoolkit.GeneratePatchInput.md)

Input payload for ``generate_git_apply_patch``.

## [GetCodeFrequencyInput](entities/class:parrot_tools.gittoolkit.GetCodeFrequencyInput.md)

Input payload for ``get_code_frequency``.

## [GetCommitActivityInput](entities/class:parrot_tools.gittoolkit.GetCommitActivityInput.md)

Input payload for ``get_weekly_commit_activity``.

## [GetContributorStatsInput](entities/class:parrot_tools.gittoolkit.GetContributorStatsInput.md)

Input payload for ``get_contributor_stats``.

## [GetFileContentInput](entities/class:parrot_tools.gittoolkit.GetFileContentInput.md)

Input payload for ``get_file_content_at_ref``.

## [GetPullRequestDiffInput](entities/class:parrot_tools.gittoolkit.GetPullRequestDiffInput.md)

Input payload for ``get_pull_request_diff``.

## [GetPullRequestInput](entities/class:parrot_tools.gittoolkit.GetPullRequestInput.md)

Input payload for ``get_pull_request``.

## [GitHubFileChange](entities/class:parrot_tools.gittoolkit.GitHubFileChange.md)

Description of a file mutation when creating a pull request.

## [GitPatchFile](entities/class:parrot_tools.gittoolkit.GitPatchFile.md)

Represents a single file change for patch generation.

## [GitToolkit](entities/class:parrot_tools.gittoolkit.GitToolkit.md)

Toolkit dedicated to Git patch generation and GitHub pull requests.

## [GitToolkitError](entities/class:parrot_tools.gittoolkit.GitToolkitError.md)

Raised when the toolkit cannot satisfy a request.

## [GitToolkitInput](entities/class:parrot_tools.gittoolkit.GitToolkitInput.md)

Default configuration shared by all tools in the toolkit.

## [ListPullRequestsInput](entities/class:parrot_tools.gittoolkit.ListPullRequestsInput.md)

Input payload for ``list_pull_requests``.

## [RepositoryCredential](entities/class:parrot_tools.gittoolkit.RepositoryCredential.md)

Credentials + defaults for a single named repository in a registry.

## [SearchCodeResult](entities/class:parrot_tools.gittoolkit.SearchCodeResult.md)

Return payload for ``search_repo_code``.

## [SearchRepoCodeInput](entities/class:parrot_tools.gittoolkit.SearchRepoCodeInput.md)

Input payload for ``search_repo_code``.

## [SubmitPRReviewInput](entities/class:parrot_tools.gittoolkit.SubmitPRReviewInput.md)

Input payload for ``submit_pr_review``.

## [WeeklyCodeFrequency](entities/class:parrot_tools.gittoolkit.WeeklyCodeFrequency.md)

Repo-wide weekly additions/deletions totals.

## [GoogleAuthMode](entities/class:parrot_tools.google.base.GoogleAuthMode.md)

Authentication modes available for Google tools.

## [GoogleBaseTool](entities/class:parrot_tools.google.base.GoogleBaseTool.md)

Base class for Google Workspace tools leveraging :class:`GoogleClient`.

## [GoogleToolArgsSchema](entities/class:parrot_tools.google.base.GoogleToolArgsSchema.md)

Base schema for Google tool arguments.

## [GoogleBusinessTool](entities/class:parrot_tools.google.places.GoogleBusinessTool.md)

Tool for interacting with Google Business Profile API.

## [GoogleBusinessToolArgs](entities/class:parrot_tools.google.places.GoogleBusinessToolArgs.md)

Arguments schema for Google Business Tool.

## [GoogleLocationArgs](entities/class:parrot_tools.google.tools.GoogleLocationArgs.md)

Arguments schema for Google Location Finder.

## [GoogleLocationTool](entities/class:parrot_tools.google.tools.GoogleLocationTool.md)

Google Geocoding tool for location information.

## [GooglePlaceReviewsArgs](entities/class:parrot_tools.google.tools.GooglePlaceReviewsArgs.md)

Arguments schema for Google Place Reviews tool.

## [GooglePlacesBaseTool](entities/class:parrot_tools.google.tools.GooglePlacesBaseTool.md)

Shared helpers for Google Places based tools.

## [GoogleReviewsTool](entities/class:parrot_tools.google.tools.GoogleReviewsTool.md)

Retrieve reviews, rating, and metadata for a Google Place.

## [GoogleRouteArgs](entities/class:parrot_tools.google.tools.GoogleRouteArgs.md)

Arguments schema for Google Route Search.

## [GoogleRoutesTool](entities/class:parrot_tools.google.tools.GoogleRoutesTool.md)

Google Routes tool using the new Routes API v2.

## [GoogleSearchArgs](entities/class:parrot_tools.google.tools.GoogleSearchArgs.md)

Arguments schema for Google Search Tool.

## [GoogleSearchTool](entities/class:parrot_tools.google.tools.GoogleSearchTool.md)

Enhanced Google Search tool with content preview capabilities.

## [GoogleSiteSearchArgs](entities/class:parrot_tools.google.tools.GoogleSiteSearchArgs.md)

Arguments schema for Google Site Search Tool.

## [GoogleSiteSearchTool](entities/class:parrot_tools.google.tools.GoogleSiteSearchTool.md)

Google Site Search tool - extends GoogleSearchTool with site restriction.

## [GoogleTrafficArgs](entities/class:parrot_tools.google.tools.GoogleTrafficArgs.md)

Arguments schema for Google Place traffic tool.

## [GoogleTrafficTool](entities/class:parrot_tools.google.tools.GoogleTrafficTool.md)

Retrieve Google popular times data to estimate venue traffic.

## [GraphIndexComponent](entities/class:parrot_tools.graphindex.flowtask.GraphIndexComponent.md)

Flowtask component wrapper for the GraphIndex pipeline.

## [GraphIndexToolkit](entities/class:parrot_tools.graphindex.toolkit.GraphIndexToolkit.md)

Agent-facing tools for querying AND mutating the GraphIndex graph.

## [GoogleTTSArgs](entities/class:parrot_tools.gvoice.GoogleTTSArgs.md)

Arguments schema for GoogleTTSTool.

## [GoogleVoiceTool](entities/class:parrot_tools.gvoice.GoogleVoiceTool.md)

Tool for generating speech audio from text using Google Cloud Text-to-Speech.

## [IBISWorldSearchArgs](entities/class:parrot_tools.ibisworld.tool.IBISWorldSearchArgs.md)

Arguments schema for IBISWorld Search Tool.

## [IBISWorldTool](entities/class:parrot_tools.ibisworld.tool.IBISWorldTool.md)

IBISWorld search and content extraction tool.

## [IBKRToolkit](entities/class:parrot_tools.ibkr.IBKRToolkit.md)

Interactive Brokers trading toolkit for market data, orders, and portfolio management.

## [IBKRBackend](entities/class:parrot_tools.ibkr.backend.IBKRBackend.md)

Abstract base class for IBKR connection backends.

## [AccountSummary](entities/class:parrot_tools.ibkr.models.AccountSummary.md)

Account summary information.

## [BarData](entities/class:parrot_tools.ibkr.models.BarData.md)

Historical OHLCV bar.

## [ContractSpec](entities/class:parrot_tools.ibkr.models.ContractSpec.md)

Unified contract specification for IBKR instruments.

## [IBKRConfig](entities/class:parrot_tools.ibkr.models.IBKRConfig.md)

Configuration for IBKR connection.

## [OrderRequest](entities/class:parrot_tools.ibkr.models.OrderRequest.md)

Order placement request with validation.

## [OrderStatus](entities/class:parrot_tools.ibkr.models.OrderStatus.md)

Order status response from IBKR.

## [Position](entities/class:parrot_tools.ibkr.models.Position.md)

Account position for a single instrument.

## [Quote](entities/class:parrot_tools.ibkr.models.Quote.md)

Real-time quote data for a contract.

## [RiskConfig](entities/class:parrot_tools.ibkr.models.RiskConfig.md)

Risk management guardrails for agent-driven trading.

## [PortalBackend](entities/class:parrot_tools.ibkr.portal_backend.PortalBackend.md)

IBKR Client Portal REST API backend.

## [RiskCheckResult](entities/class:parrot_tools.ibkr.risk.RiskCheckResult.md)

Result of a risk check.

## [RiskManager](entities/class:parrot_tools.ibkr.risk.RiskManager.md)

Pre-trade risk management for IBKR orders.

## [TWSBackend](entities/class:parrot_tools.ibkr.tws_backend.TWSBackend.md)

TWS API backend using ib_async.

## [GigSmartAuth](entities/class:parrot_tools.interfaces.gigsmart.auth.GigSmartAuth.md)

OAuth 2.1 token lifecycle manager for the GigSmart API.

## [GigSmartClient](entities/class:parrot_tools.interfaces.gigsmart.client.GigSmartClient.md)

aiohttp-based GraphQL client for the GigSmart API.

## [GigSmartConfig](entities/class:parrot_tools.interfaces.gigsmart.config.GigSmartConfig.md)

Configuration for the GigSmart API client.

## [GigSmartAuthError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-e6a181a6.md)

Authentication or authorisation failure.

## [GigSmartConflictError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-646b45b3.md)

Conflict with the current resource state.

## [GigSmartError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-e06694ae.md)

Base exception for all GigSmart API errors.

## [GigSmartGraphQLError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-c213fa30.md)

Generic GraphQL protocol error.

## [GigSmartNotFoundError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-aab1d1c8.md)

Requested resource does not exist.

## [GigSmartRateLimitError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-b8dc98cc.md)

Rate limit exceeded (HTTP 429 / ``RATE_LIMITED`` extension code).

## [GigSmartTransportError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-77773e6e.md)

Network or server-side transport failure.

## [GigSmartValidationError](entities/class:parrot_tools.interfaces.gigsmart.exceptions.G-3824d8f4.md)

Input validation failure.

## [OAuthToken](entities/class:parrot_tools.interfaces.gigsmart.models.commo-72c25a49.md)

Parsed OAuth 2.1 token response from the GigSmart token endpoint.

## [RelayConnection](entities/class:parrot_tools.interfaces.gigsmart.models.commo-a263e361.md)

A Relay pagination connection wrapping a list of typed edges.

## [RelayEdge](entities/class:parrot_tools.interfaces.gigsmart.models.commo-27fdd9a8.md)

A single edge in a Relay connection.

## [RelayPageInfo](entities/class:parrot_tools.interfaces.gigsmart.models.commo-14697678.md)

GraphQL Relay PageInfo fragment.

## [AddEngagementInput](entities/class:parrot_tools.interfaces.gigsmart.models.engag-3846102c.md)

Input for the ``addEngagement`` mutation.

## [Engagement](entities/class:parrot_tools.interfaces.gigsmart.models.engag-19f8c129.md)

A GigSmart engagement resource linking a worker to a gig.

## [TransitionEngagementInput](entities/class:parrot_tools.interfaces.gigsmart.models.engag-1bfeb552.md)

Input for the single ``transitionEngagement`` mutation.

## [Gig](entities/class:parrot_tools.interfaces.gigsmart.models.gig.Gig.md)

A GigSmart shift/gig resource.

## [PostShiftInput](entities/class:parrot_tools.interfaces.gigsmart.models.gig.P-945d4b99.md)

Input for the ``postShift`` mutation.

## [TransitionGigInput](entities/class:parrot_tools.interfaces.gigsmart.models.gig.T-83bbb157.md)

Input for the ``transitionGig`` mutation.

## [AddOrganizationLocationInput](entities/class:parrot_tools.interfaces.gigsmart.models.locat-e1b502a2.md)

Input for the ``addOrganizationLocation`` mutation.

## [OrganizationLocation](entities/class:parrot_tools.interfaces.gigsmart.models.locat-70b67ecc.md)

A location belonging to a GigSmart organisation.

## [PlaceResult](entities/class:parrot_tools.interfaces.gigsmart.models.locat-efef7e8d.md)

A single address suggestion from the placeAutocomplete query.

## [AddOrganizationPositionInput](entities/class:parrot_tools.interfaces.gigsmart.models.posit-b103baea.md)

Input for the ``addOrganizationPosition`` mutation.

## [Position](entities/class:parrot_tools.interfaces.gigsmart.models.posit-22486bf9.md)

A GigSmart organisation position template.

## [AddEngagementDisputeInput](entities/class:parrot_tools.interfaces.gigsmart.models.times-e6fa9ba4.md)

Input for the ``addEngagementDispute`` mutation.

## [ApproveEngagementTimesheetInput](entities/class:parrot_tools.interfaces.gigsmart.models.times-cb0b7f94.md)

Input for the ``approveEngagementTimesheet`` mutation.

## [EngagementTimesheet](entities/class:parrot_tools.interfaces.gigsmart.models.times-6bb2d42b.md)

A GigSmart engagement timesheet record.

## [RemoveEngagementTimesheetInput](entities/class:parrot_tools.interfaces.gigsmart.models.times-69dc90a5.md)

Input for the ``removeEngagementTimesheet`` mutation.

## [SetEngagementDisputeApprovalInput](entities/class:parrot_tools.interfaces.gigsmart.models.times-d09c1da2.md)

Input for the ``setEngagementDisputeApproval`` mutation.

## [WorkdayConfig](entities/class:parrot_tools.interfaces.workday.config.WorkdayConfig.md)

Explicit Workday credentials / tenant; each optional field falls back

## [ApplicantType](entities/class:parrot_tools.interfaces.workday.handlers.appl-49343bcd.md)

Handler for the Workday Get_Applicants operation from Recruiting API.

## [WorkdayTypeBase](entities/class:parrot_tools.interfaces.workday.handlers.base-1daea88e.md)

Base class for Workday operation types.

## [WorkdayWriteTypeBase](entities/class:parrot_tools.interfaces.workday.handlers.base-10551ca7.md)

Single-call (non-paginated) write base for Workday write operations.

## [CandidateType](entities/class:parrot_tools.interfaces.workday.handlers.cand-f1b26fb5.md)

Handler para la operación Get_Candidates del Workday Recruiting API (v45.0).

## [CostCenterType](entities/class:parrot_tools.interfaces.workday.handlers.cost-bab207ca.md)

Handler for the Workday Get_Cost_Centers operation.

## [CustomPunchFieldReportType](entities/class:parrot_tools.interfaces.workday.handlers.cust-6c76157e.md)

Handler for the Custom Punch - Field Report.

## [CustomPunchFieldReportRestType](entities/class:parrot_tools.interfaces.workday.handlers.cust-b4a6c054.md)

Fetch the Custom Punch - Field Report via REST (customreport2).

## [CustomReportType](entities/class:parrot_tools.interfaces.workday.handlers.cust-676e6868.md)

Generic handler for ANY Workday RaaS custom report.

## [ImportReportedTimeBlocksType](entities/class:parrot_tools.interfaces.workday.handlers.impo-317c784e.md)

Handler for ``Import_Reported_Time_Blocks`` (batch async import).

## [ImportTimeClockEventsType](entities/class:parrot_tools.interfaces.workday.handlers.impo-49eb466e.md)

Handler for ``Import_Time_Clock_Events`` (batch async import).

## [JobPostingSiteType](entities/class:parrot_tools.interfaces.workday.handlers.job_-4acae829.md)

Handler for the Workday Get_Job_Posting_Sites operation.

## [JobPostingType](entities/class:parrot_tools.interfaces.workday.handlers.job_-f682967f.md)

Handler for the Workday Get_Job_Postings operation.

## [JobRequisitionType](entities/class:parrot_tools.interfaces.workday.handlers.job_-4d58a2e7.md)

Handler for the Workday Get_Job_Requisitions operation.

## [LocationHierarchyAssignmentsType](entities/class:parrot_tools.interfaces.workday.handlers.loca-d106e8ec.md)

Handler for Get_Location_Hierarchy_Organization_Assignments operation.

## [LocationType](entities/class:parrot_tools.interfaces.workday.handlers.loca-8eea49a4.md)

Handler for the Workday Get_Locations operation.

## [GetOrganization](entities/class:parrot_tools.interfaces.workday.handlers.orga-197ce5ea.md)

Handler for Get_Organization operation.

## [OrganizationType](entities/class:parrot_tools.interfaces.workday.handlers.orga-a71c2336.md)

Handler for the Workday Get_Organizations operation.

## [CompanyPaymentDatesType](entities/class:parrot_tools.interfaces.workday.handlers.payr-0e84a6b8.md)

Get_Company_Payment_Dates — company payment dates in a window.

## [PayrollBalancesType](entities/class:parrot_tools.interfaces.workday.handlers.payr-7a7c57e2.md)

Get_Payroll_Balances — payroll balances for a worker.

## [PayrollResultsType](entities/class:parrot_tools.interfaces.workday.handlers.payr-667f52ec.md)

Get_Payroll_Results — historical / off-cycle payroll results for a worker.

## [PutTimeClockEventsType](entities/class:parrot_tools.interfaces.workday.handlers.put_-0c515cb9.md)

Handler for ``Put_Time_Clock_Events`` (real-time clock-event submission).

## [RecruitingAgencyUsersType](entities/class:parrot_tools.interfaces.workday.handlers.recr-901b0fb8.md)

Handler for Get_Recruiting_Agency_Users operation from Recruiting API.

## [ReferencesType](entities/class:parrot_tools.interfaces.workday.handlers.refe-d045d5fb.md)

Handler for the Workday ``Get_References`` operation (Integrations service).

## [TimeBlockReportType](entities/class:parrot_tools.interfaces.workday.handlers.time-fc33d091.md)

Handler for the Extract Time Blocks Navigator custom report.

## [TimeBlockType](entities/class:parrot_tools.interfaces.workday.handlers.time-26b74767.md)

Handler for the Workday Get_Calculated_Time_Blocks operation.

## [TimeOffBalanceType](entities/class:parrot_tools.interfaces.workday.handlers.time-7eafdfc9.md)

Handles Get_Time_Off_Plan_Balances operation for Workday Absence Management API.

## [TimeOffEligibilityType](entities/class:parrot_tools.interfaces.workday.handlers.time-f5fc85ea.md)

Handler for ``Get_Time_Off_Types`` (Absence Management read op).

## [RequestTimeOffType](entities/class:parrot_tools.interfaces.workday.handlers.time-464482a0.md)

Handler for ``Request_Time_Off`` (Absence Management write op).

## [TimeRequestType](entities/class:parrot_tools.interfaces.workday.handlers.time-5bd51dbb.md)

Handles Get_Time_Requests operation for Workday Time Tracking API.

## [WorkerType](entities/class:parrot_tools.interfaces.workday.handlers.work-f5a21e78.md)

Handler for the Workday Get_Workers operation, batching pages

## [Applicant](entities/class:parrot_tools.interfaces.workday.models.applic-66a3950c.md)

Pydantic model for a Workday Applicant/Pre-hire record.

## [Candidate](entities/class:parrot_tools.interfaces.workday.models.candid-268c960c.md)

Pydantic model for a Workday Candidate record.

## [ClockEvent](entities/class:parrot_tools.interfaces.workday.models.clock_-faf0ecfb.md)

One Time Clock Event for Put_Time_Clock_Events / Import_Time_Clock_Events.

## [ClockEventResult](entities/class:parrot_tools.interfaces.workday.models.clock_-22370fac.md)

Per-row submission outcome echoed back into the flow (G6).

## [ReportedTimeBlock](entities/class:parrot_tools.interfaces.workday.models.clock_-fbf9691e.md)

One reported time block for Import_Reported_Time_Blocks.

## [CostCenter](entities/class:parrot_tools.interfaces.workday.models.cost_c-a18c1f3d.md)

Complete cost center model based on Workday Get_Cost_Centers API documentation.

## [CustomPunchFieldReportEntry](entities/class:parrot_tools.interfaces.workday.models.custom-c220d84b.md)

Model for a single entry in the Custom Punch - Field Report.

## [WorkerGroup](entities/class:parrot_tools.interfaces.workday.models.custom-aa8661e0.md)

Worker group information containing employee details.

## [JobPosting](entities/class:parrot_tools.interfaces.workday.models.job_po-ae7591ce.md)

Job Posting model based on Workday Get_Job_Postings API.

## [JobPostingSite](entities/class:parrot_tools.interfaces.workday.models.job_po-d31b8668.md)

Job Posting Site model based on Workday Get_Job_Posting_Sites API.

## [JobRequisition](entities/class:parrot_tools.interfaces.workday.models.job_re-35bd2f01.md)

Complete job requisition model based on Workday Get_Job_Requisitions API documentation.

## [Location](entities/class:parrot_tools.interfaces.workday.models.locati-726a0686.md)

Pydantic model for a Workday location record.

## [LocationHierarchyAssignment](entities/class:parrot_tools.interfaces.workday.models.locati-5b7e1354.md)

Model for location hierarchy organization assignment.

## [LocationHierarchyAssignmentsResponse](entities/class:parrot_tools.interfaces.workday.models.locati-e78db179.md)

Model for the complete location hierarchy assignments response.

## [LocationHierarchyReference](entities/class:parrot_tools.interfaces.workday.models.locati-59485f48.md)

Model for location hierarchy reference.

## [OrganizationAssignment](entities/class:parrot_tools.interfaces.workday.models.locati-fb1a1ded.md)

Model for organization assignment by type.

## [OrganizationReference](entities/class:parrot_tools.interfaces.workday.models.locati-63648211.md)

Model for organization reference in assignments.

## [OrganizationTypeReference](entities/class:parrot_tools.interfaces.workday.models.locati-84daaf76.md)

Model for organization type reference.

## [Organization](entities/class:parrot_tools.interfaces.workday.models.organi-cc698034.md)

Complete organization model based on actual Workday payload.

## [WorkdayReference](entities/class:parrot_tools.interfaces.workday.models.refere-4d4db848.md)

Single Reference instance returned by Workday Get_References.

## [TimeBlock](entities/class:parrot_tools.interfaces.workday.models.time_b-473442d4.md)

Pydantic model for a Workday calculated time block record.

## [TimeOffBalance](entities/class:parrot_tools.interfaces.workday.models.time_o-9b210474.md)

Pydantic model for a Workday Time Off Plan Balance record.

## [TimeOffEligibility](entities/class:parrot_tools.interfaces.workday.models.time_o-ea7af57d.md)

Pydantic model for a Workday eligible time-off type.

## [TimeRequest](entities/class:parrot_tools.interfaces.workday.models.time_r-c7520084.md)

Pydantic model for a Workday time request record.

## [ManagementChainLevel](entities/class:parrot_tools.interfaces.workday.models.worker-1403f032.md)

Model for a single level in the management chain

## [Worker](entities/class:parrot_tools.interfaces.workday.models.worker.Worker.md)

Pydantic model for a Workday worker record.

## [WorkdayService](entities/class:parrot_tools.interfaces.workday.service.WorkdayService.md)

Workday operational interface — composable without a FlowComponent.

## [AddAttachmentInput](entities/class:parrot_tools.jiratoolkit.AddAttachmentInput.md)

Input for adding an attachment to an issue.

## [AddCommentInput](entities/class:parrot_tools.jiratoolkit.AddCommentInput.md)

Input for adding a comment to an issue.

## [AddComponentInput](entities/class:parrot_tools.jiratoolkit.AddComponentInput.md)

Input for adding a component to an issue by name.

## [AddWatcherInput](entities/class:parrot_tools.jiratoolkit.AddWatcherInput.md)

Input for adding a watcher to an issue.

## [AddWorklogInput](entities/class:parrot_tools.jiratoolkit.AddWorklogInput.md)

Input for adding a worklog to an issue.

## [AggregateJiraDataInput](entities/class:parrot_tools.jiratoolkit.AggregateJiraDataInput.md)

Input for aggregating stored Jira data.

## [AssignIssueInput](entities/class:parrot_tools.jiratoolkit.AssignIssueInput.md)

Input for assigning an issue to a user.

## [ChangeAssigneeInput](entities/class:parrot_tools.jiratoolkit.ChangeAssigneeInput.md)

Input for changing assignee.

## [ChangeReporterInput](entities/class:parrot_tools.jiratoolkit.ChangeReporterInput.md)

Input for changing the reporter of an issue.

## [ConfigureClientInput](entities/class:parrot_tools.jiratoolkit.ConfigureClientInput.md)

Input for re-configuring the Jira client.

## [CountIssuesInput](entities/class:parrot_tools.jiratoolkit.CountIssuesInput.md)

Optimized input for counting issues - requests minimal fields.

## [CreateIssueInput](entities/class:parrot_tools.jiratoolkit.CreateIssueInput.md)

Input for creating a new issue.

## [FindIssuesByAssigneeInput](entities/class:parrot_tools.jiratoolkit.FindIssuesByAssigneeInput.md)

Input for finding issues assigned to a given user.

## [FindUserInput](entities/class:parrot_tools.jiratoolkit.FindUserInput.md)

Input for finding a user.

## [GetComponentByNameInput](entities/class:parrot_tools.jiratoolkit.GetComponentByNameInput.md)

Input for finding a component by name.

## [GetComponentsInput](entities/class:parrot_tools.jiratoolkit.GetComponentsInput.md)

Input for listing project components.

## [GetIssueInput](entities/class:parrot_tools.jiratoolkit.GetIssueInput.md)

Input for getting a single issue.

## [GetIssueTypesInput](entities/class:parrot_tools.jiratoolkit.GetIssueTypesInput.md)

Input for listing issue types.

## [GetMyTicketsInput](entities/class:parrot_tools.jiratoolkit.GetMyTicketsInput.md)

Input for retrieving the CURRENT (authenticated) user's Jira tickets.

## [GetProjectsInput](entities/class:parrot_tools.jiratoolkit.GetProjectsInput.md)

Input for listing projects.

## [GetTransitionsInput](entities/class:parrot_tools.jiratoolkit.GetTransitionsInput.md)

Input for getting available transitions for an issue.

## [JiraInput](entities/class:parrot_tools.jiratoolkit.JiraInput.md)

Default input for Jira tools: holds auth + default project context.

## [JiraToolEnvelope](entities/class:parrot_tools.jiratoolkit.JiraToolEnvelope.md)

Uniform return shape for all JiraToolkit read methods.

## [JiraToolkit](entities/class:parrot_tools.jiratoolkit.JiraToolkit.md)

Toolkit for interacting with Jira via pycontribs/jira.

## [ListHistoryInput](entities/class:parrot_tools.jiratoolkit.ListHistoryInput.md)

Input for listing history.

## [SearchIssuesInput](entities/class:parrot_tools.jiratoolkit.SearchIssuesInput.md)

Input for searching issues with JQL.

## [SearchUsersInput](entities/class:parrot_tools.jiratoolkit.SearchUsersInput.md)

Input for searching users.

## [SetAcceptanceCriteriaInput](entities/class:parrot_tools.jiratoolkit.SetAcceptanceCriteriaInput.md)

Input for setting acceptance criteria on an issue.

## [StructuredOutputOptions](entities/class:parrot_tools.jiratoolkit.StructuredOutputOptions.md)

Options to shape the output of Jira items into either a whitelist or a Pydantic model.

## [TagInput](entities/class:parrot_tools.jiratoolkit.TagInput.md)

Input for tag operations.

## [TicketIdInput](entities/class:parrot_tools.jiratoolkit.TicketIdInput.md)

Input for generic ticket operations.

## [TransitionIssueInput](entities/class:parrot_tools.jiratoolkit.TransitionIssueInput.md)

Input for transitioning an issue.

## [TransitionToInput](entities/class:parrot_tools.jiratoolkit.TransitionToInput.md)

Input for walking an issue to a target status across a custom workflow.

## [UpdateIssueInput](entities/class:parrot_tools.jiratoolkit.UpdateIssueInput.md)

Input for updating an existing issue.

## [VerifyAuthInput](entities/class:parrot_tools.jiratoolkit.VerifyAuthInput.md)

Input for verifying Jira authentication.

## [K8sOperationResult](entities/class:parrot_tools.kubernetes.config.K8sOperationResult.md)

Result of a Kubernetes operation.

## [KubernetesConfig](entities/class:parrot_tools.kubernetes.config.KubernetesConfig.md)

Configuration for KubernetesExecutor.

## [KubernetesExecutor](entities/class:parrot_tools.kubernetes.executor.KubernetesExecutor.md)

Async Kubernetes client wrapper.

## [KubernetesToolkit](entities/class:parrot_tools.kubernetes.toolkit.KubernetesToolkit.md)

Kubernetes cluster management toolkit.

## [LeadIQSearchInput](entities/class:parrot_tools.leadiq.tool.LeadIQSearchInput.md)

Input schema shared by all LeadIQ search tools.

## [LeadIQToolkit](entities/class:parrot_tools.leadiq.tool.LeadIQToolkit.md)

Toolkit for querying the LeadIQ GraphQL API for company and people data.

## [MassiveCache](entities/class:parrot_tools.massive.cache.MassiveCache.md)

Cache layer for MassiveToolkit with per-endpoint TTLs.

## [MassiveAPIError](entities/class:parrot_tools.massive.client.MassiveAPIError.md)

Base error for Massive API calls.

## [MassiveClient](entities/class:parrot_tools.massive.client.MassiveClient.md)

Async REST client for Massive API with retry and rate limit handling.

## [MassiveRateLimitError](entities/class:parrot_tools.massive.client.MassiveRateLimitError.md)

Rate limit exceeded (429).

## [MassiveTransientError](entities/class:parrot_tools.massive.client.MassiveTransientError.md)

Transient error (5xx, timeouts).

## [AnalystAction](entities/class:parrot_tools.massive.models.AnalystAction.md)

Single analyst rating action.

## [AnalystRatingsDerived](entities/class:parrot_tools.massive.models.AnalystRatingsDerived.md)

Derived metrics for analyst ratings.

## [AnalystRatingsInput](entities/class:parrot_tools.massive.models.AnalystRatingsInput.md)

Input model for get_analyst_ratings tool.

## [AnalystRatingsOutput](entities/class:parrot_tools.massive.models.AnalystRatingsOutput.md)

Output model for get_analyst_ratings.

## [ConsensusRating](entities/class:parrot_tools.massive.models.ConsensusRating.md)

Consensus rating summary.

## [EarningsDataInput](entities/class:parrot_tools.massive.models.EarningsDataInput.md)

Input model for get_earnings_data tool.

## [EarningsDerived](entities/class:parrot_tools.massive.models.EarningsDerived.md)

Derived metrics for earnings.

## [EarningsOutput](entities/class:parrot_tools.massive.models.EarningsOutput.md)

Output model for get_earnings_data.

## [EarningsRecord](entities/class:parrot_tools.massive.models.EarningsRecord.md)

Single earnings record.

## [GreeksData](entities/class:parrot_tools.massive.models.GreeksData.md)

Greeks data for an options contract.

## [NextEarnings](entities/class:parrot_tools.massive.models.NextEarnings.md)

Next scheduled earnings.

## [OptionsChainInput](entities/class:parrot_tools.massive.models.OptionsChainInput.md)

Input model for get_options_chain_enriched tool.

## [OptionsChainOutput](entities/class:parrot_tools.massive.models.OptionsChainOutput.md)

Output model for get_options_chain_enriched.

## [OptionsContract](entities/class:parrot_tools.massive.models.OptionsContract.md)

Single options contract with Greeks and pricing.

## [ShortInterestDerived](entities/class:parrot_tools.massive.models.ShortInterestDerived.md)

Derived metrics for short interest.

## [ShortInterestInput](entities/class:parrot_tools.massive.models.ShortInterestInput.md)

Input model for get_short_interest tool.

## [ShortInterestOutput](entities/class:parrot_tools.massive.models.ShortInterestOutput.md)

Output model for get_short_interest.

## [ShortInterestRecord](entities/class:parrot_tools.massive.models.ShortInterestRecord.md)

Single short interest record.

## [ShortVolumeDerived](entities/class:parrot_tools.massive.models.ShortVolumeDerived.md)

Derived metrics for short volume.

## [ShortVolumeInput](entities/class:parrot_tools.massive.models.ShortVolumeInput.md)

Input model for get_short_volume tool.

## [ShortVolumeOutput](entities/class:parrot_tools.massive.models.ShortVolumeOutput.md)

Output model for get_short_volume.

## [ShortVolumeRecord](entities/class:parrot_tools.massive.models.ShortVolumeRecord.md)

Single short volume record.

## [MassiveToolkit](entities/class:parrot_tools.massive.toolkit.MassiveToolkit.md)

Premium market data enrichment from Massive.com (ex-Polygon.io).

## [MathTool](entities/class:parrot_tools.math.MathTool.md)

A tool for performing basic arithmetic operations.

## [MathToolArgs](entities/class:parrot_tools.math.MathToolArgs.md)

Arguments schema for MathTool.

## [WhatsAppSendInput](entities/class:parrot_tools.messaging.whatsapp.WhatsAppSendInput.md)

Input schema for sending WhatsApp messages.

## [WhatsAppTool](entities/class:parrot_tools.messaging.whatsapp.WhatsAppTool.md)

Send WhatsApp messages through the whatsmeow bridge.

## [MetadataTool](entities/class:parrot_tools.metadata.MetadataTool.md)

Expose DataFrame metadata with comprehensive EDA capabilities.

## [MetadataToolArgs](entities/class:parrot_tools.metadata.MetadataToolArgs.md)

Arguments for the MetadataTool.

## [MonteCarloInput](entities/class:parrot_tools.montecarlo.MonteCarloInput.md)

Input schema for MonteCarloSimulationTool.

## [MonteCarloSimulationTool](entities/class:parrot_tools.montecarlo.MonteCarloSimulationTool.md)

Run Monte Carlo simulations to provide probability distributions of outcomes.

## [VariableDistribution](entities/class:parrot_tools.montecarlo.VariableDistribution.md)

Distribution specification for a variable.

## [ChatMessagesFromUserInput](entities/class:parrot_tools.msteams.ChatMessagesFromUserInput.md)

Input schema for extracting messages from a specific user in a chat.

## [CreateAdaptiveCardInput](entities/class:parrot_tools.msteams.CreateAdaptiveCardInput.md)

Input schema for creating an Adaptive Card.

## [CreateChatInput](entities/class:parrot_tools.msteams.CreateChatInput.md)

Input schema for creating a one-on-one chat.

## [ExtractChannelMessagesInput](entities/class:parrot_tools.msteams.ExtractChannelMessagesInput.md)

Input schema for extracting channel messages.

## [FindChannelByNameInput](entities/class:parrot_tools.msteams.FindChannelByNameInput.md)

Input schema for finding a channel by name within a team.

## [FindChatByNameInput](entities/class:parrot_tools.msteams.FindChatByNameInput.md)

Input schema for finding a chat by name/topic.

## [FindOneOnOneChatInput](entities/class:parrot_tools.msteams.FindOneOnOneChatInput.md)

Input schema for finding a one-on-one chat between two users.

## [FindTeamByNameInput](entities/class:parrot_tools.msteams.FindTeamByNameInput.md)

Input schema for finding a team by name.

## [GetChannelDetailsInput](entities/class:parrot_tools.msteams.GetChannelDetailsInput.md)

Input schema for getting channel details.

## [GetChannelMembersInput](entities/class:parrot_tools.msteams.GetChannelMembersInput.md)

Input schema for getting channel members.

## [GetChatMessagesInput](entities/class:parrot_tools.msteams.GetChatMessagesInput.md)

Input schema for getting messages from a chat.

## [GetMeetingTranscriptInput](entities/class:parrot_tools.msteams.GetMeetingTranscriptInput.md)

Input schema for downloading a meeting transcript.

## [GetOnlineMeetingIdInput](entities/class:parrot_tools.msteams.GetOnlineMeetingIdInput.md)

Input schema for getting online meeting ID from a calendar event by subject.

## [GetUserInput](entities/class:parrot_tools.msteams.GetUserInput.md)

Input schema for getting user information.

## [ListMeetingTranscriptsInput](entities/class:parrot_tools.msteams.ListMeetingTranscriptsInput.md)

Input schema for listing meeting transcripts.

## [ListUserChatsInput](entities/class:parrot_tools.msteams.ListUserChatsInput.md)

Input schema for listing user chats.

## [MSTeamsToolkit](entities/class:parrot_tools.msteams.MSTeamsToolkit.md)

Toolkit for interacting with Microsoft Teams via Microsoft Graph API.

## [SendDirectMessageInput](entities/class:parrot_tools.msteams.SendDirectMessageInput.md)

Input schema for sending direct message to a user.

## [SendMessageToChannelInput](entities/class:parrot_tools.msteams.SendMessageToChannelInput.md)

Input schema for sending message to a Teams channel.

## [SendMessageToChatInput](entities/class:parrot_tools.msteams.SendMessageToChatInput.md)

Input schema for sending message to a Teams chat.

## [MSWordArgs](entities/class:parrot_tools.msword.MSWordArgs.md)

Arguments schema for MS Word Document generation.

## [MSWordTool](entities/class:parrot_tools.msword.MSWordTool.md)

Microsoft Word Document Generation Tool.

## [WordToMarkdownTool](entities/class:parrot_tools.msword.WordToMarkdownTool.md)

Tool for converting Word documents to Markdown format.

## [EnhancedDatabaseTool](entities/class:parrot_tools.multidb.EnhancedDatabaseTool.md)

Enhanced DatabaseTool with intelligent multi-tier schema caching.

## [MetadataFormat](entities/class:parrot_tools.multidb.MetadataFormat.md)

Supported metadata formats for schema representation.

## [SchemaMetadataCache](entities/class:parrot_tools.multidb.SchemaMetadataCache.md)

Multi-tier caching system for database schema metadata.

## [TableMetadata](entities/class:parrot_tools.multidb.TableMetadata.md)

Optimized table metadata structure designed for both caching efficiency

## [MultiStoreSearchSchema](entities/class:parrot_tools.multistoresearch.MultiStoreSearchSchema.md)

Input schema for multi-store search tool

## [MultiStoreSearchTool](entities/class:parrot_tools.multistoresearch.MultiStoreSearchTool.md)

Multi-store search tool with BM25 reranking.

## [NavigatorPageIndex](entities/class:parrot_tools.navigator.prompt.NavigatorPageIndex.md)

Manages the PageIndex tree for Navigator knowledge base.

## [AssignModuleClientInput](entities/class:parrot_tools.navigator.schemas.AssignModuleClientInput.md)

Input for assigning a module to a client.

## [AssignModuleGroupInput](entities/class:parrot_tools.navigator.schemas.AssignModuleGroupInput.md)

Input for assigning a module to a group (permissions).

## [CloneDashboardInput](entities/class:parrot_tools.navigator.schemas.CloneDashboardInput.md)

Input for cloning a dashboard with all its widgets.

## [DashboardCreateInput](entities/class:parrot_tools.navigator.schemas.DashboardCreateInput.md)

Input for creating a new dashboard.

## [DashboardUpdateInput](entities/class:parrot_tools.navigator.schemas.DashboardUpdateInput.md)

Input for updating an existing dashboard.

## [EntityLookupInput](entities/class:parrot_tools.navigator.schemas.EntityLookupInput.md)

Input for looking up an entity by ID or slug.

## [ExecuteSqlInput](entities/class:parrot_tools.navigator.schemas.ExecuteSqlInput.md)

Input for executing a raw SQL statement (DDL or DML).

## [ModuleCreateInput](entities/class:parrot_tools.navigator.schemas.ModuleCreateInput.md)

Input for creating a new module inside a Program.

## [ModuleUpdateInput](entities/class:parrot_tools.navigator.schemas.ModuleUpdateInput.md)

Input for updating an existing Module.

## [ProgramCreateInput](entities/class:parrot_tools.navigator.schemas.ProgramCreateInput.md)

Input for creating a new Navigator program.

## [ProgramUpdateInput](entities/class:parrot_tools.navigator.schemas.ProgramUpdateInput.md)

Input for updating an existing Program.

## [PublishDashboardInput](entities/class:parrot_tools.navigator.schemas.PublishDashboardInput.md)

Input for publishing a draft dashboard (promote to system-wide).

## [SearchInput](entities/class:parrot_tools.navigator.schemas.SearchInput.md)

Input for searching across Navigator entities.

## [WidgetCreateInput](entities/class:parrot_tools.navigator.schemas.WidgetCreateInput.md)

Input for creating a widget in a dashboard.

## [WidgetUpdateInput](entities/class:parrot_tools.navigator.schemas.WidgetUpdateInput.md)

Input for updating an existing widget.

## [NavigatorToolkit](entities/class:parrot_tools.navigator.toolkit.NavigatorToolkit.md)

Toolkit for managing the Navigator platform.

## [NetworkNinjaArgsSchema](entities/class:parrot_tools.networkninja.NetworkNinjaArgsSchema.md)

Schema for NetworkNinja API calls.

## [NetworkNinjaTool](entities/class:parrot_tools.networkninja.NetworkNinjaTool.md)

NetworkNinja Batch Processing API Tool.

## [FileType](entities/class:parrot_tools.notification.FileType.md)

File types for smart handling.

## [NotificationInput](entities/class:parrot_tools.notification.NotificationInput.md)

Input schema for notification tool.

## [NotificationTool](entities/class:parrot_tools.notification.NotificationTool.md)

Unified notification tool for sending messages through multiple channels.

## [NotificationType](entities/class:parrot_tools.notification.NotificationType.md)

Supported notification types.

## [O365AuthMode](entities/class:parrot_tools.o365.base.O365AuthMode.md)

Authentication modes for Office365 tools.

## [O365Tool](entities/class:parrot_tools.o365.base.O365Tool.md)

Base class for Office365 tools that interact with Microsoft Graph API.

## [O365ToolArgsSchema](entities/class:parrot_tools.o365.base.O365ToolArgsSchema.md)

Base schema for Office365 tool arguments.

## [Office365FileManagementToolkit](entities/class:parrot_tools.o365.bundle.Office365FileManagem-475b214d.md)

Complete Office365 file management toolkit (SharePoint + OneDrive).

## [OneDriveToolkit](entities/class:parrot_tools.o365.bundle.OneDriveToolkit.md)

OneDrive file management toolkit for AI-Parrot agents.

## [SharePointToolkit](entities/class:parrot_tools.o365.bundle.SharePointToolkit.md)

SharePoint file management toolkit for AI-Parrot agents.

## [CreateEventArgs](entities/class:parrot_tools.o365.events.CreateEventArgs.md)

Arguments for creating a calendar event.

## [CreateEventTool](entities/class:parrot_tools.o365.events.CreateEventTool.md)

Tool for creating calendar events in Office365.

## [GetEventArgs](entities/class:parrot_tools.o365.events.GetEventArgs.md)

Arguments for retrieving a single calendar event by ID.

## [GetEventTool](entities/class:parrot_tools.o365.events.GetEventTool.md)

Tool for retrieving a single calendar event by its ID.

## [ListEventArgs](entities/class:parrot_tools.o365.events.ListEventArgs.md)

Arguments for listing calendar events.

## [ListEventsTool](entities/class:parrot_tools.o365.events.ListEventsTool.md)

Tool for listing events in the user's calendar.

## [UpdateEventArgs](entities/class:parrot_tools.o365.events.UpdateEventArgs.md)

Arguments for updating a calendar event.

## [UpdateEventTool](entities/class:parrot_tools.o365.events.UpdateEventTool.md)

Tool for updating an existing calendar event in Office365.

## [CreateDraftMessageArgs](entities/class:parrot_tools.o365.mail.CreateDraftMessageArgs.md)

Arguments for creating a draft email message.

## [CreateDraftMessageTool](entities/class:parrot_tools.o365.mail.CreateDraftMessageTool.md)

Tool for creating draft email messages in Office365.

## [DownloadAttachmentArgs](entities/class:parrot_tools.o365.mail.DownloadAttachmentArgs.md)

Arguments for downloading an email attachment.

## [DownloadAttachmentTool](entities/class:parrot_tools.o365.mail.DownloadAttachmentTool.md)

Tool for downloading email attachments to local storage.

## [GetMessageArgs](entities/class:parrot_tools.o365.mail.GetMessageArgs.md)

Arguments for retrieving a specific message.

## [GetMessageTool](entities/class:parrot_tools.o365.mail.GetMessageTool.md)

Tool for retrieving a specific email message by its ID.

## [ListMessagesArgs](entities/class:parrot_tools.o365.mail.ListMessagesArgs.md)

Arguments for listing email messages.

## [ListMessagesTool](entities/class:parrot_tools.o365.mail.ListMessagesTool.md)

Tool for listing email messages from a specified folder.

## [SearchEmailArgs](entities/class:parrot_tools.o365.mail.SearchEmailArgs.md)

Arguments for searching emails.

## [SearchEmailTool](entities/class:parrot_tools.o365.mail.SearchEmailTool.md)

Tool for searching emails in Office365.

## [SendEmailArgs](entities/class:parrot_tools.o365.mail.SendEmailArgs.md)

Arguments for sending an email.

## [SendEmailTool](entities/class:parrot_tools.o365.mail.SendEmailTool.md)

Tool for sending emails directly in Office365.

## [Office365Toolkit](entities/class:parrot_tools.o365.oauth_toolkit.Office365Toolkit.md)

Microsoft Graph toolkit with delegated per-user OAuth tokens.

## [DownloadOneDriveFileArgs](entities/class:parrot_tools.o365.onedrive.DownloadOneDriveFileArgs.md)

Arguments for downloading OneDrive files.

## [DownloadOneDriveFileTool](entities/class:parrot_tools.o365.onedrive.DownloadOneDriveFileTool.md)

Tool for downloading files from OneDrive.

## [ListOneDriveFilesArgs](entities/class:parrot_tools.o365.onedrive.ListOneDriveFilesArgs.md)

Arguments for listing OneDrive files.

## [ListOneDriveFilesTool](entities/class:parrot_tools.o365.onedrive.ListOneDriveFilesTool.md)

Tool for listing files in OneDrive.

## [SearchOneDriveFilesArgs](entities/class:parrot_tools.o365.onedrive.SearchOneDriveFilesArgs.md)

Arguments for searching OneDrive files.

## [SearchOneDriveFilesTool](entities/class:parrot_tools.o365.onedrive.SearchOneDriveFilesTool.md)

Tool for searching files in OneDrive.

## [UploadOneDriveFileArgs](entities/class:parrot_tools.o365.onedrive.UploadOneDriveFileArgs.md)

Arguments for uploading files to OneDrive.

## [UploadOneDriveFileTool](entities/class:parrot_tools.o365.onedrive.UploadOneDriveFileTool.md)

Tool for uploading files to OneDrive.

## [DownloadSharePointFileArgs](entities/class:parrot_tools.o365.sharepoint.DownloadSharePoi-8cec083a.md)

Arguments for downloading SharePoint files.

## [DownloadSharePointFileTool](entities/class:parrot_tools.o365.sharepoint.DownloadSharePoi-ae826fd8.md)

Tool for downloading files from SharePoint.

## [ListSharePointFilesArgs](entities/class:parrot_tools.o365.sharepoint.ListSharePointFilesArgs.md)

Arguments for listing SharePoint files.

## [ListSharePointFilesTool](entities/class:parrot_tools.o365.sharepoint.ListSharePointFilesTool.md)

Tool for listing files in SharePoint document libraries.

## [SearchSharePointFilesArgs](entities/class:parrot_tools.o365.sharepoint.SearchSharePointFilesArgs.md)

Arguments for searching SharePoint files.

## [SearchSharePointFilesTool](entities/class:parrot_tools.o365.sharepoint.SearchSharePointFilesTool.md)

Tool for searching files in SharePoint.

## [UploadSharePointFileArgs](entities/class:parrot_tools.o365.sharepoint.UploadSharePointFileArgs.md)

Arguments for uploading files to SharePoint.

## [UploadSharePointFileTool](entities/class:parrot_tools.o365.sharepoint.UploadSharePointFileTool.md)

Tool for uploading files to SharePoint.

## [AccountMove](entities/class:parrot_tools.odoo.models.entities.AccountMove.md)

Subset of ``account.move`` fields (invoices, bills, journal entries).

## [AccountMoveLine](entities/class:parrot_tools.odoo.models.entities.AccountMoveLine.md)

Subset of ``account.move.line`` fields.

## [CrmLead](entities/class:parrot_tools.odoo.models.entities.CrmLead.md)

Subset of ``crm.lead`` fields.

## [HrEmployee](entities/class:parrot_tools.odoo.models.entities.HrEmployee.md)

Subset of ``hr.employee`` fields most agents need.

## [HrLeave](entities/class:parrot_tools.odoo.models.entities.HrLeave.md)

Subset of ``hr.leave`` (leave allocation/request) fields.

## [ProductProduct](entities/class:parrot_tools.odoo.models.entities.ProductProduct.md)

Subset of ``product.product`` fields (variants).

## [ProductTemplate](entities/class:parrot_tools.odoo.models.entities.ProductTemplate.md)

Subset of ``product.template`` fields.

## [ResPartner](entities/class:parrot_tools.odoo.models.entities.ResPartner.md)

Subset of ``res.partner`` fields most agents need.

## [ResUsers](entities/class:parrot_tools.odoo.models.entities.ResUsers.md)

Subset of ``res.users`` fields.

## [SaleOrder](entities/class:parrot_tools.odoo.models.entities.SaleOrder.md)

Subset of ``sale.order`` fields.

## [SaleOrderLine](entities/class:parrot_tools.odoo.models.entities.SaleOrderLine.md)

Subset of ``sale.order.line`` fields.

## [StockPicking](entities/class:parrot_tools.odoo.models.entities.StockPicking.md)

Subset of ``stock.picking`` fields (delivery / receipt orders).

## [AccessDiagnosisResult](entities/class:parrot_tools.odoo.models.envelopes.AccessDiag-b8e9c008.md)

Result envelope for ``diagnose_access``.

## [AddonScanResult](entities/class:parrot_tools.odoo.models.envelopes.AddonScanResult.md)

Result envelope for ``scan_addons_source``.

## [AggregateResult](entities/class:parrot_tools.odoo.models.envelopes.AggregateResult.md)

Result envelope for ``aggregate_records``.

## [BinaryFieldResult](entities/class:parrot_tools.odoo.models.envelopes.BinaryFieldResult.md)

Result envelope for binary field uploads.

## [BulkCreateResult](entities/class:parrot_tools.odoo.models.envelopes.BulkCreateResult.md)

Result envelope for ``create_records``.

## [BulkDeleteResult](entities/class:parrot_tools.odoo.models.envelopes.BulkDeleteResult.md)

Result envelope for ``delete_records``.

## [BulkUpdateResult](entities/class:parrot_tools.odoo.models.envelopes.BulkUpdateResult.md)

Result envelope for ``update_records``.

## [BusinessPackResult](entities/class:parrot_tools.odoo.models.envelopes.BusinessPackResult.md)

Result envelope for ``business_pack_report``.

## [CreateResult](entities/class:parrot_tools.odoo.models.envelopes.CreateResult.md)

Result envelope for ``create_record``.

## [DeleteResult](entities/class:parrot_tools.odoo.models.envelopes.DeleteResult.md)

Result envelope for ``delete_record``.

## [DomainBuildResult](entities/class:parrot_tools.odoo.models.envelopes.DomainBuildResult.md)

Result envelope for ``build_domain``.

## [FieldSelectionMetadata](entities/class:parrot_tools.odoo.models.envelopes.FieldSelec-c2e9f2e2.md)

Metadata describing how the returned field set was chosen.

## [FitGapResult](entities/class:parrot_tools.odoo.models.envelopes.FitGapResult.md)

Result envelope for ``fit_gap_report``.

## [HealthCheckResult](entities/class:parrot_tools.odoo.models.envelopes.HealthCheckResult.md)

Result envelope for ``health_check`` — runtime posture report.

## [ImportResult](entities/class:parrot_tools.odoo.models.envelopes.ImportResult.md)

Result envelope for ``import_records`` (Odoo's ``load`` semantics).

## [Json2PayloadResult](entities/class:parrot_tools.odoo.models.envelopes.Json2PayloadResult.md)

Result envelope for ``generate_json2_payload``.

## [ModelInfo](entities/class:parrot_tools.odoo.models.envelopes.ModelInfo.md)

One entry in a list_models response.

## [ModelOperations](entities/class:parrot_tools.odoo.models.envelopes.ModelOperations.md)

ACL summary for a given Odoo model, from the connected user's perspective.

## [ModelRelationshipsResult](entities/class:parrot_tools.odoo.models.envelopes.ModelRelat-c6332585.md)

Result envelope for ``inspect_model_relationships``.

## [ModelsResult](entities/class:parrot_tools.odoo.models.envelopes.ModelsResult.md)

Result envelope for ``list_models``.

## [OdooCallDiagnosisResult](entities/class:parrot_tools.odoo.models.envelopes.OdooCallDi-84e1cdc9.md)

Result envelope for ``diagnose_odoo_call``.

## [OdooProfileResult](entities/class:parrot_tools.odoo.models.envelopes.OdooProfileResult.md)

Result envelope for ``get_odoo_profile``.

## [RecordResult](entities/class:parrot_tools.odoo.models.envelopes.RecordResult.md)

Result envelope for ``get_record``.

## [SchemaCatalogResult](entities/class:parrot_tools.odoo.models.envelopes.SchemaCatalogResult.md)

Result envelope for ``schema_catalog``.

## [SearchResult](entities/class:parrot_tools.odoo.models.envelopes.SearchResult.md)

Result envelope for ``search_records``.

## [ServerInfoResult](entities/class:parrot_tools.odoo.models.envelopes.ServerInfoResult.md)

Result envelope for ``server_info``.

## [UpdateResult](entities/class:parrot_tools.odoo.models.envelopes.UpdateResult.md)

Result envelope for ``update_record``.

## [AggregateRecordsInput](entities/class:parrot_tools.odoo.models.inputs.AggregateRecordsInput.md)

Input schema for ``aggregate_records`` — server-side grouping via read_group.

## [AttachDocumentInput](entities/class:parrot_tools.odoo.models.inputs.AttachDocumentInput.md)

Class AttachDocumentInput in parrot_tools.odoo.models.inputs

## [BuildDomainInput](entities/class:parrot_tools.odoo.models.inputs.BuildDomainInput.md)

Input schema for ``build_domain`` — structured domain construction.

## [BusinessPackReportInput](entities/class:parrot_tools.odoo.models.inputs.BusinessPackR-831e4fab.md)

Input schema for ``business_pack_report``.

## [ConfirmSaleOrderInput](entities/class:parrot_tools.odoo.models.inputs.ConfirmSaleOrderInput.md)

Class ConfirmSaleOrderInput in parrot_tools.odoo.models.inputs

## [CreateInvoiceInput](entities/class:parrot_tools.odoo.models.inputs.CreateInvoiceInput.md)

Class CreateInvoiceInput in parrot_tools.odoo.models.inputs

## [CreatePartnerInput](entities/class:parrot_tools.odoo.models.inputs.CreatePartnerInput.md)

Class CreatePartnerInput in parrot_tools.odoo.models.inputs

## [CreateQuotationInput](entities/class:parrot_tools.odoo.models.inputs.CreateQuotationInput.md)

Class CreateQuotationInput in parrot_tools.odoo.models.inputs

## [CreateRecordInput](entities/class:parrot_tools.odoo.models.inputs.CreateRecordInput.md)

Class CreateRecordInput in parrot_tools.odoo.models.inputs

## [CreateRecordsInput](entities/class:parrot_tools.odoo.models.inputs.CreateRecordsInput.md)

Class CreateRecordsInput in parrot_tools.odoo.models.inputs

## [DeleteRecordInput](entities/class:parrot_tools.odoo.models.inputs.DeleteRecordInput.md)

Class DeleteRecordInput in parrot_tools.odoo.models.inputs

## [DeleteRecordsInput](entities/class:parrot_tools.odoo.models.inputs.DeleteRecordsInput.md)

Class DeleteRecordsInput in parrot_tools.odoo.models.inputs

## [DiagnoseAccessInput](entities/class:parrot_tools.odoo.models.inputs.DiagnoseAccessInput.md)

Input schema for ``diagnose_access`` — ACL and record-rule diagnosis.

## [DiagnoseOdooCallInput](entities/class:parrot_tools.odoo.models.inputs.DiagnoseOdooCallInput.md)

Input schema for ``diagnose_odoo_call`` — call preview/debug.

## [FieldsGetInput](entities/class:parrot_tools.odoo.models.inputs.FieldsGetInput.md)

Class FieldsGetInput in parrot_tools.odoo.models.inputs

## [FindPartnerInput](entities/class:parrot_tools.odoo.models.inputs.FindPartnerInput.md)

Class FindPartnerInput in parrot_tools.odoo.models.inputs

## [FitGapReportInput](entities/class:parrot_tools.odoo.models.inputs.FitGapReportInput.md)

Input schema for ``fit_gap_report`` — requirement classification.

## [GenerateJson2PayloadInput](entities/class:parrot_tools.odoo.models.inputs.GenerateJson2-c8bbe706.md)

Input schema for ``generate_json2_payload`` — JSON-2 request preview.

## [GetOdooProfileInput](entities/class:parrot_tools.odoo.models.inputs.GetOdooProfileInput.md)

Input schema for ``get_odoo_profile`` — comprehensive server snapshot.

## [GetRecordInput](entities/class:parrot_tools.odoo.models.inputs.GetRecordInput.md)

Class GetRecordInput in parrot_tools.odoo.models.inputs

## [ImportRecordsInput](entities/class:parrot_tools.odoo.models.inputs.ImportRecordsInput.md)

Idempotent upsert via Odoo's ``load`` (supports external IDs).

## [InspectModelRelationshipsInput](entities/class:parrot_tools.odoo.models.inputs.InspectModelR-ff2451cc.md)

Input schema for ``inspect_model_relationships``.

## [InvoiceLineInput](entities/class:parrot_tools.odoo.models.inputs.InvoiceLineInput.md)

Class InvoiceLineInput in parrot_tools.odoo.models.inputs

## [PostInvoiceInput](entities/class:parrot_tools.odoo.models.inputs.PostInvoiceInput.md)

Class PostInvoiceInput in parrot_tools.odoo.models.inputs

## [QuotationLineInput](entities/class:parrot_tools.odoo.models.inputs.QuotationLineInput.md)

Class QuotationLineInput in parrot_tools.odoo.models.inputs

## [RegisterPaymentInput](entities/class:parrot_tools.odoo.models.inputs.RegisterPaymentInput.md)

Class RegisterPaymentInput in parrot_tools.odoo.models.inputs

## [ScanAddonsSourceInput](entities/class:parrot_tools.odoo.models.inputs.ScanAddonsSourceInput.md)

Input schema for ``scan_addons_source`` — local addon scanning.

## [SchemaCatalogInput](entities/class:parrot_tools.odoo.models.inputs.SchemaCatalogInput.md)

Input schema for ``schema_catalog`` — bounded model catalog.

## [SearchEmployeeInput](entities/class:parrot_tools.odoo.models.inputs.SearchEmployeeInput.md)

Input schema for ``search_employee``.

## [SearchHolidaysInput](entities/class:parrot_tools.odoo.models.inputs.SearchHolidaysInput.md)

Input schema for ``search_holidays`` — leave/holiday queries.

## [SearchRecordsInput](entities/class:parrot_tools.odoo.models.inputs.SearchRecordsInput.md)

Class SearchRecordsInput in parrot_tools.odoo.models.inputs

## [SetBinaryFieldInput](entities/class:parrot_tools.odoo.models.inputs.SetBinaryFieldInput.md)

Class SetBinaryFieldInput in parrot_tools.odoo.models.inputs

## [UpdatePartnerContactInfoInput](entities/class:parrot_tools.odoo.models.inputs.UpdatePartner-854176b3.md)

Class UpdatePartnerContactInfoInput in parrot_tools.odoo.models.inputs

## [UpdateRecordInput](entities/class:parrot_tools.odoo.models.inputs.UpdateRecordInput.md)

Class UpdateRecordInput in parrot_tools.odoo.models.inputs

## [UpdateRecordsInput](entities/class:parrot_tools.odoo.models.inputs.UpdateRecordsInput.md)

Class UpdateRecordsInput in parrot_tools.odoo.models.inputs

## [OdooCliCommandInput](entities/class:parrot_tools.odoo.shell.OdooCliCommandInput.md)

Input schema for ``odoo_cli_command``.

## [OdooShellInstallInput](entities/class:parrot_tools.odoo.shell.OdooShellInstallInput.md)

Input schema for ``odoo_shell_install_module``.

## [OdooShellUpgradeInput](entities/class:parrot_tools.odoo.shell.OdooShellUpgradeInput.md)

Input schema for ``odoo_shell_upgrade_module``.

## [ShellResult](entities/class:parrot_tools.odoo.shell.ShellResult.md)

Typed result envelope for odoo-bin / odoo-cli subprocess calls.

## [OdooToolkit](entities/class:parrot_tools.odoo.toolkit.OdooToolkit.md)

Toolkit exposing Odoo ERP CRUD + business helpers as agent tools.

## [AbstractOdooTransport](entities/class:parrot_tools.odoo.transport.base.AbstractOdooTransport.md)

Common surface for JSON-2, legacy JSON-RPC, and XML-RPC backends.

## [Json2Transport](entities/class:parrot_tools.odoo.transport.json2.Json2Transport.md)

Async transport for Odoo's External JSON-2 API.

## [JsonRpcTransport](entities/class:parrot_tools.odoo.transport.jsonrpc.JsonRpcTransport.md)

Wrap :class:`parrot.interfaces.OdooInterface` as a transport.

## [TimeoutSafeTransport](entities/class:parrot_tools.odoo.transport.xmlrpc.TimeoutSaf-ba38cc2d.md)

HTTPS XML-RPC transport with explicit socket timeout.

## [TimeoutTransport](entities/class:parrot_tools.odoo.transport.xmlrpc.TimeoutTransport.md)

HTTP XML-RPC transport with explicit socket timeout.

## [XmlRpcTransport](entities/class:parrot_tools.odoo.transport.xmlrpc.XmlRpcTransport.md)

Synchronous XML-RPC client wrapped in an async surface.

## [OpenWeatherArgs](entities/class:parrot_tools.openweather.OpenWeatherArgs.md)

Arguments schema for OpenWeatherTool.

## [OpenWeatherTool](entities/class:parrot_tools.openweather.OpenWeatherTool.md)

Tool to get weather information for specific locations using OpenWeatherMap API.

## [PDFPrintArgs](entities/class:parrot_tools.pdfprint.PDFPrintArgs.md)

Arguments schema for PDFPrintTool.

## [PDFPrintTool](entities/class:parrot_tools.pdfprint.PDFPrintTool.md)

Enhanced PDF Print Tool with improved Markdown table support.

## [PowerBIDatasetClient](entities/class:parrot_tools.powerbi.PowerBIDatasetClient.md)

Client for executing DAX queries against a Power BI dataset.

## [PowerBIQueryArgs](entities/class:parrot_tools.powerbi.PowerBIQueryArgs.md)

Arguments for PowerBIQueryTool.

## [PowerBIQueryTool](entities/class:parrot_tools.powerbi.PowerBIQueryTool.md)

Tool for executing DAX queries against a Power BI dataset.

## [PowerBITableInfoArgs](entities/class:parrot_tools.powerbi.PowerBITableInfoArgs.md)

Class PowerBITableInfoArgs in parrot_tools.powerbi

## [PowerBITableInfoTool](entities/class:parrot_tools.powerbi.PowerBITableInfoTool.md)

Tool for previewing table info (sample rows) from a Power BI dataset.

## [PowerPointArgs](entities/class:parrot_tools.powerpoint.PowerPointArgs.md)

Arguments schema for PowerPoint presentation generation.

## [PowerPointTool](entities/class:parrot_tools.powerpoint.PowerPointTool.md)

PowerPoint Presentation Generator Tool.

## [ModelPriceInput](entities/class:parrot_tools.pricestool.ModelPriceInput.md)

Class ModelPriceInput in parrot_tools.pricestool

## [PriceInput](entities/class:parrot_tools.pricestool.PriceInput.md)

Class PriceInput in parrot_tools.pricestool

## [PriceOutput](entities/class:parrot_tools.pricestool.PriceOutput.md)

Class PriceOutput in parrot_tools.pricestool

## [PricesTool](entities/class:parrot_tools.pricestool.PricesTool.md)

Tool for querying product prices from a database or API.

## [TotalPriceInput](entities/class:parrot_tools.pricestool.TotalPriceInput.md)

Class TotalPriceInput in parrot_tools.pricestool

## [WeeklyPriceInput](entities/class:parrot_tools.pricestool.WeeklyPriceInput.md)

Class WeeklyPriceInput in parrot_tools.pricestool

## [ProductInfo](entities/class:parrot_tools.products.ProductInfo.md)

Schema for the product information returned by the query.

## [ProductInfoTool](entities/class:parrot_tools.products.ProductInfoTool.md)

Tool to get detailed information about a specific product model.

## [ProductInput](entities/class:parrot_tools.products.ProductInput.md)

Input schema for product information requests.

## [ProductListInput](entities/class:parrot_tools.products.ProductListInput.md)

Input schema for product list requests.

## [ProductListTool](entities/class:parrot_tools.products.ProductListTool.md)

Tool to get list of products for a given program/tenant.

## [ProductResponse](entities/class:parrot_tools.products.ProductResponse.md)

ProductResponse is a model that defines the structure of the response for Product agents.

## [ProphetForecastArgs](entities/class:parrot_tools.prophetforecast.ProphetForecastArgs.md)

Arguments for :class:`ProphetForecastTool`.

## [ProphetForecastTool](entities/class:parrot_tools.prophetforecast.ProphetForecastTool.md)

Generate time series forecasts with Facebook Prophet and return plots.

## [PulumiApplyInput](entities/class:parrot_tools.pulumi.config.PulumiApplyInput.md)

Input for pulumi_apply operation.

## [PulumiConfig](entities/class:parrot_tools.pulumi.config.PulumiConfig.md)

Configuration for Pulumi executor.

## [PulumiDestroyInput](entities/class:parrot_tools.pulumi.config.PulumiDestroyInput.md)

Input for pulumi_destroy operation.

## [PulumiOperationResult](entities/class:parrot_tools.pulumi.config.PulumiOperationResult.md)

Result of a Pulumi operation.

## [PulumiPlanInput](entities/class:parrot_tools.pulumi.config.PulumiPlanInput.md)

Input for pulumi_plan operation.

## [PulumiResource](entities/class:parrot_tools.pulumi.config.PulumiResource.md)

A resource in Pulumi state.

## [PulumiStatusInput](entities/class:parrot_tools.pulumi.config.PulumiStatusInput.md)

Input for pulumi_status operation.

## [PulumiExecutor](entities/class:parrot_tools.pulumi.executor.PulumiExecutor.md)

Executes Pulumi CLI commands via Docker or direct CLI.

## [PulumiToolkit](entities/class:parrot_tools.pulumi.toolkit.PulumiToolkit.md)

Toolkit for infrastructure deployment using Pulumi.

## [QSourceTool](entities/class:parrot_tools.qsource.QSourceTool.md)

Tool for executing QuerySource queries and returning structured data.

## [QuerySourceInput](entities/class:parrot_tools.qsource.QuerySourceInput.md)

Input schema for QuerySource tool.

## [AssetRiskInput](entities/class:parrot_tools.quant.models.AssetRiskInput.md)

Input for single-asset risk metrics.

## [CorrelationInput](entities/class:parrot_tools.quant.models.CorrelationInput.md)

Input for correlation analysis.

## [PiotroskiInput](entities/class:parrot_tools.quant.models.PiotroskiInput.md)

Input for Piotroski F-Score calculation.

## [PortfolioRiskInput](entities/class:parrot_tools.quant.models.PortfolioRiskInput.md)

Input for portfolio-level risk computation.

## [PortfolioRiskOutput](entities/class:parrot_tools.quant.models.PortfolioRiskOutput.md)

Output from portfolio risk calculation.

## [RiskMetricsOutput](entities/class:parrot_tools.quant.models.RiskMetricsOutput.md)

Output from single-asset risk calculation.

## [StressScenario](entities/class:parrot_tools.quant.models.StressScenario.md)

A single stress test scenario definition.

## [QuantToolkit](entities/class:parrot_tools.quant.toolkit.QuantToolkit.md)

Quantitative risk analysis, portfolio metrics, and fundamental scoring toolkit.

## [QueryToolkit](entities/class:parrot_tools.querytoolkit.QueryToolkit.md)

Abstract base class for DB Queries-like Toolkits.

## [EdaUtils](entities/class:parrot_tools.quickeda.EdaUtils.md)

Utility functions for EDA operations.

## [QuickEdaArgs](entities/class:parrot_tools.quickeda.QuickEdaArgs.md)

Arguments schema for Quick EDA analysis.

## [QuickEdaTool](entities/class:parrot_tools.quickeda.QuickEdaTool.md)

Tool for performing comprehensive Exploratory Data Analysis on pandas DataFrames.

## [RedditToolkit](entities/class:parrot_tools.reddit.RedditToolkit.md)

Reddit Toolkit for extracting data from Reddit using PRAW.

## [SubredditSearchInput](entities/class:parrot_tools.reddit.SubredditSearchInput.md)

Input parameters for searching a subreddit.

## [RegressionAnalysisTool](entities/class:parrot_tools.regression_analysis.RegressionAn-25210713.md)

Model quantitative relationships between variables.

## [RegressionInput](entities/class:parrot_tools.regression_analysis.RegressionInput.md)

Input schema for RegressionAnalysisTool.

## [DynamicRESTTool](entities/class:parrot_tools.resttool.DynamicRESTTool.md)

Dynamic REST tool that can be configured with custom endpoints.

## [RESTArgsSchema](entities/class:parrot_tools.resttool.RESTArgsSchema.md)

Base schema for REST API calls.

## [RESTTool](entities/class:parrot_tools.resttool.RESTTool.md)

Base class for creating REST API tools.

## [SimpleRESTTool](entities/class:parrot_tools.resttool.SimpleRESTTool.md)

Simplified REST tool for quick API integrations.

## [BestBuyToolkit](entities/class:parrot_tools.retail.bby.BestBuyToolkit.md)

Toolkit for interacting with BestBuy API and services.

## [ProductAvailabilityInput](entities/class:parrot_tools.retail.bby.ProductAvailabilityInput.md)

Input schema for checking product availability.

## [ProductSearchInput](entities/class:parrot_tools.retail.bby.ProductSearchInput.md)

Input schema for product search.

## [StoreLocatorInput](entities/class:parrot_tools.retail.bby.StoreLocatorInput.md)

Input schema for finding stores.

## [ArticleFetcher](entities/class:parrot_tools.rss.fetcher.ArticleFetcher.md)

Fetches feed XML and article pages with bounded concurrency.

## [FeedItemMetadata](entities/class:parrot_tools.rss.models.FeedItemMetadata.md)

LLM-facing record for a retrieved feed item.

## [FeedSite](entities/class:parrot_tools.rss.models.FeedSite.md)

A configured RSS/Atom feed source.

## [FetchedPage](entities/class:parrot_tools.rss.models.FetchedPage.md)

Internal result of a single article-page fetch attempt.

## [GetContentInput](entities/class:parrot_tools.rss.models.GetContentInput.md)

Input schema for ``rss_get_content``.

## [RSSStorage](entities/class:parrot_tools.rss.storage.RSSStorage.md)

Filesystem archive for fetched feed items.

## [RSSFeedReaderToolkit](entities/class:parrot_tools.rss.toolkit.RSSFeedReaderToolkit.md)

Toolkit that archives RSS feed articles to disk for later retrieval.

## [GenericReportComparator](entities/class:parrot_tools.s3.comparator.GenericReportComparator.md)

Structural diff engine for S3-stored report documents.

## [S3ReportReaderToolkit](entities/class:parrot_tools.s3.report_reader.S3ReportReaderToolkit.md)

Agnostic read-only toolkit for LLM agents to explore S3-stored reports.

## [ExecutionResult](entities/class:parrot_tools.sandboxtool.ExecutionResult.md)

Result from sandbox execution

## [SandboxConfig](entities/class:parrot_tools.sandboxtool.SandboxConfig.md)

Configuration for gVisor sandbox

## [SandboxPandasTool](entities/class:parrot_tools.sandboxtool.SandboxPandasTool.md)

Specialized version for Pandas operations with enhanced data handling.

## [SandboxTool](entities/class:parrot_tools.sandboxtool.SandboxTool.md)

Secure Python execution using gVisor sandbox.

## [ClientInput](entities/class:parrot_tools.sassie.ClientInput.md)

Input schema for client-related tools.

## [EvaluationRecord](entities/class:parrot_tools.sassie.EvaluationRecord.md)

Complete evaluation record with visit data and metadata.

## [ProductInfo](entities/class:parrot_tools.sassie.ProductInfo.md)

Schema for the product information returned by the query.

## [ProductInput](entities/class:parrot_tools.sassie.ProductInput.md)

Input schema for querying Epson product information.

## [RetailerEvaluation](entities/class:parrot_tools.sassie.RetailerEvaluation.md)

Schema for retailer evaluation data.

## [RetailerInput](entities/class:parrot_tools.sassie.RetailerInput.md)

Input schema for querying retailer evaluation data.

## [VisitData](entities/class:parrot_tools.sassie.VisitData.md)

Individual visit data entry containing question and answer information.

## [VisitDataResponse](entities/class:parrot_tools.sassie.VisitDataResponse.md)

Simplified model containing only the visit data.

## [VisitsToolkit](entities/class:parrot_tools.sassie.VisitsToolkit.md)

Toolkit for managing employee-related operations in Sassie Survey Project.

## [BasePlanRegistry](entities/class:parrot_tools.scraping.base_registry.BasePlanRegistry.md)

Generic disk-backed plan registry with 3-tier URL lookup.

## [PlanLike](entities/class:parrot_tools.scraping.base_registry.PlanLike.md)

Protocol that all registrable plan types must satisfy.

## [CrawlGraph](entities/class:parrot_tools.scraping.crawl_graph.CrawlGraph.md)

BFS-based crawl graph that manages the frontier and visited set.

## [CrawlNode](entities/class:parrot_tools.scraping.crawl_graph.CrawlNode.md)

A single node in the crawl graph representing one URL to visit.

## [CrawlResult](entities/class:parrot_tools.scraping.crawl_graph.CrawlResult.md)

Summary of a completed crawl session.

## [BFSStrategy](entities/class:parrot_tools.scraping.crawl_strategy.BFSStrategy.md)

Breadth-first strategy: visits all nodes at depth N before depth N+1.

## [CrawlStrategy](entities/class:parrot_tools.scraping.crawl_strategy.CrawlStrategy.md)

Protocol that determines traversal order for the CrawlEngine.

## [DFSStrategy](entities/class:parrot_tools.scraping.crawl_strategy.DFSStrategy.md)

Depth-first strategy: follows links deep before backtracking.

## [CrawlEngine](entities/class:parrot_tools.scraping.crawler.CrawlEngine.md)

Orchestrates multi-page crawling.

## [SeleniumSetup](entities/class:parrot_tools.scraping.driver.SeleniumSetup.md)

Selenium Setup Configuration.

## [DriverRegistry](entities/class:parrot_tools.scraping.driver_context.DriverRegistry.md)

Plugin-style registry for browser driver factories.

## [DriverFactory](entities/class:parrot_tools.scraping.driver_factory.DriverFactory.md)

Factory for creating browser automation driver instances.

## [AbstractDriver](entities/class:parrot_tools.scraping.drivers.abstract.AbstractDriver.md)

Unified interface for browser automation drivers.

## [PageDriver](entities/class:parrot_tools.scraping.drivers.page_driver.PageDriver.md)

Adapt a live Playwright ``Page`` to the :class:`AbstractDriver` interface.

## [PlaywrightConfig](entities/class:parrot_tools.scraping.drivers.playwright_conf-c8c37985.md)

Configuration for PlaywrightDriver.

## [PlaywrightDriver](entities/class:parrot_tools.scraping.drivers.playwright_driv-7fd05071.md)

Playwright-based browser automation driver.

## [SeleniumDriver](entities/class:parrot_tools.scraping.drivers.selenium_driver-fca47b64.md)

Selenium-based browser automation driver.

## [EntityFieldSpec](entities/class:parrot_tools.scraping.extraction_models.Entit-a5c12c73.md)

Specification for a single field within an entity.

## [EntitySpec](entities/class:parrot_tools.scraping.extraction_models.EntitySpec.md)

Specification for one type of entity to extract.

## [ExtractedEntity](entities/class:parrot_tools.scraping.extraction_models.Extra-07f8cd36.md)

A single structured entity extracted from a page.

## [ExtractionPlan](entities/class:parrot_tools.scraping.extraction_models.ExtractionPlan.md)

Rich schema describing WHAT to extract — translates to ScrapingPlan for execution.

## [ExtractionResult](entities/class:parrot_tools.scraping.extraction_models.Extra-5ae19203.md)

Complete result from an extraction run.

## [ExtractionPlanGenerator](entities/class:parrot_tools.scraping.extraction_plan_generat-d2051046.md)

Generates ExtractionPlan from HTML content + objective using LLM reconnaissance.

## [ExtractionPlanRegistry](entities/class:parrot_tools.scraping.extraction_registry.Ext-4621cbca.md)

Disk-backed registry for ExtractionPlans with cache lifecycle management.

## [FlowExecutor](entities/class:parrot_tools.scraping.flow_executor.FlowExecutor.md)

Orchestrate end-to-end execution of a :class:`ScrapingFlow`.

## [FlowNode](entities/class:parrot_tools.scraping.flow_models.FlowNode.md)

A single stage in a :class:`ScrapingFlow` DAG.

## [FlowResult](entities/class:parrot_tools.scraping.flow_models.FlowResult.md)

Aggregated result of a :class:`ScrapingFlow` execution.

## [ScrapingFlow](entities/class:parrot_tools.scraping.flow_models.ScrapingFlow.md)

DAG of :class:`FlowNode`s with data-dependency edges and session affinity.

## [LinkDiscoverer](entities/class:parrot_tools.scraping.link_discoverer.LinkDiscoverer.md)

Discovers and filters links from HTML pages.

## [Authenticate](entities/class:parrot_tools.scraping.models.Authenticate.md)

Handle authentication flows

## [AwaitBrowserEvent](entities/class:parrot_tools.scraping.models.AwaitBrowserEvent.md)

Wait for human interaction in the browser

## [AwaitHuman](entities/class:parrot_tools.scraping.models.AwaitHuman.md)

Pause and wait for human intervention

## [AwaitKeyPress](entities/class:parrot_tools.scraping.models.AwaitKeyPress.md)

Wait for human to press a key in console

## [Back](entities/class:parrot_tools.scraping.models.Back.md)

Navigate back to the previous page

## [BrowserAction](entities/class:parrot_tools.scraping.models.BrowserAction.md)

Base class for all browser actions

## [Click](entities/class:parrot_tools.scraping.models.Click.md)

Click on a web page element

## [Conditional](entities/class:parrot_tools.scraping.models.Conditional.md)

Execute actions conditionally based on a JavaScript expression

## [Evaluate](entities/class:parrot_tools.scraping.models.Evaluate.md)

Execute JavaScript code in the browser context

## [Extract](entities/class:parrot_tools.scraping.models.Extract.md)

Extract data from the page using CSS selectors or XPath.

## [ExtractJsonLd](entities/class:parrot_tools.scraping.models.ExtractJsonLd.md)

Extract structured data from JSON-LD blocks on the current page.

## [FieldSpec](entities/class:parrot_tools.scraping.models.FieldSpec.md)

One sub-selector for a row-of-fields ``Extract`` step.

## [Fill](entities/class:parrot_tools.scraping.models.Fill.md)

Fill text into an input field

## [GetCookies](entities/class:parrot_tools.scraping.models.GetCookies.md)

Extract and evaluate cookies

## [GetHTML](entities/class:parrot_tools.scraping.models.GetHTML.md)

Extract complete HTML content from elements matching selector

## [GetText](entities/class:parrot_tools.scraping.models.GetText.md)

Extract pure text content from elements matching selector

## [Hover](entities/class:parrot_tools.scraping.models.Hover.md)

Move the mouse over an area/element

## [Loop](entities/class:parrot_tools.scraping.models.Loop.md)

Repeat a sequence of actions multiple times

## [Navigate](entities/class:parrot_tools.scraping.models.Navigate.md)

Navigate to a URL

## [PressKey](entities/class:parrot_tools.scraping.models.PressKey.md)

Press keyboard keys

## [Refresh](entities/class:parrot_tools.scraping.models.Refresh.md)

Reload the current web page

## [ScrapingResult](entities/class:parrot_tools.scraping.models.ScrapingResult.md)

Stores results from a single page scrape

## [ScrapingSelector](entities/class:parrot_tools.scraping.models.ScrapingSelector.md)

Defines what content to extract from a page

## [ScrapingStep](entities/class:parrot_tools.scraping.models.ScrapingStep.md)

ScrapingStep that wraps a BrowserAction.

## [Screenshot](entities/class:parrot_tools.scraping.models.Screenshot.md)

Take a screenshot of the page or a specific element

## [Scroll](entities/class:parrot_tools.scraping.models.Scroll.md)

Scroll the page or an element

## [Select](entities/class:parrot_tools.scraping.models.Select.md)

Select an option from a dropdown/select element.

## [SetCookies](entities/class:parrot_tools.scraping.models.SetCookies.md)

Set cookies on the current page or domain

## [Submit](entities/class:parrot_tools.scraping.models.Submit.md)

Click on a submit button or submit a form

## [Type](entities/class:parrot_tools.scraping.models.Type.md)

Send keystrokes to the page or an element

## [UploadFile](entities/class:parrot_tools.scraping.models.UploadFile.md)

Upload a file to a file input element

## [Wait](entities/class:parrot_tools.scraping.models.Wait.md)

Wait for a condition to be met.

## [WaitForDownload](entities/class:parrot_tools.scraping.models.WaitForDownload.md)

Wait for a file download to complete

## [ScrapingMissionBuilder](entities/class:parrot_tools.scraping.orchestrator.ScrapingMi-ca965150.md)

Builder pattern for creating complex scraping missions

## [ScrapingOrchestrator](entities/class:parrot_tools.scraping.orchestrator.ScrapingOr-48fdb2ce.md)

High-level orchestrator that manages the complete LLM-directed scraping workflow.

## [PageSnapshot](entities/class:parrot_tools.scraping.page_snapshot.PageSnapshot.md)

Compact page data for LLM prompt building.

## [PlanRegistryEntry](entities/class:parrot_tools.scraping.plan.PlanRegistryEntry.md)

Entry in the PlanRegistry index mapping a plan to its disk location.

## [ScrapingPlan](entities/class:parrot_tools.scraping.plan.ScrapingPlan.md)

Declarative scraping plan — value object, immutable once saved.

## [PlanGenerator](entities/class:parrot_tools.scraping.plan_generator.PlanGenerator.md)

Generates ScrapingPlan from URL + objective using an LLM client.

## [RecallProcessor](entities/class:parrot_tools.scraping.recall_processor.RecallProcessor.md)

Post-extraction LLM recall for rag_text generation and gap-filling.

## [PlanRegistry](entities/class:parrot_tools.scraping.registry.PlanRegistry.md)

Async, disk-backed index mapping URLs to saved ScrapingPlan files.

## [SessionManager](entities/class:parrot_tools.scraping.session_manager.SessionManager.md)

Manage Playwright ``BrowserContext``s keyed by session label.

## [ParamSpec](entities/class:parrot_tools.scraping.template_plan.ParamSpec.md)

Typed parameter definition for a :class:`TemplatePlan`.

## [TemplatePlan](entities/class:parrot_tools.scraping.template_plan.TemplatePlan.md)

Parameterized plan template that produces ``ScrapingPlan``s via ``bind()``.

## [WebScrapingTool](entities/class:parrot_tools.scraping.tool.WebScrapingTool.md)

Advanced web scraping tool with LLM integration support.

## [WebScrapingToolArgs](entities/class:parrot_tools.scraping.tool.WebScrapingToolArgs.md)

Arguments schema for WebScrapingTool.

## [ExtractionScore](entities/class:parrot_tools.scraping.toolkit.ExtractionScore.md)

Heuristic quality score for a ``ScrapingResult``.

## [WebScrapingToolkit](entities/class:parrot_tools.scraping.toolkit.WebScrapingToolkit.md)

Toolkit for intelligent web scraping and crawling with plan caching.

## [DriverConfig](entities/class:parrot_tools.scraping.toolkit_models.DriverConfig.md)

Frozen browser configuration passed to the driver factory.

## [PlanSaveResult](entities/class:parrot_tools.scraping.toolkit_models.PlanSaveResult.md)

Result of a plan save operation.

## [PlanSummary](entities/class:parrot_tools.scraping.toolkit_models.PlanSummary.md)

Slim projection of PlanRegistryEntry for plan listing results.

## [SeasonalDetectionArgs](entities/class:parrot_tools.seasonaldetection.SeasonalDetectionArgs.md)

Arguments schema for SeasonalDetectionTool.

## [SeasonalDetectionTool](entities/class:parrot_tools.seasonaldetection.SeasonalDetectionTool.md)

Tool for detecting stationarity and seasonality in time series data.

## [AdvisoryRecommendation](entities/class:parrot_tools.security.advisory_engine.Advisor-971962b1.md)

One actionable recommendation tied to SOC2 controls.

## [AdvisoryReport](entities/class:parrot_tools.security.advisory_engine.AdvisoryReport.md)

Structured day-over-day SOC2 advisory for one framework.

## [FindingDelta](entities/class:parrot_tools.security.advisory_engine.FindingDelta.md)

Day-over-day change for a single finding (aligned to SecurityFinding).

## [SecurityAdvisoryEngine](entities/class:parrot_tools.security.advisory_engine.Securit-09110248.md)

Deterministic day-over-day security advisory engine.

## [BaseExecutor](entities/class:parrot_tools.security.base_executor.BaseExecutor.md)

Abstract base executor for Docker or CLI process management.

## [BaseExecutorConfig](entities/class:parrot_tools.security.base_executor.BaseExecutorConfig.md)

Base configuration shared by all scanner executors.

## [BaseParser](entities/class:parrot_tools.security.base_parser.BaseParser.md)

Abstract parser for security scanner output.

## [CheckovConfig](entities/class:parrot_tools.security.checkov.config.CheckovConfig.md)

Configuration for Checkov IaC security scanner.

## [CheckovExecutor](entities/class:parrot_tools.security.checkov.executor.CheckovExecutor.md)

Executes Checkov IaC security scans via Docker or direct CLI.

## [CheckovParser](entities/class:parrot_tools.security.checkov.parser.CheckovParser.md)

Parser for Checkov JSON output.

## [CloudPostureToolkit](entities/class:parrot_tools.security.cloud_posture_toolkit.C-98b69867.md)

Cloud Security Posture Management toolkit powered by Prowler.

## [ComplianceReportToolkit](entities/class:parrot_tools.security.compliance_report_toolk-931c131a.md)

Multi-scanner compliance reporting toolkit.

## [ContainerSecurityToolkit](entities/class:parrot_tools.security.container_security_tool-75ea7470.md)

Container and infrastructure security toolkit powered by Trivy.

## [CloudProvider](entities/class:parrot_tools.security.models.CloudProvider.md)

Cloud providers supported by scanners.

## [ComparisonDelta](entities/class:parrot_tools.security.models.ComparisonDelta.md)

Comparison between two scan results for trend analysis.

## [ComplianceFramework](entities/class:parrot_tools.security.models.ComplianceFramework.md)

Supported compliance frameworks for mapping findings.

## [ConsolidatedReport](entities/class:parrot_tools.security.models.ConsolidatedReport.md)

Consolidated report aggregating results from multiple scanners.

## [FindingSource](entities/class:parrot_tools.security.models.FindingSource.md)

Security scanner sources.

## [ScanResult](entities/class:parrot_tools.security.models.ScanResult.md)

Complete results from a single scanner execution.

## [ScanSummary](entities/class:parrot_tools.security.models.ScanSummary.md)

Summary statistics for a single scanner run.

## [SecurityFinding](entities/class:parrot_tools.security.models.SecurityFinding.md)

Unified security finding from any scanner.

## [SeverityLevel](entities/class:parrot_tools.security.models.SeverityLevel.md)

Normalized severity levels across all scanners.

## [ParsedReport](entities/class:parrot_tools.security.parsers._types.ParsedReport.md)

Result returned by every catalog-level parser's ``parse()`` method.

## [ReportParser](entities/class:parrot_tools.security.parsers._types.ReportParser.md)

Protocol every catalog-level parser must satisfy.

## [AggregatorParser](entities/class:parrot_tools.security.parsers.aggregator.Aggr-c05de6f2.md)

Passthrough parser for weekly / monthly aggregated summary reports.

## [CheckovParser](entities/class:parrot_tools.security.parsers.checkov.CheckovParser.md)

Catalog-level parser for Checkov JSON reports.

## [CloudSploitParser](entities/class:parrot_tools.security.parsers.cloudsploit.Clo-026ca931.md)

Catalog-level parser for CloudSploit scan JSON reports.

## [ProwlerParser](entities/class:parrot_tools.security.parsers.prowler.ProwlerParser.md)

Catalog-level parser for Prowler JSON-OCSF reports.

## [TrivyParser](entities/class:parrot_tools.security.parsers.trivy.TrivyParser.md)

Catalog-level parser for Trivy filesystem/image JSON reports.

## [ReportPersistenceMixin](entities/class:parrot_tools.security.persistence.ReportPersi-d6c3febf.md)

Mixin that gives producer toolkits catalog write capability.

## [ProwlerConfig](entities/class:parrot_tools.security.prowler.config.ProwlerConfig.md)

Configuration for Prowler security scanner.

## [ProwlerExecutor](entities/class:parrot_tools.security.prowler.executor.ProwlerExecutor.md)

Executes Prowler security scans via Docker or direct CLI.

## [ProwlerParser](entities/class:parrot_tools.security.prowler.parser.ProwlerParser.md)

Parser for Prowler JSON-OCSF output.

## [SecurityReportToolkit](entities/class:parrot_tools.security.report_toolkit.Security-d3538dc2.md)

LLM-facing tools for querying the cross-session security report catalog.

## [ComplianceMapper](entities/class:parrot_tools.security.reports.compliance_mapp-58a6389b.md)

Maps security findings to compliance framework controls.

## [ReportGenerator](entities/class:parrot_tools.security.reports.generator.Repor-89fde0e9.md)

Multi-format report generator with Jinja2 templates.

## [ScoutSuiteConfig](entities/class:parrot_tools.security.scoutsuite.config.Scout-aa673bb3.md)

Configuration for ScoutSuite security scanner.

## [ScoutSuiteExecutor](entities/class:parrot_tools.security.scoutsuite.executor.Sco-f3a287d5.md)

Executes ScoutSuite security scans.

## [ScoutSuiteParser](entities/class:parrot_tools.security.scoutsuite.parser.Scout-a044a1f8.md)

Parses ScoutSuite JSON output into unified SecurityFinding models.

## [SecretsIaCToolkit](entities/class:parrot_tools.security.secrets_iac_toolkit.Sec-d1508f33.md)

Infrastructure as Code and Secrets scanning toolkit powered by Checkov.

## [SOC2AdvisoryToolkit](entities/class:parrot_tools.security.soc2_advisory.SOC2Advis-9c685ea8.md)

LLM-facing tools for SOC2-oriented security advisory.

## [MonthlySecuritySummarizer](entities/class:parrot_tools.security.summarizer.MonthlySecur-1242abc6.md)

Produces a ``MonthlySummary`` from a list of weekly ``WeeklySummary`` objects.

## [MonthlySummary](entities/class:parrot_tools.security.summarizer.MonthlySummary.md)

A month-scoped security posture summary for one (provider, framework) pair.

## [WeeklySecuritySummarizer](entities/class:parrot_tools.security.summarizer.WeeklySecuri-8d6dc03a.md)

Produces a ``WeeklySummary`` from a list of scan ``ReportRef``s.

## [WeeklySummary](entities/class:parrot_tools.security.summarizer.WeeklySummary.md)

A week-scoped security posture summary for one (provider, framework) pair.

## [TrivyConfig](entities/class:parrot_tools.security.trivy.config.TrivyConfig.md)

Configuration for Trivy security scanner.

## [ImageNotFoundError](entities/class:parrot_tools.security.trivy.executor.ImageNot-ab3d545c.md)

Raised when a `trivy image` target is not present on the local Docker daemon.

## [TrivyExecutor](entities/class:parrot_tools.security.trivy.executor.TrivyExecutor.md)

Executes Trivy security scans via Docker or direct CLI.

## [TrivyParser](entities/class:parrot_tools.security.trivy.parser.TrivyParser.md)

Parser for Trivy JSON output.

## [SensitivityAnalysisInput](entities/class:parrot_tools.sensitivity_analysis.Sensitivity-c7fc6754.md)

Input schema for SensitivityAnalysisTool.

## [SensitivityAnalysisTool](entities/class:parrot_tools.sensitivity_analysis.Sensitivity-792ec10b.md)

Analyze which variables have the greatest impact on a target metric.

## [SerpApiSearchArgs](entities/class:parrot_tools.serpapi.SerpApiSearchArgs.md)

Arguments for the SerpApi Search Tool.

## [SerpApiSearchTool](entities/class:parrot_tools.serpapi.SerpApiSearchTool.md)

Tool to execute web searches using SerpApi.

## [CheckExists](entities/class:parrot_tools.shell_tool.actions.CheckExists.md)

Check if a file/directory exists.

## [CopyFile](entities/class:parrot_tools.shell_tool.actions.CopyFile.md)

Copy a file or directory.

## [DeleteFile](entities/class:parrot_tools.shell_tool.actions.DeleteFile.md)

Deletes a file or directory (with optional recursion).

## [ExecFile](entities/class:parrot_tools.shell_tool.actions.ExecFile.md)

Execute a file/script via /bin/sh {file_or_cmd}.

## [ListFiles](entities/class:parrot_tools.shell_tool.actions.ListFiles.md)

List files in a directory, optionally with flags/args.

## [MoveFile](entities/class:parrot_tools.shell_tool.actions.MoveFile.md)

Move/rename a file or directory.

## [ReadFile](entities/class:parrot_tools.shell_tool.actions.ReadFile.md)

Read a file's content, with optional max bytes and encoding.

## [RunCommand](entities/class:parrot_tools.shell_tool.actions.RunCommand.md)

Run a shell command via /bin/sh -lc 'command'.

## [WriteFile](entities/class:parrot_tools.shell_tool.actions.WriteFile.md)

Writes text content to a file relative to work_dir.

## [EvalAction](entities/class:parrot_tools.shell_tool.engine.EvalAction.md)

Evaluate an expression using regex, jsonpath, or jq.

## [EvaluationEngine](entities/class:parrot_tools.shell_tool.engine.EvaluationEngine.md)

Supports:

## [ActionResult](entities/class:parrot_tools.shell_tool.models.ActionResult.md)

Result of a shell action execution.

## [BaseAction](entities/class:parrot_tools.shell_tool.models.BaseAction.md)

Base class for shell and utility actions.

## [CommandObject](entities/class:parrot_tools.shell_tool.models.CommandObject.md)

Represents a shell command to be executed.

## [PlanStep](entities/class:parrot_tools.shell_tool.models.PlanStep.md)

Represents a step in a shell command plan.

## [ShellToolArgs](entities/class:parrot_tools.shell_tool.models.ShellToolArgs.md)

Arguments for the ShellTool.

## [SecureShellMixin](entities/class:parrot_tools.shell_tool.security.SecureShellMixin.md)

Mixin that adds security validation to ShellTool via composition.

## [ShellTool](entities/class:parrot_tools.shell_tool.tool.ShellTool.md)

Interactive Shell tool with optional PTY support.

## [PresetConfig](entities/class:parrot_tools.sitesearch.presets.PresetConfig.md)

Type definition for preset configuration.

## [SiteSearch](entities/class:parrot_tools.sitesearch.tool.SiteSearch.md)

Perform Google-powered site searches and return rendered content as markdown.

## [SiteSearchArgs](entities/class:parrot_tools.sitesearch.tool.SiteSearchArgs.md)

Arguments schema for :class:`SiteSearch`.

## [SiteSearchToolkit](entities/class:parrot_tools.sitesearch.toolkit.SiteSearchToolkit.md)

Toolkit for site-specific web searches with preset configurations.

## [StatisticalTestInput](entities/class:parrot_tools.statistical_tests.StatisticalTestInput.md)

Input schema for StatisticalTestsTool.

## [StatisticalTestsTool](entities/class:parrot_tools.statistical_tests.StatisticalTestsTool.md)

Run statistical hypothesis tests on dataset groups.

## [HealthCategory](entities/class:parrot_tools.system_health.tool.HealthCategory.md)

Available health-check categories.

## [SystemHealthArgs](entities/class:parrot_tools.system_health.tool.SystemHealthArgs.md)

Arguments for the system health tool.

## [SystemHealthTool](entities/class:parrot_tools.system_health.tool.SystemHealthTool.md)

Read-only system health monitor.

## [ADXOutput](entities/class:parrot_tools.technical_analysis.ADXOutput.md)

ADX (Average Directional Index) indicator output.

## [ATROutput](entities/class:parrot_tools.technical_analysis.ATROutput.md)

ATR (Average True Range) indicator output with stop-loss levels.

## [CompositeScore](entities/class:parrot_tools.technical_analysis.CompositeScore.md)

Composite technical score for asset ranking.

## [TechnicalAnalysisInput](entities/class:parrot_tools.technical_analysis.TechnicalAnalysisInput.md)

Class TechnicalAnalysisInput in parrot_tools.technical_analysis

## [TechnicalAnalysisTool](entities/class:parrot_tools.technical_analysis.TechnicalAnalysisTool.md)

Tool for performing Technical Analysis on stocks and crypto.

## [TechnicalSignal](entities/class:parrot_tools.technical_analysis.TechnicalSignal.md)

Structured technical signal with confidence scoring.

## [FileManagementArgs](entities/class:parrot_tools.textfile.FileManagementArgs.md)

Arguments for file management operations.

## [TextFileTool](entities/class:parrot_tools.textfile.TextFileTool.md)

Comprehensive file management tool supporting CRUD operations.

## [DataAnalysisThinkTool](entities/class:parrot_tools.think.DataAnalysisThinkTool.md)

Specialized thinking tool for data analysis tasks.

## [QueryPlanTool](entities/class:parrot_tools.think.QueryPlanTool.md)

Specialized thinking tool for database query planning.

## [RAGRetrievalThinkTool](entities/class:parrot_tools.think.RAGRetrievalThinkTool.md)

Specialized thinking tool for RAG retrieval strategy.

## [ScrapingPlanTool](entities/class:parrot_tools.think.ScrapingPlanTool.md)

Specialized thinking tool for web scraping tasks.

## [ThinkInput](entities/class:parrot_tools.think.ThinkInput.md)

Input schema for the ThinkTool.

## [ThinkTool](entities/class:parrot_tools.think.ThinkTool.md)

A metacognitive tool that forces explicit reasoning before action.

## [TROCOperationsToolkit](entities/class:parrot_tools.troc.tool.TROCOperationsToolkit.md)

TROC vending operations KPI toolkit.

## [Action](entities/class:parrot_tools.whatif.Action.md)

Defines a possible action

## [Constraint](entities/class:parrot_tools.whatif.Constraint.md)

Defines a constraint

## [ConstraintType](entities/class:parrot_tools.whatif.ConstraintType.md)

Type of constraint

## [DerivedMetric](entities/class:parrot_tools.whatif.DerivedMetric.md)

Calculated/derived metric

## [MetricsCalculator](entities/class:parrot_tools.whatif.MetricsCalculator.md)

Calculates derived metrics on DataFrames

## [Objective](entities/class:parrot_tools.whatif.Objective.md)

Defines an optimization objective

## [ObjectiveType](entities/class:parrot_tools.whatif.ObjectiveType.md)

Type of optimization objective

## [ScenarioOptimizer](entities/class:parrot_tools.whatif.ScenarioOptimizer.md)

Optimizer with support for derived metrics

## [ScenarioResult](entities/class:parrot_tools.whatif.ScenarioResult.md)

Result of an optimized scenario

## [WhatIfAction](entities/class:parrot_tools.whatif.WhatIfAction.md)

Possible action to take

## [WhatIfConstraint](entities/class:parrot_tools.whatif.WhatIfConstraint.md)

Constraint for scenario

## [WhatIfDSL](entities/class:parrot_tools.whatif.WhatIfDSL.md)

Domain Specific Language for What-If analysis with optimization

## [WhatIfInput](entities/class:parrot_tools.whatif.WhatIfInput.md)

Input schema for WhatIfTool

## [WhatIfObjective](entities/class:parrot_tools.whatif.WhatIfObjective.md)

Objective for scenario optimization

## [WhatIfTool](entities/class:parrot_tools.whatif.WhatIfTool.md)

What-If Analysis Tool with support for derived metrics and optimization.

## [AddActionsInput](entities/class:parrot_tools.whatif_toolkit.AddActionsInput.md)

Input for add_actions tool.

## [CompareScenariosInput](entities/class:parrot_tools.whatif_toolkit.CompareScenariosInput.md)

Input for compare_scenarios tool.

## [DescribeScenarioInput](entities/class:parrot_tools.whatif_toolkit.DescribeScenarioInput.md)

Input for describe_scenario tool.

## [QuickImpactInput](entities/class:parrot_tools.whatif_toolkit.QuickImpactInput.md)

Input for quick_impact tool -- the simple fast-path.

## [ScenarioState](entities/class:parrot_tools.whatif_toolkit.ScenarioState.md)

Internal state for a scenario being built incrementally.

## [SetConstraintsInput](entities/class:parrot_tools.whatif_toolkit.SetConstraintsInput.md)

Input for set_constraints tool.

## [SimulateInput](entities/class:parrot_tools.whatif_toolkit.SimulateInput.md)

Input for simulate tool.

## [WhatIfToolkit](entities/class:parrot_tools.whatif_toolkit.WhatIfToolkit.md)

What-If scenario analysis toolkit for simulating hypothetical changes on datasets.

## [Address](entities/class:parrot_tools.workday.models.Address.md)

Physical address.

## [Compensation](entities/class:parrot_tools.workday.models.Compensation.md)

Compensation information.

## [ContactModel](entities/class:parrot_tools.workday.models.ContactModel.md)

Clean Contact model - Default output for contact information.

## [EmailAddress](entities/class:parrot_tools.workday.models.EmailAddress.md)

Email address with metadata.

## [JobProfile](entities/class:parrot_tools.workday.models.JobProfile.md)

Job profile information.

## [Manager](entities/class:parrot_tools.workday.models.Manager.md)

Manager reference.

## [OrganizationModel](entities/class:parrot_tools.workday.models.OrganizationModel.md)

Clean Organization model.

## [PhoneNumber](entities/class:parrot_tools.workday.models.PhoneNumber.md)

Phone number with metadata.

## [Position](entities/class:parrot_tools.workday.models.Position.md)

Worker position information.

## [TimeOffBalance](entities/class:parrot_tools.workday.models.TimeOffBalance.md)

Individual time off balance for a specific time off type.

## [TimeOffBalanceModel](entities/class:parrot_tools.workday.models.TimeOffBalanceModel.md)

Clean Time Off Balance model - Default output for time off information.

## [WorkdayReference](entities/class:parrot_tools.workday.models.WorkdayReference.md)

Standard Workday reference object.

## [WorkdayResponseParser](entities/class:parrot_tools.workday.models.WorkdayResponseParser.md)

Parser that transforms verbose Zeep responses into clean Pydantic models.

## [WorkerModel](entities/class:parrot_tools.workday.models.WorkerModel.md)

Clean, structured Worker model - Default output format.

## [CustomReportInput](entities/class:parrot_tools.workday.tool.CustomReportInput.md)

Input for executing a Workday RaaS custom report.

## [FindEmployeeByNameInput](entities/class:parrot_tools.workday.tool.FindEmployeeByNameInput.md)

Input for finding a worker by name.

## [GetCompanyPaymentDatesInput](entities/class:parrot_tools.workday.tool.GetCompanyPaymentDatesInput.md)

Input for retrieving company payment dates.

## [GetOrganizationInput](entities/class:parrot_tools.workday.tool.GetOrganizationInput.md)

Input for retrieving organization information.

## [GetPayrollBalancesInput](entities/class:parrot_tools.workday.tool.GetPayrollBalancesInput.md)

Input for retrieving payroll balances.

## [GetPayrollResultsInput](entities/class:parrot_tools.workday.tool.GetPayrollResultsInput.md)

Input for retrieving payroll results (historical/off-cycle).

## [GetTimeOffBalanceInput](entities/class:parrot_tools.workday.tool.GetTimeOffBalanceInput.md)

Input for retrieving time off balance information.

## [GetTimeOffBalanceInput2](entities/class:parrot_tools.workday.tool.GetTimeOffBalanceInput2.md)

Input for retrieving time off plan balances.

## [GetTimeOffHistoryInput](entities/class:parrot_tools.workday.tool.GetTimeOffHistoryInput.md)

Input for retrieving a worker's time-off request history.

## [GetWorkerContactInput](entities/class:parrot_tools.workday.tool.GetWorkerContactInput.md)

Input for retrieving worker contact information.

## [GetWorkerInfoInput](entities/class:parrot_tools.workday.tool.GetWorkerInfoInput.md)

Input for retrieving worker information by ID.

## [GetWorkerInput](entities/class:parrot_tools.workday.tool.GetWorkerInput.md)

Input for retrieving a single worker by ID.

## [GetWorkerJobDataInput](entities/class:parrot_tools.workday.tool.GetWorkerJobDataInput.md)

Input for retrieving worker's job-related data.

## [RequestTimeOffInput](entities/class:parrot_tools.workday.tool.RequestTimeOffInput.md)

Input for submitting a time-off request.

## [SearchWorkersInput](entities/class:parrot_tools.workday.tool.SearchWorkersInput.md)

Input for searching workers with filters.

## [WorkdayToolkit](entities/class:parrot_tools.workday.tool.WorkdayToolkit.md)

Toolkit for interacting with Workday via SOAP/WSDL with multi-service support.

## [WorkdayToolkitInput](entities/class:parrot_tools.workday.tool.WorkdayToolkitInput.md)

Default configuration for Workday toolkit operations.

## [YFinanceArgs](entities/class:parrot_tools.yfinance.YFinanceArgs.md)

Argument schema for :class:`YFinanceTool`.

## [YFinanceTool](entities/class:parrot_tools.yfinance.YFinanceTool.md)

Retrieve quotes, company information, and financial statements via Yahoo Finance.

## [CloseTicketInput](entities/class:parrot_tools.zammad.CloseTicketInput.md)

Input schema for ``zammad_close_ticket``.

## [CreateTicketInput](entities/class:parrot_tools.zammad.CreateTicketInput.md)

Input schema for ``zammad_create_ticket``.

## [CreateUserInput](entities/class:parrot_tools.zammad.CreateUserInput.md)

Input schema for ``zammad_create_user``.

## [DeleteTicketInput](entities/class:parrot_tools.zammad.DeleteTicketInput.md)

Input schema for the (excluded) ``delete_ticket`` method.

## [GetArticlesInput](entities/class:parrot_tools.zammad.GetArticlesInput.md)

Input schema for ``zammad_get_articles``.

## [GetAttachmentInput](entities/class:parrot_tools.zammad.GetAttachmentInput.md)

Input schema for ``zammad_get_attachment``.

## [GetTicketInput](entities/class:parrot_tools.zammad.GetTicketInput.md)

Input schema for ``zammad_get_ticket``.

## [GetUserInput](entities/class:parrot_tools.zammad.GetUserInput.md)

Input schema for ``zammad_get_user``.

## [ListTicketsInput](entities/class:parrot_tools.zammad.ListTicketsInput.md)

Input schema for ``zammad_list_tickets``.

## [SearchTicketsInput](entities/class:parrot_tools.zammad.SearchTicketsInput.md)

Input schema for ``zammad_search_tickets``.

## [SearchUsersInput](entities/class:parrot_tools.zammad.SearchUsersInput.md)

Input schema for ``zammad_search_users``.

## [UpdateTicketInput](entities/class:parrot_tools.zammad.UpdateTicketInput.md)

Input schema for ``zammad_update_ticket``.

## [ZammadToolkit](entities/class:parrot_tools.zammad.ZammadToolkit.md)

Toolkit exposing Zammad helpdesk operations as agent tools.

## [BasicZipcodeInput](entities/class:parrot_tools.zipcode.BasicZipcodeInput.md)

Basic input schema for zipcode operations.

## [CityToZipcodesInput](entities/class:parrot_tools.zipcode.CityToZipcodesInput.md)

Input schema for city to zipcodes lookup.

## [ZipcodeAPIToolkit](entities/class:parrot_tools.zipcode.ZipcodeAPIToolkit.md)

Toolkit for interacting with ZipcodeAPI service.

## [ZipcodeDistanceInput](entities/class:parrot_tools.zipcode.ZipcodeDistanceInput.md)

Input schema for zipcode distance calculation.

## [ZipcodeRadiusInput](entities/class:parrot_tools.zipcode.ZipcodeRadiusInput.md)

Input schema for zipcode radius search.

## [ZoomUsInterface](entities/class:parrot_tools.zoom.client.ZoomUsInterface.md)

Interface for interacting with Zoom.us API via Server-to-Server OAuth.

## [GetAccountSettingsInput](entities/class:parrot_tools.zoomtoolkit.GetAccountSettingsInput.md)

Input schema for get_account_settings.

## [ZoomUsToolkit](entities/class:parrot_tools.zoomtoolkit.ZoomUsToolkit.md)

Toolkit for interacting with Zoom.us API.

## [AI-Parrot — Architectural Context](overviews/doc:agent-context-md.md)

Async-first Python framework for building AI Agents and Chatbots.

## [Async Programming Expert](overviews/doc:agent-rules-async-programming-expert-md.md)

trigger: glob

## [Code Reviewer](overviews/doc:agent-rules-code-reviewer-md.md)

trigger: model_decision

## [Cython Development](overviews/doc:agent-rules-cython-development-md.md)

trigger: glob

## [🛸 Antigravity Directives (v1.0)](overviews/doc:agent-rules-md.md)

You are running inside Google Antigravity. DO NOT just write code.

## [Patching Files](overviews/doc:agent-rules-patching-files-md.md)

name: patch-plan

## [Prompt Expert](overviews/doc:agent-rules-prompt-expert-md.md)

trigger: model_decision

## [Python Development](overviews/doc:agent-rules-python-development-md.md)

trigger: always_on

## [Refactor Planner Expert](overviews/doc:agent-rules-refactor-planner-expert-md.md)

trigger: always_on

## [Rust Development](overviews/doc:agent-rules-rust-development-md.md)

trigger: glob

## [Browser Automation with agent-browser (async Playwright)](overviews/doc:agent-skills-agent-browser-skill-md.md)

name: agent-browser

## [Code Review Skill](overviews/doc:agent-skills-code-review-skill-md.md)

name: code-review

## [Codex Specifications Skill](overviews/doc:agent-skills-codex-specifications-skill-md.md)

name: codex-specifications

## [NumPy 2.0 Migration Reference](overviews/doc:agent-skills-cython-extensions-references-numpy-04aa993d.md)

This reference provides detailed information about deprecated types and breaking changes in NumPy 2.0 relevant to Cython extension builds.

## [Building Cython Extension Packages](overviews/doc:agent-skills-cython-extensions-skill-md.md)

name: build-cython-ext

## [Data Storytelling](overviews/doc:agent-skills-data-storytelling-skill-md.md)

name: data-storytelling

## [Database Schema Validator Skill](overviews/doc:agent-skills-database-schema-validator-skill-md.md)

name: database-schema-validator

## [Skill](overviews/doc:agent-skills-docstring-skill-md.md)

name: docstring

## [Skill](overviews/doc:agent-skills-git-commit-formatter-skill-md.md)

name: git-commit-formatter

## [JSON to Pydantic Skill](overviews/doc:agent-skills-json-to-pydantic-skill-md.md)

name: json-to-pydantic

## [License Header Adder Skill](overviews/doc:agent-skills-license-header-adder-skill-md.md)

name: license-header-adder

## [SKILL: Analyze Task Complexity](overviews/doc:agent-skills-meta-prompting-analyze-complexity-skill-md.md)

Determine the optimal meta-prompting strategy for any task by analyzing complexity factors and routing to the appropriate approach.

## [SKILL: Assess Output Quality](overviews/doc:agent-skills-meta-prompting-assess-quality-skill-md.md)

Score LLM output quality (0.0-1.0) against task requirements to determine if iteration is needed or solution is complete.

## [SKILL: Extract Context from Output](overviews/doc:agent-skills-meta-prompting-extract-context-skill-md.md)

Analyze LLM outputs to extract patterns, constraints, and success indicators that can improve subsequent iterations.

## [SKILL: Meta-Prompt Iterate](overviews/doc:agent-skills-meta-prompting-meta-prompt-iterate-skill-md.md)

Recursively improve LLM outputs through quality-driven iteration with automatic complexity routing, context extraction, and quality assessment.

## [Meta-Prompting Framework](overviews/doc:agent-skills-meta-prompting-skill-md.md)

name: meta-prompting

## [ai-parrot Tool Scaffold Skill](overviews/doc:agent-skills-parrot-scaffold-tool-skill-md.md)

name: parrot-tool-scaffold

## [Production Dockerfile Skill](overviews/doc:agent-skills-production-dockerfile-skill-md.md)

name: production-dockerfile

## [Python Standards](overviews/doc:agent-skills-python-standards-skill-md.md)

name: Python Standards

## [Changelog](overviews/doc:agent-skills-reverse-engineering-api-changelog-md.md)

All notable changes to the Reverse Engineering API skill will be documented in this file.

## [Authentication Patterns Reference](overviews/doc:agent-skills-reverse-engineering-api-references-eaa41ffd.md)

This document covers common authentication patterns found in web APIs and how to handle them when generating API clients. These patterns align with the reverse-api-engineer codebase conventions.

## [HAR File Analysis Reference](overviews/doc:agent-skills-reverse-engineering-api-references-556ead1d.md)

This document covers how to analyze HAR (HTTP Archive) files to extract API endpoints and patterns.

## [Reverse Engineering API Skill](overviews/doc:agent-skills-reverse-engineering-api-skill-md.md)

name: reverse-engineering-api

## [Rust + PyO3 function skill (eo-processor)](overviews/doc:agent-skills-rust-pyo3-function-skill-md.md)

name: rust-pyo3-function

## [Skill Creator](overviews/doc:agent-skills-skill-creator-readme-md.md)

This skill allows the user to create new skills for the agent.

## [Output Patterns](overviews/doc:agent-skills-skill-creator-references-output-patterns-md.md)

Use these patterns when skills need to produce consistent, high-quality output.

## [Workflow Patterns](overviews/doc:agent-skills-skill-creator-references-workflows-md.md)

For complex tasks, break operations into clear, sequential steps. It is often helpful to give Claude an overview of the process towards the beginning of SKILL.md:

## [Skill Creator](overviews/doc:agent-skills-skill-creator-skill-md.md)

name: skill-creator

## [Using Git Worktrees](overviews/doc:agent-skills-using-git-worktrees-skill-md.md)

name: using-git-worktrees

## [Goal](overviews/doc:agent-skills-worktree-pr-and-clean-skill-md.md)

name: worktree-pr-and-clean

## [Goal](overviews/doc:agent-skills-worktree-start-feature-skill-md.md)

name: worktree-start-feature

## [Goal](overviews/doc:agent-skills-worktree-status-skill-md.md)

name: worktree-status

## [System Prompt for Antigravity IDE](overviews/doc:agent-system-prompt-md.md)

You are an advanced AI assistant operating within the **Google Antigravity IDE**. Your primary goal is to assist the user in building high-quality, autonomous agents powered by Gemini 3.

## [Create Parrot Tool](overviews/doc:agent-workflows-create-parrot-tool-md.md)

description: Create a new Parrot Tool

## [Workflow Creator](overviews/doc:agent-workflows-create-workflow-md.md)

description: Create an antigravity Workflow

## [Generate Tests Workflow](overviews/doc:agent-workflows-generate-tests-md.md)

description: Generate comprehensive pytest suites

## [Git New Feature](overviews/doc:agent-workflows-git-new-feature-md.md)

description: Create a new feature from main branch

## [Parrot Mcp Server](overviews/doc:agent-workflows-parrot-mcp-server-md.md)

description: Scaffold a SimpleMCPServer for a designated Parrot Tool

## [Release Package](overviews/doc:agent-workflows-release-package-md.md)

description: Release Package

## [Run Python Command](overviews/doc:agent-workflows-run-python-command-md.md)

description: Run a Python command inside the virtual environment

## [/brainstorm — Structured Idea Exploration](overviews/doc:agent-workflows-sdd-brainstorm-md.md)

description: Structured brainstorming for projects and features. Explores multiple options before implementation.

## [/sdd-codereview — Code Review a Completed Task](overviews/doc:agent-workflows-sdd-codereview-md.md)

description: Run a code-review analysis over a completed SDD task

## [/sdd-fromjira — Bootstrap Brainstorm from Jira](overviews/doc:agent-workflows-sdd-fromjira-md.md)

description: Bootstrap an SDD Brainstorm from a Jira ticket using mcp-atlassian

## [/sdd-next — Suggest Next Tasks to Assign](overviews/doc:agent-workflows-sdd-next-md.md)

description: Suggest next unblocked SDD tasks to assign

## [/sdd-proposal — Feature Proposal & Discussion](overviews/doc:agent-workflows-sdd-proposal-md.md)

description: Propose and discuss a feature idea before building a spec

## [/sdd-spec — Scaffold a Feature Specification](overviews/doc:agent-workflows-sdd-spec-md.md)

description: Scaffold a Feature Specification using SDD methodology

## [/sdd-start — Start an SDD Task](overviews/doc:agent-workflows-sdd-start-md.md)

description: Start working on an SDD task by name or ID

## [/sdd-status — Show Task Status](overviews/doc:agent-workflows-sdd-status-md.md)

description: Show SDD task index status summary

## [/sdd-task — Generate Task Artifacts from a Spec](overviews/doc:agent-workflows-sdd-task-md.md)

description: Decompose an approved spec into SDD Task Artifacts

## [/sdd-tojira — Export Specification to Jira](overviews/doc:agent-workflows-sdd-tojira-md.md)

description: Export an SDD Specification to a Jira Story using mcp-atlassian

## [Start Flow](overviews/doc:agent-workflows-start-flow-md.md)

description: A fresh startup for work

## [AI-Parrot Development Guide for Claude](overviews/doc:claude-md.md)

Async-first Python framework for AI Agents and Chatbots.

## [A2A Secure Communication Demo](overviews/doc:docs-a2a-communication-md.md)

This demo showcases secure Agent-to-Agent (A2A) communication with JWT authentication,

## [Agent Configuration via `agents.yaml`](overviews/doc:docs-agent-config-creation-md.md)

The AI-Parrot `AgentRegistry` allows you to define and manage agents declaratively using a YAML configuration file. This approach is preferred for static agent definitions, enabling easy modification of models, tools, and behaviors without changing code.

## [AgentFactory HTTP API](overviews/doc:docs-agent-factory-handler-md.md)

Reference for the `AgentFactoryHandler` endpoint and the HITL flow needed

## [AgentTalk Integration Guide](overviews/doc:docs-agent-md.md)

This guide covers the new **AgentTalk** HTTP handler and the migration of MCP support directly into `BasicAgent`. These changes provide a more flexible and powerful way to interact with agents via HTTP APIs.

## [Agent Mesh](overviews/doc:docs-agent-mesh-md.md)

┌─────────────────────────────────────────────────────────────────────┐

## [AgentService — Standalone Runtime for Autonomous Agents](overviews/doc:docs-agent-service-md.md)

Agent resolution uses `BotManager.get_bot()` — the same mechanism used by `TelegramBotManager` and the `AutonomyOrchestrator`.

## [API Endpoints Reference](overviews/doc:docs-api-endpoints-md.md)

[Back to README](../README.md)

## [Ephemeral User Agents — Frontend Integration Handoff](overviews/doc:docs-api-feat-149-ephemeral-agents-api-md.md)

An *ephemeral user agent* is a personal AI assistant that lives entirely in

## [A2A (Agent-to-Agent)](overviews/doc:docs-api-reference-a2a-md.md)

::: parrot.a2a

## [Bots](overviews/doc:docs-api-reference-bots-md.md)

::: parrot.bots

## [Clients](overviews/doc:docs-api-reference-clients-md.md)

::: parrot.clients

## [API Reference](overviews/doc:docs-api-reference-index-md.md)

This section is generated automatically from the docstrings of the

## [Integrations](overviews/doc:docs-api-reference-integrations-md.md)

::: parrot.integrations

## [Loaders](overviews/doc:docs-api-reference-loaders-md.md)

::: parrot.loaders

## [MCP (Model Context Protocol)](overviews/doc:docs-api-reference-mcp-md.md)

::: parrot.mcp

## [Memory](overviews/doc:docs-api-reference-memory-md.md)

::: parrot.memory

## [Stores](overviews/doc:docs-api-reference-stores-md.md)

::: parrot.stores

## [Tools](overviews/doc:docs-api-reference-tools-md.md)

::: parrot.tools

## [1. MCP Server — exposing tools as a service](overviews/doc:docs-architecture-01-mcp-server-md.md)

AI-Parrot can act as an **MCP server** so that any MCP-compatible client

## [2. A2A — exposing agents and orchestrators as services](overviews/doc:docs-architecture-02-a2a-md.md)

Where MCP exposes **tools**, A2A (Agent-to-Agent) exposes **agents**:

## [3. Toolkits for third-party services and Cloud-Security composition](overviews/doc:docs-architecture-03-toolkits-md.md)

This chapter is a curated catalogue of toolkits in

## [4. Interaction surface — WebSockets, audio, integrations](overviews/doc:docs-architecture-04-interaction-surface-md.md)

AI-Parrot speaks to humans through a deliberately polyglot front. Every

## [5. Hardening — anti-prompt-injection, PBAC and tool gating](overviews/doc:docs-architecture-05-hardening-md.md)

Hardening is layered: every request crosses **transport auth → user

## [6. Cross-cutting concerns and reference deployment](overviews/doc:docs-architecture-06-cross-cutting-md.md)

The diagram below traces a single user message from any channel down to

## [7. AgentCrew — Sequential, Parallel, Flow and Loop execution](overviews/doc:docs-architecture-07-agentcrew-md.md)

prompt, a crew owns a *roster of agents* and chooses **how** they are

## [8. AgentsFlow — DAG-first orchestration with per-node FSM](overviews/doc:docs-architecture-08-agentsflow-dag-md.md)

AI-Parrot's dedicated **Directed Acyclic Graph executor**. Where

## [9. Ontologic RAG — graph-first retrieval, intent routing & multi-tenant knowledge](overviews/doc:docs-architecture-09-ontologic-rag-md.md)

graph TB

## [10. Observability — OpenLIT + OpenTelemetry](overviews/doc:docs-architecture-10-observability-md.md)

AI-Parrot ships a first-class observability subsystem that turns every LLM

## [AI-Parrot — Exposure, Interoperability & Hardening Architecture](overviews/doc:docs-architecture-readme-md.md)

All file references in the chapters use the `package/path/file.py:line`

## [ArxivTool for AI-Parrot](overviews/doc:docs-arxiv-tool-readme-md.md)

A comprehensive tool for searching and retrieving academic papers from arXiv.org, designed to integrate seamlessly with the AI-Parrot framework.

## [Audio Form Voice Modes — Developer Guide](overviews/doc:docs-audio-form-voice-modes-md.md)

1. [What Changed in FEAT-236](#1-what-changed-in-feat-236)

## [AI-Parrot MCP Server - AWS Deployment Guide](overviews/doc:docs-aws-deployment-md.md)

Este directorio contiene todo lo necesario para desplegar un **SimpleMCPServer** de AI-Parrot en AWS, ya sea usando **App Runner** o **Fargate**.

## [Bot Cleanup Lifecycle](overviews/doc:docs-bot-cleanup-lifecycle-md.md)

This document describes how AI-Parrot bots are torn down cleanly during

## [Bots & Agents](overviews/doc:docs-chapters-bots-agents-md.md)

A **bot** in AI-Parrot is a stateful conversational entity wrapped

## [Foundations](overviews/doc:docs-chapters-foundations-md.md)

The foundations layer holds the core abstractions every other module in

## [Integrations & Transport](overviews/doc:docs-chapters-integrations-md.md)

AI-Parrot ships first-class integrations with messaging platforms

## [LLM Clients](overviews/doc:docs-chapters-llm-clients-md.md)

AI-Parrot talks to every LLM provider through a single

## [Memory & Knowledge](overviews/doc:docs-chapters-memory-knowledge-md.md)

AI-Parrot separates two concerns that often get confused: **memory**

## [Tools, Loaders & RAG](overviews/doc:docs-chapters-tools-rag-md.md)

Agents are useful only as far as their tools let them act on the world.

## [=== D3.js ===](overviews/doc:docs-charts-samples-md.md)

from parrot.bots import BasicAgent

## [Class Catalog by Module](overviews/doc:docs-classes-md.md)

[Back to README](../README.md)

## [Per-Loop LLM Client Cache](overviews/doc:docs-clients-per-loop-cache-md.md)

cross-loop runtime errors in production.

## [CompanyInfoToolkit](overviews/doc:docs-company-info-md.md)

A comprehensive toolkit for scraping company information from multiple business intelligence platforms. Built as an extension of AI-Parrot's `AbstractToolkit`, this toolkit provides unified access to company data from ZoomInfo, LeadIQ, Explorium, RocketReach, and SICCode.

## [AI-Parrot Configuration Guide](overviews/doc:docs-config-md.md)

This document describes the most important configuration values for AI-Parrot. All configuration values are loaded from `.env` files in the `env/` folder using `navconfig`.

## [Contextual Embedding Headers](overviews/doc:docs-contextual-embedding-md.md)

When you ingest documents into a vector store today, each chunk is embedded as

## [Usage Example](overviews/doc:docs-crew-handler-md.md)

"""

## [Agent Orchestration System - Complete Guide](overviews/doc:docs-crew-md.md)

The Agent Orchestration System allows you to coordinate multiple AI agents to work together on complex tasks. It supports:

## [Método `summary()` - Documentación Completa](overviews/doc:docs-crew-summary-md.md)

El método `summary()` genera reportes completos o resúmenes ejecutivos de todos los resultados del crew, con dos modos de operación optimizados para diferentes casos de uso.

## [Database Agent](overviews/doc:docs-database-agent-md.md)

AI-Parrot's **Database Agent** is a conversational AI system that connects to databases, understands natural language questions, generates queries, executes them, and returns formatted results tailored to the user's role. It supports SQL, NoSQL, time-series, and search databases 

## [DatasetManager Implementation Walkthrough](overviews/doc:docs-datasetmanager-design-md.md)

Implemented a `DatasetManager` class that acts as a data catalog and toolkit for `PandasAgent`, replacing the standalone `MetadataTool` with integrated functionality.

## [DecisionFlowNode Usage Guide](overviews/doc:docs-decision-node-usage-md.md)

The `DecisionFlowNode` component enables multi-agent decision-making within AgentsFlow workflows. It supports three decision modes: CIO (single coordinator), Ballot (voting), and Consensus (deliberative).

## [DocumentDB Interface Guide](overviews/doc:docs-documentdb-interface-md.md)

This guide describes how to use the `DocumentDb` interface to interact with AWS DocumentDB (or MongoDB-compatible databases).

## [Async context manager para cleanup automático](overviews/doc:docs-documentdb-md.md)

async with DocumentDb() as db:

## [DynamoDB Local (docker-compose)](overviews/doc:docs-dynamodb-local-md.md)

This page documents the local DynamoDB stack we use for developing the

## [ExecutionMemory Integration Guide](overviews/doc:docs-execution-memory-md.md)

ExecutionMemory is a powerful feature in AgentsFlow that enables sophisticated agent collaboration by automatically storing and retrieving execution results. Agents can access previous results from any agent in the workflow, enabling context-aware decision making and eliminating 

## [FormDesigner — Audio Renderer](overviews/doc:docs-formdesigner-audio-renderer-md.md)

1. [¿Qué es el Audio Renderer?](#1-qué-es-el-audio-renderer)

## [Form Designer — Conditional Sections: Pre/Post Dependencies](overviews/doc:docs-formdesigner-conditional-sections-md.md)

This document is the authoritative reference for the conditional-logic system

## [FredAPITool Documentation](overviews/doc:docs-fred-api-tool-md.md)

The `FredAPITool` allows `ai-parrot` agents to interact with the Federal Reserve Economic Data (FRED) API. It provides access to a vast repository of economic data series, including interest rates, inflation metrics, employment numbers, and more.

## [Guía Técnica de Voz (AgentTalk Voice) para Frontend](overviews/doc:docs-frontend-agentalk-voice-frontend-guide-md.md)

(grabar y enviar nota de voz + reproducir la contestación hablada del agente)

## [Guía Técnica del Avatar (LiveAvatar Phase A) para Frontend](overviews/doc:docs-frontend-liveavatar-frontend-guide-md.md)

el **vídeo + audio** en el navegador.

## [Guía Frontend (SvelteKit) — LiveAvatar FULL Mode + VoiceBot (FEAT-248)](overviews/doc:docs-frontend-liveavatar-fullmode-sveltekit-guide-md.md)

para conversar **por voz con un agente de ai-parrot mostrando un avatar

## [⚠️ DEPRECATED — Guía Técnica del Avatar Voz-Nativo (LiveAvatar Phase C) para Frontend](overviews/doc:docs-frontend-liveavatar-phase-c-frontend-guide-md.md)

micrófono, el agente responde con voz y cara (lip-sync), y los **artefactos

## [Guía Técnica de Artefactos Estructurados para Frontend](overviews/doc:docs-frontend-structured-artifacts-frontend-guide-md.md)

1. [Modelo mental: el contrato común](#1-modelo-mental-el-contrato-común)

## [VoiceBot · VoiceChatHandler · FEAT-245 — Guía de Frontend para Conversación Realtime con Agentes](overviews/doc:docs-frontend-voicebot-realtime-frontend-guide-md.md)

┌──────────────────────────── Browser (tu UI) ───────────────────────────┐

## [Module-level Functions Catalog](overviews/doc:docs-functions-md.md)

[Back to README](../README.md)

## [GitHub Reviewer Agent](overviews/doc:docs-github-reviewer-md.md)

An autonomous AI-Parrot agent that reviews GitHub pull requests against the

## [HeartbeatManager — Per-Agent Autonomous Heartbeat Loop](overviews/doc:docs-heartbeat-manager-md.md)

Unlike a cron scheduler (which fires unconditionally at fixed intervals), the

## [EmployeesTool - Employee Hierarchy Tool for AI-Parrot](overviews/doc:docs-hierarchy-tool-md.md)

A comprehensive tool for querying and analyzing employee organizational hierarchies in AI-Parrot. This tool provides a unified interface for agents and chatbots to access employee relationships, reporting structures, and departmental information.

## [HITL Tool-Call Confirmation (FEAT-235)](overviews/doc:docs-hitl-confirmation-md.md)

AI-Parrot agents can now pause before executing side-effecting or irreversible

## [Teams HITL Channel Setup Guide (FEAT-205)](overviews/doc:docs-hitl-teams-channel-md.md)

Human-in-the-Loop over Microsoft Teams — setup, deployment prerequisites,

## [AI-Parrot](overviews/doc:docs-index-md.md)

hide:

## [Infographic Handler — Frontend API Contract](overviews/doc:docs-infographic-handler-api-md.md)

This document is the authoritative contract for talking to the Infographic HTTP API exposed by ai-parrot. It covers URL shapes, request payloads, response shapes, error codes, built-in templates/themes and the data blocks the LLM can return.

## [GitHub MCP Installation and Usage](overviews/doc:docs-install-github-mcp-md.md)

This guide explains how to install and use the GitHub MCP server with `ai-parrot`.

## [add repository:](overviews/doc:docs-install-mcp-genmedia-md.md)

Remove old version:

## [Installation Guide](overviews/doc:docs-install-md.md)

[Back to README](../README.md)

## [Semantic UI Model → Adaptive Cards (FEAT-303)](overviews/doc:docs-integrations-msagentsdk-semantic-cards-md.md)

365 Copilot / Teams.

## [Office 365 OAuth 2.0 (Delegated) — AI-Parrot Integration](overviews/doc:docs-integrations-office365-oauth2-md.md)

This guide documents the Microsoft Graph delegated permissions required by

## [Interactive Artifacts — Frontend API Contract](overviews/doc:docs-interactive-artifacts-api-md.md)

This document is the authoritative contract for requesting and rendering **Interactive Artifacts** — self-contained HTML pages (dashboards, wizards, data grids, diagrams, reports) generated by the LLM using a curated catalog of vetted JavaScript libraries. It covers the conversat

## [JiraSpecialist Prompt-Layer Stack](overviews/doc:docs-jira-specialist-prompt-layers-md.md)

Before FEAT-138, `JiraSpecialist` used a single 500-line string assigned

## [Jira Transition Actions — Activating `TRIGGER_AGENT` Dispatch](overviews/doc:docs-jira-transition-actions-md.md)

them, and routes `jira.transitioned` events through

## [JobManagerMixin Architecture Documentation](overviews/doc:docs-jobmanager-md.md)

The `JobManagerMixin` is a sophisticated architectural pattern that bridges synchronous web views with asynchronous job execution systems. It was designed specifically for AI-Parrot's needs but maintains flexibility for any Python web framework.

## [Jupyter Output Mode Documentation](overviews/doc:docs-jupyter-mode-md.md)

The **Jupyter Output Mode** provides specialized formatting for Jupyter notebooks with interactive widgets, rich markdown rendering, and collapsible sections. It automatically detects Jupyter environments and provides the best possible display experience.

## [LiveAvatar over your own LiveKit (Cloud or self-hosted)](overviews/doc:docs-liveavatar-byo-livekit-md.md)

This runbook wires the **kept "LITE over LiveKit" transport** (FEAT-242 /

## [LLM Wiki — an agent-maintained knowledge repository](overviews/doc:docs-llm-wiki-md.md)

Classic RAG re-synthesises an answer from raw text on every query and throws the

## [Loader Metadata Standard](overviews/doc:docs-loaders-metadata-md.md)

Every `Document.metadata` dict produced by a loader follows this structure:

## [Local Kb](overviews/doc:docs-local-kb-md.md)

1. Durante `configure()`, se busca `AGENTS_DIR/<agent_name>/kb/*.md`

## [Matryoshka Embedding Truncation](overviews/doc:docs-matryoshka-embeddings-md.md)

Matryoshka Representation Learning (MRL) trains embedding models so that a

## [Create and configure agent](overviews/doc:docs-mcp-session-md.md)

Fireflies MCP Server Configuration Fix

## [WhatsApp Integration - Resumen de Implementación](overviews/doc:docs-messaging-implement-whatsapp-md.md)

He implementado una integración completa de WhatsApp para AI-Parrot que te permite:

## [WhatsApp Integration for AI-Parrot](overviews/doc:docs-messaging-whatsapp-md.md)

Complete WhatsApp integration using **whatsmeow** (Go) bridge with Python hooks for autonomous agents.

## [Migration — FEAT-201: ai-parrot-embeddings](overviews/doc:docs-migration-feat-201-ai-parrot-embeddings-md.md)

The concrete backends for embeddings, vector stores, and rerankers moved

## [Migration Guide: FEAT-202 — ai-parrot-integrations](overviews/doc:docs-migration-feat-202-ai-parrot-integrations-md.md)

FEAT-202 extracts messaging channel integrations (Slack, Telegram, MS Teams,

## [Migration — FEAT-203: ai-parrot-server](overviews/doc:docs-migration-feat-203-ai-parrot-server-md.md)

BotManager, MCP/A2A server transports, scheduler, or autonomous orchestrator.

## [FEAT-223 — Structured Artifact Contract: Migration Guide](overviews/doc:docs-migration-feat-223-structured-artifact-contract-md.md)

FEAT-223 homologates the three structured-output renderers

## [FEAT-273 — Legacy output-mode deprecations → A2UI](overviews/doc:docs-migration-feat-273-a2ui-deprecations-md.md)

The A2UI rendering pipeline (`OutputMode.A2UI`, `parrot.outputs.a2ui`) supersedes the

## [MS Teams Toolkit for AI-Parrot](overviews/doc:docs-msteams-md.md)

A comprehensive toolkit for Microsoft Teams integration, extending `AbstractToolkit` from the ai-parrot library.

## [OdooToolkit Capabilities](overviews/doc:docs-odoo-toolkit-capabilities-md.md)

The `OdooToolkit` exposes Odoo ERP operations as agent tools. It composes an Odoo transport (JSON-2, JSONRPC, or XML-RPC depending on the detected version) and turns each of its public async methods into a tool.

## [Infographic CSP and Signed URLs — Operations Guide](overviews/doc:docs-operations-infographic-csp-and-signed-urls-md.md)

GET /api/v1/artifacts/public/{signature}/{artifact_id}.html

## [AI-Parrot Agent Orchestration Documentation](overviews/doc:docs-orchestration-md.md)

AI-Parrot provides powerful agent orchestration capabilities through two main classes:

## [OrchestratorAgent — Multi-Party Conferencing (`confer`)](overviews/doc:docs-orchestrator-conferencing-md.md)

LLM-driven `ask()` ReAct loop. Instead of letting an LLM pick which

## [Smart OutputFormatter Documentation](overviews/doc:docs-outputs-md.md)

The **Smart OutputFormatter** is an intelligent rendering system that automatically detects visualization types (Folium maps, Plotly charts, DataFrames, etc.) and renders them appropriately based on the environment (Terminal, HTML, Jupyter).

## [PageIndex — Tree-Based RAG for Document Retrieval](overviews/doc:docs-pageindex-md.md)

PageIndex builds a **hierarchical semantic tree** from PDF and Markdown documents using LLM reasoning, then uses that tree for **vectorless, context-aware retrieval**. Unlike embedding-based RAG, PageIndex navigates the document structure to find relevant sections — no vector dat

## [Capacidades de un Agente Analítico AI-Parrot (PandasAgent)](overviews/doc:docs-pandas-agent-capabilities-md.md)

1. [Anatomía de un agente analítico](#1-anatomía-de-un-agente-analítico)

## [Parent-Child Retrieval (Small-to-Big)](overviews/doc:docs-parent-child-retrieval-md.md)

Parent-child retrieval is a small-to-big strategy that improves answer quality

## [AI-Parrot · Roadmap McKinsey-Delta](overviews/doc:docs-parrot-roadmap-2026-md.md)

Cada feature usa el flujo SDD: `brainstorm → proposal → spec → tasks → worktree → PR a dev`. Los IDs `FEAT-A/B/...` son placeholders del documento McKinsey-delta; al iniciar `/sdd-spec` recibirán su `FEAT-NNN` real.

## [PR Review Command — Setup Guide](overviews/doc:docs-pr-review-setup-md.md)

This guide covers installing and configuring the prerequisites for the `/pr-review` Claude Code command.

## [Product Analysis — Structured Table Output Mode](overviews/doc:docs-product-analysis-structured-table-analysis-md.md)

Add `OutputMode.STRUCTURED_TABLE` — the table sibling of `STRUCTURED_CHART` (FEAT-215) —

## [Layers Reference](overviews/doc:docs-prompts-layers-reference-md.md)

Complete reference for every built-in and domain-specific `PromptLayer`

## [gVisor Installation Guide for AI-Parrot Secure Sandbox](overviews/doc:docs-sandbox-tool-md.md)

This guide provides step-by-step instructions for setting up gVisor on Ubuntu to enable secure Python code execution in AI-Parrot. gVisor provides kernel-level isolation, protecting your system from potentially malicious LLM-generated code.

## [Guía de uso de los comandos `/sdd-*`](overviews/doc:docs-sdd-guide-md.md)

SDD es nuestra forma de trabajar features con Claude Code. La regla

## [AI-Parrot Spec-Driven Development (SDD) Platform](overviews/doc:docs-sdd-platform-md.md)

A reference for the `/sdd-*` command suite under `.claude/commands/`, the

## [AI-Parrot SDD Workflow for Claude Code](overviews/doc:docs-sdd-workflow-md.md)

This document defines the **Spec-Driven Development (SDD)** methodology for AI-Parrot,

## [SecurityAdvisor — SOC2-Oriented Read-Only Advisory Agent](overviews/doc:docs-security-advisor-md.md)

already collected by `SecurityAgent` into actionable, audit-ready intelligence.

## [SimpleMCPServer Configuration](overviews/doc:docs-simple-mcp-server-config-md.md)

The `SimpleMCPServer` can be configured via a YAML file. This document details the supported configuration options, including all authentication methods.

## [Simple Mcp Server](overviews/doc:docs-simple-mcp-server-md.md)

Walkthrough - YAML Configurable SimpleMCPServer

## [SpawnSubAgentTool](overviews/doc:docs-spawn-subagent-tool-md.md)

Spawn ephemeral sub-agents on-the-fly to delegate bounded work, then tear them

## [Storage Backends Guide](overviews/doc:docs-storage-backends-md.md)

AI-Parrot persists chat history, conversation threads, and artifacts through a pluggable

## [AI Parrot Code Style Guide](overviews/doc:docs-style-guide-md.md)

[Back to README](../README.md)

## [FEAT-103 Code-Review Fixes Implementation Plan](overviews/doc:docs-superpowers-plans-2026-04-17-feat103-revie-49c8be5f.md)

class TestDeleteTurn:

## [FEAT-107 Review Fixes Implementation Plan](overviews/doc:docs-superpowers-plans-2026-04-17-feat107-revie-c06e5666.md)

cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo

## [OrchestratorAgent AIMessage Preservation — Implementation Plan](overviews/doc:docs-superpowers-plans-2026-04-20-orchestrator--4148c877.md)

Create `packages/ai-parrot/tests/test_agent_result_ai_message.py`:

## [MS Teams Agent Commands — Implementation Plan](overviews/doc:docs-superpowers-plans-2026-07-08-msteams-agent-f4f924c9.md)

Create `packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py`:

## [OrchestratorAgent AIMessage Preservation](overviews/doc:docs-superpowers-specs-2026-04-20-orchestrator--66729735.md)

OrchestratorAgent exposes specialist agents as tools via `AgentTool`. When a specialist

## [JiraToolkit — Remove Silent Default Auth](overviews/doc:docs-superpowers-specs-2026-07-06-jiratoolkit-r-b953bd06.md)

Now that the toolkit supports per-user OAuth 2.0 (3LO) authentication, the

## [MS Teams Agent Commands](overviews/doc:docs-superpowers-specs-2026-07-08-msteams-agent-57d97154.md)

The MS Teams wrapper (`MSTeamsAgentWrapper`) has no way to invoke agent methods directly. All user messages go through `agent.ask()` via the `FormOrchestrator`. The Telegram wrapper exposes `/function`, `/tool`, `/skill`, and other commands that allow direct method invocation, to

## [Crew Tools Catalog Endpoint](overviews/doc:docs-superpowers-specs-2026-07-14-crew-tools-ca-19ab0f6a.md)

The frontend crew builder hardcodes the list of tools that can be assigned to

## [Telegram Bot Integration Guide](overviews/doc:docs-telegram-integration-md.md)

1. Open Telegram and search for **@BotFather**

## [Testagent](overviews/doc:docs-testagent-md.md)

You are **Tester**, a Senior QA Automation Engineer specialized in high-performance Python architectures (`ai-parrot`).

## [AbstractTool Clone Method](overviews/doc:docs-tool-clone-md.md)

The `AbstractTool` class now includes a `clone()` method that allows you to create a new instance of a tool with the same configuration. This is useful when you need multiple instances of the same tool with identical settings.

## [Toolbar API Documentation](overviews/doc:docs-toolbar-api-md.md)

The `Toolbar API` allows modules and pages to dynamically inject buttons and actions into the global Top Toolbar of the AgentUI application. This ensures that context-specific actions are readily available to the user without cluttering the main content area.

## [InfographicToolkit — Reference](overviews/doc:docs-toolkits-infographic-toolkit-md.md)

artifacts in a single agent turn. With `return_direct=True` set on the toolkit,

## [AI-Parrot Tools Documentation](overviews/doc:docs-tools-md.md)

Complete reference guide for all available tools in the AI-parrot library.

## [AI-Parrot Tools Quick Reference Guide](overviews/doc:docs-tools-quick-md.md)

Fast lookup for all AI-parrot tools with minimal examples.

## [Uiagent](overviews/doc:docs-uiagent-md.md)

You are the **UI Agent**, a Senior Full-Stack Engineer specializing in:

## [User Profile Management](overviews/doc:docs-user-profile-md.md)

This document describes the user profile structure and how to configure profile attributes in AI Parrot.

## [Vector Store Handler — API Reference](overviews/doc:docs-vectorstore-handler-api-md.md)

REST API for vector store lifecycle management: create collections, load data (files, URLs, inline content), run test searches, and query configuration metadata.

## [🦜 AI-Parrot Voice Chat](overviews/doc:docs-voice-chat-md.md)

Real-time voice chat interface using **Gemini Live API** for native speech-to-speech interactions.

## [Web HITL — Frontend Brainstorm](overviews/doc:docs-web-hitl-frontend-brainstorm-md.md)

This document describes what the `navigator-frontend-next` codebase must implement

## [WhatIfTool Implementation - Complete Summary](overviews/doc:docs-whatif-tool-md.md)

A complete What-If scenario analysis tool for AI-Parrot's PandasAgent with the following capabilities:

## [WhatsApp + AutonomousOrchestrator Integration](overviews/doc:docs-whatsapp-autonomous-orchestrator-md.md)

Complete guide for connecting WhatsApp as an input channel to AI-Parrot's `AutonomousOrchestrator` via the WhatsApp Bridge and Redis Pub/Sub.

## [WhisperX Setup Guide for AI-Parrot](overviews/doc:docs-whisperx-md.md)

If you have an NVIDIA GPU:

## [AI-Parrot](overviews/doc:readme-md.md)

Whether you need a simple chatbot, a complex multi-agent orchestration workflow, or a robust production-ready AI service, AI-Parrot exposes the primitives to build it efficiently.

## [lazy_import()](concepts/func:parrot._imports.lazy_import.md)

Import a module lazily, raising a clear error if not installed.

## [require_extra()](concepts/func:parrot._imports.require_extra.md)

Verify that all required modules for an extras group are importable.

## [parse_role()](concepts/func:parrot.a2a.models.parse_role.md)

Parse a Role from either the v0.3 or the v1.0 format.

## [parse_task_state()](concepts/func:parrot.a2a.models.parse_task_state.md)

Parse a TaskState from either the v0.3 or the v1.0 format.

## [serialize_role()](concepts/func:parrot.a2a.models.serialize_role.md)

Serialize a Role to the wire value for the target protocol version.

## [serialize_task_state()](concepts/func:parrot.a2a.models.serialize_task_state.md)

Serialize a TaskState to the wire value for the target protocol version.

## [generate_api_key()](concepts/func:parrot.a2a.security.generate_api_key.md)

Generate a secure API key.

## [generate_hmac_secret()](concepts/func:parrot.a2a.security.generate_hmac_secret.md)

Generate a secure HMAC secret.

## [get_request_identity()](concepts/func:parrot.a2a.security.get_request_identity.md)

Get the authenticated identity from a request.

## [hash_password()](concepts/func:parrot.a2a.security.hash_password.md)

Hash a password for storage.

## [require_permission()](concepts/func:parrot.a2a.security.require_permission.md)

Decorator to require a specific permission.

## [require_role()](concepts/func:parrot.a2a.security.require_role.md)

Decorator to require a specific role.

## [verify_password()](concepts/func:parrot.a2a.security.verify_password.md)

Verify a password against a hash.

## [generate_discriminant_questions()](concepts/func:parrot.advisors.generator.generate_discriminan-5fd7b812.md)

Convenience function to generate questions for a catalog.

## [create_advisor_tools()](concepts/func:parrot.advisors.tools.create_advisor_tools.md)

Factory function to create all advisor tools with shared dependencies.

## [infer_criteria_from_response()](concepts/func:parrot.advisors.tools.utils.infer_criteria_fro-edb95370.md)

Try to infer criteria from a free-form response.

## [normalize_price_value()](concepts/func:parrot.advisors.tools.utils.normalize_price_value.md)

Normalize price string to a float value.

## [enforce_agent_access()](concepts/func:parrot.auth.agent_guard.enforce_agent_access.md)

Raise ``AgentAccessDenied`` if the request's subject cannot resolve ``bot_name``.

## [parse_bot_permissions()](concepts/func:parrot.auth.agent_guard.parse_bot_permissions.md)

Validate and parse the JSONB shape stored in ``ai_bots.permissions``.

## [build_form_schema()](concepts/func:parrot.auth.confirmation.build_form_schema.md)

Build a FORM interaction schema from the tool's args_schema.

## [compute_args_hash()](concepts/func:parrot.auth.confirmation.compute_args_hash.md)

Produce a stable SHA-256 hash over normalized parameters.

## [render_briefing()](concepts/func:parrot.auth.confirmation.render_briefing.md)

Render a confirmation briefing string for the tool call.

## [revalidate_edit()](concepts/func:parrot.auth.confirmation.revalidate_edit.md)

Validate edited values against the tool's args_schema.

## [load_credentials_manifest()](concepts/func:parrot.auth.manifest.load_credentials_manifest.md)

Load credential provider configs from a YAML file.

## [parse_credentials_block()](concepts/func:parrot.auth.manifest.parse_credentials_block.md)

Parse a raw ``credentials:`` list (already parsed from YAML) into configs.

## [register_mcp_oauth2_provider()](concepts/func:parrot.auth.oauth2.mcp_provider.register_mcp_o-6963b38f.md)

Create an :class:`MCPOAuth2Provider` and register it in the global registry.

## [delete_user_agent_toolkits_by_provider()](concepts/func:parrot.auth.oauth2.persistence.delete_user_age-f450da77.md)

Cascade-delete all enablement records for ``(user_id, provider)``.

## [delete_users_integration()](concepts/func:parrot.auth.oauth2.persistence.delete_users_integration.md)

Hard-delete the credential record for ``(user_id, provider)``.

## [get_users_integration()](concepts/func:parrot.auth.oauth2.persistence.get_users_integration.md)

Fetch a single credential record by ``(user_id, provider)``.

## [list_user_agent_toolkits()](concepts/func:parrot.auth.oauth2.persistence.list_user_agent_toolkits.md)

Return all enablement records for a ``(user_id, agent_id)`` pair.

## [upsert_user_agent_toolkit()](concepts/func:parrot.auth.oauth2.persistence.upsert_user_age-b2050cf1.md)

Upsert an enablement record in ``user_agent_toolkits``.

## [upsert_users_integration()](concepts/func:parrot.auth.oauth2.persistence.upsert_users_integration.md)

Upsert a credential record in ``users_integrations``.

## [register_oauth2_provider()](concepts/func:parrot.auth.oauth2.registry.register_oauth2_provider.md)

Module-level convenience for application startup.

## [handle_mcp_oauth2_callback()](concepts/func:parrot.auth.oauth2_routes.handle_mcp_oauth2_callback.md)

Handle OAuth2 callback for MCP server authorization code flows.

## [make_oauth2_callback()](concepts/func:parrot.auth.oauth2_routes.make_oauth2_callback.md)

Return a request handler bound to ``provider_id``.

## [register_a2a_resume_hook()](concepts/func:parrot.auth.oauth2_routes.register_a2a_resume_hook.md)

Register an async callable to resume suspended A2A tasks after OAuth.

## [setup_mcp_oauth2_callback()](concepts/func:parrot.auth.oauth2_routes.setup_mcp_oauth2_callback.md)

Register the MCP OAuth2 callback route on *app*.

## [setup_oauth2_routes()](concepts/func:parrot.auth.oauth2_routes.setup_oauth2_routes.md)

Attach the OAuth2 callback route for ``provider_id`` to *app*.

## [setup_pbac()](concepts/func:parrot.auth.pbac.setup_pbac.md)

Initialize the PBAC engine and register it with the aiohttp application.

## [to_eval_context()](concepts/func:parrot.auth.permission.to_eval_context.md)

Bridge a PermissionContext to a navigator-auth EvalContext.

## [jira_oauth_callback()](concepts/func:parrot.auth.routes.jira_oauth_callback.md)

Handle ``GET /api/auth/jira/callback``.

## [setup_jira_oauth_routes()](concepts/func:parrot.auth.routes.setup_jira_oauth_routes.md)

Attach the Jira OAuth callback route to *app*.

## [admin_login_page()](concepts/func:parrot.autonomous.admin.admin_login_page.md)

Serve the admin login HTML page (no auth required).

## [autonomous()](concepts/func:parrot.autonomous.cli.autonomous.md)

Manage AutonomousOrchestrator agents.

## [create()](concepts/func:parrot.autonomous.cli.create.md)

Generate a sample AutonomousOrchestrator agent script.

## [install()](concepts/func:parrot.autonomous.cli.install.md)

Generate gunicorn, supervisord, and systemd configs for an agent.

## [create_sample_agent()](concepts/func:parrot.autonomous.deploy.installer.create_sample_agent.md)

Write a sample AutonomousOrchestrator agent script to *output_path*.

## [components_from_string()](concepts/func:parrot.bots.database.models.components_from_string.md)

Parse components from comma-separated string.

## [customize_components()](concepts/func:parrot.bots.database.models.customize_components.md)

Customize output components based on base role.

## [get_default_components()](concepts/func:parrot.bots.database.models.get_default_components.md)

Get default output components for a user role.

## [get_user_name()](concepts/func:parrot.bots.dynamic_values.get_user_name.md)

This one needs context to determine the user

## [finalize_agent_registration()](concepts/func:parrot.bots.factory.tools.finalize.finalize_ag-57df7731.md)

Write the YAML, reload the registry, and return the registration result.

## [write_agent_yaml()](concepts/func:parrot.bots.factory.tools.finalize.write_agent_yaml.md)

Persist an ``AgentDefinition`` as a YAML file under ``agents/<category>/``.

## [list_available_toolkits()](concepts/func:parrot.bots.factory.tools.introspection.list_a-e52caf54.md)

Return the registered toolkit catalog: name + class docstring summary.

## [list_available_tools()](concepts/func:parrot.bots.factory.tools.introspection.list_a-c4940872.md)

Return the catalog of standalone ``@tool`` functions discovered.

## [list_registered_agents()](concepts/func:parrot.bots.factory.tools.introspection.list_r-65013a96.md)

List agents currently known to ``AgentRegistry`` (YAML + decorator).

## [load_agent_definition()](concepts/func:parrot.bots.factory.tools.introspection.load_a-9f694593.md)

Return the ``BotConfig`` of a registered agent as a dict (for cloning).

## [register_openapi_toolkit()](concepts/func:parrot.bots.factory.tools.openapi_register.reg-2ff62279.md)

Materialise + register an OpenAPI toolkit.

## [provision_vector_store()](concepts/func:parrot.bots.factory.tools.vector_store.provisi-ebd1a8ea.md)

Create a PgVector table and return a ``StoreConfig``-shaped dict.

## [build_node_metadata()](concepts/func:parrot.bots.flows.core.result.build_node_metadata.md)

Create execution metadata for a node run.

## [determine_run_status()](concepts/func:parrot.bots.flows.core.result.determine_run_status.md)

Compute the overall status for a crew/flow execution.

## [get_result_storage()](concepts/func:parrot.bots.flows.core.storage.backends.factor-853efc99.md)

Resolve a ``ResultStorage`` instance.

## [synthesize_results()](concepts/func:parrot.bots.flows.core.storage.synthesis.synth-bc011a61.md)

LLM-summarize all agent responses collected in a ``FlowResult``.

## [build_deterministic_tabs()](concepts/func:parrot.bots.flows.crew.result_infographic.buil-623543e0.md)

Build the deterministic ``crew_report`` block list.

## [merge_tab1_blocks()](concepts/func:parrot.bots.flows.crew.result_infographic.merg-d7fc56c5.md)

Insert the LLM-authored Tab 1 as the first tab in the ``tab_view``.

## [extract_tool_output()](concepts/func:parrot.bots.flows.crew.tool_node.extract_tool_output.md)

Return the string form of a ``ToolResult`` payload.

## [resolve_templates()](concepts/func:parrot.bots.flows.crew.tool_node.resolve_templates.md)

Recursively resolve template placeholders inside a value.

## [create_action()](concepts/func:parrot.bots.flows.flow.actions.create_action.md)

Create an action instance from a configuration.

## [register_action()](concepts/func:parrot.bots.flows.flow.actions.register_action.md)

Decorator to register an action class in the ACTION_REGISTRY.

## [register_node()](concepts/func:parrot.bots.flows.flow.flow.register_node.md)

Register a Node subclass under ``name`` in ``NODE_REGISTRY``.

## [from_svelteflow()](concepts/func:parrot.bots.flows.flow.svelteflow.from_svelteflow.md)

Convert SvelteFlow node/edge data into a ``FlowDefinition``.

## [to_svelteflow()](concepts/func:parrot.bots.flows.flow.svelteflow.to_svelteflow.md)

Convert a ``FlowDefinition`` to SvelteFlow node/edge format.

## [load_agent_context()](concepts/func:parrot.bots.prompts.agent_context.load_agent_context.md)

Load the per-agent context file for the given agent ID.

## [get_domain_layer()](concepts/func:parrot.bots.prompts.domain_layers.get_domain_layer.md)

Look up a registered domain layer by name.

## [get_preset()](concepts/func:parrot.bots.prompts.presets.get_preset.md)

Get a preset by name. Returns a fresh builder each time.

## [list_presets()](concepts/func:parrot.bots.prompts.presets.list_presets.md)

List available preset names.

## [register_preset()](concepts/func:parrot.bots.prompts.presets.register_preset.md)

Register a named preset.

## [create_voice_bot()](concepts/func:parrot.bots.voice.create_voice_bot.md)

Factory to create a configured VoiceBot.

## [agent()](concepts/func:parrot.cli.agent_repl.agent.md)

Interactive REPL for AI-Parrot agents.

## [cli()](concepts/func:parrot.cli.cli.md)

Parrot command-line interface.

## [bot_declares_o365_device_code()](concepts/func:parrot.cli.identity.bot_declares_o365_device_code.md)

Return True when ``bot`` declares an ``o365``/``device_code`` credential.

## [build_cli_permission_context()](concepts/func:parrot.cli.identity.build_cli_permission_context.md)

Build the CLI ``PermissionContext`` for the O365 device-code broker seam.

## [resolve_cli_o365_principal()](concepts/func:parrot.cli.identity.resolve_cli_o365_principal.md)

Read and normalize the CLI's canonical O365 principal from the environment.

## [register_python_tool()](concepts/func:parrot.clients.base.register_python_tool.md)

Register Python REPL tool with a ClaudeAPIClient.

## [create_live_client()](concepts/func:parrot.clients.live.create_live_client.md)

Factory function to create a GeminiLiveClient.

## [get_global_registry()](concepts/func:parrot.core.events.lifecycle.global_registry.g-599164d8.md)

Return the process-wide singleton ``EventRegistry``.

## [scope()](concepts/func:parrot.core.events.lifecycle.global_registry.scope.md)

Replace the global registry with a fresh one for the block duration.

## [wire_events()](concepts/func:parrot.core.events.lifecycle.yaml_loader.wire_events.md)

Apply a parsed YAML ``events:`` block to the bot's event registry.

## [create_crew_whatsapp_hook()](concepts/func:parrot.core.hooks.models.create_crew_whatsapp_hook.md)

Create a WhatsApp hook that routes messages to an AgentCrew.

## [create_multi_agent_whatsapp_hook()](concepts/func:parrot.core.hooks.models.create_multi_agent_wh-d6b275b3.md)

Create a multi-agent WhatsApp hook with keyword/phone routing.

## [create_simple_whatsapp_hook()](concepts/func:parrot.core.hooks.models.create_simple_whatsapp_hook.md)

Create a simple WhatsApp hook that routes all messages to one agent.

## [get_embedding_models()](concepts/func:parrot.embeddings.catalog.get_embedding_models.md)

Return the curated list of embedding models, optionally filtered.

## [get_model_recommendations()](concepts/func:parrot.embeddings.catalog.get_model_recommendations.md)

Return per-model retrieval recommendations from the catalog.

## [get_use_cases()](concepts/func:parrot.embeddings.catalog.get_use_cases.md)

Return available use-case categories and their descriptions.

## [validate_against_catalog()](concepts/func:parrot.embeddings.matryoshka.validate_against_catalog.md)

Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.

## [resolve_image()](concepts/func:parrot.embeddings.multimodal.base.resolve_image.md)

Resolve an ImageInput to a PIL.Image.Image.

## [l2_normalize()](concepts/func:parrot.embeddings.multimodal.quantization.l2_normalize.md)

L2-normalize each row vector to unit length.

## [matryoshka_slice()](concepts/func:parrot.embeddings.multimodal.quantization.matr-11afb8e9.md)

Slice the leading ``dim`` dimensions from each embedding vector.

## [postprocess()](concepts/func:parrot.embeddings.multimodal.quantization.postprocess.md)

Apply the full post-processing pipeline: slice -> normalize -> quantize.

## [quantize()](concepts/func:parrot.embeddings.multimodal.quantization.quantize.md)

Apply the specified quantization to an embedding array.

## [get_evaluator()](concepts/func:parrot.eval.registry.get_evaluator.md)

Return the evaluator class registered under *name*.

## [get_metric()](concepts/func:parrot.eval.registry.get_metric.md)

Return the metric class registered under *name*.

## [list_evaluators()](concepts/func:parrot.eval.registry.list_evaluators.md)

Return a sorted list of all registered evaluator names.

## [list_metrics()](concepts/func:parrot.eval.registry.list_metrics.md)

Return a sorted list of all registered metric names.

## [register_evaluator()](concepts/func:parrot.eval.registry.register_evaluator.md)

Class decorator that registers an evaluator under *name*.

## [register_metric()](concepts/func:parrot.eval.registry.register_metric.md)

Class decorator that registers a metric under *name*.

## [load_subagent_definition()](concepts/func:parrot.flows.dev_loop._subagent_defs.load_suba-47f803b8.md)

Return the system-prompt body of an SDD subagent.

## [parse_repo_specs()](concepts/func:parrot.flows.dev_loop.config.parse_repo_specs.md)

Parse ``DEV_LOOP_REPOS`` entries into :class:`RepoSpec` objects.

## [build_dev_loop_definition()](concepts/func:parrot.flows.dev_loop.definition.build_dev_loo-f9c66e86.md)

Return the declarative dev-loop :class:`FlowDefinition`.

## [build_dev_loop_node_factories()](concepts/func:parrot.flows.dev_loop.factories.build_dev_loop-6789c0cf.md)

Return the ``{dev_loop.* type: factory}`` map binding live deps.

## [build_dev_loop_flow()](concepts/func:parrot.flows.dev_loop.flow.build_dev_loop_flow.md)

Build the eight-node dev-loop ``AgentsFlow`` (FEAT-132).

## [register_dev_loop_node()](concepts/func:parrot.flows.dev_loop.nodes.base.register_dev_loop_node.md)

Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).

## [scrub_git_output()](concepts/func:parrot.flows.dev_loop.nodes.base.scrub_git_output.md)

Redact credentials from raw git CLI output before surfacing it.

## [transition_issue_with_candidates()](concepts/func:parrot.flows.dev_loop.nodes.base.transition_is-b5b225d0.md)

Apply the first candidate Jira transition that the workflow exposes.

## [build_dev_loop_revision_flow()](concepts/func:parrot.flows.dev_loop.runner.build_dev_loop_re-499e3bd3.md)

Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).

## [flow_stream_ws()](concepts/func:parrot.flows.dev_loop.streaming.flow_stream_ws.md)

aiohttp WebSocket handler bound to ``GET /api/flow/{run_id}/ws``.

## [cleanup_worktree()](concepts/func:parrot.flows.dev_loop.webhook.cleanup_worktree.md)

Run ``git worktree remove`` then ``git worktree prune``.

## [register_pull_request_webhook()](concepts/func:parrot.flows.dev_loop.webhook.register_pull_re-8c06f5c3.md)

Register the GitHub ``pull_request.closed`` webhook handler.

## [sweep_finished_worktrees()](concepts/func:parrot.flows.dev_loop.webhook.sweep_finished_worktrees.md)

Remove dev-loop worktrees whose PR is merged/closed. Best effort.

## [auth_by_attribute()](concepts/func:parrot.handlers.agents.abstract.auth_by_attribute.md)

Ensure the request is authenticated *and* the user belongs

## [auth_groups()](concepts/func:parrot.handlers.agents.abstract.auth_groups.md)

Ensure the request is authenticated *and* the user belongs

## [build_auto_approve_manager()](concepts/func:parrot.handlers.agents.factory.build_auto_appr-7e61027c.md)

Construct a manager whose only channel auto-approves every gate.

## [avatar_upstream_error_response()](concepts/func:parrot.handlers.avatar.avatar_upstream_error_response.md)

Translate a LiveAvatar upstream error into a clean JSON response.

## [close_all_avatar_sessions()](concepts/func:parrot.handlers.avatar.close_all_avatar_sessions.md)

Best-effort teardown of any lingering avatar sessions on shutdown.

## [register_avatar_routes()](concepts/func:parrot.handlers.avatar.register_avatar_routes.md)

Register avatar session endpoints on the provided aiohttp router.

## [close_all_fullmode_sessions()](concepts/func:parrot.handlers.avatar_fullmode.close_all_full-ee94e410.md)

Best-effort teardown of any lingering FULL mode sessions on shutdown.

## [register_fullmode_routes()](concepts/func:parrot.handlers.avatar_fullmode.register_fullm-ebe25ff3.md)

Register FULL mode avatar endpoints on the provided aiohttp router.

## [setup_credentials_routes()](concepts/func:parrot.handlers.credentials.setup_credentials_routes.md)

Register credential management routes on the aiohttp application.

## [test_crew_redis()](concepts/func:parrot.handlers.crew.redis_persistence.test_crew_redis.md)

Test the CrewRedis persistence layer.

## [build_csp_headers()](concepts/func:parrot.handlers.csp.build_csp_headers.md)

Build the full CSP + security header set.

## [frame_ancestors_from_env()](concepts/func:parrot.handlers.csp.frame_ancestors_from_env.md)

Read ``INFOGRAPHIC_FRAME_ANCESTORS`` and normalise to space-separated.

## [build_structured_message()](concepts/func:parrot.handlers.deeplink.build_structured_message.md)

Serialize a resumed action into a structured user-message query string.

## [setup_deeplink_routes()](concepts/func:parrot.handlers.deeplink.setup_deeplink_routes.md)

Register the web resume routes on ``app`` and return the handler.

## [configure_job_manager()](concepts/func:parrot.handlers.jobs.worker.configure_job_manager.md)

Configure and register a JobManager on the aiohttp Application.

## [configure_liveavatar_output_subscriber()](concepts/func:parrot.handlers.liveavatar_output.configure_li-59ff7390.md)

Register the LiveAvatar output subscriber on the aiohttp application.

## [setup_mcp_helper_routes()](concepts/func:parrot.handlers.mcp_helper.setup_mcp_helper_routes.md)

Register MCP helper management routes on the aiohttp application.

## [seal()](concepts/func:parrot.handlers.models._encrypted_field.seal.md)

Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.

## [unseal()](concepts/func:parrot.handlers.models._encrypted_field.unseal.md)

Decrypt a base64 ciphertext string and verify its bound context.

## [create_bot()](concepts/func:parrot.handlers.models.bots.create_bot.md)

Create a BasicBot instance from a BotModel database record.

## [media_type_from_filename()](concepts/func:parrot.handlers.models.understanding.media_typ-6f2cda6b.md)

Return 'image' or 'video' based on the file extension of *filename*.

## [setup_scraping_routes()](concepts/func:parrot.handlers.scraping.setup_scraping_routes.md)

Register all scraping handler routes on the aiohttp application.

## [get_current_web_session()](concepts/func:parrot.handlers.web_hitl.get_current_web_session.md)

Return the active web session ID for the current request context.

## [reset_current_web_session()](concepts/func:parrot.handlers.web_hitl.reset_current_web_session.md)

Reset the web session ContextVar to its previous value.

## [set_current_web_session()](concepts/func:parrot.handlers.web_hitl.set_current_web_session.md)

Set the active web session ID for the current request context.

## [setup_web_hitl()](concepts/func:parrot.handlers.web_hitl.setup_web_hitl.md)

Bootstrap a process-wide HumanInteractionManager with a WebHumanChannel.

## [get_template()](concepts/func:parrot.helpers.infographics.get_template.md)

Retrieve a template by name.

## [get_theme()](concepts/func:parrot.helpers.infographics.get_theme.md)

Retrieve a theme by name.

## [list_templates()](concepts/func:parrot.helpers.infographics.list_templates.md)

List available infographic template names.

## [list_themes()](concepts/func:parrot.helpers.infographics.list_themes.md)

List available infographic theme names.

## [register_template()](concepts/func:parrot.helpers.infographics.register_template.md)

Register a custom infographic template.

## [register_theme()](concepts/func:parrot.helpers.infographics.register_theme.md)

Register a custom infographic theme.

## [escalate_option()](concepts/func:parrot.human.channels.base.escalate_option.md)

Return the standardised "↑ Escalar" choice option.

## [setup_teams_hitl()](concepts/func:parrot.human.channels.teams.setup_teams_hitl.md)

Wire the shared HITL bot in one call.

## [main()](concepts/func:parrot.human.cli_companion.main.md)

CLI entry point.

## [get_default_human_manager()](concepts/func:parrot.human.get_default_human_manager.md)

Return the process-wide default HumanInteractionManager, if any.

## [set_default_human_manager()](concepts/func:parrot.human.set_default_human_manager.md)

Register the process-wide default HumanInteractionManager.

## [cloudsploit()](concepts/func:parrot.install.cli.cloudsploit.md)

Install CloudSploit by cloning its repo, patching, and building a Docker image.

## [install()](concepts/func:parrot.install.cli.install.md)

Install external tools and services (e.g., CloudSploit, Prowler).

## [prowler()](concepts/func:parrot.install.cli.prowler.md)

Install Prowler by pulling its latest Docker image.

## [pulumi()](concepts/func:parrot.install.cli.pulumi.md)

Install Pulumi CLI and optionally the Docker provider.

## [scoutsuite()](concepts/func:parrot.install.cli.scoutsuite.md)

Install ScoutSuite by running uv pip install.

## [conf()](concepts/func:parrot.install.conf.conf.md)

Configuration management commands.

## [init()](concepts/func:parrot.install.conf.init.md)

Initialize configuration structure (env/ and etc/).

## [build_structured_message()](concepts/func:parrot.integrations.a2ui_resume.build_structur-1318e87a.md)

Serialize a resumed action into a structured user-message query string.

## [get_provider()](concepts/func:parrot.integrations.core.auth.oauth2_providers-360975c4.md)

Look up an OAuth2 provider by name.

## [is_avatar_enabled()](concepts/func:parrot.integrations.liveavatar.optin.is_avatar_enabled.md)

Return ``True`` iff avatar mode is enabled for the given tenant + agent.

## [is_fullmode_enabled()](concepts/func:parrot.integrations.liveavatar.optin.is_fullmo-4fa44bc3.md)

Return ``True`` iff FULL mode avatar is enabled for the given tenant + agent.

## [run_output_subscriber()](concepts/func:parrot.integrations.liveavatar.output_transpor-6f094277.md)

Consume output envelopes from Redis and re-broadcast them (server side).

## [resolve_fullmode_config()](concepts/func:parrot.integrations.liveavatar.tenant_config.r-d3ee891d.md)

Resolve a :class:`FullModeConfig` from env defaults (+ future DB overrides).

## [handle_a2a_directory()](concepts/func:parrot.integrations.manager.handle_a2a_directory.md)

GET /a2a/directory — returns JSON array of all registered AgentCards.

## [build_pill()](concepts/func:parrot.integrations.matrix.crew.mention.build_pill.md)

Build a Matrix "pill" HTML mention link.

## [build_reply_content()](concepts/func:parrot.integrations.matrix.crew.mention.build_-3029f6d0.md)

Build the ``m.relates_to`` content dict for a reply-to message.

## [format_reply()](concepts/func:parrot.integrations.matrix.crew.mention.format_reply.md)

Format a reply with the agent's identity prepended.

## [parse_mention()](concepts/func:parrot.integrations.matrix.crew.mention.parse_mention.md)

Extract the agent localpart from a Matrix message body.

## [generate_registration()](concepts/func:parrot.integrations.matrix.registration.genera-c068430f.md)

Generate an AS registration YAML.

## [generate_tokens()](concepts/func:parrot.integrations.matrix.registration.generate_tokens.md)

Generate random AS and HS tokens.

## [patch_mcs_connector_empty_response()](concepts/func:parrot.integrations.msagentsdk._patches.patch_-151521a5.md)

Make the MCS connector tolerate an empty / non-JSON 200 response.

## [render_reply_text()](concepts/func:parrot.integrations.msagentsdk.agent.render_reply_text.md)

Produce human-readable reply text from an ``AIMessage``.

## [build_card_attachment()](concepts/func:parrot.integrations.msagentsdk.cards.build_car-0931716c.md)

Wrap card JSON in the Bot Framework attachment envelope.

## [render_card()](concepts/func:parrot.integrations.msagentsdk.cards.render_card.md)

Render a `SemanticUIResult` as Adaptive Card 1.4 JSON.

## [render_text()](concepts/func:parrot.integrations.msagentsdk.cards.render_text.md)

Render a `SemanticUIResult` as plain/markdown text.

## [proactive_resume()](concepts/func:parrot.integrations.msagentsdk.resume.proactive_resume.md)

Re-run the suspended ask() and proactively deliver the response.

## [connect_jira_handler()](concepts/func:parrot.integrations.msteams.commands.jira_comm-6b3ab6cc.md)

Handle ``/connect_jira`` text command.

## [disconnect_jira_handler()](concepts/func:parrot.integrations.msteams.commands.jira_comm-1c82cd74.md)

Handle ``/disconnect_jira`` text command.

## [jira_menu_handler()](concepts/func:parrot.integrations.msteams.commands.jira_comm-ac21cca9.md)

Show a discoverability menu with all Jira commands.

## [jira_status_handler()](concepts/func:parrot.integrations.msteams.commands.jira_comm-28555397.md)

Handle ``/jira_status`` text command.

## [register_jira_commands()](concepts/func:parrot.integrations.msteams.commands.jira_comm-ba99ddf4.md)

Register Jira commands on *router*.

## [get_registered_form()](concepts/func:parrot.integrations.msteams.dialogs.presets.ba-d1410ec2.md)

Get a form and style from the global registry.

## [register_form()](concepts/func:parrot.integrations.msteams.dialogs.presets.ba-ecddff05.md)

Register a form and optional style in the global registry for later lookup.

## [handle_msteams_jira_callback()](concepts/func:parrot.integrations.msteams.oauth_callback.han-543052d8.md)

Process a Jira OAuth callback originating from the MS Teams integration.

## [parse_response()](concepts/func:parrot.integrations.parser.parse_response.md)

Parse an AIMessage or similar response into structured content.

## [connect_jira_handler()](concepts/func:parrot.integrations.slack.commands.jira_comman-b9ec4689.md)

Handle ``/connect_jira`` slash command.

## [disconnect_jira_handler()](concepts/func:parrot.integrations.slack.commands.jira_comman-f2271efe.md)

Handle ``/disconnect_jira`` slash command.

## [jira_status_handler()](concepts/func:parrot.integrations.slack.commands.jira_comman-afbbc099.md)

Handle ``/jira_status`` slash command.

## [register_jira_commands()](concepts/func:parrot.integrations.slack.commands.jira_comman-ac98a72b.md)

Register the three Jira commands on *router*.

## [download_slack_file()](concepts/func:parrot.integrations.slack.files.download_slack_file.md)

Download a file from Slack using bot token authentication.

## [extract_files_from_event()](concepts/func:parrot.integrations.slack.files.extract_files_-f86686b4.md)

Extract file information from a Slack event.

## [get_file_extension()](concepts/func:parrot.integrations.slack.files.get_file_extension.md)

Get file extension from file info.

## [is_processable_file()](concepts/func:parrot.integrations.slack.files.is_processable_file.md)

Check if a file can be processed by AI-Parrot loaders.

## [upload_file_to_slack()](concepts/func:parrot.integrations.slack.files.upload_file_to_slack.md)

Upload file to Slack using v2 async upload flow.

## [build_clear_button()](concepts/func:parrot.integrations.slack.interactive.build_cl-ddd1ccdf.md)

Build a clear conversation button.

## [build_feedback_blocks()](concepts/func:parrot.integrations.slack.interactive.build_fe-bbdc2d6d.md)

Build feedback buttons to append to agent responses.

## [handle_slack_jira_callback()](concepts/func:parrot.integrations.slack.oauth_callback.handl-b0ba1188.md)

Process a Jira OAuth callback originating from the Slack integration.

## [verify_slack_signature_raw()](concepts/func:parrot.integrations.slack.security.verify_slac-035c397f.md)

Verify that an incoming request actually comes from Slack.

## [convert_markdown_to_mrkdwn()](concepts/func:parrot.integrations.slack.wrapper.convert_mark-da964e2c.md)

Convert standard Markdown to Slack mrkdwn format.

## [build_inline_keyboard()](concepts/func:parrot.integrations.telegram.callbacks.build_i-df3bc113.md)

Build an InlineKeyboardMarkup dict compatible with aiogram.

## [telegram_callback()](concepts/func:parrot.integrations.telegram.callbacks.telegra-39c3e339.md)

Decorator to register an agent method as a Telegram inline callback handler.

## [combined_auth_callback_handler()](concepts/func:parrot.integrations.telegram.combined_callback-32e94c45.md)

Handle the combined BasicAuth + secondary OAuth redirect.

## [setup_combined_auth_routes()](concepts/func:parrot.integrations.telegram.combined_callback-e2233ec2.md)

Register the combined callback route and exclude it from auth.

## [get_current_telegram_chat_id()](concepts/func:parrot.integrations.telegram.context.get_curre-139755a6.md)

Return the current Telegram chat id, or None if unset.

## [telegram_chat_scope()](concepts/func:parrot.integrations.telegram.context.telegram_-2ed7e80b.md)

Set the current Telegram chat id for the duration of the block.

## [format_reply()](concepts/func:parrot.integrations.telegram.crew.mention.format_reply.md)

Format a response by prepending a mention to the text.

## [mention_from_card()](concepts/func:parrot.integrations.telegram.crew.mention.ment-147602b7.md)

Build an @mention string from an AgentCard.

## [mention_from_user_id()](concepts/func:parrot.integrations.telegram.crew.mention.ment-02e75ebf.md)

Build a Telegram HTML deep-link mention from a user ID.

## [mention_from_username()](concepts/func:parrot.integrations.telegram.crew.mention.ment-bc9ff7b4.md)

Build an @mention string from a Telegram username.

## [discover_telegram_commands()](concepts/func:parrot.integrations.telegram.decorators.discov-fcc1a32e.md)

Scan an agent instance for methods decorated with @telegram_command.

## [telegram_command()](concepts/func:parrot.integrations.telegram.decorators.telegr-aa9b8b77.md)

Mark an agent method as a Telegram slash command.

## [connect_jira_handler()](concepts/func:parrot.integrations.telegram.jira_commands.con-a586a78c.md)

Handle ``/connect_jira`` — send the authorization URL or a status.

## [disconnect_jira_handler()](concepts/func:parrot.integrations.telegram.jira_commands.dis-a38bea92.md)

Handle ``/disconnect_jira`` — revoke stored tokens and clear session.

## [jira_status_handler()](concepts/func:parrot.integrations.telegram.jira_commands.jir-c64eddce.md)

Handle ``/jira_status`` — report the user's Jira connection state.

## [register_jira_commands()](concepts/func:parrot.integrations.telegram.jira_commands.reg-9e914c95.md)

Register the three Jira commands on *router*.

## [add_mcp_handler()](concepts/func:parrot.integrations.telegram.mcp_commands.add_-482b788b.md)

Handle ``/add_mcp <json>``.

## [list_mcp_handler()](concepts/func:parrot.integrations.telegram.mcp_commands.list-5fdda854.md)

Handle ``/list_mcp`` — show the user's saved servers (no secrets).

## [register_mcp_commands()](concepts/func:parrot.integrations.telegram.mcp_commands.regi-493a972a.md)

Wire the three MCP commands on *router*.

## [rehydrate_user_mcp_servers()](concepts/func:parrot.integrations.telegram.mcp_commands.rehy-300b40be.md)

Re-attach every persisted MCP server to ``tool_manager``.

## [remove_mcp_handler()](concepts/func:parrot.integrations.telegram.mcp_commands.remo-5aab2043.md)

Handle ``/remove_mcp <name>``.

## [oauth2_callback_handler()](concepts/func:parrot.integrations.telegram.oauth2_callback.o-2a3e6411.md)

Handle OAuth2 provider redirect with authorization code.

## [setup_oauth2_routes()](concepts/func:parrot.integrations.telegram.oauth2_callback.s-0085ed9d.md)

Register OAuth2 callback route on the aiohttp application.

## [connect_office365_handler()](concepts/func:parrot.integrations.telegram.office365_command-4913a2d2.md)

Handle ``/connect_office365`` from Telegram chat.

## [disconnect_office365_handler()](concepts/func:parrot.integrations.telegram.office365_command-54eb163b.md)

Handle ``/disconnect_office365`` from Telegram chat.

## [office365_status_handler()](concepts/func:parrot.integrations.telegram.office365_command-f920af92.md)

Handle ``/office365_status`` from Telegram chat.

## [register_office365_commands()](concepts/func:parrot.integrations.telegram.office365_command-33825a47.md)

Register Office365 command handlers on the router.

## [extract_query_from_mention()](concepts/func:parrot.integrations.telegram.utils.extract_que-ecfa0852.md)

Extract the actual query from a mention or command message.

## [get_user_display_name()](concepts/func:parrot.integrations.telegram.utils.get_user_di-24d97c68.md)

Get a display name for the message sender.

## [parse_kwargs()](concepts/func:parrot.integrations.utils.parse_kwargs.md)

Parse 'key=val key2="quoted val"' into a kwargs dict.

## [convert_markdown_to_whatsapp()](concepts/func:parrot.integrations.whatsapp.utils.convert_mar-e5ab9ad2.md)

Convert standard Markdown to WhatsApp-compatible formatting.

## [sanitize_phone_number()](concepts/func:parrot.integrations.whatsapp.utils.sanitize_ph-e12c81d8.md)

Normalize a phone number by stripping non-digit characters.

## [split_message()](concepts/func:parrot.integrations.whatsapp.utils.split_message.md)

Split a long message into chunks that fit WhatsApp's message size limit.

## [get_default_credentials()](concepts/func:parrot.interfaces.database.get_default_credentials.md)

Return default credentials for a database driver from environment variables.

## [create_google_client()](concepts/func:parrot.interfaces.google.create_google_client.md)

Factory function to create a GoogleClient.

## [bad_gateway_exception()](concepts/func:parrot.interfaces.http.bad_gateway_exception.md)

Check if the exception is a 502 Bad Gateway error.

## [compute_analytics()](concepts/func:parrot.knowledge.graphindex.analytics.compute_analytics.md)

Compute centrality metrics and rank cross-domain connections.

## [dismiss_insight()](concepts/func:parrot.knowledge.graphindex.analytics.dismiss_insight.md)

Mark an insight as dismissed.

## [find_bridge_nodes()](concepts/func:parrot.knowledge.graphindex.analytics.find_bridge_nodes.md)

Find nodes that bridge multiple distinct communities.

## [find_isolated_nodes()](concepts/func:parrot.knowledge.graphindex.analytics.find_iso-e32e9c22.md)

Find nodes with few connections (potential knowledge gaps).

## [find_sparse_communities()](concepts/func:parrot.knowledge.graphindex.analytics.find_spa-8db9a7b7.md)

Find communities with low internal cohesion (sparse communities).

## [generate_report()](concepts/func:parrot.knowledge.graphindex.analytics.generate_report.md)

Generate ``GRAPH_REPORT.md`` from analytics results.

## [list_unreviewed_insights()](concepts/func:parrot.knowledge.graphindex.analytics.list_unr-767e9a85.md)

Return all insights not yet dismissed.

## [build_code_graph()](concepts/func:parrot.knowledge.graphindex.cli.build_code_graph.md)

Build the code knowledge graph and write the ``graphindex`` artefacts.

## [discover_python_files()](concepts/func:parrot.knowledge.graphindex.cli.discover_python_files.md)

Recursively find Python source files under ``root``.

## [main()](concepts/func:parrot.knowledge.graphindex.cli.main.md)

CLI entry point.

## [cohesion_for_community()](concepts/func:parrot.knowledge.graphindex.communities.cohesi-30817835.md)

internal_edges / (internal_edges + boundary_edges).

## [derive_community_label()](concepts/func:parrot.knowledge.graphindex.communities.derive-e3d20515.md)

Derive a deterministic, LLM-free label from member titles.

## [detect_communities()](concepts/func:parrot.knowledge.graphindex.communities.detect-0070fb50.md)

Run Louvain community detection on the assembled graph.

## [build_export_payload()](concepts/func:parrot.knowledge.graphindex.export_html.build_-277c2d17.md)

Build a :class:`GraphExportPayload` from an assembled graph.

## [community_color()](concepts/func:parrot.knowledge.graphindex.export_html.community_color.md)

Return the deterministic colour for a community display index.

## [export_graph()](concepts/func:parrot.knowledge.graphindex.export_html.export_graph.md)

Build the payload and write both ``graph.json`` and ``graph.html``.

## [write_graph_html()](concepts/func:parrot.knowledge.graphindex.export_html.write_-39b64987.md)

Write a self-contained ``graph.html`` to ``output_dir``.

## [write_graph_json()](concepts/func:parrot.knowledge.graphindex.export_html.write_-411adf64.md)

Write ``graph.json`` to ``output_dir``.

## [build_graphindex_ontology()](concepts/func:parrot.knowledge.graphindex.meta_ontology.buil-bbe8f7bc.md)

Return the universal GraphIndex meta-ontology as a ``MergedOntology``.

## [node_to_frontmatter_dict()](concepts/func:parrot.knowledge.graphindex.projection.node_to-f2f9402f.md)

Convert a UniversalNode + its outgoing edges into a project_frontmatter() dict.

## [project_graph_sidecars()](concepts/func:parrot.knowledge.graphindex.projection.project-954a3441.md)

Write per-node ``.md`` sidecars to ``output_dir/nodes/``.

## [project_node_sidecar()](concepts/func:parrot.knowledge.graphindex.projection.project-dc9dbea7.md)

Return the complete sidecar text: YAML frontmatter + body.

## [project_report_frontmatter()](concepts/func:parrot.knowledge.graphindex.projection.project-e309c8bf.md)

Generate OKF YAML frontmatter string for GRAPH_REPORT.md.

## [resolve_cross_domain()](concepts/func:parrot.knowledge.graphindex.resolve.resolve_cr-a5f0ccca.md)

Discover implicit cross-domain edges via embedding similarity.

## [compute_pairwise_signals()](concepts/func:parrot.knowledge.graphindex.signals.compute_pa-7898ecd8.md)

Raw five signals without combination. Cheap building block.

## [relevance_neighborhood()](concepts/func:parrot.knowledge.graphindex.signals.relevance_-f294b5ee.md)

Top-K nodes most relevant to ``node_id`` by combined score.

## [signal_relevance()](concepts/func:parrot.knowledge.graphindex.signals.signal_relevance.md)

Pairwise five-signal relevance over an assembled GraphIndex.

## [parse_frontmatter()](concepts/func:parrot.knowledge.okf.frontmatter.parse_frontmatter.md)

Parse YAML frontmatter from a sidecar string back into a model.

## [project_frontmatter()](concepts/func:parrot.knowledge.okf.frontmatter.project_frontmatter.md)

Produce a byte-deterministic YAML frontmatter string from a node dict.

## [build_uri()](concepts/func:parrot.knowledge.okf.uri.build_uri.md)

Build a ``knowledge://`` URI for cross-index addressing.

## [parse_uri()](concepts/func:parrot.knowledge.okf.uri.parse_uri.md)

Parse a ``knowledge://`` or legacy ``pageindex://`` URI.

## [flatten_concept_id_for_filename()](concepts/func:parrot.knowledge.okf.utils.flatten_concept_id_-eee855e4.md)

Convert a slash-containing concept_id to a flat filename stem.

## [approve_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-2315c0aa.md)

POST /api/ontology/concepts/{id}/transitions/approve — reviewer+ only.

## [deprecate_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-273f64d7.md)

POST /api/ontology/concepts/{id}/transitions/deprecate — admin only.

## [get_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-d18ed8e0.md)

GET /api/ontology/concepts/{id}

## [get_concept_history()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-d05bfecf.md)

GET /api/ontology/concepts/{id}/history

## [get_concept_isa()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-d858e3d9.md)

GET /api/ontology/concepts/{id}/isa — is_a subgraph.

## [isa_edge_transition()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-db520b3d.md)

POST /api/ontology/concepts/isa/{id}/transitions/{action}

## [list_concepts()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-084dad6e.md)

GET /api/ontology/concepts — list concepts for a tenant.

## [modify_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-a4cd8ea4.md)

PATCH /api/ontology/concepts/{id} — reviewer+ only.

## [propose_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-80da4b8f.md)

POST /api/ontology/concepts — propose a new concept.

## [propose_isa_edge()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-a090dcb3.md)

POST /api/ontology/concepts/isa — propose is_a edge.

## [register_routes()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-7ecaafa0.md)

Register all concept catalog routes on *app*.

## [reject_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-dba56f47.md)

POST /api/ontology/concepts/{id}/transitions/reject — reviewer+ only.

## [restore_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-ae637a78.md)

POST /api/ontology/concepts/{id}/transitions/restore — admin only.

## [submit_concept()](concepts/func:parrot.knowledge.ontology.concept_catalog.http-dc285801.md)

POST /api/ontology/concepts/{id}/transitions/submit

## [seed_concepts_from_yaml()](concepts/func:parrot.knowledge.ontology.concept_catalog.seed-cb901919.md)

Seed concept rows from a YAML ontology file.

## [dry_run_overlay_endpoint()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-61ce2ccc.md)

GET /api/ontology/schema/{id}/dry-run — run validation without approving.

## [get_overlay()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-981d1d74.md)

GET /api/ontology/schema/{id}

## [list_overlays()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-9397e59e.md)

GET /api/ontology/schema — list pending overlays for tenant.

## [overlay_transition()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-4557e97f.md)

POST /api/ontology/schema/{id}/transitions/{action}

## [propose_overlay()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-afc99662.md)

POST /api/ontology/schema — propose a new schema overlay.

## [register_routes()](concepts/func:parrot.knowledge.ontology.schema_overlay.http.-27fb3a72.md)

Register all schema overlay routes on *app*.

## [dry_run_overlay()](concepts/func:parrot.knowledge.ontology.schema_overlay.valid-1e832a89.md)

Sandboxed validation of a schema overlay candidate.

## [jira_accounts()](concepts/func:parrot.knowledge.ontology.tool_dispatcher.jira_accounts.md)

Render a comma-separated list of Jira accountIds for a JQL clause.

## [join_ids()](concepts/func:parrot.knowledge.ontology.tool_dispatcher.join_ids.md)

Join the values of a given key across a list of dicts.

## [jql_quote()](concepts/func:parrot.knowledge.ontology.tool_dispatcher.jql_quote.md)

Escape a value for safe inclusion as a JQL string literal.

## [map_attr()](concepts/func:parrot.knowledge.ontology.tool_dispatcher.map_attr.md)

Extract a single attribute from each dict in a list.

## [validate_aql()](concepts/func:parrot.knowledge.ontology.validators.validate_aql.md)

Validate LLM-generated AQL for safety.

## [extract_json()](concepts/func:parrot.knowledge.pageindex.llm_adapter.extract_json.md)

Extract JSON from LLM text that may contain ```json fences.

## [export_okf_bundle()](concepts/func:parrot.knowledge.pageindex.okf.bundle.export_okf_bundle.md)

Export a PageIndex tree as an OKF v0.1 compliant directory bundle.

## [import_okf_bundle()](concepts/func:parrot.knowledge.pageindex.okf.bundle.import_okf_bundle.md)

Import an OKF bundle directory into a new PageIndex tree.

## [assign_concept_ids()](concepts/func:parrot.knowledge.pageindex.okf.concept_id.assi-901d5ef1.md)

Walk the tree depth-first and write deterministic ``concept_id`` values.

## [dedup_concept_ids()](concepts/func:parrot.knowledge.pageindex.okf.concept_id.dedu-58e844ac.md)

Resolve slug collisions with stable numeric suffixes.

## [derive_concept_id()](concepts/func:parrot.knowledge.pageindex.okf.concept_id.deri-7a2540c5.md)

Derive a deterministic concept_id slug from a title.

## [build_graph()](concepts/func:parrot.knowledge.pageindex.okf.graph.build_graph.md)

Build a full knowledge graph including prose link edges.

## [parse_markdown_links()](concepts/func:parrot.knowledge.pageindex.okf.graph.parse_mar-0bebe7d0.md)

Extract markdown hyperlink targets from body text.

## [lint_knowledge_base()](concepts/func:parrot.knowledge.pageindex.okf.lint.lint_knowledge_base.md)

Run lint checks on a knowledge base and return a structured report.

## [okf_migrate()](concepts/func:parrot.knowledge.pageindex.okf.migrate.okf_migrate.md)

Retrofit an existing PageIndex tree with OKF fields.

## [generate_index_md()](concepts/func:parrot.knowledge.pageindex.okf.projection.gene-a2f3cdbc.md)

Generate a deterministic root-level index.md view of the JSON ToC.

## [project_sidecar()](concepts/func:parrot.knowledge.pageindex.okf.projection.proj-e4400459.md)

Combine projected frontmatter and existing body into a sidecar string.

## [project_sidecars()](concepts/func:parrot.knowledge.pageindex.okf.projection.proj-64ff1db8.md)

Regenerate all sidecars from the authoritative JSON tree.

## [build_node_markdown_map()](concepts/func:parrot.knowledge.pageindex.pdf_to_markdown.bui-0191fd92.md)

Walk a node tree and return ``{node_id: concatenated_markdown}``.

## [extract_markdown_per_page()](concepts/func:parrot.knowledge.pageindex.pdf_to_markdown.ext-14f65584.md)

Extract per-physical-page markdown from a PDF.

## [delete_node()](concepts/func:parrot.knowledge.pageindex.tree_ops.delete_node.md)

Remove the node with ``node_id`` and all its descendants.

## [make_folder_node()](concepts/func:parrot.knowledge.pageindex.tree_ops.make_folder_node.md)

Build a synthetic inner node representing a directory.

## [reindex_node_ids()](concepts/func:parrot.knowledge.pageindex.tree_ops.reindex_node_ids.md)

Reassign sequential 4-digit ``node_id`` values across the tree.

## [splice_subtree()](concepts/func:parrot.knowledge.pageindex.tree_ops.splice_subtree.md)

Insert ``subtree`` under ``parent_node_id`` (or at root if None).

## [add_node_text()](concepts/func:parrot.knowledge.pageindex.utils.add_node_text.md)

Add page text to tree nodes based on start/end indices.

## [add_node_text_with_labels()](concepts/func:parrot.knowledge.pageindex.utils.add_node_text-6613a3ce.md)

Add page text with physical_index tags to tree nodes.

## [add_page_offset_to_toc_json()](concepts/func:parrot.knowledge.pageindex.utils.add_page_offs-0d8d9058.md)

Apply page offset to convert page numbers to physical indices.

## [add_preface_if_needed()](concepts/func:parrot.knowledge.pageindex.utils.add_preface_if_needed.md)

Add a preface node if the document starts after page 1.

## [calculate_page_offset()](concepts/func:parrot.knowledge.pageindex.utils.calculate_page_offset.md)

Calculate the most common difference between physical and page indices.

## [clean_structure_post()](concepts/func:parrot.knowledge.pageindex.utils.clean_structure_post.md)

Remove page_number, start_index, end_index from structure.

## [convert_page_to_int()](concepts/func:parrot.knowledge.pageindex.utils.convert_page_to_int.md)

Convert page string values to integers.

## [convert_physical_index_to_int()](concepts/func:parrot.knowledge.pageindex.utils.convert_physi-dc179054.md)

Convert '<physical_index_X>' strings to integers.

## [count_tokens()](concepts/func:parrot.knowledge.pageindex.utils.count_tokens.md)

Count tokens using tiktoken (approximation for non-OpenAI models).

## [create_clean_structure_for_description()](concepts/func:parrot.knowledge.pageindex.utils.create_clean_-2a301de5.md)

Create a clean structure without text for description generation.

## [extract_json()](concepts/func:parrot.knowledge.pageindex.utils.extract_json.md)

Extract JSON from LLM response text.

## [extract_matching_page_pairs()](concepts/func:parrot.knowledge.pageindex.utils.extract_match-217f3382.md)

Find matching title pairs between TOC pages and physical indices.

## [find_node_by_id()](concepts/func:parrot.knowledge.pageindex.utils.find_node_by_id.md)

Find a node by its node_id in the tree.

## [format_structure()](concepts/func:parrot.knowledge.pageindex.utils.format_structure.md)

Recursively format tree nodes with ordered keys.

## [get_first_start_page_from_text()](concepts/func:parrot.knowledge.pageindex.utils.get_first_sta-0249325e.md)

Extract first start_index page number from tagged text.

## [get_json_content()](concepts/func:parrot.knowledge.pageindex.utils.get_json_content.md)

Strip ```json fences from a string.

## [get_last_start_page_from_text()](concepts/func:parrot.knowledge.pageindex.utils.get_last_star-6bbde09b.md)

Extract last start_index page number from tagged text.

## [get_leaf_nodes()](concepts/func:parrot.knowledge.pageindex.utils.get_leaf_nodes.md)

Get all leaf nodes (nodes without children).

## [get_nodes()](concepts/func:parrot.knowledge.pageindex.utils.get_nodes.md)

Flatten a tree into a list of nodes (without children).

## [get_number_of_pages()](concepts/func:parrot.knowledge.pageindex.utils.get_number_of_pages.md)

Get the number of pages in a PDF.

## [get_page_tokens()](concepts/func:parrot.knowledge.pageindex.utils.get_page_tokens.md)

Extract page text and token counts from a PDF.

## [get_pdf_name()](concepts/func:parrot.knowledge.pageindex.utils.get_pdf_name.md)

Extract a human-readable name from a PDF path or stream.

## [get_pdf_title()](concepts/func:parrot.knowledge.pageindex.utils.get_pdf_title.md)

Get the title from PDF metadata.

## [get_text_of_pages()](concepts/func:parrot.knowledge.pageindex.utils.get_text_of_pages.md)

Get text from specific pages of a PDF.

## [get_text_of_pdf_pages()](concepts/func:parrot.knowledge.pageindex.utils.get_text_of_pdf_pages.md)

Get concatenated text from a page list (1-indexed).

## [get_text_of_pdf_pages_with_labels()](concepts/func:parrot.knowledge.pageindex.utils.get_text_of_p-f4d8d148.md)

Get concatenated text with physical_index tags.

## [is_leaf_node()](concepts/func:parrot.knowledge.pageindex.utils.is_leaf_node.md)

Check if a node with given node_id is a leaf.

## [list_to_tree()](concepts/func:parrot.knowledge.pageindex.utils.list_to_tree.md)

Convert a flat TOC list into a hierarchical tree.

## [page_list_to_group_text()](concepts/func:parrot.knowledge.pageindex.utils.page_list_to_-7a5f408e.md)

Split page contents into groups respecting token limits.

## [post_processing()](concepts/func:parrot.knowledge.pageindex.utils.post_processing.md)

Convert flat TOC list to tree with start/end indices.

## [print_toc()](concepts/func:parrot.knowledge.pageindex.utils.print_toc.md)

Print a tree structure as indented text.

## [remove_fields()](concepts/func:parrot.knowledge.pageindex.utils.remove_fields.md)

Remove specified fields from a nested structure.

## [remove_first_physical_index_section()](concepts/func:parrot.knowledge.pageindex.utils.remove_first_-48d10c4b.md)

Remove first physical_index tagged section from text.

## [remove_page_number()](concepts/func:parrot.knowledge.pageindex.utils.remove_page_number.md)

Remove page_number field from all nodes.

## [remove_structure_text()](concepts/func:parrot.knowledge.pageindex.utils.remove_structure_text.md)

Remove 'text' field from all nodes in the tree.

## [reorder_dict()](concepts/func:parrot.knowledge.pageindex.utils.reorder_dict.md)

Reorder dictionary keys.

## [sanitize_filename()](concepts/func:parrot.knowledge.pageindex.utils.sanitize_filename.md)

Replace filesystem-unsafe characters.

## [structure_to_list()](concepts/func:parrot.knowledge.pageindex.utils.structure_to_list.md)

Flatten a tree into a list preserving parent nodes.

## [validate_and_truncate_physical_indices()](concepts/func:parrot.knowledge.pageindex.utils.validate_and_-8e3eb17f.md)

Remove physical indices exceeding actual document length.

## [write_node_id()](concepts/func:parrot.knowledge.pageindex.utils.write_node_id.md)

Assign sequential node_id values to a tree structure.

## [embedding_tree_walk()](concepts/func:parrot.knowledge.pageindex.vector_walk.embeddi-9e97fad0.md)

Beam search over per-node embeddings to propose candidate node_ids.

## [first_sentence()](concepts/func:parrot.knowledge.wiki.context.first_sentence.md)

Return the lead sentence of ``text``, hard-capped at ``max_chars``.

## [pack_results()](concepts/func:parrot.knowledge.wiki.context.pack_results.md)

Pack search results into a token-budgeted context block.

## [stub_line()](concepts/func:parrot.knowledge.wiki.context.stub_line.md)

Render one search result as a compact single-line stub.

## [truncate_to_tokens()](concepts/func:parrot.knowledge.wiki.context.truncate_to_tokens.md)

Deterministically truncate ``text`` to approximately ``max_tokens``.

## [category_dir()](concepts/func:parrot.knowledge.wiki.export.category_dir.md)

Directory name for a category (naive English plural, lowercase).

## [export_okf_bundle()](concepts/func:parrot.knowledge.wiki.export.export_okf_bundle.md)

Project a wiki store into an OKF v0.1 markdown bundle.

## [generate_index()](concepts/func:parrot.knowledge.wiki.export.generate_index.md)

Render the root ``index.md`` (title, relative path, summary).

## [okf_type()](concepts/func:parrot.knowledge.wiki.export.okf_type.md)

Map a wiki category to an OKF ``type`` string.

## [page_frontmatter()](concepts/func:parrot.knowledge.wiki.export.page_frontmatter.md)

Render OKF frontmatter for one page (deterministic key order).

## [create_wiki_store()](concepts/func:parrot.knowledge.wiki.store.create_wiki_store.md)

Instantiate the configured wiki retrieval-plane backend.

## [estimate_tokens()](concepts/func:parrot.knowledge.wiki.store.estimate_tokens.md)

Cheap deterministic token estimate for budget accounting.

## [rank_by_cosine()](concepts/func:parrot.knowledge.wiki.store.rank_by_cosine.md)

Rank candidate stubs by cosine similarity to a query vector.

## [mcp()](concepts/func:parrot.mcp.cli.mcp.md)

MCP server commands.

## [serve()](concepts/func:parrot.mcp.cli.serve.md)

Start an MCP server from a Python config file or YAML.

## [parse_retry_after()](concepts/func:parrot.mcp.client.parse_retry_after.md)

Normalize a server-provided retry hint into seconds-from-now.

## [raise_for_jsonrpc_error()](concepts/func:parrot.mcp.client.raise_for_jsonrpc_error.md)

Translate a JSON-RPC ``error`` object into the right exception.

## [retry_on_errors()](concepts/func:parrot.mcp.context.retry_on_errors.md)

Decorator for automatic retry on transient errors with exponential backoff.

## [allow_all_tools()](concepts/func:parrot.mcp.filtering.allow_all_tools.md)

Allow all tools regardless of context.

## [by_organization()](concepts/func:parrot.mcp.filtering.by_organization.md)

Create predicate that restricts to specific organizations (multi-tenancy).

## [by_permission()](concepts/func:parrot.mcp.filtering.by_permission.md)

Create predicate that requires specific permission.

## [by_role()](concepts/func:parrot.mcp.filtering.by_role.md)

Create predicate that requires specific role.

## [by_scope()](concepts/func:parrot.mcp.filtering.by_scope.md)

Create predicate that requires OAuth scope.

## [by_server()](concepts/func:parrot.mcp.filtering.by_server.md)

Create predicate that filters by MCP server name.

## [by_tool_name()](concepts/func:parrot.mcp.filtering.by_tool_name.md)

Create predicate that filters by tool name (simple allowlist).

## [by_tool_pattern()](concepts/func:parrot.mcp.filtering.by_tool_pattern.md)

Create predicate that filters tools by name pattern.

## [by_user()](concepts/func:parrot.mcp.filtering.by_user.md)

Create predicate that restricts to specific users.

## [combine_and()](concepts/func:parrot.mcp.filtering.combine_and.md)

Combine multiple predicates with AND logic (all must pass).

## [combine_or()](concepts/func:parrot.mcp.filtering.combine_or.md)

Combine multiple predicates with OR logic (any can pass).

## [deny_all_tools()](concepts/func:parrot.mcp.filtering.deny_all_tools.md)

Deny all tools regardless of context.

## [exclude_by_tool_name()](concepts/func:parrot.mcp.filtering.exclude_by_tool_name.md)

Create predicate that blocks specific tool names (blocklist).

## [filter_tools()](concepts/func:parrot.mcp.filtering.filter_tools.md)

Filter tools using a predicate or allowlist.

## [negate()](concepts/func:parrot.mcp.filtering.negate.md)

Negate a predicate (invert boolean result).

## [create_alphavantage_mcp_server()](concepts/func:parrot.mcp.integration.create_alphavantage_mcp_server.md)

Create configuration for AlphaVantage MCP server.

## [create_api_key_mcp_server()](concepts/func:parrot.mcp.integration.create_api_key_mcp_server.md)

Create configuration for API key authenticated MCP server.

## [create_chrome_devtools_mcp_server()](concepts/func:parrot.mcp.integration.create_chrome_devtools_-5add390e.md)

Create configuration for Chrome DevTools MCP server.

## [create_fireflies_mcp_server()](concepts/func:parrot.mcp.integration.create_fireflies_mcp_server.md)

Create configuration for Fireflies MCP server using stdio transport.

## [create_google_maps_mcp_server()](concepts/func:parrot.mcp.integration.create_google_maps_mcp_server.md)

Create configuration for Google Maps MCP server.

## [create_http_mcp_server()](concepts/func:parrot.mcp.integration.create_http_mcp_server.md)

Create configuration for HTTP MCP server.

## [create_local_mcp_server()](concepts/func:parrot.mcp.integration.create_local_mcp_server.md)

Create configuration for local stdio MCP server.

## [create_netsuite_m2m_mcp_server()](concepts/func:parrot.mcp.integration.create_netsuite_m2m_mcp_server.md)

Create a NetSuite MCP server using OAuth2 Client Credentials (M2M) with certificate.

## [create_netsuite_mcp_server()](concepts/func:parrot.mcp.integration.create_netsuite_mcp_server.md)

Create a NetSuite MCP server configuration using OAuth2 Authorization Code + PKCE.

## [create_oauth_mcp_server()](concepts/func:parrot.mcp.integration.create_oauth_mcp_server.md)

Create an MCP server configuration with OAuth2 authorization code flow.

## [create_perplexity_mcp_server()](concepts/func:parrot.mcp.integration.create_perplexity_mcp_server.md)

Create configuration for Perplexity MCP server.

## [create_quic_mcp_server()](concepts/func:parrot.mcp.integration.create_quic_mcp_server.md)

Create configuration for QUIC MCP server.

## [create_unix_mcp_server()](concepts/func:parrot.mcp.integration.create_unix_mcp_server.md)

Create a Unix socket MCP server configuration.

## [create_websocket_mcp_server()](concepts/func:parrot.mcp.integration.create_websocket_mcp_server.md)

Create a WebSocket MCP server configuration.

## [validate_mcp_http()](concepts/func:parrot.mcp.integration.validate_mcp_http.md)

Validate that an MCP HTTP server is reachable and lists its tools.

## [get_mcp_oauth2_preset()](concepts/func:parrot.mcp.oauth2_config.get_mcp_oauth2_preset.md)

Look up an MCP OAuth2 preset by its registry slug.

## [list_mcp_oauth2_presets()](concepts/func:parrot.mcp.oauth2_config.list_mcp_oauth2_presets.md)

Return all registered MCP OAuth2 presets.

## [deregister_pending_callback()](concepts/func:parrot.mcp.oauth2_state.deregister_pending_callback.md)

Remove a pending callback entry without signalling it.

## [is_pending()](concepts/func:parrot.mcp.oauth2_state.is_pending.md)

Return ``True`` if there is a pending callback for the given state.

## [register_pending_callback()](concepts/func:parrot.mcp.oauth2_state.register_pending_callback.md)

Register a pending OAuth2 callback for the given state parameter.

## [resolve_pending_callback()](concepts/func:parrot.mcp.oauth2_state.resolve_pending_callback.md)

Resolve a pending OAuth2 callback by signalling the event.

## [get_factory_map()](concepts/func:parrot.mcp.registry.get_factory_map.md)

Return the dispatch map from registry slug to ``create_*`` factory function.

## [create_http_mcp_server()](concepts/func:parrot.mcp.server.create_http_mcp_server.md)

Create an HTTP MCP server.

## [create_sse_mcp_server()](concepts/func:parrot.mcp.server.create_sse_mcp_server.md)

Create an SSE MCP server.

## [create_stdio_mcp_server()](concepts/func:parrot.mcp.server.create_stdio_mcp_server.md)

Create a stdio MCP server.

## [create_unix_mcp_server()](concepts/func:parrot.mcp.server.create_unix_mcp_server.md)

Create an Unix MCP server.

## [main()](concepts/func:parrot.mcp.server.main.md)

Main CLI entry point.

## [create_quic_mcp_server()](concepts/func:parrot.mcp.transports.quic.create_quic_mcp_server.md)

Create configuration for QUIC/HTTP3 MCP server.

## [generate_self_signed_cert()](concepts/func:parrot.mcp.transports.quic.generate_self_signed_cert.md)

Generate self-signed certificate for development.

## [load_server_from_config()](concepts/func:parrot.mcp.wrapper.load_server_from_config.md)

Load a SimpleMCPServer instance from a YAML configuration file.

## [load_tool_class()](concepts/func:parrot.mcp.wrapper.load_tool_class.md)

Dynamic loading of a tool class by its class name.

## [resolve_config_value()](concepts/func:parrot.mcp.wrapper.resolve_config_value.md)

Resolve a configuration value against navconfig / os.environ.

## [cached_query()](concepts/func:parrot.memory.cache.cached_query.md)

Decorator to cache the result of async methods in classes

## [translate()](concepts/func:parrot.models.bedrock_models.translate.md)

Translate a public Anthropic model ID to its AWS Bedrock equivalent.

## [build_agent_metadata()](concepts/func:parrot.models.crew.build_agent_metadata.md)

Create execution metadata for an agent run.

## [determine_run_status()](concepts/func:parrot.models.crew.determine_run_status.md)

Compute the overall status for a crew execution.

## [build_planogram_json_diagram()](concepts/func:parrot.models.detections.build_planogram_json_diagram.md)

Produce a compact, human-friendly JSON 'diagram' of a PlanogramDescription.

## [planogram_diagram_to_markdown()](concepts/func:parrot.models.detections.planogram_diagram_to_markdown.md)

Render the JSON diagram as Markdown ready for reports.

## [validate_aspect_ratio()](concepts/func:parrot.models.generation.validate_aspect_ratio.md)

Validate that aspect ratio is in a supported format.

## [validate_resolution()](concepts/func:parrot.models.generation.validate_resolution.md)

Validate that resolution is supported.

## [get_shutoff_date()](concepts/func:parrot.models.openai.get_shutoff_date.md)

Return the API shutoff date for ``model``, or None if not deprecated.

## [is_deprecated()](concepts/func:parrot.models.openai.is_deprecated.md)

Return True if ``model`` is in DEPRECATIONS or matches an alias entry.

## [resolve_alias()](concepts/func:parrot.models.openai.resolve_alias.md)

Map a deprecated model ID to the recommended migration target.

## [pydantic_to_guided_json()](concepts/func:parrot.models.vllm.pydantic_to_guided_json.md)

Convert a Pydantic model class to vLLM guided_json schema.

## [build_after_client_attrs()](concepts/func:parrot.observability.attributes.build_after_cl-78b6b2e5.md)

Build OTel attributes for ``AfterClientCallEvent`` (client child span end).

## [build_after_invoke_attrs()](concepts/func:parrot.observability.attributes.build_after_in-d5f52d61.md)

Build OTel attributes for ``AfterInvokeEvent`` (agent root span end).

## [build_after_tool_attrs()](concepts/func:parrot.observability.attributes.build_after_tool_attrs.md)

Build OTel attributes for ``AfterToolCallEvent`` (tool child span end).

## [build_before_client_attrs()](concepts/func:parrot.observability.attributes.build_before_c-2008de68.md)

Build OTel attributes for ``BeforeClientCallEvent`` (client child span start).

## [build_before_invoke_attrs()](concepts/func:parrot.observability.attributes.build_before_i-07d7e313.md)

Build OTel attributes for ``BeforeInvokeEvent`` (agent root span start).

## [build_before_tool_attrs()](concepts/func:parrot.observability.attributes.build_before_tool_attrs.md)

Build OTel attributes for ``BeforeToolCallEvent`` (tool child span start).

## [build_client_failed_attrs()](concepts/func:parrot.observability.attributes.build_client_f-90b3d26d.md)

Build OTel attributes for ``ClientCallFailedEvent`` (client error span end).

## [build_invoke_failed_attrs()](concepts/func:parrot.observability.attributes.build_invoke_f-901c6fdd.md)

Build OTel attributes for ``InvokeFailedEvent`` (agent root span error end).

## [build_message_event_attrs()](concepts/func:parrot.observability.attributes.build_message_-ac074392.md)

Build OTel span-event attributes for ``MessageAddedEvent``.

## [build_tool_failed_attrs()](concepts/func:parrot.observability.attributes.build_tool_failed_attrs.md)

Build OTel attributes for ``ToolCallFailedEvent`` (tool error span end).

## [resolve_gen_ai_system()](concepts/func:parrot.observability.attributes.resolve_gen_ai_system.md)

Resolve a ``client_name`` emitted on ``BeforeClientCallEvent`` to the

## [ensure_observability_bootstrapped()](concepts/func:parrot.observability.bootstrap.ensure_observab-6f5a6c16.md)

Activate env-driven observability exactly once. Safe to call repeatedly.

## [reset_bootstrap_for_tests()](concepts/func:parrot.observability.bootstrap.reset_bootstrap-9a5dad9c.md)

Test-only: reset module state so a fresh bootstrap can run.

## [shutdown_observability()](concepts/func:parrot.observability.bootstrap.shutdown_observability.md)

Flush and tear down every active observability path. Idempotent + defensive.

## [shutdown_usage_recording()](concepts/func:parrot.observability.bootstrap.shutdown_usage_recording.md)

Unsubscribe the usage subscriber and close recorders. Idempotent.

## [agent_identity()](concepts/func:parrot.observability.context.agent_identity.md)

Bind *name* as the active agent for the duration of the block.

## [main()](concepts/func:parrot.observability.examples.basic_telemetry.main.md)

Run 3 demo ask() calls and send traces/metrics to OpenLIT.

## [make_metric_exporter()](concepts/func:parrot.observability.exporters.make_metric_exporter.md)

Return an OTLP metric exporter configured from *config*.

## [make_span_exporter()](concepts/func:parrot.observability.exporters.make_span_exporter.md)

Return an OTLP span exporter configured from *config*.

## [init_openlit()](concepts/func:parrot.observability.openlit_integration.init_openlit.md)

Initialize OpenLIT auto-instrumentation. Idempotent.

## [build_recorders_from_config()](concepts/func:parrot.observability.recorders.factory.build_r-1c46c065.md)

Return the recorder backends for ``config.usage_backend``.

## [setup_telemetry()](concepts/func:parrot.observability.setup.setup_telemetry.md)

Configure OpenTelemetry + cost observability and wire to the global registry.

## [shutdown_telemetry()](concepts/func:parrot.observability.setup.shutdown_telemetry.md)

Flush all exporters and clear the setup state. Idempotent.

## [init_traceloop()](concepts/func:parrot.observability.traceloop_integration.ini-12ff620a.md)

Initialize the Traceloop SDK (OpenLLMetry). Idempotent.

## [setup_traceloop()](concepts/func:parrot.observability.traceloop_integration.set-6458d2f7.md)

Activate the full ``traceloop`` backend. Idempotent.

## [shutdown_traceloop()](concepts/func:parrot.observability.traceloop_integration.shu-6e8a4a72.md)

Flush Traceloop and unregister native subscribers. Idempotent + defensive.

## [get_common_responses()](concepts/func:parrot.openapi.config.get_common_responses.md)

Common HTTP responses used across all endpoints.

## [get_security_schemes()](concepts/func:parrot.openapi.config.get_security_schemes.md)

Security schemes for API authentication.

## [setup_swagger()](concepts/func:parrot.openapi.config.setup_swagger.md)

Configure Swagger/OpenAPI documentation for AI-Parrot.

## [bake_envelope()](concepts/func:parrot.outputs.a2ui.baking.bake_envelope.md)

Bake an envelope: resolve all bindings against its data model.

## [persist_envelope()](concepts/func:parrot.outputs.a2ui.baking.persist_envelope.md)

Persist the source envelope via ``ArtifactStore`` and return its reference.

## [catalog_instructions()](concepts/func:parrot.outputs.a2ui.catalog.catalog_instructions.md)

Aggregate every component's embedded ``instructions`` for the LLM producer.

## [get_component()](concepts/func:parrot.outputs.a2ui.catalog.get_component.md)

Return the registered component for ``name``.

## [list_components()](concepts/func:parrot.outputs.a2ui.catalog.list_components.md)

Return the definitions of all registered components (name-sorted).

## [register_component()](concepts/func:parrot.outputs.a2ui.catalog.register_component.md)

Register a catalog component under ``name``.

## [unregister_component()](concepts/func:parrot.outputs.a2ui.catalog.unregister_component.md)

Remove a component from the catalog (primarily for test isolation).

## [validate_envelope()](concepts/func:parrot.outputs.a2ui.catalog.validate_envelope.md)

Validate an envelope against the catalog allowlist and the action gate.

## [deliver_artifact()](concepts/func:parrot.outputs.a2ui.delivery.deliver_artifact.md)

Deliver a ``RenderedArtifact`` via ``owner.send_notification`` (per-provider policy).

## [finalize_a2ui_response()](concepts/func:parrot.outputs.a2ui.emission.finalize_a2ui_response.md)

Route an ``OutputMode.A2UI`` response around the legacy formatter (FEAT-273).

## [is_binding_expression()](concepts/func:parrot.outputs.a2ui.models.is_binding_expression.md)

Return whether ``value`` is a data-model binding expression.

## [is_valid_pointer()](concepts/func:parrot.outputs.a2ui.models.is_valid_pointer.md)

Return whether ``pointer`` is a syntactically well-formed JSON Pointer.

## [generate_envelope()](concepts/func:parrot.outputs.a2ui.producer.generate_envelope.md)

Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.

## [get_a2ui_renderer()](concepts/func:parrot.outputs.a2ui.renderers.get_a2ui_renderer.md)

Resolve a renderer class by name, importing its satellite module if needed.

## [register_a2ui_renderer()](concepts/func:parrot.outputs.a2ui.renderers.register_a2ui_renderer.md)

Register an A2UI renderer class under ``name``.

## [deserialize()](concepts/func:parrot.outputs.a2ui.serialization.deserialize.md)

Deserialize wire JSON into the correct concrete A2UI message.

## [iter_jsonl()](concepts/func:parrot.outputs.a2ui.serialization.iter_jsonl.md)

Parse a JSONL payload into A2UI messages, one per non-empty line.

## [serialize()](concepts/func:parrot.outputs.a2ui.serialization.serialize.md)

Serialize an A2UI message to a JSON-ready dict, injecting ``version``.

## [to_jsonl()](concepts/func:parrot.outputs.a2ui.serialization.to_jsonl.md)

Serialize one or more messages to JSONL (one complete message per line).

## [get_infographic_html_renderer()](concepts/func:parrot.outputs.formats.get_infographic_html_renderer.md)

Return ``InfographicHTMLRenderer`` with its concrete type preserved.

## [get_output_prompt()](concepts/func:parrot.outputs.formats.get_output_prompt.md)

Get system prompt for mode.

## [get_renderer()](concepts/func:parrot.outputs.formats.get_renderer.md)

Get the renderer class for the given output mode.

## [has_system_prompt()](concepts/func:parrot.outputs.formats.has_system_prompt.md)

Check if mode has a registered system prompt.

## [extract_infographic_data()](concepts/func:parrot.outputs.formats.infographic.extract_inf-bf11b322.md)

Extract infographic data from the AIMessage response.

## [get_echarts_system_prompt_with_geo()](concepts/func:parrot.outputs.formats.mixins.emaps.get_echart-36c4cb77.md)

Combine base ECharts prompt with geo extension

## [register_renderer()](concepts/func:parrot.outputs.formats.register_renderer.md)

Decorator to register a renderer class and optionally its system prompt.

## [base_column_types()](concepts/func:parrot.outputs.formats.table_types.base_column_types.md)

Map DataFrame column dtypes to the FEAT-218 storage vocabulary.

## [canonical_records()](concepts/func:parrot.outputs.formats.table_types.canonical_records.md)

Serialize DataFrame rows to canonical, JSON-boundary-safe dicts.

## [dynamic_import_helper()](concepts/func:parrot.plugins.dynamic_import_helper.md)

Helper for __getattr__ to dynamically import plugin modules.

## [list_plugins()](concepts/func:parrot.plugins.importer.list_plugins.md)

List all available plugins in a subdirectory.

## [setup_plugin_importer()](concepts/func:parrot.plugins.setup_plugin_importer.md)

Configures a PluginImporter for any package to extend its search path.

## [build_cache_key()](concepts/func:parrot.registry.routing.cache.build_cache_key.md)

Build a stable, compact cache key.

## [extract_json_from_response()](concepts/func:parrot.registry.routing.llm_helper.extract_jso-bdc3a185.md)

Extract the first JSON object from an LLM response.

## [run_llm_ranking()](concepts/func:parrot.registry.routing.llm_helper.run_llm_ranking.md)

Call *invoke_fn* with *prompt*, apply a timeout, and parse JSON output.

## [apply_rules()](concepts/func:parrot.registry.routing.rules.apply_rules.md)

Score *available_stores* for *query* using the provided *rules*.

## [load_store_router_config()](concepts/func:parrot.registry.routing.yaml_loader.load_store-bbdf40fb.md)

Load a ``StoreRouterConfig`` from a YAML file or a pre-parsed dict.

## [create_reranker()](concepts/func:parrot.rerankers.factory.create_reranker.md)

Instantiate a reranker from a config dict.

## [schedule()](concepts/func:parrot.scheduler.manager.schedule.md)

Decorator to mark agent methods for scheduling.

## [derive_key_fingerprint()](concepts/func:parrot.security.audit_ledger.derive_key_fingerprint.md)

Return the SHA-256 hex digest of ``credential_material``.

## [decrypt_credential()](concepts/func:parrot.security.credentials_utils.decrypt_credential.md)

Decrypt a credential string retrieved from DocumentDB.

## [encrypt_credential()](concepts/func:parrot.security.credentials_utils.encrypt_credential.md)

Encrypt a credential dict for DocumentDB storage.

## [data_analysis_profile()](concepts/func:parrot.security.python_sanitizer.data_analysis_profile.md)

Return the data-analysis execution policy.

## [general_profile()](concepts/func:parrot.security.python_sanitizer.general_profile.md)

Return the general (tightest) execution policy.

## [looks_sensitive_key()](concepts/func:parrot.security.redaction.looks_sensitive_key.md)

Return True when a mapping key/name likely denotes a secret.

## [redact_secrets()](concepts/func:parrot.security.redaction.redact_secrets.md)

Recursively redact secret-like values from JSON-ish structures.

## [redact_text()](concepts/func:parrot.security.redaction.redact_text.md)

Redact common secret assignments and token-like values in text.

## [delete_vault_credential()](concepts/func:parrot.security.vault_utils.delete_vault_credential.md)

Hard-delete a Vault credential from DocumentDB.

## [load_vault_keys()](concepts/func:parrot.security.vault_utils.load_vault_keys.md)

Load vault master keys from the environment.

## [oauth2_vault_name()](concepts/func:parrot.security.vault_utils.oauth2_vault_name.md)

Build the deterministic Vault credential name for an OAuth2 token.

## [retrieve_vault_credential()](concepts/func:parrot.security.vault_utils.retrieve_vault_credential.md)

Decrypt and return a secret credential from the Vault.

## [store_vault_credential()](concepts/func:parrot.security.vault_utils.store_vault_credential.md)

Encrypt and upsert secret parameters in the Vault.

## [setup_whatsapp_bridge()](concepts/func:parrot.services.whatsapp.setup_whatsapp_bridge.md)

Register WhatsApp configuration API endpoints.

## [whatsapp_dashboard_page()](concepts/func:parrot.services.whatsapp.whatsapp_dashboard_page.md)

Serve the WhatsApp dashboard HTML (no auth required).

## [setup()](concepts/func:parrot.setup.cli.setup.md)

Interactive first-time setup wizard for AI-Parrot.

## [bootstrap_app()](concepts/func:parrot.setup.scaffolding.bootstrap_app.md)

Generate ``app.py`` and ``run.py`` in the project root.

## [class_name_from_slug()](concepts/func:parrot.setup.scaffolding.class_name_from_slug.md)

Convert a hyphenated slug to a PascalCase class name.

## [module_name_from_slug()](concepts/func:parrot.setup.scaffolding.module_name_from_slug.md)

Convert a hyphenated slug to a valid Python module name.

## [render_template()](concepts/func:parrot.setup.scaffolding.render_template.md)

Render a ``string.Template`` file from ``parrot/templates/``.

## [scaffold_agent()](concepts/func:parrot.setup.scaffolding.scaffold_agent.md)

Scaffold a new Agent Python file from the ``agent.py.tpl`` template.

## [slugify()](concepts/func:parrot.setup.scaffolding.slugify.md)

Convert a human-readable name to a URL-safe hyphenated slug.

## [write_env_vars()](concepts/func:parrot.setup.scaffolding.write_env_vars.md)

Write environment variables to a ``.env`` file.

## [create_skill_trigger_middleware()](concepts/func:parrot.skills.middleware.create_skill_trigger_-861caae3.md)

Create a PromptMiddleware that detects /trigger patterns.

## [discover_skills_in_dir()](concepts/func:parrot.skills.parsers.discover_skills_in_dir.md)

Discover single-file and composite skills in a directory (non-recursive).

## [parse_skill_directory()](concepts/func:parrot.skills.parsers.parse_skill_directory.md)

Parse a composite skill: ``{dir}/SKILL.md`` plus adjacent asset files.

## [parse_skill_file()](concepts/func:parrot.skills.parsers.parse_skill_file.md)

Parse a .md skill file with YAML frontmatter into a SkillDefinition.

## [render_skills_prompt_layer()](concepts/func:parrot.skills.prompt.render_skills_prompt_layer.md)

Build a static ``<available_skills>`` XML PromptLayer from the registry.

## [apply_unified_diff()](concepts/func:parrot.skills.store.apply_unified_diff.md)

Apply unified diff to reconstruct content.

## [compute_unified_diff()](concepts/func:parrot.skills.store.compute_unified_diff.md)

Compute unified diff between two versions.

## [create_skill_registry()](concepts/func:parrot.skills.store.create_skill_registry.md)

Factory function for SkillRegistry.

## [create_skill_tools()](concepts/func:parrot.skills.tools.create_skill_tools.md)

Create skill registry tools for an agent.

## [build_public_html_url()](concepts/func:parrot.storage.artifact_signing.build_public_html_url.md)

Build a signed, relative public-HTML URL for an infographic artifact.

## [get_signing_key()](concepts/func:parrot.storage.artifact_signing.get_signing_key.md)

Read ``INFOGRAPHIC_SIGNING_KEY`` from the environment.

## [sign_artifact()](concepts/func:parrot.storage.artifact_signing.sign_artifact.md)

Compute the base64url HMAC digest over ``'{artifact_id}|{expiry}'``.

## [verify_signature()](concepts/func:parrot.storage.artifact_signing.verify_signature.md)

Verify a ``{expiry}.{sig}`` signature segment.

## [build_conversation_backend()](concepts/func:parrot.storage.backends.build_conversation_backend.md)

Instantiate the backend specified by ``PARROT_STORAGE_BACKEND``.

## [build_overflow_store()](concepts/func:parrot.storage.backends.build_overflow_store.md)

Instantiate the overflow store specified by ``PARROT_OVERFLOW_STORE``.

## [load_metrics_from_path()](concepts/func:parrot.storage.backends.load_metrics_from_path.md)

Import and return a ``StorageMetrics`` instance from a module path.

## [create_multimodal_table()](concepts/func:parrot.stores.multimodal_schema.create_multimodal_table.md)

Create the multimodal collection table and HNSW index in PostgreSQL.

## [define_multimodal_collection()](concepts/func:parrot.stores.multimodal_schema.define_multimo-0fa17d9d.md)

Define (and cache) a SQLAlchemy ORM class for a multimodal collection.

## [search_multimodal()](concepts/func:parrot.stores.multimodal_schema.search_multimodal.md)

Search the multimodal collection for nearest neighbors.

## [create_parent_searcher()](concepts/func:parrot.stores.parents.factory.create_parent_searcher.md)

Instantiate a parent searcher from a config dict.

## [build_contextual_text()](concepts/func:parrot.stores.utils.contextual.build_contextual_text.md)

Build the text that will be embedded plus the header used.

## [validate_enhanced_html()](concepts/func:parrot.tools._enhance_html_check.validate_enhanced_html.md)

Raise ENHANCE_OUTPUT_INVALID if the HTML references disallowed resources.

## [current_credential()](concepts/func:parrot.tools.abstract.current_credential.md)

Return the per-call credential injected by the broker, or ``None``.

## [add_row_limit()](concepts/func:parrot.tools.databasequery.base.add_row_limit.md)

Inject a dialect-specific row limit into a query string.

## [get_source_class()](concepts/func:parrot.tools.databasequery.sources.get_source_class.md)

Look up a registered database source class by driver name.

## [normalize_driver()](concepts/func:parrot.tools.databasequery.sources.normalize_driver.md)

Map driver aliases to their canonical names.

## [register_source()](concepts/func:parrot.tools.databasequery.sources.register_source.md)

Decorator that registers a database source class in the registry.

## [get_computed_function()](concepts/func:parrot.tools.dataset_manager.computed.get_comp-d15a9bcc.md)

Look up a function by name from the registry.

## [list_computed_functions()](concepts/func:parrot.tools.dataset_manager.computed.list_com-870e8493.md)

Return a sorted list of all registered function names.

## [register_computed_function()](concepts/func:parrot.tools.dataset_manager.computed.register-ac5c236f.md)

Register a custom function in the computed-columns registry.

## [csv_to_markdown()](concepts/func:parrot.tools.dataset_manager.csv_reader.csv_to_markdown.md)

Convert a CSV file to a clean markdown table.

## [csv_to_structural_summary()](concepts/func:parrot.tools.dataset_manager.csv_reader.csv_to-cbfef1a9.md)

Return a brief structural summary of a CSV file.

## [columns_present_in_any()](concepts/func:parrot.tools.dataset_manager.filtering.store.c-15a09350.md)

Return names of datasets that contain ALL of the given columns.

## [warn_if_no_coverage()](concepts/func:parrot.tools.dataset_manager.filtering.store.w-371e124d.md)

Log a warning when no registered dataset covers the column(s).

## [apply_cardinality_cap()](concepts/func:parrot.tools.dataset_manager.filtering.values.-522b1593.md)

Truncate *values* to at most *cap* items, logging a warning if truncated.

## [infer_values_from_datasets()](concepts/func:parrot.tools.dataset_manager.filtering.values.-da220373.md)

Collect distinct values for *column* from in-memory datasets.

## [driver_to_dialect()](concepts/func:parrot.tools.dataset_manager.sources.dialects.-ea33e83a.md)

Map an ai-parrot driver name to a sqlglot dialect identifier.

## [resolve_opaque_source()](concepts/func:parrot.tools.dataset_manager.sources.opaque.re-f110709e.md)

Extract resource identifiers from non-SQL DataSource subclasses.

## [physical_tables()](concepts/func:parrot.tools.dataset_manager.sources.resolver.-8a448f7c.md)

Extract physical table references from a SQL query using sqlglot.

## [resolve_physical_resources()](concepts/func:parrot.tools.dataset_manager.sources.resolver.-5d177717.md)

Resolve a DataSource to the set of physical resources it will touch.

## [inject_rls_mongo()](concepts/func:parrot.tools.dataset_manager.sources.rls.injec-f46c5085.md)

Build a Mongo ``$and`` filter dict from RLS predicates.

## [inject_rls_postfetch()](concepts/func:parrot.tools.dataset_manager.sources.rls.injec-7efcae7f.md)

Apply RLS predicates as post-fetch row filtering on a DataFrame.

## [inject_rls_query_slug()](concepts/func:parrot.tools.dataset_manager.sources.rls.injec-1d44b932.md)

Merge RLS predicates into a QuerySlugSource's permanent_filter.

## [inject_rls_sql()](concepts/func:parrot.tools.dataset_manager.sources.rls.inject_rls_sql.md)

Inject RLS predicates into a SQL query via wrapping.

## [inject_rls_table_source()](concepts/func:parrot.tools.dataset_manager.sources.rls.injec-48e4623a.md)

Extend a TableSource's permanent_filter with RLS conditions.

## [dialect_hint()](concepts/func:parrot.tools.dataset_manager.sources.table.dialect_hint.md)

Return concise SQL-dialect guidance for ``driver`` (empty if unknown).

## [get_spatial_profile()](concepts/func:parrot.tools.dataset_manager.spatial.registry.-58b68472.md)

Look up a spatial profile by dataset name.

## [register_spatial_profile()](concepts/func:parrot.tools.dataset_manager.spatial.registry.-f0589de3.md)

Register (or replace) a spatial profile for a dataset.

## [validate_profiles_exist()](concepts/func:parrot.tools.dataset_manager.spatial.registry.-f5f59062.md)

Validate that every dataset name has a registered spatial profile.

## [requires_permission()](concepts/func:parrot.tools.decorators.requires_permission.md)

Annotate a toolkit method or AbstractTool class with required permissions.

## [tool()](concepts/func:parrot.tools.decorators.tool.md)

Decorator to mark a function as a tool with automatic schema generation.

## [tool_schema()](concepts/func:parrot.tools.decorators.tool_schema.md)

Decorator to specify a custom argument schema for a toolkit method.

## [discover_all()](concepts/func:parrot.tools.discovery.discover_all.md)

Combined discovery: fast registry + walk for plugins.

## [discover_from_registry()](concepts/func:parrot.tools.discovery.discover_from_registry.md)

Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.

## [discover_from_walk()](concepts/func:parrot.tools.discovery.discover_from_walk.md)

Full discovery: walk packages and find all AbstractTool/AbstractToolkit subclasses.

## [resolve_class()](concepts/func:parrot.tools.discovery.resolve_class.md)

Resolve a dotted path string to an actual class.

## [build_envelope_from_tool()](concepts/func:parrot.tools.executors.abstract.build_envelope-2214f4d6.md)

Construct a ToolExecutionEnvelope from a tool instance.

## [project_permission_context()](concepts/func:parrot.tools.executors.abstract.project_permis-9f5fb612.md)

Project a PermissionContext into a JSON-safe dict.

## [project_trace_context()](concepts/func:parrot.tools.executors.abstract.project_trace_context.md)

Project a TraceContext into a JSON-safe dict.

## [run_envelope_inprocess()](concepts/func:parrot.tools.executors.runner.run_envelope_inprocess.md)

Execute *envelope* in the current Python process.

## [build_head()](concepts/func:parrot.tools.interactive.catalog_registry.build_head.md)

Assemble the ``<head>`` injection for a skeleton's ``<!--HEAD-->`` marker.

## [get_interactive_catalog()](concepts/func:parrot.tools.interactive.catalog_registry.get_-c8f1449d.md)

Return the process-wide catalog singleton (not yet loaded).

## [hotswap_to_full_toolkit()](concepts/func:parrot.tools.jira_connect_tool.hotswap_to_full_toolkit.md)

Replace :class:`JiraConnectTool` in-place with the full toolkit.

## [setup_jira_oauth_session()](concepts/func:parrot.tools.jira_connect_tool.setup_jira_oauth_session.md)

Register either :class:`JiraConnectTool` or the full Jira toolkit.

## [brace_escape()](concepts/func:parrot.tools.pythonrepl.brace_escape.md)

Escape curly braces in text for format strings.

## [sanitize_input()](concepts/func:parrot.tools.pythonrepl.sanitize_input.md)

Sanitize input to the python REPL.

## [get_supported_toolkits()](concepts/func:parrot.tools.registry.get_supported_toolkits.md)

Get the dictionary of supported toolkits.

## [deliver_reminder()](concepts/func:parrot.tools.reminder.deliver_reminder.md)

Fire a reminder by delivering it through the requested notification channel.

## [register_telegram_bot()](concepts/func:parrot.tools.reminder.register_telegram_bot.md)

Register a Telegram bot token under its non-secret numeric id.

## [unregister_telegram_bot()](concepts/func:parrot.tools.reminder.unregister_telegram_bot.md)

Remove a previously registered Telegram bot token.

## [answer_memory()](concepts/func:parrot.tools.working_memory.tests.conftest.ans-9fa7ba67.md)

Create an in-memory AnswerMemory for testing.

## [census_df()](concepts/func:parrot.tools.working_memory.tests.conftest.census_df.md)

Generate a synthetic US Census-style DataFrame.

## [sales_df()](concepts/func:parrot.tools.working_memory.tests.conftest.sales_df.md)

Generate a synthetic sales DataFrame.

## [sample_dict()](concepts/func:parrot.tools.working_memory.tests.conftest.sample_dict.md)

A simple nested dict fixture.

## [sample_message()](concepts/func:parrot.tools.working_memory.tests.conftest.sam-ca3fd736.md)

AIMessage-like object with .content and .role attributes.

## [sample_text()](concepts/func:parrot.tools.working_memory.tests.conftest.sample_text.md)

A plain-text research finding.

## [toolkit()](concepts/func:parrot.tools.working_memory.tests.conftest.toolkit.md)

Create a WorkingMemoryToolkit with pre-loaded census and sales DataFrames.

## [toolkit_with_memory()](concepts/func:parrot.tools.working_memory.tests.conftest.too-6dde6ab4.md)

Create a WorkingMemoryToolkit wired to an AnswerMemory instance.

## [spy()](concepts/func:parrot.tools.working_memory.tests.test_thread_-e4750337.md)

Patch ``asyncio.to_thread`` as seen by the toolkit module with a spy.

## [cPrint()](concepts/func:parrot.utils.cPrint.md)

Console Print.

## [quiet_faiss_loader()](concepts/func:parrot.utils.faiss_logging.quiet_faiss_loader.md)

Raise the ``faiss`` logger to WARNING (or ``FAISS_LOG_LEVEL``). Idempotent.

## [current_context()](concepts/func:parrot.utils.helpers.current_context.md)

Return the RequestContext bound to the current asyncio task, if any.

## [article_extractor()](concepts/func:parrot.utils.jsonld_extractors.article_extractor.md)

Extract Article / NewsArticle / BlogPosting data from a JSON-LD node.

## [breadcrumb_extractor()](concepts/func:parrot.utils.jsonld_extractors.breadcrumb_extractor.md)

Extract BreadcrumbList data from a JSON-LD node.

## [event_extractor()](concepts/func:parrot.utils.jsonld_extractors.event_extractor.md)

Extract Event data from a JSON-LD node.

## [faq_extractor()](concepts/func:parrot.utils.jsonld_extractors.faq_extractor.md)

Extract FAQ Q&A pairs from a FAQPage JSON-LD node.

## [howto_extractor()](concepts/func:parrot.utils.jsonld_extractors.howto_extractor.md)

Extract HowTo data from a JSON-LD node.

## [organization_extractor()](concepts/func:parrot.utils.jsonld_extractors.organization_extractor.md)

Extract Organization data from a JSON-LD node.

## [person_extractor()](concepts/func:parrot.utils.jsonld_extractors.person_extractor.md)

Extract Person data from a JSON-LD node.

## [place_extractor()](concepts/func:parrot.utils.jsonld_extractors.place_extractor.md)

Extract Place / LocalBusiness data from a JSON-LD node.

## [product_extractor()](concepts/func:parrot.utils.jsonld_extractors.product_extractor.md)

Extract Product data from a JSON-LD node.

## [question_extractor()](concepts/func:parrot.utils.jsonld_extractors.question_extractor.md)

Extract a bare top-level ``Question`` node.

## [recipe_extractor()](concepts/func:parrot.utils.jsonld_extractors.recipe_extractor.md)

Extract Recipe data from a JSON-LD node.

## [strip_html_text()](concepts/func:parrot.utils.jsonld_extractors.strip_html_text.md)

Render arbitrary text as clean plain text.

## [walk_jsonld()](concepts/func:parrot.utils.jsonld_extractors.walk_jsonld.md)

Recursively walk a JSON-LD structure dispatching typed nodes to extractors.

## [deduplicate_name()](concepts/func:parrot.utils.naming.deduplicate_name.md)

Find a unique name by appending a numeric suffix if needed.

## [slugify_name()](concepts/func:parrot.utils.naming.slugify_name.md)

Convert a user-provided name into a URL-safe slug.

## [install_uvloop()](concepts/func:parrot.utils.uv.install_uvloop.md)

install uvloop and set as default loop for asyncio.

## [create_voice_server()](concepts/func:parrot.voice.handler.create_voice_server.md)

Create complete voice server application.

## [resolve_voice_client_class()](concepts/func:parrot.voice.handler.resolve_voice_client_class.md)

Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.

## [chunk_text()](concepts/func:parrot.voice.tts.supertonic_inference.chunk_text.md)

Split text into synthesis-sized chunks by paragraph then sentence.

## [get_latent_mask()](concepts/func:parrot.voice.tts.supertonic_inference.get_latent_mask.md)

Mask the latent sequence to the per-item audio length.

## [length_to_mask()](concepts/func:parrot.voice.tts.supertonic_inference.length_to_mask.md)

Build a binary length mask of shape ``(B, 1, max_len)``.

## [load_voice_style()](concepts/func:parrot.voice.tts.supertonic_inference.load_voice_style.md)

Load a single voice-style JSON into a batch-of-one :class:`Style`.

## [dumps()](concepts/func:parrot.yaml-rs.python.yaml_rs.dumps.md)

Serialize Python object to YAML string.

## [loads()](concepts/func:parrot.yaml-rs.python.yaml_rs.loads.md)

Deserialize YAML string to Python object.

## [handle_form_controls()](concepts/func:parrot_formdesigner.api.controls.handle_form_controls.md)

GET /api/v1/form-controls — return the registered control metadata.

## [handle_operations()](concepts/func:parrot_formdesigner.api.operations.handle_operations.md)

PATCH /api/v1/forms/{form_id}/operations — atomic batched edits.

## [get_renderer()](concepts/func:parrot_formdesigner.api.render.get_renderer.md)

Return the renderer registered under ``format_key`` or ``None``.

## [handle_render()](concepts/func:parrot_formdesigner.api.render.handle_render.md)

GET /api/v1/forms/{form_id}/render/{format} — render dispatcher.

## [register_renderer()](concepts/func:parrot_formdesigner.api.render.register_renderer.md)

Register (or overwrite) a renderer under ``format_key``.

## [supported_formats()](concepts/func:parrot_formdesigner.api.render.supported_formats.md)

Return the sorted list of currently registered format keys.

## [setup_form_api()](concepts/func:parrot_formdesigner.api.routes.setup_form_api.md)

Mount the JSON REST surface on ``app`` under ``base_path``.

## [handle_rest_upload()](concepts/func:parrot_formdesigner.api.uploads.handle_rest_upload.md)

Handle POST /api/v1/forms/{form_id}/fields/{field_id}/upload.

## [get_controls()](concepts/func:parrot_formdesigner.controls.registry.get_controls.md)

Return all registered controls in registration order.

## [iter_controls()](concepts/func:parrot_formdesigner.controls.registry.iter_controls.md)

Yield registered controls in registration order.

## [register_field_control()](concepts/func:parrot_formdesigner.controls.registry.register-33e43f79.md)

Register (or overwrite) a control entry in the toolbar registry.

## [get_country_info()](concepts/func:parrot_formdesigner.core._location_data.get_co-adbcef52.md)

Return name, flag emoji, and dial code for a country code.

## [is_valid_iso_country_code()](concepts/func:parrot_formdesigner.core._location_data.is_val-953348d7.md)

Return True if code is a valid ISO 3166-1 alpha-2 country code.

## [list_country_options()](concepts/func:parrot_formdesigner.core._location_data.list_c-d462ae95.md)

Return all countries as a FieldOption list sorted by name.

## [build_audio_synthesizer()](concepts/func:parrot_formdesigner.renderers.audio.build_audi-63aa4230.md)

Build a VoiceSynthesizer preferring SuperTonic, else None (FEAT-236).

## [classify_voice_mode()](concepts/func:parrot_formdesigner.renderers.audio.classify_voice_mode.md)

Classify a FormField into a VoiceMode (FEAT-236).

## [synthesize_with_fallback()](concepts/func:parrot_formdesigner.renderers.audio.synthesize-68252a70.md)

Synthesize ``text`` to audio bytes, SuperTonic→Google→text-only.

## [is_unique_violation()](concepts/func:parrot_formdesigner.services._db_utils.is_uniq-45b50a75.md)

Return True when ``exc`` is a Postgres UNIQUE constraint violation.

## [qualified_table()](concepts/func:parrot_formdesigner.services._identifiers.qual-0d821a70.md)

Return ``"<schema>"."<table>"`` after validating both identifiers.

## [validate_identifier()](concepts/func:parrot_formdesigner.services._identifiers.vali-0b266942.md)

Return ``value`` if it is a safe Postgres identifier.

## [get_form_callback()](concepts/func:parrot_formdesigner.services.callback_registry-2b8f95c1.md)

Look up a registered callback with tenant → global fallback.

## [list_form_callbacks()](concepts/func:parrot_formdesigner.services.callback_registry-a79f2145.md)

Return all callback keys visible to a tenant.

## [register_form_callback()](concepts/func:parrot_formdesigner.services.callback_registry-10b6dc46.md)

Decorator that registers an async callback in the form callback registry.

## [issue_form_csrf_token()](concepts/func:parrot_formdesigner.services.csrf.issue_form_csrf_token.md)

Issue a CSRF token for the given session / form pair.

## [validate_form_csrf_token()](concepts/func:parrot_formdesigner.services.csrf.validate_for-871fbc3c.md)

Validate a CSRF token against the in-process store.

## [apply_schema_overrides()](concepts/func:parrot_formdesigner.services.event_dispatcher.-b6b7e3ad.md)

Shallow-merge ``overrides`` onto a copy of ``base``.

## [dispatch()](concepts/func:parrot_formdesigner.services.event_dispatcher.dispatch.md)

Resolve and run the handler bound to ``event`` for ``form``.

## [dispatch_visit()](concepts/func:parrot_formdesigner.services.event_dispatcher.-bf62100e.md)

Resolve and run the handler bound to a visit lifecycle ``event``.

## [get_form_event()](concepts/func:parrot_formdesigner.services.event_registry.ge-ad1d519e.md)

Look up a registered event handler with tenant → global fallback.

## [list_form_events()](concepts/func:parrot_formdesigner.services.event_registry.li-350ec467.md)

Return all event handler keys visible to a tenant.

## [register_form_event()](concepts/func:parrot_formdesigner.services.event_registry.re-ee4ce25b.md)

Decorator that registers an async handler in the form event registry.

## [enrich_submission()](concepts/func:parrot_formdesigner.services.metadata_enricher-a25727e2.md)

Resolve declared metadata for a pending submission.

## [public_form_paths()](concepts/func:parrot_formdesigner.services.public_forms.publ-8332e668.md)

Return the auth-exempt glob patterns for a public form.

## [get_dependency_rule_snippets()](concepts/func:parrot_formdesigner.tools.field_helpers.get_de-f6eb0bc8.md)

Return skeleton dicts for building ``depends_on`` and ``post_depends`` rules.

## [get_form_field_schema_snippets()](concepts/func:parrot_formdesigner.tools.field_helpers.get_fo-2cec44b3.md)

Return example JSON snippets for each supported field type.

## [list_supported_form_field_types()](concepts/func:parrot_formdesigner.tools.field_helpers.list_s-0033d0a8.md)

Return supported field type values for FormField.field_type.

## [get_form_service()](concepts/func:parrot_formdesigner.tools.services.registry.ge-38b70427.md)

Resolve a registered form-service class by name.

## [list_form_services()](concepts/func:parrot_formdesigner.tools.services.registry.li-25e1aa6f.md)

Return registered service names in registration order.

## [register_form_service()](concepts/func:parrot_formdesigner.tools.services.registry.re-f9dbb895.md)

Register (or overwrite) a form-service class under ``name``.

## [setup_form_ui()](concepts/func:parrot_formdesigner.ui.routes.setup_form_ui.md)

Mount the HTML page + Telegram WebApp surface on ``app``.

## [error_page()](concepts/func:parrot_formdesigner.ui.templates.error_page.md)

Return an error page body.

## [form_page()](concepts/func:parrot_formdesigner.ui.templates.form_page.md)

Return the HTML body wrapping a rendered form fragment.

## [gallery_page()](concepts/func:parrot_formdesigner.ui.templates.gallery_page.md)

Return the HTML body for the gallery page.

## [index_page()](concepts/func:parrot_formdesigner.ui.templates.index_page.md)

Return the HTML body for the index page (prompt builder + DB loader).

## [page_shell()](concepts/func:parrot_formdesigner.ui.templates.page_shell.md)

Wrap body HTML in a full page shell.

## [schema_page()](concepts/func:parrot_formdesigner.ui.templates.schema_page.md)

Return the HTML body for the JSON Schema view page.

## [get_loader_class()](concepts/func:parrot_loaders.factory.get_loader_class.md)

Get the loader class for the given extension.

## [extract_sections_from_response()](concepts/func:parrot_loaders.imageunderstanding.extract_sect-a2aa52e3.md)

Extract structured sections from the AI image analysis response.

## [split_text()](concepts/func:parrot_loaders.imageunderstanding.split_text.md)

Split text into chunks of a maximum length, ensuring not to break words.

## [get_ocr_backend()](concepts/func:parrot_loaders.ocr.get_ocr_backend.md)

Factory function to instantiate an OCR backend by name.

## [render_markdown()](concepts/func:parrot_loaders.ocr.layout.render_markdown.md)

Convert a :class:`LayoutResult` into a Markdown string.

## [split_text()](concepts/func:parrot_loaders.videolocal.split_text.md)

Split text into chunks of a maximum length, ensuring not to break words.

## [extract_scenes_from_response()](concepts/func:parrot_loaders.videounderstanding.extract_scen-67afba3b.md)

Extract structured scenes from the AI response.

## [split_text()](concepts/func:parrot_loaders.videounderstanding.split_text.md)

Split text into chunks of a maximum length, ensuring not to break words.

## [get_strategy()](concepts/func:parrot_pipelines.planogram.grid.strategy.get_strategy.md)

Instantiate and return the grid strategy for the given GridType.

## [create_arangodb_search_tool()](concepts/func:parrot_tools.arangodbsearch.create_arangodb_search_tool.md)

Factory function to create ArangoDB search tool with embedding support.

## [numerical_derivative()](concepts/func:parrot_tools.calculator.operations.calculus.nu-2a5617a6.md)

Calculate numerical derivative using central difference.

## [numerical_integral()](concepts/func:parrot_tools.calculator.operations.calculus.nu-69dbb1a6.md)

Calculate numerical integral using Simpson's rule.

## [operation()](concepts/func:parrot_tools.calculator.operations.operation.md)

Decorator to mark a function as a calculator operation.

## [calculate_correlation()](concepts/func:parrot_tools.calculator.operations.statistics.-4f390d36.md)

Calculate Pearson correlation coefficient.

## [calculate_mean()](concepts/func:parrot_tools.calculator.operations.statistics.-106194cc.md)

Calculate the arithmetic mean of a list of values.

## [calculate_median()](concepts/func:parrot_tools.calculator.operations.statistics.-ed76c9ab.md)

Calculate median value.

## [calculate_std()](concepts/func:parrot_tools.calculator.operations.statistics.-45a76c10.md)

Calculate standard deviation.

## [generate_chart()](concepts/func:parrot_tools.chart.generate_chart.md)

Convenience function to generate a chart without instantiating the tool.

## [parse_frontmatter()](concepts/func:parrot_tools.code_toolkit.parse_frontmatter.md)

Parse a small YAML-like frontmatter block without adding dependencies.

## [create_executor()](concepts/func:parrot_tools.codeinterpreter.executor.create_executor.md)

Factory function to create appropriate executor.

## [calculate_code_hash()](concepts/func:parrot_tools.codeinterpreter.internals.calcula-73e085b8.md)

Calculate SHA-256 hash of code.

## [markdown_to_plain()](concepts/func:parrot_tools.gvoice.markdown_to_plain.md)

Convert Markdown to plain text via HTML parsing.

## [strip_markdown()](concepts/func:parrot_tools.gvoice.strip_markdown.md)

Remove the most common inline Markdown markers.

## [get_wsdl_path()](concepts/func:parrot_tools.interfaces.workday.config.get_wsdl_path.md)

Return the WSDL path for a given Workday operation type.

## [extract_id_by_type()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-fc0a486a.md)

Helper function to extract ID value by type from ID list

## [parse_applicant_background_check_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-44efd606.md)

Parse Background Check data for Applicant

## [parse_applicant_contact_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-636d183c.md)

Parse Contact Information for Applicant

## [parse_applicant_document_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-73efb6cf.md)

Parse Document/Attachment data for Applicant

## [parse_applicant_education_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-cfd12996.md)

Parse Education data for Applicant

## [parse_applicant_experience_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-79c96f57.md)

Parse Experience data for Applicant

## [parse_applicant_identification_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-c7847db1.md)

Parse Identification data for Applicant

## [parse_applicant_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-547188f4.md)

Parse Organization/Location data for Applicant

## [parse_applicant_personal_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-82b8d617.md)

Parse Personal Data for Applicant

## [parse_applicant_recruitment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-1e5b79f3.md)

Parse Recruitment specific data for Applicant

## [parse_applicant_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-8feec438.md)

Parse Applicant Reference data

## [parse_applicant_skills_data()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-697f3f7d.md)

Parse Skills and Competencies data for Applicant

## [safe_get_dict()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-87f3e80b.md)

Safely get a value from data, handling cases where data might be a list.

## [to_date_string()](concepts/func:parrot_tools.interfaces.workday.parsers.applic-9ad2a104.md)

Convert datetime/date objects to ISO format string (YYYY-MM-DD)

## [ensure_list()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-274a7265.md)

Ensure value is a list

## [extract_id_by_type()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-2289661f.md)

Helper function to extract ID value by type from ID list

## [parse_candidate_applications()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-ae3d4b07.md)

Devuelve todas las postulaciones del candidato como una lista en 'applications'.

## [parse_candidate_assessment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-405026c7.md)

Parse Assessment/Rating data for Candidate

## [parse_candidate_background_check_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-f3d90995.md)

Parse Background Check data for Candidate

## [parse_candidate_contact_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-3fda74b1.md)

Parse Contact Information for Candidate - based on actual Workday XML structure

## [parse_candidate_document_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-648aa7bc.md)

Parse Document/Attachment data for Candidate.

## [parse_candidate_education_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-9a5d9fcd.md)

Parse Education data for Candidate.

## [parse_candidate_experience_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-6c01e735.md)

Parse Experience data for Candidate.

## [parse_candidate_identification_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-b7edf89e.md)

Parse Identification data for Candidate

## [parse_candidate_interview_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-8a310e88.md)

Parse Interview data for Candidate

## [parse_candidate_language_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-663e67f3.md)

Parse Language data for Candidate

## [parse_candidate_metadata()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-1f010e7f.md)

Parse metadata like created date, modified date, tags

## [parse_candidate_offer_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-214e6fe5.md)

Parse Offer data for Candidate

## [parse_candidate_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-5822ee8c.md)

Parse Organization/Location data for Candidate

## [parse_candidate_personal_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-369ac750.md)

Parse Personal Data for Candidate - based on actual Workday XML structure

## [parse_candidate_prospect_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-d7484f84.md)

Parse Prospect Data for Candidate

## [parse_candidate_recruitment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-eb33837b.md)

Parse Recruitment-specific data for Candidate (campos "planos" a partir de la

## [parse_candidate_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-fb6f4ce4.md)

Parse Candidate Reference data and related references (Pre-Hire, Worker).

## [parse_candidate_reference_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-e19fae4d.md)

Parse Reference (employment references) data for Candidate

## [parse_candidate_skills_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-3d1ffda3.md)

Parse Skills, Competencies and Languages data for Candidate.

## [parse_candidate_status_data()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-b6f34fa6.md)

Parse Status Data for Candidate (Do Not Hire, Withdrawn)

## [safe_get_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-a751ce24.md)

Safely get a _Reference field that might be a dict, list, or None.

## [save_attachment()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-40d81e39.md)

Save attachment file from base64 content to disk.

## [to_date_string()](concepts/func:parrot_tools.interfaces.workday.parsers.candid-f0dc010b.md)

Convert datetime/date objects to ISO format string (YYYY-MM-DD)

## [parse_cost_center_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-35da4c2a.md)

Parse complete Cost Center data from Workday response.

## [parse_cost_center_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-f62c2e18.md)

Parse Cost Center Reference to extract WID and ID.

## [parse_integration_id_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-616ce682.md)

Parse Integration ID Data from Cost Center response.

## [parse_organization_container_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-6d0ac8e3.md)

Parse Organization Container data.

## [parse_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-e914998e.md)

Parse Organization Data section from Cost Center response.

## [parse_organization_type_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-c648cc74.md)

Parse Organization Type and Subtype data.

## [parse_worktags_data()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-baec0da9.md)

Parse Worktags data.

## [safe_get_nested()](concepts/func:parrot_tools.interfaces.workday.parsers.cost_c-94c80ced.md)

Safely get nested dictionary values.

## [parse_custom_punch_field_report_data()](concepts/func:parrot_tools.interfaces.workday.parsers.custom-530e1404.md)

Parse the raw Custom Punch - Field Report data from SOAP response.

## [coalesce()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-661c5417.md)

Return the first non-None value from the arguments.

## [parse_integration_id_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-e1625bf1.md)

Parse Integration ID Data from Job Posting response.

## [parse_job_posting_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-b0e602e8.md)

Parse complete Job Posting data from Workday response.

## [parse_job_posting_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-a4454aa4.md)

Parse Job Posting Reference to extract WID and ID.

## [parse_job_posting_sites()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-0ef38261.md)

Parse Job Posting Sites data.

## [parse_job_profile_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-e4d683e0.md)

Parse Job Profile Reference data.

## [parse_job_requisition_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-50108c93.md)

Parse Job Requisition Reference from Job Posting.

## [parse_location_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-786d8069.md)

Parse Location Reference data.

## [parse_qualifications_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-cbd4065a.md)

Parse Qualifications data (competencies).

## [parse_supervisory_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-d9490c54.md)

Parse Supervisory Organization Reference data.

## [parse_worker_type_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-cafee2f1.md)

Parse Worker Type Reference data.

## [parse_integration_id_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-9a1fd523.md)

Parse Integration ID Data from Job Posting Site response.

## [parse_job_posting_site_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-01f7805f.md)

Parse complete Job Posting Site data from Workday response.

## [parse_job_posting_site_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-99230ec3.md)

Parse Job Posting Site Reference to extract WID and ID.

## [parse_site_type_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_po-19588f42.md)

Parse Site Type Reference data.

## [parse_compensation_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-3cec085e.md)

Parse Requisition Compensation Data.

## [parse_hiring_manager_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-3f4e07c9.md)

Parse Hiring Manager Reference data.

## [parse_integration_id_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-616dabb9.md)

Parse Integration ID Data from Job Requisition response.

## [parse_job_profile_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-a76e7d89.md)

Parse Job Profile Reference data.

## [parse_job_requisition_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-888d0f20.md)

Parse complete Job Requisition data from Workday response.

## [parse_job_requisition_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-c813f166.md)

Parse Job Requisition Reference to extract WID and ID.

## [parse_jr_location_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-29a45d7b.md)

Parse Location Reference data for Job Requisitions.

## [parse_organization_assignments_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-09577fd6.md)

Parse Organization Assignments Data (Company, Cost Center, etc.).

## [parse_position_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-8119c0f0.md)

Parse Position Reference data.

## [parse_qualifications_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-260e87ff.md)

Parse Qualifications data (competencies, certifications, education, etc.).

## [parse_questionnaire_references()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-4cc24778.md)

Parse Questionnaire Reference data.

## [parse_recruiter_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-8df24180.md)

Parse Recruiter Reference data (single recruiter).

## [parse_role_assignment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-36c1faf9.md)

Parse Role Assignment Data to extract recruiters and other role assignees.

## [parse_supervisory_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-979d1036.md)

Parse Supervisory Organization Reference data.

## [parse_worker_type_data()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-eac75683.md)

Parse Worker Type Reference data.

## [safe_get_nested()](concepts/func:parrot_tools.interfaces.workday.parsers.job_re-da6f9e72.md)

Safely get nested dictionary values.

## [parse_location_hierarchy_assignment()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-47050f4b.md)

Parse location hierarchy organization assignment data.

## [parse_location_hierarchy_assignments_data()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-64de3d7c.md)

Main parser function for location hierarchy assignments data.

## [parse_location_hierarchy_assignments_response()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-2cd0d61a.md)

Parse the complete location hierarchy assignments response.

## [parse_location_hierarchy_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-b628e33b.md)

Parse location hierarchy reference data.

## [parse_organization_assignment()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-61f95b3b.md)

Parse organization assignment by type data.

## [parse_organization_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-a1cd0267.md)

Parse organization reference data.

## [parse_organization_type_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-d25b3818.md)

Parse organization type reference data.

## [parse_response_results()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-f9ea42c6.md)

Parse response results (pagination info).

## [parse_location_data()](concepts/func:parrot_tools.interfaces.workday.parsers.locati-43fac0e5.md)

Parse the main location data from Workday response.

## [parse_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.organi-41347b32.md)

Parse organization data from Workday SOAP response.

## [parse_organizations_response()](concepts/func:parrot_tools.interfaces.workday.parsers.organi-1d3f6359.md)

Parse the complete organizations response from Workday.

## [parse_reference_data()](concepts/func:parrot_tools.interfaces.workday.parsers.refere-3ac3ece3.md)

Parse one ``Reference_ID`` element from a Get_References response.

## [parse_time_block_data()](concepts/func:parrot_tools.interfaces.workday.parsers.time_b-2b909af1.md)

Parse the main time block data from Workday response.

## [parse_time_off_balance_data()](concepts/func:parrot_tools.interfaces.workday.parsers.time_o-8cf2ffaa.md)

Parse time off plan balance data from the SOAP response.

## [parse_time_request_data()](concepts/func:parrot_tools.interfaces.workday.parsers.time_r-2a7d9115.md)

Parse time request data from the SOAP response.

## [format_phone_number()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-30a463d0.md)

Formats a phone number from various formats to the required standards.

## [parse_benefits_and_roles()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-d327141a.md)

Parse benefit enrollments, roles, and worker documents.

## [parse_business_site()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-ae11ac0a.md)

Parse business site summary data.

## [parse_compensation_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-0eee2a26.md)

Parse the compensation details of the worker.

## [parse_contact_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-edcf488e.md)

Parse the contact information (email, address, phone) of the worker.

## [parse_employment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-65c38ada.md)

Parse employment-related details (position, hours, job profile).

## [parse_identification_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-32d22a59.md)

Parse identification details (national ID, license, custom IDs).

## [parse_international_assignment_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-e83fd0a3.md)

Parse international assignment summary data.

## [parse_management_chain_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-4157684f.md)

Parse management chain data from Worker_Management_Chain_Data.

## [parse_payroll_and_tax_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-c18c3f6b.md)

Parse payroll and tax related data from Position_Data.

## [parse_personal_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-49a13ceb.md)

Parse the personal information of the worker.

## [parse_position_management_chain_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-d3642b59.md)

Parse management chain data from Position_Management_Chains_Data.

## [parse_position_organizations()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-afe3cd4c.md)

Parse position organization data from Position_Organizations_Data.

## [parse_worker_organization_data()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-32941ea5.md)

Parse worker organization information from worker data

## [parse_worker_reference()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-9047696e.md)

Extracts the main Worker_Reference WID from a Worker SOAP response.

## [parse_worker_status()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-542e182c.md)

Parse worker status details (active, hire/termination dates, eligibility),

## [save_worker_document()](concepts/func:parrot_tools.interfaces.workday.parsers.worker-57bbc9ad.md)

Save worker document file from base64 content to disk.

## [ensure_list()](concepts/func:parrot_tools.interfaces.workday.utils.utils.ensure_list.md)

Convert a potentially singular value to a list.

## [extract_by_type()](concepts/func:parrot_tools.interfaces.workday.utils.utils.ex-fe28117a.md)

Given a list of {'_value_1':…, 'type':…} dicts (or a single dict),

## [extract_nested()](concepts/func:parrot_tools.interfaces.workday.utils.utils.ex-50c04ed4.md)

Helper to extract nested data from a dict given a list of keys.

## [first()](concepts/func:parrot_tools.interfaces.workday.utils.utils.first.md)

Helper to get first item of a list or dict, or empty dict if neither.

## [safe_serialize()](concepts/func:parrot_tools.interfaces.workday.utils.utils.sa-f06ad41a.md)

Serialize Decimal, list or dict into JSON-friendly string,

## [create_msteams_toolkit()](concepts/func:parrot_tools.msteams.create_msteams_toolkit.md)

Create and return a configured MSTeamsToolkit instance.

## [get_navigator_layers()](concepts/func:parrot_tools.navigator.prompt.get_navigator_layers.md)

Return all custom Navigator prompt layers.

## [create_file_management_toolkit()](concepts/func:parrot_tools.o365.bundle.create_file_management_toolkit.md)

Factory function to create a complete file management toolkit.

## [create_onedrive_toolkit()](concepts/func:parrot_tools.o365.bundle.create_onedrive_toolkit.md)

Factory function to create a OneDrive toolkit.

## [create_sharepoint_toolkit()](concepts/func:parrot_tools.o365.bundle.create_sharepoint_toolkit.md)

Factory function to create a SharePoint toolkit.

## [build_install_argv()](concepts/func:parrot_tools.odoo.shell.build_install_argv.md)

Build the argv list for an install or upgrade call.

## [default_database()](concepts/func:parrot_tools.odoo.shell.default_database.md)

Return the default Odoo database from the environment.

## [odoo_bin_path()](concepts/func:parrot_tools.odoo.shell.odoo_bin_path.md)

Return the path to the odoo-bin binary, or None when not configured.

## [odoo_conf_path()](concepts/func:parrot_tools.odoo.shell.odoo_conf_path.md)

Return the Odoo config file path from the environment.

## [run_odoo_subprocess()](concepts/func:parrot_tools.odoo.shell.run_odoo_subprocess.md)

Run an odoo-bin / odoo-cli subprocess and capture output.

## [validate_subcommand()](concepts/func:parrot_tools.odoo.shell.validate_subcommand.md)

Validate that a subcommand is on the whitelist.

## [validate_token()](concepts/func:parrot_tools.odoo.shell.validate_token.md)

Validate that a token contains only safe characters.

## [select_smart_fields()](concepts/func:parrot_tools.odoo.smart_fields.select_smart_fields.md)

Select the most LLM-useful fields from an Odoo ``fields_get`` response.

## [auto_detect_transport()](concepts/func:parrot_tools.odoo.transport.detect.auto_detect-549bb477.md)

Return the best transport for the given server.

## [build_transport()](concepts/func:parrot_tools.odoo.transport.detect.build_transport.md)

Build a transport for an explicit protocol choice.

## [count_tokens()](concepts/func:parrot_tools.pdfprint.count_tokens.md)

Count tokens in text using tiktoken.

## [compute_correlation_from_input()](concepts/func:parrot_tools.quant.correlation.compute_correla-d858dc9f.md)

Compute correlation matrix from CorrelationInput model.

## [compute_correlation_matrix()](concepts/func:parrot_tools.quant.correlation.compute_correla-59461691.md)

Compute correlation matrix for multiple assets.

## [compute_cross_asset_correlation()](concepts/func:parrot_tools.quant.correlation.compute_cross_a-bdac6e63.md)

Compute correlation between equities (252 trading days) and crypto (365 days).

## [compute_pairwise_correlation()](concepts/func:parrot_tools.quant.correlation.compute_pairwis-88aed4cf.md)

Compute correlation between two return series.

## [compute_rolling_correlation()](concepts/func:parrot_tools.quant.correlation.compute_rolling-26fccd61.md)

Compute rolling correlation between two return series.

## [detect_correlation_regimes()](concepts/func:parrot_tools.quant.correlation.detect_correlat-2595e088.md)

Compare short-term vs long-term correlations to detect regime changes.

## [get_correlation_heatmap_data()](concepts/func:parrot_tools.quant.correlation.get_correlation-01f55900.md)

Get correlation data formatted for heatmap visualization.

## [prices_to_returns()](concepts/func:parrot_tools.quant.correlation.prices_to_returns.md)

Convert price series to returns.

## [batch_piotroski_scores()](concepts/func:parrot_tools.quant.piotroski.batch_piotroski_scores.md)

Calculate F-Scores for multiple symbols.

## [calculate_piotroski_score()](concepts/func:parrot_tools.quant.piotroski.calculate_piotroski_score.md)

Calculate Piotroski F-Score (0-9) for fundamental quality.

## [get_fscore_summary()](concepts/func:parrot_tools.quant.piotroski.get_fscore_summary.md)

Generate a human-readable summary of the F-Score result.

## [rank_by_fscore()](concepts/func:parrot_tools.quant.piotroski.rank_by_fscore.md)

Rank symbols by F-Score descending.

## [compute_beta()](concepts/func:parrot_tools.quant.risk_metrics.compute_beta.md)

Beta = Cov(asset, benchmark) / Var(benchmark).

## [compute_cvar()](concepts/func:parrot_tools.quant.risk_metrics.compute_cvar.md)

Conditional VaR (Expected Shortfall).

## [compute_exposure()](concepts/func:parrot_tools.quant.risk_metrics.compute_exposure.md)

Compute net and gross exposure from weights.

## [compute_max_drawdown()](concepts/func:parrot_tools.quant.risk_metrics.compute_max_drawdown.md)

Maximum drawdown from cumulative returns.

## [compute_portfolio_cvar()](concepts/func:parrot_tools.quant.risk_metrics.compute_portfolio_cvar.md)

Portfolio CVaR (Expected Shortfall).

## [compute_portfolio_risk()](concepts/func:parrot_tools.quant.risk_metrics.compute_portfolio_risk.md)

Compute all risk metrics for a portfolio.

## [compute_portfolio_var_historical()](concepts/func:parrot_tools.quant.risk_metrics.compute_portfo-dcb9257e.md)

Portfolio VaR using historical simulation.

## [compute_portfolio_var_parametric()](concepts/func:parrot_tools.quant.risk_metrics.compute_portfo-5d7dbc7e.md)

Portfolio VaR using variance-covariance method.

## [compute_returns()](concepts/func:parrot_tools.quant.risk_metrics.compute_returns.md)

Convert price series to daily returns.

## [compute_rolling_metrics()](concepts/func:parrot_tools.quant.risk_metrics.compute_rolling_metrics.md)

Compute rolling risk metrics.

## [compute_sharpe_ratio()](concepts/func:parrot_tools.quant.risk_metrics.compute_sharpe_ratio.md)

Annualized Sharpe ratio.

## [compute_single_asset_risk()](concepts/func:parrot_tools.quant.risk_metrics.compute_single-b77ec002.md)

Compute all risk metrics for a single asset.

## [compute_var_historical()](concepts/func:parrot_tools.quant.risk_metrics.compute_var_historical.md)

Historical VaR using empirical percentile.

## [compute_var_parametric()](concepts/func:parrot_tools.quant.risk_metrics.compute_var_parametric.md)

Parametric VaR assuming normal distribution.

## [compute_volatility_annual()](concepts/func:parrot_tools.quant.risk_metrics.compute_volati-aa78c7a1.md)

Annualized volatility.

## [create_custom_scenario()](concepts/func:parrot_tools.quant.stress_testing.create_custo-542488c7.md)

Create a custom stress scenario.

## [create_sector_rotation_scenario()](concepts/func:parrot_tools.quant.stress_testing.create_secto-7550d496.md)

Create a sector rotation scenario.

## [create_volatility_shock_scenario()](concepts/func:parrot_tools.quant.stress_testing.create_volat-c5a25a60.md)

Create a scenario where volatility spikes by a multiplier.

## [get_concentrated_risk_positions()](concepts/func:parrot_tools.quant.stress_testing.get_concentr-2564eb16.md)

Identify positions that contribute disproportionately to losses.

## [get_predefined_scenario()](concepts/func:parrot_tools.quant.stress_testing.get_predefin-17e97f06.md)

Get a predefined stress scenario by name.

## [get_scenario_descriptions()](concepts/func:parrot_tools.quant.stress_testing.get_scenario-3c5e3556.md)

Get descriptions for all predefined scenarios.

## [list_predefined_scenarios()](concepts/func:parrot_tools.quant.stress_testing.list_predefi-0f866571.md)

List all available predefined scenario names.

## [stress_test_portfolio()](concepts/func:parrot_tools.quant.stress_testing.stress_test_portfolio.md)

Apply stress scenarios to a portfolio and estimate losses.

## [summarize_stress_results()](concepts/func:parrot_tools.quant.stress_testing.summarize_st-8f5d55a6.md)

Generate a human-readable summary of stress test results.

## [classify_term_structure()](concepts/func:parrot_tools.quant.volatility.classify_term_structure.md)

Classify volatility term structure shape.

## [compute_iv_rv_spread()](concepts/func:parrot_tools.quant.volatility.compute_iv_rv_spread.md)

Compute IV vs RV spread and classify the regime.

## [compute_realized_volatility()](concepts/func:parrot_tools.quant.volatility.compute_realized-676fe198.md)

Compute rolling realized volatility.

## [compute_volatility_cone()](concepts/func:parrot_tools.quant.volatility.compute_volatility_cone.md)

Compute percentile ranks of current volatility across multiple windows.

## [compute_volatility_single()](concepts/func:parrot_tools.quant.volatility.compute_volatility_single.md)

Compute single volatility value from returns.

## [compute_volatility_term_structure()](concepts/func:parrot_tools.quant.volatility.compute_volatili-c9c0b5be.md)

Compute volatility across different time horizons.

## [interpret_iv_rv_spread()](concepts/func:parrot_tools.quant.volatility.interpret_iv_rv_spread.md)

Interpret IV/RV spread results.

## [interpret_volatility_cone()](concepts/func:parrot_tools.quant.volatility.interpret_volatility_cone.md)

Interpret volatility cone results.

## [get_model_from_collection()](concepts/func:parrot_tools.querytoolkit.get_model_from_collection.md)

Extract the individual record model from a collection container model.

## [is_collection_model()](concepts/func:parrot_tools.querytoolkit.is_collection_model.md)

Determine if a BaseModel is a collection container (single instance with records field)

## [safe_author()](concepts/func:parrot_tools.reddit.safe_author.md)

Safely get author name, handling deleted users.

## [utc_iso()](concepts/func:parrot_tools.reddit.utc_iso.md)

Convert a timestamp to an ISO 8601 string (UTC).

## [extract_text()](concepts/func:parrot_tools.rss.fetcher.extract_text.md)

Extract the main readable text from an HTML page.

## [is_item_id()](concepts/func:parrot_tools.rss.models.is_item_id.md)

Check whether a string looks like an item id produced by :func:`make_item_id`.

## [make_item_id()](concepts/func:parrot_tools.rss.models.make_item_id.md)

Derive a stable item identifier from an article link.

## [create_sandbox_tool()](concepts/func:parrot_tools.sandboxtool.create_sandbox_tool.md)

Factory function to create gVisor tools.

## [exec_conditional()](concepts/func:parrot_tools.scraping.advanced_actions.exec_conditional.md)

Execute a :class:`Conditional` action.

## [exec_loop()](concepts/func:parrot_tools.scraping.advanced_actions.exec_loop.md)

Execute a :class:`Loop` action.

## [substitute_template_vars()](concepts/func:parrot_tools.scraping.advanced_actions.substit-8f682adc.md)

Recursively substitute loop template variables in *value*.

## [driver_context()](concepts/func:parrot_tools.scraping.driver_context.driver_context.md)

Async context manager that yields a browser driver.

## [execute_plan_steps()](concepts/func:parrot_tools.scraping.executor.execute_plan_steps.md)

Execute a scraping plan's steps against a browser driver.

## [create_action()](concepts/func:parrot_tools.scraping.models.create_action.md)

Factory function to create actions by type name

## [example_ecommerce_scraping()](concepts/func:parrot_tools.scraping.orchestrator.example_eco-472f330f.md)

Example: Scraping product information from e-commerce sites

## [example_news_monitoring()](concepts/func:parrot_tools.scraping.orchestrator.example_new-ba4fced3.md)

Example: Monitor news sites for specific topics

## [extract_price_number()](concepts/func:parrot_tools.scraping.orchestrator.extract_price_number.md)

Helper function to extract numeric price from text

## [integrate_with_knowledge_base()](concepts/func:parrot_tools.scraping.orchestrator.integrate_w-6eb6d0cb.md)

Example of full integration with AI-parrot knowledge base

## [fetch_snapshot()](concepts/func:parrot_tools.scraping.page_snapshot.fetch_snapshot.md)

Fetch a URL via ``aiohttp`` and build a ``PageSnapshot``.

## [snapshot_from_driver()](concepts/func:parrot_tools.scraping.page_snapshot.snapshot_f-bb420bb5.md)

Build a ``PageSnapshot`` from a live AbstractDriver (Selenium or Playwright).

## [snapshot_from_html()](concepts/func:parrot_tools.scraping.page_snapshot.snapshot_from_html.md)

Build a ``PageSnapshot`` from raw HTML without any network call.

## [load_plan_from_disk()](concepts/func:parrot_tools.scraping.plan_io.load_plan_from_disk.md)

Load a ScrapingPlan from a JSON file on disk.

## [save_plan_to_disk()](concepts/func:parrot_tools.scraping.plan_io.save_plan_to_disk.md)

Save a ScrapingPlan to disk following the naming convention.

## [normalize_url()](concepts/func:parrot_tools.scraping.url_utils.normalize_url.md)

Normalize a URL for deduplication.

## [parse_findings()](concepts/func:parrot_tools.security.advisory_engine.parse_findings.md)

Try to parse ``content`` into a list of SecurityFinding objects.

## [load_bytes()](concepts/func:parrot_tools.security.parsers._types.load_bytes.md)

Normalise content to bytes regardless of input type.

## [sort_findings()](concepts/func:parrot_tools.security.parsers._types.sort_findings.md)

Sort findings by severity desc, then finding_id asc (deterministic).

## [validate_section()](concepts/func:parrot_tools.security.parsers._types.validate_section.md)

Raise ValueError if section is not in the supported set.

## [get_report_parser()](concepts/func:parrot_tools.security.parsers.get_report_parser.md)

Return the parser registered for the given scanner name.

## [pop_persistence_kwargs()](concepts/func:parrot_tools.security.persistence.pop_persiste-86101aac.md)

Pop ``file_manager`` and ``report_store`` from a toolkit's ``**kwargs``.

## [create_think_tool()](concepts/func:parrot_tools.think.create_think_tool.md)

Factory function to create domain-specific ThinkTool instances.

## [integrate_whatif_tool()](concepts/func:parrot_tools.whatif.integrate_whatif_tool.md)

Integrate WhatIfTool into an existing PandasAgent.

## [validate_dict_or_json()](concepts/func:parrot_tools.whatif.validate_dict_or_json.md)

Validate that value is a dict, or parse it from JSON string

## [integrate_whatif_toolkit()](concepts/func:parrot_tools.whatif_toolkit.integrate_whatif_toolkit.md)

Integrate WhatIfToolkit into an agent.

## [parrot](summaries/mod:parrot.md)

Navigator Parrot.

## [parrot._imports](summaries/mod:parrot._imports.md)

Lazy Import Utility for AI-Parrot.

## [parrot.a2a](summaries/mod:parrot.a2a.md)

A2A (Agent-to-Agent) Protocol Implementation for AI-Parrot.

## [parrot.a2a.client](summaries/mod:parrot.a2a.client.md)

A2A Client - Connect to remote A2A agents from AI-Parrot.

## [parrot.a2a.mesh](summaries/mod:parrot.a2a.mesh.md)

A2A Mesh Discovery - Centralized service for discovering remote A2A agents.

## [parrot.a2a.mixin](summaries/mod:parrot.a2a.mixin.md)

A2A Client Mixin - Add A2A client capabilities to AI-Parrot agents.

## [parrot.a2a.models](summaries/mod:parrot.a2a.models.md)

A2A Protocol Data Models.

## [parrot.a2a.orchestrator](summaries/mod:parrot.a2a.orchestrator.md)

A2A Hybrid Orchestrator - Combines rule-based routing with LLM-driven orchestration.

## [parrot.a2a.push_notifications](summaries/mod:parrot.a2a.push_notifications.md)

Push notification configuration store for the A2A v1.0 server (FEAT-272).

## [parrot.a2a.router](summaries/mod:parrot.a2a.router.md)

A2A Proxy Router - Routes requests to remote A2A agents without LLM processing.

## [parrot.a2a.security](summaries/mod:parrot.a2a.security.md)

A2A Security - Authentication and authorization for agent-to-agent communication.

## [parrot.a2a.server](summaries/mod:parrot.a2a.server.md)

A2A Server - Wraps an AI-Parrot Agent as an A2A-compliant HTTP service.

## [parrot.advisors](summaries/mod:parrot.advisors.md)

Product Advisor - AI-powered product recommendation system.

## [parrot.advisors.catalog](summaries/mod:parrot.advisors.catalog.md)

Product Catalog module - Product storage and search.

## [parrot.advisors.catalog.catalog](summaries/mod:parrot.advisors.catalog.catalog.md)

ProductCatalog - Abstraction over PgVectorStore for product management.

## [parrot.advisors.catalog.loaders](summaries/mod:parrot.advisors.catalog.loaders.md)

Loaders for ingesting product data into ProductCatalog.

## [parrot.advisors.catalog.schema](summaries/mod:parrot.advisors.catalog.schema.md)

SQL Schema for Product Catalog with PgVector.

## [parrot.advisors.generator](summaries/mod:parrot.advisors.generator.md)

LLM-Powered Question Generator for Product Selection.

## [parrot.advisors.manager](summaries/mod:parrot.advisors.manager.md)

Module parrot.advisors.manager

## [parrot.advisors.mixin](summaries/mod:parrot.advisors.mixin.md)

Module parrot.advisors.mixin

## [parrot.advisors.models](summaries/mod:parrot.advisors.models.md)

Module parrot.advisors.models

## [parrot.advisors.questions](summaries/mod:parrot.advisors.questions.md)

Discriminant Question Generation for Product Selection.

## [parrot.advisors.state](summaries/mod:parrot.advisors.state.md)

Module parrot.advisors.state

## [parrot.advisors.tools](summaries/mod:parrot.advisors.tools.md)

Product Advisor Tools - Tools for guided product selection.

## [parrot.advisors.tools.base](summaries/mod:parrot.advisors.tools.base.md)

Base classes and utilities for Product Advisor Tools.

## [parrot.advisors.tools.compare](summaries/mod:parrot.advisors.tools.compare.md)

CompareProductsTool - Generates side-by-side product comparisons.

## [parrot.advisors.tools.criteria](summaries/mod:parrot.advisors.tools.criteria.md)

ApplyCriteriaTool - Applies user's answer to filter products.

## [parrot.advisors.tools.image](summaries/mod:parrot.advisors.tools.image.md)

ShowProductImageTool - Show product image on explicit request.

## [parrot.advisors.tools.question](summaries/mod:parrot.advisors.tools.question.md)

GetNextQuestionTool - Returns the next optimal question to ask.

## [parrot.advisors.tools.recommend](summaries/mod:parrot.advisors.tools.recommend.md)

RecommendProductTool - Generates a final product recommendation.

## [parrot.advisors.tools.search](summaries/mod:parrot.advisors.tools.search.md)

Product Search Tool - Direct product lookup and search.

## [parrot.advisors.tools.start](summaries/mod:parrot.advisors.tools.start.md)

StartSelectionTool - Initiates a product selection wizard session.

## [parrot.advisors.tools.state](summaries/mod:parrot.advisors.tools.state.md)

GetCurrentStateTool - Returns current selection state for transparency/debugging.

## [parrot.advisors.tools.undo](summaries/mod:parrot.advisors.tools.undo.md)

UndoSelectionTool - Reverts to the previous selection state (Memento pattern).

## [parrot.advisors.tools.utils](summaries/mod:parrot.advisors.tools.utils.md)

Shared utilities for Product Advisor tools.

## [parrot.advisors.version](summaries/mod:parrot.advisors.version.md)

AI-Parrot Advisors version information.

## [parrot.agents](summaries/mod:parrot.agents.md)

Parrot Agents - Core and Plugin Agents

## [parrot.agents.demo](summaries/mod:parrot.agents.demo.md)

HITL Demo Agent — Travel Concierge.

## [parrot.auth](summaries/mod:parrot.auth.md)

Authentication and authorization module for AI-Parrot.

## [parrot.auth.agent_guard](summaries/mod:parrot.auth.agent_guard.md)

Agent-level PBAC guard for bot resolution.

## [parrot.auth.audit](summaries/mod:parrot.auth.audit.md)

DEPRECATED: Use ``parrot.security.audit_ledger`` instead.

## [parrot.auth.broker](summaries/mod:parrot.auth.broker.md)

Surface-agnostic CredentialBroker and CredentialResolverFactory (FEAT-264).

## [parrot.auth.confirmation](summaries/mod:parrot.auth.confirmation.md)

Confirmation subsystem for per-call HITL tool-call review (FEAT-235).

## [parrot.auth.context](summaries/mod:parrot.auth.context.md)

Integration-agnostic per-user context.

## [parrot.auth.credentials](summaries/mod:parrot.auth.credentials.md)

Credential resolution abstractions for toolkits.

## [parrot.auth.dataplane_guard](summaries/mod:parrot.auth.dataplane_guard.md)

DataPlanePolicyGuard for FEAT-228 Data-Plane Authorization.

## [parrot.auth.dataset_guard](summaries/mod:parrot.auth.dataset_guard.md)

PBAC enforcement helper for DatasetManager.

## [parrot.auth.exceptions](summaries/mod:parrot.auth.exceptions.md)

Authentication and authorization exceptions for AI-Parrot.

## [parrot.auth.grants](summaries/mod:parrot.auth.grants.md)

Grant subsystem for bounded approval windows (FEAT-211).

## [parrot.auth.identity](summaries/mod:parrot.auth.identity.md)

Canonical identity mapper for cross-surface credential reuse.

## [parrot.auth.jira_oauth](summaries/mod:parrot.auth.jira_oauth.md)

Jira OAuth 2.0 (3LO) manager for per-user authentication.

## [parrot.auth.manifest](summaries/mod:parrot.auth.manifest.md)

In-package YAML manifest loader for per-agent credential configuration.

## [parrot.auth.models](summaries/mod:parrot.auth.models.md)

Policy Rule Configuration models for AI-Parrot PBAC.

## [parrot.auth.o365_oauth](summaries/mod:parrot.auth.o365_oauth.md)

Office 365 (Microsoft Graph) OAuth 2.0 manager with PKCE.

## [parrot.auth.oauth2](summaries/mod:parrot.auth.oauth2.md)

OAuth2 integration package for AI-Parrot.

## [parrot.auth.oauth2.jira_provider](summaries/mod:parrot.auth.oauth2.jira_provider.md)

Jira OAuth2 provider for the AI-Parrot integrations registry.

## [parrot.auth.oauth2.mcp_provider](summaries/mod:parrot.auth.oauth2.mcp_provider.md)

MCPOAuth2Provider — OAuth2 provider for MCP server connections.

## [parrot.auth.oauth2.models](summaries/mod:parrot.auth.oauth2.models.md)

Pydantic wire models for the OAuth2 integration layer.

## [parrot.auth.oauth2.o365_devicecode_provider](summaries/mod:parrot.auth.oauth2.o365_devicecode_provider.md)

O365 device-code (headless) credential resolver — FEAT-266.

## [parrot.auth.oauth2.o365_provider](summaries/mod:parrot.auth.oauth2.o365_provider.md)

Office365 OAuth2 provider for the AI-Parrot integrations registry.

## [parrot.auth.oauth2.persistence](summaries/mod:parrot.auth.oauth2.persistence.md)

DocumentDB persistence layer for the OAuth2 integration collections.

## [parrot.auth.oauth2.registry](summaries/mod:parrot.auth.oauth2.registry.md)

OAuth2 provider registry.

## [parrot.auth.oauth2.service](summaries/mod:parrot.auth.oauth2.service.md)

IntegrationsService — orchestration layer for the OAuth2 integration flows.

## [parrot.auth.oauth2.workiq_provider](summaries/mod:parrot.auth.oauth2.workiq_provider.md)

Work IQ OAuth2 provider with Entra On-Behalf-Of (OBO) token exchange.

## [parrot.auth.oauth2_base](summaries/mod:parrot.auth.oauth2_base.md)

Generic OAuth 2.0 / PKCE manager for AI-Parrot toolkits.

## [parrot.auth.oauth2_routes](summaries/mod:parrot.auth.oauth2_routes.md)

Generic OAuth 2.0 callback routes for AI-Parrot.

## [parrot.auth.pbac](summaries/mod:parrot.auth.pbac.md)

PBAC (Policy-Based Access Control) setup and initialization for AI-Parrot.

## [parrot.auth.permission](summaries/mod:parrot.auth.permission.md)

Permission data models for granular tool/toolkit access control.

## [parrot.auth.resolver](summaries/mod:parrot.auth.resolver.md)

Permission resolvers for granular tool/toolkit access control.

## [parrot.auth.rls_registry](summaries/mod:parrot.auth.rls_registry.md)

Row-Level Security (RLS) Registry for FEAT-228 Data-Plane Authorization.

## [parrot.auth.routes](summaries/mod:parrot.auth.routes.md)

HTTP routes for OAuth callbacks.

## [parrot.autonomous](summaries/mod:parrot.autonomous.md)

Autonomous orchestrator for AI-Parrot.

## [parrot.autonomous.admin](summaries/mod:parrot.autonomous.admin.md)

Admin login page for the Autonomous Orchestrator.

## [parrot.autonomous.cli](summaries/mod:parrot.autonomous.cli.md)

CLI commands for AutonomousOrchestrator deployment.

## [parrot.autonomous.deploy](summaries/mod:parrot.autonomous.deploy.md)

Deployment utilities for AutonomousOrchestrator.

## [parrot.autonomous.deploy.installer](summaries/mod:parrot.autonomous.deploy.installer.md)

Generates deployment configs for AutonomousOrchestrator agents.

## [parrot.autonomous.deploy.templates](summaries/mod:parrot.autonomous.deploy.templates.md)

String templates for AutonomousOrchestrator deployment artifacts.

## [parrot.autonomous.evb](summaries/mod:parrot.autonomous.evb.md)

Backward-compatible re-export of EventBus from the canonical location.

## [parrot.autonomous.example](summaries/mod:parrot.autonomous.example.md)

Module parrot.autonomous.example

## [parrot.autonomous.heartbeat](summaries/mod:parrot.autonomous.heartbeat.md)

Autonomous Agent Heartbeat.

## [parrot.autonomous.ledger](summaries/mod:parrot.autonomous.ledger.md)

Typed Event Ledger for the autonomous harness.

## [parrot.autonomous.orchestrator](summaries/mod:parrot.autonomous.orchestrator.md)

Autonomy Orchestrator for AI-Parrot.

## [parrot.autonomous.redis_jobs](summaries/mod:parrot.autonomous.redis_jobs.md)

Module parrot.autonomous.redis_jobs

## [parrot.autonomous.scheduler](summaries/mod:parrot.autonomous.scheduler.md)

Module parrot.autonomous.scheduler

## [parrot.autonomous.transport](summaries/mod:parrot.autonomous.transport.md)

Module parrot.autonomous.transport

## [parrot.autonomous.transport.base](summaries/mod:parrot.autonomous.transport.base.md)

Abstract base class for all multi-agent transports.

## [parrot.autonomous.transport.filesystem](summaries/mod:parrot.autonomous.transport.filesystem.md)

FilesystemTransport — zero-dependency local transport for multi-agent coordination.

## [parrot.autonomous.transport.filesystem.__main__](summaries/mod:parrot.autonomous.transport.filesystem.__main__.md)

Entry point for ``python -m parrot.autonomous.transport.filesystem``.

## [parrot.autonomous.transport.filesystem.channel](summaries/mod:parrot.autonomous.transport.filesystem.channel.md)

ChannelManager — broadcast channels via JSONL files.

## [parrot.autonomous.transport.filesystem.cli](summaries/mod:parrot.autonomous.transport.filesystem.cli.md)

CLI overlay for FilesystemTransport — human-in-the-loop observation and messaging.

## [parrot.autonomous.transport.filesystem.config](summaries/mod:parrot.autonomous.transport.filesystem.config.md)

Configuration model for FilesystemTransport.

## [parrot.autonomous.transport.filesystem.feed](summaries/mod:parrot.autonomous.transport.filesystem.feed.md)

ActivityFeed — global append-only JSONL event log.

## [parrot.autonomous.transport.filesystem.hook](summaries/mod:parrot.autonomous.transport.filesystem.hook.md)

FilesystemHook — integration with AI-Parrot's autonomous hooks system.

## [parrot.autonomous.transport.filesystem.inbox](summaries/mod:parrot.autonomous.transport.filesystem.inbox.md)

InboxManager — point-to-point message delivery via filesystem.

## [parrot.autonomous.transport.filesystem.registry](summaries/mod:parrot.autonomous.transport.filesystem.registry.md)

AgentRegistry — presence management via filesystem JSON files.

## [parrot.autonomous.transport.filesystem.reservation](summaries/mod:parrot.autonomous.transport.filesystem.reservation.md)

ReservationManager — cooperative resource reservations via filesystem.

## [parrot.autonomous.transport.filesystem.transport](summaries/mod:parrot.autonomous.transport.filesystem.transport.md)

FilesystemTransport — top-level orchestrator for filesystem-based multi-agent communication.

## [parrot.autonomous.webhooks](summaries/mod:parrot.autonomous.webhooks.md)

Module parrot.autonomous.webhooks

## [parrot.bots](summaries/mod:parrot.bots.md)

Module parrot.bots

## [parrot.bots._types](summaries/mod:parrot.bots._types.md)

Shared structural types for the ``parrot.bots`` package.

## [parrot.bots.a2a_agent](summaries/mod:parrot.bots.a2a_agent.md)

Module parrot.bots.a2a_agent

## [parrot.bots.abstract](summaries/mod:parrot.bots.abstract.md)

Abstract Bot interface.

## [parrot.bots.agent](summaries/mod:parrot.bots.agent.md)

Module parrot.bots.agent

## [parrot.bots.base](summaries/mod:parrot.bots.base.md)

BaseBot - Concrete implementation of AbstractBot.

## [parrot.bots.basic](summaries/mod:parrot.bots.basic.md)

Module parrot.bots.basic

## [parrot.bots.chatbot](summaries/mod:parrot.bots.chatbot.md)

Foundational base of every Chatbot and Agent in ai-parrot.

## [parrot.bots.data](summaries/mod:parrot.bots.data.md)

PandasAgent.

## [parrot.bots.database](summaries/mod:parrot.bots.database.md)

parrot.bots.database — Unified database agent with multi-toolkit architecture.

## [parrot.bots.database.agent](summaries/mod:parrot.bots.database.agent.md)

DatabaseAgent — LLM-backed unified agent with structured output.

## [parrot.bots.database.cache](summaries/mod:parrot.bots.database.cache.md)

Multi-database cache with partitioned namespaces.

## [parrot.bots.database.models](summaries/mod:parrot.bots.database.models.md)

Module parrot.bots.database.models

## [parrot.bots.database.prompts](summaries/mod:parrot.bots.database.prompts.md)

Database agent prompt layers and builder factory.

## [parrot.bots.database.retries](summaries/mod:parrot.bots.database.retries.md)

Query retry handling — generalized for multiple database types.

## [parrot.bots.database.router](summaries/mod:parrot.bots.database.router.md)

Module parrot.bots.database.router

## [parrot.bots.database.toolkits](summaries/mod:parrot.bots.database.toolkits.md)

Database toolkits — per-database-type tool collections.

## [parrot.bots.database.toolkits._crud](summaries/mod:parrot.bots.database.toolkits._crud.md)

Pure-function CRUD helpers for PostgresToolkit (FEAT-106).

## [parrot.bots.database.toolkits._internal](summaries/mod:parrot.bots.database.toolkits._internal.md)

DatabaseAgentToolkit — internal helper tools for DatabaseAgent.

## [parrot.bots.database.toolkits.base](summaries/mod:parrot.bots.database.toolkits.base.md)

DatabaseToolkit — abstract base for all database toolkits.

## [parrot.bots.database.toolkits.bigquery](summaries/mod:parrot.bots.database.toolkits.bigquery.md)

BigQueryToolkit — BigQuery-specific overrides of ``SQLToolkit``.

## [parrot.bots.database.toolkits.documentdb](summaries/mod:parrot.bots.database.toolkits.documentdb.md)

DocumentDBToolkit — MongoDB Query Language (MQL) support.

## [parrot.bots.database.toolkits.elastic](summaries/mod:parrot.bots.database.toolkits.elastic.md)

ElasticToolkit — Elasticsearch DSL query support.

## [parrot.bots.database.toolkits.influx](summaries/mod:parrot.bots.database.toolkits.influx.md)

InfluxDBToolkit — InfluxDB Flux query support.

## [parrot.bots.database.toolkits.postgres](summaries/mod:parrot.bots.database.toolkits.postgres.md)

PostgresToolkit — PostgreSQL-specific overrides of ``SQLToolkit``.

## [parrot.bots.database.toolkits.sql](summaries/mod:parrot.bots.database.toolkits.sql.md)

SQLToolkit — common SQL operations with overridable dialect hooks.

## [parrot.bots.document](summaries/mod:parrot.bots.document.md)

DocumentAgent - Specialized agent for document processing without Langchain.

## [parrot.bots.dynamic_values](summaries/mod:parrot.bots.dynamic_values.md)

Dynamic Value Provider Registry.

## [parrot.bots.factory](summaries/mod:parrot.bots.factory.md)

Agent Factory: orchestrator + specialist builders that generate, validate

## [parrot.bots.factory.contracts](summaries/mod:parrot.bots.factory.contracts.md)

Pydantic contracts for the Agent Factory subsystem.

## [parrot.bots.factory.orchestrator](summaries/mod:parrot.bots.factory.orchestrator.md)

AgentFactoryOrchestrator — the user-facing entry point of the factory.

## [parrot.bots.factory.tools](summaries/mod:parrot.bots.factory.tools.md)

Deterministic tools the Agent Factory builders invoke.

## [parrot.bots.factory.tools.finalize](summaries/mod:parrot.bots.factory.tools.finalize.md)

Finalize step — write the YAML and reload the registry.

## [parrot.bots.factory.tools.introspection](summaries/mod:parrot.bots.factory.tools.introspection.md)

Introspection helpers — the catalog the builders show to their LLM.

## [parrot.bots.factory.tools.openapi_register](summaries/mod:parrot.bots.factory.tools.openapi_register.md)

Register a third-party OpenAPI spec as a runtime-discoverable toolkit.

## [parrot.bots.factory.tools.vector_store](summaries/mod:parrot.bots.factory.tools.vector_store.md)

Provision a PgVector table for a RAG agent.

## [parrot.bots.flows](summaries/mod:parrot.bots.flows.md)

parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.

## [parrot.bots.flows.agents](summaries/mod:parrot.bots.flows.agents.md)

parrot.bots.flows.agents — orchestrator agents sub-package.

## [parrot.bots.flows.agents.a2a_orchestrator](summaries/mod:parrot.bots.flows.agents.a2a_orchestrator.md)

A2A-Enhanced Orchestrator Agent.

## [parrot.bots.flows.agents.hr](summaries/mod:parrot.bots.flows.agents.hr.md)

HR-specific orchestrator and crew factories.

## [parrot.bots.flows.agents.orchestrator](summaries/mod:parrot.bots.flows.agents.orchestrator.md)

Orchestrator agent for coordinating multiple specialized agents.

## [parrot.bots.flows.core](summaries/mod:parrot.bots.flows.core.md)

parrot.bots.flows.core — canonical public API for flow primitives.

## [parrot.bots.flows.core.context](summaries/mod:parrot.bots.flows.core.context.md)

Flow Primitives — FlowContext.

## [parrot.bots.flows.core.fsm](summaries/mod:parrot.bots.flows.core.fsm.md)

Flow Primitives — FSM Module.

## [parrot.bots.flows.core.node](summaries/mod:parrot.bots.flows.core.node.md)

Flow Primitives — Node Hierarchy.

## [parrot.bots.flows.core.result](summaries/mod:parrot.bots.flows.core.result.md)

Flow Primitives — Result Models.

## [parrot.bots.flows.core.storage](summaries/mod:parrot.bots.flows.core.storage.md)

Flow Primitives — Storage Sub-package.

## [parrot.bots.flows.core.storage.backends](summaries/mod:parrot.bots.flows.core.storage.backends.md)

Pluggable result-storage backends for AgentCrew and AgentsFlow (FEAT-147).

## [parrot.bots.flows.core.storage.backends.base](summaries/mod:parrot.bots.flows.core.storage.backends.base.md)

ResultStorage abstract base class for pluggable crew/flow result persistence.

## [parrot.bots.flows.core.storage.backends.documentdb](summaries/mod:parrot.bots.flows.core.storage.backends.documentdb.md)

DocumentDbResultStorage — default backend wrapping DocumentDb (FEAT-147).

## [parrot.bots.flows.core.storage.backends.factory](summaries/mod:parrot.bots.flows.core.storage.backends.factory.md)

Factory for resolving ResultStorage backends by name, instance, or env var.

## [parrot.bots.flows.core.storage.backends.postgres](summaries/mod:parrot.bots.flows.core.storage.backends.postgres.md)

PostgresResultStorage — Postgres backend for crew/flow execution results (FEAT-147).

## [parrot.bots.flows.core.storage.backends.redis](summaries/mod:parrot.bots.flows.core.storage.backends.redis.md)

RedisResultStorage — Redis backend for crew/flow execution results (FEAT-147).

## [parrot.bots.flows.core.storage.document](summaries/mod:parrot.bots.flows.core.storage.document.md)

CrewExecutionDocument — deterministic, LLM-free consolidated execution record.

## [parrot.bots.flows.core.storage.memory](summaries/mod:parrot.bots.flows.core.storage.memory.md)

Flow Primitives — ExecutionMemory.

## [parrot.bots.flows.core.storage.mixin](summaries/mod:parrot.bots.flows.core.storage.mixin.md)

Flow Primitives — VectorStoreMixin.

## [parrot.bots.flows.core.storage.persistence](summaries/mod:parrot.bots.flows.core.storage.persistence.md)

PersistenceMixin — pluggable persistence for crew/flow execution results (FEAT-147).

## [parrot.bots.flows.core.storage.synthesis](summaries/mod:parrot.bots.flows.core.storage.synthesis.md)

Flow Primitives — SynthesisMixin + synthesize_results util.

## [parrot.bots.flows.core.transition](summaries/mod:parrot.bots.flows.core.transition.md)

Flow Primitives — FlowTransition.

## [parrot.bots.flows.core.types](summaries/mod:parrot.bots.flows.core.types.md)

Flow Primitives — Types Module.

## [parrot.bots.flows.crew](summaries/mod:parrot.bots.flows.crew.md)

parrot.bots.flows.crew — AgentCrew sub-package.

## [parrot.bots.flows.crew.crew](summaries/mod:parrot.bots.flows.crew.crew.md)

AgentCrew — Parallel, Sequential, Flow, and Loop-Based Execution.

## [parrot.bots.flows.crew.nodes](summaries/mod:parrot.bots.flows.crew.nodes.md)

Crew-specific node type for AgentCrew orchestration.

## [parrot.bots.flows.crew.result_infographic](summaries/mod:parrot.bots.flows.crew.result_infographic.md)

Deterministic Tab-Assembly Helper for AgentCrew Infographic (FEAT-308).

## [parrot.bots.flows.crew.tool_node](summaries/mod:parrot.bots.flows.crew.tool_node.md)

ToolNode — deterministic tool execution node for AgentCrew.

## [parrot.bots.flows.flow](summaries/mod:parrot.bots.flows.flow.md)

parrot.bots.flows.flow -- AgentsFlow sub-package.

## [parrot.bots.flows.flow.actions](summaries/mod:parrot.bots.flows.flow.actions.md)

Action Registry — Lifecycle hooks for AgentsFlow nodes.

## [parrot.bots.flows.flow.cel_evaluator](summaries/mod:parrot.bots.flows.flow.cel_evaluator.md)

CEL Predicate Evaluator for AgentsFlow transition conditions.

## [parrot.bots.flows.flow.definition](summaries/mod:parrot.bots.flows.flow.definition.md)

FlowDefinition — Pydantic models for AgentsFlow JSON serialization.

## [parrot.bots.flows.flow.flow](summaries/mod:parrot.bots.flows.flow.flow.md)

AgentsFlow — DAG execution engine (FEAT-163).

## [parrot.bots.flows.flow.loader](summaries/mod:parrot.bots.flows.flow.loader.md)

FlowLoader — Load, save, and materialize FlowDefinition instances.

## [parrot.bots.flows.flow.nodes](summaries/mod:parrot.bots.flows.flow.nodes.md)

flows/flow/nodes.py — Decision + Interactive node types (FEAT-196 / TASK-1311).

## [parrot.bots.flows.flow.svelteflow](summaries/mod:parrot.bots.flows.flow.svelteflow.md)

SvelteFlow Adapter — bidirectional conversion for visual flow builders.

## [parrot.bots.flows.flow.telemetry](summaries/mod:parrot.bots.flows.flow.telemetry.md)

FlowLifecycleAdapter — bridge AgentsFlow scheduler events to FEAT-176.

## [parrot.bots.flows.result_agent](summaries/mod:parrot.bots.flows.result_agent.md)

ResultAgent — Registered Agent for Crew Infographic Rendering (FEAT-308).

## [parrot.bots.flows.tools](summaries/mod:parrot.bots.flows.tools.md)

Flow Tools — ResultRetrievalTool.

## [parrot.bots.github_reviewer](summaries/mod:parrot.bots.github_reviewer.md)

GitHub Code Reviewer agent.

## [parrot.bots.hrbot](summaries/mod:parrot.bots.hrbot.md)

Module parrot.bots.hrbot

## [parrot.bots.jira_specialist](summaries/mod:parrot.bots.jira_specialist.md)

Jira Specialist Agent with Daily Standup Workflow.

## [parrot.bots.kb](summaries/mod:parrot.bots.kb.md)

Module parrot.bots.kb

## [parrot.bots.mcp](summaries/mod:parrot.bots.mcp.md)

Simplified MCPAgent for backward compatibility.

## [parrot.bots.middleware](summaries/mod:parrot.bots.middleware.md)

Prompt middleware pipeline for query transformation.

## [parrot.bots.mixins](summaries/mod:parrot.bots.mixins.md)

Bot mixins package for AI-Parrot.

## [parrot.bots.mixins.intent_router](summaries/mod:parrot.bots.mixins.intent_router.md)

IntentRouterMixin — pre-RAG query routing for AI-Parrot bots.

## [parrot.bots.product](summaries/mod:parrot.bots.product.md)

Module parrot.bots.product

## [parrot.bots.prompts](summaries/mod:parrot.bots.prompts.md)

Collection of useful prompts for Chatbots.

## [parrot.bots.prompts.agent_context](summaries/mod:parrot.bots.prompts.agent_context.md)

AgentContextLoader and AGENT_CONTEXT_LAYER for provider-agnostic prompt caching.

## [parrot.bots.prompts.agents](summaries/mod:parrot.bots.prompts.agents.md)

Module parrot.bots.prompts.agents

## [parrot.bots.prompts.data](summaries/mod:parrot.bots.prompts.data.md)

Module parrot.bots.prompts.data

## [parrot.bots.prompts.domain_layers](summaries/mod:parrot.bots.prompts.domain_layers.md)

Domain-specific prompt layers.

## [parrot.bots.prompts.layers](summaries/mod:parrot.bots.prompts.layers.md)

Composable prompt layer system.

## [parrot.bots.prompts.output_generation](summaries/mod:parrot.bots.prompts.output_generation.md)

Module parrot.bots.prompts.output_generation

## [parrot.bots.prompts.presets](summaries/mod:parrot.bots.prompts.presets.md)

Preset registry for common PromptBuilder configurations.

## [parrot.bots.prompts.segments](summaries/mod:parrot.bots.prompts.segments.md)

CacheableSegment dataclass for provider-agnostic prompt caching.

## [parrot.bots.scraper](summaries/mod:parrot.bots.scraper.md)

Module parrot.bots.scraper

## [parrot.bots.scraper.models](summaries/mod:parrot.bots.scraper.models.md)

Module parrot.bots.scraper.models

## [parrot.bots.scraper.scraper](summaries/mod:parrot.bots.scraper.scraper.md)

ScrapingAgent for AI-Parrot

## [parrot.bots.scraper.templates](summaries/mod:parrot.bots.scraper.templates.md)

Module parrot.bots.scraper.templates

## [parrot.bots.search](summaries/mod:parrot.bots.search.md)

WebSearchAgent implementation for the ai-parrot framework.

## [parrot.bots.stores](summaries/mod:parrot.bots.stores.md)

Module parrot.bots.stores

## [parrot.bots.stores.local](summaries/mod:parrot.bots.stores.local.md)

LocalKBMixin: Mixin to add local markdown KB support to agents.

## [parrot.bots.voice](summaries/mod:parrot.bots.voice.md)

VoiceBot - Bot implementation with voice interaction capabilities.

## [parrot.cli](summaries/mod:parrot.cli.md)

Top-level CLI entrypoint for Parrot utilities.

## [parrot.cli.agent_repl](summaries/mod:parrot.cli.agent_repl.md)

Click command entry point for the AI-Parrot agent REPL.

## [parrot.cli.commands](summaries/mod:parrot.cli.commands.md)

Slash command dispatcher and built-in commands for the AI-Parrot agent REPL.

## [parrot.cli.identity](summaries/mod:parrot.cli.identity.md)

CLI identity bootstrap for the O365 device-code broker seam (FEAT-266).

## [parrot.cli.loaders](summaries/mod:parrot.cli.loaders.md)

Agent loading strategies for the AI-Parrot CLI REPL.

## [parrot.cli.renderer](summaries/mod:parrot.cli.renderer.md)

Response renderer for AI-Parrot CLI agent REPL.

## [parrot.cli.repl](summaries/mod:parrot.cli.repl.md)

REPL engine for the AI-Parrot agent CLI.

## [parrot.cli.tool_worker](summaries/mod:parrot.cli.tool_worker.md)

Worker-side entrypoint for remote tool execution.

## [parrot.clients](summaries/mod:parrot.clients.md)

Client for Interactions with LLMs (Language Models)

## [parrot.clients.anthropic_backends](summaries/mod:parrot.clients.anthropic_backends.md)

Composable backend strategy objects for AnthropicClient (FEAT-232).

## [parrot.clients.base](summaries/mod:parrot.clients.base.md)

Module parrot.clients.base

## [parrot.clients.bedrock](summaries/mod:parrot.clients.bedrock.md)

Native AWS Bedrock Converse API client for AI-Parrot (FEAT-302).

## [parrot.clients.claude](summaries/mod:parrot.clients.claude.md)

Module parrot.clients.claude

## [parrot.clients.claude_agent](summaries/mod:parrot.clients.claude_agent.md)

ClaudeAgentClient — dispatch tasks to Claude Code agents via the agent SDK.

## [parrot.clients.factory](summaries/mod:parrot.clients.factory.md)

Module parrot.clients.factory

## [parrot.clients.gemma4](summaries/mod:parrot.clients.gemma4.md)

Gemma4Client for ai-parrot framework.

## [parrot.clients.google](summaries/mod:parrot.clients.google.md)

Module parrot.clients.google

## [parrot.clients.google.analysis](summaries/mod:parrot.clients.google.analysis.md)

Module parrot.clients.google.analysis

## [parrot.clients.google.client](summaries/mod:parrot.clients.google.client.md)

Module parrot.clients.google.client

## [parrot.clients.google.generation](summaries/mod:parrot.clients.google.generation.md)

Module parrot.clients.google.generation

## [parrot.clients.gpt](summaries/mod:parrot.clients.gpt.md)

Module parrot.clients.gpt

## [parrot.clients.grok](summaries/mod:parrot.clients.grok.md)

Module parrot.clients.grok

## [parrot.clients.groq](summaries/mod:parrot.clients.groq.md)

Module parrot.clients.groq

## [parrot.clients.hf](summaries/mod:parrot.clients.hf.md)

TransformersClient for ai-parrot framework.

## [parrot.clients.live](summaries/mod:parrot.clients.live.md)

GeminiLiveClient - Live/Realtime API Client for AI-Parrot

## [parrot.clients.localllm](summaries/mod:parrot.clients.localllm.md)

LocalLLM client for AI-Parrot.

## [parrot.clients.models](summaries/mod:parrot.clients.models.md)

Module parrot.clients.models

## [parrot.clients.nova_sonic](summaries/mod:parrot.clients.nova_sonic.md)

Amazon Nova 2 Sonic experimental bidirectional voice client (FEAT-302).

## [parrot.clients.nvidia](summaries/mod:parrot.clients.nvidia.md)

Nvidia NIM client for AI-Parrot.

## [parrot.clients.openrouter](summaries/mod:parrot.clients.openrouter.md)

OpenRouter client for AI-Parrot.

## [parrot.clients.vllm](summaries/mod:parrot.clients.vllm.md)

vLLM client for AI-Parrot.

## [parrot.clients.zai](summaries/mod:parrot.clients.zai.md)

Module parrot.clients.zai

## [parrot.conf](summaries/mod:parrot.conf.md)

Module parrot.conf

## [parrot.core](summaries/mod:parrot.core.md)

Shared infrastructure for AI-Parrot.

## [parrot.core.events](summaries/mod:parrot.core.events.md)

Event bus infrastructure for AI-Parrot.

## [parrot.core.events.evb](summaries/mod:parrot.core.events.evb.md)

Module parrot.core.events.evb

## [parrot.core.events.lifecycle](summaries/mod:parrot.core.events.lifecycle.md)

Lifecycle Events System — typed, frozen, observability-first events.

## [parrot.core.events.lifecycle.base](summaries/mod:parrot.core.events.lifecycle.base.md)

Abstract base class for all lifecycle events.

## [parrot.core.events.lifecycle.events](summaries/mod:parrot.core.events.lifecycle.events.md)

Re-exports for all concrete lifecycle event classes.

## [parrot.core.events.lifecycle.events.agent](summaries/mod:parrot.core.events.lifecycle.events.agent.md)

Agent lifecycle events.

## [parrot.core.events.lifecycle.events.client](summaries/mod:parrot.core.events.lifecycle.events.client.md)

LLM Client lifecycle events.

## [parrot.core.events.lifecycle.events.flow](summaries/mod:parrot.core.events.lifecycle.events.flow.md)

Flow / node orchestration lifecycle events.

## [parrot.core.events.lifecycle.events.invoke](summaries/mod:parrot.core.events.lifecycle.events.invoke.md)

Invocation lifecycle events.

## [parrot.core.events.lifecycle.events.message](summaries/mod:parrot.core.events.lifecycle.events.message.md)

Message lifecycle events.

## [parrot.core.events.lifecycle.events.tool](summaries/mod:parrot.core.events.lifecycle.events.tool.md)

Tool lifecycle events.

## [parrot.core.events.lifecycle.global_registry](summaries/mod:parrot.core.events.lifecycle.global_registry.md)

Global registry singleton and scope() context manager.

## [parrot.core.events.lifecycle.legacy_bridge](summaries/mod:parrot.core.events.lifecycle.legacy_bridge.md)

_LegacyEventBridge — routes new typed events back to legacy _listeners callbacks.

## [parrot.core.events.lifecycle.meta](summaries/mod:parrot.core.events.lifecycle.meta.md)

Meta-events for error isolation (model B).

## [parrot.core.events.lifecycle.mixin](summaries/mod:parrot.core.events.lifecycle.mixin.md)

EventEmitterMixin — uniform self.events interface for AbstractBot, AbstractClient, AbstractTool.

## [parrot.core.events.lifecycle.provider](summaries/mod:parrot.core.events.lifecycle.provider.md)

EventProvider Protocol for batch subscriber registration.

## [parrot.core.events.lifecycle.registry](summaries/mod:parrot.core.events.lifecycle.registry.md)

EventRegistry: typed lifecycle event dispatch with error isolation.

## [parrot.core.events.lifecycle.subscribers](summaries/mod:parrot.core.events.lifecycle.subscribers.md)

Built-in lifecycle event subscribers.

## [parrot.core.events.lifecycle.subscribers.logging](summaries/mod:parrot.core.events.lifecycle.subscribers.logging.md)

LoggingSubscriber — logs every LifecycleEvent via the standard logging framework.

## [parrot.core.events.lifecycle.subscribers.opentelemetry](summaries/mod:parrot.core.events.lifecycle.subscribers.opentelemetry.md)

OpenTelemetrySubscriber — maps LifecycleEvents to OTel spans.

## [parrot.core.events.lifecycle.subscribers.webhook](summaries/mod:parrot.core.events.lifecycle.subscribers.webhook.md)

WebhookSubscriber — HTTP POST lifecycle events to an external endpoint.

## [parrot.core.events.lifecycle.trace](summaries/mod:parrot.core.events.lifecycle.trace.md)

W3C Trace Context dataclass for lifecycle event propagation.

## [parrot.core.events.lifecycle.yaml_loader](summaries/mod:parrot.core.events.lifecycle.yaml_loader.md)

YAML declarative events block parser and wiring helper.

## [parrot.core.exceptions](summaries/mod:parrot.core.exceptions.md)

Exception Definitions for Parrot Core.

## [parrot.core.hooks](summaries/mod:parrot.core.hooks.md)

External hooks system for AutonomousOrchestrator.

## [parrot.core.hooks.base](summaries/mod:parrot.core.hooks.base.md)

Abstract base class for all external hooks.

## [parrot.core.hooks.brokers](summaries/mod:parrot.core.hooks.brokers.md)

Broker hooks sub-package.

## [parrot.core.hooks.brokers.base](summaries/mod:parrot.core.hooks.brokers.base.md)

Abstract base class for message broker hooks.

## [parrot.core.hooks.brokers.mqtt](summaries/mod:parrot.core.hooks.brokers.mqtt.md)

MQTT broker hook.

## [parrot.core.hooks.brokers.rabbitmq](summaries/mod:parrot.core.hooks.brokers.rabbitmq.md)

RabbitMQ broker hook.

## [parrot.core.hooks.brokers.redis](summaries/mod:parrot.core.hooks.brokers.redis.md)

Redis Streams broker hook.

## [parrot.core.hooks.brokers.sqs](summaries/mod:parrot.core.hooks.brokers.sqs.md)

AWS SQS broker hook.

## [parrot.core.hooks.file_upload](summaries/mod:parrot.core.hooks.file_upload.md)

File upload hook — HTTP POST/PUT endpoint for file ingestion.

## [parrot.core.hooks.file_watchdog](summaries/mod:parrot.core.hooks.file_watchdog.md)

File watchdog hook — reacts to filesystem changes.

## [parrot.core.hooks.github_webhook](summaries/mod:parrot.core.hooks.github_webhook.md)

GitHub webhook hook — receives and parses GitHub pull_request events.

## [parrot.core.hooks.imap](summaries/mod:parrot.core.hooks.imap.md)

IMAP watchdog hook — async email monitoring with optional tagged filtering.

## [parrot.core.hooks.jira_webhook](summaries/mod:parrot.core.hooks.jira_webhook.md)

Jira webhook hook — receives and parses Jira issue events.

## [parrot.core.hooks.manager](summaries/mod:parrot.core.hooks.manager.md)

HookManager — registry and lifecycle coordinator for all hooks.

## [parrot.core.hooks.matrix](summaries/mod:parrot.core.hooks.matrix.md)

Matrix protocol hook for AutonomousOrchestrator.

## [parrot.core.hooks.messaging](summaries/mod:parrot.core.hooks.messaging.md)

Messaging platform hooks — Telegram, WhatsApp, MS Teams.

## [parrot.core.hooks.mixins](summaries/mod:parrot.core.hooks.mixins.md)

HookableAgent mixin — adds hook support to any agent or handler.

## [parrot.core.hooks.models](summaries/mod:parrot.core.hooks.models.md)

Pydantic models and configuration for the hooks system.

## [parrot.core.hooks.postgres](summaries/mod:parrot.core.hooks.postgres.md)

PostgreSQL LISTEN/NOTIFY hook.

## [parrot.core.hooks.scheduler](summaries/mod:parrot.core.hooks.scheduler.md)

Scheduler hook — periodic agent triggers via APScheduler.

## [parrot.core.hooks.sharepoint](summaries/mod:parrot.core.hooks.sharepoint.md)

SharePoint webhook hook — Microsoft Graph API subscription management.

## [parrot.core.hooks.whatsapp_redis](summaries/mod:parrot.core.hooks.whatsapp_redis.md)

WhatsApp Redis Bridge Hook.

## [parrot.core.tools](summaries/mod:parrot.core.tools.md)

Parrot Core Tools.

## [parrot.core.tools.handoff](summaries/mod:parrot.core.tools.handoff.md)

Handoff Tool implementation for Parrot Core.

## [parrot.core.ws_auth](summaries/mod:parrot.core.ws_auth.md)

WebSocket / token authentication infrastructure.

## [parrot.embeddings](summaries/mod:parrot.embeddings.md)

Module parrot.embeddings

## [parrot.embeddings.base](summaries/mod:parrot.embeddings.base.md)

Module parrot.embeddings.base

## [parrot.embeddings.catalog](summaries/mod:parrot.embeddings.catalog.md)

Curated catalog of supported embedding models.

## [parrot.embeddings.google](summaries/mod:parrot.embeddings.google.md)

Module parrot.embeddings.google

## [parrot.embeddings.huggingface](summaries/mod:parrot.embeddings.huggingface.md)

Module parrot.embeddings.huggingface

## [parrot.embeddings.matryoshka](summaries/mod:parrot.embeddings.matryoshka.md)

Matryoshka Representation Learning (MRL) truncation configuration.

## [parrot.embeddings.multimodal](summaries/mod:parrot.embeddings.multimodal.md)

Multimodal Embedding Provider package.

## [parrot.embeddings.multimodal.base](summaries/mod:parrot.embeddings.multimodal.base.md)

Multimodal Embedding Base ABC & Supporting Types.

## [parrot.embeddings.multimodal.quantization](summaries/mod:parrot.embeddings.multimodal.quantization.md)

Quantization and Matryoshka post-processing utilities.

## [parrot.embeddings.multimodal.uform](summaries/mod:parrot.embeddings.multimodal.uform.md)

UForm Embedding Provider.

## [parrot.embeddings.openai](summaries/mod:parrot.embeddings.openai.md)

Module parrot.embeddings.openai

## [parrot.embeddings.processor](summaries/mod:parrot.embeddings.processor.md)

Module parrot.embeddings.processor

## [parrot.embeddings.registry](summaries/mod:parrot.embeddings.registry.md)

EmbeddingRegistry — Process-wide singleton for embedding model caching.

## [parrot.embeddings.version](summaries/mod:parrot.embeddings.version.md)

AI-Parrot Embeddings Meta information.

## [parrot.eval](summaries/mod:parrot.eval.md)

Generic Agent Evaluation Harness — public surface.

## [parrot.eval.datasets](summaries/mod:parrot.eval.datasets.md)

Dataset loaders for the Generic Agent Evaluation Harness.

## [parrot.eval.evaluators](summaries/mod:parrot.eval.evaluators.md)

Evaluators subpackage for the Generic Agent Evaluation Harness.

## [parrot.eval.evaluators.base](summaries/mod:parrot.eval.evaluators.base.md)

Abstract base classes for evaluation metrics and evaluators.

## [parrot.eval.evaluators.state_based](summaries/mod:parrot.eval.evaluators.state_based.md)

State-based evaluator and metric for the Generic Agent Evaluation Harness.

## [parrot.eval.events](summaries/mod:parrot.eval.events.md)

Eval lifecycle events for the Generic Agent Evaluation Harness.

## [parrot.eval.models](summaries/mod:parrot.eval.models.md)

Pydantic v2 data models for the Generic Agent Evaluation Harness.

## [parrot.eval.registry](summaries/mod:parrot.eval.registry.md)

Lightweight decorator registries for evaluators and metrics.

## [parrot.eval.rollout](summaries/mod:parrot.eval.rollout.md)

Rollout strategies and user simulators for the Generic Agent Evaluation Harness.

## [parrot.eval.runner](summaries/mod:parrot.eval.runner.md)

EvalRunner + EvalReport for the Generic Agent Evaluation Harness.

## [parrot.eval.sandbox](summaries/mod:parrot.eval.sandbox.md)

Sandbox subpackage for the Generic Agent Evaluation Harness.

## [parrot.eval.sandbox.base](summaries/mod:parrot.eval.sandbox.base.md)

Sandbox ABCs and NoopSandbox for the Generic Agent Evaluation Harness.

## [parrot.eval.sandbox.fakes](summaries/mod:parrot.eval.sandbox.fakes.md)

Fake driver implementations for the Generic Agent Evaluation Harness.

## [parrot.eval.sandbox.state](summaries/mod:parrot.eval.sandbox.state.md)

State-based sandbox components for the Generic Agent Evaluation Harness.

## [parrot.eval.sink](summaries/mod:parrot.eval.sink.md)

Persistence sinks for the Generic Agent Evaluation Harness.

## [parrot.exceptions](summaries/mod:parrot.exceptions.md)

Parrot exception hierarchy.

## [parrot.flows](summaries/mod:parrot.flows.md)

Application-level flows for AI-Parrot.

## [parrot.flows.dev_loop](summaries/mod:parrot.flows.dev_loop.md)

Dev-loop orchestration flow (FEAT-129).

## [parrot.flows.dev_loop._subagent_defs](summaries/mod:parrot.flows.dev_loop._subagent_defs.md)

Loader for SDD subagent definitions used by the dev-loop dispatcher.

## [parrot.flows.dev_loop.code_review](summaries/mod:parrot.flows.dev_loop.code_review.md)

AbstractCodeReviewDispatcher ABC + factory (FEAT-270).

## [parrot.flows.dev_loop.config](summaries/mod:parrot.flows.dev_loop.config.md)

Dev-loop configuration helpers (FEAT-253).

## [parrot.flows.dev_loop.definition](summaries/mod:parrot.flows.dev_loop.definition.md)

Declarative dev-loop topology — ``FlowDefinition`` authoring (FEAT-250 G1).

## [parrot.flows.dev_loop.dispatcher](summaries/mod:parrot.flows.dev_loop.dispatcher.md)

ClaudeCodeDispatcher — orchestration glue between AgentsFlow and Claude Code.

## [parrot.flows.dev_loop.factories](summaries/mod:parrot.flows.dev_loop.factories.md)

Node factories that bind live dependencies into the declarative dev-loop.

## [parrot.flows.dev_loop.flow](summaries/mod:parrot.flows.dev_loop.flow.md)

build_dev_loop_flow — wire the eight dev-loop nodes into an AgentsFlow.

## [parrot.flows.dev_loop.models](summaries/mod:parrot.flows.dev_loop.models.md)

Pydantic v2 contracts for the dev-loop orchestration flow (FEAT-129).

## [parrot.flows.dev_loop.nodes](summaries/mod:parrot.flows.dev_loop.nodes.md)

Six flow nodes for the dev-loop orchestration (FEAT-129, FEAT-132).

## [parrot.flows.dev_loop.nodes.base](summaries/mod:parrot.flows.dev_loop.nodes.base.md)

DevLoopNode — shared base for the dev-loop flow nodes.

## [parrot.flows.dev_loop.nodes.bug_intake](summaries/mod:parrot.flows.dev_loop.nodes.bug_intake.md)

BugIntakeNode — bug-specific intake hook for the dev-loop flow.

## [parrot.flows.dev_loop.nodes.close](summaries/mod:parrot.flows.dev_loop.nodes.close.md)

DevLoopCloseNode — terminal node that records a run's final state.

## [parrot.flows.dev_loop.nodes.deployment_handoff](summaries/mod:parrot.flows.dev_loop.nodes.deployment_handoff.md)

DeploymentHandoffNode — push, open PR, transition Jira.

## [parrot.flows.dev_loop.nodes.development](summaries/mod:parrot.flows.dev_loop.nodes.development.md)

DevelopmentNode — sdd-worker dispatch.

## [parrot.flows.dev_loop.nodes.failure_handler](summaries/mod:parrot.flows.dev_loop.nodes.failure_handler.md)

FailureHandlerNode — Jira escalation on flow failure.

## [parrot.flows.dev_loop.nodes.intent_classifier](summaries/mod:parrot.flows.dev_loop.nodes.intent_classifier.md)

IntentClassifierNode — first node of the dev-loop flow (FEAT-132).

## [parrot.flows.dev_loop.nodes.qa](summaries/mod:parrot.flows.dev_loop.nodes.qa.md)

QANode — sdd-qa dispatch in plan mode + pluggable code-review gate.

## [parrot.flows.dev_loop.nodes.research](summaries/mod:parrot.flows.dev_loop.nodes.research.md)

ResearchNode — bug triage, Jira ticket, sdd-research dispatch.

## [parrot.flows.dev_loop.nodes.revision_handoff](summaries/mod:parrot.flows.dev_loop.nodes.revision_handoff.md)

RevisionHandoffNode — push to the existing branch + comment the same PR.

## [parrot.flows.dev_loop.runner](summaries/mod:parrot.flows.dev_loop.runner.md)

DevLoopRunner — orchestrator-side hosting for the dev-loop flow.

## [parrot.flows.dev_loop.streaming](summaries/mod:parrot.flows.dev_loop.streaming.md)

FlowStreamMultiplexer — aiohttp WebSocket fan-in for two Redis streams.

## [parrot.flows.dev_loop.webhook](summaries/mod:parrot.flows.dev_loop.webhook.md)

GitHub ``pull_request.closed`` webhook for worktree cleanup.

## [parrot.forms](summaries/mod:parrot.forms.md)

Universal Form Abstraction Layer for AI-Parrot.

## [parrot.forms.cache](summaries/mod:parrot.forms.cache.md)

Form Cache for the forms abstraction layer.

## [parrot.forms.constraints](summaries/mod:parrot.forms.constraints.md)

Field constraints and conditional visibility rules for form fields.

## [parrot.forms.extractors](summaries/mod:parrot.forms.extractors.md)

Form schema extractors for the forms abstraction layer.

## [parrot.forms.extractors.jsonschema](summaries/mod:parrot.forms.extractors.jsonschema.md)

JSON Schema extractor for FormSchema generation.

## [parrot.forms.extractors.pydantic](summaries/mod:parrot.forms.extractors.pydantic.md)

Pydantic model extractor for FormSchema generation.

## [parrot.forms.extractors.tool](summaries/mod:parrot.forms.extractors.tool.md)

Tool extractor for FormSchema generation from AbstractTool instances.

## [parrot.forms.extractors.yaml](summaries/mod:parrot.forms.extractors.yaml.md)

YAML extractor for FormSchema generation.

## [parrot.forms.options](summaries/mod:parrot.forms.options.md)

Field option definitions for select and multi-select fields.

## [parrot.forms.registry](summaries/mod:parrot.forms.registry.md)

Form Registry for the forms abstraction layer.

## [parrot.forms.renderers](summaries/mod:parrot.forms.renderers.md)

Form renderers for the forms abstraction layer.

## [parrot.forms.renderers.adaptive_card](summaries/mod:parrot.forms.renderers.adaptive_card.md)

Adaptive Card renderer for FormSchema.

## [parrot.forms.renderers.base](summaries/mod:parrot.forms.renderers.base.md)

Abstract base class for form renderers.

## [parrot.forms.renderers.html5](summaries/mod:parrot.forms.renderers.html5.md)

HTML5 form renderer for FormSchema.

## [parrot.forms.renderers.jsonschema](summaries/mod:parrot.forms.renderers.jsonschema.md)

JSON Schema renderer for FormSchema.

## [parrot.forms.schema](summaries/mod:parrot.forms.schema.md)

Core form schema data models.

## [parrot.forms.storage](summaries/mod:parrot.forms.storage.md)

PostgreSQL Form Storage for the forms abstraction layer.

## [parrot.forms.style](summaries/mod:parrot.forms.style.md)

Form presentation and layout style models.

## [parrot.forms.tools](summaries/mod:parrot.forms.tools.md)

Form tools for the forms abstraction layer.

## [parrot.forms.tools.create_form](summaries/mod:parrot.forms.tools.create_form.md)

CreateFormTool — LLM-driven form generation tool.

## [parrot.forms.tools.database_form](summaries/mod:parrot.forms.tools.database_form.md)

DatabaseFormTool — Load a form definition from PostgreSQL into a FormSchema.

## [parrot.forms.tools.request_form](summaries/mod:parrot.forms.tools.request_form.md)

RequestFormTool — platform-agnostic form request tool.

## [parrot.forms.types](summaries/mod:parrot.forms.types.md)

Core type definitions for the forms package.

## [parrot.forms.validators](summaries/mod:parrot.forms.validators.md)

Platform-agnostic form validation for FormSchema.

## [parrot.handlers](summaries/mod:parrot.handlers.md)

Parrot basic Handlers.

## [parrot.handlers.agent](summaries/mod:parrot.handlers.agent.md)

AgentTalk - HTTP Handler for Agent Conversations

## [parrot.handlers.agent_voice](summaries/mod:parrot.handlers.agent_voice.md)

HTTP handler for voice agent interaction (FEAT-231).

## [parrot.handlers.agents](summaries/mod:parrot.handlers.agents.md)

Module parrot.handlers.agents

## [parrot.handlers.agents.abstract](summaries/mod:parrot.handlers.agents.abstract.md)

Module parrot.handlers.agents.abstract

## [parrot.handlers.agents.data](summaries/mod:parrot.handlers.agents.data.md)

Module parrot.handlers.agents.data

## [parrot.handlers.agents.ephemeral](summaries/mod:parrot.handlers.agents.ephemeral.md)

HTTP handler for ephemeral user agent lifecycle (FEAT-149 TASK-1040).

## [parrot.handlers.agents.factory](summaries/mod:parrot.handlers.agents.factory.md)

HTTP handler for the AgentFactoryOrchestrator.

## [parrot.handlers.agents.sharing](summaries/mod:parrot.handlers.agents.sharing.md)

Agent sharing scaffold — deferred to a follow-up FEAT.

## [parrot.handlers.agents.users](summaries/mod:parrot.handlers.agents.users.md)

HTTP handler for user-defined bots — ``/api/v1/user_agents``.

## [parrot.handlers.artifacts](summaries/mod:parrot.handlers.artifacts.md)

REST handler for artifact CRUD.

## [parrot.handlers.avatar](summaries/mod:parrot.handlers.avatar.md)

Avatar session endpoint — start/stop/viewers for an avatar session (FEAT-242, FEAT-249).

## [parrot.handlers.avatar_fullmode](summaries/mod:parrot.handlers.avatar_fullmode.md)

FULL Mode avatar endpoint — start/stop sessions and list avatars/voices (FEAT-248).

## [parrot.handlers.bots](summaries/mod:parrot.handlers.bots.md)

Module parrot.handlers.bots

## [parrot.handlers.chat](summaries/mod:parrot.handlers.chat.md)

Module parrot.handlers.chat

## [parrot.handlers.chat_interaction](summaries/mod:parrot.handlers.chat_interaction.md)

REST handler for chat interaction persistence.

## [parrot.handlers.config_handler](summaries/mod:parrot.handlers.config_handler.md)

REST API Handler for BotConfig Management.

## [parrot.handlers.credentials](summaries/mod:parrot.handlers.credentials.md)

CredentialsHandler — CRUD HTTP view for user database credentials.

## [parrot.handlers.credentials_utils](summaries/mod:parrot.handlers.credentials_utils.md)

Backward-compatible redirect — credentials_utils relocated to parrot.security in FEAT-203.

## [parrot.handlers.crew](summaries/mod:parrot.handlers.crew.md)

Module parrot.handlers.crew

## [parrot.handlers.crew.execution_handler](summaries/mod:parrot.handlers.crew.execution_handler.md)

Module parrot.handlers.crew.execution_handler

## [parrot.handlers.crew.execution_history_handler](summaries/mod:parrot.handlers.crew.execution_history_handler.md)

REST API Handler for AgentCrew Saved Execution History (FEAT-307).

## [parrot.handlers.crew.handler](summaries/mod:parrot.handlers.crew.handler.md)

REST API Handler for AgentCrew Management.

## [parrot.handlers.crew.models](summaries/mod:parrot.handlers.crew.models.md)

Data models for AgentCrew API.

## [parrot.handlers.crew.redis_persistence](summaries/mod:parrot.handlers.crew.redis_persistence.md)

Redis Persistence for AgentsCrew Definitions.

## [parrot.handlers.crew.saved_execution_service](summaries/mod:parrot.handlers.crew.saved_execution_service.md)

SavedExecutionService — orchestration layer for execution history,

## [parrot.handlers.crew.special_nodes](summaries/mod:parrot.handlers.crew.special_nodes.md)

Curated special-node catalog for the crew builder UI.

## [parrot.handlers.crew.tool_catalog](summaries/mod:parrot.handlers.crew.tool_catalog.md)

Curated tool catalog for the crew builder UI.

## [parrot.handlers.csp](summaries/mod:parrot.handlers.csp.md)

Content-Security-Policy header builder for infographic HTML serving (FEAT-197).

## [parrot.handlers.dashboard_handler](summaries/mod:parrot.handlers.dashboard_handler.md)

REST API Handler for Dashboard Persistence.

## [parrot.handlers.database](summaries/mod:parrot.handlers.database.md)

Module parrot.handlers.database

## [parrot.handlers.database.helpers](summaries/mod:parrot.handlers.database.helpers.md)

HTTP handler exposing DatabaseAgent metadata for frontend interaction.

## [parrot.handlers.dataset_filter_handler](summaries/mod:parrot.handlers.dataset_filter_handler.md)

Dataset common-field filter HTTP handler and AgenTalk envelope (FEAT-225 Module 7).

## [parrot.handlers.datasets](summaries/mod:parrot.handlers.datasets.md)

HTTP handler for managing user's DatasetManager.

## [parrot.handlers.deeplink](summaries/mod:parrot.handlers.deeplink.md)

A2UI deep-link web resume route (FEAT-273 Module 8, web channel).

## [parrot.handlers.google_generation](summaries/mod:parrot.handlers.google_generation.md)

HTTP handler for Google multimodal generation workflows.

## [parrot.handlers.infographic](summaries/mod:parrot.handlers.infographic.md)

HTTP handler for get_infographic() generation, plus template and theme

## [parrot.handlers.integrations](summaries/mod:parrot.handlers.integrations.md)

HTTP handler for the OAuth2 integrations endpoints.

## [parrot.handlers.jobs](summaries/mod:parrot.handlers.jobs.md)

Module parrot.handlers.jobs

## [parrot.handlers.jobs.job](summaries/mod:parrot.handlers.jobs.job.md)

Job Manager for Asynchronous Crew Execution.

## [parrot.handlers.jobs.mixin](summaries/mod:parrot.handlers.jobs.mixin.md)

JobManagerMixin: A mixin class to add asynchronous job execution capabilities to views.

## [parrot.handlers.jobs.models](summaries/mod:parrot.handlers.jobs.models.md)

Module parrot.handlers.jobs.models

## [parrot.handlers.jobs.redis_store](summaries/mod:parrot.handlers.jobs.redis_store.md)

Redis-backed persistence layer for Job objects.

## [parrot.handlers.jobs.worker](summaries/mod:parrot.handlers.jobs.worker.md)

Worker / startup helpers for JobManager configuration.

## [parrot.handlers.knowledge](summaries/mod:parrot.handlers.knowledge.md)

HTTP handler to manage an agent's knowledge index (PageIndex / GraphIndex).

## [parrot.handlers.liveavatar_output](summaries/mod:parrot.handlers.liveavatar_output.md)

Server-side wiring for the Redis structured-output transport (FEAT-249).

## [parrot.handlers.llm](summaries/mod:parrot.handlers.llm.md)

LLMClient Handler - HTTP Interface for LLM Clients

## [parrot.handlers.lyria_music](summaries/mod:parrot.handlers.lyria_music.md)

HTTP handler for Lyria music generation.

## [parrot.handlers.mcp_helper](summaries/mod:parrot.handlers.mcp_helper.md)

MCP Helper HTTP Handler — discovery, activation, and management of MCP servers.

## [parrot.handlers.mcp_persistence](summaries/mod:parrot.handlers.mcp_persistence.md)

MCP Persistence Service — DocumentDB CRUD for user MCP server configs.

## [parrot.handlers.mediagen](summaries/mod:parrot.handlers.mediagen.md)

HTTP handler for Google Media Generation (Image and Video) via Google GenAI.

## [parrot.handlers.models](summaries/mod:parrot.handlers.models.md)

Handler models package.

## [parrot.handlers.models._encrypted_field](summaries/mod:parrot.handlers.models._encrypted_field.md)

Transparent AES-GCM encryption helpers for postgres TEXT columns.

## [parrot.handlers.models.bots](summaries/mod:parrot.handlers.models.bots.md)

Database model for Managing Chatbots and Agents.

## [parrot.handlers.models.credentials](summaries/mod:parrot.handlers.models.credentials.md)

Credential Pydantic data models.

## [parrot.handlers.models.understanding](summaries/mod:parrot.handlers.models.understanding.md)

Pydantic request/response models for the image & video understanding handler.

## [parrot.handlers.models.users_bots](summaries/mod:parrot.handlers.models.users_bots.md)

Database model for per-user defined bots (``navigator.users_bots``).

## [parrot.handlers.models.users_prompts](summaries/mod:parrot.handlers.models.users_prompts.md)

Database model for per-user prompts (``navigator.users_prompts``).

## [parrot.handlers.planogram_compliance](summaries/mod:parrot.handlers.planogram_compliance.md)

Backward-compat re-export — canonical location is parrot_pipelines.handlers.

## [parrot.handlers.print_pdf](summaries/mod:parrot.handlers.print_pdf.md)

PrintPDFHandler — Convert HTML to PDF via HTTP.

## [parrot.handlers.programs](summaries/mod:parrot.handlers.programs.md)

Module parrot.handlers.programs

## [parrot.handlers.prompt](summaries/mod:parrot.handlers.prompt.md)

HTTP handler for runtime system-prompt fine-tuning — ``/api/v1/agents/prompt``.

## [parrot.handlers.scheduler](summaries/mod:parrot.handlers.scheduler.md)

REST handlers for Parrot scheduler management.

## [parrot.handlers.scraping](summaries/mod:parrot.handlers.scraping.md)

Scraping HTTP handlers for exposing WebScrapingToolkit over REST API.

## [parrot.handlers.scraping.handler](summaries/mod:parrot.handlers.scraping.handler.md)

ScrapingHandler — Class-based HTTP view for plan CRUD and scrape/crawl execution.

## [parrot.handlers.scraping.info](summaries/mod:parrot.handlers.scraping.info.md)

ScrapingInfoHandler — GET-only reference metadata endpoints for the Scraping UI.

## [parrot.handlers.scraping.models](summaries/mod:parrot.handlers.scraping.models.md)

Pydantic request/response models for the Scraping HTTP API.

## [parrot.handlers.spatial_filter_handler](summaries/mod:parrot.handlers.spatial_filter_handler.md)

Spatial filter HTTP handler and AgenTalk pass-through envelope (FEAT-219 Module 6).

## [parrot.handlers.stores](summaries/mod:parrot.handlers.stores.md)

Vector Store Handler API package.

## [parrot.handlers.stores.handler](summaries/mod:parrot.handlers.stores.handler.md)

Vector Store Handler — REST API for vector store lifecycle management.

## [parrot.handlers.stores.helpers](summaries/mod:parrot.handlers.stores.helpers.md)

Vector Store Helper — public metadata endpoints for vector store configuration.

## [parrot.handlers.stream](summaries/mod:parrot.handlers.stream.md)

Module parrot.handlers.stream

## [parrot.handlers.testing_handler](summaries/mod:parrot.handlers.testing_handler.md)

REST API Handler for Agent Configuration Testing.

## [parrot.handlers.threads](summaries/mod:parrot.handlers.threads.md)

REST handler for thread management.

## [parrot.handlers.tools_catalog](summaries/mod:parrot.handlers.tools_catalog.md)

Handler for the tool catalog endpoint (FEAT-149 TASK-1039).

## [parrot.handlers.understanding](summaries/mod:parrot.handlers.understanding.md)

HTTP handler for image and video understanding via Google GenAI.

## [parrot.handlers.user](summaries/mod:parrot.handlers.user.md)

UserSocketManager - WebSocket Manager with Redis PubSub for User Interactions.

## [parrot.handlers.user_objects](summaries/mod:parrot.handlers.user_objects.md)

UserObjectsHandler - Session-Scoped User Object Management

## [parrot.handlers.vault_utils](summaries/mod:parrot.handlers.vault_utils.md)

Backward-compatible redirect — vault_utils relocated to parrot.security in FEAT-203.

## [parrot.handlers.video_reel](summaries/mod:parrot.handlers.video_reel.md)

HTTP handler for video reel generation with background job support.

## [parrot.handlers.web_hitl](summaries/mod:parrot.handlers.web_hitl.md)

Web HITL (Human-in-the-Loop) support for AI-Parrot.

## [parrot.helpers](summaries/mod:parrot.helpers.md)

Module parrot.helpers

## [parrot.helpers.infographics](summaries/mod:parrot.helpers.infographics.md)

Helper façade for the infographic template and theme registries.

## [parrot.human](summaries/mod:parrot.human.md)

Human-in-the-Loop (HITL) Architecture for AI-Parrot.

## [parrot.human.actions.backends](summaries/mod:parrot.human.actions.backends.md)

Concrete action backends for the HITL escalation system.

## [parrot.human.actions.backends.base](summaries/mod:parrot.human.actions.backends.base.md)

Abstract base class and exception hierarchy for escalation action backends.

## [parrot.human.actions.backends.email](summaries/mod:parrot.human.actions.backends.email.md)

Email action backend — async-notify backed (back-compat shim).

## [parrot.human.actions.backends.notify_provider](summaries/mod:parrot.human.actions.backends.notify_provider.md)

async-notify-backed escalation notification backend.

## [parrot.human.actions.backends.webhook](summaries/mod:parrot.human.actions.backends.webhook.md)

Generic webhook backend using aiohttp.

## [parrot.human.actions.backends.zammad](summaries/mod:parrot.human.actions.backends.zammad.md)

Zammad ticket backend using aiohttp.

## [parrot.human.actions.base](summaries/mod:parrot.human.actions.base.md)

Base class for escalation actions.

## [parrot.human.actions.notify](summaries/mod:parrot.human.actions.notify.md)

Escalation action that sends a one-way notification.

## [parrot.human.actions.ticket](summaries/mod:parrot.human.actions.ticket.md)

Escalation action that opens a ticket in an external system.

## [parrot.human.channels](summaries/mod:parrot.human.channels.md)

Communication channel implementations for HITL interactions.

## [parrot.human.channels.base](summaries/mod:parrot.human.channels.base.md)

Abstract base class for human communication channels.

## [parrot.human.channels.cli](summaries/mod:parrot.human.channels.cli.md)

CLI Human Channel for AI-Parrot HITL.

## [parrot.human.channels.teams](summaries/mod:parrot.human.channels.teams.md)

Teams HITL Human Channel for AI-Parrot.

## [parrot.human.channels.telegram](summaries/mod:parrot.human.channels.telegram.md)

Telegram Human Channel for AI-Parrot HITL.

## [parrot.human.channels.web](summaries/mod:parrot.human.channels.web.md)

WebHumanChannel — delivers HITL interactions over WebSocket.

## [parrot.human.cli_companion](summaries/mod:parrot.human.cli_companion.md)

CLI Companion for Human-in-the-Loop.

## [parrot.human.escalation_intent](summaries/mod:parrot.human.escalation_intent.md)

Escalation intent detector for HITL multi-tier escalation.

## [parrot.human.events](summaries/mod:parrot.human.events.md)

Structured event models for HITL multi-tier escalation tier transitions.

## [parrot.human.manager](summaries/mod:parrot.human.manager.md)

Central engine for human-in-the-loop interactions.

## [parrot.human.models](summaries/mod:parrot.human.models.md)

Core data models for the Human-in-the-Loop system.

## [parrot.human.node](summaries/mod:parrot.human.node.md)

HumanDecisionNode — a flow node that pauses for human decisions.

## [parrot.human.suspended_store](summaries/mod:parrot.human.suspended_store.md)

Suspended-execution store for the stateless Web HITL suspend/resume path.

## [parrot.human.tool](summaries/mod:parrot.human.tool.md)

HumanTool — an AbstractTool that asks a human for input.

## [parrot.install](summaries/mod:parrot.install.md)

Install command group for Parrot CLI.

## [parrot.install.cli](summaries/mod:parrot.install.cli.md)

CLI commands for installing external tools via Docker.

## [parrot.install.conf](summaries/mod:parrot.install.conf.md)

Module parrot.install.conf

## [parrot.integrations](summaries/mod:parrot.integrations.md)

Integrations stub — actual implementations are in ai-parrot-integrations.

## [parrot.integrations.a2a](summaries/mod:parrot.integrations.a2a.md)

A2A (Agent-to-Agent) integration for AI-Parrot.

## [parrot.integrations.a2a.models](summaries/mod:parrot.integrations.a2a.models.md)

Data models for exposing AI-Parrot agents as A2A (Agent-to-Agent) services.

## [parrot.integrations.a2ui_resume](summaries/mod:parrot.integrations.a2ui_resume.md)

Per-channel A2UI deep-link resume helper (Module 8, channel half).

## [parrot.integrations.core](summaries/mod:parrot.integrations.core.md)

Core state management for AI-Parrot integrations.

## [parrot.integrations.core.auth](summaries/mod:parrot.integrations.core.auth.md)

Shared authentication primitives for AI-Parrot integrations.

## [parrot.integrations.core.auth.oauth2_providers](summaries/mod:parrot.integrations.core.auth.oauth2_providers.md)

OAuth2 provider registry for integration authentication flows.

## [parrot.integrations.core.auth.post_auth](summaries/mod:parrot.integrations.core.auth.post_auth.md)

PostAuthProvider protocol and registry for secondary authentication flows.

## [parrot.integrations.core.state](summaries/mod:parrot.integrations.core.state.md)

Module parrot.integrations.core.state

## [parrot.integrations.liveavatar](summaries/mod:parrot.integrations.liveavatar.md)

LiveAvatar integration for AI-Parrot (FEAT-242 — Phase A).

## [parrot.integrations.liveavatar.avatar_ws](summaries/mod:parrot.integrations.liveavatar.avatar_ws.md)

Avatar audio bridge — WebSocket PCM push (FEAT-242 Phase A — Module 2).

## [parrot.integrations.liveavatar.client](summaries/mod:parrot.integrations.liveavatar.client.md)

LiveAvatar HTTP client and session lifecycle (FEAT-242 Phase A — Module 1).

## [parrot.integrations.liveavatar.models](summaries/mod:parrot.integrations.liveavatar.models.md)

Pydantic data models for the LiveAvatar integration (FEAT-242, Phase A).

## [parrot.integrations.liveavatar.optin](summaries/mod:parrot.integrations.liveavatar.optin.md)

Per-tenant opt-in gating for LiveAvatar LITE mode (FEAT-242 Phase A — Module 7).

## [parrot.integrations.liveavatar.output_bridge](summaries/mod:parrot.integrations.liveavatar.output_bridge.md)

Structured-output → AgentChat UI bridge (FEAT-243 / FEAT-249).

## [parrot.integrations.liveavatar.output_transport](summaries/mod:parrot.integrations.liveavatar.output_transport.md)

Cross-process transport for structured-output delivery (FEAT-249).

## [parrot.integrations.liveavatar.room_audio_publisher](summaries/mod:parrot.integrations.liveavatar.room_audio_publisher.md)

Headless LiveKit room audio publisher (FEAT-256 Module 1).

## [parrot.integrations.liveavatar.room_manager](summaries/mod:parrot.integrations.liveavatar.room_manager.md)

LiveKit room manager — BYO Cloud tokens (FEAT-242 Phase A — Module 3).

## [parrot.integrations.liveavatar.speakable](summaries/mod:parrot.integrations.liveavatar.speakable.md)

Speakable-text flattener and sentence segmenter (FEAT-242 Phase A — Module 4).

## [parrot.integrations.liveavatar.speaker](summaries/mod:parrot.integrations.liveavatar.speaker.md)

Per-turn avatar speaker (FEAT-242 Phase A — chat→avatar wiring).

## [parrot.integrations.liveavatar.tenant_config](summaries/mod:parrot.integrations.liveavatar.tenant_config.md)

Per-tenant FULL mode configuration resolver (FEAT-248 — Module 3).

## [parrot.integrations.liveavatar.voice_provider](summaries/mod:parrot.integrations.liveavatar.voice_provider.md)

Shared avatar voice provider (FEAT-242 Phase A — chat→avatar wiring).

## [parrot.integrations.liveavatar.voice_session](summaries/mod:parrot.integrations.liveavatar.voice_session.md)

VoiceAvatarSession — drive a LiveAvatar mouth from a realtime PCM stream (FEAT-245).

## [parrot.integrations.manager](summaries/mod:parrot.integrations.manager.md)

Integration Bot Manager.

## [parrot.integrations.matrix](summaries/mod:parrot.integrations.matrix.md)

Matrix protocol integration for AI-Parrot.

## [parrot.integrations.matrix.a2a_transport](summaries/mod:parrot.integrations.matrix.a2a_transport.md)

Matrix A2A Transport — agent-to-agent communication over Matrix.

## [parrot.integrations.matrix.appservice](summaries/mod:parrot.integrations.matrix.appservice.md)

Matrix Application Service for AI-Parrot.

## [parrot.integrations.matrix.client](summaries/mod:parrot.integrations.matrix.client.md)

Async Matrix client wrapper for AI-Parrot.

## [parrot.integrations.matrix.crew](summaries/mod:parrot.integrations.matrix.crew.md)

Matrix multi-agent crew integration package.

## [parrot.integrations.matrix.crew.config](summaries/mod:parrot.integrations.matrix.crew.config.md)

Configuration models for MatrixCrewTransport.

## [parrot.integrations.matrix.crew.coordinator](summaries/mod:parrot.integrations.matrix.crew.coordinator.md)

Matrix crew coordinator bot — manages pinned status board.

## [parrot.integrations.matrix.crew.crew_wrapper](summaries/mod:parrot.integrations.matrix.crew.crew_wrapper.md)

Per-agent message handler for the Matrix multi-agent crew.

## [parrot.integrations.matrix.crew.delegation](summaries/mod:parrot.integrations.matrix.crew.delegation.md)

Hybrid tool delegation for Matrix collaborative crew sessions.

## [parrot.integrations.matrix.crew.mention](summaries/mod:parrot.integrations.matrix.crew.mention.md)

Matrix mention parsing and formatting utilities.

## [parrot.integrations.matrix.crew.registry](summaries/mod:parrot.integrations.matrix.crew.registry.md)

Thread-safe in-memory agent registry for Matrix multi-agent crew.

## [parrot.integrations.matrix.crew.session](summaries/mod:parrot.integrations.matrix.crew.session.md)

Collaborative session orchestrator for Matrix multi-agent investigation.

## [parrot.integrations.matrix.crew.session_models](summaries/mod:parrot.integrations.matrix.crew.session_models.md)

Session state data models for collaborative multi-agent investigation sessions.

## [parrot.integrations.matrix.crew.transport](summaries/mod:parrot.integrations.matrix.crew.transport.md)

Matrix crew transport orchestrator.

## [parrot.integrations.matrix.events](summaries/mod:parrot.integrations.matrix.events.md)

Custom Matrix event types for AI-Parrot (m.parrot.* namespace).

## [parrot.integrations.matrix.hook](summaries/mod:parrot.integrations.matrix.hook.md)

Matrix protocol hook for AutonomousOrchestrator.

## [parrot.integrations.matrix.models](summaries/mod:parrot.integrations.matrix.models.md)

Pydantic configuration models for Matrix Application Service.

## [parrot.integrations.matrix.registration](summaries/mod:parrot.integrations.matrix.registration.md)

Generate Matrix Application Service registration YAML.

## [parrot.integrations.matrix.streaming](summaries/mod:parrot.integrations.matrix.streaming.md)

Matrix streaming handler — edit-based token streaming.

## [parrot.integrations.mcp](summaries/mod:parrot.integrations.mcp.md)

Module parrot.integrations.mcp

## [parrot.integrations.mcp.fireflies_a2a](summaries/mod:parrot.integrations.mcp.fireflies_a2a.md)

Fireflies.ai MCP credential adapter for the A2A per-user credential bridge.

## [parrot.integrations.models](summaries/mod:parrot.integrations.models.md)

Shared configuration models for Bot Integrations.

## [parrot.integrations.msagentsdk](summaries/mod:parrot.integrations.msagentsdk.md)

Microsoft 365 Agents SDK integration for AI-Parrot.

## [parrot.integrations.msagentsdk._patches](summaries/mod:parrot.integrations.msagentsdk._patches.md)

Runtime patches for the Microsoft 365 Agents SDK.

## [parrot.integrations.msagentsdk.agent](summaries/mod:parrot.integrations.msagentsdk.agent.md)

Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.

## [parrot.integrations.msagentsdk.auth](summaries/mod:parrot.integrations.msagentsdk.auth.md)

Per-user credential resolver for the Microsoft 365 Agents SDK integration.

## [parrot.integrations.msagentsdk.cards](summaries/mod:parrot.integrations.msagentsdk.cards.md)

Deterministic Adaptive Card renderer for the Semantic UI Model (FEAT-303).

## [parrot.integrations.msagentsdk.models](summaries/mod:parrot.integrations.msagentsdk.models.md)

Data models for Microsoft 365 Agents SDK bot configuration.

## [parrot.integrations.msagentsdk.resume](summaries/mod:parrot.integrations.msagentsdk.resume.md)

MSAgentSDK conversation-reference store and proactive-resume helper.

## [parrot.integrations.msagentsdk.semantic](summaries/mod:parrot.integrations.msagentsdk.semantic.md)

Semantic UI Model for custom engine Copilot agents (FEAT-303).

## [parrot.integrations.msagentsdk.wrapper](summaries/mod:parrot.integrations.msagentsdk.wrapper.md)

Integration wrapper for the Microsoft 365 Agents SDK.

## [parrot.integrations.msteams](summaries/mod:parrot.integrations.msteams.md)

MS Teams integration module.

## [parrot.integrations.msteams.adapter](summaries/mod:parrot.integrations.msteams.adapter.md)

Module parrot.integrations.msteams.adapter

## [parrot.integrations.msteams.commands](summaries/mod:parrot.integrations.msteams.commands.md)

MS Teams command routing infrastructure (FEAT-225).

## [parrot.integrations.msteams.commands.agent_commands](summaries/mod:parrot.integrations.msteams.commands.agent_commands.md)

Core agent commands for MS Teams (FEAT-XXX).

## [parrot.integrations.msteams.commands.jira_commands](summaries/mod:parrot.integrations.msteams.commands.jira_commands.md)

MS Teams command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

## [parrot.integrations.msteams.dialogs](summaries/mod:parrot.integrations.msteams.dialogs.md)

Module parrot.integrations.msteams.dialogs

## [parrot.integrations.msteams.dialogs.factory](summaries/mod:parrot.integrations.msteams.dialogs.factory.md)

Module parrot.integrations.msteams.dialogs.factory

## [parrot.integrations.msteams.dialogs.models](summaries/mod:parrot.integrations.msteams.dialogs.models.md)

Module parrot.integrations.msteams.dialogs.models

## [parrot.integrations.msteams.dialogs.orchestrator](summaries/mod:parrot.integrations.msteams.dialogs.orchestrator.md)

Form Orchestrator - Coordinates form generation, display, and tool execution.

## [parrot.integrations.msteams.dialogs.presets](summaries/mod:parrot.integrations.msteams.dialogs.presets.md)

Pre-built form dialog templates.

## [parrot.integrations.msteams.dialogs.presets.base](summaries/mod:parrot.integrations.msteams.dialogs.presets.base.md)

Base Form Dialog with common functionality.

## [parrot.integrations.msteams.dialogs.presets.conversational](summaries/mod:parrot.integrations.msteams.dialogs.presets.con-069250bf.md)

Conversational Form Dialog - One prompt per field, text-based interaction.

## [parrot.integrations.msteams.dialogs.presets.simple_form](summaries/mod:parrot.integrations.msteams.dialogs.presets.simple_form.md)

Simple Form Dialog - Single Adaptive Card with all fields.

## [parrot.integrations.msteams.dialogs.presets.wizard](summaries/mod:parrot.integrations.msteams.dialogs.presets.wizard.md)

Wizard Form Dialog - Multi-step form with navigation.

## [parrot.integrations.msteams.dialogs.presets.wizard_summary](summaries/mod:parrot.integrations.msteams.dialogs.presets.wiz-c34fadf0.md)

Wizard with Summary Dialog - Multi-step form with confirmation.

## [parrot.integrations.msteams.graph](summaries/mod:parrot.integrations.msteams.graph.md)

Minimal async Microsoft Graph client for the Teams HITL channel.

## [parrot.integrations.msteams.handler](summaries/mod:parrot.integrations.msteams.handler.md)

Module parrot.integrations.msteams.handler

## [parrot.integrations.msteams.hitl_adapter](summaries/mod:parrot.integrations.msteams.hitl_adapter.md)

HITL-dedicated Bot Framework adapter for TeamsHumanChannel.

## [parrot.integrations.msteams.hitl_cards](summaries/mod:parrot.integrations.msteams.hitl_cards.md)

Adaptive Card renderer for the Teams HITL channel.

## [parrot.integrations.msteams.models](summaries/mod:parrot.integrations.msteams.models.md)

Data models for MS Teams bot configuration.

## [parrot.integrations.msteams.oauth_callback](summaries/mod:parrot.integrations.msteams.oauth_callback.md)

MS Teams OAuth callback helpers for Jira 3LO flow (FEAT-225).

## [parrot.integrations.msteams.proactive](summaries/mod:parrot.integrations.msteams.proactive.md)

Proactive 1:1 bootstrap and Redis-backed conversation-reference cache.

## [parrot.integrations.msteams.tools](summaries/mod:parrot.integrations.msteams.tools.md)

Module parrot.integrations.msteams.tools

## [parrot.integrations.msteams.voice](summaries/mod:parrot.integrations.msteams.voice.md)

MS Teams Voice Module.

## [parrot.integrations.msteams.voice.backend](summaries/mod:parrot.integrations.msteams.voice.backend.md)

Abstract Transcriber Backend — backward compatibility re-export.

## [parrot.integrations.msteams.voice.faster_whisper_backend](summaries/mod:parrot.integrations.msteams.voice.faster_whisper_backend.md)

Faster Whisper Backend — backward compatibility re-export.

## [parrot.integrations.msteams.voice.models](summaries/mod:parrot.integrations.msteams.voice.models.md)

MS Teams Voice Data Models.

## [parrot.integrations.msteams.voice.openai_backend](summaries/mod:parrot.integrations.msteams.voice.openai_backend.md)

OpenAI Whisper Backend — backward compatibility re-export.

## [parrot.integrations.msteams.voice.transcriber](summaries/mod:parrot.integrations.msteams.voice.transcriber.md)

Voice Transcriber Service — backward compatibility re-export.

## [parrot.integrations.msteams.wrapper](summaries/mod:parrot.integrations.msteams.wrapper.md)

MS Teams Agent Wrapper.

## [parrot.integrations.parser](summaries/mod:parrot.integrations.parser.md)

Shared Response Parser for Integration Wrappers.

## [parrot.integrations.slack](summaries/mod:parrot.integrations.slack.md)

Slack integration module.

## [parrot.integrations.slack.assistant](summaries/mod:parrot.integrations.slack.assistant.md)

Slack Agents & AI Apps integration for AI-Parrot.

## [parrot.integrations.slack.commands](summaries/mod:parrot.integrations.slack.commands.md)

Slack command routing infrastructure (FEAT-225).

## [parrot.integrations.slack.commands.jira_commands](summaries/mod:parrot.integrations.slack.commands.jira_commands.md)

Slack command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

## [parrot.integrations.slack.dedup](summaries/mod:parrot.integrations.slack.dedup.md)

Event deduplication for Slack integration.

## [parrot.integrations.slack.files](summaries/mod:parrot.integrations.slack.files.md)

File handling for Slack integration.

## [parrot.integrations.slack.interactive](summaries/mod:parrot.integrations.slack.interactive.md)

Interactive Block Kit handler for Slack integration.

## [parrot.integrations.slack.models](summaries/mod:parrot.integrations.slack.models.md)

Data models for Slack bot configuration.

## [parrot.integrations.slack.oauth_callback](summaries/mod:parrot.integrations.slack.oauth_callback.md)

Slack OAuth callback helpers for Jira 3LO flow (FEAT-225).

## [parrot.integrations.slack.security](summaries/mod:parrot.integrations.slack.security.md)

Slack request signature verification.

## [parrot.integrations.slack.socket_handler](summaries/mod:parrot.integrations.slack.socket_handler.md)

Socket Mode handler for Slack integration.

## [parrot.integrations.slack.wrapper](summaries/mod:parrot.integrations.slack.wrapper.md)

Slack Agent Wrapper.

## [parrot.integrations.telegram](summaries/mod:parrot.integrations.telegram.md)

Telegram Integration for AI-Parrot Agents.

## [parrot.integrations.telegram.auth](summaries/mod:parrot.integrations.telegram.auth.md)

Telegram user authentication — strategies and session management.

## [parrot.integrations.telegram.callbacks](summaries/mod:parrot.integrations.telegram.callbacks.md)

Telegram Callback Decorators.

## [parrot.integrations.telegram.combined_callback](summaries/mod:parrot.integrations.telegram.combined_callback.md)

Combined BasicAuth + secondary OAuth callback for the Telegram WebApp.

## [parrot.integrations.telegram.context](summaries/mod:parrot.integrations.telegram.context.md)

Per-request context helpers for the Telegram integration.

## [parrot.integrations.telegram.crew](summaries/mod:parrot.integrations.telegram.crew.md)

Telegram Crew Transport — multi-agent crew in a Telegram supergroup.

## [parrot.integrations.telegram.crew.agent_card](summaries/mod:parrot.integrations.telegram.crew.agent_card.md)

AgentCard and AgentSkill models for TelegramCrewTransport.

## [parrot.integrations.telegram.crew.config](summaries/mod:parrot.integrations.telegram.crew.config.md)

Configuration models for TelegramCrewTransport.

## [parrot.integrations.telegram.crew.coordinator](summaries/mod:parrot.integrations.telegram.crew.coordinator.md)

CoordinatorBot — manages the pinned registry message in a crew supergroup.

## [parrot.integrations.telegram.crew.crew_wrapper](summaries/mod:parrot.integrations.telegram.crew.crew_wrapper.md)

CrewAgentWrapper — per-agent message handler for crew context.

## [parrot.integrations.telegram.crew.mention](summaries/mod:parrot.integrations.telegram.crew.mention.md)

MentionBuilder — utilities for constructing @mention strings.

## [parrot.integrations.telegram.crew.payload](summaries/mod:parrot.integrations.telegram.crew.payload.md)

DataPayload — file exchange between agents via Telegram documents.

## [parrot.integrations.telegram.crew.registry](summaries/mod:parrot.integrations.telegram.crew.registry.md)

Thread-safe in-memory registry of active agents in a crew.

## [parrot.integrations.telegram.crew.transport](summaries/mod:parrot.integrations.telegram.crew.transport.md)

TelegramCrewTransport — top-level orchestrator for multi-agent crew.

## [parrot.integrations.telegram.decorators](summaries/mod:parrot.integrations.telegram.decorators.md)

Decorator for declaring agent methods as Telegram bot commands.

## [parrot.integrations.telegram.filters](summaries/mod:parrot.integrations.telegram.filters.md)

Custom aiogram filters for Telegram bot message handling.

## [parrot.integrations.telegram.human_tool](summaries/mod:parrot.integrations.telegram.human_tool.md)

Telegram-aware HumanTool.

## [parrot.integrations.telegram.jira_commands](summaries/mod:parrot.integrations.telegram.jira_commands.md)

Telegram command handlers for the Jira OAuth 2.0 (3LO) flow.

## [parrot.integrations.telegram.manager](summaries/mod:parrot.integrations.telegram.manager.md)

Telegram Bot Manager.

## [parrot.integrations.telegram.mcp_commands](summaries/mod:parrot.integrations.telegram.mcp_commands.md)

Telegram commands for per-user HTTP MCP server management.

## [parrot.integrations.telegram.mcp_persistence](summaries/mod:parrot.integrations.telegram.mcp_persistence.md)

Telegram MCP Persistence Service — DocumentDB CRUD for /add_mcp configs.

## [parrot.integrations.telegram.models](summaries/mod:parrot.integrations.telegram.models.md)

Data models for Telegram bot configuration.

## [parrot.integrations.telegram.oauth2_callback](summaries/mod:parrot.integrations.telegram.oauth2_callback.md)

OAuth2 callback endpoint for Telegram WebApp authentication.

## [parrot.integrations.telegram.office365_commands](summaries/mod:parrot.integrations.telegram.office365_commands.md)

Telegram command handlers for Office365 delegated connection.

## [parrot.integrations.telegram.operator_commands](summaries/mod:parrot.integrations.telegram.operator_commands.md)

Operator-only Telegram commands for the autonomous harness (FEAT-210).

## [parrot.integrations.telegram.post_auth_jira](summaries/mod:parrot.integrations.telegram.post_auth_jira.md)

Jira implementation of the ``PostAuthProvider`` protocol.

## [parrot.integrations.telegram.utils](summaries/mod:parrot.integrations.telegram.utils.md)

Utility functions for Telegram bot message processing.

## [parrot.integrations.telegram.wrapper](summaries/mod:parrot.integrations.telegram.wrapper.md)

Telegram Agent Wrapper.

## [parrot.integrations.utils](summaries/mod:parrot.integrations.utils.md)

Shared utilities for integration wrappers (Telegram, MS Teams, etc.).

## [parrot.integrations.version](summaries/mod:parrot.integrations.version.md)

AI-Parrot Integrations Meta information.

## [parrot.integrations.whatsapp](summaries/mod:parrot.integrations.whatsapp.md)

WhatsApp integration for AI-Parrot.

## [parrot.integrations.whatsapp.bridge_config](summaries/mod:parrot.integrations.whatsapp.bridge_config.md)

Configuration for WhatsApp Bridge integration.

## [parrot.integrations.whatsapp.bridge_wrapper](summaries/mod:parrot.integrations.whatsapp.bridge_wrapper.md)

WhatsApp Bridge Agent Wrapper.

## [parrot.integrations.whatsapp.handler](summaries/mod:parrot.integrations.whatsapp.handler.md)

WhatsApp user session tracking.

## [parrot.integrations.whatsapp.models](summaries/mod:parrot.integrations.whatsapp.models.md)

Data models for WhatsApp bot configuration.

## [parrot.integrations.whatsapp.utils](summaries/mod:parrot.integrations.whatsapp.utils.md)

Utilities for WhatsApp integration.

## [parrot.integrations.whatsapp.wrapper](summaries/mod:parrot.integrations.whatsapp.wrapper.md)

WhatsApp Agent Wrapper.

## [parrot.interfaces](summaries/mod:parrot.interfaces.md)

Interfaces package - Mixins for bot functionality.

## [parrot.interfaces.aws](summaries/mod:parrot.interfaces.aws.md)

AWS Interface for AI-Parrot

## [parrot.interfaces.credentials](summaries/mod:parrot.interfaces.credentials.md)

Module parrot.interfaces.credentials

## [parrot.interfaces.database](summaries/mod:parrot.interfaces.database.md)

DB (asyncdb) Extension.

## [parrot.interfaces.dataframes](summaries/mod:parrot.interfaces.dataframes.md)

Module parrot.interfaces.dataframes

## [parrot.interfaces.doc_converter](summaries/mod:parrot.interfaces.doc_converter.md)

DocumentConverterInterface - Helper for document conversion via Docling.

## [parrot.interfaces.documentdb](summaries/mod:parrot.interfaces.documentdb.md)

DocumentDB Interface.

## [parrot.interfaces.file](summaries/mod:parrot.interfaces.file.md)

File manager interfaces — re-exported from navigator.utils.file.

## [parrot.interfaces.file.abstract](summaries/mod:parrot.interfaces.file.abstract.md)

Re-export of navigator.utils.file.abstract for backward compat.

## [parrot.interfaces.file.gcs](summaries/mod:parrot.interfaces.file.gcs.md)

Re-export of navigator.utils.file.gcs for backward compat.

## [parrot.interfaces.file.local](summaries/mod:parrot.interfaces.file.local.md)

Re-export of navigator.utils.file.local for backward compat.

## [parrot.interfaces.file.s3](summaries/mod:parrot.interfaces.file.s3.md)

Re-export of navigator.utils.file.s3 for backward compat.

## [parrot.interfaces.file.tmp](summaries/mod:parrot.interfaces.file.tmp.md)

Re-export of navigator.utils.file.tmp for backward compat.

## [parrot.interfaces.flowtask](summaries/mod:parrot.interfaces.flowtask.md)

Flowtask Interface - Mixin for managing Flowtask DAG tasks.

## [parrot.interfaces.google](summaries/mod:parrot.interfaces.google.md)

Google Services Client for AI-Parrot.

## [parrot.interfaces.hierarchy](summaries/mod:parrot.interfaces.hierarchy.md)

Utilities for managing the employee hierarchy stored in ArangoDB.

## [parrot.interfaces.http](summaries/mod:parrot.interfaces.http.md)

Module parrot.interfaces.http

## [parrot.interfaces.images](summaries/mod:parrot.interfaces.images.md)

Module parrot.interfaces.images

## [parrot.interfaces.images.plugins](summaries/mod:parrot.interfaces.images.plugins.md)

Image processing and generation interfaces for Parrot.

## [parrot.interfaces.images.plugins.abstract](summaries/mod:parrot.interfaces.images.plugins.abstract.md)

Module parrot.interfaces.images.plugins.abstract

## [parrot.interfaces.images.plugins.analisys](summaries/mod:parrot.interfaces.images.plugins.analisys.md)

Module parrot.interfaces.images.plugins.analisys

## [parrot.interfaces.images.plugins.classify](summaries/mod:parrot.interfaces.images.plugins.classify.md)

Module parrot.interfaces.images.plugins.classify

## [parrot.interfaces.images.plugins.classifybase](summaries/mod:parrot.interfaces.images.plugins.classifybase.md)

Module parrot.interfaces.images.plugins.classifybase

## [parrot.interfaces.images.plugins.detect](summaries/mod:parrot.interfaces.images.plugins.detect.md)

Module parrot.interfaces.images.plugins.detect

## [parrot.interfaces.images.plugins.exif](summaries/mod:parrot.interfaces.images.plugins.exif.md)

Module parrot.interfaces.images.plugins.exif

## [parrot.interfaces.images.plugins.hash](summaries/mod:parrot.interfaces.images.plugins.hash.md)

Module parrot.interfaces.images.plugins.hash

## [parrot.interfaces.images.plugins.vision](summaries/mod:parrot.interfaces.images.plugins.vision.md)

Module parrot.interfaces.images.plugins.vision

## [parrot.interfaces.images.plugins.yolo](summaries/mod:parrot.interfaces.images.plugins.yolo.md)

Module parrot.interfaces.images.plugins.yolo

## [parrot.interfaces.images.plugins.zerodetect](summaries/mod:parrot.interfaces.images.plugins.zerodetect.md)

Module parrot.interfaces.images.plugins.zerodetect

## [parrot.interfaces.o365](summaries/mod:parrot.interfaces.o365.md)

Module parrot.interfaces.o365

## [parrot.interfaces.odoointerface](summaries/mod:parrot.interfaces.odoointerface.md)

Odoo ERP interface via JSON-RPC 2.0.

## [parrot.interfaces.onedrive](summaries/mod:parrot.interfaces.onedrive.md)

Module parrot.interfaces.onedrive

## [parrot.interfaces.rss](summaries/mod:parrot.interfaces.rss.md)

Module parrot.interfaces.rss

## [parrot.interfaces.rss_content](summaries/mod:parrot.interfaces.rss_content.md)

RSSContentInterface - RSS parsing with content extraction from linked pages.

## [parrot.interfaces.sharepoint](summaries/mod:parrot.interfaces.sharepoint.md)

Module parrot.interfaces.sharepoint

## [parrot.interfaces.soap](summaries/mod:parrot.interfaces.soap.md)

Module parrot.interfaces.soap

## [parrot.interfaces.tools](summaries/mod:parrot.interfaces.tools.md)

ToolInterface - Interface for tool management functionality.

## [parrot.interfaces.vector](summaries/mod:parrot.interfaces.vector.md)

VectorInterface - Interface for vector store and search functionality.

## [parrot.interfaces.zammad](summaries/mod:parrot.interfaces.zammad.md)

Zammad helpdesk interface via REST API v1.

## [parrot.knowledge](summaries/mod:parrot.knowledge.md)

Knowledge management components for AI-Parrot.

## [parrot.knowledge.graphindex](summaries/mod:parrot.knowledge.graphindex.md)

GraphIndex — Structured Knowledge Graph Indexing for AI-Parrot.

## [parrot.knowledge.graphindex.analytics](summaries/mod:parrot.knowledge.graphindex.analytics.md)

Analytics + Report stage for GraphIndex.

## [parrot.knowledge.graphindex.assemble](summaries/mod:parrot.knowledge.graphindex.assemble.md)

Graph assembly stage for GraphIndex.

## [parrot.knowledge.graphindex.cli](summaries/mod:parrot.knowledge.graphindex.cli.md)

GraphIndex CLI — build a knowledge graph from a code repository.

## [parrot.knowledge.graphindex.communities](summaries/mod:parrot.knowledge.graphindex.communities.md)

Louvain community detection for GraphIndex (FEAT-191).

## [parrot.knowledge.graphindex.embed](summaries/mod:parrot.knowledge.graphindex.embed.md)

Embedding stage for GraphIndex.

## [parrot.knowledge.graphindex.export_html](summaries/mod:parrot.knowledge.graphindex.export_html.md)

GraphIndex HTML export — interactive, self-contained knowledge-graph map.

## [parrot.knowledge.graphindex.extractors](summaries/mod:parrot.knowledge.graphindex.extractors.md)

GraphIndex extractors sub-package.

## [parrot.knowledge.graphindex.extractors.code](summaries/mod:parrot.knowledge.graphindex.extractors.code.md)

Code extractor — tree-sitter Python parsing for GraphIndex.

## [parrot.knowledge.graphindex.extractors.loader](summaries/mod:parrot.knowledge.graphindex.extractors.loader.md)

Loader-based extractor for GraphIndex.

## [parrot.knowledge.graphindex.extractors.odoo_code](summaries/mod:parrot.knowledge.graphindex.extractors.odoo_code.md)

Odoo-aware code extractor for GraphIndex (FEAT-240).

## [parrot.knowledge.graphindex.extractors.skill](summaries/mod:parrot.knowledge.graphindex.extractors.skill.md)

SKILL.md extractor for GraphIndex.

## [parrot.knowledge.graphindex.loader](summaries/mod:parrot.knowledge.graphindex.loader.md)

GraphIndexLoader — :class:`AbstractLoader` wrapper around GraphIndex.

## [parrot.knowledge.graphindex.meta_ontology](summaries/mod:parrot.knowledge.graphindex.meta_ontology.md)

Universal meta-ontology for GraphIndex.

## [parrot.knowledge.graphindex.persist](summaries/mod:parrot.knowledge.graphindex.persist.md)

Persistence stage for GraphIndex.

## [parrot.knowledge.graphindex.persist_sqlite](summaries/mod:parrot.knowledge.graphindex.persist_sqlite.md)

SQLite persistence backend for GraphIndex (FEAT-240).

## [parrot.knowledge.graphindex.projection](summaries/mod:parrot.knowledge.graphindex.projection.md)

GraphIndex OKF Projection Layer (FEAT-239).

## [parrot.knowledge.graphindex.resolve](summaries/mod:parrot.knowledge.graphindex.resolve.md)

Cross-domain resolution stage for GraphIndex.

## [parrot.knowledge.graphindex.retriever](summaries/mod:parrot.knowledge.graphindex.retriever.md)

Graph-Expanded Retrieval Pipeline.

## [parrot.knowledge.graphindex.schema](summaries/mod:parrot.knowledge.graphindex.schema.md)

Core schema models for GraphIndex.

## [parrot.knowledge.graphindex.signals](summaries/mod:parrot.knowledge.graphindex.signals.md)

Signal Knowledge Graph relevance model for GraphIndex (FEAT-190).

## [parrot.knowledge.graphindex.sqlite_reader](summaries/mod:parrot.knowledge.graphindex.sqlite_reader.md)

SQLiteGraphReader — read side of the SQLite GraphIndex artefact (FEAT-240).

## [parrot.knowledge.okf](summaries/mod:parrot.knowledge.okf.md)

Shared OKF (Open Knowledge Framework) core package.

## [parrot.knowledge.okf.frontmatter](summaries/mod:parrot.knowledge.okf.frontmatter.md)

Frontmatter model and deterministic YAML projection for OKF sidecars.

## [parrot.knowledge.okf.ontology](summaries/mod:parrot.knowledge.okf.ontology.md)

Shared OKF type vocabulary — single source of truth for all indexes.

## [parrot.knowledge.okf.uri](summaries/mod:parrot.knowledge.okf.uri.md)

Knowledge URI scheme — unified cross-index addressing (FEAT-239).

## [parrot.knowledge.okf.utils](summaries/mod:parrot.knowledge.okf.utils.md)

Shared filesystem utilities for the OKF package.

## [parrot.knowledge.ontology](summaries/mod:parrot.knowledge.ontology.md)

Ontological Graph RAG — composable ontology-driven retrieval augmented generation.

## [parrot.knowledge.ontology.authorization](summaries/mod:parrot.knowledge.ontology.authorization.md)

Intent-level authorization checker for the ontology pipeline (FEAT-158).

## [parrot.knowledge.ontology.cache](summaries/mod:parrot.knowledge.ontology.cache.md)

Redis cache helpers for ontology pipeline results.

## [parrot.knowledge.ontology.concept_catalog](summaries/mod:parrot.knowledge.ontology.concept_catalog.md)

Concept Catalog sub-package for FEAT-159 Topic-Authority Ontology Curation.

## [parrot.knowledge.ontology.concept_catalog.http](summaries/mod:parrot.knowledge.ontology.concept_catalog.http.md)

Concept Catalog HTTP Routes (FEAT-159 TASK-1092).

## [parrot.knowledge.ontology.concept_catalog.models](summaries/mod:parrot.knowledge.ontology.concept_catalog.models.md)

Pydantic v2 row models for the Concept Catalog tables.

## [parrot.knowledge.ontology.concept_catalog.reconcile](summaries/mod:parrot.knowledge.ontology.concept_catalog.reconcile.md)

Concept Catalog Reconciliation Job (FEAT-159 TASK-1091).

## [parrot.knowledge.ontology.concept_catalog.seed](summaries/mod:parrot.knowledge.ontology.concept_catalog.seed.md)

Concept Catalog YAML seed utility (FEAT-159 TASK-1090).

## [parrot.knowledge.ontology.concept_catalog.service](summaries/mod:parrot.knowledge.ontology.concept_catalog.service.md)

Concept Catalog Service — sole SQL writer for ontology_concept* tables.

## [parrot.knowledge.ontology.concept_catalog.worker](summaries/mod:parrot.knowledge.ontology.concept_catalog.worker.md)

Concept Catalog Sync Worker (FEAT-159 TASK-1089).

## [parrot.knowledge.ontology.concept_embedding](summaries/mod:parrot.knowledge.ontology.concept_embedding.md)

Concept embedding pipeline for the ontology knowledge layer (FEAT-159).

## [parrot.knowledge.ontology.defaults](summaries/mod:parrot.knowledge.ontology.defaults.md)

Module parrot.knowledge.ontology.defaults

## [parrot.knowledge.ontology.discovery](summaries/mod:parrot.knowledge.ontology.discovery.md)

Relation discovery engine for automatic edge creation.

## [parrot.knowledge.ontology.entity_resolver](summaries/mod:parrot.knowledge.ontology.entity_resolver.md)

Entity extraction and resolution for the ontology pipeline (FEAT-158).

## [parrot.knowledge.ontology.exceptions](summaries/mod:parrot.knowledge.ontology.exceptions.md)

Custom exceptions for the Ontological Graph RAG system.

## [parrot.knowledge.ontology.graph_store](summaries/mod:parrot.knowledge.ontology.graph_store.md)

ArangoDB wrapper for ontology graph operations.

## [parrot.knowledge.ontology.intent](summaries/mod:parrot.knowledge.ontology.intent.md)

Dual-path intent resolution for ontology graph RAG.

## [parrot.knowledge.ontology.merger](summaries/mod:parrot.knowledge.ontology.merger.md)

Multi-layer YAML ontology composition engine.

## [parrot.knowledge.ontology.mixin](summaries/mod:parrot.knowledge.ontology.mixin.md)

OntologyRAGMixin — agent mixin for ontological graph RAG.

## [parrot.knowledge.ontology.parser](summaries/mod:parrot.knowledge.ontology.parser.md)

YAML ontology file loading and validation.

## [parrot.knowledge.ontology.refresh](summaries/mod:parrot.knowledge.ontology.refresh.md)

CRON-triggered refresh pipeline for ontology graph delta sync.

## [parrot.knowledge.ontology.schema](summaries/mod:parrot.knowledge.ontology.schema.md)

Pydantic v2 models for ontology YAML validation and runtime representation.

## [parrot.knowledge.ontology.schema_overlay](summaries/mod:parrot.knowledge.ontology.schema_overlay.md)

Schema Overlay sub-package for FEAT-159 Topic-Authority Ontology Curation.

## [parrot.knowledge.ontology.schema_overlay.http](summaries/mod:parrot.knowledge.ontology.schema_overlay.http.md)

Schema Overlay HTTP Routes (FEAT-159 TASK-1097).

## [parrot.knowledge.ontology.schema_overlay.models](summaries/mod:parrot.knowledge.ontology.schema_overlay.models.md)

Pydantic v2 row models for the Schema Overlay tables.

## [parrot.knowledge.ontology.schema_overlay.service](summaries/mod:parrot.knowledge.ontology.schema_overlay.service.md)

Schema Overlay Service (FEAT-159 TASK-1095).

## [parrot.knowledge.ontology.schema_overlay.validator](summaries/mod:parrot.knowledge.ontology.schema_overlay.validator.md)

Schema Overlay dry-run validator (FEAT-159 TASK-1094).

## [parrot.knowledge.ontology.schema_overlay.worker](summaries/mod:parrot.knowledge.ontology.schema_overlay.worker.md)

Schema Overlay Sync Worker (FEAT-159 TASK-1096).

## [parrot.knowledge.ontology.tenant](summaries/mod:parrot.knowledge.ontology.tenant.md)

Multi-tenant ontology resolution and caching.

## [parrot.knowledge.ontology.tool_dispatcher](summaries/mod:parrot.knowledge.ontology.tool_dispatcher.md)

Jinja2-based tool call dispatcher for the ontology pipeline (FEAT-158).

## [parrot.knowledge.ontology.validators](summaries/mod:parrot.knowledge.ontology.validators.md)

AQL security validation for LLM-generated queries.

## [parrot.knowledge.pageindex](summaries/mod:parrot.knowledge.pageindex.md)

PageIndex: Vectorless, reasoning-based RAG with hierarchical tree indexing.

## [parrot.knowledge.pageindex.content_store](summaries/mod:parrot.knowledge.pageindex.content_store.md)

Per-node markdown content store for PageIndex trees.

## [parrot.knowledge.pageindex.embedding_store](summaries/mod:parrot.knowledge.pageindex.embedding_store.md)

Two-tier content-addressed embedding store for PageIndex trees.

## [parrot.knowledge.pageindex.hybrid_search](summaries/mod:parrot.knowledge.pageindex.hybrid_search.md)

Hybrid search over a PageIndex tree.

## [parrot.knowledge.pageindex.ingest](summaries/mod:parrot.knowledge.pageindex.ingest.md)

Two-Step Chain-of-Thought ingestion: raw content -> clean markdown.

## [parrot.knowledge.pageindex.llm_adapter](summaries/mod:parrot.knowledge.pageindex.llm_adapter.md)

LLM adapter for PageIndex — wraps any AbstractClient for LLM-agnostic calls.

## [parrot.knowledge.pageindex.loader](summaries/mod:parrot.knowledge.pageindex.loader.md)

PageIndexLoader — :class:`AbstractLoader` wrapper around PageIndex.

## [parrot.knowledge.pageindex.okf](summaries/mod:parrot.knowledge.pageindex.okf.md)

OKF Knowledge Layer subpackage for PageIndex.

## [parrot.knowledge.pageindex.okf.bundle](summaries/mod:parrot.knowledge.pageindex.okf.bundle.md)

OKF v0.1 bundle import/export for PageIndex.

## [parrot.knowledge.pageindex.okf.concept_id](summaries/mod:parrot.knowledge.pageindex.okf.concept_id.md)

Deterministic slug generation for OKF concept identifiers.

## [parrot.knowledge.pageindex.okf.frontmatter](summaries/mod:parrot.knowledge.pageindex.okf.frontmatter.md)

Backwards-compatible re-export shim for OKF frontmatter engine.

## [parrot.knowledge.pageindex.okf.graph](summaries/mod:parrot.knowledge.pageindex.okf.graph.md)

In-memory knowledge graph for OKF concept-level traversal.

## [parrot.knowledge.pageindex.okf.lint](summaries/mod:parrot.knowledge.pageindex.okf.lint.md)

Knowledge base lint engine for OKF.

## [parrot.knowledge.pageindex.okf.migrate](summaries/mod:parrot.knowledge.pageindex.okf.migrate.md)

okf-migrate: Retrofit existing PageIndex trees with OKF fields.

## [parrot.knowledge.pageindex.okf.ontology](summaries/mod:parrot.knowledge.pageindex.okf.ontology.md)

Backwards-compatible re-export shim for OKF ontology types.

## [parrot.knowledge.pageindex.okf.projection](summaries/mod:parrot.knowledge.pageindex.okf.projection.md)

Deterministic sidecar and index.md generation for OKF.

## [parrot.knowledge.pageindex.okf.tools](summaries/mod:parrot.knowledge.pageindex.okf.tools.md)

Named read tools for OKF knowledge-layer retrieval and traversal.

## [parrot.knowledge.pageindex.pdf_to_markdown](summaries/mod:parrot.knowledge.pageindex.pdf_to_markdown.md)

PDF → per-page markdown extraction for PageIndex.

## [parrot.knowledge.pageindex.prompts](summaries/mod:parrot.knowledge.pageindex.prompts.md)

Prompt templates for the Two-Step Chain-of-Thought ingest pipeline.

## [parrot.knowledge.pageindex.retriever](summaries/mod:parrot.knowledge.pageindex.retriever.md)

PageIndex tree-search retriever for RAG.

## [parrot.knowledge.pageindex.schemas](summaries/mod:parrot.knowledge.pageindex.schemas.md)

Pydantic models for PageIndex structured LLM outputs.

## [parrot.knowledge.pageindex.store](summaries/mod:parrot.knowledge.pageindex.store.md)

On-disk JSON persistence for PageIndex trees.

## [parrot.knowledge.pageindex.toolkit](summaries/mod:parrot.knowledge.pageindex.toolkit.md)

Agent-facing toolkit for PageIndex.

## [parrot.knowledge.pageindex.tree_ops](summaries/mod:parrot.knowledge.pageindex.tree_ops.md)

Mutation helpers for PageIndex trees.

## [parrot.knowledge.pageindex.utils](summaries/mod:parrot.knowledge.pageindex.utils.md)

Pure utility functions for PageIndex — no LLM dependency.

## [parrot.knowledge.pageindex.vector_walk](summaries/mod:parrot.knowledge.pageindex.vector_walk.md)

Embedding-guided beam walk over a PageIndex tree (Phase B of FEAT-237).

## [parrot.knowledge.wiki](summaries/mod:parrot.knowledge.wiki.md)

parrot.knowledge.wiki — LLM Wiki: Persistent Knowledge Base (FEAT-260).

## [parrot.knowledge.wiki.bookkeeper](summaries/mod:parrot.knowledge.wiki.bookkeeper.md)

Wiki bookkeeper — index.md and log.md lifecycle management (FEAT-260).

## [parrot.knowledge.wiki.context](summaries/mod:parrot.knowledge.wiki.context.md)

Token-efficient context packing for wiki retrieval results.

## [parrot.knowledge.wiki.export](summaries/mod:parrot.knowledge.wiki.export.md)

OKF v0.1 bundle export for the LLM Wiki (export-only boundary).

## [parrot.knowledge.wiki.file_store](summaries/mod:parrot.knowledge.wiki.file_store.md)

In-memory wiki retrieval plane persisted as an OKF markdown bundle.

## [parrot.knowledge.wiki.ingest](summaries/mod:parrot.knowledge.wiki.ingest.md)

Wiki ingest orchestrator for the LLM Wiki feature (FEAT-260).

## [parrot.knowledge.wiki.models](summaries/mod:parrot.knowledge.wiki.models.md)

Pydantic data models for the LLM Wiki feature (FEAT-260).

## [parrot.knowledge.wiki.search](summaries/mod:parrot.knowledge.wiki.search.md)

Combined search for the LLM Wiki (FEAT-260 + WikiStore plane).

## [parrot.knowledge.wiki.sources](summaries/mod:parrot.knowledge.wiki.sources.md)

Source collection manager for the LLM Wiki feature (FEAT-260).

## [parrot.knowledge.wiki.store](summaries/mod:parrot.knowledge.wiki.store.md)

WikiStore — single-file SQLite retrieval plane for the LLM Wiki.

## [parrot.knowledge.wiki.toolkit](summaries/mod:parrot.knowledge.wiki.toolkit.md)

LLMWikiToolkit — agent-facing orchestrator for the LLM Wiki (FEAT-260).

## [parrot.loaders](summaries/mod:parrot.loaders.md)

Document Loaders — load data from different sources for RAG.

## [parrot.loaders.abstract](summaries/mod:parrot.loaders.abstract.md)

Module parrot.loaders.abstract

## [parrot.loaders.splitters](summaries/mod:parrot.loaders.splitters.md)

Module parrot.loaders.splitters

## [parrot.loaders.splitters.base](summaries/mod:parrot.loaders.splitters.base.md)

Module parrot.loaders.splitters.base

## [parrot.loaders.splitters.md](summaries/mod:parrot.loaders.splitters.md.md)

Rust-backed Markdown splitter (thin wrapper over semantic_text_splitter.MarkdownSplitter).

## [parrot.loaders.splitters.semantic](summaries/mod:parrot.loaders.splitters.semantic.md)

Rust-backed semantic text splitter (thin wrapper over TextSplitter from semantic_text_splitter).

## [parrot.loaders.splitters.token](summaries/mod:parrot.loaders.splitters.token.md)

Module parrot.loaders.splitters.token

## [parrot.manager](summaries/mod:parrot.manager.md)

Bot Manager for AI-Parrot.

## [parrot.manager.ephemeral](summaries/mod:parrot.manager.ephemeral.md)

Ephemeral user agent lifecycle models and registry.

## [parrot.manager.manager](summaries/mod:parrot.manager.manager.md)

Chatbot Manager.

## [parrot.mcp](summaries/mod:parrot.mcp.md)

MCP integration for AI-Parrot.

## [parrot.mcp.adapter](summaries/mod:parrot.mcp.adapter.md)

Module parrot.mcp.adapter

## [parrot.mcp.chrome](summaries/mod:parrot.mcp.chrome.md)

Module parrot.mcp.chrome

## [parrot.mcp.cli](summaries/mod:parrot.mcp.cli.md)

Module parrot.mcp.cli

## [parrot.mcp.client](summaries/mod:parrot.mcp.client.md)

Module parrot.mcp.client

## [parrot.mcp.config](summaries/mod:parrot.mcp.config.md)

Module parrot.mcp.config

## [parrot.mcp.context](summaries/mod:parrot.mcp.context.md)

MCP Context Module.

## [parrot.mcp.filtering](summaries/mod:parrot.mcp.filtering.md)

Tool filtering module for dynamic, context-aware MCP tool filtering.

## [parrot.mcp.integration](summaries/mod:parrot.mcp.integration.md)

Module parrot.mcp.integration

## [parrot.mcp.oauth](summaries/mod:parrot.mcp.oauth.md)

Module parrot.mcp.oauth

## [parrot.mcp.oauth2_config](summaries/mod:parrot.mcp.oauth2_config.md)

MCP OAuth2 configuration models and presets registry.

## [parrot.mcp.oauth2_state](summaries/mod:parrot.mcp.oauth2_state.md)

Shared in-process state for MCP OAuth2 callback coordination.

## [parrot.mcp.oauth2_storage](summaries/mod:parrot.mcp.oauth2_storage.md)

VaultMCPTokenStorage — adapter bridging MCP SDK's TokenStorage protocol to

## [parrot.mcp.oauth_server](summaries/mod:parrot.mcp.oauth_server.md)

OAuth server-side classes for MCP — extracted from parrot.mcp.oauth in FEAT-203.

## [parrot.mcp.parrot_server](summaries/mod:parrot.mcp.parrot_server.md)

Utilities for starting the MCP server inside the aiohttp application.

## [parrot.mcp.registry](summaries/mod:parrot.mcp.registry.md)

MCP Server Registry — declarative catalog of pre-built MCP server helpers.

## [parrot.mcp.resources](summaries/mod:parrot.mcp.resources.md)

Module parrot.mcp.resources

## [parrot.mcp.server](summaries/mod:parrot.mcp.server.md)

MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol

## [parrot.mcp.simple_server](summaries/mod:parrot.mcp.simple_server.md)

Module parrot.mcp.simple_server

## [parrot.mcp.transports](summaries/mod:parrot.mcp.transports.md)

Module parrot.mcp.transports

## [parrot.mcp.transports.base](summaries/mod:parrot.mcp.transports.base.md)

Module parrot.mcp.transports.base

## [parrot.mcp.transports.grpc_session](summaries/mod:parrot.mcp.transports.grpc_session.md)

Module parrot.mcp.transports.grpc_session

## [parrot.mcp.transports.http](summaries/mod:parrot.mcp.transports.http.md)

Module parrot.mcp.transports.http

## [parrot.mcp.transports.quic](summaries/mod:parrot.mcp.transports.quic.md)

QUIC/HTTP3 MCP Server Implementation

## [parrot.mcp.transports.sse](summaries/mod:parrot.mcp.transports.sse.md)

Module parrot.mcp.transports.sse

## [parrot.mcp.transports.stdio](summaries/mod:parrot.mcp.transports.stdio.md)

Module parrot.mcp.transports.stdio

## [parrot.mcp.transports.unix](summaries/mod:parrot.mcp.transports.unix.md)

Module parrot.mcp.transports.unix

## [parrot.mcp.transports.websocket](summaries/mod:parrot.mcp.transports.websocket.md)

Module parrot.mcp.transports.websocket

## [parrot.mcp.wrapper](summaries/mod:parrot.mcp.wrapper.md)

Module parrot.mcp.wrapper

## [parrot.memory](summaries/mod:parrot.memory.md)

Module parrot.memory

## [parrot.memory.abstract](summaries/mod:parrot.memory.abstract.md)

Module parrot.memory.abstract

## [parrot.memory.agent](summaries/mod:parrot.memory.agent.md)

Simple in-memory storage for agent question/answer pairs keyed by turn_id.

## [parrot.memory.cache](summaries/mod:parrot.memory.cache.md)

Module parrot.memory.cache

## [parrot.memory.episodic](summaries/mod:parrot.memory.episodic.md)

Episodic Memory Store for AI-Parrot agents.

## [parrot.memory.episodic.backends](summaries/mod:parrot.memory.episodic.backends.md)

Episodic memory storage backends.

## [parrot.memory.episodic.backends.abstract](summaries/mod:parrot.memory.episodic.backends.abstract.md)

Abstract backend protocol for episodic memory storage.

## [parrot.memory.episodic.backends.faiss](summaries/mod:parrot.memory.episodic.backends.faiss.md)

FAISS backend for episodic memory storage (local development).

## [parrot.memory.episodic.backends.pgvector](summaries/mod:parrot.memory.episodic.backends.pgvector.md)

PgVector backend for episodic memory storage.

## [parrot.memory.episodic.backends.redis_vector](summaries/mod:parrot.memory.episodic.backends.redis_vector.md)

Redis Stack (RediSearch) vector backend for episodic memory.

## [parrot.memory.episodic.cache](summaries/mod:parrot.memory.episodic.cache.md)

Redis hot cache for episodic memory.

## [parrot.memory.episodic.embedding](summaries/mod:parrot.memory.episodic.embedding.md)

Embedding provider for episodic memory.

## [parrot.memory.episodic.mixin](summaries/mod:parrot.memory.episodic.mixin.md)

EpisodicMemoryMixin for AbstractBot integration.

## [parrot.memory.episodic.models](summaries/mod:parrot.memory.episodic.models.md)

Episodic Memory data models, enums, and namespace types.

## [parrot.memory.episodic.recall](summaries/mod:parrot.memory.episodic.recall.md)

Pluggable recall strategy protocol and implementations for episodic memory.

## [parrot.memory.episodic.reflection](summaries/mod:parrot.memory.episodic.reflection.md)

Reflection engine for episodic memory.

## [parrot.memory.episodic.scoring](summaries/mod:parrot.memory.episodic.scoring.md)

Pluggable importance scoring strategies for episodic memory.

## [parrot.memory.episodic.store](summaries/mod:parrot.memory.episodic.store.md)

EpisodicMemoryStore — main orchestrator for episodic memory.

## [parrot.memory.episodic.tools](summaries/mod:parrot.memory.episodic.tools.md)

Agent-usable tools for episodic memory.

## [parrot.memory.file](summaries/mod:parrot.memory.file.md)

Module parrot.memory.file

## [parrot.memory.mem](summaries/mod:parrot.memory.mem.md)

Module parrot.memory.mem

## [parrot.memory.redis](summaries/mod:parrot.memory.redis.md)

Module parrot.memory.redis

## [parrot.memory.skills](summaries/mod:parrot.memory.skills.md)

AI-Parrot SkillRegistry Module — Deprecated re-export shim.

## [parrot.memory.skills.file_registry](summaries/mod:parrot.memory.skills.file_registry.md)

Deprecated: use parrot.skills.file_registry instead.

## [parrot.memory.skills.middleware](summaries/mod:parrot.memory.skills.middleware.md)

Deprecated: use parrot.skills.middleware instead.

## [parrot.memory.skills.mixin](summaries/mod:parrot.memory.skills.mixin.md)

Deprecated: use parrot.skills.mixin instead.

## [parrot.memory.skills.models](summaries/mod:parrot.memory.skills.models.md)

Deprecated: use parrot.skills.models instead.

## [parrot.memory.skills.parsers](summaries/mod:parrot.memory.skills.parsers.md)

Deprecated: use parrot.skills.parsers instead.

## [parrot.memory.skills.store](summaries/mod:parrot.memory.skills.store.md)

Deprecated: use parrot.skills.store instead.

## [parrot.memory.skills.tools](summaries/mod:parrot.memory.skills.tools.md)

Deprecated: use parrot.skills.tools instead.

## [parrot.memory.unified](summaries/mod:parrot.memory.unified.md)

Unified long-term memory package.

## [parrot.memory.unified.context](summaries/mod:parrot.memory.unified.context.md)

Context assembler for unified memory — priority-based token budgeting.

## [parrot.memory.unified.manager](summaries/mod:parrot.memory.unified.manager.md)

Unified Memory Manager — coordinates all long-term memory subsystems.

## [parrot.memory.unified.mixin](summaries/mod:parrot.memory.unified.mixin.md)

LongTermMemoryMixin — opt-in unified long-term memory for any bot/agent.

## [parrot.memory.unified.models](summaries/mod:parrot.memory.unified.models.md)

Unified Memory data models for the long-term memory layer.

## [parrot.memory.unified.routing](summaries/mod:parrot.memory.unified.routing.md)

CrossDomainRouter for multi-agent memory sharing.

## [parrot.models](summaries/mod:parrot.models.md)

Models for the Parrot application.

## [parrot.models.basic](summaries/mod:parrot.models.basic.md)

Module parrot.models.basic

## [parrot.models.bedrock_models](summaries/mod:parrot.models.bedrock_models.md)

Bedrock model-ID translator for AI-Parrot.

## [parrot.models.claude](summaries/mod:parrot.models.claude.md)

Module parrot.models.claude

## [parrot.models.compliance](summaries/mod:parrot.models.compliance.md)

Module parrot.models.compliance

## [parrot.models.conference](summaries/mod:parrot.models.conference.md)

Data models for multi-party conferencing (FEAT-223).

## [parrot.models.crew](summaries/mod:parrot.models.crew.md)

Data models for Agent Crew execution results.

## [parrot.models.crew_definition](summaries/mod:parrot.models.crew_definition.md)

Core crew definition models.

## [parrot.models.datasets](summaries/mod:parrot.models.datasets.md)

Pydantic models for DatasetManager HTTP operations.

## [parrot.models.detections](summaries/mod:parrot.models.detections.md)

Module parrot.models.detections

## [parrot.models.generation](summaries/mod:parrot.models.generation.md)

Module parrot.models.generation

## [parrot.models.google](summaries/mod:parrot.models.google.md)

Google Related Models to be used in GenAI.

## [parrot.models.groq](summaries/mod:parrot.models.groq.md)

Module parrot.models.groq

## [parrot.models.infographic](summaries/mod:parrot.models.infographic.md)

Structured Infographic Output Models.

## [parrot.models.infographic_templates](summaries/mod:parrot.models.infographic_templates.md)

Infographic Template Definitions.

## [parrot.models.interactive](summaries/mod:parrot.models.interactive.md)

Models for Interactive HTML Artifacts ("vibe-coding" canvas).

## [parrot.models.localllm](summaries/mod:parrot.models.localllm.md)

Module parrot.models.localllm

## [parrot.models.nvidia](summaries/mod:parrot.models.nvidia.md)

Nvidia NIM data models for AI-Parrot.

## [parrot.models.openai](summaries/mod:parrot.models.openai.md)

OpenAI model catalog and deprecation registry.

## [parrot.models.openrouter](summaries/mod:parrot.models.openrouter.md)

OpenRouter data models for AI-Parrot.

## [parrot.models.outputs](summaries/mod:parrot.models.outputs.md)

Module parrot.models.outputs

## [parrot.models.responses](summaries/mod:parrot.models.responses.md)

Module parrot.models.responses

## [parrot.models.status](summaries/mod:parrot.models.status.md)

Module parrot.models.status

## [parrot.models.stores](summaries/mod:parrot.models.stores.md)

Store-identifier and store data models.

## [parrot.models.vllm](summaries/mod:parrot.models.vllm.md)

Pydantic models for vLLM client integration.

## [parrot.models.voice](summaries/mod:parrot.models.voice.md)

Voice configuration models for VoiceBot.

## [parrot.models.zai](summaries/mod:parrot.models.zai.md)

Module parrot.models.zai

## [parrot.notifications](summaries/mod:parrot.notifications.md)

Notification Mixin for AI-Parrot Agents.

## [parrot.observability](summaries/mod:parrot.observability.md)

parrot.observability — OpenTelemetry + Cost Observability for AI-Parrot.

## [parrot.observability.attributes](summaries/mod:parrot.observability.attributes.md)

GenAI SemConv attribute builders and provider mapping.

## [parrot.observability.bootstrap](summaries/mod:parrot.observability.bootstrap.md)

ensure_observability_bootstrapped — env-driven, idempotent auto-boot.

## [parrot.observability.config](summaries/mod:parrot.observability.config.md)

ObservabilityConfig — single global configuration for parrot.observability.

## [parrot.observability.context](summaries/mod:parrot.observability.context.md)

Agent-identity ContextVar for per-agent cost and usage metrics.

## [parrot.observability.cost](summaries/mod:parrot.observability.cost.md)

parrot.observability.cost — USD cost calculation for LLM calls.

## [parrot.observability.cost.calculator](summaries/mod:parrot.observability.cost.calculator.md)

CostCalculator — stateless USD cost estimation for LLM API calls.

## [parrot.observability.errors](summaries/mod:parrot.observability.errors.md)

Custom exceptions for parrot.observability.

## [parrot.observability.examples.basic_telemetry](summaries/mod:parrot.observability.examples.basic_telemetry.md)

Basic telemetry demo for AI-Parrot.

## [parrot.observability.exporters](summaries/mod:parrot.observability.exporters.md)

OTLP exporter factory helpers.

## [parrot.observability.openlit_integration](summaries/mod:parrot.observability.openlit_integration.md)

OpenLIT auto-instrumentation wrapper.

## [parrot.observability.provider](summaries/mod:parrot.observability.provider.md)

ParrotTelemetryProvider — EventProvider bundle for parrot.observability.

## [parrot.observability.recorders](summaries/mod:parrot.observability.recorders.md)

Pluggable usage/token/cost recording backends.

## [parrot.observability.recorders.base](summaries/mod:parrot.observability.recorders.base.md)

AbstractLogger — the pluggable usage-recording interface.

## [parrot.observability.recorders.factory](summaries/mod:parrot.observability.recorders.factory.md)

build_recorders_from_config — map an ObservabilityConfig to recorder backends.

## [parrot.observability.recorders.logging_recorder](summaries/mod:parrot.observability.recorders.logging_recorder.md)

LoggingUsageRecorder — zero-infra usage backend that logs one line per call.

## [parrot.observability.recorders.models](summaries/mod:parrot.observability.recorders.models.md)

UsageRecord — the normalized, PII-free record shared by all usage recorders.

## [parrot.observability.recorders.prometheus_recorder](summaries/mod:parrot.observability.recorders.prometheus_recorder.md)

PrometheusUsageRecorder — pull-based metrics backend (described, lazy-loaded).

## [parrot.observability.recorders.subscriber](summaries/mod:parrot.observability.recorders.subscriber.md)

UsageRecordingSubscriber — turns LLM-call events into UsageRecords + fan-out.

## [parrot.observability.setup](summaries/mod:parrot.observability.setup.md)

setup_telemetry() and shutdown_telemetry() — one-call observability boot helpers.

## [parrot.observability.subscribers](summaries/mod:parrot.observability.subscribers.md)

parrot.observability.subscribers — lifecycle event subscribers.

## [parrot.observability.subscribers.metrics](summaries/mod:parrot.observability.subscribers.metrics.md)

MetricsSubscriber — OTel counters and histograms for LLM calls.

## [parrot.observability.subscribers.trace](summaries/mod:parrot.observability.subscribers.trace.md)

GenAIOpenTelemetrySubscriber — rich GenAI SemConv span subscriber.

## [parrot.observability.traceloop_integration](summaries/mod:parrot.observability.traceloop_integration.md)

OpenLLMetry (Traceloop) backend — simple, content-rich tracing for local/dev.

## [parrot.openapi](summaries/mod:parrot.openapi.md)

Module parrot.openapi

## [parrot.openapi.config](summaries/mod:parrot.openapi.config.md)

OpenAPI Configuration for AI-Parrot

## [parrot.outputs](summaries/mod:parrot.outputs.md)

Output formatters for AI-Parrot using Rich (terminal) and Panel (HTML) with Jupyter support.

## [parrot.outputs.a2ui](summaries/mod:parrot.outputs.a2ui.md)

``parrot.outputs.a2ui`` — A2UI v1.0 rendering core (FEAT-273).

## [parrot.outputs.a2ui.artifacts](summaries/mod:parrot.outputs.a2ui.artifacts.md)

Rendered-artifact and deep-link models (Module 6).

## [parrot.outputs.a2ui.baking](summaries/mod:parrot.outputs.a2ui.baking.md)

A2UI baking pass (Module 6).

## [parrot.outputs.a2ui.catalog](summaries/mod:parrot.outputs.a2ui.catalog.md)

A2UI component catalog — public decorator, lookup, and envelope validation.

## [parrot.outputs.a2ui.catalog.base](summaries/mod:parrot.outputs.a2ui.catalog.base.md)

A2UI component catalog — contract types and registry internals (Module 2).

## [parrot.outputs.a2ui.catalog.components](summaries/mod:parrot.outputs.a2ui.catalog.components.md)

A2UI v1 catalog components (Module 3).

## [parrot.outputs.a2ui.catalog.components.card](summaries/mod:parrot.outputs.a2ui.catalog.components.card.md)

A2UI ``Card`` catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.chart](summaries/mod:parrot.outputs.a2ui.catalog.components.chart.md)

A2UI ``Chart`` catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.datatable](summaries/mod:parrot.outputs.a2ui.catalog.components.datatable.md)

A2UI ``DataTable`` catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.form](summaries/mod:parrot.outputs.a2ui.catalog.components.form.md)

A2UI ``Form`` catalog component (Module 3) — the one ``requires_actions=True``

## [parrot.outputs.a2ui.catalog.components.infographic](summaries/mod:parrot.outputs.a2ui.catalog.components.infographic.md)

A2UI ``Infographic`` composite catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.kpicard](summaries/mod:parrot.outputs.a2ui.catalog.components.kpicard.md)

A2UI ``KPICard`` catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.map](summaries/mod:parrot.outputs.a2ui.catalog.components.map.md)

A2UI ``Map`` catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.report](summaries/mod:parrot.outputs.a2ui.catalog.components.report.md)

A2UI ``Report`` composite catalog component (Module 3).

## [parrot.outputs.a2ui.catalog.components.timeline](summaries/mod:parrot.outputs.a2ui.catalog.components.timeline.md)

A2UI ``Timeline`` catalog component (Module 3).

## [parrot.outputs.a2ui.deeplink](summaries/mod:parrot.outputs.a2ui.deeplink.md)

Deep-link token service (Module 8, goal G6).

## [parrot.outputs.a2ui.delivery](summaries/mod:parrot.outputs.a2ui.delivery.md)

A2UI delivery bridge (Module 7, first half).

## [parrot.outputs.a2ui.emission](summaries/mod:parrot.outputs.a2ui.emission.md)

A2UI emission helper (Module 10).

## [parrot.outputs.a2ui.models](summaries/mod:parrot.outputs.a2ui.models.md)

A2UI v1.0 wire message models.

## [parrot.outputs.a2ui.producer](summaries/mod:parrot.outputs.a2ui.producer.md)

LLM envelope producer with a catalog-validate-retry loop (Module 9, D1b).

## [parrot.outputs.a2ui.renderers](summaries/mod:parrot.outputs.a2ui.renderers.md)

A2UI renderer registry and contract (Module 4, core side).

## [parrot.outputs.a2ui.serialization](summaries/mod:parrot.outputs.a2ui.serialization.md)

A2UI serialization layer — the *sole* owner of the protocol ``version`` field.

## [parrot.outputs.a2ui_renderers](summaries/mod:parrot.outputs.a2ui_renderers.md)

A2UI concrete renderers (satellite package, Module 5).

## [parrot.outputs.a2ui_renderers.adaptive_cards](summaries/mod:parrot.outputs.a2ui_renderers.adaptive_cards.md)

Adaptive Cards renderer (Module 5, satellite).

## [parrot.outputs.a2ui_renderers.echarts](summaries/mod:parrot.outputs.a2ui_renderers.echarts.md)

ECharts payload renderer (Module 5, satellite).

## [parrot.outputs.a2ui_renderers.folium_map](summaries/mod:parrot.outputs.a2ui_renderers.folium_map.md)

Folium map renderer (Module 5, satellite).

## [parrot.outputs.a2ui_renderers.pdf](summaries/mod:parrot.outputs.a2ui_renderers.pdf.md)

PDF renderer (Module 5, satellite) — SPK-1 backend = weasyprint.

## [parrot.outputs.a2ui_renderers.ssr_html](summaries/mod:parrot.outputs.a2ui_renderers.ssr_html.md)

SSR-HTML renderer (Module 5, satellite).

## [parrot.outputs.formats](summaries/mod:parrot.outputs.formats.md)

Module parrot.outputs.formats

## [parrot.outputs.formats.altair](summaries/mod:parrot.outputs.formats.altair.md)

Module parrot.outputs.formats.altair

## [parrot.outputs.formats.application](summaries/mod:parrot.outputs.formats.application.md)

Module parrot.outputs.formats.application

## [parrot.outputs.formats.assets](summaries/mod:parrot.outputs.formats.assets.md)

Module parrot.outputs.formats.assets

## [parrot.outputs.formats.base](summaries/mod:parrot.outputs.formats.base.md)

Module parrot.outputs.formats.base

## [parrot.outputs.formats.card](summaries/mod:parrot.outputs.formats.card.md)

Card Renderer for AI-Parrot

## [parrot.outputs.formats.chart](summaries/mod:parrot.outputs.formats.chart.md)

Module parrot.outputs.formats.chart

## [parrot.outputs.formats.echarts](summaries/mod:parrot.outputs.formats.echarts.md)

Module parrot.outputs.formats.echarts

## [parrot.outputs.formats.generators](summaries/mod:parrot.outputs.formats.generators.md)

Module parrot.outputs.formats.generators

## [parrot.outputs.formats.generators.abstract](summaries/mod:parrot.outputs.formats.generators.abstract.md)

Module parrot.outputs.formats.generators.abstract

## [parrot.outputs.formats.generators.panel](summaries/mod:parrot.outputs.formats.generators.panel.md)

Module parrot.outputs.formats.generators.panel

## [parrot.outputs.formats.generators.streamlit](summaries/mod:parrot.outputs.formats.generators.streamlit.md)

Module parrot.outputs.formats.generators.streamlit

## [parrot.outputs.formats.generators.terminal](summaries/mod:parrot.outputs.formats.generators.terminal.md)

Module parrot.outputs.formats.generators.terminal

## [parrot.outputs.formats.html](summaries/mod:parrot.outputs.formats.html.md)

Module parrot.outputs.formats.html

## [parrot.outputs.formats.infographic](summaries/mod:parrot.outputs.formats.infographic.md)

Infographic Renderer for AI-Parrot.

## [parrot.outputs.formats.infographic_html](summaries/mod:parrot.outputs.formats.infographic_html.md)

Infographic HTML Renderer for AI-Parrot.

## [parrot.outputs.formats.jinja2](summaries/mod:parrot.outputs.formats.jinja2.md)

Module parrot.outputs.formats.jinja2

## [parrot.outputs.formats.json](summaries/mod:parrot.outputs.formats.json.md)

Module parrot.outputs.formats.json

## [parrot.outputs.formats.map](summaries/mod:parrot.outputs.formats.map.md)

Module parrot.outputs.formats.map

## [parrot.outputs.formats.markdown](summaries/mod:parrot.outputs.formats.markdown.md)

Module parrot.outputs.formats.markdown

## [parrot.outputs.formats.matplotlib](summaries/mod:parrot.outputs.formats.matplotlib.md)

Module parrot.outputs.formats.matplotlib

## [parrot.outputs.formats.mixins](summaries/mod:parrot.outputs.formats.mixins.md)

Module parrot.outputs.formats.mixins

## [parrot.outputs.formats.mixins.emaps](summaries/mod:parrot.outputs.formats.mixins.emaps.md)

ECharts Geo Extension for AI-Parrot

## [parrot.outputs.formats.plotly](summaries/mod:parrot.outputs.formats.plotly.md)

Module parrot.outputs.formats.plotly

## [parrot.outputs.formats.seaborn](summaries/mod:parrot.outputs.formats.seaborn.md)

Module parrot.outputs.formats.seaborn

## [parrot.outputs.formats.slack](summaries/mod:parrot.outputs.formats.slack.md)

Slack output renderer.

## [parrot.outputs.formats.structured_base](summaries/mod:parrot.outputs.formats.structured_base.md)

FEAT-223 Module 1: Shared structured-output base mixin.

## [parrot.outputs.formats.structured_chart](summaries/mod:parrot.outputs.formats.structured_chart.md)

FEAT-215 (FEAT-223 Module 2 / FEAT-224 Module 2): Structured Chart Output Mode renderer.

## [parrot.outputs.formats.structured_map](summaries/mod:parrot.outputs.formats.structured_map.md)

FEAT-221: Structured Map Output Mode renderer.

## [parrot.outputs.formats.structured_table](summaries/mod:parrot.outputs.formats.structured_table.md)

FEAT-218: Structured Table Output Mode renderer.

## [parrot.outputs.formats.table](summaries/mod:parrot.outputs.formats.table.md)

Module parrot.outputs.formats.table

## [parrot.outputs.formats.table_types](summaries/mod:parrot.outputs.formats.table_types.md)

FEAT-218: Deterministic dtype→vocabulary map + canonical value serialization.

## [parrot.outputs.formats.template_report](summaries/mod:parrot.outputs.formats.template_report.md)

Module parrot.outputs.formats.template_report

## [parrot.outputs.formats.version](summaries/mod:parrot.outputs.formats.version.md)

AI-Parrot Visualizations Meta information.

## [parrot.outputs.formats.whatsapp](summaries/mod:parrot.outputs.formats.whatsapp.md)

WhatsApp output renderer.

## [parrot.outputs.formats.yaml](summaries/mod:parrot.outputs.formats.yaml.md)

Module parrot.outputs.formats.yaml

## [parrot.outputs.formatter](summaries/mod:parrot.outputs.formatter.md)

Module parrot.outputs.formatter

## [parrot.outputs.templates](summaries/mod:parrot.outputs.templates.md)

Module parrot.outputs.templates

## [parrot.pipelines](summaries/mod:parrot.pipelines.md)

AI-Parrot pipelines proxy.

## [parrot.pipelines.abstract](summaries/mod:parrot.pipelines.abstract.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.detector](summaries/mod:parrot.pipelines.detector.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.models](summaries/mod:parrot.pipelines.models.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram](summaries/mod:parrot.pipelines.planogram.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.legacy](summaries/mod:parrot.pipelines.planogram.legacy.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.plan](summaries/mod:parrot.pipelines.planogram.plan.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.types](summaries/mod:parrot.pipelines.planogram.types.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.types.abstract](summaries/mod:parrot.pipelines.planogram.types.abstract.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.types.graphic_panel_display](summaries/mod:parrot.pipelines.planogram.types.graphic_panel_display.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.pipelines.planogram.types.product_on_shelves](summaries/mod:parrot.pipelines.planogram.types.product_on_shelves.md)

Backward-compatible proxy for ai-parrot-pipelines.

## [parrot.plugins](summaries/mod:parrot.plugins.md)

Module parrot.plugins

## [parrot.plugins.importer](summaries/mod:parrot.plugins.importer.md)

Module parrot.plugins.importer

## [parrot.registry](summaries/mod:parrot.registry.md)

Module parrot.registry

## [parrot.registry.capabilities](summaries/mod:parrot.registry.capabilities.md)

Capability Registry package for Intent Router (FEAT-070).

## [parrot.registry.capabilities.models](summaries/mod:parrot.registry.capabilities.models.md)

Pydantic v2 models for Intent Router and Capability Registry.

## [parrot.registry.capabilities.registry](summaries/mod:parrot.registry.capabilities.registry.md)

CapabilityRegistry — semantic resource index for intent routing.

## [parrot.registry.registry](summaries/mod:parrot.registry.registry.md)

Agent Auto-Registration System for AI-Parrot.

## [parrot.registry.routing](summaries/mod:parrot.registry.routing.md)

parrot.registry.routing — Store-level router for FEAT-111.

## [parrot.registry.routing.cache](summaries/mod:parrot.registry.routing.cache.md)

Asyncio-safe LRU cache for store routing decisions (FEAT-111 Module 6).

## [parrot.registry.routing.embedding_router](summaries/mod:parrot.registry.routing.embedding_router.md)

EmbeddingIntentRouter — deterministic, embedding-based output-mode router.

## [parrot.registry.routing.llm_helper](summaries/mod:parrot.registry.routing.llm_helper.md)

Shared LLM-route helper utilities (FEAT-111 Module 3).

## [parrot.registry.routing.models](summaries/mod:parrot.registry.routing.models.md)

Pydantic v2 data models for the FEAT-111 store-level router.

## [parrot.registry.routing.ontology_signal](summaries/mod:parrot.registry.routing.ontology_signal.md)

Ontology Pre-Annotator adapter (FEAT-111 Module 5).

## [parrot.registry.routing.rules](summaries/mod:parrot.registry.routing.rules.md)

Fast-path rules engine for the store-level router (FEAT-111 Module 4).

## [parrot.registry.routing.store_router](summaries/mod:parrot.registry.routing.store_router.md)

StoreRouter core orchestrator (FEAT-111 Module 7).

## [parrot.registry.routing.yaml_loader](summaries/mod:parrot.registry.routing.yaml_loader.md)

YAML override loader for ``StoreRouterConfig`` (FEAT-111 Module 2).

## [parrot.registry.storage](summaries/mod:parrot.registry.storage.md)

Redis-backed storage for BotConfig objects.

## [parrot.rerankers](summaries/mod:parrot.rerankers.md)

Reranker subsystem for AI-Parrot.

## [parrot.rerankers.abstract](summaries/mod:parrot.rerankers.abstract.md)

Abstract base class for relevance rerankers.

## [parrot.rerankers.factory](summaries/mod:parrot.rerankers.factory.md)

Factory for creating AbstractReranker instances from a config dict.

## [parrot.rerankers.llm](summaries/mod:parrot.rerankers.llm.md)

LLM-based debug reranker implementation.

## [parrot.rerankers.local](summaries/mod:parrot.rerankers.local.md)

Local cross-encoder reranker implementation.

## [parrot.rerankers.models](summaries/mod:parrot.rerankers.models.md)

Pydantic data models for the reranker subsystem.

## [parrot.scheduler](summaries/mod:parrot.scheduler.md)

Agent Scheduler for AI-Parrot.

## [parrot.scheduler.functions](summaries/mod:parrot.scheduler.functions.md)

Module parrot.scheduler.functions

## [parrot.scheduler.manager](summaries/mod:parrot.scheduler.manager.md)

Agent Scheduler Module for AI-Parrot.

## [parrot.scheduler.models](summaries/mod:parrot.scheduler.models.md)

Module parrot.scheduler.models

## [parrot.security](summaries/mod:parrot.security.md)

Security utilities for AI-Parrot.

## [parrot.security.audit_ledger](summaries/mod:parrot.security.audit_ledger.md)

Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).

## [parrot.security.command_sanitizer](summaries/mod:parrot.security.command_sanitizer.md)

Command Sanitizer — Shared Security Engine (FEAT-252).

## [parrot.security.credentials_utils](summaries/mod:parrot.security.credentials_utils.md)

Credential encryption/decryption helpers for DocumentDB storage.

## [parrot.security.prompt_injection](summaries/mod:parrot.security.prompt_injection.md)

Prompt Injection Detection and Protection.

## [parrot.security.python_sanitizer](summaries/mod:parrot.security.python_sanitizer.md)

Allowlist-first AST gate for Python code executed in the REPL sandbox.

## [parrot.security.query_validator](summaries/mod:parrot.security.query_validator.md)

Query safety validator — shared across ai-parrot and parrot-tools.

## [parrot.security.redaction](summaries/mod:parrot.security.redaction.md)

Utilities for redacting secrets before data leaves trusted process memory.

## [parrot.security.vault_utils](summaries/mod:parrot.security.vault_utils.md)

Vault CRUD helpers — shared encrypted-credential storage for handlers.

## [parrot.server](summaries/mod:parrot.server.md)

AI-Parrot Server package metadata.

## [parrot.server.version](summaries/mod:parrot.server.version.md)

AI-Parrot Server version information.

## [parrot.services](summaries/mod:parrot.services.md)

Parrot service helpers.

## [parrot.services.agent_service](summaries/mod:parrot.services.agent_service.md)

AgentService — standalone asyncio runtime for autonomous AI agents.

## [parrot.services.client](summaries/mod:parrot.services.client.md)

Client for submitting tasks to AgentService via Redis Streams.

## [parrot.services.delivery](summaries/mod:parrot.services.delivery.md)

Delivery routing for task results.

## [parrot.services.heartbeat](summaries/mod:parrot.services.heartbeat.md)

Heartbeat scheduler for periodic agent wake-ups.

## [parrot.services.identity_mapping](summaries/mod:parrot.services.identity_mapping.md)

IdentityMappingService — CRUD for navigator-auth ``user_identities``.

## [parrot.services.models](summaries/mod:parrot.services.models.md)

Pydantic models and configuration for AgentService.

## [parrot.services.redis_listener](summaries/mod:parrot.services.redis_listener.md)

Redis Streams listener for IPC with the web server.

## [parrot.services.task_queue](summaries/mod:parrot.services.task_queue.md)

Priority task queue with optional Redis persistence.

## [parrot.services.vault_token_sync](summaries/mod:parrot.services.vault_token_sync.md)

VaultTokenSync — store and retrieve OAuth tokens in the user's navigator

## [parrot.services.whatsapp](summaries/mod:parrot.services.whatsapp.md)

WhatsApp Configuration API Handler.

## [parrot.services.worker_pool](summaries/mod:parrot.services.worker_pool.md)

Bounded async worker pool for concurrent agent execution.

## [parrot.setup](summaries/mod:parrot.setup.md)

parrot.setup — Interactive first-time setup wizard for AI-Parrot.

## [parrot.setup.cli](summaries/mod:parrot.setup.cli.md)

CLI entry point for the parrot setup wizard.

## [parrot.setup.providers](summaries/mod:parrot.setup.providers.md)

Provider wizard implementations — imported to register BaseClientWizard subclasses.

## [parrot.setup.providers.anthropic](summaries/mod:parrot.setup.providers.anthropic.md)

Anthropic (Claude) provider wizard for parrot setup.

## [parrot.setup.providers.google](summaries/mod:parrot.setup.providers.google.md)

Google (Gemini) provider wizard for parrot setup.

## [parrot.setup.providers.openai](summaries/mod:parrot.setup.providers.openai.md)

OpenAI provider wizard for parrot setup.

## [parrot.setup.providers.openrouter](summaries/mod:parrot.setup.providers.openrouter.md)

OpenRouter provider wizard for parrot setup.

## [parrot.setup.providers.xai](summaries/mod:parrot.setup.providers.xai.md)

xAI (Grok) provider wizard for parrot setup.

## [parrot.setup.scaffolding](summaries/mod:parrot.setup.scaffolding.md)

Scaffolding utilities for the parrot setup wizard.

## [parrot.setup.wizard](summaries/mod:parrot.setup.wizard.md)

Wizard data models and base abstractions for parrot setup.

## [parrot.skills](summaries/mod:parrot.skills.md)

AI-Parrot Skills Module (top-level namespace).

## [parrot.skills.file_registry](summaries/mod:parrot.skills.file_registry.md)

Filesystem-based skill registry with eager loading.

## [parrot.skills.loader](summaries/mod:parrot.skills.loader.md)

SkillsDirectoryLoader — Filesystem discovery for skills.

## [parrot.skills.middleware](summaries/mod:parrot.skills.middleware.md)

Skill trigger middleware for the prompt pipeline.

## [parrot.skills.mixin](summaries/mod:parrot.skills.mixin.md)

SkillRegistryMixin for AbstractBot integration.

## [parrot.skills.models](summaries/mod:parrot.skills.models.md)

SkillRegistry Models for AI-Parrot Framework.

## [parrot.skills.parsers](summaries/mod:parrot.skills.parsers.md)

Skill file parser for .md files with YAML frontmatter.

## [parrot.skills.prompt](summaries/mod:parrot.skills.prompt.md)

Skills Prompt Layer Factory.

## [parrot.skills.store](summaries/mod:parrot.skills.store.md)

SkillRegistry - Git-like versioned skill/knowledge store.

## [parrot.skills.tools](summaries/mod:parrot.skills.tools.md)

SkillRegistry Tools for AI-Parrot Agents.

## [parrot.storage](summaries/mod:parrot.storage.md)

Module parrot.storage

## [parrot.storage.artifact_signing](summaries/mod:parrot.storage.artifact_signing.md)

Shared signing helpers for public infographic artifact URLs (FEAT-197).

## [parrot.storage.artifacts](summaries/mod:parrot.storage.artifacts.md)

High-level artifact CRUD operations.

## [parrot.storage.backends](summaries/mod:parrot.storage.backends.md)

Pluggable ConversationBackend factory and re-exports.

## [parrot.storage.backends.base](summaries/mod:parrot.storage.backends.base.md)

Abstract ConversationBackend interface for pluggable storage.

## [parrot.storage.backends.dynamodb](summaries/mod:parrot.storage.backends.dynamodb.md)

DynamoDB backend implementing ConversationBackend.

## [parrot.storage.backends.mongodb](summaries/mod:parrot.storage.backends.mongodb.md)

MongoDB conversation backend using motor (via asyncdb[mongo]).

## [parrot.storage.backends.postgres](summaries/mod:parrot.storage.backends.postgres.md)

PostgreSQL conversation backend using asyncpg via asyncdb[pg].

## [parrot.storage.backends.sqlite](summaries/mod:parrot.storage.backends.sqlite.md)

SQLite conversation backend — zero-dependency local storage.

## [parrot.storage.chat](summaries/mod:parrot.storage.chat.md)

Unified hot+cold chat storage.

## [parrot.storage.dynamodb](summaries/mod:parrot.storage.dynamodb.md)

Backward-compatible re-export shim for ConversationDynamoDB.

## [parrot.storage.instrumented](summaries/mod:parrot.storage.instrumented.md)

InstrumentedBackend — transparent ConversationBackend wrapper.

## [parrot.storage.metrics](summaries/mod:parrot.storage.metrics.md)

StorageMetrics protocol and no-op default implementation.

## [parrot.storage.models](summaries/mod:parrot.storage.models.md)

Data models for chat persistence.

## [parrot.storage.overflow](summaries/mod:parrot.storage.overflow.md)

Generic artifact overflow store backed by any FileManagerInterface.

## [parrot.storage.s3_overflow](summaries/mod:parrot.storage.s3_overflow.md)

S3 Overflow Manager — backward-compatible subclass of OverflowStore.

## [parrot.storage.security_reports](summaries/mod:parrot.storage.security_reports.md)

Cross-session security report catalog — storage layer.

## [parrot.storage.security_reports.models](summaries/mod:parrot.storage.security_reports.models.md)

Pydantic v2 data models for the cross-session security report catalog.

## [parrot.storage.security_reports.store](summaries/mod:parrot.storage.security_reports.store.md)

SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation.

## [parrot.stores](summaries/mod:parrot.stores.md)

Module parrot.stores

## [parrot.stores.abstract](summaries/mod:parrot.stores.abstract.md)

Module parrot.stores.abstract

## [parrot.stores.arango](summaries/mod:parrot.stores.arango.md)

ArangoDBStore: Vector Store implementation for ArangoDB.

## [parrot.stores.bigquery](summaries/mod:parrot.stores.bigquery.md)

Module parrot.stores.bigquery

## [parrot.stores.cache](summaries/mod:parrot.stores.cache.md)

Module parrot.stores.cache

## [parrot.stores.empty](summaries/mod:parrot.stores.empty.md)

Module parrot.stores.empty

## [parrot.stores.faiss_store](summaries/mod:parrot.stores.faiss_store.md)

FAISSStore: In-memory Vector Store implementation using FAISS.

## [parrot.stores.kb](summaries/mod:parrot.stores.kb.md)

Module parrot.stores.kb

## [parrot.stores.kb.abstract](summaries/mod:parrot.stores.kb.abstract.md)

Module parrot.stores.kb.abstract

## [parrot.stores.kb.cache](summaries/mod:parrot.stores.kb.cache.md)

Module parrot.stores.kb.cache

## [parrot.stores.kb.doc](summaries/mod:parrot.stores.kb.doc.md)

Module parrot.stores.kb.doc

## [parrot.stores.kb.hierarchy](summaries/mod:parrot.stores.kb.hierarchy.md)

Module parrot.stores.kb.hierarchy

## [parrot.stores.kb.local](summaries/mod:parrot.stores.kb.local.md)

LocalKB: Knowledge Base from local text and markdown files with FAISS vector store.

## [parrot.stores.kb.prompt](summaries/mod:parrot.stores.kb.prompt.md)

Module parrot.stores.kb.prompt

## [parrot.stores.kb.redis](summaries/mod:parrot.stores.kb.redis.md)

Redis-backed knowledge base primitives.

## [parrot.stores.kb.store](summaries/mod:parrot.stores.kb.store.md)

KnowledgeBaseStore — In-memory fact store with FAISS-backed similarity search.

## [parrot.stores.kb.user](summaries/mod:parrot.stores.kb.user.md)

Module parrot.stores.kb.user

## [parrot.stores.milvus](summaries/mod:parrot.stores.milvus.md)

MilvusStore: Vector Store implementation using Milvus.

## [parrot.stores.models](summaries/mod:parrot.stores.models.md)

Store data models.

## [parrot.stores.multimodal_schema](summaries/mod:parrot.stores.multimodal_schema.md)

Multimodal Collection Schema for PgVector.

## [parrot.stores.parents](summaries/mod:parrot.stores.parents.md)

Parent document searcher package for FEAT-128 — Parent-Child Retrieval.

## [parrot.stores.parents.abstract](summaries/mod:parrot.stores.parents.abstract.md)

Abstract base class for parent document searchers.

## [parrot.stores.parents.factory](summaries/mod:parrot.stores.parents.factory.md)

Factory for creating AbstractParentSearcher instances from a config dict.

## [parrot.stores.parents.in_table](summaries/mod:parrot.stores.parents.in_table.md)

In-table parent searcher for pgvector stores.

## [parrot.stores.pgvector](summaries/mod:parrot.stores.pgvector.md)

Module parrot.stores.pgvector

## [parrot.stores.postgres](summaries/mod:parrot.stores.postgres.md)

Module parrot.stores.postgres

## [parrot.stores.utils](summaries/mod:parrot.stores.utils.md)

Module parrot.stores.utils

## [parrot.stores.utils.chunking](summaries/mod:parrot.stores.utils.chunking.md)

Module parrot.stores.utils.chunking

## [parrot.stores.utils.contextual](summaries/mod:parrot.stores.utils.contextual.md)

Contextual embedding header helper.

## [parrot.template](summaries/mod:parrot.template.md)

Module parrot.template

## [parrot.template.engine](summaries/mod:parrot.template.engine.md)

Module parrot.template.engine

## [parrot.tools](summaries/mod:parrot.tools.md)

Tools infrastructure for building Agents.

## [parrot.tools._enhance_html_check](summaries/mod:parrot.tools._enhance_html_check.md)

HTML validator for LLM-enhanced output (FEAT-197, TASK-1325).

## [parrot.tools.abstract](summaries/mod:parrot.tools.abstract.md)

Abstract Tool base class for all function-calling tools.in ai-parrot framework.

## [parrot.tools.agent](summaries/mod:parrot.tools.agent.md)

Complete Fixed AgentTool with Correct Schema Structure

## [parrot.tools.database](summaries/mod:parrot.tools.database.md)

Deprecated alias — use ``parrot.tools.databasequery`` instead.

## [parrot.tools.databasequery](summaries/mod:parrot.tools.databasequery.md)

parrot.tools.databasequery — Public exports for the database query tools package.

## [parrot.tools.databasequery.base](summaries/mod:parrot.tools.databasequery.base.md)

DatabaseToolkit — Result Types & AbstractDatabaseSource.

## [parrot.tools.databasequery.sources](summaries/mod:parrot.tools.databasequery.sources.md)

DatabaseToolkit — Source Registry & Driver Alias Resolution.

## [parrot.tools.databasequery.sources.atlas](summaries/mod:parrot.tools.databasequery.sources.atlas.md)

MongoDB Atlas database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.bigquery](summaries/mod:parrot.tools.databasequery.sources.bigquery.md)

BigQuery database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.clickhouse](summaries/mod:parrot.tools.databasequery.sources.clickhouse.md)

ClickHouse database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.documentdb](summaries/mod:parrot.tools.databasequery.sources.documentdb.md)

AWS DocumentDB database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.duckdb](summaries/mod:parrot.tools.databasequery.sources.duckdb.md)

DuckDB database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.elastic](summaries/mod:parrot.tools.databasequery.sources.elastic.md)

Elasticsearch/OpenSearch database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.influx](summaries/mod:parrot.tools.databasequery.sources.influx.md)

InfluxDB time-series database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.mongodb](summaries/mod:parrot.tools.databasequery.sources.mongodb.md)

MongoDB database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.mssql](summaries/mod:parrot.tools.databasequery.sources.mssql.md)

Microsoft SQL Server database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.mysql](summaries/mod:parrot.tools.databasequery.sources.mysql.md)

MySQL database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.oracle](summaries/mod:parrot.tools.databasequery.sources.oracle.md)

Oracle database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.postgres](summaries/mod:parrot.tools.databasequery.sources.postgres.md)

PostgreSQL database source for DatabaseToolkit.

## [parrot.tools.databasequery.sources.sqlite](summaries/mod:parrot.tools.databasequery.sources.sqlite.md)

SQLite database source for DatabaseToolkit.

## [parrot.tools.databasequery.tool](summaries/mod:parrot.tools.databasequery.tool.md)

Database Query Tool migrated to use AbstractTool framework.

## [parrot.tools.databasequery.toolkit](summaries/mod:parrot.tools.databasequery.toolkit.md)

DatabaseQueryToolkit — Multi-database tools as an AbstractToolkit.

## [parrot.tools.dataset_manager](summaries/mod:parrot.tools.dataset_manager.md)

DatasetManager subpackage.

## [parrot.tools.dataset_manager.computed](summaries/mod:parrot.tools.dataset_manager.computed.md)

Computed Columns for DatasetManager.

## [parrot.tools.dataset_manager.csv_reader](summaries/mod:parrot.tools.dataset_manager.csv_reader.md)

CSV-to-markdown converter for DatasetManager file loading.

## [parrot.tools.dataset_manager.excel_analyzer](summaries/mod:parrot.tools.dataset_manager.excel_analyzer.md)

Excel Structure Analysis Engine.

## [parrot.tools.dataset_manager.filtering](summaries/mod:parrot.tools.dataset_manager.filtering.md)

DatasetManager common-field filtering sub-package (FEAT-225).

## [parrot.tools.dataset_manager.filtering.compiler](summaries/mod:parrot.tools.dataset_manager.filtering.compiler.md)

Filter Compiler for FEAT-225 Module 3.

## [parrot.tools.dataset_manager.filtering.contracts](summaries/mod:parrot.tools.dataset_manager.filtering.contracts.md)

Pure Pydantic contracts for common-field filtering (FEAT-225 Module 1).

## [parrot.tools.dataset_manager.filtering.store](summaries/mod:parrot.tools.dataset_manager.filtering.store.md)

Pure validation helpers for the FilterDefinition instance store (FEAT-225 Module 2).

## [parrot.tools.dataset_manager.filtering.values](summaries/mod:parrot.tools.dataset_manager.filtering.values.md)

Value catalog helpers for FEAT-225 Module 5.

## [parrot.tools.dataset_manager.sources](summaries/mod:parrot.tools.dataset_manager.sources.md)

DataSource implementations for DatasetManager.

## [parrot.tools.dataset_manager.sources.airtable](summaries/mod:parrot.tools.dataset_manager.sources.airtable.md)

Airtable DataSource implementation.

## [parrot.tools.dataset_manager.sources.authorizing](summaries/mod:parrot.tools.dataset_manager.sources.authorizing.md)

AuthorizingDataSource — DataSource decorator for FEAT-228.

## [parrot.tools.dataset_manager.sources.base](summaries/mod:parrot.tools.dataset_manager.sources.base.md)

DataSource abstract base class.

## [parrot.tools.dataset_manager.sources.composite](summaries/mod:parrot.tools.dataset_manager.sources.composite.md)

CompositeDataSource — virtual dataset that JOINs two or more existing datasets.

## [parrot.tools.dataset_manager.sources.deltatable](summaries/mod:parrot.tools.dataset_manager.sources.deltatable.md)

DeltaTableSource — DataSource subclass for Delta Lake tables.

## [parrot.tools.dataset_manager.sources.dialects](summaries/mod:parrot.tools.dataset_manager.sources.dialects.md)

Driver–Dialect Map for FEAT-228 Data-Plane Authorization.

## [parrot.tools.dataset_manager.sources.iceberg](summaries/mod:parrot.tools.dataset_manager.sources.iceberg.md)

IcebergSource — DataSource subclass for Apache Iceberg tables.

## [parrot.tools.dataset_manager.sources.memory](summaries/mod:parrot.tools.dataset_manager.sources.memory.md)

InMemorySource — wraps an already-loaded pd.DataFrame as a DataSource.

## [parrot.tools.dataset_manager.sources.mongo](summaries/mod:parrot.tools.dataset_manager.sources.mongo.md)

MongoSource — DataSource subclass for MongoDB/DocumentDB collections.

## [parrot.tools.dataset_manager.sources.opaque](summaries/mod:parrot.tools.dataset_manager.sources.opaque.md)

Opaque-Source Resolvers for FEAT-228 Data-Plane Authorization.

## [parrot.tools.dataset_manager.sources.query_slug](summaries/mod:parrot.tools.dataset_manager.sources.query_slug.md)

QuerySlugSource and MultiQuerySlugSource implementations.

## [parrot.tools.dataset_manager.sources.resolver](summaries/mod:parrot.tools.dataset_manager.sources.resolver.md)

Physical-Resource Resolver for FEAT-228 Data-Plane Authorization.

## [parrot.tools.dataset_manager.sources.rls](summaries/mod:parrot.tools.dataset_manager.sources.rls.md)

RLS Predicate Injection for FEAT-228 Data-Plane Authorization.

## [parrot.tools.dataset_manager.sources.smartsheet](summaries/mod:parrot.tools.dataset_manager.sources.smartsheet.md)

Smartsheet DataSource implementation.

## [parrot.tools.dataset_manager.sources.sql](summaries/mod:parrot.tools.dataset_manager.sources.sql.md)

SQLQuerySource — user-provided SQL with {param} interpolation.

## [parrot.tools.dataset_manager.sources.table](summaries/mod:parrot.tools.dataset_manager.sources.table.md)

TableSource — schema-prefetch DataSource for database tables.

## [parrot.tools.dataset_manager.spatial](summaries/mod:parrot.tools.dataset_manager.spatial.md)

Spatial filtering support for DatasetManager (FEAT-219).

## [parrot.tools.dataset_manager.spatial._ibis_probe](summaries/mod:parrot.tools.dataset_manager.spatial._ibis_probe.md)

THROWAWAY: Ibis connection spike for FEAT-219 Module 2.

## [parrot.tools.dataset_manager.spatial.compiler](summaries/mod:parrot.tools.dataset_manager.spatial.compiler.md)

SpatialCompiler — compile and execute spatial filter queries (FEAT-219).

## [parrot.tools.dataset_manager.spatial.contracts](summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md)

Pure Pydantic contracts for spatial filtering (FEAT-219 Module 1).

## [parrot.tools.dataset_manager.spatial.registry](summaries/mod:parrot.tools.dataset_manager.spatial.registry.md)

SPATIAL_PROFILE_REGISTRY — standalone profile store for DatasetManager spatial queries.

## [parrot.tools.dataset_manager.tool](summaries/mod:parrot.tools.dataset_manager.tool.md)

DatasetManager: A Toolkit and Data Catalog for PandasAgent.

## [parrot.tools.decorators](summaries/mod:parrot.tools.decorators.md)

Module parrot.tools.decorators

## [parrot.tools.discovery](summaries/mod:parrot.tools.discovery.md)

Multi-source tool discovery for ToolManager.

## [parrot.tools.excel_intelligence](summaries/mod:parrot.tools.excel_intelligence.md)

ExcelIntelligenceToolkit — LLM-callable tools for Excel file analysis.

## [parrot.tools.executors](summaries/mod:parrot.tools.executors.md)

Remote tool executors for AI-Parrot.

## [parrot.tools.executors.abstract](summaries/mod:parrot.tools.executors.abstract.md)

Abstract executor interface and serializable envelope.

## [parrot.tools.executors.k8s](summaries/mod:parrot.tools.executors.k8s.md)

Kubernetes-backed remote tool executor.

## [parrot.tools.executors.local](summaries/mod:parrot.tools.executors.local.md)

In-process reference executor.

## [parrot.tools.executors.qworker](summaries/mod:parrot.tools.executors.qworker.md)

Qworker-backed remote tool executor.

## [parrot.tools.executors.runner](summaries/mod:parrot.tools.executors.runner.md)

In-process envelope runner shared by LocalToolExecutor and the k8s/qworker worker entrypoints.

## [parrot.tools.filemanager](summaries/mod:parrot.tools.filemanager.md)

FileManagerTool and FileManagerToolkit — tools for AI agents to interact with file systems.

## [parrot.tools.infographic_toolkit](summaries/mod:parrot.tools.infographic_toolkit.md)

InfographicToolkit — Frozen multi-dataset HTML infographic artifacts (FEAT-197).

## [parrot.tools.interactive](summaries/mod:parrot.tools.interactive.md)

Interactive HTML artifact catalog (libraries + scaffold templates).

## [parrot.tools.interactive.catalog_registry](summaries/mod:parrot.tools.interactive.catalog_registry.md)

On-disk loader for the interactive HTML artifact catalog.

## [parrot.tools.interactive_toolkit](summaries/mod:parrot.tools.interactive_toolkit.md)

InteractiveToolkit — free-form, self-contained interactive HTML artifacts.

## [parrot.tools.jira_connect_tool](summaries/mod:parrot.tools.jira_connect_tool.md)

Placeholder tool and session helpers for Jira OAuth 2.0 (3LO) in AgenTalk.

## [parrot.tools.json_tool](summaries/mod:parrot.tools.json_tool.md)

Module parrot.tools.json_tool

## [parrot.tools.manager](summaries/mod:parrot.tools.manager.md)

Module parrot.tools.manager

## [parrot.tools.mcp_mixin](summaries/mod:parrot.tools.mcp_mixin.md)

MCP Tool Manager Mixin - Adds MCP server capabilities to ToolManager.

## [parrot.tools.openapitoolkit](summaries/mod:parrot.tools.openapitoolkit.md)

OpenAPIToolkit - Dynamic toolkit that exposes OpenAPI services as tools.

## [parrot.tools.pythonpandas](summaries/mod:parrot.tools.pythonpandas.md)

Module parrot.tools.pythonpandas

## [parrot.tools.pythonrepl](summaries/mod:parrot.tools.pythonrepl.md)

PythonREPLTool migrated to use AbstractTool framework with matplotlib fixes.

## [parrot.tools.registry](summaries/mod:parrot.tools.registry.md)

Toolkit Registry - Registry of supported toolkits for dynamic loading.

## [parrot.tools.reminder](summaries/mod:parrot.tools.reminder.md)

One-time reminder tooling for agents — FEAT-115.

## [parrot.tools.spawn](summaries/mod:parrot.tools.spawn.md)

SpawnSubAgentTool — ephemeral sub-agent spawner (FEAT-208).

## [parrot.tools.stub_credentialed_tool](summaries/mod:parrot.tools.stub_credentialed_tool.md)

Stub credentialed tool for FEAT-260 v1 acceptance testing.

## [parrot.tools.toolkit](summaries/mod:parrot.tools.toolkit.md)

AbstractToolkit for creating collections of tools from class methods.

## [parrot.tools.vectorstoresearch](summaries/mod:parrot.tools.vectorstoresearch.md)

VectorStoreSearchTool - A tool for performing similarity search on vector stores.

## [parrot.tools.working_memory](summaries/mod:parrot.tools.working_memory.md)

WorkingMemoryToolkit — intermediate result store for analytical operations.

## [parrot.tools.working_memory.conftest](summaries/mod:parrot.tools.working_memory.conftest.md)

Conftest for working_memory package tests.

## [parrot.tools.working_memory.internals](summaries/mod:parrot.tools.working_memory.internals.md)

Internal engine classes for WorkingMemoryToolkit.

## [parrot.tools.working_memory.models](summaries/mod:parrot.tools.working_memory.models.md)

Enums and Pydantic input models for WorkingMemoryToolkit DSL.

## [parrot.tools.working_memory.tests](summaries/mod:parrot.tools.working_memory.tests.md)

Tests for WorkingMemoryToolkit v2 (AbstractToolkit-compatible).

## [parrot.tools.working_memory.tests.conftest](summaries/mod:parrot.tools.working_memory.tests.conftest.md)

Shared fixtures for WorkingMemoryToolkit tests.

## [parrot.tools.working_memory.tests.test_answer_memory_bridge](summaries/mod:parrot.tools.working_memory.tests.test_answer_m-4c0e1fe7.md)

Tests for the AnswerMemory bridge in WorkingMemoryToolkit.

## [parrot.tools.working_memory.tests.test_generic_entries](summaries/mod:parrot.tools.working_memory.tests.test_generic_entries.md)

Tests for generic (non-DataFrame) entry support in WorkingMemoryToolkit.

## [parrot.tools.working_memory.tests.test_integration_workflow](summaries/mod:parrot.tools.working_memory.tests.test_integrat-6aef4846.md)

Integration tests for WorkingMemoryToolkit FEAT-074 changes.

## [parrot.tools.working_memory.tests.test_thread_offload](summaries/mod:parrot.tools.working_memory.tests.test_thread_offload.md)

Tests for the CPU-bound thread-offload optimisation in WorkingMemoryToolkit.

## [parrot.tools.working_memory.tests.test_working_memory](summaries/mod:parrot.tools.working_memory.tests.test_working_memory.md)

Tests for WorkingMemoryToolkit.

## [parrot.tools.working_memory.tool](summaries/mod:parrot.tools.working_memory.tool.md)

WorkingMemoryToolkit: Intermediate result store for long-running analytical operations.

## [parrot.tools.workiq_tool](summaries/mod:parrot.tools.workiq_tool.md)

Work IQ MCP credential adapter tool for the A2A per-user credential bridge.

## [parrot.utils](summaries/mod:parrot.utils.md)

Module parrot.utils

## [parrot.utils.faiss_logging](summaries/mod:parrot.utils.faiss_logging.md)

Quiet FAISS's own import-time boot chatter.

## [parrot.utils.helpers](summaries/mod:parrot.utils.helpers.md)

Module parrot.utils.helpers

## [parrot.utils.jsonld_extractors](summaries/mod:parrot.utils.jsonld_extractors.md)

JSON-LD extractor functions and data model for WebScrapingLoader.

## [parrot.utils.naming](summaries/mod:parrot.utils.naming.md)

Name normalization utilities for bot/agent creation.

## [parrot.utils.parsers](summaries/mod:parrot.utils.parsers.md)

Module parrot.utils.parsers

## [parrot.utils.toml](summaries/mod:parrot.utils.toml.md)

Module parrot.utils.toml

## [parrot.utils.uv](summaries/mod:parrot.utils.uv.md)

Module parrot.utils.uv

## [parrot.version](summaries/mod:parrot.version.md)

Nav Parrot Meta information.

## [parrot.voice](summaries/mod:parrot.voice.md)

Shared Voice Module.

## [parrot.voice.handler](summaries/mod:parrot.voice.handler.md)

VoiceChatHandler - WebSocket Handler with Authentication

## [parrot.voice.models](summaries/mod:parrot.voice.models.md)

Voice Module Data Models

## [parrot.voice.transcriber](summaries/mod:parrot.voice.transcriber.md)

Shared Voice Transcription Module.

## [parrot.voice.transcriber.backend](summaries/mod:parrot.voice.transcriber.backend.md)

Abstract Transcriber Backend.

## [parrot.voice.transcriber.faster_whisper_backend](summaries/mod:parrot.voice.transcriber.faster_whisper_backend.md)

Faster Whisper Backend for Voice Transcription.

## [parrot.voice.transcriber.models](summaries/mod:parrot.voice.transcriber.models.md)

Voice Transcription Data Models.

## [parrot.voice.transcriber.moonshine_backend](summaries/mod:parrot.voice.transcriber.moonshine_backend.md)

Moonshine STT Backend.

## [parrot.voice.transcriber.openai_backend](summaries/mod:parrot.voice.transcriber.openai_backend.md)

OpenAI Whisper Backend for Voice Transcription.

## [parrot.voice.transcriber.transcriber](summaries/mod:parrot.voice.transcriber.transcriber.md)

Voice Transcriber Service.

## [parrot.voice.tts](summaries/mod:parrot.voice.tts.md)

TTS (Text-to-Speech) Module.

## [parrot.voice.tts.backend](summaries/mod:parrot.voice.tts.backend.md)

Abstract TTS Backend.

## [parrot.voice.tts.google_backend](summaries/mod:parrot.voice.tts.google_backend.md)

Google TTS Backend.

## [parrot.voice.tts.models](summaries/mod:parrot.voice.tts.models.md)

TTS Data Models.

## [parrot.voice.tts.supertonic_backend](summaries/mod:parrot.voice.tts.supertonic_backend.md)

Supertonic TTS Backend.

## [parrot.voice.tts.supertonic_inference](summaries/mod:parrot.voice.tts.supertonic_inference.md)

Supertonic ONNX inference wiring (4-graph flow-matching TTS).

## [parrot.voice.tts.synthesizer](summaries/mod:parrot.voice.tts.synthesizer.md)

Voice Synthesizer Service.

## [parrot.yaml-rs.python.yaml_rs](summaries/mod:parrot.yaml-rs.python.yaml_rs.md)

Module parrot.yaml-rs.python.yaml_rs

## [parrot_formdesigner](summaries/mod:parrot_formdesigner.md)

parrot-formdesigner — Form design and rendering for AI-Parrot.

## [parrot_formdesigner.api](summaries/mod:parrot_formdesigner.api.md)

parrot_formdesigner.api — JSON REST surface.

## [parrot_formdesigner.api._utils](summaries/mod:parrot_formdesigner.api._utils.md)

Shared utility helpers for the JSON REST API surface.

## [parrot_formdesigner.api.audio_ws](summaries/mod:parrot_formdesigner.api.audio_ws.md)

AudioFormWSHandler — WebSocket handler for interactive audio form sessions.

## [parrot_formdesigner.api.controls](summaries/mod:parrot_formdesigner.api.controls.md)

HTTP handler for ``GET /api/v1/form-controls``.

## [parrot_formdesigner.api.handlers](summaries/mod:parrot_formdesigner.api.handlers.md)

JSON REST API handlers for parrot-formdesigner.

## [parrot_formdesigner.api.operations](summaries/mod:parrot_formdesigner.api.operations.md)

``PATCH /api/v1/forms/{form_id}/operations`` — atomic batched-edit endpoint.

## [parrot_formdesigner.api.render](summaries/mod:parrot_formdesigner.api.render.md)

Render dispatcher for parrot-formdesigner.

## [parrot_formdesigner.api.routes](summaries/mod:parrot_formdesigner.api.routes.md)

Route registration for the JSON REST surface of parrot-formdesigner.

## [parrot_formdesigner.api.uploads](summaries/mod:parrot_formdesigner.api.uploads.md)

REST field upload handler for FormDesigner (FEAT-170).

## [parrot_formdesigner.audio](summaries/mod:parrot_formdesigner.audio.md)

Audio form session subpackage for parrot-formdesigner.

## [parrot_formdesigner.audio.models](summaries/mod:parrot_formdesigner.audio.models.md)

Audio form session data models for parrot-formdesigner.

## [parrot_formdesigner.controls](summaries/mod:parrot_formdesigner.controls.md)

Form-control registry — extensible toolbar metadata.

## [parrot_formdesigner.controls.builtin](summaries/mod:parrot_formdesigner.controls.builtin.md)

Built-in form-control seed.

## [parrot_formdesigner.controls.registry](summaries/mod:parrot_formdesigner.controls.registry.md)

Form-control registry.

## [parrot_formdesigner.core](summaries/mod:parrot_formdesigner.core.md)

Core form models for parrot-formdesigner.

## [parrot_formdesigner.core._location_data](summaries/mod:parrot_formdesigner.core._location_data.md)

Offline country reference data via pycountry.

## [parrot_formdesigner.core.auth](summaries/mod:parrot_formdesigner.core.auth.md)

Authentication configuration models for form submission forwarding.

## [parrot_formdesigner.core.constraints](summaries/mod:parrot_formdesigner.core.constraints.md)

Field constraints and conditional visibility rules for form fields.

## [parrot_formdesigner.core.events](summaries/mod:parrot_formdesigner.core.events.md)

Form lifecycle event models for parrot-formdesigner.

## [parrot_formdesigner.core.options](summaries/mod:parrot_formdesigner.core.options.md)

Field option definitions for select and multi-select fields.

## [parrot_formdesigner.core.partial](summaries/mod:parrot_formdesigner.core.partial.md)

Ephemeral partial form answer cache model.

## [parrot_formdesigner.core.schema](summaries/mod:parrot_formdesigner.core.schema.md)

Core form schema data models.

## [parrot_formdesigner.core.style](summaries/mod:parrot_formdesigner.core.style.md)

Form presentation and layout style models.

## [parrot_formdesigner.core.types](summaries/mod:parrot_formdesigner.core.types.md)

Core type definitions for the formdesigner package.

## [parrot_formdesigner.extractors](summaries/mod:parrot_formdesigner.extractors.md)

Form schema extractors for the formdesigner package.

## [parrot_formdesigner.extractors.jsonschema](summaries/mod:parrot_formdesigner.extractors.jsonschema.md)

JSON Schema extractor for FormSchema generation.

## [parrot_formdesigner.extractors.pydantic](summaries/mod:parrot_formdesigner.extractors.pydantic.md)

Pydantic model extractor for FormSchema generation.

## [parrot_formdesigner.extractors.tool](summaries/mod:parrot_formdesigner.extractors.tool.md)

Tool extractor for FormSchema generation from AbstractTool instances.

## [parrot_formdesigner.extractors.yaml](summaries/mod:parrot_formdesigner.extractors.yaml.md)

YAML extractor for FormSchema generation.

## [parrot_formdesigner.renderers](summaries/mod:parrot_formdesigner.renderers.md)

Form renderers for the forms abstraction layer.

## [parrot_formdesigner.renderers.adaptive_card](summaries/mod:parrot_formdesigner.renderers.adaptive_card.md)

Adaptive Card renderer for FormSchema.

## [parrot_formdesigner.renderers.audio](summaries/mod:parrot_formdesigner.renderers.audio.md)

AudioFormRenderer — Standalone audio form renderer for parrot-formdesigner.

## [parrot_formdesigner.renderers.base](summaries/mod:parrot_formdesigner.renderers.base.md)

Abstract base class for form renderers.

## [parrot_formdesigner.renderers.fields](summaries/mod:parrot_formdesigner.renderers.fields.md)

Per-field renderer implementations for parrot-formdesigner.

## [parrot_formdesigner.renderers.fields.audio](summaries/mod:parrot_formdesigner.renderers.fields.audio.md)

AudioFieldRenderer — HTML5 field renderer for FieldType.AUDIO.

## [parrot_formdesigner.renderers.html5](summaries/mod:parrot_formdesigner.renderers.html5.md)

HTML5 form renderer for FormSchema.

## [parrot_formdesigner.renderers.jsonschema](summaries/mod:parrot_formdesigner.renderers.jsonschema.md)

JSON Schema renderer for FormSchema.

## [parrot_formdesigner.renderers.pdf](summaries/mod:parrot_formdesigner.renderers.pdf.md)

PDF AcroForm fillable renderer for ``FormSchema`` (FEAT-152 Wave 2b).

## [parrot_formdesigner.renderers.telegram](summaries/mod:parrot_formdesigner.renderers.telegram.md)

Telegram renderer for parrot-formdesigner.

## [parrot_formdesigner.renderers.telegram.models](summaries/mod:parrot_formdesigner.renderers.telegram.models.md)

Data models for the Telegram form renderer.

## [parrot_formdesigner.renderers.telegram.renderer](summaries/mod:parrot_formdesigner.renderers.telegram.renderer.md)

Telegram form renderer.

## [parrot_formdesigner.renderers.telegram.router](summaries/mod:parrot_formdesigner.renderers.telegram.router.md)

Telegram form conversation router.

## [parrot_formdesigner.renderers.xforms](summaries/mod:parrot_formdesigner.renderers.xforms.md)

XForms 1.1 (W3C) exporter for ``FormSchema``.

## [parrot_formdesigner.services](summaries/mod:parrot_formdesigner.services.md)

Form services for parrot-formdesigner.

## [parrot_formdesigner.services._db_utils](summaries/mod:parrot_formdesigner.services._db_utils.md)

Shared database utilities for parrot-formdesigner services.

## [parrot_formdesigner.services._identifiers](summaries/mod:parrot_formdesigner.services._identifiers.md)

Postgres identifier validation helpers.

## [parrot_formdesigner.services.auth_context](summaries/mod:parrot_formdesigner.services.auth_context.md)

Runtime authentication context for per-request credential resolution.

## [parrot_formdesigner.services.blob_storage](summaries/mod:parrot_formdesigner.services.blob_storage.md)

Async blob storage abstraction for FieldType.REST uploads.

## [parrot_formdesigner.services.cache](summaries/mod:parrot_formdesigner.services.cache.md)

Form Cache for the forms abstraction layer.

## [parrot_formdesigner.services.callback_registry](summaries/mod:parrot_formdesigner.services.callback_registry.md)

Tenant-scoped form callback registry for FieldType.REST (mode=callback).

## [parrot_formdesigner.services.csrf](summaries/mod:parrot_formdesigner.services.csrf.md)

CSRF token utilities for the remote events endpoint — FEAT-188.

## [parrot_formdesigner.services.event_dispatcher](summaries/mod:parrot_formdesigner.services.event_dispatcher.md)

Form lifecycle event dispatcher — FEAT-188.

## [parrot_formdesigner.services.event_registry](summaries/mod:parrot_formdesigner.services.event_registry.md)

Tenant-scoped form lifecycle event handler registry (FEAT-188).

## [parrot_formdesigner.services.fieldsync_schema](summaries/mod:parrot_formdesigner.services.fieldsync_schema.md)

DDL canónico para el schema ``fieldsync`` — idempotente, sin migraciones.

## [parrot_formdesigner.services.form_version](summaries/mod:parrot_formdesigner.services.form_version.md)

FormVersionService — immutable semver publishing for FormSchema objects.

## [parrot_formdesigner.services.forwarder](summaries/mod:parrot_formdesigner.services.forwarder.md)

Submission forwarding service.

## [parrot_formdesigner.services.metadata_callbacks](summaries/mod:parrot_formdesigner.services.metadata_callbacks.md)

Pydantic I/O models for submission metadata callbacks.

## [parrot_formdesigner.services.metadata_enricher](summaries/mod:parrot_formdesigner.services.metadata_enricher.md)

Before-save submission metadata enrichment.

## [parrot_formdesigner.services.metadata_sources](summaries/mod:parrot_formdesigner.services.metadata_sources.md)

Built-in resolvers for ``FormMetadataField`` sources.

## [parrot_formdesigner.services.options_loader](summaries/mod:parrot_formdesigner.services.options_loader.md)

OptionsLoader service for dynamic field option fetching.

## [parrot_formdesigner.services.org_graph](summaries/mod:parrot_formdesigner.services.org_graph.md)

OrgGraphService — árbol multi-jerarquía read-only sobre auth.* + geografía.

## [parrot_formdesigner.services.partial_saves](summaries/mod:parrot_formdesigner.services.partial_saves.md)

Redis-backed ephemeral storage for partial form answers.

## [parrot_formdesigner.services.project_service](summaries/mod:parrot_formdesigner.services.project_service.md)

ProjectService — CRUD sobre ``fieldsync.projects`` + mapping Workday.

## [parrot_formdesigner.services.public_forms](summaries/mod:parrot_formdesigner.services.public_forms.md)

Helper for computing auth-exempt URL patterns for public forms (FEAT-241).

## [parrot_formdesigner.services.question_bank](summaries/mod:parrot_formdesigner.services.question_bank.md)

QuestionBankService — tenant-scoped library of reusable field definitions.

## [parrot_formdesigner.services.rbac](summaries/mod:parrot_formdesigner.services.rbac.md)

RBACService — policies ABAC/PBAC (nav-auth format) + RBACContext.

## [parrot_formdesigner.services.registry](summaries/mod:parrot_formdesigner.services.registry.md)

Form Registry for the forms abstraction layer.

## [parrot_formdesigner.services.remote_response_resolver](summaries/mod:parrot_formdesigner.services.remote_response_resolver.md)

RemoteResponseResolver service for REMOTE_RESPONSE field type.

## [parrot_formdesigner.services.rest_field_resolver](summaries/mod:parrot_formdesigner.services.rest_field_resolver.md)

RestFieldResolver service for FieldType.REST form fields.

## [parrot_formdesigner.services.rule_evaluator](summaries/mod:parrot_formdesigner.services.rule_evaluator.md)

Authoritative server-side rule evaluator for FormSchema conditional sections.

## [parrot_formdesigner.services.storage](summaries/mod:parrot_formdesigner.services.storage.md)

PostgreSQL Form Storage for the forms abstraction layer.

## [parrot_formdesigner.services.submissions](summaries/mod:parrot_formdesigner.services.submissions.md)

Form submission persistence service.

## [parrot_formdesigner.services.validators](summaries/mod:parrot_formdesigner.services.validators.md)

Platform-agnostic form validation for FormSchema.

## [parrot_formdesigner.services.venue_service](summaries/mod:parrot_formdesigner.services.venue_service.md)

VenueService — CRUD sobre ``fieldsync.sites`` / ``fieldsync.locations``.

## [parrot_formdesigner.services.workday_sync](summaries/mod:parrot_formdesigner.services.workday_sync.md)

WorkdayIdentitySyncAdapter — stub de sincronización de identidades con Workday.

## [parrot_formdesigner.tools](summaries/mod:parrot_formdesigner.tools.md)

Form tools for the forms abstraction layer.

## [parrot_formdesigner.tools.create_form](summaries/mod:parrot_formdesigner.tools.create_form.md)

CreateFormTool — LLM-driven form generation tool.

## [parrot_formdesigner.tools.database_form](summaries/mod:parrot_formdesigner.tools.database_form.md)

DatabaseFormTool — thin dispatcher over an AbstractFormService.

## [parrot_formdesigner.tools.edit_toolkit](summaries/mod:parrot_formdesigner.tools.edit_toolkit.md)

EditToolkit — LLM-callable toolkit for surgical FormSchema editing.

## [parrot_formdesigner.tools.field_helpers](summaries/mod:parrot_formdesigner.tools.field_helpers.md)

Helper utilities for supported form field definitions.

## [parrot_formdesigner.tools.request_form](summaries/mod:parrot_formdesigner.tools.request_form.md)

RequestFormTool — platform-agnostic form request tool.

## [parrot_formdesigner.tools.services](summaries/mod:parrot_formdesigner.tools.services.md)

Form-source services for DatabaseFormTool.

## [parrot_formdesigner.tools.services.abstract](summaries/mod:parrot_formdesigner.tools.services.abstract.md)

AbstractFormService — strategy interface for form-source services.

## [parrot_formdesigner.tools.services.networkninja](summaries/mod:parrot_formdesigner.tools.services.networkninja.md)

NetworkninjaFormService — NetworkNinja PostgreSQL form-source service.

## [parrot_formdesigner.tools.services.registry](summaries/mod:parrot_formdesigner.tools.services.registry.md)

Form-service registry — name → AbstractFormService subclass.

## [parrot_formdesigner.ui](summaries/mod:parrot_formdesigner.ui.md)

parrot_formdesigner.ui — HTML pages + Telegram WebApp surface.

## [parrot_formdesigner.ui.handlers](summaries/mod:parrot_formdesigner.ui.handlers.md)

HTML page handlers for parrot-formdesigner.

## [parrot_formdesigner.ui.routes](summaries/mod:parrot_formdesigner.ui.routes.md)

Route registration for the HTML / Telegram UI surface of parrot-formdesigner.

## [parrot_formdesigner.ui.telegram](summaries/mod:parrot_formdesigner.ui.telegram.md)

Telegram WebApp handlers for parrot-formdesigner.

## [parrot_formdesigner.ui.templates](summaries/mod:parrot_formdesigner.ui.templates.md)

HTML page templates and CSS for parrot-formdesigner HTTP handlers.

## [parrot_formdesigner.version](summaries/mod:parrot_formdesigner.version.md)

parrot-formdesigner Meta information.

## [parrot_loaders](summaries/mod:parrot_loaders.md)

AI-Parrot Document Loaders package.

## [parrot_loaders.audio](summaries/mod:parrot_loaders.audio.md)

Module parrot_loaders.audio

## [parrot_loaders.basepdf](summaries/mod:parrot_loaders.basepdf.md)

Module parrot_loaders.basepdf

## [parrot_loaders.basevideo](summaries/mod:parrot_loaders.basevideo.md)

Module parrot_loaders.basevideo

## [parrot_loaders.csv](summaries/mod:parrot_loaders.csv.md)

Module parrot_loaders.csv

## [parrot_loaders.database](summaries/mod:parrot_loaders.database.md)

DatabaseLoader — Load database table rows as RAG Documents via AsyncDB.

## [parrot_loaders.doc_converter](summaries/mod:parrot_loaders.doc_converter.md)

DocumentConverterLoader - Load documents via Docling into Document objects.

## [parrot_loaders.docx](summaries/mod:parrot_loaders.docx.md)

Module parrot_loaders.docx

## [parrot_loaders.epubloader](summaries/mod:parrot_loaders.epubloader.md)

Module parrot_loaders.epubloader

## [parrot_loaders.excel](summaries/mod:parrot_loaders.excel.md)

Module parrot_loaders.excel

## [parrot_loaders.extractors](summaries/mod:parrot_loaders.extractors.md)

Structured data extraction for ontology ingestion and data pipelines.

## [parrot_loaders.extractors.api_source](summaries/mod:parrot_loaders.extractors.api_source.md)

REST API data source for structured record extraction.

## [parrot_loaders.extractors.base](summaries/mod:parrot_loaders.extractors.base.md)

Abstract base class and data models for structured data extraction.

## [parrot_loaders.extractors.csv_source](summaries/mod:parrot_loaders.extractors.csv_source.md)

CSV data source for structured record extraction.

## [parrot_loaders.extractors.exceptions](summaries/mod:parrot_loaders.extractors.exceptions.md)

Exceptions for the ExtractDataSource framework.

## [parrot_loaders.extractors.factory](summaries/mod:parrot_loaders.extractors.factory.md)

Factory for resolving source names to ExtractDataSource implementations.

## [parrot_loaders.extractors.json_source](summaries/mod:parrot_loaders.extractors.json_source.md)

JSON data source for structured record extraction.

## [parrot_loaders.extractors.records_source](summaries/mod:parrot_loaders.extractors.records_source.md)

In-memory records data source for structured record extraction.

## [parrot_loaders.extractors.sql_source](summaries/mod:parrot_loaders.extractors.sql_source.md)

SQL data source for structured record extraction.

## [parrot_loaders.factory](summaries/mod:parrot_loaders.factory.md)

Module parrot_loaders.factory

## [parrot_loaders.files](summaries/mod:parrot_loaders.files.md)

Module parrot_loaders.files

## [parrot_loaders.files.abstract](summaries/mod:parrot_loaders.files.abstract.md)

Module parrot_loaders.files.abstract

## [parrot_loaders.files.html](summaries/mod:parrot_loaders.files.html.md)

Module parrot_loaders.files.html

## [parrot_loaders.files.text](summaries/mod:parrot_loaders.files.text.md)

Module parrot_loaders.files.text

## [parrot_loaders.html](summaries/mod:parrot_loaders.html.md)

Module parrot_loaders.html

## [parrot_loaders.image](summaries/mod:parrot_loaders.image.md)

ImageLoader: OCR-based image loader with layout-aware text extraction.

## [parrot_loaders.imageunderstanding](summaries/mod:parrot_loaders.imageunderstanding.md)

Image Understanding Loader using Google GenAI for analyzing images.

## [parrot_loaders.jsonld_extractors](summaries/mod:parrot_loaders.jsonld_extractors.md)

Backward-compat re-export. Canonical home is parrot.utils.jsonld_extractors.

## [parrot_loaders.markdown](summaries/mod:parrot_loaders.markdown.md)

Module parrot_loaders.markdown

## [parrot_loaders.ocr](summaries/mod:parrot_loaders.ocr.md)

OCR subpackage for parrot_loaders.

## [parrot_loaders.ocr.base](summaries/mod:parrot_loaders.ocr.base.md)

OCR Backend Protocol definition.

## [parrot_loaders.ocr.easyocr_backend](summaries/mod:parrot_loaders.ocr.easyocr_backend.md)

EasyOCR backend for parrot_loaders.

## [parrot_loaders.ocr.layout](summaries/mod:parrot_loaders.ocr.layout.md)

Heuristic layout analyzer for parrot_loaders.

## [parrot_loaders.ocr.layoutlm](summaries/mod:parrot_loaders.ocr.layoutlm.md)

LayoutLMv3 semantic layout analyzer for parrot_loaders.

## [parrot_loaders.ocr.models](summaries/mod:parrot_loaders.ocr.models.md)

OCR data models for the ImageLoader feature.

## [parrot_loaders.ocr.paddle](summaries/mod:parrot_loaders.ocr.paddle.md)

PaddleOCR Backend for ImageLoader.

## [parrot_loaders.ocr.tesseract](summaries/mod:parrot_loaders.ocr.tesseract.md)

Tesseract OCR backend for parrot_loaders.

## [parrot_loaders.pdf](summaries/mod:parrot_loaders.pdf.md)

Module parrot_loaders.pdf

## [parrot_loaders.pdfmark](summaries/mod:parrot_loaders.pdfmark.md)

Module parrot_loaders.pdfmark

## [parrot_loaders.pdftables](summaries/mod:parrot_loaders.pdftables.md)

Module parrot_loaders.pdftables

## [parrot_loaders.ppt](summaries/mod:parrot_loaders.ppt.md)

Module parrot_loaders.ppt

## [parrot_loaders.qa](summaries/mod:parrot_loaders.qa.md)

Module parrot_loaders.qa

## [parrot_loaders.splitters](summaries/mod:parrot_loaders.splitters.md)

Backward-compatibility shim.

## [parrot_loaders.txt](summaries/mod:parrot_loaders.txt.md)

Module parrot_loaders.txt

## [parrot_loaders.version](summaries/mod:parrot_loaders.version.md)

AI-Parrot Loaders Meta information.

## [parrot_loaders.video](summaries/mod:parrot_loaders.video.md)

Module parrot_loaders.video

## [parrot_loaders.videolocal](summaries/mod:parrot_loaders.videolocal.md)

Module parrot_loaders.videolocal

## [parrot_loaders.videounderstanding](summaries/mod:parrot_loaders.videounderstanding.md)

Module parrot_loaders.videounderstanding

## [parrot_loaders.vimeo](summaries/mod:parrot_loaders.vimeo.md)

Module parrot_loaders.vimeo

## [parrot_loaders.web](summaries/mod:parrot_loaders.web.md)

Module parrot_loaders.web

## [parrot_loaders.webscraping](summaries/mod:parrot_loaders.webscraping.md)

WebScrapingLoader — Loader interface for WebScrapingToolkit + CrawlEngine.

## [parrot_loaders.youtube](summaries/mod:parrot_loaders.youtube.md)

Module parrot_loaders.youtube

## [parrot_pipelines](summaries/mod:parrot_pipelines.md)

AI-Parrot Pipelines package.

## [parrot_pipelines.abstract](summaries/mod:parrot_pipelines.abstract.md)

Module parrot_pipelines.abstract

## [parrot_pipelines.detector](summaries/mod:parrot_pipelines.detector.md)

Module parrot_pipelines.detector

## [parrot_pipelines.handlers](summaries/mod:parrot_pipelines.handlers.md)

HTTP handlers for ai-parrot-pipelines.

## [parrot_pipelines.handlers.planogram_compliance](summaries/mod:parrot_pipelines.handlers.planogram_compliance.md)

HTTP handler for planogram compliance analysis with async job support.

## [parrot_pipelines.models](summaries/mod:parrot_pipelines.models.md)

Module parrot_pipelines.models

## [parrot_pipelines.planogram](summaries/mod:parrot_pipelines.planogram.md)

Planogram Compliance Pipeline exports.

## [parrot_pipelines.planogram.grid](summaries/mod:parrot_pipelines.planogram.grid.md)

Grid detection package for adaptive planogram compliance.

## [parrot_pipelines.planogram.grid.detector](summaries/mod:parrot_pipelines.planogram.grid.detector.md)

Grid-based detection orchestrator.

## [parrot_pipelines.planogram.grid.horizontal_bands](summaries/mod:parrot_pipelines.planogram.grid.horizontal_bands.md)

HorizontalBands grid strategy for product-on-shelves planograms.

## [parrot_pipelines.planogram.grid.merger](summaries/mod:parrot_pipelines.planogram.grid.merger.md)

Cell Result Merger for grid-based detection.

## [parrot_pipelines.planogram.grid.models](summaries/mod:parrot_pipelines.planogram.grid.models.md)

Detection grid data models.

## [parrot_pipelines.planogram.grid.strategy](summaries/mod:parrot_pipelines.planogram.grid.strategy.md)

Abstract Grid Strategy and NoGrid default implementation.

## [parrot_pipelines.planogram.legacy](summaries/mod:parrot_pipelines.planogram.legacy.md)

3-Step Planogram Compliance Pipeline

## [parrot_pipelines.planogram.plan](summaries/mod:parrot_pipelines.planogram.plan.md)

Module parrot_pipelines.planogram.plan

## [parrot_pipelines.planogram.types](summaries/mod:parrot_pipelines.planogram.types.md)

Planogram type composables for the Composable Pattern.

## [parrot_pipelines.planogram.types.abstract](summaries/mod:parrot_pipelines.planogram.types.abstract.md)

Abstract base class for planogram type composables.

## [parrot_pipelines.planogram.types.endcap_backlit_multitier](summaries/mod:parrot_pipelines.planogram.types.endcap_backlit-f08fa3da.md)

EndcapBacklitMultitier planogram type composable.

## [parrot_pipelines.planogram.types.endcap_no_shelves_promotional](summaries/mod:parrot_pipelines.planogram.types.endcap_no_shel-f74e2433.md)

EndcapNoShelvesPromotional planogram type composable.

## [parrot_pipelines.planogram.types.graphic_panel_display](summaries/mod:parrot_pipelines.planogram.types.graphic_panel_display.md)

GraphicPanelDisplay planogram type composable.

## [parrot_pipelines.planogram.types.product_counter](summaries/mod:parrot_pipelines.planogram.types.product_counter.md)

ProductCounter planogram type composable.

## [parrot_pipelines.planogram.types.product_on_shelves](summaries/mod:parrot_pipelines.planogram.types.product_on_shelves.md)

ProductOnShelves planogram type composable.

## [parrot_pipelines.version](summaries/mod:parrot_pipelines.version.md)

AI-Parrot Pipelines Meta information.

## [parrot_tools](summaries/mod:parrot_tools.md)

AI-Parrot Tools & Toolkits package.

## [parrot_tools.abstract](summaries/mod:parrot_tools.abstract.md)

Re-export from core — canonical location is parrot.tools.abstract.

## [parrot_tools.arangodbsearch](summaries/mod:parrot_tools.arangodbsearch.md)

ArangoDB Vector Search Tool for AI-Parrot Framework.

## [parrot_tools.arxiv_tool](summaries/mod:parrot_tools.arxiv_tool.md)

ArxivTool - Search and retrieve papers from arXiv.org

## [parrot_tools.aws](summaries/mod:parrot_tools.aws.md)

AWS Toolkits for AI-Parrot.

## [parrot_tools.aws.cloudwatch](summaries/mod:parrot_tools.aws.cloudwatch.md)

AWS CloudWatch Toolkit for AI-Parrot.

## [parrot_tools.aws.documentdb](summaries/mod:parrot_tools.aws.documentdb.md)

AWS DocumentDB Toolkit for AI-Parrot.

## [parrot_tools.aws.ec2](summaries/mod:parrot_tools.aws.ec2.md)

AWS EC2 Toolkit for AI-Parrot.

## [parrot_tools.aws.ecr](summaries/mod:parrot_tools.aws.ecr.md)

AWS ECR Toolkit for AI-Parrot.

## [parrot_tools.aws.ecs](summaries/mod:parrot_tools.aws.ecs.md)

AWS ECS Toolkit for AI-Parrot.

## [parrot_tools.aws.eks](summaries/mod:parrot_tools.aws.eks.md)

AWS EKS Toolkit for AI-Parrot.

## [parrot_tools.aws.guardduty](summaries/mod:parrot_tools.aws.guardduty.md)

AWS GuardDuty Toolkit for AI-Parrot.

## [parrot_tools.aws.iam](summaries/mod:parrot_tools.aws.iam.md)

AWS IAM Toolkit for AI-Parrot.

## [parrot_tools.aws.inspector](summaries/mod:parrot_tools.aws.inspector.md)

AWS Inspector v2 Toolkit for AI-Parrot.

## [parrot_tools.aws.lambda_func](summaries/mod:parrot_tools.aws.lambda_func.md)

AWS Lambda Toolkit for AI-Parrot.

## [parrot_tools.aws.rds](summaries/mod:parrot_tools.aws.rds.md)

AWS RDS Toolkit for AI-Parrot.

## [parrot_tools.aws.route53](summaries/mod:parrot_tools.aws.route53.md)

AWS Route53 Toolkit for AI-Parrot.

## [parrot_tools.aws.s3](summaries/mod:parrot_tools.aws.s3.md)

AWS S3 Toolkit for AI-Parrot.

## [parrot_tools.aws.securityhub](summaries/mod:parrot_tools.aws.securityhub.md)

AWS SecurityHub Toolkit for AI-Parrot.

## [parrot_tools.backstage](summaries/mod:parrot_tools.backstage.md)

Module parrot_tools.backstage

## [parrot_tools.backstage.models](summaries/mod:parrot_tools.backstage.models.md)

Pydantic models for Backstage Catalog API responses.

## [parrot_tools.backstage.toolkit](summaries/mod:parrot_tools.backstage.toolkit.md)

BackstageCatalogToolkit — Read entries from a Backstage.io software catalog.

## [parrot_tools.bingsearch](summaries/mod:parrot_tools.bingsearch.md)

Bing Search Tool implementation for the ai-parrot framework.

## [parrot_tools.bloomberg](summaries/mod:parrot_tools.bloomberg.md)

Module parrot_tools.bloomberg

## [parrot_tools.breakeven](summaries/mod:parrot_tools.breakeven.md)

BreakEvenAnalysisTool — threshold and root-finding analysis.

## [parrot_tools.cache](summaries/mod:parrot_tools.cache.md)

Redis-based caching for Tool and Toolkit API responses.

## [parrot_tools.calculator](summaries/mod:parrot_tools.calculator.md)

Module parrot_tools.calculator

## [parrot_tools.calculator.operations](summaries/mod:parrot_tools.calculator.operations.md)

Calculator operations module.

## [parrot_tools.calculator.operations.calculus](summaries/mod:parrot_tools.calculator.operations.calculus.md)

Calculus operations.

## [parrot_tools.calculator.operations.statistics](summaries/mod:parrot_tools.calculator.operations.statistics.md)

Statistical operations.

## [parrot_tools.calculator.tool](summaries/mod:parrot_tools.calculator.tool.md)

Module parrot_tools.calculator.tool

## [parrot_tools.chart](summaries/mod:parrot_tools.chart.md)

Chart Generation Tool for AI-Parrot Agents.

## [parrot_tools.cloudsploit](summaries/mod:parrot_tools.cloudsploit.md)

CloudSploit Security Scanning Toolkit for AI-Parrot.

## [parrot_tools.cloudsploit.comparator](summaries/mod:parrot_tools.cloudsploit.comparator.md)

Scan comparator for diffing two CloudSploit scan results.

## [parrot_tools.cloudsploit.ecr_collector](summaries/mod:parrot_tools.cloudsploit.ecr_collector.md)

ECR image-scan collector for CloudSploit toolkit (FEAT-165).

## [parrot_tools.cloudsploit.executor](summaries/mod:parrot_tools.cloudsploit.executor.md)

CloudSploit executor for running scans via Docker or direct CLI.

## [parrot_tools.cloudsploit.models](summaries/mod:parrot_tools.cloudsploit.models.md)

Pydantic data models for CloudSploit security scanning toolkit.

## [parrot_tools.cloudsploit.parser](summaries/mod:parrot_tools.cloudsploit.parser.md)

Parses CloudSploit JSON output into typed ScanResult objects.

## [parrot_tools.cloudsploit.reports](summaries/mod:parrot_tools.cloudsploit.reports.md)

Report generator for CloudSploit scan results.

## [parrot_tools.cloudsploit.toolkit](summaries/mod:parrot_tools.cloudsploit.toolkit.md)

CloudSploit Security Scanning Toolkit for AI-Parrot.

## [parrot_tools.code_toolkit](summaries/mod:parrot_tools.code_toolkit.md)

Code toolkit for spec-driven coding tasks.

## [parrot_tools.codeinterpreter](summaries/mod:parrot_tools.codeinterpreter.md)

CodeInterpreterTool - Agent-as-Tool for comprehensive code analysis.

## [parrot_tools.codeinterpreter.executor](summaries/mod:parrot_tools.codeinterpreter.executor.md)

Isolated code execution environment using Docker containers.

## [parrot_tools.codeinterpreter.internals](summaries/mod:parrot_tools.codeinterpreter.internals.md)

Internal tools for the CodeInterpreterTool agent.

## [parrot_tools.codeinterpreter.models](summaries/mod:parrot_tools.codeinterpreter.models.md)

Module parrot_tools.codeinterpreter.models

## [parrot_tools.codeinterpreter.prompts](summaries/mod:parrot_tools.codeinterpreter.prompts.md)

System prompt for the CodeInterpreterTool agent.

## [parrot_tools.codeinterpreter.tool](summaries/mod:parrot_tools.codeinterpreter.tool.md)

CodeInterpreterTool - Parrot Tool for comprehensive code analysis.

## [parrot_tools.company_info](summaries/mod:parrot_tools.company_info.md)

Module parrot_tools.company_info

## [parrot_tools.company_info.tool](summaries/mod:parrot_tools.company_info.tool.md)

CompanyInfoToolkit - Unified toolkit for scraping company information from multiple sources.

## [parrot_tools.composite_score](summaries/mod:parrot_tools.composite_score.md)

Composite Score Tool for Technical Analysis.

## [parrot_tools.computer](summaries/mod:parrot_tools.computer.md)

parrot_tools.computer — Computer-Use Agent package.

## [parrot_tools.computer.agent](summaries/mod:parrot_tools.computer.agent.md)

ComputerAgent — Agent subclass for vision-based browser automation (FEAT-227).

## [parrot_tools.computer.backend](summaries/mod:parrot_tools.computer.backend.md)

AsyncComputerBackend — async Playwright wrapper for computer-use actions.

## [parrot_tools.computer.models](summaries/mod:parrot_tools.computer.models.md)

Data models for the Computer-Use Agent feature (FEAT-227).

## [parrot_tools.computer.toolkit](summaries/mod:parrot_tools.computer.toolkit.md)

ComputerInteractionToolkit — AbstractToolkit subclass for computer-use actions.

## [parrot_tools.correlationanalysis](summaries/mod:parrot_tools.correlationanalysis.md)

Correlation Analysis Tool - Analyze correlations between a key column and other columns.

## [parrot_tools.csv_export](summaries/mod:parrot_tools.csv_export.md)

CSV Export Tool - Export DataFrames and structured data to CSV format.

## [parrot_tools.database](summaries/mod:parrot_tools.database.md)

parrot_tools.database — Database tools.

## [parrot_tools.database.abstract](summaries/mod:parrot_tools.database.abstract.md)

Module parrot_tools.database.abstract

## [parrot_tools.database.cache](summaries/mod:parrot_tools.database.cache.md)

Module parrot_tools.database.cache

## [parrot_tools.database.models](summaries/mod:parrot_tools.database.models.md)

Module parrot_tools.database.models

## [parrot_tools.databasequery](summaries/mod:parrot_tools.databasequery.md)

Compat shim — use parrot.tools.databasequery instead.

## [parrot_tools.dataset_manager](summaries/mod:parrot_tools.dataset_manager.md)

Backward-compat re-export — canonical location is parrot.tools.dataset_manager.

## [parrot_tools.dataset_manager.sources](summaries/mod:parrot_tools.dataset_manager.sources.md)

Backward-compat re-export — canonical location is parrot.tools.dataset_manager.sources.

## [parrot_tools.db](summaries/mod:parrot_tools.db.md)

Unified Database Tool for AI-Parrot

## [parrot_tools.ddgo](summaries/mod:parrot_tools.ddgo.md)

DuckDuckGo Search Toolkit for AI-Parrot.

## [parrot_tools.ddgsearch](summaries/mod:parrot_tools.ddgsearch.md)

DuckDuckGo Search Tool for AI-Parrot.

## [parrot_tools.decorators](summaries/mod:parrot_tools.decorators.md)

Re-export from core — canonical location is parrot.tools.decorators.

## [parrot_tools.dftohtml](summaries/mod:parrot_tools.dftohtml.md)

DataFrame to HTML Tool - Convert pandas DataFrames to styled HTML tables.

## [parrot_tools.doc_converter](summaries/mod:parrot_tools.doc_converter.md)

DocumentConverterTool - Convert documents to JSON/Markdown via Docling.

## [parrot_tools.docker](summaries/mod:parrot_tools.docker.md)

Docker Toolkit — manage containers and compose stacks.

## [parrot_tools.docker.compose](summaries/mod:parrot_tools.docker.compose.md)

Docker Compose file generator.

## [parrot_tools.docker.config](summaries/mod:parrot_tools.docker.config.md)

Docker executor configuration.

## [parrot_tools.docker.executor](summaries/mod:parrot_tools.docker.executor.md)

Docker executor for running Docker CLI commands.

## [parrot_tools.docker.models](summaries/mod:parrot_tools.docker.models.md)

Docker data models for container, image, and compose operations.

## [parrot_tools.docker.toolkit](summaries/mod:parrot_tools.docker.toolkit.md)

Docker Toolkit for managing containers and compose stacks.

## [parrot_tools.document](summaries/mod:parrot_tools.document.md)

AbstractDocumentTool - Base class for document generation tools.

## [parrot_tools.edareport](summaries/mod:parrot_tools.edareport.md)

EDA Report Tool - Comprehensive profiling using ydata_profiling (formerly pandas_profiling).

## [parrot_tools.elasticsearch](summaries/mod:parrot_tools.elasticsearch.md)

Elasticsearch/OpenSearch Tool for AI-Parrot

## [parrot_tools.employees](summaries/mod:parrot_tools.employees.md)

Employee Hierarchy Tool for AI-Parrot.

## [parrot_tools.epson](summaries/mod:parrot_tools.epson.md)

Module parrot_tools.epson

## [parrot_tools.excel](summaries/mod:parrot_tools.excel.md)

MS Excel Tool migrated to use AbstractDocumentTool framework.

## [parrot_tools.file](summaries/mod:parrot_tools.file.md)

Backward-compat re-exports — canonical location is parrot.interfaces.file.

## [parrot_tools.file_reader](summaries/mod:parrot_tools.file_reader.md)

FileReaderTool implementation for reading various file formats.

## [parrot_tools.flowtask](summaries/mod:parrot_tools.flowtask.md)

Flowtask Toolkit — optional extra.

## [parrot_tools.flowtask.tool](summaries/mod:parrot_tools.flowtask.tool.md)

FlowtaskToolkit for AI-Parrot - Execute Flowtask components and tasks dynamically.

## [parrot_tools.fred_api](summaries/mod:parrot_tools.fred_api.md)

FredAPITool for interacting with Federal Reserve Economic Data (FRED) API.

## [parrot_tools.gigsmart](summaries/mod:parrot_tools.gigsmart.md)

GigSmartToolkit — LLM-facing toolkit for the GigSmart staffing platform API.

## [parrot_tools.gigsmart.schemas](summaries/mod:parrot_tools.gigsmart.schemas.md)

Pydantic input schemas for GigSmartToolkit @tool_schema decorators.

## [parrot_tools.gigsmart.toolkit](summaries/mod:parrot_tools.gigsmart.toolkit.md)

GigSmartToolkit — AbstractToolkit exposing GigSmart API surfaces as LLM tools.

## [parrot_tools.gittoolkit](summaries/mod:parrot_tools.gittoolkit.md)

Git/GitHub toolkit inspired by :mod:`parrot.tools.jiratoolkit`.

## [parrot_tools.google](summaries/mod:parrot_tools.google.md)

Module parrot_tools.google

## [parrot_tools.google.base](summaries/mod:parrot_tools.google.base.md)

Base classes for Google Workspace tools.

## [parrot_tools.google.places](summaries/mod:parrot_tools.google.places.md)

Google Business Profile Tools.

## [parrot_tools.google.tools](summaries/mod:parrot_tools.google.tools.md)

Migrated Google Tools using the AbstractTool framework.

## [parrot_tools.googlelocation](summaries/mod:parrot_tools.googlelocation.md)

Module parrot_tools.googlelocation

## [parrot_tools.googleroutes](summaries/mod:parrot_tools.googleroutes.md)

Module parrot_tools.googleroutes

## [parrot_tools.googlesearch](summaries/mod:parrot_tools.googlesearch.md)

Module parrot_tools.googlesearch

## [parrot_tools.googlesitesearch](summaries/mod:parrot_tools.googlesitesearch.md)

Module parrot_tools.googlesitesearch

## [parrot_tools.googlevoice](summaries/mod:parrot_tools.googlevoice.md)

Module parrot_tools.googlevoice

## [parrot_tools.graphindex](summaries/mod:parrot_tools.graphindex.md)

GraphIndex toolkit for AI agents.

## [parrot_tools.graphindex.flowtask](summaries/mod:parrot_tools.graphindex.flowtask.md)

Flowtask component wrapper for the GraphIndex pipeline.

## [parrot_tools.graphindex.toolkit](summaries/mod:parrot_tools.graphindex.toolkit.md)

GraphIndex Toolkit — Agent-Facing Tools.

## [parrot_tools.gvoice](summaries/mod:parrot_tools.gvoice.md)

Google Text-to-Speech Tool migrated to use AbstractTool framework with async support.

## [parrot_tools.ibisworld](summaries/mod:parrot_tools.ibisworld.md)

IBISWorld Tool Package

## [parrot_tools.ibisworld.tool](summaries/mod:parrot_tools.ibisworld.tool.md)

IBISWorld Tool for AI-Parrot

## [parrot_tools.ibkr](summaries/mod:parrot_tools.ibkr.md)

IBKR Trading Toolkit for AI-Parrot agents.

## [parrot_tools.ibkr.backend](summaries/mod:parrot_tools.ibkr.backend.md)

Abstract backend interface for IBKR connections.

## [parrot_tools.ibkr.models](summaries/mod:parrot_tools.ibkr.models.md)

Pydantic data models for the IBKR Trading Toolkit.

## [parrot_tools.ibkr.portal_backend](summaries/mod:parrot_tools.ibkr.portal_backend.md)

IBKR Client Portal REST API backend.

## [parrot_tools.ibkr.risk](summaries/mod:parrot_tools.ibkr.risk.md)

Pre-trade risk management for IBKR agent-driven trading.

## [parrot_tools.ibkr.tws_backend](summaries/mod:parrot_tools.ibkr.tws_backend.md)

TWS API backend for IBKR using ib_async.

## [parrot_tools.interfaces](summaries/mod:parrot_tools.interfaces.md)

Module parrot_tools.interfaces

## [parrot_tools.interfaces.gigsmart](summaries/mod:parrot_tools.interfaces.gigsmart.md)

GigSmart interface package — aiohttp-based GraphQL transport with OAuth 2.1.

## [parrot_tools.interfaces.gigsmart.auth](summaries/mod:parrot_tools.interfaces.gigsmart.auth.md)

GigSmart OAuth 2.1 authentication — token lifecycle management.

## [parrot_tools.interfaces.gigsmart.client](summaries/mod:parrot_tools.interfaces.gigsmart.client.md)

GigSmart GraphQL client — aiohttp-based transport with retry and error classification.

## [parrot_tools.interfaces.gigsmart.config](summaries/mod:parrot_tools.interfaces.gigsmart.config.md)

GigSmart configuration — credentials and API settings.

## [parrot_tools.interfaces.gigsmart.exceptions](summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md)

Typed exception hierarchy for GigSmart API errors.

## [parrot_tools.interfaces.gigsmart.models](summaries/mod:parrot_tools.interfaces.gigsmart.models.md)

GigSmart Pydantic v2 models — public exports.

## [parrot_tools.interfaces.gigsmart.models.common](summaries/mod:parrot_tools.interfaces.gigsmart.models.common.md)

Common / shared models — Relay pagination generics and OAuth token.

## [parrot_tools.interfaces.gigsmart.models.engagement](summaries/mod:parrot_tools.interfaces.gigsmart.models.engagement.md)

Pydantic v2 models for GigSmart engagements API surface.

## [parrot_tools.interfaces.gigsmart.models.gig](summaries/mod:parrot_tools.interfaces.gigsmart.models.gig.md)

Pydantic v2 models for GigSmart gigs (shifts) API surface.

## [parrot_tools.interfaces.gigsmart.models.location](summaries/mod:parrot_tools.interfaces.gigsmart.models.location.md)

Pydantic v2 models for GigSmart locations API surface.

## [parrot_tools.interfaces.gigsmart.models.position](summaries/mod:parrot_tools.interfaces.gigsmart.models.position.md)

Pydantic v2 models for GigSmart positions API surface.

## [parrot_tools.interfaces.gigsmart.models.timesheet](summaries/mod:parrot_tools.interfaces.gigsmart.models.timesheet.md)

Pydantic v2 models for GigSmart timesheets and disputes API surfaces.

## [parrot_tools.interfaces.gigsmart.queries](summaries/mod:parrot_tools.interfaces.gigsmart.queries.md)

GigSmart GraphQL document strings — public exports.

## [parrot_tools.interfaces.gigsmart.queries.engagements](summaries/mod:parrot_tools.interfaces.gigsmart.queries.engagements.md)

GraphQL query and mutation strings for the GigSmart engagements surface.

## [parrot_tools.interfaces.gigsmart.queries.fragments](summaries/mod:parrot_tools.interfaces.gigsmart.queries.fragments.md)

Shared GraphQL fragments reused across GigSmart query modules.

## [parrot_tools.interfaces.gigsmart.queries.gigs](summaries/mod:parrot_tools.interfaces.gigsmart.queries.gigs.md)

GraphQL query and mutation strings for the GigSmart gigs (shifts) surface.

## [parrot_tools.interfaces.gigsmart.queries.locations](summaries/mod:parrot_tools.interfaces.gigsmart.queries.locations.md)

GraphQL query and mutation strings for the GigSmart locations surface.

## [parrot_tools.interfaces.gigsmart.queries.messages](summaries/mod:parrot_tools.interfaces.gigsmart.queries.messages.md)

GraphQL mutation strings for the GigSmart messages surface.

## [parrot_tools.interfaces.gigsmart.queries.positions](summaries/mod:parrot_tools.interfaces.gigsmart.queries.positions.md)

GraphQL query and mutation strings for the GigSmart positions surface.

## [parrot_tools.interfaces.gigsmart.queries.timesheets](summaries/mod:parrot_tools.interfaces.gigsmart.queries.timesheets.md)

GraphQL query and mutation strings for the GigSmart timesheets and disputes surfaces.

## [parrot_tools.interfaces.workday](summaries/mod:parrot_tools.interfaces.workday.md)

parrot_tools.interfaces.workday — Workday operational interface package.

## [parrot_tools.interfaces.workday.config](summaries/mod:parrot_tools.interfaces.workday.config.md)

WorkdayConfig — credential + tenant configuration for WorkdayService.

## [parrot_tools.interfaces.workday.handlers](summaries/mod:parrot_tools.interfaces.workday.handlers.md)

Module parrot_tools.interfaces.workday.handlers

## [parrot_tools.interfaces.workday.handlers.applicants](summaries/mod:parrot_tools.interfaces.workday.handlers.applicants.md)

Module parrot_tools.interfaces.workday.handlers.applicants

## [parrot_tools.interfaces.workday.handlers.base](summaries/mod:parrot_tools.interfaces.workday.handlers.base.md)

Module parrot_tools.interfaces.workday.handlers.base

## [parrot_tools.interfaces.workday.handlers.candidates](summaries/mod:parrot_tools.interfaces.workday.handlers.candidates.md)

Module parrot_tools.interfaces.workday.handlers.candidates

## [parrot_tools.interfaces.workday.handlers.cost_centers](summaries/mod:parrot_tools.interfaces.workday.handlers.cost_centers.md)

Module parrot_tools.interfaces.workday.handlers.cost_centers

## [parrot_tools.interfaces.workday.handlers.custom_punch_field_report](summaries/mod:parrot_tools.interfaces.workday.handlers.custom-60a9db47.md)

Type handler for Workday Custom Punch - Field Report.

## [parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest](summaries/mod:parrot_tools.interfaces.workday.handlers.custom-534af80a.md)

REST handler for the Custom Punch - Field Report (RaaS).

## [parrot_tools.interfaces.workday.handlers.custom_report](summaries/mod:parrot_tools.interfaces.workday.handlers.custom_report.md)

Generic type handler for Workday RaaS (Reports as a Service) custom reports.

## [parrot_tools.interfaces.workday.handlers.import_reported_time_blocks](summaries/mod:parrot_tools.interfaces.workday.handlers.import-0a3490b1.md)

ImportReportedTimeBlocksType — handler for Import_Reported_Time_Blocks.

## [parrot_tools.interfaces.workday.handlers.import_time_clock_events](summaries/mod:parrot_tools.interfaces.workday.handlers.import-649a8cfe.md)

ImportTimeClockEventsType — handler for Import_Time_Clock_Events.

## [parrot_tools.interfaces.workday.handlers.job_posting_sites](summaries/mod:parrot_tools.interfaces.workday.handlers.job_po-817325f3.md)

Module parrot_tools.interfaces.workday.handlers.job_posting_sites

## [parrot_tools.interfaces.workday.handlers.job_postings](summaries/mod:parrot_tools.interfaces.workday.handlers.job_postings.md)

Module parrot_tools.interfaces.workday.handlers.job_postings

## [parrot_tools.interfaces.workday.handlers.job_requisitions](summaries/mod:parrot_tools.interfaces.workday.handlers.job_re-9a20de79.md)

Module parrot_tools.interfaces.workday.handlers.job_requisitions

## [parrot_tools.interfaces.workday.handlers.location_hierarchy_assignments](summaries/mod:parrot_tools.interfaces.workday.handlers.locati-12e680b1.md)

Get_Location_Hierarchy_Organization_Assignments operation handler.

## [parrot_tools.interfaces.workday.handlers.locations](summaries/mod:parrot_tools.interfaces.workday.handlers.locations.md)

Module parrot_tools.interfaces.workday.handlers.locations

## [parrot_tools.interfaces.workday.handlers.organization_single](summaries/mod:parrot_tools.interfaces.workday.handlers.organi-a88b280d.md)

Get_Organization operation handler.

## [parrot_tools.interfaces.workday.handlers.organizations](summaries/mod:parrot_tools.interfaces.workday.handlers.organizations.md)

Module parrot_tools.interfaces.workday.handlers.organizations

## [parrot_tools.interfaces.workday.handlers.payroll](summaries/mod:parrot_tools.interfaces.workday.handlers.payroll.md)

Workday Payroll read handlers (FEAT-232).

## [parrot_tools.interfaces.workday.handlers.put_time_clock_events](summaries/mod:parrot_tools.interfaces.workday.handlers.put_ti-91a18a55.md)

PutTimeClockEventsType — handler for Put_Time_Clock_Events.

## [parrot_tools.interfaces.workday.handlers.recruiting_agency_users](summaries/mod:parrot_tools.interfaces.workday.handlers.recrui-e66fd23b.md)

Handler for the Workday Get_Recruiting_Agency_Users operation.

## [parrot_tools.interfaces.workday.handlers.references](summaries/mod:parrot_tools.interfaces.workday.handlers.references.md)

Module parrot_tools.interfaces.workday.handlers.references

## [parrot_tools.interfaces.workday.handlers.time_block_report](summaries/mod:parrot_tools.interfaces.workday.handlers.time_b-8f981bbf.md)

Type handler for Workday Extract Time Blocks Navigator Custom Report.

## [parrot_tools.interfaces.workday.handlers.time_blocks](summaries/mod:parrot_tools.interfaces.workday.handlers.time_blocks.md)

Module parrot_tools.interfaces.workday.handlers.time_blocks

## [parrot_tools.interfaces.workday.handlers.time_off_balances](summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-da072657.md)

Module parrot_tools.interfaces.workday.handlers.time_off_balances

## [parrot_tools.interfaces.workday.handlers.time_off_eligibility](summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-a48c5708.md)

TimeOffEligibilityType — read handler for Get_Time_Off_Types.

## [parrot_tools.interfaces.workday.handlers.time_off_request](summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-c8218c4e.md)

RequestTimeOffType — handler for Request_Time_Off.

## [parrot_tools.interfaces.workday.handlers.time_requests](summaries/mod:parrot_tools.interfaces.workday.handlers.time_requests.md)

Module parrot_tools.interfaces.workday.handlers.time_requests

## [parrot_tools.interfaces.workday.handlers.workers](summaries/mod:parrot_tools.interfaces.workday.handlers.workers.md)

Module parrot_tools.interfaces.workday.handlers.workers

## [parrot_tools.interfaces.workday.models](summaries/mod:parrot_tools.interfaces.workday.models.md)

Module parrot_tools.interfaces.workday.models

## [parrot_tools.interfaces.workday.models.applicant](summaries/mod:parrot_tools.interfaces.workday.models.applicant.md)

Module parrot_tools.interfaces.workday.models.applicant

## [parrot_tools.interfaces.workday.models.candidate](summaries/mod:parrot_tools.interfaces.workday.models.candidate.md)

Module parrot_tools.interfaces.workday.models.candidate

## [parrot_tools.interfaces.workday.models.clock_event](summaries/mod:parrot_tools.interfaces.workday.models.clock_event.md)

Clock-event Pydantic models for Workday Time Tracking write operations.

## [parrot_tools.interfaces.workday.models.cost_center](summaries/mod:parrot_tools.interfaces.workday.models.cost_center.md)

Module parrot_tools.interfaces.workday.models.cost_center

## [parrot_tools.interfaces.workday.models.custom_punch_field_report](summaries/mod:parrot_tools.interfaces.workday.models.custom_p-6ac793b8.md)

Pydantic models for Workday Custom Punch - Field Report.

## [parrot_tools.interfaces.workday.models.job_posting](summaries/mod:parrot_tools.interfaces.workday.models.job_posting.md)

Module parrot_tools.interfaces.workday.models.job_posting

## [parrot_tools.interfaces.workday.models.job_posting_site](summaries/mod:parrot_tools.interfaces.workday.models.job_posting_site.md)

Module parrot_tools.interfaces.workday.models.job_posting_site

## [parrot_tools.interfaces.workday.models.job_requisition](summaries/mod:parrot_tools.interfaces.workday.models.job_requisition.md)

Module parrot_tools.interfaces.workday.models.job_requisition

## [parrot_tools.interfaces.workday.models.location](summaries/mod:parrot_tools.interfaces.workday.models.location.md)

Module parrot_tools.interfaces.workday.models.location

## [parrot_tools.interfaces.workday.models.location_hierarchy_assignments](summaries/mod:parrot_tools.interfaces.workday.models.location-8bcdffa0.md)

Pydantic models for Location Hierarchy Organization Assignments.

## [parrot_tools.interfaces.workday.models.organizations](summaries/mod:parrot_tools.interfaces.workday.models.organizations.md)

Module parrot_tools.interfaces.workday.models.organizations

## [parrot_tools.interfaces.workday.models.reference](summaries/mod:parrot_tools.interfaces.workday.models.reference.md)

Module parrot_tools.interfaces.workday.models.reference

## [parrot_tools.interfaces.workday.models.time_block](summaries/mod:parrot_tools.interfaces.workday.models.time_block.md)

Module parrot_tools.interfaces.workday.models.time_block

## [parrot_tools.interfaces.workday.models.time_off_balance](summaries/mod:parrot_tools.interfaces.workday.models.time_off_balance.md)

Module parrot_tools.interfaces.workday.models.time_off_balance

## [parrot_tools.interfaces.workday.models.time_off_eligibility](summaries/mod:parrot_tools.interfaces.workday.models.time_off-72f6a0d8.md)

Module parrot_tools.interfaces.workday.models.time_off_eligibility

## [parrot_tools.interfaces.workday.models.time_request](summaries/mod:parrot_tools.interfaces.workday.models.time_request.md)

Module parrot_tools.interfaces.workday.models.time_request

## [parrot_tools.interfaces.workday.models.worker](summaries/mod:parrot_tools.interfaces.workday.models.worker.md)

Module parrot_tools.interfaces.workday.models.worker

## [parrot_tools.interfaces.workday.parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.md)

Module parrot_tools.interfaces.workday.parsers

## [parrot_tools.interfaces.workday.parsers.applicant_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.applica-40128aa9.md)

Module parrot_tools.interfaces.workday.parsers.applicant_parsers

## [parrot_tools.interfaces.workday.parsers.candidate_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.candida-56f86300.md)

Module parrot_tools.interfaces.workday.parsers.candidate_parsers

## [parrot_tools.interfaces.workday.parsers.cost_center_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.cost_ce-680cee26.md)

Cost Center parsers for Workday Get_Cost_Centers operation.

## [parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.custom_-31fb44b3.md)

Parsers for Workday Custom Punch - Field Report.

## [parrot_tools.interfaces.workday.parsers.job_posting_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.job_pos-02bdf0f3.md)

Job Posting parsers for Workday Get_Job_Postings operation.

## [parrot_tools.interfaces.workday.parsers.job_posting_site_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.job_pos-4dc94e7b.md)

Job Posting Site parsers for Workday Get_Job_Posting_Sites operation.

## [parrot_tools.interfaces.workday.parsers.job_requisition_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.job_req-97686f31.md)

Job Requisition parsers for Workday Get_Job_Requisitions operation.

## [parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.locatio-5e38806d.md)

Parsers for Location Hierarchy Organization Assignments data.

## [parrot_tools.interfaces.workday.parsers.location_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.location_parsers.md)

Module parrot_tools.interfaces.workday.parsers.location_parsers

## [parrot_tools.interfaces.workday.parsers.organization_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.organiz-095428cf.md)

Module parrot_tools.interfaces.workday.parsers.organization_parsers

## [parrot_tools.interfaces.workday.parsers.reference_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.referen-07cba2df.md)

Parsers for Workday Get_References (Integrations service) responses.

## [parrot_tools.interfaces.workday.parsers.time_block_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.time_bl-da1a0d62.md)

Module parrot_tools.interfaces.workday.parsers.time_block_parsers

## [parrot_tools.interfaces.workday.parsers.time_off_balance_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.time_of-83aeaf9e.md)

Module parrot_tools.interfaces.workday.parsers.time_off_balance_parsers

## [parrot_tools.interfaces.workday.parsers.time_request_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.time_re-cb561096.md)

Module parrot_tools.interfaces.workday.parsers.time_request_parsers

## [parrot_tools.interfaces.workday.parsers.worker_parsers](summaries/mod:parrot_tools.interfaces.workday.parsers.worker_parsers.md)

Module parrot_tools.interfaces.workday.parsers.worker_parsers

## [parrot_tools.interfaces.workday.service](summaries/mod:parrot_tools.interfaces.workday.service.md)

WorkdayService — self-contained Workday operational interface.

## [parrot_tools.interfaces.workday.utils](summaries/mod:parrot_tools.interfaces.workday.utils.md)

Module parrot_tools.interfaces.workday.utils

## [parrot_tools.interfaces.workday.utils.utils](summaries/mod:parrot_tools.interfaces.workday.utils.utils.md)

Module parrot_tools.interfaces.workday.utils.utils

## [parrot_tools.jiratoolkit](summaries/mod:parrot_tools.jiratoolkit.md)

Jira Toolkit - A unified toolkit for Jira operations using pycontribs/jira.

## [parrot_tools.kubernetes](summaries/mod:parrot_tools.kubernetes.md)

Kubernetes Toolkit for AI-Parrot agents.

## [parrot_tools.kubernetes.config](summaries/mod:parrot_tools.kubernetes.config.md)

Kubernetes Toolkit configuration and result models.

## [parrot_tools.kubernetes.executor](summaries/mod:parrot_tools.kubernetes.executor.md)

KubernetesExecutor — async Kubernetes client wrapper.

## [parrot_tools.kubernetes.toolkit](summaries/mod:parrot_tools.kubernetes.toolkit.md)

KubernetesToolkit — AbstractToolkit exposing kubectl-like agent tools.

## [parrot_tools.leadiq](summaries/mod:parrot_tools.leadiq.md)

Module parrot_tools.leadiq

## [parrot_tools.leadiq.tool](summaries/mod:parrot_tools.leadiq.tool.md)

LeadIQToolkit - Agent-usable toolkit for the LeadIQ GraphQL API.

## [parrot_tools.massive](summaries/mod:parrot_tools.massive.md)

MassiveToolkit - Premium market data enrichment from Massive.com (ex-Polygon.io).

## [parrot_tools.massive.cache](summaries/mod:parrot_tools.massive.cache.md)

Cache layer for MassiveToolkit with per-endpoint TTLs.

## [parrot_tools.massive.client](summaries/mod:parrot_tools.massive.client.md)

Async REST client for Massive (ex-Polygon.io).

## [parrot_tools.massive.models](summaries/mod:parrot_tools.massive.models.md)

Pydantic models for MassiveToolkit.

## [parrot_tools.massive.toolkit](summaries/mod:parrot_tools.massive.toolkit.md)

MassiveToolkit — Premium market data enrichment from Massive.com (ex-Polygon.io).

## [parrot_tools.math](summaries/mod:parrot_tools.math.md)

Module parrot_tools.math

## [parrot_tools.messaging](summaries/mod:parrot_tools.messaging.md)

Module parrot_tools.messaging

## [parrot_tools.messaging.whatsapp](summaries/mod:parrot_tools.messaging.whatsapp.md)

WhatsApp Tool - Send and receive WhatsApp messages via whatsmeow bridge.

## [parrot_tools.metadata](summaries/mod:parrot_tools.metadata.md)

Metadata tool for describing DataFrame schemas to the LLM.

## [parrot_tools.montecarlo](summaries/mod:parrot_tools.montecarlo.md)

MonteCarloSimulationTool — Stochastic simulation with distributions.

## [parrot_tools.msteams](summaries/mod:parrot_tools.msteams.md)

MS Teams Toolkit - A unified toolkit for Microsoft Teams operations.

## [parrot_tools.msword](summaries/mod:parrot_tools.msword.md)

MS Word Tool migrated to use AbstractDocumentTool framework.

## [parrot_tools.multidb](summaries/mod:parrot_tools.multidb.md)

Multi-Tier Schema Metadata Caching System for AI-Parrot DatabaseTool

## [parrot_tools.multistoresearch](summaries/mod:parrot_tools.multistoresearch.md)

Multi-store search tool with BM25 reranking.

## [parrot_tools.navigator](summaries/mod:parrot_tools.navigator.md)

Navigator Toolkit for AI-Parrot.

## [parrot_tools.navigator.prompt](summaries/mod:parrot_tools.navigator.prompt.md)

Navigator context provider using PageIndex (vectorless, LLM-driven RAG).

## [parrot_tools.navigator.schemas](summaries/mod:parrot_tools.navigator.schemas.md)

Pydantic input schemas for NavigatorToolkit methods.

## [parrot_tools.navigator.toolkit](summaries/mod:parrot_tools.navigator.toolkit.md)

NavigatorToolkit for AI-Parrot - Manage Navigator Programs, Modules, Dashboards & Widgets.

## [parrot_tools.networkninja](summaries/mod:parrot_tools.networkninja.md)

NetworkNinja API Tool - Real World Implementation

## [parrot_tools.notification](summaries/mod:parrot_tools.notification.md)

NotificationTool - Send notifications via email, Telegram, Slack, or MS Teams.

## [parrot_tools.o365](summaries/mod:parrot_tools.o365.md)

Office 365 Tools and Toolkit integration.

## [parrot_tools.o365.base](summaries/mod:parrot_tools.o365.base.md)

Office365 Tools for AI-Parrot.

## [parrot_tools.o365.bundle](summaries/mod:parrot_tools.o365.bundle.md)

SharePoint and OneDrive Toolkits for AI-Parrot

## [parrot_tools.o365.events](summaries/mod:parrot_tools.o365.events.md)

Office365 Tools Implementation.

## [parrot_tools.o365.mail](summaries/mod:parrot_tools.o365.mail.md)

Office365 Mails Tools.

## [parrot_tools.o365.oauth_toolkit](summaries/mod:parrot_tools.o365.oauth_toolkit.md)

Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth.

## [parrot_tools.o365.onedrive](summaries/mod:parrot_tools.o365.onedrive.md)

OneDrive Tools for AI-Parrot.

## [parrot_tools.o365.sharepoint](summaries/mod:parrot_tools.o365.sharepoint.md)

SharePoint Tools for AI-Parrot.

## [parrot_tools.odoo](summaries/mod:parrot_tools.odoo.md)

Odoo Toolkit for AI-Parrot.

## [parrot_tools.odoo.models](summaries/mod:parrot_tools.odoo.models.md)

Pydantic models exposed by the Odoo toolkit.

## [parrot_tools.odoo.models.entities](summaries/mod:parrot_tools.odoo.models.entities.md)

Pydantic entity models for the most-used Odoo objects.

## [parrot_tools.odoo.models.envelopes](summaries/mod:parrot_tools.odoo.models.envelopes.md)

Pydantic result envelopes for OdooToolkit operations.

## [parrot_tools.odoo.models.inputs](summaries/mod:parrot_tools.odoo.models.inputs.md)

Pydantic input schemas for OdooToolkit tool methods.

## [parrot_tools.odoo.shell](summaries/mod:parrot_tools.odoo.shell.md)

Shell execution helpers for OdooToolkit odoo-bin / odoo-cli tools.

## [parrot_tools.odoo.smart_fields](summaries/mod:parrot_tools.odoo.smart_fields.md)

Smart field selection heuristic for OdooToolkit.

## [parrot_tools.odoo.toolkit](summaries/mod:parrot_tools.odoo.toolkit.md)

OdooToolkit — exposes Odoo ERP operations as agent tools.

## [parrot_tools.odoo.transport](summaries/mod:parrot_tools.odoo.transport.md)

Transport layer for OdooToolkit (JSON-2 + legacy RPC + auto-detect).

## [parrot_tools.odoo.transport.base](summaries/mod:parrot_tools.odoo.transport.base.md)

Abstract transport for Odoo external API dialects.

## [parrot_tools.odoo.transport.detect](summaries/mod:parrot_tools.odoo.transport.detect.md)

Auto-detect the best Odoo external API transport for a given server.

## [parrot_tools.odoo.transport.json2](summaries/mod:parrot_tools.odoo.transport.json2.md)

External JSON-2 transport for Odoo 19+.

## [parrot_tools.odoo.transport.jsonrpc](summaries/mod:parrot_tools.odoo.transport.jsonrpc.md)

Legacy JSON-RPC 2.0 transport — adapts the existing async OdooInterface.

## [parrot_tools.odoo.transport.xmlrpc](summaries/mod:parrot_tools.odoo.transport.xmlrpc.md)

XML-RPC transport for Odoo (v14-18 and any version with /xmlrpc/2/ enabled).

## [parrot_tools.openweather](summaries/mod:parrot_tools.openweather.md)

OpenWeather Tool migrated to use AbstractTool framework with aiohttp.

## [parrot_tools.pdfprint](summaries/mod:parrot_tools.pdfprint.md)

Enhanced PDF Print Tool with improved Markdown table support.

## [parrot_tools.powerbi](summaries/mod:parrot_tools.powerbi.md)

Module parrot_tools.powerbi

## [parrot_tools.powerpoint](summaries/mod:parrot_tools.powerpoint.md)

PowerPoint Tool migrated to use AbstractDocumentTool framework.

## [parrot_tools.pricestool](summaries/mod:parrot_tools.pricestool.md)

Module parrot_tools.pricestool

## [parrot_tools.products](summaries/mod:parrot_tools.products.md)

Module parrot_tools.products

## [parrot_tools.prophetforecast](summaries/mod:parrot_tools.prophetforecast.md)

ProphetForecastTool for time series forecasting using Facebook Prophet.

## [parrot_tools.pulumi](summaries/mod:parrot_tools.pulumi.md)

Pulumi Toolkit for infrastructure deployment.

## [parrot_tools.pulumi.config](summaries/mod:parrot_tools.pulumi.config.md)

Pulumi configuration and data models.

## [parrot_tools.pulumi.executor](summaries/mod:parrot_tools.pulumi.executor.md)

Pulumi executor for running infrastructure deployment commands.

## [parrot_tools.pulumi.toolkit](summaries/mod:parrot_tools.pulumi.toolkit.md)

Pulumi Toolkit for infrastructure deployment.

## [parrot_tools.pythonpandas](summaries/mod:parrot_tools.pythonpandas.md)

Backward-compat re-export — canonical location is parrot.tools.pythonpandas.

## [parrot_tools.qsource](summaries/mod:parrot_tools.qsource.md)

QuerySource Tool for AI-Parrot

## [parrot_tools.quant](summaries/mod:parrot_tools.quant.md)

QuantToolkit - Quantitative risk analysis and portfolio metrics.

## [parrot_tools.quant.correlation](summaries/mod:parrot_tools.quant.correlation.md)

Correlation Engine for QuantToolkit.

## [parrot_tools.quant.models](summaries/mod:parrot_tools.quant.models.md)

Pydantic models for QuantToolkit input/output contracts.

## [parrot_tools.quant.piotroski](summaries/mod:parrot_tools.quant.piotroski.md)

Piotroski F-Score Calculator for QuantToolkit.

## [parrot_tools.quant.risk_metrics](summaries/mod:parrot_tools.quant.risk_metrics.md)

Risk Metrics Engine for QuantToolkit.

## [parrot_tools.quant.stress_testing](summaries/mod:parrot_tools.quant.stress_testing.md)

Stress Testing Framework for QuantToolkit.

## [parrot_tools.quant.toolkit](summaries/mod:parrot_tools.quant.toolkit.md)

QuantToolkit - Quantitative Risk Analysis Toolkit.

## [parrot_tools.quant.volatility](summaries/mod:parrot_tools.quant.volatility.md)

Volatility Analytics for QuantToolkit.

## [parrot_tools.querytoolkit](summaries/mod:parrot_tools.querytoolkit.md)

Module parrot_tools.querytoolkit

## [parrot_tools.quickeda](summaries/mod:parrot_tools.quickeda.md)

Quick EDA Tool - Comprehensive Exploratory Data Analysis for pandas DataFrames.

## [parrot_tools.reddit](summaries/mod:parrot_tools.reddit.md)

Reddit Toolkit for AI-Parrot.

## [parrot_tools.regression_analysis](summaries/mod:parrot_tools.regression_analysis.md)

RegressionAnalysisTool — linear/polynomial/log regression.

## [parrot_tools.resttool](summaries/mod:parrot_tools.resttool.md)

RESTTool - A tool for calling REST APIs with natural language interface.

## [parrot_tools.retail](summaries/mod:parrot_tools.retail.md)

Module parrot_tools.retail

## [parrot_tools.retail.bby](summaries/mod:parrot_tools.retail.bby.md)

BestBuy API Toolkit - Unified toolkit for BestBuy operations.

## [parrot_tools.rss](summaries/mod:parrot_tools.rss.md)

RSS Feed Reader Toolkit — archive RSS articles to disk, feed the LLM only

## [parrot_tools.rss.fetcher](summaries/mod:parrot_tools.rss.fetcher.md)

Article and feed fetching for the RSS Feed Reader Toolkit.

## [parrot_tools.rss.models](summaries/mod:parrot_tools.rss.models.md)

Pydantic models and internal data structures for the RSS Feed Reader Toolkit.

## [parrot_tools.rss.storage](summaries/mod:parrot_tools.rss.storage.md)

Disk storage for archived RSS articles.

## [parrot_tools.rss.toolkit](summaries/mod:parrot_tools.rss.toolkit.md)

RSS Feed Reader Toolkit.

## [parrot_tools.s3](summaries/mod:parrot_tools.s3.md)

parrot_tools.s3 — Agnostic S3 report reader toolkit and utilities.

## [parrot_tools.s3.comparator](summaries/mod:parrot_tools.s3.comparator.md)

GenericReportComparator — agnostic structural diff for S3-stored reports.

## [parrot_tools.s3.report_reader](summaries/mod:parrot_tools.s3.report_reader.md)

S3ReportReaderToolkit — LLM-facing agnostic S3 report reader.

## [parrot_tools.sandboxtool](summaries/mod:parrot_tools.sandboxtool.md)

AI-Parrot gVisor Sandbox Tool

## [parrot_tools.sassie](summaries/mod:parrot_tools.sassie.md)

Module parrot_tools.sassie

## [parrot_tools.scraping](summaries/mod:parrot_tools.scraping.md)

Module parrot_tools.scraping

## [parrot_tools.scraping.advanced_actions](summaries/mod:parrot_tools.scraping.advanced_actions.md)

Advanced action dispatch — Loop, Conditional, and template substitution.

## [parrot_tools.scraping.base_registry](summaries/mod:parrot_tools.scraping.base_registry.md)

BasePlanRegistry — Generic disk-backed plan registry.

## [parrot_tools.scraping.crawl_graph](summaries/mod:parrot_tools.scraping.crawl_graph.md)

CrawlGraph & CrawlNode for the CrawlEngine.

## [parrot_tools.scraping.crawl_strategy](summaries/mod:parrot_tools.scraping.crawl_strategy.md)

Pluggable crawl traversal strategies for the CrawlEngine.

## [parrot_tools.scraping.crawler](summaries/mod:parrot_tools.scraping.crawler.md)

CrawlEngine — multi-page crawl orchestrator for the WebScrapingToolkit.

## [parrot_tools.scraping.driver](summaries/mod:parrot_tools.scraping.driver.md)

Enhanced Selenium Setup for WebScrapingTool

## [parrot_tools.scraping.driver_context](summaries/mod:parrot_tools.scraping.driver_context.md)

Driver Context Manager — manages browser driver lifecycle.

## [parrot_tools.scraping.driver_factory](summaries/mod:parrot_tools.scraping.driver_factory.md)

Factory for creating browser automation driver instances.

## [parrot_tools.scraping.drivers](summaries/mod:parrot_tools.scraping.drivers.md)

Browser automation drivers for the scraping toolkit.

## [parrot_tools.scraping.drivers.abstract](summaries/mod:parrot_tools.scraping.drivers.abstract.md)

Abstract driver interface for browser automation.

## [parrot_tools.scraping.drivers.page_driver](summaries/mod:parrot_tools.scraping.drivers.page_driver.md)

PageDriver — a lightweight AbstractDriver over a single Playwright Page.

## [parrot_tools.scraping.drivers.playwright_config](summaries/mod:parrot_tools.scraping.drivers.playwright_config.md)

Playwright browser configuration dataclass.

## [parrot_tools.scraping.drivers.playwright_driver](summaries/mod:parrot_tools.scraping.drivers.playwright_driver.md)

Playwright-based browser automation driver.

## [parrot_tools.scraping.drivers.selenium_driver](summaries/mod:parrot_tools.scraping.drivers.selenium_driver.md)

Selenium-based browser automation driver.

## [parrot_tools.scraping.executor](summaries/mod:parrot_tools.scraping.executor.md)

Step Executor — standalone scraping plan execution.

## [parrot_tools.scraping.extraction_models](summaries/mod:parrot_tools.scraping.extraction_models.md)

ExtractionPlan Data Models.

## [parrot_tools.scraping.extraction_plan_generator](summaries/mod:parrot_tools.scraping.extraction_plan_generator.md)

ExtractionPlanGenerator — LLM-based ExtractionPlan generation.

## [parrot_tools.scraping.extraction_plans](summaries/mod:parrot_tools.scraping.extraction_plans.md)

Module parrot_tools.scraping.extraction_plans

## [parrot_tools.scraping.extraction_plans._prebuilt](summaries/mod:parrot_tools.scraping.extraction_plans._prebuilt.md)

Module parrot_tools.scraping.extraction_plans._prebuilt

## [parrot_tools.scraping.extraction_registry](summaries/mod:parrot_tools.scraping.extraction_registry.md)

ExtractionPlanRegistry — Disk-backed registry for ExtractionPlans.

## [parrot_tools.scraping.flow_executor](summaries/mod:parrot_tools.scraping.flow_executor.md)

FlowExecutor — orchestration engine for ScrapingFlow execution.

## [parrot_tools.scraping.flow_models](summaries/mod:parrot_tools.scraping.flow_models.md)

ScrapingFlow DAG models — FlowNode, ScrapingFlow, FlowResult.

## [parrot_tools.scraping.link_discoverer](summaries/mod:parrot_tools.scraping.link_discoverer.md)

Link discovery for the CrawlEngine.

## [parrot_tools.scraping.models](summaries/mod:parrot_tools.scraping.models.md)

Browser Action System for AI-Parrot WebScrapingTool

## [parrot_tools.scraping.options](summaries/mod:parrot_tools.scraping.options.md)

Module parrot_tools.scraping.options

## [parrot_tools.scraping.orchestrator](summaries/mod:parrot_tools.scraping.orchestrator.md)

ScrapingOrchestrator for AI-Parrot

## [parrot_tools.scraping.page_snapshot](summaries/mod:parrot_tools.scraping.page_snapshot.md)

Page snapshot builder for LLM-based plan generation.

## [parrot_tools.scraping.plan](summaries/mod:parrot_tools.scraping.plan.md)

ScrapingPlan & PlanRegistryEntry Models.

## [parrot_tools.scraping.plan_generator](summaries/mod:parrot_tools.scraping.plan_generator.md)

PlanGenerator — LLM-based scraping plan generation.

## [parrot_tools.scraping.plan_io](summaries/mod:parrot_tools.scraping.plan_io.md)

Plan File I/O Helpers.

## [parrot_tools.scraping.recall_processor](summaries/mod:parrot_tools.scraping.recall_processor.md)

RecallProcessor — Post-extraction LLM recall for rag_text generation and gap-filling.

## [parrot_tools.scraping.registry](summaries/mod:parrot_tools.scraping.registry.md)

PlanRegistry — Async, disk-backed index mapping URLs to saved plan files.

## [parrot_tools.scraping.session_manager](summaries/mod:parrot_tools.scraping.session_manager.md)

SessionManager — BrowserContext lifecycle per session label.

## [parrot_tools.scraping.template_plan](summaries/mod:parrot_tools.scraping.template_plan.md)

TemplatePlan & ParamSpec — parameterized scraping plan templates.

## [parrot_tools.scraping.tool](summaries/mod:parrot_tools.scraping.tool.md)

WebScrapingTool for AI-Parrot

## [parrot_tools.scraping.toolkit](summaries/mod:parrot_tools.scraping.toolkit.md)

WebScrapingToolkit — AbstractToolkit-based entry point for scraping.

## [parrot_tools.scraping.toolkit_models](summaries/mod:parrot_tools.scraping.toolkit_models.md)

Toolkit data models for WebScrapingToolkit.

## [parrot_tools.scraping.url_utils](summaries/mod:parrot_tools.scraping.url_utils.md)

URL normalization utilities for the CrawlEngine.

## [parrot_tools.seasonaldetection](summaries/mod:parrot_tools.seasonaldetection.md)

SeasonalDetectionTool for detecting stationarity in time series data using ADF and KPSS tests.

## [parrot_tools.security](summaries/mod:parrot_tools.security.md)

AI-Parrot Security Toolkits Suite.

## [parrot_tools.security.advisory_engine](summaries/mod:parrot_tools.security.advisory_engine.md)

SecurityAdvisoryEngine — day-over-day diff and SOC2 control mapping.

## [parrot_tools.security.base_executor](summaries/mod:parrot_tools.security.base_executor.md)

Base executor for running CLI-based security scanners.

## [parrot_tools.security.base_parser](summaries/mod:parrot_tools.security.base_parser.md)

Base parser for normalizing security scanner output.

## [parrot_tools.security.checkov](summaries/mod:parrot_tools.security.checkov.md)

Checkov IaC security scanner integration.

## [parrot_tools.security.checkov.config](summaries/mod:parrot_tools.security.checkov.config.md)

Checkov configuration model.

## [parrot_tools.security.checkov.executor](summaries/mod:parrot_tools.security.checkov.executor.md)

Checkov executor for running IaC security scans.

## [parrot_tools.security.checkov.parser](summaries/mod:parrot_tools.security.checkov.parser.md)

Checkov output parser.

## [parrot_tools.security.cloud_posture_toolkit](summaries/mod:parrot_tools.security.cloud_posture_toolkit.md)

Cloud Security Posture Management Toolkit.

## [parrot_tools.security.compliance_report_toolkit](summaries/mod:parrot_tools.security.compliance_report_toolkit.md)

Compliance Report Toolkit — Multi-scanner orchestration and reporting.

## [parrot_tools.security.container_security_toolkit](summaries/mod:parrot_tools.security.container_security_toolkit.md)

Container Security Toolkit.

## [parrot_tools.security.models](summaries/mod:parrot_tools.security.models.md)

Unified security data models for the Security Toolkits Suite.

## [parrot_tools.security.parsers](summaries/mod:parrot_tools.security.parsers.md)

Catalog-level scanner parser registry.

## [parrot_tools.security.parsers._types](summaries/mod:parrot_tools.security.parsers._types.md)

Shared types for the catalog-level scanner parser registry.

## [parrot_tools.security.parsers.aggregator](summaries/mod:parrot_tools.security.parsers.aggregator.md)

Catalog-level Aggregator passthrough parser.

## [parrot_tools.security.parsers.checkov](summaries/mod:parrot_tools.security.parsers.checkov.md)

Catalog-level Checkov JSON parser.

## [parrot_tools.security.parsers.cloudsploit](summaries/mod:parrot_tools.security.parsers.cloudsploit.md)

Catalog-level CloudSploit JSON parser.

## [parrot_tools.security.parsers.prowler](summaries/mod:parrot_tools.security.parsers.prowler.md)

Catalog-level Prowler JSON parser.

## [parrot_tools.security.parsers.trivy](summaries/mod:parrot_tools.security.parsers.trivy.md)

Catalog-level Trivy JSON parser.

## [parrot_tools.security.persistence](summaries/mod:parrot_tools.security.persistence.md)

ReportPersistenceMixin — catalog write-side mixin for producer toolkits.

## [parrot_tools.security.prowler](summaries/mod:parrot_tools.security.prowler.md)

Prowler security scanner integration.

## [parrot_tools.security.prowler.config](summaries/mod:parrot_tools.security.prowler.config.md)

Prowler-specific configuration.

## [parrot_tools.security.prowler.executor](summaries/mod:parrot_tools.security.prowler.executor.md)

Prowler executor for running cloud security scans.

## [parrot_tools.security.prowler.parser](summaries/mod:parrot_tools.security.prowler.parser.md)

Prowler output parser.

## [parrot_tools.security.report_toolkit](summaries/mod:parrot_tools.security.report_toolkit.md)

SecurityReportToolkit — LLM-facing read side of the security report catalog.

## [parrot_tools.security.reports](summaries/mod:parrot_tools.security.reports.md)

Security Reports Package.

## [parrot_tools.security.reports.compliance_mapper](summaries/mod:parrot_tools.security.reports.compliance_mapper.md)

Compliance Mapper for security findings.

## [parrot_tools.security.reports.generator](summaries/mod:parrot_tools.security.reports.generator.md)

Report Generator for security scan results.

## [parrot_tools.security.scoutsuite](summaries/mod:parrot_tools.security.scoutsuite.md)

Module parrot_tools.security.scoutsuite

## [parrot_tools.security.scoutsuite.config](summaries/mod:parrot_tools.security.scoutsuite.config.md)

ScoutSuite-specific configuration.

## [parrot_tools.security.scoutsuite.executor](summaries/mod:parrot_tools.security.scoutsuite.executor.md)

ScoutSuite executor for running cloud security scans.

## [parrot_tools.security.scoutsuite.parser](summaries/mod:parrot_tools.security.scoutsuite.parser.md)

Parser for ScoutSuite security findings.

## [parrot_tools.security.secrets_iac_toolkit](summaries/mod:parrot_tools.security.secrets_iac_toolkit.md)

Secrets and Infrastructure as Code Security Toolkit.

## [parrot_tools.security.soc2_advisory](summaries/mod:parrot_tools.security.soc2_advisory.md)

SOC2AdvisoryToolkit — LLM-facing read-only SOC2 advisory tools.

## [parrot_tools.security.summarizer](summaries/mod:parrot_tools.security.summarizer.md)

Weekly and monthly security report summarizers.

## [parrot_tools.security.trivy](summaries/mod:parrot_tools.security.trivy.md)

Trivy security scanner integration.

## [parrot_tools.security.trivy.config](summaries/mod:parrot_tools.security.trivy.config.md)

Trivy configuration model.

## [parrot_tools.security.trivy.executor](summaries/mod:parrot_tools.security.trivy.executor.md)

Trivy executor for running security scans.

## [parrot_tools.security.trivy.parser](summaries/mod:parrot_tools.security.trivy.parser.md)

Trivy output parser.

## [parrot_tools.sensitivity_analysis](summaries/mod:parrot_tools.sensitivity_analysis.md)

SensitivityAnalysisTool — One-at-a-time sensitivity analysis.

## [parrot_tools.serpapi](summaries/mod:parrot_tools.serpapi.md)

SerpApi Search Tool implementation for the ai-parrot framework.

## [parrot_tools.shell_tool](summaries/mod:parrot_tools.shell_tool.md)

Module parrot_tools.shell_tool

## [parrot_tools.shell_tool.actions](summaries/mod:parrot_tools.shell_tool.actions.md)

Module parrot_tools.shell_tool.actions

## [parrot_tools.shell_tool.engine](summaries/mod:parrot_tools.shell_tool.engine.md)

Module parrot_tools.shell_tool.engine

## [parrot_tools.shell_tool.models](summaries/mod:parrot_tools.shell_tool.models.md)

Module parrot_tools.shell_tool.models

## [parrot_tools.shell_tool.security](summaries/mod:parrot_tools.shell_tool.security.md)

ShellTool Security — re-export shim (FEAT-252).

## [parrot_tools.shell_tool.tool](summaries/mod:parrot_tools.shell_tool.tool.md)

Module parrot_tools.shell_tool.tool

## [parrot_tools.sitesearch](summaries/mod:parrot_tools.sitesearch.md)

SiteSearch package for site-specific crawling with preset support.

## [parrot_tools.sitesearch.presets](summaries/mod:parrot_tools.sitesearch.presets.md)

Preset configurations for site-specific searches.

## [parrot_tools.sitesearch.tool](summaries/mod:parrot_tools.sitesearch.tool.md)

SiteSearch tool for site-specific crawling with markdown output.

## [parrot_tools.sitesearch.toolkit](summaries/mod:parrot_tools.sitesearch.toolkit.md)

SiteSearchToolkit for site-specific searches with preset support.

## [parrot_tools.statistical_tests](summaries/mod:parrot_tools.statistical_tests.md)

StatisticalTestsTool — t-test, ANOVA, chi-square, normality.

## [parrot_tools.system_health](summaries/mod:parrot_tools.system_health.md)

System Health Tool — read-only host metrics for agent monitoring.

## [parrot_tools.system_health.tool](summaries/mod:parrot_tools.system_health.tool.md)

Read-only system health monitoring tool.

## [parrot_tools.technical_analysis](summaries/mod:parrot_tools.technical_analysis.md)

Technical Analysis Tool

## [parrot_tools.textfile](summaries/mod:parrot_tools.textfile.md)

Module parrot_tools.textfile

## [parrot_tools.think](summaries/mod:parrot_tools.think.md)

ThinkTool - A metacognitive tool for explicit agent reasoning.

## [parrot_tools.toolkit](summaries/mod:parrot_tools.toolkit.md)

Re-export from core — canonical location is parrot.tools.toolkit.

## [parrot_tools.troc](summaries/mod:parrot_tools.troc.md)

Module parrot_tools.troc

## [parrot_tools.troc.tool](summaries/mod:parrot_tools.troc.tool.md)

TROCOperationsToolkit - KPI computation tools for TROC vending operations.

## [parrot_tools.version](summaries/mod:parrot_tools.version.md)

AI-Parrot Tools Meta information.

## [parrot_tools.whatif](summaries/mod:parrot_tools.whatif.md)

What-If Scenario Analysis Tool for AI-Parrot

## [parrot_tools.whatif_toolkit](summaries/mod:parrot_tools.whatif_toolkit.md)

WhatIf Toolkit — Decomposed What-If Scenario Analysis.

## [parrot_tools.workday](summaries/mod:parrot_tools.workday.md)

Module parrot_tools.workday

## [parrot_tools.workday.models](summaries/mod:parrot_tools.workday.models.md)

Workday Response Models and Structured Output Parser

## [parrot_tools.workday.tool](summaries/mod:parrot_tools.workday.tool.md)

Workday Toolkit - A unified toolkit for Workday SOAP operations with multi-service support.

## [parrot_tools.yfinance](summaries/mod:parrot_tools.yfinance.md)

YFinance tool for retrieving market data via Yahoo Finance.

## [parrot_tools.zammad](summaries/mod:parrot_tools.zammad.md)

ZammadToolkit — exposes Zammad helpdesk operations as agent tools.

## [parrot_tools.zipcode](summaries/mod:parrot_tools.zipcode.md)

ZipcodeAPI Toolkit - A unified toolkit for zipcode operations.

## [parrot_tools.zoom](summaries/mod:parrot_tools.zoom.md)

Module parrot_tools.zoom

## [parrot_tools.zoom.client](summaries/mod:parrot_tools.zoom.client.md)

Module parrot_tools.zoom.client

## [parrot_tools.zoomtoolkit](summaries/mod:parrot_tools.zoomtoolkit.md)

Module parrot_tools.zoomtoolkit

## [parrot](overviews/pkg:parrot.md)

Package parrot (49 modules, 45 sub-packages).

## [parrot.a2a](overviews/pkg:parrot.a2a.md)

Package parrot.a2a (9 modules, 0 sub-packages).

## [parrot.advisors](overviews/pkg:parrot.advisors.md)

Package parrot.advisors (9 modules, 2 sub-packages).

## [parrot.advisors.catalog](overviews/pkg:parrot.advisors.catalog.md)

Package parrot.advisors.catalog (3 modules, 0 sub-packages).

## [parrot.advisors.tools](overviews/pkg:parrot.advisors.tools.md)

Package parrot.advisors.tools (11 modules, 0 sub-packages).

## [parrot.agents](overviews/pkg:parrot.agents.md)

Package parrot.agents (1 modules, 0 sub-packages).

## [parrot.auth](overviews/pkg:parrot.auth.md)

Package parrot.auth (23 modules, 1 sub-packages).

## [parrot.auth.oauth2](overviews/pkg:parrot.auth.oauth2.md)

Package parrot.auth.oauth2 (9 modules, 0 sub-packages).

## [parrot.autonomous](overviews/pkg:parrot.autonomous.md)

Package parrot.autonomous (12 modules, 2 sub-packages).

## [parrot.autonomous.deploy](overviews/pkg:parrot.autonomous.deploy.md)

Package parrot.autonomous.deploy (2 modules, 0 sub-packages).

## [parrot.autonomous.transport](overviews/pkg:parrot.autonomous.transport.md)

Package parrot.autonomous.transport (2 modules, 1 sub-packages).

## [parrot.autonomous.transport.filesystem](overviews/pkg:parrot.autonomous.transport.filesystem.md)

Package parrot.autonomous.transport.filesystem (10 modules, 0 sub-packages).

## [parrot.bots](overviews/pkg:parrot.bots.md)

Package parrot.bots (26 modules, 7 sub-packages).

## [parrot.bots.database](overviews/pkg:parrot.bots.database.md)

Package parrot.bots.database (7 modules, 1 sub-packages).

## [parrot.bots.database.toolkits](overviews/pkg:parrot.bots.database.toolkits.md)

Package parrot.bots.database.toolkits (9 modules, 0 sub-packages).

## [parrot.bots.factory](overviews/pkg:parrot.bots.factory.md)

Package parrot.bots.factory (3 modules, 1 sub-packages).

## [parrot.bots.factory.tools](overviews/pkg:parrot.bots.factory.tools.md)

Package parrot.bots.factory.tools (4 modules, 0 sub-packages).

## [parrot.bots.flows](overviews/pkg:parrot.bots.flows.md)

Package parrot.bots.flows (6 modules, 4 sub-packages).

## [parrot.bots.flows.agents](overviews/pkg:parrot.bots.flows.agents.md)

Package parrot.bots.flows.agents (3 modules, 0 sub-packages).

## [parrot.bots.flows.core](overviews/pkg:parrot.bots.flows.core.md)

Package parrot.bots.flows.core (7 modules, 1 sub-packages).

## [parrot.bots.flows.core.storage](overviews/pkg:parrot.bots.flows.core.storage.md)

Package parrot.bots.flows.core.storage (6 modules, 1 sub-packages).

## [parrot.bots.flows.core.storage.backends](overviews/pkg:parrot.bots.flows.core.storage.backends.md)

Package parrot.bots.flows.core.storage.backends (5 modules, 0 sub-packages).

## [parrot.bots.flows.crew](overviews/pkg:parrot.bots.flows.crew.md)

Package parrot.bots.flows.crew (4 modules, 0 sub-packages).

## [parrot.bots.flows.flow](overviews/pkg:parrot.bots.flows.flow.md)

Package parrot.bots.flows.flow (8 modules, 0 sub-packages).

## [parrot.bots.mixins](overviews/pkg:parrot.bots.mixins.md)

Package parrot.bots.mixins (1 modules, 0 sub-packages).

## [parrot.bots.prompts](overviews/pkg:parrot.bots.prompts.md)

Package parrot.bots.prompts (8 modules, 0 sub-packages).

## [parrot.bots.scraper](overviews/pkg:parrot.bots.scraper.md)

Package parrot.bots.scraper (3 modules, 0 sub-packages).

## [parrot.bots.stores](overviews/pkg:parrot.bots.stores.md)

Package parrot.bots.stores (1 modules, 0 sub-packages).

## [parrot.cli](overviews/pkg:parrot.cli.md)

Package parrot.cli (7 modules, 0 sub-packages).

## [parrot.clients](overviews/pkg:parrot.clients.md)

Package parrot.clients (20 modules, 1 sub-packages).

## [parrot.clients.google](overviews/pkg:parrot.clients.google.md)

Package parrot.clients.google (3 modules, 0 sub-packages).

## [parrot.core](overviews/pkg:parrot.core.md)

Package parrot.core (5 modules, 3 sub-packages).

## [parrot.core.events](overviews/pkg:parrot.core.events.md)

Package parrot.core.events (2 modules, 1 sub-packages).

## [parrot.core.events.lifecycle](overviews/pkg:parrot.core.events.lifecycle.md)

Package parrot.core.events.lifecycle (11 modules, 2 sub-packages).

## [parrot.core.events.lifecycle.events](overviews/pkg:parrot.core.events.lifecycle.events.md)

Package parrot.core.events.lifecycle.events (6 modules, 0 sub-packages).

## [parrot.core.events.lifecycle.subscribers](overviews/pkg:parrot.core.events.lifecycle.subscribers.md)

Package parrot.core.events.lifecycle.subscribers (3 modules, 0 sub-packages).

## [parrot.core.hooks](overviews/pkg:parrot.core.hooks.md)

Package parrot.core.hooks (16 modules, 1 sub-packages).

## [parrot.core.hooks.brokers](overviews/pkg:parrot.core.hooks.brokers.md)

Package parrot.core.hooks.brokers (5 modules, 0 sub-packages).

## [parrot.core.tools](overviews/pkg:parrot.core.tools.md)

Package parrot.core.tools (1 modules, 0 sub-packages).

## [parrot.embeddings](overviews/pkg:parrot.embeddings.md)

Package parrot.embeddings (10 modules, 1 sub-packages).

## [parrot.embeddings.multimodal](overviews/pkg:parrot.embeddings.multimodal.md)

Package parrot.embeddings.multimodal (3 modules, 0 sub-packages).

## [parrot.eval](overviews/pkg:parrot.eval.md)

Package parrot.eval (9 modules, 2 sub-packages).

## [parrot.eval.evaluators](overviews/pkg:parrot.eval.evaluators.md)

Package parrot.eval.evaluators (2 modules, 0 sub-packages).

## [parrot.eval.sandbox](overviews/pkg:parrot.eval.sandbox.md)

Package parrot.eval.sandbox (3 modules, 0 sub-packages).

## [parrot.flows](overviews/pkg:parrot.flows.md)

Package parrot.flows (1 modules, 1 sub-packages).

## [parrot.flows.dev_loop](overviews/pkg:parrot.flows.dev_loop.md)

Package parrot.flows.dev_loop (12 modules, 1 sub-packages).

## [parrot.flows.dev_loop.nodes](overviews/pkg:parrot.flows.dev_loop.nodes.md)

Package parrot.flows.dev_loop.nodes (10 modules, 0 sub-packages).

## [parrot.forms](overviews/pkg:parrot.forms.md)

Package parrot.forms (12 modules, 3 sub-packages).

## [parrot.forms.extractors](overviews/pkg:parrot.forms.extractors.md)

Package parrot.forms.extractors (4 modules, 0 sub-packages).

## [parrot.forms.renderers](overviews/pkg:parrot.forms.renderers.md)

Package parrot.forms.renderers (4 modules, 0 sub-packages).

## [parrot.forms.tools](overviews/pkg:parrot.forms.tools.md)

Package parrot.forms.tools (3 modules, 0 sub-packages).

## [parrot.handlers](overviews/pkg:parrot.handlers.md)

Package parrot.handlers (49 modules, 7 sub-packages).

## [parrot.handlers.agents](overviews/pkg:parrot.handlers.agents.md)

Package parrot.handlers.agents (6 modules, 0 sub-packages).

## [parrot.handlers.crew](overviews/pkg:parrot.handlers.crew.md)

Package parrot.handlers.crew (8 modules, 0 sub-packages).

## [parrot.handlers.database](overviews/pkg:parrot.handlers.database.md)

Package parrot.handlers.database (1 modules, 0 sub-packages).

## [parrot.handlers.jobs](overviews/pkg:parrot.handlers.jobs.md)

Package parrot.handlers.jobs (5 modules, 0 sub-packages).

## [parrot.handlers.models](overviews/pkg:parrot.handlers.models.md)

Package parrot.handlers.models (6 modules, 0 sub-packages).

## [parrot.handlers.scraping](overviews/pkg:parrot.handlers.scraping.md)

Package parrot.handlers.scraping (3 modules, 0 sub-packages).

## [parrot.handlers.stores](overviews/pkg:parrot.handlers.stores.md)

Package parrot.handlers.stores (2 modules, 0 sub-packages).

## [parrot.helpers](overviews/pkg:parrot.helpers.md)

Package parrot.helpers (1 modules, 0 sub-packages).

## [parrot.human](overviews/pkg:parrot.human.md)

Package parrot.human (9 modules, 2 sub-packages).

## [parrot.human.actions](overviews/pkg:parrot.human.actions.md)

Package parrot.human.actions (4 modules, 1 sub-packages).

## [parrot.human.actions.backends](overviews/pkg:parrot.human.actions.backends.md)

Package parrot.human.actions.backends (5 modules, 0 sub-packages).

## [parrot.human.channels](overviews/pkg:parrot.human.channels.md)

Package parrot.human.channels (5 modules, 0 sub-packages).

## [parrot.install](overviews/pkg:parrot.install.md)

Package parrot.install (2 modules, 0 sub-packages).

## [parrot.integrations](overviews/pkg:parrot.integrations.md)

Package parrot.integrations (16 modules, 10 sub-packages).

## [parrot.integrations.a2a](overviews/pkg:parrot.integrations.a2a.md)

Package parrot.integrations.a2a (1 modules, 0 sub-packages).

## [parrot.integrations.core](overviews/pkg:parrot.integrations.core.md)

Package parrot.integrations.core (2 modules, 1 sub-packages).

## [parrot.integrations.core.auth](overviews/pkg:parrot.integrations.core.auth.md)

Package parrot.integrations.core.auth (2 modules, 0 sub-packages).

## [parrot.integrations.liveavatar](overviews/pkg:parrot.integrations.liveavatar.md)

Package parrot.integrations.liveavatar (13 modules, 0 sub-packages).

## [parrot.integrations.matrix](overviews/pkg:parrot.integrations.matrix.md)

Package parrot.integrations.matrix (9 modules, 1 sub-packages).

## [parrot.integrations.matrix.crew](overviews/pkg:parrot.integrations.matrix.crew.md)

Package parrot.integrations.matrix.crew (9 modules, 0 sub-packages).

## [parrot.integrations.mcp](overviews/pkg:parrot.integrations.mcp.md)

Package parrot.integrations.mcp (1 modules, 0 sub-packages).

## [parrot.integrations.msagentsdk](overviews/pkg:parrot.integrations.msagentsdk.md)

Package parrot.integrations.msagentsdk (8 modules, 0 sub-packages).

## [parrot.integrations.msteams](overviews/pkg:parrot.integrations.msteams.md)

Package parrot.integrations.msteams (13 modules, 3 sub-packages).

## [parrot.integrations.msteams.commands](overviews/pkg:parrot.integrations.msteams.commands.md)

Package parrot.integrations.msteams.commands (2 modules, 0 sub-packages).

## [parrot.integrations.msteams.dialogs](overviews/pkg:parrot.integrations.msteams.dialogs.md)

Package parrot.integrations.msteams.dialogs (4 modules, 1 sub-packages).

## [parrot.integrations.msteams.dialogs.presets](overviews/pkg:parrot.integrations.msteams.dialogs.presets.md)

Package parrot.integrations.msteams.dialogs.presets (5 modules, 0 sub-packages).

## [parrot.integrations.msteams.voice](overviews/pkg:parrot.integrations.msteams.voice.md)

Package parrot.integrations.msteams.voice (5 modules, 0 sub-packages).

## [parrot.integrations.slack](overviews/pkg:parrot.integrations.slack.md)

Package parrot.integrations.slack (10 modules, 1 sub-packages).

## [parrot.integrations.slack.commands](overviews/pkg:parrot.integrations.slack.commands.md)

Package parrot.integrations.slack.commands (1 modules, 0 sub-packages).

## [parrot.integrations.telegram](overviews/pkg:parrot.integrations.telegram.md)

Package parrot.integrations.telegram (19 modules, 1 sub-packages).

## [parrot.integrations.telegram.crew](overviews/pkg:parrot.integrations.telegram.crew.md)

Package parrot.integrations.telegram.crew (8 modules, 0 sub-packages).

## [parrot.integrations.whatsapp](overviews/pkg:parrot.integrations.whatsapp.md)

Package parrot.integrations.whatsapp (6 modules, 0 sub-packages).

## [parrot.interfaces](overviews/pkg:parrot.interfaces.md)

Package parrot.interfaces (22 modules, 2 sub-packages).

## [parrot.interfaces.file](overviews/pkg:parrot.interfaces.file.md)

Package parrot.interfaces.file (5 modules, 0 sub-packages).

## [parrot.interfaces.images](overviews/pkg:parrot.interfaces.images.md)

Package parrot.interfaces.images (1 modules, 1 sub-packages).

## [parrot.interfaces.images.plugins](overviews/pkg:parrot.interfaces.images.plugins.md)

Package parrot.interfaces.images.plugins (10 modules, 0 sub-packages).

## [parrot.knowledge](overviews/pkg:parrot.knowledge.md)

Package parrot.knowledge (5 modules, 5 sub-packages).

## [parrot.knowledge.graphindex](overviews/pkg:parrot.knowledge.graphindex.md)

Package parrot.knowledge.graphindex (17 modules, 1 sub-packages).

## [parrot.knowledge.graphindex.extractors](overviews/pkg:parrot.knowledge.graphindex.extractors.md)

Package parrot.knowledge.graphindex.extractors (4 modules, 0 sub-packages).

## [parrot.knowledge.okf](overviews/pkg:parrot.knowledge.okf.md)

Package parrot.knowledge.okf (4 modules, 0 sub-packages).

## [parrot.knowledge.ontology](overviews/pkg:parrot.knowledge.ontology.md)

Package parrot.knowledge.ontology (19 modules, 2 sub-packages).

## [parrot.knowledge.ontology.concept_catalog](overviews/pkg:parrot.knowledge.ontology.concept_catalog.md)

Package parrot.knowledge.ontology.concept_catalog (6 modules, 0 sub-packages).

## [parrot.knowledge.ontology.schema_overlay](overviews/pkg:parrot.knowledge.ontology.schema_overlay.md)

Package parrot.knowledge.ontology.schema_overlay (5 modules, 0 sub-packages).

## [parrot.knowledge.pageindex](overviews/pkg:parrot.knowledge.pageindex.md)

Package parrot.knowledge.pageindex (16 modules, 1 sub-packages).

## [parrot.knowledge.pageindex.okf](overviews/pkg:parrot.knowledge.pageindex.okf.md)

Package parrot.knowledge.pageindex.okf (9 modules, 0 sub-packages).

## [parrot.knowledge.wiki](overviews/pkg:parrot.knowledge.wiki.md)

Package parrot.knowledge.wiki (10 modules, 0 sub-packages).

## [parrot.loaders](overviews/pkg:parrot.loaders.md)

Package parrot.loaders (2 modules, 1 sub-packages).

## [parrot.loaders.splitters](overviews/pkg:parrot.loaders.splitters.md)

Package parrot.loaders.splitters (4 modules, 0 sub-packages).

## [parrot.manager](overviews/pkg:parrot.manager.md)

Package parrot.manager (2 modules, 0 sub-packages).

## [parrot.mcp](overviews/pkg:parrot.mcp.md)

Package parrot.mcp (20 modules, 1 sub-packages).

## [parrot.mcp.transports](overviews/pkg:parrot.mcp.transports.md)

Package parrot.mcp.transports (8 modules, 0 sub-packages).

## [parrot.memory](overviews/pkg:parrot.memory.md)

Package parrot.memory (9 modules, 3 sub-packages).

## [parrot.memory.episodic](overviews/pkg:parrot.memory.episodic.md)

Package parrot.memory.episodic (10 modules, 1 sub-packages).

## [parrot.memory.episodic.backends](overviews/pkg:parrot.memory.episodic.backends.md)

Package parrot.memory.episodic.backends (4 modules, 0 sub-packages).

## [parrot.memory.skills](overviews/pkg:parrot.memory.skills.md)

Package parrot.memory.skills (7 modules, 0 sub-packages).

## [parrot.memory.unified](overviews/pkg:parrot.memory.unified.md)

Package parrot.memory.unified (5 modules, 0 sub-packages).

## [parrot.models](overviews/pkg:parrot.models.md)

Package parrot.models (26 modules, 0 sub-packages).

## [parrot.observability](overviews/pkg:parrot.observability.md)

Package parrot.observability (13 modules, 4 sub-packages).

## [parrot.observability.cost](overviews/pkg:parrot.observability.cost.md)

Package parrot.observability.cost (1 modules, 0 sub-packages).

## [parrot.observability.examples](overviews/pkg:parrot.observability.examples.md)

Package parrot.observability.examples (1 modules, 0 sub-packages).

## [parrot.observability.recorders](overviews/pkg:parrot.observability.recorders.md)

Package parrot.observability.recorders (6 modules, 0 sub-packages).

## [parrot.observability.subscribers](overviews/pkg:parrot.observability.subscribers.md)

Package parrot.observability.subscribers (2 modules, 0 sub-packages).

## [parrot.openapi](overviews/pkg:parrot.openapi.md)

Package parrot.openapi (1 modules, 0 sub-packages).

## [parrot.outputs](overviews/pkg:parrot.outputs.md)

Package parrot.outputs (5 modules, 3 sub-packages).

## [parrot.outputs.a2ui](overviews/pkg:parrot.outputs.a2ui.md)

Package parrot.outputs.a2ui (10 modules, 1 sub-packages).

## [parrot.outputs.a2ui.catalog](overviews/pkg:parrot.outputs.a2ui.catalog.md)

Package parrot.outputs.a2ui.catalog (2 modules, 1 sub-packages).

## [parrot.outputs.a2ui.catalog.components](overviews/pkg:parrot.outputs.a2ui.catalog.components.md)

Package parrot.outputs.a2ui.catalog.components (9 modules, 0 sub-packages).

## [parrot.outputs.a2ui_renderers](overviews/pkg:parrot.outputs.a2ui_renderers.md)

Package parrot.outputs.a2ui_renderers (5 modules, 0 sub-packages).

## [parrot.outputs.formats](overviews/pkg:parrot.outputs.formats.md)

Package parrot.outputs.formats (30 modules, 2 sub-packages).

## [parrot.outputs.formats.generators](overviews/pkg:parrot.outputs.formats.generators.md)

Package parrot.outputs.formats.generators (4 modules, 0 sub-packages).

## [parrot.outputs.formats.mixins](overviews/pkg:parrot.outputs.formats.mixins.md)

Package parrot.outputs.formats.mixins (1 modules, 0 sub-packages).

## [parrot.pipelines](overviews/pkg:parrot.pipelines.md)

Package parrot.pipelines (4 modules, 1 sub-packages).

## [parrot.pipelines.planogram](overviews/pkg:parrot.pipelines.planogram.md)

Package parrot.pipelines.planogram (3 modules, 1 sub-packages).

## [parrot.pipelines.planogram.types](overviews/pkg:parrot.pipelines.planogram.types.md)

Package parrot.pipelines.planogram.types (3 modules, 0 sub-packages).

## [parrot.plugins](overviews/pkg:parrot.plugins.md)

Package parrot.plugins (1 modules, 0 sub-packages).

## [parrot.registry](overviews/pkg:parrot.registry.md)

Package parrot.registry (4 modules, 2 sub-packages).

## [parrot.registry.capabilities](overviews/pkg:parrot.registry.capabilities.md)

Package parrot.registry.capabilities (2 modules, 0 sub-packages).

## [parrot.registry.routing](overviews/pkg:parrot.registry.routing.md)

Package parrot.registry.routing (8 modules, 0 sub-packages).

## [parrot.rerankers](overviews/pkg:parrot.rerankers.md)

Package parrot.rerankers (5 modules, 0 sub-packages).

## [parrot.scheduler](overviews/pkg:parrot.scheduler.md)

Package parrot.scheduler (3 modules, 0 sub-packages).

## [parrot.security](overviews/pkg:parrot.security.md)

Package parrot.security (8 modules, 0 sub-packages).

## [parrot.server](overviews/pkg:parrot.server.md)

Package parrot.server (1 modules, 0 sub-packages).

## [parrot.services](overviews/pkg:parrot.services.md)

Package parrot.services (11 modules, 0 sub-packages).

## [parrot.setup](overviews/pkg:parrot.setup.md)

Package parrot.setup (4 modules, 1 sub-packages).

## [parrot.setup.providers](overviews/pkg:parrot.setup.providers.md)

Package parrot.setup.providers (5 modules, 0 sub-packages).

## [parrot.skills](overviews/pkg:parrot.skills.md)

Package parrot.skills (9 modules, 0 sub-packages).

## [parrot.storage](overviews/pkg:parrot.storage.md)

Package parrot.storage (11 modules, 2 sub-packages).

## [parrot.storage.backends](overviews/pkg:parrot.storage.backends.md)

Package parrot.storage.backends (5 modules, 0 sub-packages).

## [parrot.storage.security_reports](overviews/pkg:parrot.storage.security_reports.md)

Package parrot.storage.security_reports (2 modules, 0 sub-packages).

## [parrot.stores](overviews/pkg:parrot.stores.md)

Package parrot.stores (14 modules, 3 sub-packages).

## [parrot.stores.kb](overviews/pkg:parrot.stores.kb.md)

Package parrot.stores.kb (9 modules, 0 sub-packages).

## [parrot.stores.parents](overviews/pkg:parrot.stores.parents.md)

Package parrot.stores.parents (3 modules, 0 sub-packages).

## [parrot.stores.utils](overviews/pkg:parrot.stores.utils.md)

Package parrot.stores.utils (2 modules, 0 sub-packages).

## [parrot.template](overviews/pkg:parrot.template.md)

Package parrot.template (1 modules, 0 sub-packages).

## [parrot.tools](overviews/pkg:parrot.tools.md)

Package parrot.tools (29 modules, 5 sub-packages).

## [parrot.tools.databasequery](overviews/pkg:parrot.tools.databasequery.md)

Package parrot.tools.databasequery (4 modules, 1 sub-packages).

## [parrot.tools.databasequery.sources](overviews/pkg:parrot.tools.databasequery.sources.md)

Package parrot.tools.databasequery.sources (13 modules, 0 sub-packages).

## [parrot.tools.dataset_manager](overviews/pkg:parrot.tools.dataset_manager.md)

Package parrot.tools.dataset_manager (7 modules, 3 sub-packages).

## [parrot.tools.dataset_manager.filtering](overviews/pkg:parrot.tools.dataset_manager.filtering.md)

Package parrot.tools.dataset_manager.filtering (4 modules, 0 sub-packages).

## [parrot.tools.dataset_manager.sources](overviews/pkg:parrot.tools.dataset_manager.sources.md)

Package parrot.tools.dataset_manager.sources (16 modules, 0 sub-packages).

## [parrot.tools.dataset_manager.spatial](overviews/pkg:parrot.tools.dataset_manager.spatial.md)

Package parrot.tools.dataset_manager.spatial (4 modules, 0 sub-packages).

## [parrot.tools.executors](overviews/pkg:parrot.tools.executors.md)

Package parrot.tools.executors (5 modules, 0 sub-packages).

## [parrot.tools.interactive](overviews/pkg:parrot.tools.interactive.md)

Package parrot.tools.interactive (1 modules, 0 sub-packages).

## [parrot.tools.working_memory](overviews/pkg:parrot.tools.working_memory.md)

Package parrot.tools.working_memory (5 modules, 1 sub-packages).

## [parrot.tools.working_memory.tests](overviews/pkg:parrot.tools.working_memory.tests.md)

Package parrot.tools.working_memory.tests (6 modules, 0 sub-packages).

## [parrot.utils](overviews/pkg:parrot.utils.md)

Package parrot.utils (7 modules, 0 sub-packages).

## [parrot.voice](overviews/pkg:parrot.voice.md)

Package parrot.voice (4 modules, 2 sub-packages).

## [parrot.voice.transcriber](overviews/pkg:parrot.voice.transcriber.md)

Package parrot.voice.transcriber (6 modules, 0 sub-packages).

## [parrot.voice.tts](overviews/pkg:parrot.voice.tts.md)

Package parrot.voice.tts (6 modules, 0 sub-packages).

## [parrot.yaml-rs](overviews/pkg:parrot.yaml-rs.md)

Package parrot.yaml-rs (0 modules, 1 sub-packages).

## [parrot.yaml-rs.python](overviews/pkg:parrot.yaml-rs.python.md)

Package parrot.yaml-rs.python (1 modules, 0 sub-packages).

## [parrot_formdesigner](overviews/pkg:parrot_formdesigner.md)

Package parrot_formdesigner (10 modules, 9 sub-packages).

## [parrot_formdesigner.api](overviews/pkg:parrot_formdesigner.api.md)

Package parrot_formdesigner.api (8 modules, 0 sub-packages).

## [parrot_formdesigner.audio](overviews/pkg:parrot_formdesigner.audio.md)

Package parrot_formdesigner.audio (1 modules, 0 sub-packages).

## [parrot_formdesigner.controls](overviews/pkg:parrot_formdesigner.controls.md)

Package parrot_formdesigner.controls (2 modules, 0 sub-packages).

## [parrot_formdesigner.core](overviews/pkg:parrot_formdesigner.core.md)

Package parrot_formdesigner.core (9 modules, 0 sub-packages).

## [parrot_formdesigner.extractors](overviews/pkg:parrot_formdesigner.extractors.md)

Package parrot_formdesigner.extractors (4 modules, 0 sub-packages).

## [parrot_formdesigner.renderers](overviews/pkg:parrot_formdesigner.renderers.md)

Package parrot_formdesigner.renderers (9 modules, 2 sub-packages).

## [parrot_formdesigner.renderers.fields](overviews/pkg:parrot_formdesigner.renderers.fields.md)

Package parrot_formdesigner.renderers.fields (1 modules, 0 sub-packages).

## [parrot_formdesigner.renderers.telegram](overviews/pkg:parrot_formdesigner.renderers.telegram.md)

Package parrot_formdesigner.renderers.telegram (3 modules, 0 sub-packages).

## [parrot_formdesigner.services](overviews/pkg:parrot_formdesigner.services.md)

Package parrot_formdesigner.services (31 modules, 0 sub-packages).

## [parrot_formdesigner.tools](overviews/pkg:parrot_formdesigner.tools.md)

Package parrot_formdesigner.tools (6 modules, 1 sub-packages).

## [parrot_formdesigner.tools.services](overviews/pkg:parrot_formdesigner.tools.services.md)

Package parrot_formdesigner.tools.services (3 modules, 0 sub-packages).

## [parrot_formdesigner.ui](overviews/pkg:parrot_formdesigner.ui.md)

Package parrot_formdesigner.ui (4 modules, 0 sub-packages).

## [parrot_loaders](overviews/pkg:parrot_loaders.md)

Package parrot_loaders (33 modules, 3 sub-packages).

## [parrot_loaders.extractors](overviews/pkg:parrot_loaders.extractors.md)

Package parrot_loaders.extractors (8 modules, 0 sub-packages).

## [parrot_loaders.files](overviews/pkg:parrot_loaders.files.md)

Package parrot_loaders.files (3 modules, 0 sub-packages).

## [parrot_loaders.ocr](overviews/pkg:parrot_loaders.ocr.md)

Package parrot_loaders.ocr (7 modules, 0 sub-packages).

## [parrot_pipelines](overviews/pkg:parrot_pipelines.md)

Package parrot_pipelines (6 modules, 2 sub-packages).

## [parrot_pipelines.handlers](overviews/pkg:parrot_pipelines.handlers.md)

Package parrot_pipelines.handlers (1 modules, 0 sub-packages).

## [parrot_pipelines.planogram](overviews/pkg:parrot_pipelines.planogram.md)

Package parrot_pipelines.planogram (4 modules, 2 sub-packages).

## [parrot_pipelines.planogram.grid](overviews/pkg:parrot_pipelines.planogram.grid.md)

Package parrot_pipelines.planogram.grid (5 modules, 0 sub-packages).

## [parrot_pipelines.planogram.types](overviews/pkg:parrot_pipelines.planogram.types.md)

Package parrot_pipelines.planogram.types (6 modules, 0 sub-packages).

## [parrot_tools](overviews/pkg:parrot_tools.md)

Package parrot_tools (113 modules, 37 sub-packages).

## [parrot_tools.aws](overviews/pkg:parrot_tools.aws.md)

Package parrot_tools.aws (14 modules, 0 sub-packages).

## [parrot_tools.backstage](overviews/pkg:parrot_tools.backstage.md)

Package parrot_tools.backstage (2 modules, 0 sub-packages).

## [parrot_tools.calculator](overviews/pkg:parrot_tools.calculator.md)

Package parrot_tools.calculator (2 modules, 1 sub-packages).

## [parrot_tools.calculator.operations](overviews/pkg:parrot_tools.calculator.operations.md)

Package parrot_tools.calculator.operations (2 modules, 0 sub-packages).

## [parrot_tools.cloudsploit](overviews/pkg:parrot_tools.cloudsploit.md)

Package parrot_tools.cloudsploit (7 modules, 0 sub-packages).

## [parrot_tools.codeinterpreter](overviews/pkg:parrot_tools.codeinterpreter.md)

Package parrot_tools.codeinterpreter (5 modules, 0 sub-packages).

## [parrot_tools.company_info](overviews/pkg:parrot_tools.company_info.md)

Package parrot_tools.company_info (1 modules, 0 sub-packages).

## [parrot_tools.computer](overviews/pkg:parrot_tools.computer.md)

Package parrot_tools.computer (4 modules, 0 sub-packages).

## [parrot_tools.database](overviews/pkg:parrot_tools.database.md)

Package parrot_tools.database (3 modules, 0 sub-packages).

## [parrot_tools.dataset_manager](overviews/pkg:parrot_tools.dataset_manager.md)

Package parrot_tools.dataset_manager (1 modules, 0 sub-packages).

## [parrot_tools.docker](overviews/pkg:parrot_tools.docker.md)

Package parrot_tools.docker (5 modules, 0 sub-packages).

## [parrot_tools.flowtask](overviews/pkg:parrot_tools.flowtask.md)

Package parrot_tools.flowtask (1 modules, 0 sub-packages).

## [parrot_tools.gigsmart](overviews/pkg:parrot_tools.gigsmart.md)

Package parrot_tools.gigsmart (2 modules, 0 sub-packages).

## [parrot_tools.google](overviews/pkg:parrot_tools.google.md)

Package parrot_tools.google (3 modules, 0 sub-packages).

## [parrot_tools.graphindex](overviews/pkg:parrot_tools.graphindex.md)

Package parrot_tools.graphindex (2 modules, 0 sub-packages).

## [parrot_tools.ibisworld](overviews/pkg:parrot_tools.ibisworld.md)

Package parrot_tools.ibisworld (1 modules, 0 sub-packages).

## [parrot_tools.ibkr](overviews/pkg:parrot_tools.ibkr.md)

Package parrot_tools.ibkr (5 modules, 0 sub-packages).

## [parrot_tools.interfaces](overviews/pkg:parrot_tools.interfaces.md)

Package parrot_tools.interfaces (2 modules, 2 sub-packages).

## [parrot_tools.interfaces.gigsmart](overviews/pkg:parrot_tools.interfaces.gigsmart.md)

Package parrot_tools.interfaces.gigsmart (6 modules, 2 sub-packages).

## [parrot_tools.interfaces.gigsmart.models](overviews/pkg:parrot_tools.interfaces.gigsmart.models.md)

Package parrot_tools.interfaces.gigsmart.models (6 modules, 0 sub-packages).

## [parrot_tools.interfaces.gigsmart.queries](overviews/pkg:parrot_tools.interfaces.gigsmart.queries.md)

Package parrot_tools.interfaces.gigsmart.queries (7 modules, 0 sub-packages).

## [parrot_tools.interfaces.workday](overviews/pkg:parrot_tools.interfaces.workday.md)

Package parrot_tools.interfaces.workday (6 modules, 4 sub-packages).

## [parrot_tools.interfaces.workday.handlers](overviews/pkg:parrot_tools.interfaces.workday.handlers.md)

Package parrot_tools.interfaces.workday.handlers (27 modules, 0 sub-packages).

## [parrot_tools.interfaces.workday.models](overviews/pkg:parrot_tools.interfaces.workday.models.md)

Package parrot_tools.interfaces.workday.models (17 modules, 0 sub-packages).

## [parrot_tools.interfaces.workday.parsers](overviews/pkg:parrot_tools.interfaces.workday.parsers.md)

Package parrot_tools.interfaces.workday.parsers (15 modules, 0 sub-packages).

## [parrot_tools.interfaces.workday.utils](overviews/pkg:parrot_tools.interfaces.workday.utils.md)

Package parrot_tools.interfaces.workday.utils (1 modules, 0 sub-packages).

## [parrot_tools.kubernetes](overviews/pkg:parrot_tools.kubernetes.md)

Package parrot_tools.kubernetes (3 modules, 0 sub-packages).

## [parrot_tools.leadiq](overviews/pkg:parrot_tools.leadiq.md)

Package parrot_tools.leadiq (1 modules, 0 sub-packages).

## [parrot_tools.massive](overviews/pkg:parrot_tools.massive.md)

Package parrot_tools.massive (4 modules, 0 sub-packages).

## [parrot_tools.messaging](overviews/pkg:parrot_tools.messaging.md)

Package parrot_tools.messaging (1 modules, 0 sub-packages).

## [parrot_tools.navigator](overviews/pkg:parrot_tools.navigator.md)

Package parrot_tools.navigator (3 modules, 0 sub-packages).

## [parrot_tools.o365](overviews/pkg:parrot_tools.o365.md)

Package parrot_tools.o365 (7 modules, 0 sub-packages).

## [parrot_tools.odoo](overviews/pkg:parrot_tools.odoo.md)

Package parrot_tools.odoo (5 modules, 2 sub-packages).

## [parrot_tools.odoo.models](overviews/pkg:parrot_tools.odoo.models.md)

Package parrot_tools.odoo.models (3 modules, 0 sub-packages).

## [parrot_tools.odoo.transport](overviews/pkg:parrot_tools.odoo.transport.md)

Package parrot_tools.odoo.transport (5 modules, 0 sub-packages).

## [parrot_tools.pulumi](overviews/pkg:parrot_tools.pulumi.md)

Package parrot_tools.pulumi (3 modules, 0 sub-packages).

## [parrot_tools.quant](overviews/pkg:parrot_tools.quant.md)

Package parrot_tools.quant (7 modules, 0 sub-packages).

## [parrot_tools.retail](overviews/pkg:parrot_tools.retail.md)

Package parrot_tools.retail (1 modules, 0 sub-packages).

## [parrot_tools.rss](overviews/pkg:parrot_tools.rss.md)

Package parrot_tools.rss (4 modules, 0 sub-packages).

## [parrot_tools.s3](overviews/pkg:parrot_tools.s3.md)

Package parrot_tools.s3 (2 modules, 0 sub-packages).

## [parrot_tools.scraping](overviews/pkg:parrot_tools.scraping.md)

Package parrot_tools.scraping (32 modules, 2 sub-packages).

## [parrot_tools.scraping.drivers](overviews/pkg:parrot_tools.scraping.drivers.md)

Package parrot_tools.scraping.drivers (5 modules, 0 sub-packages).

## [parrot_tools.scraping.extraction_plans](overviews/pkg:parrot_tools.scraping.extraction_plans.md)

Package parrot_tools.scraping.extraction_plans (1 modules, 0 sub-packages).

## [parrot_tools.security](overviews/pkg:parrot_tools.security.md)

Package parrot_tools.security (18 modules, 6 sub-packages).

## [parrot_tools.security.checkov](overviews/pkg:parrot_tools.security.checkov.md)

Package parrot_tools.security.checkov (3 modules, 0 sub-packages).

## [parrot_tools.security.parsers](overviews/pkg:parrot_tools.security.parsers.md)

Package parrot_tools.security.parsers (6 modules, 0 sub-packages).

## [parrot_tools.security.prowler](overviews/pkg:parrot_tools.security.prowler.md)

Package parrot_tools.security.prowler (3 modules, 0 sub-packages).

## [parrot_tools.security.reports](overviews/pkg:parrot_tools.security.reports.md)

Package parrot_tools.security.reports (2 modules, 0 sub-packages).

## [parrot_tools.security.scoutsuite](overviews/pkg:parrot_tools.security.scoutsuite.md)

Package parrot_tools.security.scoutsuite (3 modules, 0 sub-packages).

## [parrot_tools.security.trivy](overviews/pkg:parrot_tools.security.trivy.md)

Package parrot_tools.security.trivy (3 modules, 0 sub-packages).

## [parrot_tools.shell_tool](overviews/pkg:parrot_tools.shell_tool.md)

Package parrot_tools.shell_tool (5 modules, 0 sub-packages).

## [parrot_tools.sitesearch](overviews/pkg:parrot_tools.sitesearch.md)

Package parrot_tools.sitesearch (3 modules, 0 sub-packages).

## [parrot_tools.system_health](overviews/pkg:parrot_tools.system_health.md)

Package parrot_tools.system_health (1 modules, 0 sub-packages).

## [parrot_tools.troc](overviews/pkg:parrot_tools.troc.md)

Package parrot_tools.troc (1 modules, 0 sub-packages).

## [parrot_tools.workday](overviews/pkg:parrot_tools.workday.md)

Package parrot_tools.workday (2 modules, 0 sub-packages).

## [parrot_tools.zoom](overviews/pkg:parrot_tools.zoom.md)

Package parrot_tools.zoom (1 modules, 0 sub-packages).
