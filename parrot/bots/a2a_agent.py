from aiohttp import web
from .agent import BasicAgent
from ..a2a.server import A2AEnabledMixin


class A2AAgent(BasicAgent, A2AEnabledMixin):
    """An AI-Parrot Agent with A2A capabilities."""

    def __init__(self, app: web.Application, url: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.url = url
        # add the "configure" into the startup signal
        self.app.middlewares.append(self.configure)

    async def configure(self):
        """Configure the agent and initialize A2A server."""
        await super().configure()
        self.setup_a2a(self.app, self.url)
