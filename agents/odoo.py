from parrot.bots import Agent
from parrot.registry import register_agent
from parrot_tools.odoo import OdooToolkit
from parrot.models.google import GoogleModel
from parrot.conf import (
    ODOO_URL,
    ODOO_DATABASE,
    ODOO_USERNAME,
    ODOO_PASSWORD,
)


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
                ("ODOO_URL", ODOO_URL),
                ("ODOO_DATABASE", ODOO_DATABASE),
                ("ODOO_USERNAME", ODOO_USERNAME),
                ("ODOO_PASSWORD", ODOO_PASSWORD),
            ] if not val
        ]
        if missing:
            self.logger.warning(
                "OdooToolkit skipped — missing env vars: %s",
                ", ".join(missing),
            )
            return []

        self._odoo_toolkit = OdooToolkit()
        return self._odoo_toolkit.get_tools()

    async def cleanup(self):
        """Release the Odoo transport session on shutdown."""
        if self._odoo_toolkit:
            await self._odoo_toolkit.cleanup()
        await super().cleanup()
