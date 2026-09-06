"""LyriaToolkit — Google Lyria music generation toolkit for ai-parrot."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Union

from parrot.models.google import MusicGenre, MusicMood
from parrot.tools.toolkit import AbstractToolkit

from .audio_utils import (
    BYTES_PER_SECOND,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    async_save_pcm_to_wav,
    async_slice_wav_file,
    seconds_to_pcm_bytes,
)
from .lyria_models import (
    LyriaMusicParameters,
    LyriaMusicResult,
    parse_natural_music_request,
)

if TYPE_CHECKING:
    from parrot.clients.google.client import GoogleGenAIClient

logger = logging.getLogger(__name__)


class LyriaToolkit(AbstractToolkit):
    """Toolkit for converting natural language descriptions into Google Lyria music generation.

    Exposes tools for:
    - generate_music: Generate audio from a prompt and musical parameters.
    - list_genres_and_moods: Discover supported genres and moods.
    - parse_music_prompt: Parse raw natural language into structured parameters.
    """

    tool_prefix: str = "lyria"
    auto_open: bool = False

    def __init__(
        self,
        client: Optional[Any] = None,
        output_dir: Optional[Union[str, Path]] = None,
        default_duration: int = 10,
        mode: Literal["stream", "batch"] = "stream",
        model: str = "models/lyria-realtime-exp",
        **kwargs: Any,
    ) -> None:
        """Initialize the Lyria music generation toolkit.

        Args:
            client: Optional pre-constructed `GoogleGenAIClient` (or
                compatible mock). When omitted, a client is lazily
                instantiated on first use and owned (and closed) by the
                toolkit.
            output_dir: Directory where generated WAV files are written.
                Defaults to `tmp/music` relative to the current working
                directory.
            default_duration: Default audio duration in seconds when the
                caller does not supply one (default: 10).
            mode: Generation mode — `"stream"` (Lyria RealTime, default)
                or `"batch"` (Vertex AI `lyria-002`).
            model: Model identifier used when lazily constructing the
                client (default: `"models/lyria-realtime-exp"`).
            **kwargs: Additional configuration forwarded to
                `AbstractToolkit.__init__`.
        """
        super().__init__(**kwargs)
        self._client = client
        self._owns_client = client is None
        self.output_dir = Path(output_dir or "tmp/music").resolve()
        self.default_duration = default_duration
        self.mode = mode
        self.model = model
        self.logger = logging.getLogger(self.__class__.__name__)

    async def _get_client(self) -> "GoogleGenAIClient":
        """Lazy-resolve or instantiate the GoogleGenAIClient.

        Returns:
            The active `GoogleGenAIClient` instance (injected or lazily
            constructed).

        Raises:
            RuntimeError: If `ai-parrot-client-google` is not installed.
        """
        if self._client is not None:
            return self._client
        try:
            from parrot.clients.google.client import GoogleGenAIClient
            self._client = GoogleGenAIClient(model=self.model)
            return self._client
        except ImportError as exc:
            raise RuntimeError(
                "GoogleGenAIClient is not available. Ensure ai-parrot-client-google is installed: "
                f"{exc}"
            ) from exc

    async def _close(self) -> None:
        """Release the client if it was created (owned) by this toolkit."""
        if self._client is not None and self._owns_client:
            if hasattr(self._client, "close"):
                await self._client.close()
            self._client = None
        await super()._close()

    async def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 10,
        genre: Optional[str] = None,
        mood: Optional[str] = None,
        bpm: int = 90,
        temperature: float = 1.0,
        density: float = 0.5,
        brightness: float = 0.5,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate music using Google Lyria from a prompt and structured musical parameters.

        Args:
            prompt: Text description of the desired music (instruments, style, feel).
            duration_seconds: Duration of the generated audio in seconds (1 to 120, default 10).
            genre: Music genre hint (e.g. 'Ambient', 'Chillout', 'Lo-Fi Hip Hop', 'Classical').
            mood: Music mood hint (e.g. 'Ambient', 'Chill', 'Dreamy', 'Ethereal Ambience').
            bpm: Tempo in beats per minute (60-200, default 90). Slow=60-80, Medium=90-110, Fast=120-160.
            temperature: Creativity/randomness parameter (0.0 to 3.0, default 1.0).
            density: Note density (0.0 to 1.0). Use 0.2-0.4 for soft/sparse, 0.7-0.9 for dense.
            brightness: Tonal brightness (0.0 to 1.0). Use 0.2-0.4 for warm/mellow, 0.7-0.9 for bright.
            negative_prompt: Musical elements or sounds to exclude (e.g. 'drums, vocals').
            seed: Deterministic integer seed for reproducible generation.

        Returns:
            Dict containing status, file_path, duration_seconds, sample_rate, channels, and parameters.
        """
        duration = max(1, min(120, duration_seconds or self.default_duration))
        params = LyriaMusicParameters(
            prompt=prompt,
            duration_seconds=duration,
            genre=genre,
            mood=mood,
            bpm=bpm,
            temperature=temperature,
            density=density,
            brightness=brightness,
            negative_prompt=negative_prompt,
            seed=seed,
        )

        client = await self._get_client()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex[:10]
        out_path = self.output_dir / f"lyria_{file_id}.wav"

        if self.mode == "stream":
            return await self._generate_stream(client, params, out_path)
        return await self._generate_batch(client, params, out_path)

    async def _generate_stream(
        self,
        client: Any,
        params: LyriaMusicParameters,
        out_path: Path,
    ) -> Dict[str, Any]:
        """Stream PCM chunks from Lyria RealTime and truncate to the exact target duration.

        Args:
            client: Active `GoogleGenAIClient` (or compatible mock).
            params: Resolved music generation parameters.
            out_path: Destination WAV file path.

        Returns:
            Structured result dict (`LyriaMusicResult.model_dump()`), or an
            error dict on failure.
        """
        target_bytes = seconds_to_pcm_bytes(params.duration_seconds)
        pcm_chunks: list[bytes] = []
        collected = 0

        try:
            stream = client.generate_music_stream(
                prompt=params.prompt,
                genre=params.genre,
                mood=params.mood,
                bpm=params.bpm,
                temperature=params.temperature,
                density=params.density,
                brightness=params.brightness,
                timeout=max(30, params.duration_seconds * 3),
            )
            async for chunk in stream:
                if chunk:
                    pcm_chunks.append(chunk)
                    collected += len(chunk)
                    if collected >= target_bytes:
                        break

            all_pcm = b"".join(pcm_chunks)
            if not all_pcm:
                return {
                    "status": "error",
                    "error": "No audio data received from Lyria stream.",
                }

            # Truncate to exact required bytes
            final_pcm = all_pcm[:target_bytes]
            saved_file = await async_save_pcm_to_wav(final_pcm, out_path)
            actual_duration = len(final_pcm) / BYTES_PER_SECOND

            res = LyriaMusicResult(
                status="success",
                file_path=str(saved_file),
                duration_seconds=round(actual_duration, 2),
                sample_rate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                format="wav",
                size_bytes=saved_file.stat().st_size,
                parameters=params,
            )
            return res.model_dump()

        except Exception as exc:
            self.logger.error(f"Lyria stream generation failed: {exc}", exc_info=True)
            return {
                "status": "error",
                "error": str(exc),
                "parameters": params.model_dump(),
            }

    async def _generate_batch(
        self,
        client: Any,
        params: LyriaMusicParameters,
        out_path: Path,
    ) -> Dict[str, Any]:
        """Generate music via Vertex AI Lyria batch and slice to the target duration.

        Args:
            client: Active `GoogleGenAIClient` (or compatible mock).
            params: Resolved music generation parameters.
            out_path: Destination WAV file path.

        Returns:
            Structured result dict (`LyriaMusicResult.model_dump()`), or an
            error dict on failure.
        """
        try:
            files = await client.generate_music_batch(
                prompt=params.prompt,
                negative_prompt=params.negative_prompt,
                seed=params.seed,
                genre=params.genre,
                mood=params.mood,
                output_directory=self.output_dir,
            )
            if not files:
                return {"status": "error", "error": "Lyria batch returned no files."}

            raw_file = files[0]
            saved_file = await async_slice_wav_file(raw_file, out_path, params.duration_seconds)
            return LyriaMusicResult(
                status="success",
                file_path=str(saved_file),
                duration_seconds=float(params.duration_seconds),
                sample_rate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                format="wav",
                size_bytes=saved_file.stat().st_size,
                parameters=params,
            ).model_dump()
        except Exception as exc:
            self.logger.error(f"Lyria batch generation failed: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc), "parameters": params.model_dump()}

    async def list_genres_and_moods(self) -> Dict[str, Any]:
        """Return the catalog of genres and moods supported by Google Lyria.

        Returns:
            Dict with `genres`, `moods`, and default parameter values.
        """
        return {
            "genres": [g.value for g in MusicGenre],
            "moods": [m.value for m in MusicMood],
            "defaults": {
                "duration_seconds": self.default_duration,
                "bpm": 90,
                "temperature": 1.0,
                "density": 0.5,
                "brightness": 0.5,
            },
        }

    async def parse_music_prompt(self, request: str) -> Dict[str, Any]:
        """Parse a natural language request into structured Lyria parameters.

        Args:
            request: Free-form natural language music description.

        Returns:
            Dict matching `LyriaMusicParameters` fields.
        """
        parsed = parse_natural_music_request(request, default_duration=self.default_duration)
        return parsed.model_dump()
