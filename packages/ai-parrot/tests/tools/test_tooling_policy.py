"""M7 unit tests for the tenant tooling policy core (FEAT-622)."""
from uuid import uuid4

import pytest
from aiohttp import web

from parrot.tools.spec import AgentMCPServerSpec, NormalizedTooling, ToolkitSpec
from parrot.tools.tooling_policy import (
    HostMCPServer,
    TenantToolingPolicy,
    TenantToolingRefused,
    ToolingSubject,
    effective_mcp_config,
    enforce_tenant_tooling,
    get_tenant_tooling_policy,
    set_tenant_tooling_policy,
)

from ._host_probe import host_plugins  # noqa: F401

AGENT_ID = uuid4()
SUBJECT = ToolingSubject(tenant="acme", agent_id=AGENT_ID, actor="u1", phase="write")
POLICY = TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",))


def _mcp(**kw) -> AgentMCPServerSpec:
    kw.setdefault("name", "srv")
    return AgentMCPServerSpec(**kw)


@pytest.mark.parametrize(
    "raw, reason",
    [
        (dict(transport="stdio", command="sh"), "local_execution"),
        (dict(transport="stdio", url="https://mcp.host/api/x"), "local_execution"),
        (dict(url="https://mcp.host/api/x", params={"transport": "stdio", "command": "sh"}), "local_execution"),
        (dict(transport="auto", params={"command": "sh"}), "local_execution"),
        (dict(url="https://mcp.host/api/x", params={"socket_path": "/tmp/s"}), "local_execution"),
        (dict(url="https://mcp.host/api/x", args=["-c", "x"]), "local_execution"),
        (dict(url="https://mcp.host/api/x", secret_refs={"env": "v"}), "local_execution"),
        (dict(url="https://mcp.host/api/x", params={"transport": "websocket"}), "transport_not_permitted"),
        (dict(url="https://mcp.host/api/x", params={"header_provider": "x"}), "field_not_permitted"),
        (dict(url="https://mcp.host/api/x", secret_refs={"command": "v"}), "local_execution"),
    ],
)
def test_policy_refuses_stdio_and_params_smuggling(raw, reason):
    """Explicit/auto/params-smuggled local execution and bad fields are refused in spec order."""
    with pytest.raises(TenantToolingRefused) as err:
        POLICY.resolve_mcp(effective_mcp_config(_mcp(**raw)), subject=SUBJECT)
    assert err.value.reason == reason
    assert err.value.code == "tooling_not_permitted"


def test_policy_accepts_clean_http_spec():
    """A plain https spec under an allowed prefix returns its kwargs."""
    out = POLICY.resolve_mcp(effective_mcp_config(_mcp(url="https://mcp.host/api/x")), subject=SUBJECT)
    assert out["url"] == "https://mcp.host/api/x"


def test_policy_endpoint_allowlist_normalisation():
    """Prefix normalisation: case/port/segment boundary; userinfo, http, missing url refused."""
    ok = effective_mcp_config(_mcp(url="https://MCP.host:443/api/x"))
    assert POLICY.resolve_mcp(ok, subject=SUBJECT)
    for url in (
        "https://mcp.host/apix",
        "https://user:pw@mcp.host/api/x",
        "http://mcp.host/api/x",
        "https://mcp.host/api/../secret",
        "https://mcp.host:8443/api/x",
    ):
        with pytest.raises(TenantToolingRefused) as err:
            POLICY.resolve_mcp(effective_mcp_config(_mcp(url=url)), subject=SUBJECT)
        assert err.value.reason == "endpoint_not_allowed", url
    with pytest.raises(TenantToolingRefused) as err:
        POLICY.resolve_mcp(effective_mcp_config(_mcp()), subject=SUBJECT)
    assert err.value.reason == "endpoint_not_allowed"
    with pytest.raises(ValueError):
        TenantToolingPolicy(mcp_endpoints=("http://mcp.host/",))


def test_policy_named_host_server_allows_host_stdio():
    """A named host server (stdio config) passes with tenant fields only; url/command → field_not_permitted."""
    host = HostMCPServer(name="hs", config={"transport": "stdio", "command": "/opt/mcp", "name": "hs"})
    policy = TenantToolingPolicy(mcp_servers={"hs": host})
    out = policy.resolve_mcp(effective_mcp_config(_mcp(name="hs", allowed_tools=["a"])), subject=SUBJECT)
    assert out["command"] == "/opt/mcp" and out["allowed_tools"] == ["a"] and out["name"] == "hs"
    for extra in ({"url": "https://x/"}, {"command": "sh"}):
        with pytest.raises(TenantToolingRefused) as err:
            policy.resolve_mcp(effective_mcp_config(_mcp(name="hs", **extra)), subject=SUBJECT)
        assert err.value.reason == "field_not_permitted"


def test_policy_builtin_allowlist(host_plugins):
    """deny_all refuses built-ins; allow-listed passes; host toolkit passes; unknown is unavailable."""
    deny = TenantToolingPolicy.deny_all()
    for slug in ("shell", "python_execution", "docker"):
        with pytest.raises(TenantToolingRefused) as err:
            deny.check_tool(slug, subject=SUBJECT)
        assert err.value.reason == "builtin_not_permitted"
    TenantToolingPolicy(builtin_tools=frozenset({"wiki"})).check_tool("WIKI", subject=SUBJECT)
    deny.check_tool("tp_probe", subject=SUBJECT)
    with pytest.raises(TenantToolingRefused) as err:
        deny.check_tool("nope_missing", subject=SUBJECT)
    assert err.value.reason == "toolkit_unavailable"
    with pytest.raises(TenantToolingRefused):
        TenantToolingPolicy(host_toolkits=False).check_tool("tp_probe", subject=SUBJECT)


def test_policy_refuses_client_secret_refs():
    """write/activate/attach refuse any client secret_refs/vault_owner; build checks namespace and owner."""
    ref = f"studio-agent:{AGENT_ID}"
    tk = NormalizedTooling(toolkits=[ToolkitSpec(slug="wiki", secret_refs={"k": "toolkit_wiki_x"}, vault_owner="u")])
    pol = TenantToolingPolicy(builtin_tools=frozenset({"wiki"}))
    for phase in ("write", "activate", "attach"):
        subj = SUBJECT.model_copy(update={"phase": phase})
        with pytest.raises(TenantToolingRefused) as err:
            pol.check_tooling(tk, subject=subj)
        assert err.value.reason == "secret_ref_not_permitted"
    build = SUBJECT.model_copy(update={"phase": "build"})
    with pytest.raises(TenantToolingRefused):  # foreign vault name
        pol.check_tooling(tk, subject=build, owner="u")
    good = NormalizedTooling(
        toolkits=[ToolkitSpec(slug="wiki", secret_refs={"k": f"toolkit_wiki_{ref}"}, vault_owner="u")]
    )
    pol.check_tooling(good, subject=build, owner="u")
    with pytest.raises(TenantToolingRefused):  # wrong owner
        pol.check_tooling(good, subject=build, owner="other")
    mcp_good = NormalizedTooling(
        mcp_servers=[_mcp(url="https://mcp.host/api/x", secret_refs={"headers": f"mcp_agent_srv_{ref}"}, vault_owner="u")]
    )
    POLICY.check_tooling(mcp_good, subject=build, owner="u")
    with pytest.raises(TenantToolingRefused):
        POLICY.check_tooling(mcp_good, subject=build, owner="x")


def test_policy_registration_once_and_default_deny():
    """Unset → deny_all; set once; second set raises; enforce is a no-op for tenant=None unless apply_to_global."""
    app = web.Application()
    assert get_tenant_tooling_policy(app) == TenantToolingPolicy.deny_all()
    set_tenant_tooling_policy(app, POLICY)
    assert get_tenant_tooling_policy(app) is POLICY
    with pytest.raises(RuntimeError):
        set_tenant_tooling_policy(app, POLICY)
    bad = NormalizedTooling(tools=["shell"])
    glob = SUBJECT.model_copy(update={"tenant": None})
    enforce_tenant_tooling(app, bad, subject=glob)
    with pytest.raises(TenantToolingRefused):
        enforce_tenant_tooling(app, bad, subject=SUBJECT)
    app2 = web.Application()
    set_tenant_tooling_policy(app2, TenantToolingPolicy(apply_to_global=True))
    with pytest.raises(TenantToolingRefused):
        enforce_tenant_tooling(app2, bad, subject=glob)
