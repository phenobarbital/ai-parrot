from parrot.knowledge.wiki.mcp_server import create_proxy_mcp_server
from parrot.knowledge.wiki.project import WikiRemoteConfig

from .test_remote_client import server


async def test_forwarding(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    srv = create_proxy_mcp_server(WikiRemoteConfig(url=url, actor="agent:proxy-test"))

    init = await srv._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    assert init["result"]["serverInfo"]["name"] == "wikitoolkit"
    assert init["result"]["serverInfo"]["description"] == f"remote proxy → {url}"

    tools = await srv._handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert "tools" in tools["result"]

    call = await srv._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wiki_query", "arguments": {"question": "x"}},
        }
    )
    assert call["result"]["content"][0]["text"] == "hello"
    assert fake.seen[-1]["X-Wiki-Actor"] == "agent:proxy-test"


async def test_remote_down_is_jsonrpc_error(monkeypatch):
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    srv = create_proxy_mcp_server(WikiRemoteConfig(url="http://127.0.0.1:9/mcp/w"))

    response = await srv._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "wiki_query", "arguments": {}},
        }
    )
    assert response["error"]["code"] == -32603
    assert "[remote:" in response["error"]["message"]
