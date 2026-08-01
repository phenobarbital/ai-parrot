"""Tests for parrot.bots.flows.core.checkpoint.serializer (TASK-2047).

Validates the FlowStateSerializer type registry + ormsgpack hybrid
serialization: registered Pydantic models round-trip with type identity,
unregistered objects degrade to a lossy tagged repr, and exceptions
encode as structured dicts.
"""
from datetime import UTC

import pytest
from parrot.bots.flows.core.checkpoint import FlowStateSerializer
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from pydantic import BaseModel


@pytest.fixture
def serializer() -> FlowStateSerializer:
    return FlowStateSerializer()


@pytest.fixture
def sample_ai_message() -> AIMessage:
    return AIMessage(
        input="hello",
        output="world",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(),
    )


class Weird:
    """An arbitrary, unregistered class used to exercise lossy degradation."""

    def __repr__(self) -> str:
        return "Weird(marker=1)"


def test_registered_pydantic_roundtrip(serializer, sample_ai_message):
    data, lossy = serializer.encode_with_meta({"n1": sample_ai_message})
    assert not lossy

    out = serializer.decode(data)
    assert isinstance(out["n1"], AIMessage)
    assert out["n1"].input == "hello"
    assert out["n1"].output == "world"
    assert out["n1"].model == "test-model"


def test_unregistered_pydantic_model_degrades_lossy(serializer):
    class UnregisteredModel(BaseModel):
        value: int = 1

    data, lossy = serializer.encode_with_meta({"n1": UnregisteredModel()})
    assert lossy
    out = serializer.decode(data)
    assert "UnregisteredModel" in out["n1"]


def test_unregistered_degrades_lossy(serializer):
    data, lossy = serializer.encode_with_meta({"n1": Weird()})
    assert lossy
    out = serializer.decode(data)
    assert "Weird" in str(out["n1"])


def test_exception_structured(serializer):
    exc = ValueError("boom")
    data, lossy = serializer.encode_with_meta({"err": exc})
    assert not lossy  # structured error encoding is not "lossy"

    out = serializer.decode(data)
    assert out["err"]["type"] == "ValueError"
    assert out["err"]["message"] == "boom"
    assert "ValueError" in out["err"]["repr"]


def test_encode_error_helper():
    exc = RuntimeError("oops")
    encoded = FlowStateSerializer.encode_error(exc)
    assert encoded == {
        "type": "RuntimeError",
        "message": "oops",
        "repr": repr(exc),
    }


def test_primitives_and_nested_structures_roundtrip(serializer):
    payload = {
        "a": 1,
        "b": "text",
        "c": [1, 2, {"d": True}],
        "e": None,
        "f": {"nested": {"deep": 3.14}},
    }
    data, lossy = serializer.encode_with_meta(payload)
    assert not lossy
    out = serializer.decode(data)
    assert out == payload


def test_register_custom_model_roundtrips(serializer):
    class CustomModel(BaseModel):
        name: str

    tag = serializer.register(CustomModel)
    assert tag == f"{CustomModel.__module__}.{CustomModel.__qualname__}"

    data, lossy = serializer.encode_with_meta({"n1": CustomModel(name="x")})
    assert not lossy
    out = serializer.decode(data)
    assert isinstance(out["n1"], CustomModel)
    assert out["n1"].name == "x"


def test_decode_unknown_tag_returns_raw_envelope(serializer):
    # Simulate a payload encoded with a tag this serializer instance
    # never registered — decode must not attempt to import/reconstruct it.
    import ormsgpack

    packed = ormsgpack.packb({"__type__": "some.unknown.Type", "data": {"x": 1}})
    out = serializer.decode(packed)
    assert out["__type__"] == "some.unknown.Type"
    assert out["data"] == {"x": 1}


def test_datetime_roundtrips_as_real_datetime_not_flagged_lossy(serializer):
    """Regression test (code review finding, FEAT-399): ormsgpack.unpackb()
    does not restore datetime objects on its own (it returns a plain
    string) — the serializer must explicitly tag datetimes so decode()
    reconstructs the original type, and this must NOT be reported as
    lossy since no information is actually lost."""
    from datetime import datetime

    dt = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    data, lossy = serializer.encode_with_meta({"ts": dt})
    assert not lossy

    out = serializer.decode(data)
    assert isinstance(out["ts"], datetime)
    assert out["ts"] == dt


def test_uuid_roundtrips_as_real_uuid_not_flagged_lossy(serializer):
    import uuid

    value = uuid.uuid4()
    data, lossy = serializer.encode_with_meta({"id": value})
    assert not lossy

    out = serializer.decode(data)
    assert isinstance(out["id"], uuid.UUID)
    assert out["id"] == value


def test_dict_colliding_with_type_sentinel_key_roundtrips_unchanged(serializer):
    """Regression test (code review finding, FEAT-399): a plain dict whose
    own keys happen to collide with the reserved "__type__" sentinel
    (e.g. a tool result that itself uses a "__type__" discriminator field)
    must round-trip as the exact original dict, not be misinterpreted as
    one of the serializer's own tag envelopes."""
    colliding = {"__type__": "lossy", "__repr__": "not actually lossy", "value": 42}
    data, lossy = serializer.encode_with_meta({"result": colliding})
    assert not lossy

    out = serializer.decode(data)
    assert out["result"] == colliding


def test_dict_colliding_with_registered_model_tag_roundtrips_unchanged(serializer):
    """A dict that happens to carry a registered model's own tag string
    under "__type__" must still round-trip as a plain dict, not be
    misinterpreted as an encoded instance of that model."""
    from parrot.models.responses import AIMessage

    fake_tag = f"{AIMessage.__module__}.{AIMessage.__qualname__}"
    colliding = {"__type__": fake_tag, "data": {"not": "a real AIMessage"}}

    data, lossy = serializer.encode_with_meta({"payload": colliding})
    assert not lossy

    out = serializer.decode(data)
    assert out["payload"] == colliding
    assert not isinstance(out["payload"], AIMessage)
