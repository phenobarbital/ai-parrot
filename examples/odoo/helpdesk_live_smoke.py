"""Live smoke for OdooHelpdeskToolkit against a REAL Odoo (opt-in: ODOO_HELPDESK_LIVE=1).

Replays the FEAT-616 staging verification: create → take → close → note → public comment → reassign → mass update →
SLA policy → stats → merge, and DELETES every record it created. Never run under pytest.
"""

from __future__ import annotations

import asyncio
import os
import sys

from parrot.interfaces.odoointerface import OdooError
from parrot_tools.odoo import OdooHelpdeskToolkit


async def main() -> int:
    if os.environ.get("ODOO_HELPDESK_LIVE") != "1":
        print("skipped: set ODOO_HELPDESK_LIVE=1 (and ODOO_HELPDESK_*) to run against a real instance")
        return 0
    tk = OdooHelpdeskToolkit()
    created: list[tuple[str, int]] = []
    try:
        stages = await tk.list_helpdesk_stages()
        print("stages:", [i.name for i in stages.items])

        # Create first ticket
        t1 = await tk.create_ticket(
            subject="[FEAT-616 smoke] ticket 1", partner_email="smoke@example.invalid", partner_name="FEAT-616 smoke"
        )
        created.append(("sh.helpdesk.ticket", t1.ticket.id))
        print(f"Created ticket 1: {t1.ticket.id}")

        # Take the ticket
        taken = await tk.take_ticket(ticket_id=t1.ticket.id)
        print(f"Taken ticket: {taken.applied}")

        # Close the ticket
        closed = await tk.close_ticket(ticket_id=t1.ticket.id)
        print(f"Closed ticket: {closed.applied}")

        # Add internal comment (should not reopen)
        internal_comment = await tk.add_ticket_comment(
            ticket_id=t1.ticket.id, content="Internal note - should not reopen", internal=True
        )
        print(f"Added internal comment: {internal_comment.success}")

        # Add public comment (should reopen if setting enabled)
        public_comment = await tk.add_ticket_comment(
            ticket_id=t1.ticket.id, content="Public comment - may reopen ticket", internal=False
        )
        print(f"Added public comment: {public_comment.success}")

        # Reopen the ticket
        reopened = await tk.reopen_ticket(ticket_id=t1.ticket.id)
        print(f"Reopened ticket: {reopened.applied} (method: {reopened.method_used})")

        # Create second ticket
        t2 = await tk.create_ticket(
            subject="[FEAT-616 smoke] ticket 2", partner_email="smoke2@example.invalid", partner_name="FEAT-616 smoke 2"
        )
        created.append(("sh.helpdesk.ticket", t2.ticket.id))
        print(f"Created ticket 2: {t2.ticket.id}")

        # Mass update tickets
        teams = await tk.list_helpdesk_teams()
        if teams.items:
            team_name = teams.items[0].name
            mass_update = await tk.mass_update_tickets(
                ticket_ids=[t1.ticket.id, t2.ticket.id], stage="Open", team=team_name
            )
            print(f"Mass updated tickets: {mass_update.updated_count}")

        # Create SLA policy
        if teams.items:
            sla_policy = await tk.create_sla_policy(
                name="[FEAT-616 smoke] SLA Policy", team=teams.items[0].name, hours=1, stage="Closed"
            )
            created.append(("sh.helpdesk.sla", sla_policy.policy_id))
            print(f"Created SLA policy: {sla_policy.policy_id}")

            # Check SLA status
            sla_status = await tk.get_ticket_sla_status(ticket_id=t1.ticket.id)
            print(f"SLA status: {sla_status.status}")

        # Get ticket stats
        stats = await tk.ticket_stats()
        print(f"Ticket stats: total={stats.total_tickets}, open={stats.open_tickets}")

        # Merge tickets
        merge_result = await tk.merge_tickets(ticket_ids=[t2.ticket.id], into_ticket_id=t1.ticket.id)
        print(f"Merged tickets: {merge_result.merged_count}")

        return 0
    except OdooError as exc:
        print("FAILED:", exc)
        return 1
    finally:
        for model, rid in reversed(created):
            try:
                await tk.delete_record(model=model, record_id=rid)
                print("deleted", model, rid)
            except OdooError as exc:  # keep going — leave nothing behind
                print("!! could not delete", model, rid, exc)
        await tk.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
