"""HTTP handler for Google multimodal generation workflows."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import logging

from aiohttp import web
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from navigator.views import BaseView, BaseHelper

from parrot.clients.google import GoogleGenAIClient
from parrot.models import ImageGenerationPrompt, SpeechGenerationPrompt, VideoGenerationPrompt
from parrot.models.google import (
    ALL_VOICE_PROFILES,
    ConversationalScriptConfig,
    GoogleModel,
    MusicGenre,
    MusicMood,
)


class GoogleGenerationHelper(BaseHelper):
    """Helper for metadata and schema discovery used by :class:`GoogleGeneration`."""

    @staticmethod
    def list_models() -> list[str]:
        return [model.value for model in GoogleModel]

    @staticmethod
    def list_music_genres() -> list[str]:
        return [genre.value for genre in MusicGenre]

    @staticmethod
    def list_music_moods() -> list[str]:
        return [mood.value for mood in MusicMood]

    @staticmethod
    def list_voices() -> list[dict[str, str]]:
        return [
            {
                "voice": profile.voice_name,
                "characteristic": profile.characteristic,
                "gender": profile.gender,
            }
            for profile in ALL_VOICE_PROFILES
        ]

    @staticmethod
    def list_schemas() -> dict[str, dict[str, Any]]:
        return {
            "video_generation_prompt": VideoGenerationPrompt.model_json_schema(),
            "image_generation_prompt": ImageGenerationPrompt.model_json_schema(),
            "conversational_script_config": ConversationalScriptConfig.model_json_schema(),
        }


class GoogleGeneration(BaseView):
    """Class-based HTTP view to expose Google generation methods."""

    _logger_name = "Parrot.GoogleGeneration"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)
        self.helper = GoogleGenerationHelper()

    async def get(self) -> web.Response:
        resource = self.query_parameters(self.request).get("resource", "catalog")

        if resource == "models":
            payload: Dict[str, Any] = {"models": self.helper.list_models()}
        elif resource == "music":
            payload = {
                "genres": self.helper.list_music_genres(),
                "moods": self.helper.list_music_moods(),
            }
        elif resource == "voices":
            payload = {"voices": self.helper.list_voices()}
        elif resource == "schemas":
            payload = self.helper.list_schemas()
        else:
            payload = {
                "resources": ["models", "music", "voices", "schemas"],
                "actions": ["video", "image", "nano_banana", "music", "speech"],
            }

        return self.json_response(payload)

    async def post(self) -> web.Response:
        data = await self.request.json()
        action = str(data.get("action", "")).lower().strip()

        client = GoogleGenAIClient(model=data.get("model", GoogleModel.GEMINI_2_5_FLASH.value))
        try:
            if action == "video":
                return await self._generate_video(client, data)
            if action in {"image", "nano_banana"}:
                return await self._generate_image(client, data)
            if action == "music":
                return await self._generate_music(client, data)
            if action == "speech":
                return await self._generate_speech(client, data)
            return self.error("Unsupported action. Use video, image, nano_banana, music, or speech.", status=400)
        finally:
            await client.close()

    async def _generate_video(self, client: GoogleGenAIClient, data: Dict[str, Any]) -> web.Response:
        prompt = VideoGenerationPrompt(**data["prompt"])
        output = await client.generate_videos(prompt=prompt)

        files = [str(path) for path in (output.files or [])]
        if not data.get("stream"):
            return self.json_response({"files": files, "output": json_encoder(output)})

        if not files:
            return self.error("No video file generated to stream.", status=500)

        return await self._stream_file(Path(files[0]), "video/mp4")

    async def _generate_image(self, client: GoogleGenAIClient, data: Dict[str, Any]) -> web.Response:
        prompt_data = ImageGenerationPrompt(**data["prompt"])
        response = await client.generate_images(prompt_data=prompt_data)
        return self.json_response(json_encoder(response))

    async def _generate_music(self, client: GoogleGenAIClient, data: Dict[str, Any]) -> web.StreamResponse:
        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "audio/wav",
                "Transfer-Encoding": "chunked",
            },
        )
        await stream.prepare(self.request)

        async for chunk in client.generate_music(
            prompt=data["prompt"],
            genre=data.get("genre"),
            mood=data.get("mood"),
            bpm=int(data.get("bpm", 90)),
            temperature=float(data.get("temperature", 1.0)),
            density=float(data.get("density", 0.5)),
            brightness=float(data.get("brightness", 0.5)),
            timeout=int(data.get("timeout", 300)),
        ):
            await stream.write(chunk)

        await stream.write_eof()
        return stream

    async def _generate_speech(self, client: GoogleGenAIClient, data: Dict[str, Any]) -> web.Response:
        prompt_data = SpeechGenerationPrompt(**data["prompt"])
        response = await client.generate_speech(prompt_data=prompt_data)
        return self.json_response(json_encoder(response))

    async def _stream_file(self, file_path: Path, content_type: str, chunk_size: int = 256 * 1024) -> web.StreamResponse:
        if not file_path.exists():
            return self.error(f"File not found for streaming: {file_path}", status=404)

        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'inline; filename="{file_path.name}"',
            },
        )
        await stream.prepare(self.request)

        with file_path.open("rb") as handler:
            while True:
                chunk = handler.read(chunk_size)
                if not chunk:
                    break
                await stream.write(chunk)

        await stream.write_eof()
        return stream
