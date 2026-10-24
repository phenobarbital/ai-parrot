"""FEAT-734 — FormDesignerTurn isolation."""

import asyncio
import uuid

import pytest

from parrot.integrations.msteams.formdesigner_turn import FormDesignerTurn, active_turn, bind_turn


async def test_enqueue_dedupes_in_order():
    """enqueue returns True for new items, False when closed, and dedupes."""
    turn = FormDesignerTurn(conversation_id="conv-1")
    uid1 = uuid.uuid4()
    uid2 = uuid.uuid4()
    uid3 = uuid.uuid4()
    uid4 = uid1  # Duplicate of uid1
    assert turn.enqueue(uid1) is True
    assert turn.enqueue(uid2) is True
    assert turn.enqueue(uid3) is True
    assert turn.enqueue(uid4) is True
    # First three are unique, fourth is a duplicate
    assert len(turn.pending) == 3
    # drain() is called by bind_turn in finally, so queue is empty after


async def test_closed_turn_refuses_enqueue():
    """After close(), enqueue returns False."""
    turn = FormDesignerTurn(conversation_id="conv-1")
    turn.close()
    assert turn.enqueue(uuid.uuid4()) is False


async def test_bind_turn_resets_on_exception():
    """After bind_turn exits by exception, active_turn() is None and bearer cleared."""
    turn = FormDesignerTurn(conversation_id="conv-1", bearer="secret")
    with pytest.raises(RuntimeError):
        async with bind_turn(turn):
            raise RuntimeError("test")
    assert active_turn() is None
    assert turn.bearer is None


async def test_concurrent_turns_are_isolated():
    """Two concurrent tasks each bind their own turn; queues never mix."""
    turn1 = FormDesignerTurn(conversation_id="conv-1")
    turn2 = FormDesignerTurn(conversation_id="conv-2")
    results = []

    async def task1():
        async with bind_turn(turn1):
            results.append(("task1", turn1.enqueue(uuid.uuid4())))
            results.append(("task1", turn1.enqueue(uuid.uuid4())))

    async def task2():
        async with bind_turn(turn2):
            results.append(("task2", turn2.enqueue(uuid.uuid4())))
            results.append(("task2", turn2.enqueue(uuid.uuid4())))

    await asyncio.gather(task1(), task2())
    assert len(results) == 4
    assert results[0] == ("task1", True)
    assert results[1] == ("task1", True)
    assert results[2] == ("task2", True)
    assert results[3] == ("task2", True)
    # drain() is called by bind_turn in finally, so queues are empty after
    assert turn1.drain() == []
    assert turn2.drain() == []


async def test_late_task_sees_no_active_turn():
    """Task created inside, awaited after exit -> active_turn() None."""
    turn = FormDesignerTurn(conversation_id="conv-1")
    async with bind_turn(turn):
        task = asyncio.create_task(asyncio.sleep(0.01))
        await task
    assert active_turn() is None


async def test_cancellation_closes_turn():
    """Cancellation during bind_turn closes the turn and resets the ContextVar."""
    turn = FormDesignerTurn(conversation_id="conv-1", bearer="secret")
    async with bind_turn(turn):
        task = asyncio.create_task(asyncio.sleep(0.01))
        await asyncio.sleep(0.005)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert active_turn() is None
    assert turn.bearer is None
    assert turn.closed
