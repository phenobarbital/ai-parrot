"""FEAT-621 M10 — identity helpers (§2.5c)."""
from types import SimpleNamespace  # plain object stand-in for a bot: no request/session plumbing involved

from parrot.tools.spec import agent_tooling_ref, mcp_vault_name, toolkit_override_vault_name, toolkit_vault_name

REF = "studio-agent:0b0c7c8e-1111-4222-8333-444455556666"


def test_vault_names_from_ref() -> None:
    assert toolkit_vault_name("jira", REF) == f"toolkit_jira_{REF}"
    assert toolkit_vault_name("jira", "sales") == "toolkit_jira_sales"   # legacy unchanged
    assert mcp_vault_name("srv", REF) == f"mcp_agent_srv_{REF}"
    assert mcp_vault_name("srv", "sales") == "mcp_agent_srv_sales"
    assert toolkit_override_vault_name("jira", REF) == f"toolkit_jira_{REF}_user"
    assert toolkit_override_vault_name("jira", "sales") == "toolkit_jira_sales_user"


def test_agent_tooling_ref_legacy_and_studio() -> None:
    assert agent_tooling_ref(SimpleNamespace(name="sales")) == "sales"
    assert agent_tooling_ref(SimpleNamespace(name="sales", _tooling_ref=None)) == "sales"
    assert agent_tooling_ref(SimpleNamespace(name="sales", _tooling_ref=REF)) == REF
