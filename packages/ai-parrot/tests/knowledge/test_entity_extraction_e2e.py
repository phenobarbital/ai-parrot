"""End-to-end tests for FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch.

Exercises the full pipeline: entity extraction → authorization → graph traversal →
tool dispatch → ContextEnvelope. All external services (ArangoDB, Jira) are mocked.

Fixture YAML: packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml

Spy strategy: a lightweight ToolCallSpy registered in a fake ToolManager. The spy
records the last ``_permission_context`` kwarg so tests can verify per-user OAuth
routing without importing JiraToolkit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import PermissionContext, UserSession
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.schema import (
    AuthorizationRule,
    AuthorizationSpec,
    ContextEnvelope,
    EntityDef,
    EntityExtractionRule,
    MergedOntology,
    PropertyDef,
    TenantContext,
    ToolCallSpec,
    TraversalPattern,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager


# ---------------------------------------------------------------------------
# Fixture YAML path
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_YAML = _FIXTURES_DIR / "team_work_in_progress.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ToolCallSpy:
    """Lightweight spy that acts as a registered tool.

    Records the last ``_permission_context`` passed via ``execute()`` so
    tests can assert that per-user OAuth routing was honoured.
    """

    def __init__(self, return_value: Any = None) -> None:
        self.last_permission_context: PermissionContext | None = None
        self._return_value = return_value or {"issues": [{"key": "TROC-1"}]}
        self.call_count = 0

    async def execute(self, **kwargs: Any) -> Any:
        self.last_permission_context = kwargs.get("_permission_context")
        self.call_count += 1
        return self._return_value


def _make_tool_manager(spy: _ToolCallSpy) -> MagicMock:
    """Build a fake ToolManager that returns the spy for any tool lookup."""
    tm = MagicMock()
    tm.get_tool = MagicMock(return_value=spy)
    return tm


def _load_pattern_from_fixture() -> TraversalPattern:
    """Load ``team_work_in_progress`` pattern from the YAML fixture."""
    raw = yaml.safe_load(_FIXTURE_YAML.read_text())
    spec = raw["team_work_in_progress"]

    # Parse entity_extraction
    ee = {
        k: EntityExtractionRule(**v)
        for k, v in spec.get("entity_extraction", {}).items()
    }

    # Parse authorization
    auth_raw = spec.get("authorization")
    auth_spec = None
    if auth_raw:
        rules = [AuthorizationRule(**r) for r in auth_raw.get("rules", [])]
        auth_spec = AuthorizationSpec(rules=rules)

    # Parse tool_call — note: fields list is inside parameters
    tc_raw = spec.get("tool_call")
    tool_call_spec = None
    if tc_raw:
        params = dict(tc_raw.get("parameters", {}))
        # Normalise multi-line YAML scalars (jql has a trailing newline)
        if "jql" in params:
            params["jql"] = params["jql"].strip()
        tool_call_spec = ToolCallSpec(
            toolkit=tc_raw["toolkit"],
            method=tc_raw["method"],
            credential_mode=tc_raw.get("credential_mode", "requesting_user"),
            parameters=params,
            result_binding=tc_raw.get("result_binding", "issues"),
            empty_team_behavior=tc_raw.get("empty_team_behavior", "short_circuit"),
        )

    return TraversalPattern(
        description=spec["description"],
        trigger_intents=spec["trigger_intents"],
        query_template=spec.get("query_template", "FOR e IN Employee RETURN e"),
        post_action=spec.get("post_action", "none"),
        entity_extraction=ee,
        authorization=auth_spec,
        tool_call=tool_call_spec,
    )


def _make_ontology(pattern: TraversalPattern) -> MergedOntology:
    """Build a MergedOntology with the given TraversalPattern."""
    return MergedOntology(
        name="acme",
        version="1.0",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[
                    {"employee_id": PropertyDef(type="string")},
                    {"name": PropertyDef(type="string")},
                    {"jira_account_id": PropertyDef(type="string")},
                    {"department": PropertyDef(type="string")},
                ],
            ),
        },
        relations={},
        traversal_patterns={"team_work_in_progress": pattern},
        layers=["fixture"],
        merge_timestamp=datetime.now(timezone.utc),
    )


def _make_mixin(
    ontology: MergedOntology,
    graph_store: Any,
    cache: Any,
    tool_manager: Any,
    tenant_id: str = "acme",
) -> OntologyRAGMixin:
    """Create a mixin wired to the given services."""
    tenant_ctx = TenantContext(
        tenant_id=tenant_id,
        arango_db=f"{tenant_id}_ontology",
        pgvector_schema=tenant_id,
        ontology=ontology,
    )
    mock_tm = MagicMock(spec=TenantOntologyManager)
    mock_tm.resolve.return_value = tenant_ctx

    mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
    mixin._ont_tenant_manager = mock_tm
    mixin._ont_graph_store = graph_store
    mixin._ont_vector_store = None
    mixin._ont_cache = cache
    mixin._ont_llm_client = None
    mixin._ont_tool_manager = tool_manager
    return mixin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pattern() -> TraversalPattern:
    return _load_pattern_from_fixture()


@pytest.fixture
def spy() -> _ToolCallSpy:
    return _ToolCallSpy(return_value={"issues": [{"key": "TROC-1", "summary": "Fix bug"}]})


@pytest.fixture
def cache() -> AsyncMock:
    c = AsyncMock(spec=OntologyCache)
    c.get.return_value = None
    c.build_key = OntologyCache.build_key
    return c


@pytest.fixture
def graph_store_with_team() -> AsyncMock:
    """Graph store returning a seeded team (Jesús Lara's reports)."""
    store = AsyncMock(spec=OntologyGraphStore)
    store.execute_traversal.return_value = [
        {"employee_id": "E002", "name": "Bob Jones", "jira_account_id": "acct:bob"},
        {"employee_id": "E003", "name": "Carol Chen", "jira_account_id": "acct:carol"},
    ]
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2ETeamWorkInProgress:
    """End-to-end scenarios for the team_work_in_progress pattern."""

    @pytest.mark.asyncio
    async def test_fixture_yaml_loads(self, pattern: TraversalPattern) -> None:
        """Sanity: YAML fixture loads into a valid TraversalPattern."""
        assert pattern.tool_call is not None
        assert pattern.tool_call.toolkit == "JiraToolkit"
        assert pattern.tool_call.result_binding == "in_progress_issues"
        assert pattern.authorization is not None
        assert len(pattern.authorization.rules) == 3
        assert "target_employee" in pattern.entity_extraction

    @pytest.mark.asyncio
    async def test_happy_path_returns_ok_with_tool_result(
        self,
        pattern: TraversalPattern,
        spy: _ToolCallSpy,
        cache: AsyncMock,
        graph_store_with_team: AsyncMock,
    ) -> None:
        """Full pipeline: ok state with tool_result["in_progress_issues"] populated.

        Verifies:
        - ContextEnvelope.state == "ok"
        - tool_result has the bound key from result_binding
        - _permission_context.user_id is the requesting user (not a service account)
        - _permission_context.channel is the requesting user's channel
        """
        ontology = _make_ontology(pattern)
        tm = _make_tool_manager(spy)
        mixin = _make_mixin(ontology, graph_store_with_team, cache, tm)

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                 "parrot.knowledge.ontology.mixin.EntityResolver",
                 autospec=True,
             ) as MockResolver:
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/E001"}
            )

            result = await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Jesús Lara?",
                user_context={
                    "user_id": "alice",
                    "channel": "telegram",
                    "roles": ["hr_manager"],
                },
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok", f"Expected ok, got {result.state!r}"
        assert result.tool_result is not None
        assert "in_progress_issues" in result.tool_result

        # Verify per-user OAuth path: the spy recorded the permission context
        assert spy.last_permission_context is not None
        assert spy.last_permission_context.user_id == "alice"
        assert spy.last_permission_context.channel == "telegram"

    @pytest.mark.asyncio
    async def test_ambiguous_name_returns_clarification(
        self,
        pattern: TraversalPattern,
        spy: _ToolCallSpy,
        cache: AsyncMock,
    ) -> None:
        """Two Jesús employees → ambiguity_strategy=ask_user → state="ambiguous"."""
        ontology = _make_ontology(pattern)
        gs = AsyncMock(spec=OntologyGraphStore)
        mixin = _make_mixin(ontology, gs, cache, _make_tool_manager(spy))

        ambiguous_candidates = [
            {"_id": "Employee/1", "name": "Jesús Lara"},
            {"_id": "Employee/2", "name": "Jesús Pérez"},
        ]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                 "parrot.knowledge.ontology.mixin.EntityResolver",
                 autospec=True,
             ) as MockResolver:
            from parrot.knowledge.ontology.entity_resolver import EntityAmbiguityError
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                side_effect=EntityAmbiguityError(
                    rule_name="target_employee",
                    mention="Jesús",
                    candidates=ambiguous_candidates,
                )
            )

            result = await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Jesús?",
                user_context={"user_id": "alice", "roles": []},
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ambiguous"
        assert result.clarification is not None
        assert result.clarification["rule"] == "target_employee"
        assert len(result.clarification["candidates"]) == 2
        # Tool must NOT have been called during ambiguity
        assert spy.call_count == 0

    @pytest.mark.asyncio
    async def test_denied_cross_department(
        self,
        pattern: TraversalPattern,
        spy: _ToolCallSpy,
        cache: AsyncMock,
    ) -> None:
        """Caller without hr_manager role querying another dept → state="denied"."""
        # Make authorization strict: no hr_manager → denied
        auth_spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="has_role", role="hr_manager")],
            default_deny=True,
        )
        restricted_pattern = TraversalPattern(
            description=pattern.description,
            trigger_intents=pattern.trigger_intents,
            query_template=pattern.query_template,
            post_action=pattern.post_action,
            entity_extraction=pattern.entity_extraction,
            authorization=auth_spec,
            tool_call=pattern.tool_call,
        )
        ontology = _make_ontology(restricted_pattern)
        gs = AsyncMock(spec=OntologyGraphStore)
        mixin = _make_mixin(ontology, gs, cache, _make_tool_manager(spy))

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
                return_value={"target_employee": "Employee/E001"}
            )
            instance_checker = MockChecker.return_value
            instance_checker.check = AsyncMock(
                return_value=(False, "no authorization rule matched")
            )

            result = await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Jesús?",
                user_context={"user_id": "bob", "roles": ["employee"]},
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "denied"
        assert result.denial_reason is not None
        # Tool must NOT have been called
        assert spy.call_count == 0

    @pytest.mark.asyncio
    async def test_auth_required_deep_link(
        self,
        pattern: TraversalPattern,
        cache: AsyncMock,
        graph_store_with_team: AsyncMock,
    ) -> None:
        """Toolkit raises AuthorizationRequired → state="auth_required" with auth_url."""
        # Build a spy that raises AuthorizationRequired
        auth_required_spy = _ToolCallSpy()
        auth_required_spy.execute = AsyncMock(
            side_effect=AuthorizationRequired(
                tool_name="jira_search_issues",
                message="please reauth",
                auth_url="https://auth.atlassian.com/authorize?client_id=X",
                provider="jira",
                scopes=["read:jira-work"],
            )
        )

        ontology = _make_ontology(pattern)
        mixin = _make_mixin(
            ontology, graph_store_with_team, cache,
            _make_tool_manager(auth_required_spy),
        )

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                 "parrot.knowledge.ontology.mixin.EntityResolver",
                 autospec=True,
             ) as MockResolver:
            instance = MockResolver.return_value
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/E001"}
            )

            result = await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Jesús?",
                user_context={"user_id": "alice", "roles": ["hr_manager"]},
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "auth_required"
        assert result.auth_prompt is not None
        assert result.auth_prompt["auth_url"] == "https://auth.atlassian.com/authorize?client_id=X"
        assert result.auth_prompt["provider"] == "jira"

    @pytest.mark.asyncio
    async def test_cache_isolates_targets(
        self,
        pattern: TraversalPattern,
        spy: _ToolCallSpy,
        cache: AsyncMock,
        graph_store_with_team: AsyncMock,
    ) -> None:
        """Two queries with different target employees get distinct cache keys.

        Verifies that graph_store.execute_traversal is called a second time —
        the second call cannot reuse the first call's cached result because
        resolved_entities differ.
        """
        ontology = _make_ontology(pattern)
        mixin = _make_mixin(
            ontology, graph_store_with_team, cache,
            _make_tool_manager(spy),
        )

        seen_keys: list[str] = []

        def fake_build_key(
            tenant_id: str,
            user_id: str,
            pattern_name: str,
            resolved_entities: dict | None = None,
        ) -> str:
            key = f"{tenant_id}:{user_id}:{pattern_name}:{sorted((resolved_entities or {}).items())}"
            seen_keys.append(key)
            return key

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True), \
             patch(
                 "parrot.knowledge.ontology.mixin.EntityResolver",
                 autospec=True,
             ) as MockResolver, \
             patch.object(OntologyCache, 'build_key', staticmethod(fake_build_key)):

            instance = MockResolver.return_value

            # First query: resolves Employee/E001
            cache.get.return_value = None
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/E001"}
            )
            await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Jesús Lara?",
                user_context={"user_id": "alice", "roles": ["hr_manager"]},
                tenant_id="acme",
            )
            traversal_count_after_first = graph_store_with_team.execute_traversal.call_count

            # Second query: resolves a different employee
            cache.get.return_value = None  # Cache miss also for second query
            instance.extract_and_resolve = AsyncMock(
                return_value={"target_employee": "Employee/E004"}
            )
            await mixin.ontology_process(
                query="¿en qué está trabajando el equipo de Pérez?",
                user_context={"user_id": "alice", "roles": ["hr_manager"]},
                tenant_id="acme",
            )
            traversal_count_after_second = graph_store_with_team.execute_traversal.call_count

        # Each query should produce a distinct cache key
        assert len(seen_keys) == 2
        assert seen_keys[0] != seen_keys[1], (
            f"Cache keys must differ when resolved_entities differ.\n"
            f"Key 1: {seen_keys[0]}\nKey 2: {seen_keys[1]}"
        )
        # Second query hit the graph store again (not served from cache)
        assert traversal_count_after_second > traversal_count_after_first, (
            "Second query must go through graph traversal again "
            "(different resolved_entities → different cache key → cache miss)"
        )
