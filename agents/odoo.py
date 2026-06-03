import os

from parrot.bots import Agent
from parrot.registry import register_agent
from parrot_tools.odoo import OdooToolkit
from parrot.models.google import GoogleModel


# ── Odoo test instance (prozac, Odoo 18.0) ──────────────────────────────────
# This agent targets a local *test* Odoo, not the shared staging instance
# configured via the global ``ODOO_*`` env vars (which point at TROC staging).
# Values are overridable through ``ODOO_TEST_*`` environment variables so the
# admin/admin test credentials never need to be edited in code.
ODOO_TEST_URL = os.getenv("ODOO_TEST_URL", "http://prozac:8069")
ODOO_TEST_DATABASE = os.getenv("ODOO_TEST_DATABASE", "odoo")
ODOO_TEST_USERNAME = os.getenv("ODOO_TEST_USERNAME", "admin")
ODOO_TEST_PASSWORD = os.getenv("ODOO_TEST_PASSWORD", "admin")


BACKSTORY = """
You are an Odoo ERP specialist with full access to the company's Odoo instance.

Your capabilities include:
- Searching and reading any Odoo record (partners, products, sales orders,
  invoices, stock pickings, etc.).
- Creating and updating records: partners, quotations, invoices, payments.
- Uploading documents and binary fields (images, attachments).
- Listing available models and inspecting their field definitions.

Guidelines:
- Before writing or deleting records, confirm the operation with the user.
- When returning record lists, include the record ID and a human-readable
  identifier (name, reference, number).
- Use `odoo_search_records` with a domain filter rather than fetching all
  records — respect pagination.
- If a tool returns an Odoo error, explain the likely cause (missing fields,
  access rights, invalid domain syntax) and suggest a fix.
- Never fabricate data. If the information is unavailable, say so.
"""


@register_agent(name="odoo_agent", at_startup=True)
class OdooAgent(Agent):
    """Odoo ERP agent powered by OdooToolkit (JSON-2 / XML-RPC auto-detect)."""

    agent_id: str = "odoo_agent"
    model: str = GoogleModel.GEMINI_FLASH_LATEST

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            backstory=BACKSTORY,
            **kwargs,
        )
        self._odoo_toolkit: OdooToolkit | None = None

    def agent_tools(self):
        missing = [
            name for name, val in [
                ("ODOO_TEST_URL", ODOO_TEST_URL),
                ("ODOO_TEST_DATABASE", ODOO_TEST_DATABASE),
                ("ODOO_TEST_USERNAME", ODOO_TEST_USERNAME),
                ("ODOO_TEST_PASSWORD", ODOO_TEST_PASSWORD),
            ] if not val
        ]
        if missing:
            self.logger.warning(
                "OdooToolkit skipped — missing config: %s",
                ", ".join(missing),
            )
            return []

        # Explicit config so this agent always talks to the test instance,
        # independent of the global ODOO_* env vars (TROC staging).
        self._odoo_toolkit = OdooToolkit(
            url=ODOO_TEST_URL,
            database=ODOO_TEST_DATABASE,
            username=ODOO_TEST_USERNAME,
            password=ODOO_TEST_PASSWORD,
            verify_ssl=False,
        )
        return self._odoo_toolkit.get_tools()

    async def cleanup(self):
        """Release the Odoo transport session on shutdown."""
        if self._odoo_toolkit:
            await self._odoo_toolkit.cleanup()
        await super().cleanup()
