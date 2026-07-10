"""Cross-version (v0.3 ⇄ v1.0.0) model-layer compatibility tests for A2A.

Ported from the parallel ``feat-272`` implementation's ``test_a2a_v1_compat.py``
to widen the ``feat-FEAT-272`` model-layer coverage. These exercise the public
model API only (``AgentCard`` / ``AgentInterface`` / ``Part`` / ``TaskState`` /
``Role`` + ``parse_task_state`` / ``parse_role``) — no ``A2AServer`` import — so
they verify that a value built in one protocol version round-trips faithfully
through the other wire format.
"""
from parrot.a2a.models import (
    AgentCard,
    AgentInterface,
    Part,
    TaskState,
    Role,
    parse_task_state,
    parse_role,
)


class TestAgentCardCrossVersion:
    """A card built as v1.0 must serialize/deserialize correctly as v0.3, and
    vice versa — the two shapes describe the same agent.
    """

    def test_v1_card_roundtrips_through_v03_wire_format(self):
        card = AgentCard(
            name="Agent", description="D", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(
                    url="https://a.com/a2a",
                    protocol_binding="JSONRPC",
                    protocol_version="1.0",
                )
            ],
        )
        v03_wire = card.to_dict(version="0.3")
        reparsed = AgentCard.from_dict(v03_wire)
        assert reparsed.url == "https://a.com/a2a"
        assert reparsed.preferred_transport == "JSONRPC"

    def test_v03_card_roundtrips_through_v1_wire_format(self):
        v03_wire = {
            "name": "Agent", "description": "D", "version": "1.0",
            "url": "https://b.com/a2a", "preferredTransport": "JSONRPC",
            "protocolVersion": "0.3.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }
        card = AgentCard.from_dict(v03_wire)
        v1_wire = card.to_dict(version="1.0")
        assert v1_wire["supportedInterfaces"][0]["url"] == "https://b.com/a2a"

        reparsed = AgentCard.from_dict(v1_wire)
        assert reparsed.url == "https://b.com/a2a"


class TestTaskStateCrossVersion:
    def test_all_task_states_parse_both_formats(self):
        pairs = [
            ("submitted", "TASK_STATE_SUBMITTED", TaskState.SUBMITTED),
            ("working", "TASK_STATE_WORKING", TaskState.WORKING),
            ("completed", "TASK_STATE_COMPLETED", TaskState.COMPLETED),
            ("failed", "TASK_STATE_FAILED", TaskState.FAILED),
            ("cancelled", "TASK_STATE_CANCELED", TaskState.CANCELED),
            ("input_required", "TASK_STATE_INPUT_REQUIRED", TaskState.INPUT_REQUIRED),
            ("rejected", "TASK_STATE_REJECTED", TaskState.REJECTED),
        ]
        for v03_value, v1_value, expected in pairs:
            assert parse_task_state(v03_value) == expected
            assert parse_task_state(v1_value) == expected

    def test_auth_required_only_exists_in_v1(self):
        # AUTH_REQUIRED is new in v1.0 — no v0.3 equivalent existed.
        assert parse_task_state("TASK_STATE_AUTH_REQUIRED") == TaskState.AUTH_REQUIRED

    def test_cancelled_double_l_alias_is_same_member_as_canceled(self):
        assert TaskState.CANCELLED is TaskState.CANCELED
        assert TaskState.CANCELLED.value == "TASK_STATE_CANCELED"


class TestRoleCrossVersion:
    def test_all_roles_parse_both_formats(self):
        assert parse_role("user") == Role.USER
        assert parse_role("ROLE_USER") == Role.USER
        assert parse_role("agent") == Role.AGENT
        assert parse_role("ROLE_AGENT") == Role.AGENT


class TestPartCrossVersion:
    def test_file_part_roundtrips_v03_to_v1(self):
        part = Part(file_uri="https://x.com/f.pdf", file_media_type="application/pdf")
        v03 = part.to_dict(version="0.3")
        reparsed = Part.from_dict(v03)
        v1 = reparsed.to_dict(version="1.0")
        assert v1["url"] == "https://x.com/f.pdf"
        assert v1["mediaType"] == "application/pdf"

    def test_file_part_roundtrips_v1_to_v03(self):
        part = Part(file_uri="https://y.com/f.pdf")
        v1 = part.to_dict(version="1.0")
        reparsed = Part.from_dict(v1)
        v03 = reparsed.to_dict(version="0.3")
        assert v03["file"]["fileWithUri"] == "https://y.com/f.pdf"
