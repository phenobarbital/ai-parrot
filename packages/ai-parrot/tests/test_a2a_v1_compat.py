"""Cross-version (v0.3 <-> v1.0) compatibility tests (FEAT-272 TASK-1719).

These tests are transport-free: they verify that the model layer round-trips
between the two protocol versions so a v0.3 peer and a v1.0 peer can always
understand each other's serialized payloads.
"""
from parrot.a2a.models import (
    AgentCard, AgentInterface, AgentCapabilities, AgentSkill,
    Task, TaskState, Message, Part, Role,
    parse_task_state, parse_role,
)


class TestEnumCrossVersion:
    def test_task_state_both_formats(self):
        for legacy, screaming, member in [
            ("submitted", "TASK_STATE_SUBMITTED", TaskState.SUBMITTED),
            ("completed", "TASK_STATE_COMPLETED", TaskState.COMPLETED),
            ("cancelled", "TASK_STATE_CANCELED", TaskState.CANCELED),
        ]:
            assert parse_task_state(legacy) == member
            assert parse_task_state(screaming) == member

    def test_role_both_formats(self):
        assert parse_role("user") == Role.USER
        assert parse_role("ROLE_USER") == Role.USER


class TestTaskCrossVersion:
    def test_v1_serialized_task_parsed_as_v03_values(self):
        task = Task.create()
        task.complete("done")
        v1 = task.to_dict("1.0")
        v03 = task.to_dict("0.3")
        assert v1["status"]["state"] == "TASK_STATE_COMPLETED"
        assert v03["status"]["state"] == "completed"
        # Both must parse back to the same enum member.
        assert parse_task_state(v1["status"]["state"]) == TaskState.COMPLETED
        assert parse_task_state(v03["status"]["state"]) == TaskState.COMPLETED


class TestMessageCrossVersion:
    def test_message_roundtrip_v1_to_v03(self):
        m = Message.user("hello", extensions=["x"])
        # A v1.0 producer emits ROLE_USER; a v0.3 consumer must still parse it.
        v1 = m.to_dict("1.0")
        assert v1["role"] == "ROLE_USER"
        back = Message.from_dict(v1)
        assert back.role == Role.USER
        # v0.3 output has no extensions field.
        assert "extensions" not in m.to_dict("0.3")

    def test_part_file_cross_version(self):
        p = Part(file_uri="https://x.com/f.pdf", filename="f.pdf")
        v1 = p.to_dict("1.0")
        v03 = p.to_dict("0.3")
        assert v1["url"] == "https://x.com/f.pdf"
        assert v03["file"]["fileWithUri"] == "https://x.com/f.pdf"
        # Each version's payload must deserialize back to the same file_uri.
        assert Part.from_dict(v1).file_uri == "https://x.com/f.pdf"
        assert Part.from_dict(v03).file_uri == "https://x.com/f.pdf"


class TestAgentCardCrossVersion:
    def _card(self):
        return AgentCard(
            name="A", description="d", version="1.0",
            skills=[AgentSkill(id="chat", name="Chat", description="c")],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
            capabilities=AgentCapabilities(streaming=True),
        )

    def test_v1_card_parsed_back(self):
        card = self._card()
        reparsed = AgentCard.from_dict(card.to_dict("1.0"))
        assert reparsed.url == "https://a.com/a2a"
        assert len(reparsed.supported_interfaces) == 1

    def test_v03_card_parsed_back(self):
        card = self._card()
        reparsed = AgentCard.from_dict(card.to_dict("0.3"))
        # v0.3 flat url is folded into a single supported interface.
        assert reparsed.url == "https://a.com/a2a"
        assert reparsed.preferred_transport == "JSONRPC"
