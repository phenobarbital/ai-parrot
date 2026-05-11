"""Tests for OntologyRAGMixin pipeline orchestrator.

Updated for FEAT-158: ontology_process now returns ContextEnvelope.
Existing assertions migrated from result.X → result.context.X.
New tests added for entity resolution, authorization, tool dispatch states.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.entity_resolver import (
    EntityAmbiguityError,
    EntityNotFoundError,
)
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.schema import (
    AuthorizationRule,
    AuthorizationSpec,
    ContextEnvelope,
    EntityDef,
    EnrichedContext,
    EntityExtractionRule,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TenantContext,
    ToolCallSpec,
    TraversalPattern,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.tool_dispatcher import RenderError


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ontology() -> MergedOntology:
    return MergedOntology(
        name="test",
        version="1.0",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[{"employee_id": PropertyDef(type="string")}],
            ),
        },
        relations={},
        traversal_patterns={
            "find_dept": TraversalPattern(
                description="Find department",
                trigger_intents=["my department"],
                query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to RETURN v",
                post_action="none",
            ),
            "find_portal": TraversalPattern(
                description="Find portal",
                trigger_intents=["my portal"],
                query_template="FOR v IN 1..2 OUTBOUND @user_id assigned_to RETURN v",
                post_action="vector_search",
                post_query="portal_url",
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def tenant_ctx(ontology) -> TenantContext:
    return TenantContext(
        tenant_id="test",
        arango_db="test_ontology",
        pgvector_schema="test",
        ontology=ontology,
    )


@pytest.fixture
def mock_tenant_mgr(tenant_ctx):
    mgr = MagicMock(spec=TenantOntologyManager)
    mgr.resolve.return_value = tenant_ctx
    return mgr


@pytest.fixture
def mock_graph_store():
    store = AsyncMock(spec=OntologyGraphStore)
    store.execute_traversal.return_value = [
        {"name": "Engineering", "dept_id": "ENG"},
    ]
    return store


@pytest.fixture
def mock_cache():
    cache = AsyncMock(spec=OntologyCache)
    cache.get.return_value = None  # Default: cache miss
    cache.build_key = OntologyCache.build_key  # Use real static method
    return cache


@pytest.fixture
def user_context():
    return {"user_id": "employees/emp_001"}


def _make_mixin(tenant_mgr, graph_store, cache, vector_store=None, llm=None, tool_manager=None):
    """Create an OntologyRAGMixin instance (standalone, not mixed in)."""
    mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
    mixin._ont_tenant_manager = tenant_mgr
    mixin._ont_graph_store = graph_store
    mixin._ont_vector_store = vector_store
    mixin._ont_cache = cache
    mixin._ont_llm_client = llm
    mixin._ont_tool_manager = tool_manager
    return mixin


# ---------------------------------------------------------------------------
# Existing tests — migrated to ContextEnvelope return type
# ---------------------------------------------------------------------------


class TestGraphQueryFlow:

    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "What is my department?", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.state == "ok"
            assert result.context is not None
            assert result.context.source == "ontology"
            assert result.context.graph_context is not None
            assert len(result.context.graph_context) == 1
            assert result.context.graph_context[0]["name"] == "Engineering"
            assert result.context.intent.action == "graph_query"
            assert result.context.intent.source == "fast_path"

    @pytest.mark.asyncio
    async def test_caches_result(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            await mixin.ontology_process(
                "my department", user_context, "test",
            )
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_cached(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        cached_ctx = EnrichedContext(source="ontology", graph_context=[{"cached": True}])
        mock_cache.get.return_value = cached_ctx

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.graph_context == [{"cached": True}]
            mock_graph_store.execute_traversal.assert_not_called()


class TestVectorOnlyFlow:

    @pytest.mark.asyncio
    async def test_no_keyword_match(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "How do I reset my password?", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.source == "vector_only"
            mock_graph_store.execute_traversal.assert_not_called()


class TestDisabledFlow:

    @pytest.mark.asyncio
    async def test_disabled_returns_early(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=False):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.state == "disabled"
            assert result.context is None
            mock_tenant_mgr.resolve.assert_not_called()


class TestGracefulDegradation:

    @pytest.mark.asyncio
    async def test_graph_store_failure(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_graph_store.execute_traversal.side_effect = Exception("ArangoDB down")
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.source == "vector_only"

    @pytest.mark.asyncio
    async def test_no_graph_store(self, mock_tenant_mgr, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, None, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.source == "vector_only"

    @pytest.mark.asyncio
    async def test_tenant_not_found(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_tenant_mgr.resolve.side_effect = FileNotFoundError("no YAML")
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.source == "vector_only"


class TestPostActions:

    @pytest.mark.asyncio
    async def test_vector_search_post_action(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_graph_store.execute_traversal.return_value = [
            {"portal_url": "https://epson.navigator.com"},
        ]
        mock_vector_store = AsyncMock()
        mock_vector_store.search.return_value = [{"doc": "portal docs"}]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "what is my portal?", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.source == "ontology"
            assert result.context.vector_context is not None
            mock_vector_store.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_hint_post_action(self, mock_tenant_mgr, mock_cache, user_context, ontology):
        # Add a tool_call pattern WITHOUT an explicit ToolCallSpec (backwards compat)
        ontology.traversal_patterns["find_tools"] = TraversalPattern(
            description="Find tools",
            trigger_intents=["my tools"],
            query_template="FOR v IN 1..1 OUTBOUND @user_id has_tools RETURN v",
            post_action="tool_call",
        )
        tenant_ctx = TenantContext(
            tenant_id="test", arango_db="test_ontology",
            pgvector_schema="test", ontology=ontology,
        )
        mock_tenant_mgr.resolve.return_value = tenant_ctx

        mock_graph_store = AsyncMock()
        mock_graph_store.execute_traversal.return_value = [
            {"name": "Workday"},
        ]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what are my tools?", user_context, "test",
            )
            assert isinstance(result, ContextEnvelope)
            assert result.context.tool_hint is not None
            assert "Workday" in result.context.tool_hint


class TestHelpers:

    def test_extract_post_query(self):
        results = [{"portal_url": "https://example.com", "name": "Portal"}]
        val = OntologyRAGMixin._extract_post_query(results, "portal_url")
        assert val == "https://example.com"

    def test_extract_post_query_missing(self):
        val = OntologyRAGMixin._extract_post_query([{"name": "x"}], "missing_field")
        assert val is None

    def test_extract_post_query_empty(self):
        val = OntologyRAGMixin._extract_post_query([], "any")
        assert val is None

    def test_build_tool_hint(self):
        hint = OntologyRAGMixin._build_tool_hint([
            {"name": "Workday"}, {"name": "Jira"},
        ])
        assert "Workday" in hint
        assert "Jira" in hint


# ---------------------------------------------------------------------------
# New tests for TASK-1076 acceptance criteria
# ---------------------------------------------------------------------------


def _make_ontology_with_entity_extraction(
    trigger_phrase: str = "el equipo de",
    post_action: str = "none",
    tool_call_spec: ToolCallSpec | None = None,
    authorization_spec: AuthorizationSpec | None = None,
) -> MergedOntology:
    """Build a MergedOntology with entity_extraction on the 'find_team' pattern."""
    return MergedOntology(
        name="test",
        version="1.0",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[{"employee_id": PropertyDef(type="string")}],
            ),
        },
        relations={},
        traversal_patterns={
            "find_team": TraversalPattern(
                description="Find team of an employee",
                trigger_intents=[trigger_phrase],
                query_template="FOR v IN 1..1 OUTBOUND @target_employee_id belongs_to RETURN v",
                post_action=post_action,
                entity_extraction={
                    "target_employee": EntityExtractionRule(
                        type="Employee",
                        resolver="fuzzy_name_match",
                    ),
                },
                authorization=authorization_spec,
                tool_call=tool_call_spec,
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


class TestOntologyProcessStates:
    """New state-machine tests for ContextEnvelope returns."""

    @pytest.mark.asyncio
    async def test_get_permission_context_default_empty(
        self, mock_tenant_mgr, mock_graph_store, mock_cache
    ) -> None:
        """_get_permission_context returns {} on the base mixin."""
        mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
        assert mixin._get_permission_context() == {}

    @pytest.mark.asyncio
    async def test_ambiguity_returns_ambiguous_envelope(
        self, mock_cache
    ) -> None:
        """EntityAmbiguityError from resolver → state="ambiguous"."""
        ontology = _make_ontology_with_entity_extraction()
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                side_effect=EntityAmbiguityError(
                    rule_name="target_employee",
                    mention="Jesús",
                    candidates=[
                        {"_id": "Employee/1", "name": "Jesús Lara"},
                        {"_id": "Employee/2", "name": "Jesús Pérez"},
                    ],
                )
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache)
            result = await mixin.ontology_process(
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ambiguous"
        assert result.clarification is not None
        assert result.clarification["rule"] == "target_employee"
        assert result.clarification["mention"] == "Jesús"
        assert len(result.clarification["candidates"]) == 2

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_envelope(
        self, mock_cache
    ) -> None:
        """EntityNotFoundError from resolver → state="entity_not_found"."""
        ontology = _make_ontology_with_entity_extraction()
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                side_effect=EntityNotFoundError(
                    rule_name="target_employee",
                    mention="UnknownPerson",
                )
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache)
            result = await mixin.ontology_process(
                "el equipo de UnknownPerson",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "entity_not_found"

    @pytest.mark.asyncio
    async def test_denied_returns_denied_envelope(
        self, mock_cache
    ) -> None:
        """AuthorizationChecker denying → state="denied"."""
        auth_spec = AuthorizationSpec(rules=[AuthorizationRule(rule="has_role", role="hr_manager")])
        ontology = _make_ontology_with_entity_extraction(authorization_spec=auth_spec)
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver, \
             patch(
                "parrot.knowledge.ontology.mixin.AuthorizationChecker",
                autospec=True,
             ) as MockChecker:
            instance_resolver = MockResolver.return_value
            instance_resolver.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/1"}
            )
            instance_checker = MockChecker.return_value
            instance_checker.check = AsyncMock(
                return_value=(False, "no authorization rule matched")
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache)
            result = await mixin.ontology_process(
                "el equipo de Jesús",
                user_context={"user_id": "u1", "roles": []},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "denied"
        assert result.denial_reason is not None

    @pytest.mark.asyncio
    async def test_auth_required_returns_auth_required_envelope(
        self, mock_cache
    ) -> None:
        """AuthorizationRequired from dispatcher → state="auth_required"."""
        tool_spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            parameters={"jql": "project = TROC"},
            result_binding="issues",
        )
        ontology = _make_ontology_with_entity_extraction(
            post_action="tool_call", tool_call_spec=tool_spec,
        )
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)
        mock_gs.execute_traversal.return_value = [{"_id": "Employee/1"}]

        mock_tool_mgr = MagicMock()

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver, \
             patch(
                "parrot.knowledge.ontology.mixin.ToolCallDispatcher",
                autospec=True,
             ) as MockDispatcher:
            instance_resolver = MockResolver.return_value
            instance_resolver.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/1"}
            )
            instance_dispatcher = MockDispatcher.return_value
            instance_dispatcher.dispatch = AsyncMock(
                side_effect=AuthorizationRequired(
                    tool_name="jira_search_issues",
                    message="please reauth",
                    auth_url="https://auth/url",
                    provider="jira",
                    scopes=["read:jira-work"],
                )
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache, tool_manager=mock_tool_mgr)
            result = await mixin.ontology_process(
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "auth_required"
        assert result.auth_prompt is not None
        assert result.auth_prompt["auth_url"] == "https://auth/url"
        assert result.auth_prompt["provider"] == "jira"

    @pytest.mark.asyncio
    async def test_render_error_returns_render_error_envelope(
        self, mock_cache
    ) -> None:
        """RenderError from dispatcher → state="render_error"."""
        tool_spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            parameters={"jql": "project = {{ ctx.unknown }}"},
            result_binding="issues",
        )
        ontology = _make_ontology_with_entity_extraction(
            post_action="tool_call", tool_call_spec=tool_spec,
        )
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)
        mock_gs.execute_traversal.return_value = [{"_id": "Employee/1"}]

        mock_tool_mgr = MagicMock()

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver, \
             patch(
                "parrot.knowledge.ontology.mixin.ToolCallDispatcher",
                autospec=True,
             ) as MockDispatcher:
            instance_resolver = MockResolver.return_value
            instance_resolver.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/1"}
            )
            instance_dispatcher = MockDispatcher.return_value
            instance_dispatcher.dispatch = AsyncMock(
                side_effect=RenderError(field="jql", message="undefined 'ctx.unknown'")
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache, tool_manager=mock_tool_mgr)
            result = await mixin.ontology_process(
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "render_error"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_tool_call_without_spec_uses_build_tool_hint(
        self, mock_tenant_mgr, mock_cache, ontology
    ) -> None:
        """tool_call post-action with no ToolCallSpec falls back to _build_tool_hint."""
        # Add pattern with tool_call post-action but no tool_call spec
        ontology.traversal_patterns["find_tools"] = TraversalPattern(
            description="Find tools",
            trigger_intents=["my tools"],
            query_template="FOR v IN 1..1 OUTBOUND @user_id has_tools RETURN v",
            post_action="tool_call",
            # tool_call=None (default) — backwards compat fallback
        )
        tenant_ctx = TenantContext(
            tenant_id="test", arango_db="test_ontology",
            pgvector_schema="test", ontology=ontology,
        )
        mock_tenant_mgr.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock()
        mock_gs.execute_traversal.return_value = [{"name": "Workday"}]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_gs, mock_cache)
            result = await mixin.ontology_process(
                "what are my tools?",
                user_context={"user_id": "u1"},
                tenant_id="test",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.tool_hint is not None
        assert "Workday" in result.context.tool_hint
        assert result.tool_result is None  # no ToolCallSpec → no tool_result

    @pytest.mark.asyncio
    async def test_cache_key_includes_resolved_entities(
        self, mock_cache
    ) -> None:
        """Two queries with different resolved entities get distinct cache keys."""
        ontology = _make_ontology_with_entity_extraction()
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)
        mock_gs.execute_traversal.return_value = [{"_id": "Member/1"}]

        seen_keys: list[str] = []

        def fake_build_key(
            tenant_id: str,
            user_id: str,
            pattern: str,
            resolved_entities: dict | None = None,
        ) -> str:
            key = f"{tenant_id}:{user_id}:{pattern}:{sorted((resolved_entities or {}).items())}"
            seen_keys.append(key)
            return key

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            # First call resolves Employee/1
            mock_cache.get.return_value = None
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/1"}
            )
            with patch.object(OntologyCache, 'build_key', staticmethod(fake_build_key)):
                mixin = _make_mixin(mock_tm, mock_gs, mock_cache)
                await mixin.ontology_process(
                    "el equipo de Jesús",
                    user_context={"user_id": "alice"},
                    tenant_id="t1",
                )

            # Second call resolves Employee/2
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/2"}
            )
            with patch.object(OntologyCache, 'build_key', staticmethod(fake_build_key)):
                await mixin.ontology_process(
                    "el equipo de Pérez",
                    user_context={"user_id": "alice"},
                    tenant_id="t1",
                )

        assert len(seen_keys) == 2
        assert seen_keys[0] != seen_keys[1], (
            "Cache keys must differ when resolved_entities differ"
        )

    @pytest.mark.asyncio
    async def test_happy_path_with_tool_dispatch(
        self, mock_cache
    ) -> None:
        """Full pipeline with entity resolution + tool dispatch returns ok+tool_result."""
        tool_spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            parameters={"jql": "project = TROC"},
            result_binding="issues",
        )
        ontology = _make_ontology_with_entity_extraction(
            post_action="tool_call", tool_call_spec=tool_spec,
        )
        tenant_ctx = TenantContext(
            tenant_id="t1", arango_db="t1_ontology",
            pgvector_schema="t1", ontology=ontology,
        )
        mock_tm = MagicMock(spec=TenantOntologyManager)
        mock_tm.resolve.return_value = tenant_ctx

        mock_gs = AsyncMock(spec=OntologyGraphStore)
        mock_gs.execute_traversal.return_value = [{"jira_account_id": "acct:abc"}]

        mock_tool_mgr = MagicMock()

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver, \
             patch(
                "parrot.knowledge.ontology.mixin.ToolCallDispatcher",
                autospec=True,
             ) as MockDispatcher:
            instance_resolver = MockResolver.return_value
            instance_resolver.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/1"}
            )
            instance_dispatcher = MockDispatcher.return_value
            instance_dispatcher.dispatch = AsyncMock(
                return_value={"issues": [{"key": "TROC-1"}]}
            )
            mixin = _make_mixin(mock_tm, mock_gs, mock_cache, tool_manager=mock_tool_mgr)
            result = await mixin.ontology_process(
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "ontology"
        assert result.tool_result == {"issues": [{"key": "TROC-1"}]}
