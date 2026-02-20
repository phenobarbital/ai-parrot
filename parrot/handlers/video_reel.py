"""HTTP handler for video reel generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import logging

from aiohttp import web
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from navigator.views import BaseView
from pydantic import ValidationError

from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import (
    AspectRatio,
    MusicGenre,
    MusicMood,
    VideoReelRequest,
    VideoReelScene,
    GoogleModel,
)


class VideoReelHandler(BaseView):
    """REST handler for video reel generation.

    Endpoints:
        POST /api/v1/google/generation/video_reel — Generate a video reel.
        GET  /api/v1/google/generation/video_reel/schema — JSON Schema catalog.
    """

    _logger_name = "Parrot.VideoReelHandler"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    async def post(self) -> web.Response:
        """Generate a video reel from a VideoReelRequest payload."""
        try:
            data: dict[str, Any] = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        # Extract control keys before Pydantic validation.
        model = data.pop("model", GoogleModel.GEMINI_3_FLASH_PREVIEW.value)
        output_directory: Optional[str] = data.pop("output_directory", None)
        user_id: Optional[str] = data.pop("user_id", None)
        session_id: Optional[str] = data.pop("session_id", None)

        try:
            req = VideoReelRequest(**data)
        except ValidationError as exc:
            return self.error(str(exc), status=400)

        output_path = Path(output_directory) if output_directory else None

        client = GoogleGenAIClient(model=model)
        async with client:
            try:
                result = await client.generate_video_reel(
                    request=req,
                    output_directory=output_path,
                    user_id=user_id,
                    session_id=session_id,
                )
                return self.json_response(result)
            except Exception as exc:
                self.logger.error("Video reel generation failed: %s", exc)
                return self.error(
                    f"Video reel generation failed: {exc}", status=500
                )

    async def get(self) -> web.Response:
        """Return JSON Schema for VideoReelRequest and nested types."""
        payload: dict[str, Any] = {
            "video_reel_request": VideoReelRequest.model_json_schema(),
            "video_reel_scene": VideoReelScene.model_json_schema(),
            "aspect_ratios": [r.value for r in AspectRatio],
            "music_genres": [g.value for g in MusicGenre],
            "music_moods": [m.value for m in MusicMood],
        }
        return self.json_response(payload)