from navconfig import config
from parrot.bots import Agent
from parrot.registry import register_agent
from parrot.tools.databasequery import DatabaseQueryTool
from parrot.mcp import RedisTokenStore
from parrot.conf import (
    NETSUITE_ACCOUNT_ID,
    NETSUITE_CLIENT_ID,
    NETSUITE_CERTIFICATE_ID,
    NETSUITE_PRIVATE_KEY_PATH,
)


BACKSTORY = """
You are a finance operations specialist with direct access to NetSuite ERP data
through the NetSuite MCP connector.

Your capabilities include:
- Querying invoices, purchase orders, sales orders, and journal entries.
- Looking up customer, vendor, and employee records.
- Retrieving account balances and financial summaries.
- Running saved searches defined in NetSuite.

Guidelines:
- Always confirm which NetSuite entity or record type the user is asking about
  before executing a query.
- When presenting monetary values include the currency code.
- If a NetSuite MCP tool returns an error, explain the issue and suggest what
  the user can check (permissions, record IDs, date ranges).
- Never fabricate financial data. If the information is unavailable, say so.
"""


@register_agent(name="finance_agent", at_startup=True)
class FinanceAgent(Agent):
    """Finance agent connected to NetSuite via MCP (OAuth2 Client Credentials M2M)."""

    agent_id: str = "finance_agent"
    model: str = "gemini-2.5-pro"
    max_tokens: int = 16000

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            backstory=BACKSTORY,
            tools=[DatabaseQueryTool()],
            **kwargs,
        )

    async def configure(self, app=None):
        """Wire up the NetSuite MCP server after base configuration."""
        await super().configure(app)

        missing = [
            name for name, val in [
                ("NETSUITE_ACCOUNT_ID", NETSUITE_ACCOUNT_ID),
                ("NETSUITE_CLIENT_ID", NETSUITE_CLIENT_ID),
                ("NETSUITE_CERTIFICATE_ID", NETSUITE_CERTIFICATE_ID),
                ("NETSUITE_PRIVATE_KEY_PATH", NETSUITE_PRIVATE_KEY_PATH),
            ] if not val
        ]
        if missing:
            self.logger.warning(
                "NetSuite MCP skipped — missing env vars: %s", ", ".join(missing)
            )
            return

        redis_url = config.get("REDIS_URL", fallback=None)
        token_store = RedisTokenStore(redis_url) if redis_url else None

        tools = await self.add_netsuite_m2m_mcp_server(
            account_id=NETSUITE_ACCOUNT_ID,
            client_id=NETSUITE_CLIENT_ID,
            certificate_id=NETSUITE_CERTIFICATE_ID,
            private_key_path=NETSUITE_PRIVATE_KEY_PATH,
            **({"token_store": token_store} if token_store else {}),
        )
        self.logger.info(
            "NetSuite MCP registered %d tools: %s", len(tools), tools
        )
