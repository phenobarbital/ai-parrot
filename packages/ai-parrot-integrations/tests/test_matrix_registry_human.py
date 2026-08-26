"""Tests for MatrixCrewRegistry.is_human — FEAT-463 TASK-2484."""
import pytest

from parrot.integrations.matrix.crew.registry import MatrixAgentCard, MatrixCrewRegistry

pytestmark = pytest.mark.asyncio


async def test_is_human():
    r = MatrixCrewRegistry()
    r.set_human_patterns([r"^@signal_"])
    r.set_bot_mxid("@parrot:s")
    await r.register(MatrixAgentCard(agent_name="a", display_name="A", mxid="@parrot-a:s"))
    assert r.is_human("@signal_1:s") and r.is_human("@bob:s")
    assert not r.is_human("@parrot-a:s") and not r.is_human("@parrot:s")
