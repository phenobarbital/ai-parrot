"""A toolkit CLASS named in ``tools=[...]`` is constructed through the host hook and the server-param source too."""
from __future__ import annotations

import logging

from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.server_params import ServerParam
from parrot.tools.toolkit import AbstractToolkit


class _Toolkit(AbstractToolkit):
    """Toolkit with an app-sourced constructor dependency and a hook-forced switch."""

    server_managed_params = {"store": ServerParam(source="app", key="the_store")}

    def __init__(self, store: object = None, confined: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self.confined = confined

    async def ping(self) -> str:
        """Answer pong."""
        return "pong"


class _Bot(ToolInterface):
    def __init__(self) -> None:
        self.logger = logging.getLogger("tool_class_path")
        self.tool_manager = ToolManager()


def test_a_toolkit_class_goes_through_the_hook_and_the_server_fill():
    bot = _Bot()
    seen: list[tuple] = []

    def hook(slug, params, subject):
        seen.append((slug, dict(params)))
        return {**params, "confined": True}

    bot.tool_manager.set_toolkit_param_hook(hook)
    bot.tool_manager.set_server_param_source({"the_store": "STORE"})
    bot._initialize_tools([_Toolkit])
    assert seen == [("_toolkit", {"store": "STORE"})]
    names = bot.tool_manager.list_tools()
    toolkit = get_toolkit_owner(bot.tool_manager.get_tool(names[0]))
    assert toolkit.confined is True and toolkit.store == "STORE"
