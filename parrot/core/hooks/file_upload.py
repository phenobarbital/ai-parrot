"""File upload hook — HTTP POST/PUT endpoint for file ingestion."""
import os
import tempfile
from typing import Any, List, Optional

from aiohttp import web

from .base import BaseHook
from .models import FileUploadHookConfig, HookType


class FileUploadHook(BaseHook):
    """Exposes an HTTP POST/PUT endpoint that accepts file uploads.

    Validates MIME types and file names, saves files to a temporary
    directory, fires a HookEvent, then cleans up.
    """

    hook_type = HookType.FILE_UPLOAD

    def __init__(self, config: FileUploadHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._upload_dir = config.upload_dir or tempfile.mkdtemp(prefix="parrot_upload_")

    async def start(self) -> None:
        os.makedirs(self._upload_dir, exist_ok=True)
        self.logger.info(
            f"FileUploadHook '{self.name}' ready (routes via setup_routes)"
        )

    async def stop(self) -> None:
        self.logger.info(f"FileUploadHook '{self.name}' stopped")

    def setup_routes(self, app: Any) -> None:
        url = self._config.url
        for method in self._config.methods:
            handler = self._handle_upload
            app.router.add_route(method, url, handler)
        self.logger.info(
            f"Upload route registered: {self._config.methods} {url}"
        )

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def _handle_upload(self, request: web.Request) -> web.Response:
        try:
            uploaded_files, form_data = await self._save_files(request)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            self.logger.error(f"Upload error: {exc}")
            return web.json_response({"error": "Upload failed"}, status=500)

        # Validate
        for info in uploaded_files:
            if self._config.allowed_mime_types and info["mime_type"] not in self._config.allowed_mime_types:
                self._cleanup(uploaded_files)
                return web.json_response(
                    {"error": f"Invalid mime type: {info['mime_type']}"},
                    status=400,
                )
            if self._config.allowed_file_names and info["file_name"] not in self._config.allowed_file_names:
                self._cleanup(uploaded_files)
                return web.json_response(
                    {"error": f"Invalid file name: {info['file_name']}"},
                    status=400,
                )

        # Emit event
        event = self._make_event(
            event_type="file.uploaded",
            payload={
                "uploaded_files": [
                    {
                        "file_name": f["file_name"],
                        "file_path": f["file_path"],
                        "mime_type": f["mime_type"],
                        "size": f["size"],
                    }
                    for f in uploaded_files
                ],
                "form_data": form_data,
            },
            task=f"Files uploaded: {', '.join(f['file_name'] for f in uploaded_files)}",
        )
        try:
            await self.on_event(event)
        finally:
            self._cleanup(uploaded_files)

        return web.json_response({"status": "accepted"}, status=202)

    async def _save_files(self, request: web.Request) -> tuple:
        """Read multipart data, save files to disk, return metadata."""
        reader = await request.multipart()
        uploaded: List[dict] = []
        form_data: dict = {}

        async for part in reader:
            if part.filename:
                file_path = os.path.join(self._upload_dir, part.filename)
                size = 0
                with open(file_path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        f.write(chunk)
                        size += len(chunk)
                uploaded.append({
                    "file_name": part.filename,
                    "file_path": file_path,
                    "mime_type": part.headers.get("Content-Type", "application/octet-stream"),
                    "size": size,
                })
            else:
                field_name = part.name
                field_value = await part.text()
                form_data[field_name] = field_value

        if not uploaded:
            raise ValueError("No files found in request")

        return uploaded, form_data

    def _cleanup(self, files: List[dict]) -> None:
        for info in files:
            try:
                os.remove(info["file_path"])
            except Exception as exc:
                self.logger.warning(
                    f"Failed to remove temp file {info['file_path']}: {exc}"
                )
