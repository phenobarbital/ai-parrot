"""Tests for deterministic procedure retrieval."""
from __future__ import annotations

import pytest

from parrot.knowledge.manuals.domain import CURATOR_ROLE, TECHNICIAN_ROLE
from parrot_tools.procedures.retrieval import (
    READ_ROLES, AuthorizationDenied, Clarification, PatternPlan, ProcedureRetrieval, classify,
)

from ._doubles import FakeCatalog, FakeGraphStore, FakeOntology, FakePageIndex, FakePattern, make_context


def _retrieval(**kw):
    """Create retrieval with independently replaceable collaborators."""
    return ProcedureRetrieval(catalog=kw.pop("catalog", FakeCatalog()), graph_store=kw.pop("graph", FakeGraphStore()),
                              tenant_context=None, ontology=kw.pop("ontology", FakeOntology()), authorization=None, **kw)


class TestAuthorizeTightenedTenantGate:
    """The procedures tenant gate denies absent tenant identity as well."""

    def test_authorize_tightened_tenant_gate(self):
        """Only an authenticated reader on the catalog tenant passes the local gate."""
        retrieval = _retrieval()
        retrieval.authorize(make_context())
        for context in (make_context(tenant_id=""), make_context(tenant_id="t2"), make_context(roles=()), make_context(authenticated=False)):
            with pytest.raises(AuthorizationDenied):
                retrieval.authorize(context)

    def test_curator_only(self):
        """Curator-only operations do not allow a technician role."""
        retrieval = _retrieval()
        with pytest.raises(AuthorizationDenied):
            retrieval.authorize(make_context(), curator_only=True)
        retrieval.authorize(make_context(roles=("manual_curator",)), curator_only=True)

    def test_read_roles_match_domain(self):
        """The public role allowlist remains tied to the domain constants."""
        assert READ_ROLES == frozenset({TECHNICIAN_ROLE, CURATOR_ROLE})


class TestClassify:
    """Ordered bilingual trigger planning fails closed."""

    def test_classify_triggers_fail_closed(self):
        """Spanish and English assembly requests reach the same pattern."""
        assert classify("¿Cómo ensamblo el modelo X?") == "procedure_steps"
        assert classify("How do I assemble model X?") == "procedure_steps"
        assert classify("¿Qué necesito antes de empezar?") == "procedure_prerequisites"
        assert classify("tell me a joke") is None

    async def test_plan_unknown_is_clarification(self):
        """Unknown phrasing returns a typed clarification before any catalog read."""
        assert isinstance(await _retrieval().plan("tell me a joke", make_context()), Clarification)


class TestGraph:
    """Graph and fallback execution maintain their authorization boundaries."""

    def test_aql_for_allowlist(self):
        """Only declared graph patterns expose query templates."""
        retrieval = _retrieval(ontology=FakeOntology({"procedure_steps": FakePattern("FOR s IN step RETURN s")}))
        assert retrieval.aql_for("procedure_steps").startswith("FOR")
        for bad in ("lookup", "drop_everything"):
            with pytest.raises(AuthorizationDenied):
                retrieval.aql_for(bad)

    async def test_execute_graph_denies_before_traversal(self):
        """A tenant denial occurs before calling the graph store."""
        graph = FakeGraphStore()
        retrieval = _retrieval(graph=graph)
        with pytest.raises(AuthorizationDenied):
            await retrieval.execute_graph(PatternPlan(pattern="procedure_steps"), make_context(tenant_id=""))
        assert graph.calls == []

    async def test_fallback_lookup_is_llm_free_and_gated(self):
        """PageIndex fallback disables its LLM walk and remains role-gated."""
        pageindex = FakePageIndex([{"node_id": "n1", "title": "Assembly", "page": 3}])
        retrieval = _retrieval(pageindex=pageindex)
        result = await retrieval.fallback_lookup("torque for bolt", "m1", make_context())
        assert result.pattern == "lookup" and pageindex.calls[0]["use_llm_walk"] is False
        with pytest.raises(AuthorizationDenied):
            await retrieval.fallback_lookup("q", "m1", make_context(roles=()))
