"""Unit tests for the Adaptive Card renderer (FEAT-303, TASK-1752)."""
import pytest

from parrot.integrations.msagentsdk.cards import (
    CardRenderError,
    build_card_attachment,
    render_card,
    render_text,
)
from parrot.integrations.msagentsdk.semantic import (
    DetailPayload,
    MetricsPayload,
    SemanticUIResult,
    StatusPayload,
    TablePayload,
    UIAction,
    UIField,
    UIMetric,
)

ALLOWED_ELEMENTS = {"TextBlock", "ColumnSet", "Column", "FactSet", "Container"}
ALLOWED_ACTIONS = {"Action.Submit", "Action.OpenUrl"}


def _walk_types(node):
    """Yield every `type` value found anywhere in the card tree."""
    if isinstance(node, dict):
        if "type" in node:
            yield node["type"]
        for value in node.values():
            yield from _walk_types(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_types(item)


@pytest.fixture
def table_result() -> SemanticUIResult:
    return SemanticUIResult(
        title="Orders",
        payload=TablePayload(
            result_type="table",
            columns=["id", "total"],
            rows=[[str(i), f"${i * 10}"] for i in range(1, 21)],
            total_rows=20,
        ),
    )


class TestRenderCard:
    def test_render_table_card(self, table_result):
        card = render_card(table_result)
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.4"

    def test_render_metrics_card(self):
        result = SemanticUIResult(
            title="KPIs",
            payload=MetricsPayload(
                result_type="metrics",
                metrics=[UIMetric(label="Revenue", value="$1,000", delta="+5%")],
            ),
        )
        card = render_card(result)
        facts = [b for b in card["body"] if b["type"] == "FactSet"]
        assert facts
        assert facts[0]["facts"][0]["value"] == "$1,000 (+5%)"

    def test_render_detail_card(self):
        result = SemanticUIResult(
            title="Order #1",
            payload=DetailPayload(
                result_type="detail", fields=[UIField(label="Status", value="Shipped")]
            ),
        )
        card = render_card(result)
        facts = [b for b in card["body"] if b["type"] == "FactSet"]
        assert facts
        assert facts[0]["facts"][0] == {"title": "Status", "value": "Shipped"}

    def test_render_status_card_levels(self):
        for level in ("success", "warning", "error", "info"):
            result = SemanticUIResult(
                title="Result",
                payload=StatusPayload(
                    result_type="status", level=level, message="msg"
                ),
            )
            card = render_card(result)
            assert card["type"] == "AdaptiveCard"

    def test_only_allowed_elements(self, table_result):
        card = render_card(table_result)
        found = set(_walk_types(card))
        assert found <= ALLOWED_ELEMENTS | ALLOWED_ACTIONS | {"AdaptiveCard"}
        assert card["version"] == "1.4"

    def test_table_truncation(self, table_result):
        card = render_card(table_result, max_table_rows=15)
        note_blocks = [
            b
            for b in card["body"]
            if b.get("type") == "TextBlock" and "Showing" in b.get("text", "")
        ]
        assert note_blocks
        assert "Showing 15 of 20" in note_blocks[0]["text"]

    def test_no_truncation_note_when_under_cap(self):
        result = SemanticUIResult(
            title="Small",
            payload=TablePayload(
                result_type="table", columns=["a"], rows=[["1"], ["2"]]
            ),
        )
        card = render_card(result, max_table_rows=15)
        note_blocks = [
            b
            for b in card["body"]
            if b.get("type") == "TextBlock" and "Showing" in b.get("text", "")
        ]
        assert not note_blocks

    def test_card_size_guard(self, table_result):
        with pytest.raises(CardRenderError):
            render_card(table_result, max_card_bytes=50)

    def test_empty_table_renders_no_results(self):
        result = SemanticUIResult(
            title="Empty",
            payload=TablePayload(result_type="table", columns=[], rows=[]),
        )
        card = render_card(result)
        containers = [b for b in card["body"] if b["type"] == "Container"]
        assert containers
        assert "No results" in containers[0]["items"][0]["text"]


class TestActions:
    def test_prompt_action_messageback_payload(self):
        result = SemanticUIResult(
            title="t",
            payload=StatusPayload(result_type="status", level="info", message="m"),
            actions=[
                UIAction(
                    title="Details",
                    prompt_template="Show details for {id}",
                    params={"id": "42"},
                )
            ],
        )
        card = render_card(result)
        action = card["actions"][0]
        assert action["type"] == "Action.Submit"
        assert action["data"]["msteams"]["type"] == "messageBack"
        assert action["data"]["msteams"]["text"] == "Show details for 42"
        assert action["data"]["feat303_prompt"] == "Show details for 42"

    def test_url_action_openurl(self):
        result = SemanticUIResult(
            title="t",
            payload=StatusPayload(result_type="status", level="info", message="m"),
            actions=[UIAction(title="Open", url="https://example.com")],
        )
        card = render_card(result)
        action = card["actions"][0]
        assert action == {
            "type": "Action.OpenUrl",
            "title": "Open",
            "url": "https://example.com",
        }

    def test_missing_param_does_not_raise(self):
        result = SemanticUIResult(
            title="t",
            payload=StatusPayload(result_type="status", level="info", message="m"),
            actions=[
                UIAction(title="Details", prompt_template="Show {id}", params={})
            ],
        )
        card = render_card(result)
        assert card["actions"][0]["data"]["feat303_prompt"] == "Show {id}"


class TestRenderText:
    @pytest.mark.parametrize(
        "result",
        [
            SemanticUIResult(
                title="Table",
                payload=TablePayload(result_type="table", columns=[], rows=[]),
            ),
            SemanticUIResult(
                title="Metrics",
                payload=MetricsPayload(result_type="metrics", metrics=[]),
            ),
            SemanticUIResult(
                title="Detail",
                payload=DetailPayload(result_type="detail", fields=[]),
            ),
            SemanticUIResult(
                title="Status",
                payload=StatusPayload(
                    result_type="status", level="error", message="boom"
                ),
            ),
        ],
    )
    def test_render_text_total(self, result):
        assert isinstance(render_text(result), str)


def test_build_card_attachment():
    att = build_card_attachment({"type": "AdaptiveCard"})
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["content"] == {"type": "AdaptiveCard"}
