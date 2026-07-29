"""Unit tests for the Semantic UI Model (FEAT-303, TASK-1751)."""
import pytest
from pydantic import ValidationError

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


class TestPayloadValidation:
    def test_table_payload_valid(self):
        r = SemanticUIResult(
            title="Orders",
            payload=TablePayload(
                result_type="table",
                columns=["id", "total"],
                rows=[["1", "$10"]],
                total_rows=1,
            ),
        )
        assert r.payload.result_type == "table"

    def test_metrics_detail_status_valid(self):
        metrics_result = SemanticUIResult(
            title="KPIs",
            payload=MetricsPayload(
                result_type="metrics",
                metrics=[UIMetric(label="Revenue", value="$1,000", delta="+5%")],
            ),
        )
        assert metrics_result.payload.result_type == "metrics"

        detail_result = SemanticUIResult(
            title="Order #1",
            payload=DetailPayload(
                result_type="detail",
                fields=[UIField(label="Status", value="Shipped")],
            ),
        )
        assert detail_result.payload.result_type == "detail"

        status_result = SemanticUIResult(
            title="Result",
            payload=StatusPayload(
                result_type="status", level="success", message="Done"
            ),
        )
        assert status_result.payload.result_type == "status"

    def test_unknown_result_type_rejected(self):
        with pytest.raises(ValidationError):
            SemanticUIResult.model_validate(
                {"title": "x", "payload": {"result_type": "chart", "data": []}}
            )

    def test_discriminator_routes_from_dict(self):
        r = SemanticUIResult.model_validate(
            {
                "title": "s",
                "payload": {
                    "result_type": "status",
                    "level": "error",
                    "message": "boom",
                },
            }
        )
        assert isinstance(r.payload, StatusPayload)


class TestUIAction:
    def test_prompt_action_valid(self):
        UIAction(
            title="Details",
            prompt_template="Show details for {id}",
            params={"id": "42"},
        )

    def test_url_action_valid(self):
        UIAction(title="Open", url="https://example.com")

    def test_both_rejected(self):
        with pytest.raises(ValidationError):
            UIAction(title="x", prompt_template="p", url="https://e.com")

    def test_neither_rejected(self):
        with pytest.raises(ValidationError):
            UIAction(title="x")


def test_roundtrip_model_dump_validate():
    r = SemanticUIResult(
        title="t",
        payload=DetailPayload(
            result_type="detail", fields=[UIField(label="a", value="b")]
        ),
    )
    assert SemanticUIResult.model_validate(r.model_dump()) == r
