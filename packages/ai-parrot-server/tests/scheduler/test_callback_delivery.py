"""FEAT-635 M1 — scheduler callbacks report the real delivery status."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from parrot.scheduler.functions import (
    SaveDataCallback,
    SendEmailReportCallback,
    SendNotifyReportCallback,
)

ERROR = {"status": "error", "provider": "email", "error": "smtp down"}
SUCCESS = {"status": "success", "provider": "email"}


async def test_send_email_report_failed_status():
    cb = SendEmailReportCallback(config={"recipients": ["a@example.com"]})
    with patch.object(SendEmailReportCallback, "send_email", new=AsyncMock(return_value=ERROR)):
        out = await cb.run("report body", schedule_id="s1", agent_name="agent")
    assert out["status"] == "failed"
    assert out["error"] == "smtp down"


async def test_send_email_report_sent_status():
    cb = SendEmailReportCallback(config={"recipients": ["a@example.com"]})
    with patch.object(SendEmailReportCallback, "send_email", new=AsyncMock(return_value=SUCCESS)):
        out = await cb.run("report body", schedule_id="s1", agent_name="agent")
    assert out["status"] == "sent"
    assert out["error"] is None


async def test_send_notify_report_failed_status():
    cb = SendNotifyReportCallback(config={"recipients": ["x"]})
    with patch.object(SendNotifyReportCallback, "send_notification", new=AsyncMock(return_value=ERROR)):
        out = await cb.run("report body", schedule_id="s1", agent_name="agent")
    assert out["status"] == "failed"
    assert out["error"] == "smtp down"


async def test_saving_data_email_failure_is_partial(tmp_path):
    cb = SaveDataCallback(config={"output_dir": str(tmp_path), "email_to": ["a@example.com"]})
    result = SimpleNamespace(data=[{"a": 1}], response="x")
    with patch.object(SaveDataCallback, "send_email", new=AsyncMock(return_value=ERROR)):
        out = await cb.run(result, schedule_id="s1", agent_name="agent")
    assert out["status"] == "partial"
    assert out["email_status"] == "failed"
    assert (tmp_path / "agent_s1.csv").exists()


async def test_saving_data_without_email_is_saved(tmp_path):
    cb = SaveDataCallback(config={"output_dir": str(tmp_path)})
    result = SimpleNamespace(data=[{"a": 1}], response="x")
    out = await cb.run(result, schedule_id="s1", agent_name="agent")
    assert out["status"] == "saved"
    assert "email_status" not in out


def test_delivery_result_none_response_failed():
    out = SendEmailReportCallback(config={})._delivery_result(None, provider="email")
    assert out["status"] == "failed"
    assert out["error"]
