"""Unit tests for artifact and thread Pydantic models (TASK-717)."""

import pytest
from datetime import datetime

from parrot.storage.models import (
    ArtifactType,
    ArtifactCreator,
    ArtifactSummary,
    Artifact,
    ThreadMetadata,
    CanvasBlockType,
    CanvasBlock,
    CanvasDefinition,
    # Verify existing models still importable
    ChatMessage,
    Conversation,
    MessageRole,
)


class TestArtifactTypeEnum:
    """Tests for ArtifactType enum."""

    def test_chart_value(self):
        assert ArtifactType.CHART == "chart"

    def test_canvas_value(self):
        assert ArtifactType.CANVAS == "canvas"

    def test_infographic_value(self):
        assert ArtifactType.INFOGRAPHIC == "infographic"

    def test_dataframe_value(self):
        assert ArtifactType.DATAFRAME == "dataframe"

    def test_export_value(self):
        assert ArtifactType.EXPORT == "export"

    def test_str_enum_json_serializable(self):
        """ArtifactType inherits from str so it serializes as its value."""
        import json
        result = json.dumps({"type": ArtifactType.CHART})
        assert '"chart"' in result


class TestArtifactCreatorEnum:
    """Tests for ArtifactCreator enum."""

    def test_user_value(self):
        assert ArtifactCreator.USER == "user"

    def test_agent_value(self):
        assert ArtifactCreator.AGENT == "agent"

    def test_system_value(self):
        assert ArtifactCreator.SYSTEM == "system"


class TestArtifactSummary:
    """Tests for ArtifactSummary model."""

    def test_creation(self):
        summary = ArtifactSummary(
            id="chart-x1",
            type=ArtifactType.CHART,
            title="Revenue Chart",
            created_at=datetime(2025, 1, 1, 12, 0),
        )
        assert summary.id == "chart-x1"
        assert summary.type == ArtifactType.CHART
        assert summary.updated_at is None

    def test_roundtrip(self):
        now = datetime(2025, 4, 16, 10, 30)
        summary = ArtifactSummary(
            id="canvas-main",
            type=ArtifactType.CANVAS,
            title="Main Canvas",
            created_at=now,
            updated_at=now,
        )
        data = summary.model_dump()
        restored = ArtifactSummary.model_validate(data)
        assert restored.id == summary.id
        assert restored.type == summary.type
        assert restored.updated_at == now


class TestArtifact:
    """Tests for Artifact model."""

    def test_artifact_roundtrip(self):
        now = datetime(2025, 4, 16, 10, 30)
        artifact = Artifact(
            artifact_id="chart-x1",
            artifact_type=ArtifactType.CHART,
            title="Test Chart",
            created_at=now,
            updated_at=now,
            definition={"engine": "echarts", "spec": {}},
        )
        data = artifact.model_dump()
        restored = Artifact.model_validate(data)
        assert restored.artifact_id == "chart-x1"
        assert restored.artifact_type == ArtifactType.CHART
        assert restored.definition == {"engine": "echarts", "spec": {}}
        assert restored.definition_ref is None

    def test_artifact_with_s3_ref(self):
        now = datetime(2025, 4, 16, 10, 30)
        artifact = Artifact(
            artifact_id="infog-r1",
            artifact_type=ArtifactType.INFOGRAPHIC,
            title="Big Infographic",
            created_at=now,
            updated_at=now,
            definition=None,
            definition_ref="s3://parrot-artifacts/USER#u1/sess/infog.json",
        )
        assert artifact.definition is None
        assert artifact.definition_ref is not None
        assert artifact.definition_ref.startswith("s3://")

    def test_artifact_with_source_turn(self):
        now = datetime(2025, 4, 16, 10, 30)
        artifact = Artifact(
            artifact_id="df-1",
            artifact_type=ArtifactType.DATAFRAME,
            title="Sales Data",
            created_at=now,
            updated_at=now,
            source_turn_id="turn-001",
            created_by=ArtifactCreator.AGENT,
            definition={"columns": ["date", "revenue"], "rows": []},
        )
        assert artifact.source_turn_id == "turn-001"
        assert artifact.created_by == ArtifactCreator.AGENT

    def test_artifact_default_creator(self):
        now = datetime(2025, 4, 16, 10, 30)
        artifact = Artifact(
            artifact_id="x",
            artifact_type=ArtifactType.EXPORT,
            title="Export",
            created_at=now,
            updated_at=now,
        )
        assert artifact.created_by == ArtifactCreator.USER

    def test_artifact_model_dump_serializable(self):
        """model_dump() produces a JSON-serializable dict."""
        import json
        now = datetime(2025, 4, 16, 10, 30)
        artifact = Artifact(
            artifact_id="chart-x1",
            artifact_type=ArtifactType.CHART,
            title="Chart",
            created_at=now,
            updated_at=now,
            definition={"engine": "echarts"},
        )
        data = artifact.model_dump(mode="json")
        # Should not raise
        json_str = json.dumps(data)
        assert "chart-x1" in json_str


class TestThreadMetadata:
    """Tests for ThreadMetadata model."""

    def test_basic_creation(self):
        now = datetime(2025, 4, 16, 10, 30)
        meta = ThreadMetadata(
            session_id="sess-abc",
            user_id="u123",
            agent_id="sales-bot",
            title="Test Thread",
            created_at=now,
            updated_at=now,
        )
        data = meta.model_dump()
        assert data["session_id"] == "sess-abc"
        assert data["turn_count"] == 0
        assert data["pinned"] is False
        assert data["archived"] is False
        assert data["tags"] == []

    def test_roundtrip(self):
        now = datetime(2025, 4, 16, 10, 30)
        meta = ThreadMetadata(
            session_id="sess-xyz",
            user_id="u456",
            agent_id="finance-bot",
            title="Q4 Analysis",
            created_at=now,
            updated_at=now,
            turn_count=15,
            pinned=True,
            tags=["finance", "q4"],
        )
        data = meta.model_dump()
        restored = ThreadMetadata.model_validate(data)
        assert restored.session_id == "sess-xyz"
        assert restored.turn_count == 15
        assert restored.pinned is True
        assert restored.tags == ["finance", "q4"]

    def test_optional_title(self):
        now = datetime(2025, 4, 16, 10, 30)
        meta = ThreadMetadata(
            session_id="s1",
            user_id="u1",
            agent_id="bot1",
            created_at=now,
            updated_at=now,
        )
        assert meta.title is None


class TestCanvasBlockType:
    """Tests for CanvasBlockType enum."""

    def test_all_values(self):
        expected = {
            "markdown", "heading", "chart_ref", "data_table",
            "agent_response", "infographic_ref", "note",
            "code", "image", "divider",
        }
        actual = {member.value for member in CanvasBlockType}
        assert actual == expected


class TestCanvasBlock:
    """Tests for CanvasBlock model."""

    def test_markdown_block(self):
        block = CanvasBlock(
            block_id="b1",
            block_type=CanvasBlockType.MARKDOWN,
            content="# Hello World",
            position=0,
        )
        assert block.block_type == CanvasBlockType.MARKDOWN
        assert block.content == "# Hello World"
        assert block.artifact_ref is None

    def test_chart_ref_block(self):
        block = CanvasBlock(
            block_id="b2",
            block_type=CanvasBlockType.CHART_REF,
            artifact_ref="chart-x1",
            position=1,
        )
        assert block.artifact_ref == "chart-x1"
        assert block.content is None

    def test_default_position(self):
        block = CanvasBlock(block_id="b3", block_type=CanvasBlockType.DIVIDER)
        assert block.position == 0


class TestCanvasDefinition:
    """Tests for CanvasDefinition model."""

    def test_roundtrip(self):
        canvas = CanvasDefinition(
            tab_id="main",
            title="Main",
            blocks=[
                CanvasBlock(
                    block_id="b1",
                    block_type=CanvasBlockType.MARKDOWN,
                    content="# Hello",
                ),
                CanvasBlock(
                    block_id="b2",
                    block_type=CanvasBlockType.CHART_REF,
                    artifact_ref="chart-x1",
                ),
            ],
        )
        data = canvas.model_dump()
        restored = CanvasDefinition.model_validate(data)
        assert len(restored.blocks) == 2
        assert restored.blocks[0].block_type == CanvasBlockType.MARKDOWN
        assert restored.blocks[1].artifact_ref == "chart-x1"
        assert restored.layout == "vertical"

    def test_empty_blocks(self):
        canvas = CanvasDefinition(tab_id="empty", title="Empty Canvas")
        assert canvas.blocks == []

    def test_export_config(self):
        canvas = CanvasDefinition(
            tab_id="report",
            title="Report",
            export_config={"format": "pdf", "orientation": "landscape"},
        )
        assert canvas.export_config["format"] == "pdf"

    def test_as_artifact_definition(self):
        """CanvasDefinition can be used as Artifact.definition via model_dump."""
        now = datetime(2025, 4, 16, 10, 30)
        canvas = CanvasDefinition(
            tab_id="main",
            title="Main",
            blocks=[
                CanvasBlock(
                    block_id="blk-1",
                    block_type=CanvasBlockType.MARKDOWN,
                    content="## Title",
                ),
                CanvasBlock(
                    block_id="blk-2",
                    block_type=CanvasBlockType.CHART_REF,
                    artifact_ref="chart-x1",
                ),
            ],
        )
        artifact = Artifact(
            artifact_id="canvas-main",
            artifact_type=ArtifactType.CANVAS,
            title="Main",
            created_at=now,
            updated_at=now,
            created_by=ArtifactCreator.USER,
            definition=canvas.model_dump(),
        )
        assert artifact.definition["tab_id"] == "main"
        assert len(artifact.definition["blocks"]) == 2


class TestExistingModelsUnchanged:
    """Verify existing dataclass models still work after adding Pydantic models."""

    def test_message_role_enum(self):
        assert MessageRole.USER == "user"
        assert MessageRole.ASSISTANT == "assistant"

    def test_chat_message_roundtrip(self):
        msg = ChatMessage(
            message_id="m1",
            session_id="s1",
            user_id="u1",
            agent_id="bot1",
            role="user",
            content="Hello",
        )
        data = msg.to_dict()
        restored = ChatMessage.from_dict(data)
        assert restored.message_id == "m1"
        assert restored.content == "Hello"

    def test_conversation_roundtrip(self):
        conv = Conversation(
            session_id="s1",
            user_id="u1",
            agent_id="bot1",
            title="Test",
        )
        data = conv.to_dict()
        restored = Conversation.from_dict(data)
        assert restored.session_id == "s1"
        assert restored.title == "Test"
