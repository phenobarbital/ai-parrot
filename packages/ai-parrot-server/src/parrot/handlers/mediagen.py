"""HTTP handler for Google Media Generation (Image and Video) via Google GenAI."""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aiohttp import web
from navigator.views import BaseView
from datamodel.parsers.json import json_encoder

from parrot.clients.google import GoogleGenAIClient
from parrot.models import ImageGenerationPrompt, VideoGenerationPrompt
from parrot.models.google import GoogleModel


class MediaGen(BaseView):
    """REST handler for image and video generation.

    Endpoints:
        POST /api/v1/google/media — Generate images or videos.
    """

    _logger_name = "Parrot.MediaGen"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    @classmethod
    def setup(
        cls,
        app: Any,
        route: str = "/api/v1/google/media",
    ) -> None:
        """Register the handler view on *app* at *route*.

        Args:
            app: An aiohttp ``Application`` or a Navigator ``WebApp`` wrapper.
            route: URL path to register the view at.
        """
        _app = app.get_app() if hasattr(app, "get_app") else app
        _app.router.add_view(route, cls)

    async def post(self) -> web.Response:
        """Expose image and video generation endpoints in single or batch modes.

        Accepts JSON payload:
        {
            "action": "image" | "video",
            "batch": true | false,
            "use_flex": true | false,  # default is false, but true triggers flex mode for images
            "prompt": "Text prompt for single generation",
            "prompts": ["Prompt 1", "Prompt 2"],  # for list-based batches
            "requests": [{"prompt": "...", "aspect_ratio": "..."}, ...],  # for custom-parameter batches
            "download_mode": "StreamResponse" | "FileResponse",  # default is "StreamResponse"
            "model": "optional_model_name",
            ... rest of standard parameters like aspect_ratio, resolution, etc.
        }

        Returns:
            StreamResponse (default) or FileResponse containing generated image/video files,
            or JSON list of metadata/paths if multiple files are generated and no zip download is resolved.
        """
        data = await self.request.json()
        action = str(data.get("action", "")).lower().strip()
        batch = bool(data.get("batch", False))
        use_flex = bool(data.get("use_flex", False))
        download_mode = str(data.get("download_mode", "StreamResponse")).strip()
        
        # Default model based on action
        default_model = (
            GoogleModel.GEMINI_3_1_FLASH_IMAGE_PREVIEW.value
            if action == "image"
            else GoogleModel.VEO_3_1.value
        )
        model = data.get("model") or default_model

        if action not in {"image", "video"}:
            return self.error("Unsupported action. Must be 'image' or 'video'.", status=400)

        client = GoogleGenAIClient(model=model)
        try:
            generated_files: List[Path] = []
            results_metadata: List[Any] = []

            if action == "image":
                if batch:
                    # Resolve requests list
                    batch_requests = self._resolve_batch_requests(data)
                    self.logger.info(f"Generating image batch with {len(batch_requests)} items...")
                    results = await client.generate_image_batch(
                        batch_requests,
                        use_flex=True, # Force use_flex=True as requested for batch image
                        persist_results=True
                    )
                    for r in results:
                        if isinstance(r, Exception):
                            self.logger.error(f"Image batch item failed: {r}")
                            results_metadata.append({"error": str(r)})
                        else:
                            results_metadata.append(r.model_dump(mode="json"))
                            if r.images:
                                generated_files.extend([Path(p) for p in r.images])
                else:
                    # Single image generation
                    prompt = data.get("prompt", "")
                    if not prompt:
                        return self.error("Missing required field: 'prompt'", status=400)
                    
                    self.logger.info(f"Generating single image using model: {model}")
                    prompt_data = ImageGenerationPrompt(prompt=prompt, model=model, **{k: v for k, v in data.items() if k not in {"action", "batch", "prompt", "model", "download_mode", "use_flex"}})
                    r = await client.generate_images(prompt_data=prompt_data)
                    results_metadata.append(r.model_dump(mode="json"))
                    if r.images:
                        generated_files.extend([Path(p) for p in r.images])

            elif action == "video":
                if batch:
                    batch_requests = self._resolve_batch_requests(data)
                    self.logger.info(f"Generating video batch with {len(batch_requests)} items...")
                    results = await client.generate_video_batch(
                        batch_requests,
                        persist_results=True
                    )
                    for r in results:
                        if isinstance(r, Exception):
                            self.logger.error(f"Video batch item failed: {r}")
                            results_metadata.append({"error": str(r)})
                        else:
                            results_metadata.append(r.model_dump(mode="json"))
                            files_list = r.files or r.media or []
                            if files_list:
                                generated_files.extend([Path(p) for p in files_list])
                else:
                    # Single video generation
                    prompt = data.get("prompt", "")
                    if not prompt:
                        return self.error("Missing required field: 'prompt'", status=400)
                    
                    self.logger.info(f"Generating single video using model: {model}")
                    prompt_data = VideoGenerationPrompt(prompt=prompt, model=model, **{k: v for k, v in data.items() if k not in {"action", "batch", "prompt", "model", "download_mode", "use_flex"}})
                    r = await client.generate_videos(prompt_data=prompt_data)
                    results_metadata.append(r.model_dump(mode="json"))
                    files_list = r.files or r.media or []
                    if files_list:
                        generated_files.extend([Path(p) for p in files_list])

            # Resolve output downloads based on files found
            if not generated_files:
                return self.json_response({
                    "message": "Generation completed with no files returned.",
                    "metadata": results_metadata
                })

            # If there's only one file, we return/stream it directly
            if len(generated_files) == 1:
                target_file = generated_files[0]
                mime_type = "image/png" if action == "image" else "video/mp4"
                return await self._deliver_file(target_file, mime_type, download_mode)

            # If there are multiple files, we zip them up and deliver the zip file
            zip_dir = tempfile.mkdtemp()
            zip_path = Path(zip_dir) / f"generated_assets_{int(time.time())}.zip"
            with zipfile.ZipFile(zip_path, "w") as zip_file:
                for f in generated_files:
                    if f.exists() and f.is_file():
                        zip_file.write(f, arcname=f.name)

            return await self._deliver_file(zip_path, "application/zip", download_mode)

        except Exception as exc:
            self.logger.exception(f"Media generation failed: {exc}")
            return self.error(f"Media generation failed: {exc}", status=500)
        finally:
            await client.close()

    def _resolve_batch_requests(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract a list of request dictionaries from batch fields."""
        requests = data.get("requests")
        if isinstance(requests, list):
            return [dict(r) for r in requests]
        
        prompts = data.get("prompts")
        if isinstance(prompts, list):
            return [{"prompt": str(p)} for p in prompts]
        
        # Fallback to single prompt in batch mode
        prompt = data.get("prompt")
        if prompt:
            return [{"prompt": str(prompt)}]
        
        return []

    async def _deliver_file(
        self,
        file_path: Path,
        content_type: str,
        download_mode: str
    ) -> web.Response:
        """Deliver the generated file as either a web.FileResponse or a StreamResponse."""
        if not file_path.exists():
            return self.error(f"Generated file not found on disk: {file_path}", status=404)

        if download_mode == "FileResponse":
            self.logger.info(f"Delivering file via FileResponse: {file_path.name}")
            return web.FileResponse(
                file_path,
                headers={
                    "Content-Disposition": f'attachment; filename="{file_path.name}"',
                    "Content-Type": content_type
                }
            )

        # StreamResponse (default)
        self.logger.info(f"Delivering file via StreamResponse: {file_path.name}")
        return await self._stream_file(file_path, content_type)

    async def _stream_file(
        self,
        file_path: Path,
        content_type: str,
        chunk_size: int = 256 * 1024
    ) -> web.StreamResponse:
        """Stream a file chunk-by-chunk using web.StreamResponse."""
        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'inline; filename="{file_path.name}"',
            },
        )
        await stream.prepare(self.request)

        with file_path.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                await stream.write(chunk)

        await stream.write_eof()
        return stream
