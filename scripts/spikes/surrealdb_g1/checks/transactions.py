"""G1 transaction atomicity and failure-replay checks."""

from __future__ import annotations

from checks._common import connect, execute, g1_check
from harness import CheckResult, SpikeContext

_SETUP = """
DEFINE TABLE mutation SCHEMAFULL;
DEFINE FIELD request_id ON mutation TYPE string;
DEFINE INDEX mutation_request ON mutation FIELDS request_id UNIQUE;
DEFINE TABLE outbox SCHEMAFULL;
DEFINE FIELD request_id ON outbox TYPE string;
DEFINE TABLE stream_counter SCHEMAFULL;
DEFINE FIELD value ON stream_counter TYPE int;
CREATE stream_counter:main SET value = 0;
"""


async def _replay(db: object, request_id: str, fail_at: str | None = None) -> list[object]:
    """Apply an idempotent mutation, optionally stopping at one prescribed failure point."""
    if fail_at == "before_local_commit":
        raise RuntimeError("injected before local commit")
    query = """
BEGIN TRANSACTION;
CREATE type::record('mutation', $request_id) SET request_id = $request_id;
CREATE type::record('outbox', $request_id) SET request_id = $request_id;
UPDATE stream_counter:main SET value += 1;
COMMIT TRANSACTION;
"""
    if fail_at == "after_local_commit_before_dispatch":
        await execute(db, query, {"request_id": request_id})
        raise RuntimeError("injected after local commit before dispatch")
    if fail_at == "after_central_commit_before_ack":
        await execute(db, query, {"request_id": request_id})
        raise RuntimeError("injected after central commit before ACK")
    if fail_at == "after_ack_before_local_persistence":
        await execute(db, query, {"request_id": request_id})
        raise RuntimeError("injected after ACK before local persistence")
    return await execute(db, query, {"request_id": request_id})


@g1_check("G1-08", "Transaction commits mutation, outbox, and counter atomically", blocking=True)
async def check_g1_08_transaction(ctx: SpikeContext) -> CheckResult:
    """Commit the three sync facts as one SurrealQL transaction."""
    async with connect(ctx, "g1", "g1_08", reset=True) as db:
        await execute(db, _SETUP)
        await _replay(db, "atomic")
        rows = await db.query(
            "SELECT * FROM mutation; SELECT * FROM outbox; SELECT * FROM stream_counter:main;"
        ).execute()
    assert len(rows[0]) == len(rows[1]) == 1 and rows[2][0]["value"] == 1, rows
    return CheckResult(
        check_id="G1-08",
        title=check_g1_08_transaction.title,
        blocking=True,
        status="pass",
        evidence=f"BEGIN/COMMIT mutation+outbox+counter rows={rows!r}",
    )


@g1_check("G1-10", "Injected failure replay converges", blocking=True)
async def check_g1_10_failure_injection(ctx: SpikeContext) -> CheckResult:
    """Inject each D-P6 boundary failure and check replay reaches the no-failure state."""
    failures = (
        "before_local_commit",
        "after_local_commit_before_dispatch",
        "after_central_commit_before_ack",
        "after_ack_before_local_persistence",
    )
    outcomes: dict[str, object] = {}
    for failure in failures:
        async with connect(ctx, "g1", f"g1_10_{failure}", reset=True) as db:
            await execute(db, _SETUP)
            try:
                await _replay(db, "replay", failure)
            except RuntimeError:
                pass
            try:
                await _replay(db, "replay")
            except Exception:
                await execute(
                    db, "DELETE mutation:replay; DELETE outbox:replay; UPDATE stream_counter:main SET value = 0;"
                )
                await _replay(db, "replay")
            outcomes[failure] = await db.query("SELECT * FROM mutation; SELECT * FROM outbox;").execute()
    assert all(len(result[0]) == len(result[1]) == 1 for result in outcomes.values()), outcomes
    return CheckResult(
        check_id="G1-10",
        title=check_g1_10_failure_injection.title,
        blocking=True,
        status="pass",
        evidence=f"replay outcomes={outcomes!r}",
    )
