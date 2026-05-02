"""Odoo Toolkit for AI-Parrot.

Exposes Odoo ERP CRUD + business helpers (partner / sales / invoicing /
binary uploads) as agent tools, with auto-detected JSON-2 (Odoo 19+) or
XML-RPC (14-18) transport. Legacy JSON-RPC remains available explicitly for
compatibility.

Usage:
    from parrot_tools.odoo import OdooToolkit

    toolkit = OdooToolkit(
        url="https://my.odoo.com",
        database="prod",
        username="alice@acme.com",
        password="...",
        protocol="auto",
    )
    tools = toolkit.get_tools()
"""

from .toolkit import (
    OdooAuthenticationError,
    OdooConnectionError,
    OdooError,
    OdooRPCError,
    OdooToolkit,
)

__all__ = [
    "OdooToolkit",
    "OdooError",
    "OdooAuthenticationError",
    "OdooConnectionError",
    "OdooRPCError",
]
