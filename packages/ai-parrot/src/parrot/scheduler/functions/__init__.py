from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import pandas as pd
from navconfig.logging import logging

from ...models.responses import AIMessage
from ...notifications import NotificationMixin


class BaseSchedulerCallback(NotificationMixin):
    """Base class for scheduler callbacks executed after successful jobs."""

    callback_name = "base"
    description = "Base scheduler callback"

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None) -> None:
        self.config = config or {}
        self.logger = logger or logging.getLogger("Parrot.Scheduler.Callback")

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        return {
            "name": cls.callback_name,
            "description": cls.description,
        }

    def process_output(self, result: Any) -> Dict[str, Any]:
        """Normalize an AIMessage-like response into text, markdown and data."""
        files = [Path(f) for f in getattr(result, "files", []) or []]
        text = ""
        markdown = ""
        data = getattr(result, "data", None)

        if isinstance(result, AIMessage):
            text = result.response or ""
            markdown = text
            if data is None:
                data = result.data
        else:
            text = getattr(result, "response", None) or getattr(result, "output", None) or str(result)
            markdown = str(text)

        if not text and isinstance(result, AIMessage):
            text = result.response or str(result.output)
            markdown = text

        return {
            "text": text or "",
            "markdown": markdown or text or "",
            "data": data,
            "files": files,
            "result": result,
        }

    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    async def __call__(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        return await self.run(result, schedule_id=schedule_id, agent_name=agent_name, **kwargs)


class SendEmailReportCallback(BaseSchedulerCallback):
    callback_name = "send_email_report"
    description = "Send the result as markdown or PDF to one or more email recipients."

    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        payload = self.process_output(result)
        recipients = self.config.get("recipients") or self.config.get("email") or self.config.get("to")
        if not recipients:
            raise ValueError("send_email_report requires recipients")
        markdown = payload["markdown"]
        attachments = list(payload["files"])
        if self.config.get("as_pdf"):
            pdf_path = self._markdown_to_pdf(markdown, schedule_id)
            attachments.append(pdf_path)
        elif markdown:
            md_path = self._write_temp_file(markdown, suffix=".md", prefix=f"{schedule_id}_")
            attachments.append(md_path)
        response = await self.send_email(
            message=self.config.get("message", markdown or payload["text"]),
            recipients=recipients,
            subject=self.config.get("subject", f"Scheduler report for {agent_name}"),
            attachments=attachments,
            with_attachments=True,
        )
        return {"status": "sent", "provider": "email", "attachments": [str(p) for p in attachments], "response": response}

    def _write_temp_file(self, content: str, *, suffix: str, prefix: str) -> Path:
        fd, filename = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        path = Path(filename)
        with os.fdopen(fd, "w", encoding="utf-8") as handler:
            handler.write(content)
        return path

    def _markdown_to_pdf(self, markdown: str, schedule_id: str) -> Path:
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise ImportError(
                "PDF generation requires weasyprint. "
                "Install with: uv pip install 'ai-parrot[pdf]'"
            ) from exc
        html_body = f"<html><body><pre>{markdown}</pre></body></html>"
        fd, filename = tempfile.mkstemp(suffix=".pdf", prefix=f"{schedule_id}_")
        Path(filename).unlink(missing_ok=True)
        HTML(string=html_body).write_pdf(filename)
        return Path(filename)


class CreateFileCallback(BaseSchedulerCallback):
    callback_name = "create_file"
    description = "Persist the agent output as a markdown file."

    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        payload = self.process_output(result)
        output_dir = Path(self.config.get("output_dir", tempfile.gettempdir()))
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = self.config.get("filename", f"{agent_name}_{schedule_id}.md")
        destination = output_dir / filename
        destination.write_text(payload["markdown"], encoding="utf-8")
        return {"status": "saved", "path": str(destination)}


class SaveDataCallback(BaseSchedulerCallback):
    callback_name = "saving_data"
    description = "Persist the result data as CSV and optionally email it as an attachment."

    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        payload = self.process_output(result)
        dataframe = self._to_dataframe(payload["data"])
        if dataframe is None:
            raise ValueError("saving_data requires result.data or structured tabular output")
        output_dir = Path(self.config.get("output_dir", tempfile.gettempdir()))
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = self.config.get("filename", f"{agent_name}_{schedule_id}.csv")
        destination = output_dir / filename
        dataframe.to_csv(destination, index=False)
        response: Dict[str, Any] = {"status": "saved", "path": str(destination), "rows": len(dataframe.index)}
        if self.config.get("email_to"):
            email_response = await self.send_email(
                message=self.config.get("message", f"CSV report for {agent_name}"),
                recipients=self.config["email_to"],
                subject=self.config.get("subject", f"CSV data for {agent_name}"),
                attachments=[destination],
                with_attachments=True,
            )
            response["email"] = email_response
        return response

    def _to_dataframe(self, data: Any) -> Optional[pd.DataFrame]:
        if data is None:
            return None
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, list):
            return pd.DataFrame(data)
        if isinstance(data, dict):
            return pd.DataFrame([data])
        return None


class SendNotifyReportCallback(BaseSchedulerCallback):
    callback_name = "send_notify_report"
    description = "Send the result through Telegram, Microsoft Teams, or Slack; CSV data can be attached when present."

    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:
        payload = self.process_output(result)
        provider = str(self.config.get("provider", "telegram")).lower()
        recipients = self.config.get("recipients") or self.config.get("recipient")
        if not recipients:
            raise ValueError("send_notify_report requires recipients")
        message = self.config.get("message") or payload["markdown"] or payload["text"]
        attachments = list(payload["files"])
        dataframe = SaveDataCallback(config=self.config, logger=self.logger)._to_dataframe(payload["data"])
        if dataframe is not None and self.config.get("attach_data", True):
            csv_path = Path(tempfile.gettempdir()) / f"{agent_name}_{schedule_id}.csv"
            dataframe.to_csv(csv_path, index=False)
            attachments.append(csv_path)
        response = await self.send_notification(
            message=message,
            recipients=recipients,
            provider=provider,
            with_attachments=True,
            attachments=attachments,
        )
        return {"status": "sent", "provider": provider, "attachments": [str(p) for p in attachments], "response": response}


CALLBACK_REGISTRY: Dict[str, Type[BaseSchedulerCallback]] = {
    cls.callback_name: cls
    for cls in [
        SendEmailReportCallback,
        CreateFileCallback,
        SaveDataCallback,
        SendNotifyReportCallback,
    ]
}


def list_supported_callbacks() -> List[Dict[str, Any]]:
    return [callback.describe() for callback in CALLBACK_REGISTRY.values()]


def build_scheduler_callback(definition: Dict[str, Any], logger=None) -> BaseSchedulerCallback:
    callback_type = str(definition.get("type") or definition.get("name") or "").strip()
    if callback_type not in CALLBACK_REGISTRY:
        raise ValueError(f"Unsupported scheduler callback: {callback_type}")
    callback_cls = CALLBACK_REGISTRY[callback_type]
    return callback_cls(config=dict(definition.get("config") or {}), logger=logger)
