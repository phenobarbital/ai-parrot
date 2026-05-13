"""Tests for FEAT-158 schema extensions: EntityExtractionRule, AuthorizationRule,
AuthorizationSpec, ToolCallSpec, ContextEnvelope, and backward-compatible
extensions to TraversalPattern and ResolvedIntent.
"""
import pytest
from pydantic import ValidationError

from parrot.knowledge.ontology.schema import (
    AuthorizationRule,
    AuthorizationSpec,
    ContextEnvelope,
    EnrichedContext,
    EntityExtractionRule,
    ResolvedIntent,
    ToolCallSpec,
    TraversalPattern,
)


class TestEntityExtractionRule:
    """Tests for EntityExtractionRule Pydantic model."""

    def test_defaults(self) -> None:
        """Default values for optional fields are correct."""
        rule = EntityExtractionRule(type="Employee", resolver="fuzzy_name_match")
        assert rule.scope == "same_tenant"
        assert rule.ambiguity_strategy == "ask_user"
        assert rule.required is True
        assert rule.description is None

    def test_forbids_extra(self) -> None:
        """Extra fields are rejected by ConfigDict(extra='forbid')."""
        with pytest.raises(ValidationError):
            EntityExtractionRule(
                type="Employee", resolver="exact_id_match", bogus=1
            )

    def test_all_resolvers_valid(self) -> None:
        """All four resolver literals are accepted."""
        for resolver in (
            "exact_id_match",
            "fuzzy_name_match",
            "ai_assisted",
            "hybrid_concept_match",
        ):
            rule = EntityExtractionRule(type="Employee", resolver=resolver)
            assert rule.resolver == resolver

    def test_invalid_resolver_rejected(self) -> None:
        """An unknown resolver literal raises ValidationError."""
        with pytest.raises(ValidationError):
            EntityExtractionRule(type="Employee", resolver="unknown_strategy")

    def test_optional_not_required(self) -> None:
        """A rule with required=False is accepted."""
        rule = EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match", required=False
        )
        assert rule.required is False


class TestAuthorizationRule:
    """Tests for AuthorizationRule model_validator enforcement."""

    def test_has_role_requires_role(self) -> None:
        """AuthorizationRule with rule='has_role' and no role raises ValidationError."""
        with pytest.raises(ValidationError, match="has_role"):
            AuthorizationRule(rule="has_role")

    def test_has_role_with_role_ok(self) -> None:
        """AuthorizationRule with rule='has_role' and a role is valid."""
        rule = AuthorizationRule(rule="has_role", role="hr_manager")
        assert rule.role == "hr_manager"

    def test_target_is_self_no_role_ok(self) -> None:
        """target_is_self rule without role field is valid."""
        rule = AuthorizationRule(rule="target_is_self")
        assert rule.rule == "target_is_self"
        assert rule.role is None

    def test_target_in_management_chain_ok(self) -> None:
        """target_in_management_chain rule is valid without role."""
        rule = AuthorizationRule(rule="target_in_management_chain")
        assert rule.rule == "target_in_management_chain"

    def test_same_department_ok(self) -> None:
        """same_department rule is valid without role."""
        rule = AuthorizationRule(rule="same_department")
        assert rule.rule == "same_department"

    def test_always_ok(self) -> None:
        """always rule is valid."""
        rule = AuthorizationRule(rule="always")
        assert rule.rule == "always"

    def test_forbids_extra(self) -> None:
        """Extra fields rejected."""
        with pytest.raises(ValidationError):
            AuthorizationRule(rule="target_is_self", extra_field="oops")


class TestAuthorizationSpec:
    """Tests for AuthorizationSpec model."""

    def test_default_deny_true(self) -> None:
        """default_deny defaults to True."""
        spec = AuthorizationSpec()
        assert spec.default_deny is True
        assert spec.rules == []

    def test_default_deny_false(self) -> None:
        """default_deny can be set to False."""
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_is_self")],
            default_deny=False,
        )
        assert spec.default_deny is False

    def test_forbids_extra(self) -> None:
        """Extra fields rejected."""
        with pytest.raises(ValidationError):
            AuthorizationSpec(bogus=True)


class TestToolCallSpec:
    """Tests for ToolCallSpec model."""

    def test_defaults(self) -> None:
        """credential_mode and empty_team_behavior have correct defaults."""
        spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            result_binding="issues",
        )
        assert spec.credential_mode == "requesting_user"
        assert spec.empty_team_behavior == "short_circuit"
        assert spec.parameters == {}

    def test_with_parameters(self) -> None:
        """parameters dict is stored as-is."""
        spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            parameters={"jql": "project = TROC"},
            result_binding="issues",
        )
        assert spec.parameters["jql"] == "project = TROC"

    def test_forbids_extra(self) -> None:
        """Extra fields rejected."""
        with pytest.raises(ValidationError):
            ToolCallSpec(
                toolkit="JiraToolkit",
                method="jira_search_issues",
                result_binding="issues",
                unknown_field="x",
            )

    def test_all_credential_modes(self) -> None:
        """All credential_mode literals are valid."""
        for mode in ("requesting_user", "service_account", "agent_owner"):
            spec = ToolCallSpec(
                toolkit="T",
                method="m",
                result_binding="r",
                credential_mode=mode,
            )
            assert spec.credential_mode == mode


class TestContextEnvelope:
    """Tests for ContextEnvelope model."""

    def test_ok_with_context(self) -> None:
        """state='ok' accepts an EnrichedContext."""
        ctx = EnrichedContext(
            source="ontology",
            graph_context=None,
            vector_context=None,
            tool_hint=None,
            intent=None,
            metadata={},
        )
        env = ContextEnvelope(state="ok", context=ctx)
        assert env.context is ctx
        assert env.clarification is None
        assert env.denial_reason is None

    def test_denied_with_reason(self) -> None:
        """state='denied' stores denial_reason."""
        env = ContextEnvelope(state="denied", denial_reason="not authorized")
        assert env.context is None
        assert env.denial_reason == "not authorized"

    def test_ambiguous_with_clarification(self) -> None:
        """state='ambiguous' stores clarification dict."""
        env = ContextEnvelope(
            state="ambiguous",
            clarification={
                "rule": "target_employee",
                "mention": "Jesús",
                "candidates": [{"_id": "Emp/1"}, {"_id": "Emp/2"}],
            },
        )
        assert env.state == "ambiguous"
        assert len(env.clarification["candidates"]) == 2

    def test_auth_required_with_prompt(self) -> None:
        """state='auth_required' stores auth_prompt."""
        env = ContextEnvelope(
            state="auth_required",
            auth_prompt={
                "auth_url": "https://auth/url",
                "provider": "jira",
                "scopes": ["read:jira-work"],
            },
        )
        assert env.auth_prompt["provider"] == "jira"

    def test_forbids_extra(self) -> None:
        """Extra fields rejected."""
        with pytest.raises(ValidationError):
            ContextEnvelope(state="ok", bogus="x")


class TestTraversalPatternBackCompat:
    """Tests for backwards-compatible extensions to TraversalPattern."""

    def test_minimal_pattern_loads(self) -> None:
        """Existing-style pattern without any new sections still validates."""
        TraversalPattern(
            description="t",
            trigger_intents=["x"],
            query_template="FOR e IN c RETURN e",
            post_action="vector_search",
            post_query=None,
        )

    def test_entity_extraction_defaults_empty(self) -> None:
        """entity_extraction defaults to empty dict."""
        p = TraversalPattern(
            description="t",
            trigger_intents=["x"],
            query_template="FOR e IN c RETURN e",
            post_action="none",
        )
        assert p.entity_extraction == {}
        assert p.authorization is None
        assert p.tool_call is None

    def test_pattern_with_new_sections(self) -> None:
        """Pattern with all three new sections loads and round-trips correctly."""
        p = TraversalPattern(
            description="t",
            trigger_intents=["x"],
            query_template="FOR e IN c RETURN e",
            post_action="tool_call",
            post_query=None,
            entity_extraction={
                "target": EntityExtractionRule(
                    type="Employee", resolver="fuzzy_name_match"
                )
            },
            authorization=AuthorizationSpec(
                rules=[AuthorizationRule(rule="target_is_self")]
            ),
            tool_call=ToolCallSpec(
                toolkit="JiraToolkit",
                method="jira_search_issues",
                result_binding="issues",
            ),
        )
        assert "target" in p.entity_extraction
        assert p.tool_call is not None
        assert p.tool_call.method == "jira_search_issues"
        assert p.authorization is not None
        assert len(p.authorization.rules) == 1


class TestResolvedIntentBackCompat:
    """Tests for backwards-compatible extensions to ResolvedIntent."""

    def test_minimal_resolved_intent_loads(self) -> None:
        """Existing-style ResolvedIntent without new fields still loads."""
        intent = ResolvedIntent(
            action="graph_query",
            pattern="find_dept",
            aql="FOR v IN c RETURN v",
            params={"user_id": "emp/1"},
            collection_binds={},
            post_action="none",
            source="fast_path",
        )
        assert intent.resolved_entities == {}
        assert intent.tool_call is None
        assert intent.denial_reason is None

    def test_new_fields_accepted(self) -> None:
        """New optional fields are accepted on ResolvedIntent."""
        spec = ToolCallSpec(
            toolkit="JiraToolkit",
            method="jira_search_issues",
            result_binding="issues",
        )
        intent = ResolvedIntent(
            action="graph_query",
            resolved_entities={"target_employee": "Employee/42"},
            tool_call=spec,
            denial_reason=None,
        )
        assert intent.resolved_entities["target_employee"] == "Employee/42"
        assert intent.tool_call.toolkit == "JiraToolkit"
