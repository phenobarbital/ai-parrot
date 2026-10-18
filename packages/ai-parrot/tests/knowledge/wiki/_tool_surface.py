"""Frozen wiki MCP tool inventories shared by the surface tests (FEAT-700).

Owned here so that adding a tool updates ONE place; every test asserting
the local stdio surface imports ``LOCAL_NO_LEDGER`` from this module.
"""

from __future__ import annotations

LOCAL_NO_LEDGER: list[str] = sorted(
    [
        "wiki_query",
        "wiki_page",
        "wiki_related",
        "wiki_remember",
        "wiki_note",
        "wiki_status",
        "wiki_symbol_lookup",
        "wiki_code_outline",
        "wiki_blast_radius",
        "wiki_decision_why",
        "wiki_decisions_for_symbol",
        "wiki_lint",
        "wiki_standup",
    ]
)
LEDGER: list[str] = sorted(
    ["ledger_open", "ledger_ready", "ledger_claim", "ledger_close", "ledger_context", "ledger_list", "ledger_show"]
)
BULK: list[str] = sorted(["wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"])
