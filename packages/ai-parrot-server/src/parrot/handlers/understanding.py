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
        """Analyse one or more images (and optionally one video) and return the result.

        Supports multipart file uploads (one or more ``file`` parts) and JSON
        body with ``media_url`` and/or ``media_urls``. When a single video and
        any number of images are submitted together, the video is sent as the
        primary input and the images become ``reference_images``.

        Returns:
            200 JSON ``UnderstandingResponse`` on success.
            400 JSON error when the request is invalid (e.g. more than one
                video, undetermined media type, missing prompt/source).
            500 JSON error when the Google GenAI client fails.
        """
        content_type: str = self.request.content_type or ""
        temp_dir: Optional[str] = None
        prompt: Optional[str] = None
        media_type_override: Optional[str] = None
        model_override: Optional[str] = None
        req_kwargs: dict[str, Any] = {}
        sources: list[tuple[Any, Optional[str]]] = []

        try:
            if "multipart" in content_type:
                (
                    prompt,
                    file_entries,
                    media_type_override,
                    model_override,
                    temp_dir,
                ) = await self._handle_multipart()
                sources = list(file_entries)
            else:
                try:
                    body = await self.request.json()
                except Exception:
                    return self.error("Invalid JSON body.", status=400)

                try:
                    req = UnderstandingRequest(**body)
                except ValidationError as exc:
                    return self.error(str(exc), status=400)

                prompt = req.prompt
                media_type_override = req.media_type
                model_override = req.model
                req_kwargs = {
                    "detect_objects": req.detect_objects,
                    "as_image": req.as_image,
                    "temperature": req.temperature,
                    "timeout": req.timeout,
                }

                urls: list[str] = []
                if req.media_url:
                    urls.append(req.media_url)
                if req.media_urls:
                    urls.extend(req.media_urls)

                for url in urls:
                    try:
                        detected = media_type_from_filename(url)
                    except ValueError:
                        detected = None
                    sources.append((url, detected))

            if not prompt:
                return self.error(
                    "Missing required field: 'prompt'.", status=400
                )

            if not sources:
                return self.error(
                    "No media provided. Upload one or more 'file' parts "
                    "(multipart) or supply 'media_url' / 'media_urls' (JSON).",
                    status=400,
                )

            if media_type_override:
                sources = [(s, media_type_override) for s, _ in sources]

            resolved: list[tuple[Any, Optional[str]]] = []
            for source, mt in sources:
                if isinstance(source, str) and not Path(source).exists():
                    if source.startswith("blob:"):
                        return self.error(
                            "blob: URLs are browser-only and cannot be fetched "
                            "server-side. Please upload the file directly via "
                            "multipart/form-data.",
                            status=400,
                        )

                    if source.startswith(("http://", "https://")):
                        if temp_dir is None:
                            temp_dir = tempfile.mkdtemp(
                                prefix="understanding_download_"
                            )
                        try:
                            source = await self._download_url(source, temp_dir)
                        except Exception as exc:
                            self.logger.error(
                                "Failed to download media URL: %s", exc
                            )
                            return self.error(
                                f"Could not download media URL: {exc}",
                                status=400,
                            )
                        if mt is None:
                            try:
                                mt = media_type_from_filename(str(source))
                            except ValueError:
                                pass
                resolved.append((source, mt))

            for source, mt in resolved:
                if mt is None:
                    return self.error(
                        "Could not determine media type for one or more "
                        "sources. Provide an explicit 'media_type' field.",
                        status=400,
                    )

            images = [s for s, mt in resolved if mt == "image"]
            videos = [s for s, mt in resolved if mt == "video"]

            if len(videos) > 1:
                return self.error(
                    "Only one video may be analysed per request. Multiple "
                    "images may accompany a single video as reference images.",
                    status=400,
                )

            self.logger.info(
                "Understanding request: images=%d videos=%d",
                len(images),
                len(videos),
            )

            client_kwargs: dict[str, Any] = {}
            if model_override:
                client_kwargs["model"] = model_override

            client = GoogleGenAIClient(**client_kwargs)
            async with client:
                try:
                    if videos:
                        result = await client.video_understanding(
                            prompt=prompt,
                            video=videos[0],
                            as_image=req_kwargs.get("as_image", True),
                            stateless=True,
                            timeout=req_kwargs.get("timeout", 600),
                            reference_images=images or None,
                        )
                    else:
                        result = await client.image_understanding(
                            prompt=prompt,
                            images=images,
                            detect_objects=req_kwargs.get("detect_objects", True),
                            temperature=req_kwargs.get("temperature"),
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
                "multipart": (
                    "Upload one or more 'file' parts plus a 'prompt' field. "
                    "Multiple files may be sent in a single request."
                ),
                "json": (
                    "Send a JSON body with 'prompt' and either 'media_url' "
                    "(single) or 'media_urls' (list)."
                ),
            },
            "multi_source": {
                "images_only": "Pass N images → image_understanding(images=[...]).",
                "one_video_only": "Pass 1 video → video_understanding(video=...).",
                "video_with_images": (
                    "Pass 1 video + N images → video_understanding with the "
                    "images as reference_images."
                ),
                "multiple_videos": "Rejected with 400.",
            },
        }
        return self.json_response(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_multipart(
        self,
    ) -> tuple[
        Optional[str],
        list[tuple[Path, Optional[str]]],
        Optional[str],
        Optional[str],
        str,
    ]:
        """Parse a ``multipart/form-data`` request body with multi-file support.

        Reads the ``prompt`` field, one or more ``file`` parts (also accepts
        ``files`` / ``file[]``), an optional ``media_type`` override, and an
        optional ``model`` override. Each uploaded file is saved into a
        temporary directory on disk; filenames that collide are suffixed.

        Returns:
            A 5-tuple ``(prompt, file_entries, media_type_override,
            model_override, temp_dir)`` where ``file_entries`` is a list of
            ``(path, detected_media_type)`` tuples and ``temp_dir`` must be
            cleaned up by the caller.
        """
        reader = await self.request.multipart()
        prompt: Optional[str] = None
        file_entries: list[tuple[Path, Optional[str]]] = []
        media_type_override: Optional[str] = None
        model_override: Optional[str] = None
        temp_dir: str = tempfile.mkdtemp(prefix="understanding_upload_")
        seen_filenames: dict[str, int] = {}

        async for part in reader:
            name = part.name or ""

            if name == "prompt":
                raw = await part.read(decode=True)
                prompt = raw.decode("utf-8").strip()

            elif name in ("file", "files", "file[]"):
                filename: str = part.filename or f"upload-{len(file_entries)}"
                base = Path(filename).name
                # Disambiguate same-name uploads so we don't overwrite the
                # previous part's bytes on disk.
                count = seen_filenames.get(base, 0)
                seen_filenames[base] = count + 1
                if count:
                    stem = Path(base).stem
                    suffix = Path(base).suffix
                    base = f"{stem}-{count}{suffix}"
                dest = Path(temp_dir) / base
                with open(dest, "wb") as fh:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        fh.write(chunk)

                ct = part.headers.get("Content-Type", "")
                detected: Optional[str]
                if ct.startswith("video/"):
                    detected = "video"
                elif ct.startswith("image/"):
                    detected = "image"
                else:
                    try:
                        detected = media_type_from_filename(filename)
                    except ValueError:
                        detected = None

                file_entries.append((dest, detected))

            elif name == "media_type":
                raw = await part.read(decode=True)
                media_type_override = raw.decode("utf-8").strip() or None

            elif name == "model":
                raw = await part.read(decode=True)
                model_override = raw.decode("utf-8").strip() or None

        return prompt, file_entries, media_type_override, model_override, temp_dir

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
