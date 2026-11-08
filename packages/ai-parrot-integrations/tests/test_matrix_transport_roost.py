"""Tests for MatrixCrewTransport's opt-in Roost endpoint factory — FEAT-827 TASK-5247."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.matrix.crew.config import MatrixCrewAgentEntry, MatrixCrewConfig
from parrot.integrations.matrix.crew.transport import MatrixCrewTransport

pytestmark = pytest.mark.asyncio


def _config():
    return MatrixCrewConfig(
        homeserver_url="http://hs",
        server_name="parrot.local",
        as_token="a",
        hs_token="h",
        bot_mxid="@parrot:parrot.local",
        general_room_id="!gen:parrot.local",
        agents={
            name: MatrixCrewAgentEntry(chatbot_id=name, display_name=name.title(), mxid_localpart=f"parrot-{name}")
            for name in ("analyst", "writer")
        },
    )


def _transport(factory=None):
    transport = MatrixCrewTransport(_config(), roost_endpoint_factory=factory)
    transport._wrappers = {name: MagicMock(name=f"wrapper-{name}") for name in ("analyst", "writer")}
    return transport


def _endpoint():
    endpoint = MagicMock()
    endpoint.start = AsyncMock()
    endpoint.stop = AsyncMock()
    return endpoint


async def test_factory_builds_and_starts_one_endpoint_per_agent():
    endpoints = {"analyst": _endpoint(), "writer": _endpoint()}
    factory = MagicMock(side_effect=lambda name, wake: endpoints[name])
    transport = _transport(factory)

    assert await transport._start_roost_endpoint("analyst") is endpoints["analyst"]
    assert await transport._start_roost_endpoint("writer") is endpoints["writer"]

    assert [call.args for call in factory.call_args_list] == [
        ("analyst", transport._wrappers["analyst"].handle_roost_wake),
        ("writer", transport._wrappers["writer"].handle_roost_wake),
    ]
    for endpoint in endpoints.values():
        endpoint.start.assert_awaited_once()
    assert transport._roost_endpoints == endpoints


async def test_without_a_factory_no_endpoint_is_built():
    transport = _transport()
    assert await transport._start_roost_endpoint("analyst") is None
    assert transport._roost_endpoints == {}


async def test_an_agent_without_a_wrapper_gets_no_endpoint():
    factory = MagicMock()
    transport = _transport(factory)
    assert await transport._start_roost_endpoint("ghost") is None
    factory.assert_not_called()


async def test_a_factory_error_propagates_and_stops_the_endpoints_already_started():
    first = _endpoint()
    factory = MagicMock(side_effect=[first, RuntimeError("no carrier")])
    transport = _transport(factory)
    await transport._start_roost_endpoint("analyst")

    with pytest.raises(RuntimeError, match="no carrier"):
        await transport._start_roost_endpoint("writer")

    first.stop.assert_awaited_once()
    assert transport._roost_endpoints == {}


async def test_a_start_error_propagates():
    broken = _endpoint()
    broken.start.side_effect = RuntimeError("bind failed")
    transport = _transport(MagicMock(return_value=broken))
    with pytest.raises(RuntimeError, match="bind failed"):
        await transport._start_roost_endpoint("analyst")
    assert transport._roost_endpoints == {}


async def test_stop_stops_every_endpoint_even_when_one_fails():
    endpoints = {"analyst": _endpoint(), "writer": _endpoint()}
    endpoints["analyst"].stop.side_effect = RuntimeError("already closed")
    transport = _transport(MagicMock(side_effect=lambda name, wake: endpoints[name]))
    await transport._start_roost_endpoint("analyst")
    await transport._start_roost_endpoint("writer")
    transport._appservice = AsyncMock()

    await transport.stop()

    for endpoint in endpoints.values():
        endpoint.stop.assert_awaited_once()
    assert transport._roost_endpoints == {}


async def test_from_yaml_passes_the_factory_through():
    factory = MagicMock()
    with patch("parrot.integrations.matrix.crew.transport.MatrixCrewConfig.from_yaml", return_value=_config()):
        transport = MatrixCrewTransport.from_yaml("crew.yaml", roost_endpoint_factory=factory)
    assert transport._roost_endpoint_factory is factory


def _bots():
    return {name: MagicMock(name=f"bot-{name}", tool_manager=MagicMock()) for name in ("analyst", "writer")}


async def test_each_swarm_toolkit_receives_its_agents_endpoint():
    endpoints = {"analyst": _endpoint(), "writer": _endpoint()}
    transport = _transport(MagicMock(side_effect=lambda name, wake: endpoints[name]))
    transport._tunnels, transport._channels, transport._appservice = MagicMock(), MagicMock(), AsyncMock()
    bots = _bots()

    with patch("parrot.manager.BotManager.get_bot", AsyncMock(side_effect=lambda chatbot_id: bots[chatbot_id])):
        await transport._attach_swarm_toolkits()

    for name, bot in bots.items():
        toolkit = bot.tool_manager.register_toolkit.call_args.args[0]
        assert toolkit._agent_name == name
        assert toolkit._endpoint is endpoints[name]


async def test_without_a_factory_the_swarm_toolkit_keeps_the_tunnel_path():
    transport = _transport()
    transport._tunnels, transport._channels, transport._appservice = MagicMock(), MagicMock(), AsyncMock()
    bots = _bots()

    with patch("parrot.manager.BotManager.get_bot", AsyncMock(side_effect=lambda chatbot_id: bots[chatbot_id])):
        await transport._attach_swarm_toolkits()

    for bot in bots.values():
        assert bot.tool_manager.register_toolkit.call_args.args[0]._endpoint is None
    assert transport._roost_endpoints == {}


async def test_an_unresolvable_bot_gets_neither_toolkit_nor_endpoint():
    factory = MagicMock()
    transport = _transport(factory)
    transport._tunnels, transport._channels, transport._appservice = MagicMock(), MagicMock(), AsyncMock()

    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=None)):
        await transport._attach_swarm_toolkits()

    factory.assert_not_called()
