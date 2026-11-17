"""G1-01 WebSocket connection and reconnect check."""

from __future__ import annotations

from checks._common import connect, g1_check
from harness import CheckResult, SpikeContext


@g1_check("G1-01", "AsyncSurreal connects, authenticates, and reconnects over WebSocket", blocking=True)
async def check_g1_01_connect(ctx: SpikeContext) -> CheckResult:
    """Connect twice and verify the selected database in each fresh session."""
    query = "RETURN [session::ns(), session::db()];"
    async with connect(ctx, "g1", "g1_01") as db:
        first = await db.query(query).first()
    async with connect(ctx, "g1", "g1_01") as db:
        second = await db.query(query).first()
    expected = ["g1", "g1_01"]
    assert first == expected and second == expected, (first, second)
    return CheckResult(
        check_id="G1-01",
        title=check_g1_01_connect.title,
        blocking=True,
        status="pass",
        evidence=f"{query} first={first!r}; reconnect={second!r}",
    )
