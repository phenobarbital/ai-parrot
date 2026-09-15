"""Offline pre-merge reproductions; no repository implementation changes."""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd() / "packages/ai-parrot-tools/tests"))
from contracts.test_ingest_delta import FakeDeltaTool, FROZEN_NOW, page, principal_context
from contracts.test_retrieval import FakeCatalog, make_card
from parrot.knowledge.contracts.models import SourceItem
from parrot.knowledge.contracts.graph_loader import GraphPublicationReport
from parrot_tools.contracts.jobs import ingest_delta, SourceConfig

SOURCE = "sharepoint://legal"


async def setup():
    catalog = FakeCatalog()
    await catalog.upsert(make_card("acme-msa"))
    await catalog.set_delta_token(SOURCE, "old-cursor")
    await catalog.upsert_source_item(
        SourceItem(
            source=SOURCE,
            drive_id="drive-1",
            item_id="a",
            current_uri="https://example.test/a",
            contract_id="acme-msa",
            last_seen_at=FROZEN_NOW,
        )
    )
    return catalog


async def main():
    catalog = await setup()

    class Graph:
        async def retract(self, contract_id):
            return GraphPublicationReport(published=False, errors=["Arango unavailable"])

    result = await ingest_delta(
        library=SimpleNamespace(catalog=catalog),
        delta_tool=FakeDeltaTool([page([], reset_performed=True)]),
        source=SourceConfig(source=SOURCE, drive_id="drive-1"),
        principal=principal_context(),
        graph_loader=Graph(),
        now=lambda: FROZEN_NOW + timedelta(seconds=1),
    )
    print(
        "graph_failure",
        {
            "errors": result.errors,
            "cursor_committed": result.cursor_committed,
            "deleted": (await catalog.get_source_item("drive-1", "a")).deleted,
        },
    )

    catalog = await setup()
    original = catalog.list_source_items
    concurrent = []

    async def overlapping_read(source=None):
        rows = await original(source)
        if source is not None and not concurrent:
            newer = rows[0].model_copy(update={"last_seen_at": FROZEN_NOW + timedelta(seconds=2)})
            await catalog.upsert_source_item(newer)
            concurrent.append(newer.last_seen_at.isoformat())
        return rows

    catalog.list_source_items = overlapping_read
    result = await ingest_delta(
        library=SimpleNamespace(catalog=catalog),
        delta_tool=FakeDeltaTool([page([], reset_performed=True)]),
        source=SourceConfig(source=SOURCE, drive_id="drive-1"),
        principal=principal_context(),
        now=lambda: FROZEN_NOW + timedelta(seconds=1),
    )
    print(
        "concurrent_update",
        {
            "newer_observation": concurrent,
            "reconciled": result.reconciled,
            "active": (await catalog.get("acme-msa")).active,
            "cursor_committed": result.cursor_committed,
        },
    )


asyncio.run(main())
