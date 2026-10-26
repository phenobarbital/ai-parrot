"""Gate L-S5 — single writer with compare-and-set versions (FEAT-747 AC-9)."""

import asyncio

import pytest

from parrot.roost import InMemoryBlackboard, WriterPolicy
from parrot.roost.blackboard import StaleWriteError, WriterDeniedError
from parrot.roost.messages import RoostMessage


@pytest.mark.asyncio
async def test_concurrent_stale_writers_exactly_one_lands() -> None:
    """Two concurrent writes on the same version: one lands, one is refused; one inform per subscriber."""
    blackboard = InMemoryBlackboard(scope="channel", policy=WriterPolicy(coordinator="coordinator"))
    await blackboard.put("digest", {"v": 0}, writer="coordinator", expected_version=None)
    seen: dict[str, list[RoostMessage]] = {"alice": [], "bob": []}

    def _collector(name: str):
        async def collect(msg: RoostMessage) -> None:
            seen[name].append(msg)

        return collect

    for name in seen:
        await blackboard.subscribe("digest", _collector(name), subscriber_name=name)

    results = await asyncio.gather(
        blackboard.put("digest", {"v": "a"}, writer="coordinator", expected_version=1),
        blackboard.put("digest", {"v": "b"}, writer="coordinator", expected_version=1),
        return_exceptions=True,
    )

    landed = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, StaleWriteError)]
    assert len(landed) == 1 and len(refused) == 1
    assert landed[0].version == 2
    current = await blackboard.get("digest", reader="alice")
    assert current is landed[0]
    for name, messages in seen.items():
        assert len(messages) == 1, name
        assert messages[0].content is landed[0]


@pytest.mark.asyncio
async def test_non_owner_write_denied() -> None:
    """A second writer that is not the key owner is refused outright."""
    blackboard = InMemoryBlackboard(scope="channel", policy=WriterPolicy(coordinator="coordinator"))
    await blackboard.put("digest", {"v": 0}, writer="coordinator", expected_version=None)
    with pytest.raises(WriterDeniedError):
        await blackboard.put("digest", {"v": 1}, writer="intruder", expected_version=1)
