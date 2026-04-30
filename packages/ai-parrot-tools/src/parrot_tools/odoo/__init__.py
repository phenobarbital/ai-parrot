"""Odoo Toolkit for AI-Parrot.

Exposes Odoo ERP CRUD + business helpers (partner / sales / invoicing /
binary uploads) as agent tools, with auto-detected JSON-RPC (Odoo 19+) or
XML-RPC (14-18) transport.

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
