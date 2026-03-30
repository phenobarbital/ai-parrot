"""Unit tests for OntologyIntentResolver deprecation (TASK-494).

Tests that:
- OntologyIntentResolver emits DeprecationWarning when instantiated.
- __deprecated__ class attribute is set to True.
- All existing behavior remains unchanged.
- IntentDecision model is still importable.
"""
from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.ontology.intent import IntentDecision, OntologyIntentResolver


class TestOntologyIntentResolverDeprecation:
    """Tests for the soft-deprecation of OntologyIntentResolver."""

    def _make_mock_ontology(self):
        """Build a minimal mock ontology for testing."""
        ontology = MagicMock()
        ontology.build_schema_prompt.return_value = "Schema: entities=[User], relations=[]"
        ontology.traversal_patterns = {}
        ontology.entities = {}
        ontology.relations = {}
        return ontology

    def test_deprecation_warning_emitted(self) -> None:
        """OntologyIntentResolver emits DeprecationWarning on instantiation."""
        ontology = self._make_mock_ontology()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            OntologyIntentResolver(ontology=ontology)

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1, "Expected at least one DeprecationWarning"

    def test_deprecation_warning_mentions_intent_router_mixin(self) -> None:
        """DeprecationWarning message references IntentRouterMixin."""
        ontology = self._make_mock_ontology()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            OntologyIntentResolver(ontology=ontology)

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        message = str(dep_warnings[0].message)
        assert "IntentRouterMixin" in message or "intent_router" in message.lower()

    def test_deprecated_class_attribute_is_true(self) -> None:
        """OntologyIntentResolver.__deprecated__ is True."""
        assert OntologyIntentResolver.__deprecated__ is True

    def test_resolve_still_works_fast_path(self) -> None:
        """After deprecation, fast path resolve() still works correctly."""
        ontology = self._make_mock_ontology()

        # Add a simple trigger pattern
        pattern = MagicMock()
        pattern.trigger_intents = ["reports to"]
        pattern.query_template = "FOR v IN 1..1 OUTBOUND @start GRAPH @graph RETURN v"
        pattern.post_action = "none"
        pattern.post_query = None
        ontology.traversal_patterns = {"reports_to": pattern}
        ontology.entities = {}
        ontology.relations = {}

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            resolver = OntologyIntentResolver(ontology=ontology)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            resolver.resolve("who does Alice reports to?", {"user_id": "u1"})
        )
        assert result.action == "graph_query"
        assert result.pattern == "reports_to"
        assert result.source == "fast_path"

    def test_resolve_fallback_to_vector_only(self) -> None:
        """Resolver falls back to vector_only when no match found."""
        ontology = self._make_mock_ontology()
        ontology.traversal_patterns = {}

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            resolver = OntologyIntentResolver(ontology=ontology, llm_client=None)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            resolver.resolve("how do I reset my password?", {})
        )
        assert result.action == "vector_only"

    def test_instantiation_without_llm_still_works(self) -> None:
        """OntologyIntentResolver works without an llm_client."""
        ontology = self._make_mock_ontology()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            resolver = OntologyIntentResolver(ontology=ontology)
        assert resolver.llm is None


class TestIntentDecisionStillImportable:
    """Tests that IntentDecision remains importable and functional."""

    def test_intent_decision_importable(self) -> None:
        """IntentDecision can be imported from parrot.knowledge.ontology.intent."""
        assert IntentDecision is not None

    def test_intent_decision_graph_query(self) -> None:
        """IntentDecision validates graph_query action."""
        decision = IntentDecision(action="graph_query", pattern="reports_to")
        assert decision.action == "graph_query"
        assert decision.pattern == "reports_to"

    def test_intent_decision_vector_only(self) -> None:
        """IntentDecision validates vector_only action."""
        decision = IntentDecision(action="vector_only")
        assert decision.action == "vector_only"

    def test_intent_decision_rejects_invalid_action(self) -> None:
        """IntentDecision rejects actions outside the Literal."""
        with pytest.raises(Exception):
            IntentDecision(action="unknown_action")
