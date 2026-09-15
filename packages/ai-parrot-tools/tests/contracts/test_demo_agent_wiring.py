"""Unit tests for the ``agents/contracts_agent.py`` deployment wiring.

The module lives in ``AGENTS_DIR`` (repo ``agents/``), outside any
distribution, so it is loaded by path. Nothing here needs Postgres, ArangoDB
or a model: the tests cover settings/roles, the ArangoDB query adapter, and
the rendering of released outcomes into the ``AIMessage`` AgentTalk expects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.knowledge.contracts.models import Citation, ContractAnswer, HandoffBrief
from parrot_tools.contracts.retrieval import Clarification
from parrot_tools.contracts.service import AnswerOutcome

AGENT_MODULE = Path(__file__).resolve().parents[4] / "agents" / "contracts_agent.py"
pytestmark = pytest.mark.skipif(not AGENT_MODULE.exists(), reason="agents/contracts_agent.py not present")


@pytest.fixture(scope="module")
def wiring():
    spec = importlib.util.spec_from_file_location("contracts_agent_under_test", AGENT_MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def citation(contract_id: str = "acme-msa", quote: str = "Vendor shall maintain SOC 2 Type II") -> Citation:
    return Citation(
        contract_id=contract_id,
        title="ACME MSA",
        node_id="n-5-2",
        quote=quote,
        page=3,
        verification="extracted",
        version_n=1,
        source_sha256="a" * 64,
    )


# -- settings and roles ----------------------------------------------------------


def test_roles_come_from_configuration_never_from_the_request(wiring):
    settings = wiring.ContractsSettings(default_roles=("contract_reader",), owners=("bob@demo",))
    assert settings.roles_for(None) == ()
    assert settings.roles_for("alice@demo") == ("contract_reader",)
    assert settings.roles_for("bob@demo") == ("contract_reader", "contract_owner")

    context = settings.request_context("alice@demo")
    assert context.authenticated and context.tenant_id == settings.tenant_id
    assert context.confirmed is False
    assert not settings.request_context(None).authenticated


def test_from_env_reads_contracts_variables(wiring, monkeypatch):
    monkeypatch.setenv("CONTRACTS_TENANT", "acme")
    monkeypatch.setenv("CONTRACTS_PG_DSN", "postgresql://u:p@h:5432/db")
    monkeypatch.setenv("CONTRACTS_ARANGO_HOST", "")
    monkeypatch.setenv("CONTRACTS_OWNERS", "bob@acme, carol@acme")
    monkeypatch.setenv("CONTRACTS_TODAY", "2026-09-09")
    settings = wiring.ContractsSettings.from_env()
    assert settings.tenant_id == "acme" and settings.pg_schema == "contracts_acme"
    assert settings.pg_dsn.endswith("/db")
    assert settings.graph_enabled is False
    assert settings.owners == ("bob@acme", "carol@acme")
    assert settings.today_clock()().isoformat() == "2026-09-09"
    assert settings.arango_database == "contracts_acme"


# -- ArangoDB adapter --------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_adapter_maps_rows_and_errors(wiring):
    class Driver:
        async def query(self, aql, bind_vars=None):
            if "boom" in aql:
                return None, "AQL Query Error: boom"
            if "empty" in aql:
                return None, "[HTTP 404] No Data Found"
            return [{"ok": bind_vars["x"]}], None

    adapter = wiring.ArangoQueryAdapter({"host": "h"})
    object.__setattr__(adapter, "_driver", Driver())
    assert await adapter.execute_query("RETURN 1", bind_vars={"x": 1}) == [{"ok": 1}]
    assert await adapter.execute_query("empty") == []
    with pytest.raises(RuntimeError):
        await adapter.execute_query("boom")


def test_query_adapter_refuses_attribute_access_before_connect(wiring):
    adapter = wiring.ArangoQueryAdapter({"host": "h"})
    assert adapter.connected is False
    with pytest.raises(RuntimeError):
        _ = adapter.use


# -- rendering the released outcome ------------------------------------------------


def test_lookup_renders_answer_and_sources(wiring):
    answer = ContractAnswer(answer_kind="lookup", answer="ACME must hold SOC 2.", citations=[citation()])
    text = wiring.render_outcome(AnswerOutcome(answer=answer, answer_id="ans-1"))
    assert text.startswith("ACME must hold SOC 2.")
    assert "Sources:" in text and "acme-msa · n-5-2 · p.3" in text


def test_interpretation_renders_the_handoff_not_a_judgment(wiring):
    brief = HandoffBrief(
        question="Should we terminate?",
        why_judgment="termination is a business decision",
        located_clauses=[citation()],
        related_contracts=["acme-sow-1"],
        suggested_owner="bob@demo",
    )
    answer = ContractAnswer(answer_kind="interpretation_required", handoff=brief)
    text = wiring.render_outcome(AnswerOutcome(answer=answer, answer_id="ans-2"))
    assert "human judgment" in text and "termination is a business decision" in text
    assert "acme-sow-1" in text and "bob@demo" in text


def test_not_found_denied_and_clarification_render_no_evidence(wiring):
    not_found = ContractAnswer(answer_kind="not_found", reason="no citation survived")
    denied = ContractAnswer(answer_kind="denied", reason="missing role")
    assert "could not find" in wiring.render_outcome(AnswerOutcome(answer=not_found, answer_id="a"))
    assert "not authorized" in wiring.render_outcome(AnswerOutcome(answer=denied, answer_id="b"))
    text = wiring.render_outcome(Clarification(reason="which ACME contract?", candidates=["acme-msa", "acme-nda"]))
    assert "clarification" in text and "- acme-nda" in text


def test_to_message_wraps_the_released_answer_as_an_aimessage(wiring):
    settings = wiring.ContractsSettings(agent_llm="google:gemini-3.1-flash-lite")
    fake_agent = SimpleNamespace(settings=settings)
    answer = ContractAnswer(answer_kind="lookup", answer="Net 45.", citations=[citation(quote="net 45")])
    outcome = AnswerOutcome(answer=answer, answer_id="ans-9", dropped_claims=["invented"])
    message = wiring.ContractsDemoAgent.to_message(fake_agent, "payment terms?", outcome, user_id="u", session_id="s")
    assert message.output.startswith("Net 45.")
    assert message.provider == "google" and message.model == "gemini-3.1-flash-lite"
    assert message.data["kind"] == "lookup" and message.data["answer_id"] == "ans-9"
    assert message.data["dropped_claims"] == ["invented"]
    assert message.user_id == "u" and message.session_id == "s"


def test_the_gated_entrypoints_are_overridden(wiring):
    """The demo agent must route ask/ask_stream through the gate, not refuse them."""
    cls = wiring.ContractsDemoAgent
    assert "ask" in vars(cls) and "ask_stream" in vars(cls)
    assert "invoke" not in vars(cls), "invoke() keeps the base refusal"
