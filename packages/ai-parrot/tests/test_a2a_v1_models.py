"""Unit tests for A2A v1.0 data models (FEAT-272 TASK-1712 / TASK-1713)."""
import pytest
from parrot.a2a.models import (
    TaskState, Role, Part, Message, Artifact, Task, TaskStatus,
    AgentSkill, AgentCapabilities, AgentInterface, AgentProvider,
    SendMessageConfiguration, TaskPushNotificationConfig,
    AuthenticationInfo, A2AError, AgentCard,
    parse_task_state, parse_role,
    serialize_task_state, serialize_role,
)


class TestTaskStateV1:
    def test_v1_values(self):
        assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
        assert TaskState.AUTH_REQUIRED.value == "TASK_STATE_AUTH_REQUIRED"
        assert TaskState.UNSPECIFIED.value == "TASK_STATE_UNSPECIFIED"

    def test_cancelled_alias(self):
        assert TaskState.CANCELLED is TaskState.CANCELED
        assert TaskState.CANCELED.value == "TASK_STATE_CANCELED"

    def test_compat_parse(self):
        assert parse_task_state("submitted") == TaskState.SUBMITTED
        assert parse_task_state("TASK_STATE_SUBMITTED") == TaskState.SUBMITTED
        assert parse_task_state("cancelled") == TaskState.CANCELED
        assert parse_task_state("TASK_STATE_CANCELED") == TaskState.CANCELED
        assert parse_task_state(TaskState.WORKING) == TaskState.WORKING

    def test_serialize_versions(self):
        assert serialize_task_state(TaskState.SUBMITTED, "1.0") == "TASK_STATE_SUBMITTED"
        assert serialize_task_state(TaskState.SUBMITTED, "0.3") == "submitted"
        assert serialize_task_state(TaskState.CANCELED, "0.3") == "cancelled"


class TestRoleV1:
    def test_v1_values(self):
        assert Role.USER.value == "ROLE_USER"
        assert Role.AGENT.value == "ROLE_AGENT"
        assert Role.UNSPECIFIED.value == "ROLE_UNSPECIFIED"

    def test_compat_parse(self):
        assert parse_role("user") == Role.USER
        assert parse_role("ROLE_USER") == Role.USER

    def test_serialize_versions(self):
        assert serialize_role(Role.USER, "1.0") == "ROLE_USER"
        assert serialize_role(Role.USER, "0.3") == "user"


class TestPartV1:
    def test_to_dict_v1_text(self):
        p = Part(text="hello")
        d = p.to_dict(version="1.0")
        assert d["text"] == "hello"
        assert d["kind"] == "text"

    def test_to_dict_v1_file(self):
        p = Part(file_uri="https://example.com/f.pdf", file_media_type="application/pdf")
        d = p.to_dict(version="1.0")
        assert "url" in d
        assert d["url"] == "https://example.com/f.pdf"

    def test_to_dict_v03_file(self):
        p = Part(file_uri="https://example.com/f.pdf")
        d = p.to_dict(version="0.3")
        assert d["file"]["fileWithUri"] == "https://example.com/f.pdf"

    def test_from_dict_v03_compat(self):
        d = {"kind": "file", "file": {"fileWithUri": "https://x.com/f.pdf"}}
        p = Part.from_dict(d)
        assert p.file_uri == "https://x.com/f.pdf"

    def test_from_dict_v1_compat(self):
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

    def test_role_v1_serialization(self):
        m = Message.user("hello")
        assert m.to_dict(version="1.0")["role"] == "ROLE_USER"
        assert m.to_dict(version="0.3")["role"] == "user"

    def test_from_dict_roundtrip(self):
        m = Message.from_dict({"role": "ROLE_USER", "parts": [{"kind": "text", "text": "hi"}]})
        assert m.role == Role.USER
        assert m.get_text() == "hi"


class TestTaskStatusTaskV1:
    def test_task_status_versions(self):
        st = TaskStatus(state=TaskState.COMPLETED)
        assert st.to_dict("1.0")["state"] == "TASK_STATE_COMPLETED"
        assert st.to_dict("0.3")["state"] == "completed"

    def test_task_versions(self):
        t = Task.create()
        t.complete("done")
        assert t.to_dict("1.0")["status"]["state"] == "TASK_STATE_COMPLETED"
        assert t.to_dict("0.3")["status"]["state"] == "completed"


class TestAgentCapabilitiesV1:
    def test_extended_agent_card(self):
        c = AgentCapabilities(extended_agent_card=True)
        d = c.to_dict()
        assert d["extendedAgentCard"] is True

    def test_no_state_transition_history(self):
        c = AgentCapabilities()
        d = c.to_dict()
        assert "stateTransitionHistory" not in d


class TestAgentSkillV1:
    def test_input_output_modes(self):
        s = AgentSkill(id="x", name="X", description="d",
                       input_modes=["text/plain"], output_modes=["application/json"])
        d = s.to_dict(version="1.0")
        assert d["inputModes"] == ["text/plain"]
        assert d["outputModes"] == ["application/json"]

    def test_v03_omits_v1_fields(self):
        s = AgentSkill(id="x", name="X", description="d", input_modes=["text/plain"])
        d = s.to_dict(version="0.3")
        assert "inputModes" not in d


class TestNewModelTypes:
    def test_agent_interface_roundtrip(self):
        ai = AgentInterface(url="https://a.com", protocol_binding="JSONRPC", protocol_version="1.0")
        d = ai.to_dict()
        assert d["protocolBinding"] == "JSONRPC"
        assert AgentInterface.from_dict(d).url == "https://a.com"

    def test_agent_provider(self):
        p = AgentProvider(url="https://x.com", organization="Acme")
        assert p.to_dict()["organization"] == "Acme"

    def test_send_message_configuration(self):
        cfg = SendMessageConfiguration.from_dict({"historyLength": 5, "returnImmediately": True})
        assert cfg.history_length == 5
        assert cfg.return_immediately is True

    def test_push_config(self):
        cfg = TaskPushNotificationConfig(id="c1", task_id="t1", url="https://x.com/hook")
        d = cfg.to_dict()
        assert d["taskId"] == "t1"
        assert TaskPushNotificationConfig.from_dict(d).id == "c1"

    def test_authentication_info(self):
        a = AuthenticationInfo(scheme="Bearer", credentials="tok")
        assert a.to_dict()["scheme"] == "Bearer"

    def test_a2a_error(self):
        e = A2AError(code=-32001, message="not found")
        assert e.to_dict()["code"] == -32001


class TestBackwardCompatImports:
    def test_agent_card_still_flat(self):
        card = AgentCard(name="T", description="d", version="1.0", skills=[], url="https://a.com")
        d = card.to_dict()
        assert d["url"] == "https://a.com"
