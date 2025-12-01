from parrot.services.mcp import ParrotMCPServer
from parrot.tools.workday import WorkdayToolkit

mcp = ParrotMCPServer(
    name="workday-mcp",
    tools={
        "workday": WorkdayToolkit(redis_url="redis://localhost:6379/4")
    }
)
