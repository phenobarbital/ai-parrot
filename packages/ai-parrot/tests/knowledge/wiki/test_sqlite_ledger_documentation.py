"""Smoke-test the public asynchronous cursor example published in the wiki."""
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.store import LedgerCursorInvalid, LedgerStore

MARKER = "<!-- feat902:cursor-example -->"


def _published_example() -> str:
    """Return only the python block that follows the example marker."""
    root = Path(__file__).resolve().parents[5]
    text = (root / "wiki/wiki/sqlite-ledger-concurrency.md").read_text(encoding="utf-8")
    after = text.split(MARKER, 1)[1]
    fence = after.split("```python\n", 1)[1]
    return fence.split("```", 1)[0]


@pytest.mark.asyncio
async def test_published_cursor_example(tmp_path: Path) -> None:
    """Execute the trusted repository page's example on a disposable ledger."""
    namespace: dict = {}
    exec(compile(_published_example(), "sqlite-ledger-concurrency.md", "exec"), namespace)  # noqa: S102
    read_ledger_cursor = namespace["read_ledger_cursor"]

    db_path = tmp_path / "ledger.db"
    store = LedgerStore(str(db_path))
    async with store.ledger_transaction("test.seed") as conn:
        await conn.execute("INSERT INTO ledger_state (key, value) VALUES ('cursor_offset', '42')")
        await conn.execute("INSERT INTO ledger_state (key, value) VALUES ('last_event_id', 'evt-1')")

    assert await read_ledger_cursor(db_path) == (42, "evt-1")

    async with store.ledger_transaction("test.corrupt") as conn:
        await conn.execute("DELETE FROM ledger_state WHERE key = 'last_event_id'")

    with pytest.raises(LedgerCursorInvalid):
        await read_ledger_cursor(db_path)
