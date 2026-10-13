"""AudioFormRenderer — Standalone audio form renderer for parrot-formdesigner.

Converts a FormSchema into an AudioFormManifest — a sequential list of
questions suitable for a voice-driven Q&A session over WebSocket.

The renderer is registered under the "audio" format key and is discoverable
at GET /api/v1/forms/{form_uid}/render/audio.

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
from ..audio.narration.engine import render_author_prompt
from ..core.llm_validation import llm_validation_enabled
from ..core.schema import FormField, FormSchema, FormSubsection, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from ..core.voice import field_voice_meta, is_sensitive
from .base import AbstractFormRenderer

if TYPE_CHECKING:
    from parrot.voice.tts.synthesizer import VoiceSynthesizer

logger = logging.getLogger(__name__)

# Field types that should be excluded from the audio question list (FEAT-236).
# Only HIDDEN is dropped — it is never user-visible. Every other field becomes
# a question tagged with its VoiceMode so no required field is ever lost.
_SKIP_FIELD_TYPES: frozenset[FieldType] = frozenset({FieldType.HIDDEN})

# Field types that carry options (SELECT / MULTI_SELECT).
_SELECT_TYPES: frozenset[FieldType] = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})

# FEAT-236 voice-capability taxonomy (spec §2 pillar 2). Field types not listed
# in either set default to VoiceMode.VOICE (narrate + spoken/typed answer).
# FEAT-448 (TASK-2337) additions: SEARCH (an option-based, DYNAMIC_SELECT-like
# pick) and COLOR_PICKER (same posture as COLOR) join _PROMPT_SELECT_TYPES;
# MASKED, EMOJI and CRON are plain scalar strings and are left to the VOICE
# default, same posture as TEXT/PHONE/EMAIL above.
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
        FieldType.SEARCH,
        FieldType.COLOR_PICKER,
    }
)
# FEAT-448 (TASK-2337) additions: PLACE (LOCATION's cascade), TREE_SELECT
# (TRANSFER_LIST's hierarchy), SIGNATURE_PAD (same shape as SIGNATURE),
# CREDIT_CARD (structured object, security-sensitive), IMAGE_DROPZONE and
# MULTI_UPLOAD (FILE-like), and AI_CAPTURE (unconstrained third-party
# payload) — none of these has a sensible spoken/typed answer.
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
        FieldType.PLACE,
        FieldType.TREE_SELECT,
        FieldType.SIGNATURE_PAD,
        FieldType.CREDIT_CARD,
        FieldType.IMAGE_DROPZONE,
        FieldType.MULTI_UPLOAD,
        FieldType.AI_CAPTURE,
    }
)

# Maps a VoiceMode to the client-facing render hint carried on the question.
_RENDER_MODE_BY_VOICE: dict[VoiceMode, str] = {
    VoiceMode.VOICE: "voice",
    VoiceMode.PROMPT_SELECT: "select",
    VoiceMode.VISUAL_FALLBACK: "visual",
}

# FEAT-649: how a question may be answered, per VoiceMode (client hint; engine enforces).
_ANSWER_MODES_BY_VOICE: dict[VoiceMode, list[str]] = {
    VoiceMode.VOICE: ["voice", "text"],
    VoiceMode.PROMPT_SELECT: ["voice", "selection"],
    VoiceMode.VISUAL_FALLBACK: ["control"],
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
    # Everything else (text-like fields, plus FieldType.AUDIO — which is itself a
    # voice-recorded answer) defaults to VOICE. AUDIO is intentionally VOICE, not
    # VISUAL_FALLBACK: it is answered by speaking/recording, not a visual control.
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
        logger.warning("parrot.voice TTS stack unavailable (%s); audio runs text-only", exc)
        return None

    backend = config.tts_backend if config is not None else "supertonic"
    voice = config.tts_voice if config is not None else None
    mime_format = config.tts_mime_format if config is not None else "audio/wav"
    return VoiceSynthesizer(TTSConfig(backend=backend, voice=voice, mime_format=mime_format))


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
        logger.warning("parrot.voice TTS stack unavailable (%s); text-only synthesis", exc)
        return None

    preferred = config.tts_backend if config is not None else "supertonic"
    voice = config.tts_voice if config is not None else None
    mime_format = config.tts_mime_format if config is not None else "audio/wav"

    # Preferred backend first, then Google as a fallback (deduplicated).
    backends = [preferred] + [b for b in ("google",) if b != preferred]
    for backend in backends:
        synth = VoiceSynthesizer(TTSConfig(backend=backend, voice=voice, mime_format=mime_format))
        try:
            result = await synth.synthesize(text, language=language)
            return result.audio
        except Exception as exc:  # noqa: BLE001 — never raise (FEAT-231 contract)
            # Backends raise a variety of types when misconfigured (missing
            # extra/weights → ImportError/ValueError/RuntimeError; live provider
            # errors → domain-specific exceptions). Catch broadly so a TTS
            # failure always degrades to the next backend / text-only.
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
        manifest = result.content  # dict with form_uid, questions, ws_endpoint, ...
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

        Each question carries its section/subsection context (GROUP children
        inherit the parent's). ``required`` is the static ``field.required``;
        the dynamic value is applied by the planner from ``RuleResolution.required``.

        Returns:
            Ordered list of AudioQuestion objects, one per voiced field.
        """
        questions: list[AudioQuestion] = []
        for section in form.sections:
            ctx: dict[str, Any] = {
                "section_uid": section.section_uid,
                "section_title": _resolve(section.title, locale) or None,
                "subsection_title": None,
            }
            for item in section.fields:
                if isinstance(item, FormSubsection):
                    sub_ctx = {**ctx, "subsection_title": _resolve(item.title, locale) or None}
                    for field in item.fields:
                        questions.extend(self._field_to_questions(field, locale=locale, form=form, context=sub_ctx))
                else:
                    questions.extend(self._field_to_questions(item, locale=locale, form=form, context=ctx))

        total = len(questions)
        result: list[AudioQuestion] = []
        for index, q in enumerate(questions):
            # model_copy preserves the FEAT-236 voice fields.
            update: dict[str, Any] = {"index": index}
            if q.voice_meta is not None and q.voice_meta.prompt:
                update["prompt"] = render_author_prompt(
                    q.voice_meta.prompt,
                    label=q.label,
                    hint=q.hint or "",
                    section=q.section_title or "",
                    n=index + 1,
                    total=total,
                )
            result.append(q.model_copy(update=update))
        return result

    def _field_to_questions(
        self,
        field: FormField,
        *,
        locale: str = "en",
        form: FormSchema | None = None,
        context: dict[str, Any] | None = None,
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
                result.extend(self._field_to_questions(child, locale=locale, form=form, context=context))
            return result

        label = _resolve(field.label, locale)
        description = _resolve(field.description, locale) or None

        options: list[dict] | None = None
        if field.options:
            options = [
                {
                    "value": opt.value,
                    "label": _resolve(opt.label, locale),
                    "disabled": opt.disabled,
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
        sensitive = is_sensitive(field)

        # FEAT-488: Propagate accept_content_types from FormField to AudioQuestion.
        # When set, the client may submit a VoiceAnswerEnvelope dict instead of
        # a plain string.
        accept_content_types = field.accept_content_types
        answer_envelope = field.answer_envelope

        voice_meta = field_voice_meta(field, logger=self.logger)
        hint = _resolve(field.hint, locale) or None
        answer_modes = list(_ANSWER_MODES_BY_VOICE[voice_mode])
        if field.field_type == FieldType.AUDIO:
            answer_modes = ["audio"]  # recorded answer
        llm_flag = llm_validation_enabled(form, field) if form is not None else bool(field.llm_validation)
        ctx = context or {}
        section_uid = ctx.get("section_uid")

        return [
            AudioQuestion(
                index=0,  # re-indexed by caller
                field_id=field.field_id,
                field_uid=field.field_uid,
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
                accept_content_types=accept_content_types,
                answer_envelope=answer_envelope,
                section_uid=str(section_uid) if section_uid is not None else None,
                section_title=ctx.get("section_title"),
                subsection_title=ctx.get("subsection_title"),
                hint=hint,
                ui_cue=voice_meta.ui_cue,
                answer_modes=answer_modes,
                voice_meta=voice_meta,
                llm_validation=llm_flag,
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

        Note:
            ``FormField.relation`` (FEAT-456) is intentionally ignored — a
            relational field renders exactly as its ``field_type`` dictates,
            byte-identical to the same field without ``relation``. Only
            ``JsonSchemaRenderer`` surfaces it.
        """
        questions = self.split_into_questions(form, locale=locale)

        # Pre-synthesize TTS audio if a synthesizer is available.
        if self._synthesizer is not None:
            questions = await self._synthesize_questions(questions, locale=locale)

        # FEAT-421: the audio WS route is tenant-qualified. `form.tenant` is
        # set by every write path that can reach this renderer (create/
        # edit/patch/update all construct FormSchema with an explicit
        # tenant=), the same invariant handlers.py's _assert_form_tenant
        # relies on.
        ws_endpoint = f"/api/v1/{form.tenant or ''}/forms/{form.form_uid}/audio/ws"
        form_title = _resolve(form.title, locale) if form.title else form.form_id

        manifest = AudioFormManifest(
            # FEAT-393 (TASK-1995): form.form_uid is now uuid.UUID (was str
            # under FEAT-389); AudioFormManifest.form_uid stays a wire-facing
            # str field, so stringify explicitly.
            form_uid=str(form.form_uid),
            title=form_title,
            total_questions=len(questions),
            questions=questions,
            ws_endpoint=ws_endpoint,
            locale=locale,
        )

        # Serialize to dict; exclude audio_prompt bytes from JSON output.
        # mode="json" so field_uid (FEAT-393) and any other UUID values
        # serialize as strings instead of raw uuid.UUID objects.
        manifest_dict = manifest.model_dump(mode="json", exclude={"questions": {"__all__": {"audio_prompt"}}})

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
                self.logger.warning("TTS synthesis failed for field %s: %s", q.field_id, exc)
                result.append(q)
        return result
