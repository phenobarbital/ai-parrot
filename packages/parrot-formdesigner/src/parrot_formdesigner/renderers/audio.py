"""AudioFormRenderer — Standalone audio form renderer for parrot-formdesigner.

Converts a FormSchema into an AudioFormManifest — a sequential list of
questions suitable for a voice-driven Q&A session over WebSocket.

The renderer is registered under the "audio" format key and is discoverable
at GET /api/v1/forms/{form_id}/render/audio.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from ..audio.models import (
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    VoiceMode,
)
from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer

if TYPE_CHECKING:
    from parrot.voice.tts.synthesizer import VoiceSynthesizer

logger = logging.getLogger(__name__)

# Field types that should be excluded from the audio question list (FEAT-236).
# Only HIDDEN is dropped — it is never user-visible. Every other field becomes
# a question tagged with its VoiceMode so no required field is ever lost.
_SKIP_FIELD_TYPES: frozenset[FieldType] = frozenset({FieldType.HIDDEN})

# Field types that carry options (SELECT / MULTI_SELECT).
_SELECT_TYPES: frozenset[FieldType] = frozenset(
    {FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT}
)

# FEAT-236 voice-capability taxonomy (spec §2 pillar 2). Field types not listed
# in either set default to VoiceMode.VOICE (narrate + spoken/typed answer).
_PROMPT_SELECT_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.SELECT,
        FieldType.MULTI_SELECT,
        FieldType.DYNAMIC_SELECT,
        FieldType.BOOLEAN,
        FieldType.RANKING,
        FieldType.LIKERT,
        FieldType.NPS,
        FieldType.COLOR,
    }
)
_VISUAL_FALLBACK_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.REST,
        FieldType.REMOTE_RESPONSE,
        FieldType.FILE,
        FieldType.IMAGE,
        FieldType.LOCATION,
        FieldType.SIGNATURE,
        FieldType.TRANSFER_LIST,
        FieldType.AVAILABILITY,
        FieldType.ARRAY,
    }
)

# Maps a VoiceMode to the client-facing render hint carried on the question.
_RENDER_MODE_BY_VOICE: dict[VoiceMode, str] = {
    VoiceMode.VOICE: "voice",
    VoiceMode.PROMPT_SELECT: "select",
    VoiceMode.VISUAL_FALLBACK: "visual",
}


def classify_voice_mode(field: FormField) -> VoiceMode:
    """Classify a FormField into a VoiceMode (FEAT-236).

    A per-field override in ``field.meta["voice_mode"]`` (case-insensitive
    match against the VoiceMode values) wins over the default FieldType table.
    An invalid override logs a warning and falls back to the default.

    Args:
        field: The FormField to classify.

    Returns:
        The VoiceMode for this field.
    """
    if field.meta:
        override = field.meta.get("voice_mode")
        if override is not None:
            try:
                return VoiceMode(str(override).strip().lower())
            except ValueError:
                logger.warning(
                    "Invalid voice_mode override %r on field %s; using default",
                    override,
                    field.field_id,
                )

    field_type = field.field_type
    if field_type in _VISUAL_FALLBACK_TYPES:
        return VoiceMode.VISUAL_FALLBACK
    if field_type in _PROMPT_SELECT_TYPES:
        return VoiceMode.PROMPT_SELECT
    return VoiceMode.VOICE


def build_audio_synthesizer(
    config: AudioSessionConfig | None = None,
) -> "VoiceSynthesizer | None":
    """Build a VoiceSynthesizer preferring SuperTonic, else None (FEAT-236).

    Constructs a ``VoiceSynthesizer`` configured with the preferred TTS backend
    (``config.tts_backend``, default ``"supertonic"``). The backend itself is
    created lazily on first ``synthesize()`` — no model is loaded here. Returns
    ``None`` when the ``parrot.voice`` TTS stack is not importable at all
    (text-only session). The SuperTonic→Google→text-only fallback at synthesis
    time lives in :func:`synthesize_with_fallback`.

    Args:
        config: Optional session config carrying ``tts_backend``,
            ``tts_voice`` and ``tts_mime_format``.

    Returns:
        A configured ``VoiceSynthesizer``, or ``None`` if voice TTS is
        unavailable.
    """
    try:
        from parrot.voice.tts.models import TTSConfig
        from parrot.voice.tts.synthesizer import VoiceSynthesizer
    except ImportError as exc:
        logger.warning(
            "parrot.voice TTS stack unavailable (%s); audio runs text-only", exc
        )
        return None

    backend = config.tts_backend if config is not None else "supertonic"
    voice = config.tts_voice if config is not None else None
    mime_format = config.tts_mime_format if config is not None else "audio/wav"
    return VoiceSynthesizer(
        TTSConfig(backend=backend, voice=voice, mime_format=mime_format)
    )


async def synthesize_with_fallback(
    text: str,
    *,
    config: AudioSessionConfig | None = None,
    language: str | None = None,
) -> bytes | None:
    """Synthesize ``text`` to audio bytes, SuperTonic→Google→text-only.

    The single reusable place for the FEAT-236 graceful-degradation contract
    (shared by the renderer and the WebSocket handler). Tries the preferred
    backend first (default SuperTonic), then Google. Any
    ``ImportError``/``ValueError``/``RuntimeError`` raised by a backend (missing
    extra, unconfigured weights, no ``inference_fn``) is caught and the next
    backend is tried. Returns ``None`` when no backend is usable — the caller
    delivers the question text-only. NEVER raises for a missing/misconfigured
    backend (FEAT-231 contract).

    Args:
        text: The text to synthesize.
        config: Optional session config (preferred backend, voice, mime).
        language: Optional BCP 47 language hint for the backend.

    Returns:
        Raw audio bytes, or ``None`` for a text-only fallback.
    """
    try:
        from parrot.voice.tts.models import TTSConfig
        from parrot.voice.tts.synthesizer import VoiceSynthesizer
    except ImportError as exc:
        logger.warning(
            "parrot.voice TTS stack unavailable (%s); text-only synthesis", exc
        )
        return None

    preferred = config.tts_backend if config is not None else "supertonic"
    voice = config.tts_voice if config is not None else None
    mime_format = config.tts_mime_format if config is not None else "audio/wav"

    # Preferred backend first, then Google as a fallback (deduplicated).
    backends = [preferred] + [b for b in ("google",) if b != preferred]
    for backend in backends:
        synth = VoiceSynthesizer(
            TTSConfig(backend=backend, voice=voice, mime_format=mime_format)
        )
        try:
            result = await synth.synthesize(text, language=language)
            return result.audio
        except (ImportError, ValueError, RuntimeError) as exc:
            logger.warning("TTS backend %s unavailable: %s", backend, exc)
        finally:
            await synth.close()
    return None


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve a LocalizedString to a plain string.

    Args:
        value: String or locale dict.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string, or empty string when value is None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


class AudioFormRenderer(AbstractFormRenderer):
    """Renders a FormSchema as an AudioFormManifest (sequential questions).

    The manifest is returned as `RenderedForm.content` (a dict) with
    `content_type="application/json"`. Optionally pre-synthesizes TTS audio
    for each question when a `VoiceSynthesizer` is provided.

    The renderer is registered under the ``"audio"`` format key by
    ``_seed_default_renderers()`` in ``api/render.py``.

    Args:
        synthesizer: Optional VoiceSynthesizer. When provided, each question
            will have its label synthesized to bytes stored in
            ``AudioQuestion.audio_prompt``.

    Example::

        renderer = AudioFormRenderer()
        result = await renderer.render(form_schema, locale="en")
        manifest = result.content  # dict with form_id, questions, ws_endpoint, ...
    """

    def __init__(
        self,
        synthesizer: Optional["VoiceSynthesizer"] = None,
    ) -> None:
        """Initialize the AudioFormRenderer.

        Args:
            synthesizer: Optional TTS synthesizer for pre-synthesizing
                question audio. When None, AudioQuestion.audio_prompt stays None.
        """
        self._synthesizer = synthesizer
        self.logger = logging.getLogger(__name__)

    def split_into_questions(
        self,
        form: FormSchema,
        *,
        locale: str = "en",
    ) -> list[AudioQuestion]:
        """Flatten a FormSchema into a sequential list of AudioQuestion objects.

        Iterates all sections → subsections → fields. Skips HIDDEN and ARRAY
        fields. Expands GROUP fields by flattening their children into individual
        questions.

        Args:
            form: The FormSchema to convert.
            locale: BCP 47 locale for label resolution.

        Returns:
            Ordered list of AudioQuestion objects, one per voiced field.
        """
        questions: list[AudioQuestion] = []
        index = 0

        for field in form.iter_all_fields():
            new_questions = self._field_to_questions(field, locale=locale)
            for q in new_questions:
                # model_copy preserves the FEAT-236 voice fields
                # (voice_mode / render_mode / sensitive / fallback_html).
                questions.append(q.model_copy(update={"index": index}))
                index += 1

        return questions

    def _field_to_questions(
        self,
        field: FormField,
        *,
        locale: str = "en",
    ) -> list[AudioQuestion]:
        """Convert a single FormField into one or more AudioQuestion objects.

        GROUP fields expand their children into individual questions.
        Only HIDDEN fields are skipped (return empty list); every other field
        becomes a question tagged with its VoiceMode (FEAT-236).

        Args:
            field: The FormField to convert.
            locale: BCP 47 locale for label resolution.

        Returns:
            List of AudioQuestion objects (empty if field should be skipped).
        """
        if field.field_type in _SKIP_FIELD_TYPES:
            return []

        if field.field_type == FieldType.GROUP:
            children = field.children or []
            result: list[AudioQuestion] = []
            for child in children:
                result.extend(self._field_to_questions(child, locale=locale))
            return result

        label = _resolve(field.label, locale)
        description = _resolve(field.description, locale) or None

        options: list[dict] | None = None
        if field.options:
            options = [
                {
                    "value": opt.value,
                    "label": _resolve(opt.label, locale),
                }
                for opt in field.options
            ]

        constraints: dict | None = None
        if field.constraints is not None:
            try:
                constraints = field.constraints.model_dump(exclude_none=True)
            except Exception as exc:
                self.logger.warning("Failed to serialize field constraints: %s", exc)
                constraints = None

        voice_mode = classify_voice_mode(field)
        render_mode = _RENDER_MODE_BY_VOICE[voice_mode]
        sensitive = field.field_type == FieldType.PASSWORD

        return [
            AudioQuestion(
                index=0,  # re-indexed by caller
                field_id=field.field_id,
                field_type=field.field_type.value,
                label=label,
                description=description,
                required=field.required,
                audio_prompt=None,
                constraints=constraints,
                options=options,
                voice_mode=voice_mode,
                render_mode=render_mode,
                sensitive=sensitive,
            )
        ]

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a FormSchema into an AudioFormManifest.

        Flattens the form into a sequential question list. Optionally
        pre-synthesizes TTS audio for each question using the injected
        VoiceSynthesizer.

        Args:
            form: The form to render.
            style: Ignored for the audio renderer.
            locale: BCP 47 locale for label resolution.
            prefilled: Ignored for the audio renderer.
            errors: Ignored for the audio renderer.

        Returns:
            RenderedForm with content as a dict (AudioFormManifest.model_dump())
            and content_type="application/json".
        """
        questions = self.split_into_questions(form, locale=locale)

        # Pre-synthesize TTS audio if a synthesizer is available.
        if self._synthesizer is not None:
            questions = await self._synthesize_questions(questions, locale=locale)

        ws_endpoint = f"/api/v1/forms/{form.form_id}/audio/ws"
        form_title = _resolve(form.title, locale) if form.title else form.form_id

        manifest = AudioFormManifest(
            form_id=form.form_id,
            title=form_title,
            total_questions=len(questions),
            questions=questions,
            ws_endpoint=ws_endpoint,
            locale=locale,
        )

        # Serialize to dict; exclude audio_prompt bytes from JSON output.
        manifest_dict = manifest.model_dump(exclude={"questions": {"__all__": {"audio_prompt"}}})

        return RenderedForm(
            content=manifest_dict,
            content_type="application/json",
        )

    async def _synthesize_questions(
        self,
        questions: list[AudioQuestion],
        *,
        locale: str = "en",
    ) -> list[AudioQuestion]:
        """Pre-synthesize TTS audio for each question.

        Args:
            questions: List of AudioQuestion objects without audio_prompt.
            locale: BCP 47 locale for TTS language hint.

        Returns:
            Updated list with audio_prompt populated per question where
            synthesis succeeded. Questions where synthesis fails are
            returned with audio_prompt=None and a warning is logged.
        """
        result: list[AudioQuestion] = []
        for q in questions:
            try:
                synthesis = await self._synthesizer.synthesize(  # type: ignore[union-attr]
                    q.label,
                    language=locale if locale != "en" else None,
                )
                # model_copy preserves the FEAT-236 voice fields.
                result.append(q.model_copy(update={"audio_prompt": synthesis.audio}))
            except Exception as exc:
                self.logger.warning(
                    "TTS synthesis failed for field %s: %s", q.field_id, exc
                )
                result.append(q)
        return result
