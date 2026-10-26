"""Unit tests for Roost's message vocabulary and local envelope."""
import importlib
import sys

import pytest

from parrot.roost.messages import AgentAddress, EnvelopeLike, RoostMessage
from parrot.roost.performatives import OBLIGATIONS, InteractionProtocol, Performative


def test_obligations_table_complete() -> None:
    """Every speech act has its specified reply obligation."""
    assert set(OBLIGATIONS) == set(Performative)
    assert OBLIGATIONS[Performative.INFORM].owed is False
    assert Performative.AGREE in OBLIGATIONS[Performative.REQUEST].allowed_replies


def test_reply_threads_conversation_and_preserves_content_identity(envelope: object) -> None:
    """Replies retain the conversation context and native content object."""
    request = RoostMessage(
        performative=Performative.REQUEST,
        protocol=InteractionProtocol.REQUEST,
        conversation_id="c1",
        sender=AgentAddress(name="a"),
        receivers=[AgentAddress(name="b")],
        envelope=envelope,
    )
    content = object()
    reply = request.reply(Performative.AGREE, content=content)
    assert reply.in_reply_to == request.message_id
    assert reply.sender.name == "b"
    assert reply.receivers[0].name == "a"
    assert reply.content is content


def test_reply_rejects_disallowed_act(envelope: object) -> None:
    """An inform cannot be answered with another inform."""
    inform = RoostMessage(
        performative=Performative.INFORM,
        protocol=InteractionProtocol.INFORM,
        conversation_id="c",
        sender=AgentAddress(name="a"),
        receivers=[AgentAddress(name="b")],
        envelope=envelope,
    )
    with pytest.raises(ValueError):
        inform.reply(Performative.INFORM)


def test_envelope_like(envelope: object) -> None:
    """The local fallback envelope is structurally compatible."""
    assert isinstance(envelope, EnvelopeLike)


def test_message_requires_receiver_or_capability_filter() -> None:
    """Broadcast messages require an explicit capability filter."""
    with pytest.raises(ValueError, match="receivers or capability_filter"):
        RoostMessage(
            performative=Performative.INFORM,
            protocol=InteractionProtocol.INFORM,
            conversation_id="c",
            sender=AgentAddress(name="a"),
        )


def test_package_import_is_lazy() -> None:
    """Importing the package alone does not load a Roost submodule."""
    for module_name in [name for name in sys.modules if name.startswith("parrot.roost")]:
        del sys.modules[module_name]
    importlib.import_module("parrot.roost")
    assert "parrot.roost.messages" not in sys.modules
