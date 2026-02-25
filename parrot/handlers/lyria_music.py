"""HTTP handler for Lyria music generation."""
from __future__ import annotations

from typing import Any
import logging

from aiohttp import web
from navigator.views import BaseView
from pydantic import ValidationError

from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import (
    MusicGenerationRequest,
    MusicGenre,
    MusicMood,
    GoogleModel,
)


class LyriaMusicHandler(BaseView):
    """REST handler for Lyria music generation.

    Endpoints:
        POST /api/v1/google/generation/music — Generate music via Lyria.
        GET  /api/v1/google/generation/music — Catalog of genres, moods, and schema.
    """

    _logger_name = "Parrot.LyriaMusicHandler"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    async def post(self) -> web.StreamResponse:
        """Generate music from a MusicGenerationRequest payload.

        Supports two modes:
        - Streaming (default): chunked WAV audio via StreamResponse.
        - Download: buffered WAV with Content-Length when ``stream: false``.
        """
        try:
            data: dict[str, Any] = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        # Extract control keys separately; pass only model fields to Pydantic.
        stream_mode = data.get("stream", True)
        model = data.get("model", GoogleModel.LYRIA.value)
        _control_keys = {"stream", "model"}
        model_data = {k: v for k, v in data.items() if k not in _control_keys}

        try:
            req = MusicGenerationRequest(**model_data)
        except ValidationError as exc:
            return self.error(str(exc), status=400)

        client = GoogleGenAIClient(model=model)
        async with client:
            try:
                if stream_mode:
                    return await self._stream_music(client, req)
                return await self._download_music(client, req)
            except Exception as exc:
                self.logger.error("Music generation failed: %s", exc)
                return self.error(f"Music generation failed: {exc}", status=500)

    async def get(self) -> web.Response:
        """Return catalog of genres, moods, parameter ranges, and JSON schema."""
        schema = MusicGenerationRequest.model_json_schema()
        props = schema["properties"]
        param_names = ("bpm", "temperature", "density", "brightness", "timeout")
        parameters = {
            name: {
                "min": props[name].get("minimum"),
                "max": props[name].get("maximum"),
                "default": props[name].get("default"),
            }
            for name in param_names
        }
        payload: dict[str, Any] = {
            "genres": [g.value for g in MusicGenre],
            "moods": [m.value for m in MusicMood],
            "parameters": parameters,
            "schema": schema,
        }
        return self.json_response(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _music_kwargs(req: MusicGenerationRequest) -> dict[str, Any]:
        """Build kwargs dict for GoogleGenAIClient.generate_music."""
        return {
            "prompt": req.prompt,
            "genre": req.genre,
            "mood": req.mood,
            "bpm": req.bpm,
            "temperature": req.temperature,
            "density": req.density,
            "brightness": req.brightness,
            "timeout": req.timeout,
        }

    async def _stream_music(
        self, client: GoogleGenAIClient, req: MusicGenerationRequest
    ) -> web.StreamResponse:
        """Stream WAV audio chunks via chunked transfer encoding."""
        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "audio/wav",
                "Transfer-Encoding": "chunked",
            },
        )
        await stream.prepare(self.request)

        async for chunk in client.generate_music(**self._music_kwargs(req)):
            await stream.write(chunk)

        await stream.write_eof()
        return stream

    async def _download_music(
        self, client: GoogleGenAIClient, req: MusicGenerationRequest
    ) -> web.Response:
        """Buffer full audio and return with Content-Length."""
        audio_chunks: list[bytes] = []

        async for chunk in client.generate_music(**self._music_kwargs(req)):
            audio_chunks.append(chunk)

        audio_bytes = b"".join(audio_chunks)
        return web.Response(
            body=audio_bytes,
            content_type="audio/wav",
            headers={
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'attachment; filename="music.wav"',
            },
        )
