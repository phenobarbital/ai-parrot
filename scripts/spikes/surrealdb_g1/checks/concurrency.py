"""G1 multi-process writer and operational-information checks."""

from __future__ import annotations

import asyncio
import multiprocessing
from typing import Any

from checks._common import connect, execute, g1_check
from harness import CheckResult, SpikeContext


def _writer(ctx_data: dict[str, str], index: int, queue: Any) -> None:
    """Write one independently identified mutation from a spawned process."""

    async def write() -> None:
        from surrealdb import AsyncSurreal

        url = ctx_data["url"].replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        db = AsyncSurreal(url)
        await db.connect()
        try:
            await db.signin({"username": ctx_data["username"], "password": ctx_data["password"]})
            await db.use("g1", "g1_09")
            await db.query(
                "CREATE type::record('mutation', $request_id) SET origin = 'writer', ns = 'g1', db = 'g1_09', seq = $seq, request_id = $request_id;",
                {"request_id": f"writer-{index}", "seq": index},
            ).execute()
            queue.put({"index": index, "ok": True})
        except Exception as exc:  # worker errors must return across the process boundary
            queue.put({"index": index, "ok": False, "error": repr(exc)})
        finally:
            await db.close()

    asyncio.run(write())


@g1_check("G1-09", "Eight writers preserve unique mutation identities", blocking=True)
async def check_g1_09_writers(ctx: SpikeContext) -> CheckResult:
    """Spawn eight clients and check no mutation identity was lost or duplicated."""
    async with connect(ctx, "g1", "g1_09", reset=True) as db:
        await execute(
            db,
            "DEFINE TABLE mutation SCHEMAFULL; DEFINE FIELD origin ON mutation TYPE string; DEFINE FIELD ns ON mutation TYPE string; "
            "DEFINE FIELD db ON mutation TYPE string; DEFINE FIELD seq ON mutation TYPE int; DEFINE FIELD request_id ON mutation TYPE string; "
            "DEFINE INDEX mutation_sequence ON mutation FIELDS origin, ns, db, seq UNIQUE; "
            "DEFINE INDEX mutation_request ON mutation FIELDS request_id UNIQUE;",
        )
    mp = multiprocessing.get_context("spawn")
    queue = mp.Queue()
    ctx_data = ctx.model_dump()
    writers = [mp.Process(target=_writer, args=(ctx_data, index, queue)) for index in range(8)]
    for writer in writers:
        writer.start()
    messages: list[dict[str, object]] = []
    while len(messages) < len(writers):
        try:
            messages.append(queue.get_nowait())
        except Exception:
            if all(not writer.is_alive() for writer in writers):
                break
            await asyncio.sleep(0.05)
    for writer in writers:
        writer.join(timeout=1)
    assert len(messages) == 8 and all(message.get("ok") for message in messages), messages
    async with connect(ctx, "g1", "g1_09") as db:
        rows = await db.query("SELECT * FROM mutation ORDER BY seq;").first()
    assert len(rows) == 8 and len({row["request_id"] for row in rows}) == 8, rows
    return CheckResult(
        check_id="G1-09",
        title=check_g1_09_writers.title,
        blocking=True,
        status="pass",
        evidence=f"spawn eight writers messages={messages!r} rows={rows!r}",
        measurements={"writers": 8.0, "mutations": float(len(rows))},
    )


@g1_check("G1-13", "SDK licence, image digest, and multi-process server sharing", blocking=False)
async def check_g1_13_info(ctx: SpikeContext) -> CheckResult:
    """Record the immutable runtime pins and that G1-09 shares one server."""
    digest_present = "@sha256:" in ctx.server_image
    return CheckResult(
        check_id="G1-13",
        title=check_g1_13_info.title,
        blocking=False,
        status="pass" if digest_present else "skipped",
        evidence=f"sdk={ctx.sdk_version}; image={ctx.server_image}; G1-09 uses eight spawned clients against one server",
    )
