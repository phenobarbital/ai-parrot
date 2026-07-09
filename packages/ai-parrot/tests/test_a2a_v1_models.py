"""Unit tests for A2A Protocol v1.0.0 data models (FEAT-272 / TASK-1712, TASK-1713).

Covers:
    - TaskState / Role v1.0.0 enum values + backward-compat parsing (TASK-1712)
    - Part / Message v1.0.0 field renames and additions (TASK-1712)
    - AgentCapabilities v1.0.0 restructuring (TASK-1712)
    - AgentCard v1.0.0 `supportedInterfaces` structure (TASK-1713)
"""
from parrot.a2a.models import (
    TaskState,
    Role,
    Part,
    Message,
    Artifact,
    Task,
    TaskStatus,
    AgentSkill,
    AgentCapabilities,
    AgentInterface,
    AgentProvider,
    SendMessageConfiguration,
    TaskPushNotificationConfig,
    AuthenticationInfo,
    A2AError,
    parse_task_state,
    parse_role,
)


class TestTaskStateV1:
    def test_v1_values(self):
        assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
        assert TaskState.AUTH_REQUIRED.value == "TASK_STATE_AUTH_REQUIRED"

    def test_unspecified_member_exists(self):
        assert TaskState.UNSPECIFIED.value == "TASK_STATE_UNSPECIFIED"

    def test_cancelled_alias(self):
        assert TaskState.CANCELLED is TaskState.CANCELED

    def test_compat_parse(self):
        assert parse_task_state("submitted") == TaskState.SUBMITTED
        assert parse_task_state("TASK_STATE_SUBMITTED") == TaskState.SUBMITTED
        assert parse_task_state("cancelled") == TaskState.CANCELED
        assert parse_task_state("TASK_STATE_CANCELED") == TaskState.CANCELED


class TestRoleV1:
    def test_v1_values(self):
        assert Role.USER.value == "ROLE_USER"
        assert Role.UNSPECIFIED.value == "ROLE_UNSPECIFIED"

    def test_compat_parse(self):
        assert parse_role("user") == Role.USER
        assert parse_role("ROLE_USER") == Role.USER


class TestPartV1:
    def test_to_dict_v1_text(self):
        p = Part(text="hello")
        d = p.to_dict(version="1.0")
        assert d["text"] == "hello"

    def test_to_dict_v1_file(self):
        p = Part(file_uri="https://example.com/f.pdf", file_media_type="application/pdf")
        d = p.to_dict(version="1.0")
        assert "url" in d
        assert "raw" not in d

    def test_to_dict_v03_file_still_nested(self):
        p = Part(file_uri="https://example.com/f.pdf")
        d = p.to_dict(version="0.3")
        assert d["file"]["fileWithUri"] == "https://example.com/f.pdf"

    def test_from_dict_v03_compat(self):
        d = {"kind": "file", "file": {"fileWithUri": "https://x.com/f.pdf"}}
        p = Part.from_dict(d)
        assert p.file_uri == "https://x.com/f.pdf"

    def test_from_dict_v1_flat(self):
        d = {"kind": "file", "url": "https://x.com/f.pdf"}
        p = Part.from_dict(d)
        assert p.file_uri == "https://x.com/f.pdf"

    def test_filename_field(self):
        p = Part(text="hello", filename="doc.txt")
        d = p.to_dict(version="1.0")
        assert d.get("filename") == "doc.txt"


class TestMessageV1:
    def test_extensions_field(self):
        m = Message.user("hello", extensions=["ext1"])
        d = m.to_dict(version="1.0")
        assert d["extensions"] == ["ext1"]

    def test_reference_task_ids(self):
        m = Message.user("hello", reference_task_ids=["task-1"])
        d = m.to_dict(version="1.0")
        assert d["referenceTaskIds"] == ["task-1"]

    def test_v1_role_serialization(self):
        m = Message.user("hello")
        d = m.to_dict(version="1.0")
        assert d["role"] == "ROLE_USER"

    def test_v03_role_serialization(self):
        m = Message.user("hello")
        d = m.to_dict(version="0.3")
        assert d["role"] == "user"

    def test_from_dict_roundtrip(self):
        m = Message.user("hello")
        d = m.to_dict(version="1.0")
        m2 = Message.from_dict(d)
        assert m2.role == Role.USER
        assert m2.get_text() == "hello"


class TestTaskStatusV1:
    def test_v1_state_serialization(self):
        status = TaskStatus(state=TaskState.COMPLETED)
        d = status.to_dict(version="1.0")
        assert d["state"] == "TASK_STATE_COMPLETED"

    def test_v03_state_serialization(self):
        status = TaskStatus(state=TaskState.COMPLETED)
        d = status.to_dict(version="0.3")
        assert d["state"] == "completed"

    def test_v03_canceled_serializes_double_l(self):
        status = TaskStatus(state=TaskState.CANCELED)
        d = status.to_dict(version="0.3")
        assert d["state"] == "cancelled"


class TestTaskV1:
    def test_task_to_dict_v1_default(self):
        task = Task.create()
        d = task.to_dict()
        assert d["status"]["state"] == "TASK_STATE_SUBMITTED"

    def test_task_to_dict_v03(self):
        task = Task.create()
        d = task.to_dict(version="0.3")
        assert d["status"]["state"] == "submitted"


class TestArtifactV1:
    def test_artifact_to_dict_versions(self):
        art = Artifact(artifact_id="a1", parts=[Part(text="hi")])
        d1 = art.to_dict(version="1.0")
        d03 = art.to_dict(version="0.3")
        assert d1["parts"][0]["text"] == "hi"
        assert d03["parts"][0]["text"] == "hi"


class TestAgentCapabilitiesV1:
    def test_extended_agent_card(self):
        c = AgentCapabilities(extended_agent_card=True)
        d = c.to_dict()
        assert d["extendedAgentCard"] is True

    def test_no_state_transition_history(self):
        c = AgentCapabilities()
        d = c.to_dict()
        assert "stateTransitionHistory" not in d

    def test_from_dict_roundtrip(self):
        c = AgentCapabilities(streaming=False, push_notifications=True, extended_agent_card=True)
        d = c.to_dict()
        c2 = AgentCapabilities.from_dict(d)
        assert c2.streaming is False
        assert c2.push_notifications is True
        assert c2.extended_agent_card is True


class TestAgentSkillV1:
    def test_input_output_modes(self):
        skill = AgentSkill(
            id="s1", name="Skill", description="d",
            input_modes=["text/plain"], output_modes=["text/plain"],
        )
        d = skill.to_dict()
        assert d["inputModes"] == ["text/plain"]
        assert d["outputModes"] == ["text/plain"]

    def test_from_dict_roundtrip(self):
        d = {
            "id": "s1", "name": "Skill", "description": "d",
            "inputModes": ["text/plain"], "outputModes": ["text/plain"],
        }
        skill = AgentSkill.from_dict(d)
        assert skill.input_modes == ["text/plain"]
        assert skill.output_modes == ["text/plain"]


class TestNewV1Dataclasses:
    def test_agent_interface_roundtrip(self):
        iface = AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC", protocol_version="1.0")
        d = iface.to_dict()
        iface2 = AgentInterface.from_dict(d)
        assert iface2.url == "https://a.com/a2a"
        assert iface2.protocol_binding == "JSONRPC"

    def test_agent_provider(self):
        provider = AgentProvider(url="https://example.com", organization="Acme")
        d = provider.to_dict()
        assert d["organization"] == "Acme"

    def test_send_message_configuration(self):
        cfg = SendMessageConfiguration(history_length=5, return_immediately=True)
        d = cfg.to_dict()
        assert d["historyLength"] == 5
        assert d["returnImmediately"] is True

    def test_task_push_notification_config(self):
        cfg = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook",
            authentication=AuthenticationInfo(scheme="Bearer", credentials="tok"),
        )
        d = cfg.to_dict()
        assert d["url"] == "https://example.com/hook"
        assert d["authentication"]["scheme"] == "Bearer"
        cfg2 = TaskPushNotificationConfig.from_dict(d)
        assert cfg2.id == "cfg-1"
        assert cfg2.authentication.credentials == "tok"

    def test_a2a_error(self):
        err = A2AError(code=-32001, message="Task not found")
        d = err.to_dict()
        assert d["code"] == -32001


# NOTE: AgentCard v1.0 `supportedInterfaces` restructuring tests are added by
# TASK-1713 (AgentCard v1.0 Structure) in a follow-up edit to this same file.
