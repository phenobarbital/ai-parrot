"""HTTP handler for Google Media Generation (Image and Video) via Google GenAI."""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aiohttp import MultipartWriter, web
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
            "download_mode": "StreamResponse" | "FileResponse" | "Multipart",  # default is "StreamResponse"
            "model": "optional_model_name",
            ... rest of standard parameters like aspect_ratio, resolution, etc.
        }

        Returns:
            StreamResponse (default) or FileResponse containing generated image/video files,
            or JSON list of metadata/paths if multiple files are generated and no zip download is resolved.

            When ``download_mode`` is ``"Multipart"`` and at least one file is
            produced, a ``multipart/mixed`` response is returned instead: the
            first part is an ``application/json`` document with per-item
            ``metadata`` (including ``{"error": ...}`` entries for failed batch
            items), followed by one part per generated file. This is the only
            delivery mode that preserves batch metadata alongside the binaries.
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

                    # Filter payload to only include fields accepted by ImageGenerationPrompt schema
                    model_fields = set(ImageGenerationPrompt.model_fields.keys())
                    filtered_inputs = {k: v for k, v in data.items() if k in model_fields}
                    filtered_inputs["prompt"] = prompt
                    filtered_inputs["model"] = model

                    prompt_data = ImageGenerationPrompt(**filtered_inputs)

                    # The image backends only persist files to disk when an
                    # output_directory is provided; without it ``r.images`` is
                    # empty and nothing can be streamed back. Always generate
                    # into a temp directory so the file can be delivered.
                    image_output_dir = tempfile.mkdtemp(prefix="mediagen_img_")

                    # Route to either Gemini/Nano Banana or Imagen based on model prefix
                    if str(model).startswith("gemini"):
                        self.logger.info(f"Routing image generation to Gemini generate_image() for: {model}")
                        r = await client.generate_image(
                            prompt=prompt,
                            model=model,
                            aspect_ratio=prompt_data.aspect_ratio,
                            resolution=prompt_data.resolution,
                            auto_upscale=prompt_data.auto_upscale,
                            service_tier="flex" if use_flex else None,
                            output_directory=image_output_dir
                        )
                    else:
                        self.logger.info(f"Routing image generation to Imagen generate_images() for: {model}")
                        r = await client.generate_images(
                            prompt=prompt_data,
                            output_directory=Path(image_output_dir)
                        )

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
                    
                    # Filter payload to only include fields accepted by VideoGenerationPrompt schema
                    model_fields = set(VideoGenerationPrompt.model_fields.keys())
                    filtered_inputs = {k: v for k, v in data.items() if k in model_fields}
                    filtered_inputs["prompt"] = prompt
                    filtered_inputs["model"] = model
                    
                    prompt_data = VideoGenerationPrompt(**filtered_inputs)
                    r = await client.generate_videos(prompt=prompt_data)
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

            # Multipart delivery: a JSON metadata part followed by one part per
            # file. Unlike the single-file and zip paths below, this preserves
            # per-item metadata (including failed-item errors) alongside the
            # binaries — relevant for partially-failing batches.
            if download_mode == "Multipart":
                mime_type = "image/png" if action == "image" else "video/mp4"
                return await self._deliver_multipart(
                    generated_files, results_metadata, mime_type
                )

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
            
            error_message = str(exc)
            error_code = 500
            
            # Dynamic parsing for embedded JSON/Dict representations (e.g. {'code': 13, ...})
            if "{" in error_message and "}" in error_message:
                try:
                    import re
                    match = re.search(r"\{.*?\}", error_message.replace("'", '"'))
                    if match:
                        from datamodel.parsers.json import json_decoder
                        err_dict = json_decoder(match.group(0))
                        if isinstance(err_dict, dict):
                            error_message = err_dict.get("message", error_message)
                            error_code = err_dict.get("code", error_code)
                except Exception:
                    pass
            
            # Direct attribute check for native google-genai ClientError/APIError
            if hasattr(exc, "code") and hasattr(exc, "message"):
                error_message = getattr(exc, "message")
                error_code = getattr(exc, "code")
                
            return self.json_response({
                "error": {
                    "message": error_message,
                    "code": error_code,
                    "details": str(exc)
                }
            }, status=500)
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

    async def _deliver_multipart(
        self,
        files: List[Path],
        metadata: List[Any],
        content_type: str,
    ) -> web.StreamResponse:
        """Deliver files and metadata as a single ``multipart/mixed`` response.

        The first part is an ``application/json`` document carrying the
        per-item ``metadata`` list (including ``{"error": ...}`` entries for
        failed batch items); each remaining part carries one generated file.
        This preserves batch metadata that the zip and single-file delivery
        paths discard once any file is produced, and lets the client consume
        individual assets without unzipping.

        Args:
            files: Generated asset paths to stream, one per multipart part.
            metadata: Per-item result metadata to embed as the JSON part.
            content_type: MIME type for the file parts (e.g. ``video/mp4``).

        Returns:
            A prepared ``StreamResponse`` with the multipart body written.
        """
        mpwriter = MultipartWriter("mixed")

        meta_part = mpwriter.append(
            json_encoder({"metadata": metadata}),
            {"Content-Type": "application/json"},
        )
        meta_part.set_content_disposition("inline", name="metadata")

        handles: List[Any] = []
        for f in files:
            if f.exists() and f.is_file():
                fh = f.open("rb")
                handles.append(fh)
                file_part = mpwriter.append(fh, {"Content-Type": content_type})
                file_part.set_content_disposition(
                    "attachment", name="file", filename=f.name
                )

        self.logger.info(
            f"Delivering {len(handles)} file(s) + metadata via multipart/mixed"
        )
        try:
            response = web.StreamResponse(status=200, headers=mpwriter.headers)
            await response.prepare(self.request)
            await mpwriter.write(response)
            await response.write_eof()
            return response
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass

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
