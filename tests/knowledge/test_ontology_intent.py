"""Tests for ontology dual-path intent resolver."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.exceptions import AQLValidationError
from parrot.knowledge.ontology.intent import OntologyIntentResolver
from parrot.knowledge.ontology.schema import (
    EntityDef,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TraversalPattern,
)


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
            "Department": EntityDef(
                collection="departments",
                key_field="dept_id",
                properties=[{"dept_id": PropertyDef(type="string")}],
            ),
            "Project": EntityDef(
                collection="projects",
                key_field="project_id",
                properties=[{"project_id": PropertyDef(type="string")}],
            ),
        },
        relations={
            "belongs_to": RelationDef(
                from_entity="Employee",
                to_entity="Department",
                edge_collection="belongs_to_dept",
            ),
            "assigned_to": RelationDef(
                from_entity="Employee",
                to_entity="Project",
                edge_collection="assigned_to",
            ),
        },
        traversal_patterns={
            "find_dept": TraversalPattern(
                description="Find employee department",
                trigger_intents=["my department", "which department"],
                query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to_dept RETURN v",
                post_action="none",
            ),
            "find_portal": TraversalPattern(
                description="Find employee portal",
                trigger_intents=["my portal", "what is my portal"],
                query_template="FOR v IN 1..2 OUTBOUND @user_id assigned_to RETURN v",
                post_action="vector_search",
                post_query="portal_url",
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def user_context() -> dict:
    return {"user_id": "employees/emp_001", "tenant": "test"}


class TestFastPath:

    @pytest.mark.asyncio
    async def test_matches_keyword(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("What is my department?", user_context)
        assert result.action == "graph_query"
        assert result.pattern == "find_dept"
        assert result.source == "fast_path"
        assert result.aql is not None

    @pytest.mark.asyncio
    async def test_matches_portal_keyword(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("What is my portal?", user_context)
        assert result.action == "graph_query"
        assert result.pattern == "find_portal"
        assert result.post_action == "vector_search"
        assert result.post_query == "portal_url"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("MY DEPARTMENT please", user_context)
        assert result.action == "graph_query"
        assert result.pattern == "find_dept"

    @pytest.mark.asyncio
    async def test_no_match_without_llm(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("How do I reset my password?", user_context)
        assert result.action == "vector_only"

    @pytest.mark.asyncio
    async def test_populates_params(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("my department", user_context)
        assert result.params.get("user_id") == "employees/emp_001"

    @pytest.mark.asyncio
    async def test_populates_collection_binds(self, ontology, user_context):
        resolver = OntologyIntentResolver(ontology)
        result = await resolver.resolve("my department", user_context)
        assert "@employees" in result.collection_binds
        assert "@departments" in result.collection_binds
        assert "@belongs_to_dept" in result.collection_binds


class TestLLMPath:

    @pytest.mark.asyncio
    async def test_llm_selects_known_pattern(self, ontology, user_context):
        mock_llm = AsyncMock()
        mock_llm.completion.return_value = MagicMock(
            output=json.dumps({
                "action": "graph_query",
                "pattern": "find_dept",
            })
        )
        resolver = OntologyIntentResolver(ontology, llm_client=mock_llm)
        # Query that doesn't match fast path keywords
        result = await resolver.resolve(
            "Tell me about the org structure I belong to", user_context
        )
        assert result.action == "graph_query"
        assert result.pattern == "find_dept"
        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_llm_generates_dynamic_aql(self, ontology, user_context):
        mock_llm = AsyncMock()
        mock_llm.completion.return_value = MagicMock(
            output=json.dumps({
                "action": "graph_query",
                "pattern": "dynamic",
                "aql": "FOR v IN 1..2 OUTBOUND @user_id assigned_to RETURN v.name",
                "suggested_post_action": "none",
            })
        )
        resolver = OntologyIntentResolver(ontology, llm_client=mock_llm)
        result = await resolver.resolve(
            "Show me all projects connected to my team", user_context
        )
        assert result.action == "graph_query"
        assert result.pattern == "dynamic"
        assert result.source == "llm_dynamic"
        assert "OUTBOUND" in result.aql

    @pytest.mark.asyncio
    async def test_llm_vector_only(self, ontology, user_context):
        mock_llm = AsyncMock()
        mock_llm.completion.return_value = MagicMock(
            output=json.dumps({"action": "vector_only"})
        )
        resolver = OntologyIntentResolver(ontology, llm_client=mock_llm)
        result = await resolver.resolve(
            "How do I configure my email client?", user_context
        )
        assert result.action == "vector_only"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self, ontology, user_context):
        mock_llm = AsyncMock()
        mock_llm.completion.side_effect = Exception("LLM unavailable")
        resolver = OntologyIntentResolver(ontology, llm_client=mock_llm)
        result = await resolver.resolve(
            "Something complex about the org", user_context
        )
        assert result.action == "vector_only"

    @pytest.mark.asyncio
    async def test_llm_dynamic_aql_validated(self, ontology, user_context):
        """Dynamic AQL with mutations should be rejected."""
        mock_llm = AsyncMock()
        mock_llm.completion.return_value = MagicMock(
            output=json.dumps({
                "action": "graph_query",
                "pattern": "dynamic",
                "aql": "REMOVE { _key: '1' } IN employees",
            })
        )
        resolver = OntologyIntentResolver(ontology, llm_client=mock_llm)
        # Should fall through to vector_only because validation rejects the AQL
        result = await resolver.resolve("delete my record", user_context)
        assert result.action == "vector_only"


class TestCollectionBinds:

    def test_build_collection_binds(self, ontology):
        resolver = OntologyIntentResolver(ontology)
        binds = resolver._build_collection_binds()
        assert "@employees" in binds
        assert "@departments" in binds
        assert "@projects" in binds
        assert "@belongs_to_dept" in binds
        assert "@assigned_to" in binds

    def test_schema_prompt_built(self, ontology):
        resolver = OntologyIntentResolver(ontology)
        assert "Employee" in resolver._schema_prompt
        assert "belongs_to" in resolver._schema_prompt
        assert "find_dept" in resolver._schema_prompt
