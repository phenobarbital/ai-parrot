"""HTTP handler for image and video understanding via Google GenAI."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import logging

import aiohttp
from aiohttp import web
from navigator.views import BaseView
from pydantic import ValidationError

from parrot.clients.google import GoogleGenAIClient
from parrot.handlers.models.understanding import (
    UnderstandingRequest,
    UnderstandingResponse,
    media_type_from_filename,
)


class UnderstandingHandler(BaseView):
    """REST handler for image and video understanding.

    Endpoints:
        POST /api/v1/google/understanding — Analyse image or video.
        GET  /api/v1/google/understanding — Return parameter catalog / JSON schema.

    The POST endpoint accepts two request modes:

    * **Multipart** (``multipart/form-data``): upload a file via the ``file``
      field plus a ``prompt`` text field. Optional ``media_type`` and ``model``
      fields may also be included.
    * **JSON** (``application/json``): send a ``UnderstandingRequest`` payload
      with ``media_url`` pointing at a remote image or video.

    Media type (image vs video) is resolved in this priority order:

    1. Explicit ``media_type`` field (``'image'`` or ``'video'``).
    2. ``Content-Type`` header of the uploaded file part (multipart only).
    3. File extension of the uploaded filename or URL path.
    """

    _logger_name = "Parrot.UnderstandingHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # App-level setup
    # ------------------------------------------------------------------

    @classmethod
    def setup(
        cls,
        app: Any,
        route: str = "/api/v1/google/understanding",
    ) -> None:
        """Register the handler view on *app* at *route*.

        Args:
            app: An aiohttp ``Application`` or a Navigator ``WebApp`` wrapper.
            route: URL path to register the view at.
        """
        _app = app.get_app() if hasattr(app, "get_app") else app
        _app.router.add_view(route, cls)

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Analyse an image or video and return the AI understanding result.

        Supports multipart file uploads and JSON body with a media URL.

        Returns:
            200 JSON ``UnderstandingResponse`` on success.
            400 JSON error when the request is invalid.
            500 JSON error when the Google GenAI client fails.
        """
        content_type: str = self.request.content_type or ""
        temp_dir: Optional[str] = None

        try:
            if "multipart" in content_type:
                prompt, file_path, media_type, temp_dir = (
                    await self._handle_multipart()
                )
                model_override: Optional[str] = None
                req_kwargs: dict[str, Any] = {}
            else:
                # JSON mode
                try:
                    body = await self.request.json()
                except Exception:
                    return self.error("Invalid JSON body.", status=400)

                try:
                    req = UnderstandingRequest(**body)
                except ValidationError as exc:
                    return self.error(str(exc), status=400)

                prompt = req.prompt
                file_path = None
                media_type = req.media_type
                model_override = req.model
                req_kwargs = {
                    "detect_objects": req.detect_objects,
                    "as_image": req.as_image,
                    "temperature": req.temperature,
                    "timeout": req.timeout,
                }

                # Resolve media type from URL when not explicit
                if media_type is None and req.media_url:
                    try:
                        media_type = media_type_from_filename(req.media_url)
                    except ValueError:
                        return self.error(
                            "Cannot determine media type from URL. "
                            "Provide an explicit 'media_type' field.",
                            status=400,
                        )
                elif media_type is None:
                    return self.error(
                        "Provide a 'file' (multipart) or 'media_url' (JSON).",
                        status=400,
                    )

            # ------------------------------------------------------------------
            # Validate required fields
            # ------------------------------------------------------------------
            if not prompt:
                return self.error(
                    "Missing required field: 'prompt'.", status=400
                )

            media_source = file_path or (
                None if "multipart" in content_type else body.get("media_url")  # type: ignore[possibly-undefined]
            )
            if media_source is None:
                return self.error(
                    "No media provided. Upload a 'file' (multipart) or "
                    "supply a 'media_url' (JSON).",
                    status=400,
                )

            # ------------------------------------------------------------------
            # Handle URL-based media: download to a temp file so the
            # Google GenAI client can process it locally.
            # ------------------------------------------------------------------
            if isinstance(media_source, str) and not Path(media_source).exists():
                # Reject browser-only blob: URLs
                if media_source.startswith("blob:"):
                    return self.error(
                        "blob: URLs are browser-only and cannot be fetched "
                        "server-side. Please upload the file directly via "
                        "multipart/form-data.",
                        status=400,
                    )

                # Download HTTP(S) URLs to a local temp file
                if media_source.startswith(("http://", "https://")):
                    if temp_dir is None:
                        temp_dir = tempfile.mkdtemp(
                            prefix="understanding_download_"
                        )
                    try:
                        media_source = await self._download_url(
                            media_source, temp_dir
                        )
                    except Exception as exc:
                        self.logger.error(
                            "Failed to download media URL: %s", exc
                        )
                        return self.error(
                            f"Could not download media URL: {exc}",
                            status=400,
                        )

            if media_type is None:
                return self.error(
                    "Could not determine media type. "
                    "Provide an explicit 'media_type' field.",
                    status=400,
                )

            # ------------------------------------------------------------------
            # Dispatch to Google GenAI client
            # ------------------------------------------------------------------
            self.logger.info(
                "Understanding request: media_type=%s source=%s",
                media_type,
                media_source,
            )

            client_kwargs: dict[str, Any] = {}
            if model_override:
                client_kwargs["model"] = model_override

            client = GoogleGenAIClient(**client_kwargs)
            async with client:
                try:
                    if media_type == "image":
                        result = await client.image_understanding(
                            prompt=prompt,
                            images=[media_source],
                            detect_objects=req_kwargs.get("detect_objects", True),
                            temperature=req_kwargs.get("temperature"),
                            timeout=req_kwargs.get("timeout", 600),
                        )
                    else:  # video
                        result = await client.video_understanding(
                            prompt=prompt,
                            video=media_source,
                            as_image=req_kwargs.get("as_image", True),
                            stateless=True,
                            timeout=req_kwargs.get("timeout", 600),
                        )
                except Exception as exc:
                    self.logger.error(
                        "GoogleGenAIClient call failed: %s", exc, exc_info=True
                    )
                    return self.error(
                        f"Analysis failed: {exc}", status=500
                    )

            response = UnderstandingResponse.from_ai_message(result)
            return self.json_response(response.model_dump())

        finally:
            # Always clean up any temp directory that was created.
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    async def get(self) -> web.Response:
        """Return the parameter catalog and JSON schema for this endpoint.

        Returns:
            200 JSON payload with the request schema, supported media types,
            default values, and supported file extensions.
        """
        schema = UnderstandingRequest.model_json_schema()
        payload: dict[str, Any] = {
            "schema": schema,
            "supported_media_types": ["image", "video"],
            "image_extensions": sorted(
                [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"]
            ),
            "video_extensions": sorted(
                [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv", ".wmv"]
            ),
            "defaults": {
                "detect_objects": True,
                "as_image": True,
                "timeout": 600,
            },
            "modes": {
                "multipart": "Upload a 'file' field plus a 'prompt' field.",
                "json": "Send a JSON body with 'prompt' and 'media_url'.",
            },
        }
        return self.json_response(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_multipart(
        self,
    ) -> tuple[Optional[str], Optional[Path], Optional[str], str]:
        """Parse a ``multipart/form-data`` request body.

        Reads the ``prompt``, ``file``, and optional ``media_type`` parts.
        The uploaded file is saved into a temporary directory on disk.

        Returns:
            A 4-tuple ``(prompt, file_path, media_type, temp_dir)`` where
            *temp_dir* is the path to the temporary directory that must be
            cleaned up by the caller.
        """
        reader = await self.request.multipart()
        prompt: Optional[str] = None
        file_path: Optional[Path] = None
        media_type: Optional[str] = None
        temp_dir: str = tempfile.mkdtemp(prefix="understanding_upload_")

        async for part in reader:
            name = part.name or ""

            if name == "prompt":
                raw = await part.read(decode=True)
                prompt = raw.decode("utf-8").strip()

            elif name == "file":
                filename: str = part.filename or "upload"
                dest = Path(temp_dir) / Path(filename).name
                with open(dest, "wb") as fh:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
                file_path = dest

                # Prefer Content-Type header for type detection.
                ct = part.headers.get("Content-Type", "")
                if ct.startswith("video/"):
                    media_type = "video"
                elif ct.startswith("image/"):
                    media_type = "image"
                else:
                    try:
                        media_type = media_type_from_filename(filename)
                    except ValueError:
                        media_type = None  # Will cause a 400 later

            elif name == "media_type":
                raw = await part.read(decode=True)
                media_type = raw.decode("utf-8").strip() or None

            elif name == "model":
                # model override via multipart — stored implicitly on the
                # handler; not used here, but consumed to avoid leftover parts.
                await part.read(decode=True)

        return prompt, file_path, media_type, temp_dir

    async def _download_url(
        self, url: str, dest_dir: str
    ) -> Path:
        """Download a remote media URL to a local temp file.

        Args:
            url: HTTP(S) URL to download.
            dest_dir: Directory to save the file in.

        Returns:
            Path to the downloaded file.

        Raises:
            ValueError: If the download fails or response is not OK.
        """
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "download"
        # Ensure the file has a recognisable extension; fall back to .mp4
        if not Path(filename).suffix:
            filename = f"{filename}.mp4"
        dest = Path(dest_dir) / filename

        self.logger.info("Downloading media from %s", url)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    raise ValueError(
                        f"HTTP {resp.status} when downloading {url}"
                    )
                with open(dest, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)

        self.logger.info("Downloaded %s (%d bytes)", dest.name, dest.stat().st_size)
        return dest
