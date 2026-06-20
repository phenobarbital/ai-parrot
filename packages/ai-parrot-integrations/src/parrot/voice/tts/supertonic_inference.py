"""
Supertonic ONNX inference wiring (4-graph flow-matching TTS).

The :class:`SupertonicTTSBackend` in ``supertonic_backend.py`` is intentionally
agnostic about the concrete Supertonic ONNX graph I/O — it exposes an
``inference_fn`` seam (FEAT-231 §8 R-deps). This module fills that seam for the
public **Supertonic-3** weights (``Supertone/supertonic-3`` on Hugging Face),
which ship the model split across four ONNX graphs run in sequence:

    text  --tokenise-->  text_ids ----------------------------------+
                                                                     |
    duration_predictor(text_ids, style_dp, text_mask)  -->  duration |
    text_encoder(text_ids, style_ttl, text_mask)        -->  text_emb |
    vector_estimator(noisy_latent, text_emb, ..., step) -->  latent   |  x total_step
    vocoder(latent)                                     -->  waveform <+

The math mirrors the upstream reference (``py/helper.py`` in
``supertone-inc/supertonic``); it is reimplemented here against
``numpy``/``onnxruntime`` only — no upstream package dependency.

Expected on-disk layout (as produced by ``make install-supertonic``)::

    <model_dir>/
    ├── onnx/
    │   ├── duration_predictor.onnx
    │   ├── text_encoder.onnx
    │   ├── vector_estimator.onnx
    │   ├── vocoder.onnx
    │   ├── tts.json              # config (sample_rate, chunk sizes, latent_dim)
    │   └── unicode_indexer.json  # codepoint -> token id table
    └── voice_styles/
        ├── M1.json … M5.json     # speaker style vectors (style_ttl + style_dp)
        └── F1.json … F5.json

``SUPERTONIC_MODEL_PATH`` (or ``model_dir=``) should point at ``<model_dir>``
(the directory that *contains* ``onnx/`` and ``voice_styles/``). Pointing it
directly at the ``onnx/`` directory is also tolerated. When neither is given,
the backend falls back to ``<BASE_DIR>/models/supertonic-3`` — exactly where
``make install-supertonic`` puts the weights — so a standard checkout works
with no configuration at all.

Added by FEAT-231 follow-up (Supertonic 4-graph inference wiring).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional
from unicodedata import normalize
import numpy as np
from navconfig import BASE_DIR
from .supertonic_backend import SupertonicTTSBackend

logger = logging.getLogger(__name__)

# Language tags understood by the Supertonic text front-end. The model wraps the
# text in ``<lang>…</lang>`` markers, so an unknown tag is downgraded to English
# rather than crashing a live synthesis request.
AVAILABLE_LANGS = frozenset(
    {
        "en",
        "ko",
        "ja",
        "ar",
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "es",
        "et",
        "fi",
        "fr",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "lt",
        "lv",
        "nl",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sv",
        "tr",
        "uk",
        "vi",
        "na",
    }
)

# ONNX graph filenames inside the resolved onnx directory.
_DP_ONNX = "duration_predictor.onnx"
_TEXT_ENC_ONNX = "text_encoder.onnx"
_VECTOR_EST_ONNX = "vector_estimator.onnx"
_VOCODER_ONNX = "vocoder.onnx"
_CFG_JSON = "tts.json"
_INDEXER_JSON = "unicode_indexer.json"


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``.

    Used to tune ONNX Runtime CPU parallelism without a code change. A blank
    or unparseable value yields ``default``.

    Args:
        name: Environment variable name.
        default: Value returned when unset or invalid.

    Returns:
        The parsed integer, or ``default``.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "☀-⛿"
    "✀-➿"
    "\U0001f1e6-\U0001f1ff]+",
    flags=re.UNICODE,
)

_CHAR_REPLACEMENTS = {
    "–": "-",
    "‑": "-",
    "—": "-",
    "_": " ",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "´": "'",
    "`": "'",
    "[": " ",
    "]": " ",
    "|": " ",
    "/": " ",
    "#": " ",
    "→": " ",
    "←": " ",
}
_EXPR_REPLACEMENTS = {"@": " at ", "e.g.,": "for example, ", "i.e.,": "that is, "}

# Sentence-boundary split that ignores common abbreviations (Mr., e.g., etc.).
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!Mr\.)(?<!Mrs\.)(?<!Ms\.)(?<!Dr\.)(?<!Prof\.)(?<!Sr\.)(?<!Jr\.)"
    r"(?<!Ph\.D\.)(?<!etc\.)(?<!e\.g\.)(?<!i\.e\.)(?<!vs\.)(?<!Inc\.)(?<!Ltd\.)"
    r"(?<!Co\.)(?<!Corp\.)(?<!St\.)(?<!Ave\.)(?<!Blvd\.)(?<!\b[A-Z]\.)(?<=[.!?])\s+"
)


# ---------------------------------------------------------------------------
# Pure helpers (mirror the upstream reference math)
# ---------------------------------------------------------------------------


def length_to_mask(lengths: np.ndarray, max_len: Optional[int] = None) -> np.ndarray:
    """Build a binary length mask of shape ``(B, 1, max_len)``.

    Args:
        lengths: Per-item valid lengths, shape ``(B,)``.
        max_len: Mask width; defaults to ``lengths.max()``.

    Returns:
        Float32 mask, ``1.0`` for valid positions and ``0.0`` for padding.
    """
    width = int(max_len if max_len is not None else lengths.max())
    ids = np.arange(0, width)
    mask = (ids < np.expand_dims(lengths, axis=1)).astype(np.float32)
    return mask.reshape(-1, 1, width)


def get_latent_mask(wav_lengths: np.ndarray, base_chunk_size: int, chunk_compress_factor: int) -> np.ndarray:
    """Mask the latent sequence to the per-item audio length.

    Args:
        wav_lengths: Per-item waveform sample counts, shape ``(B,)``.
        base_chunk_size: Vocoder base chunk size (samples per latent frame).
        chunk_compress_factor: Latent compression factor from the config.

    Returns:
        Latent mask of shape ``(B, 1, latent_len)``.
    """
    latent_size = base_chunk_size * chunk_compress_factor
    latent_lengths = (wav_lengths + latent_size - 1) // latent_size
    return length_to_mask(latent_lengths)


def chunk_text(text: str, max_len: int = 300) -> list[str]:
    """Split text into synthesis-sized chunks by paragraph then sentence.

    Long agent answers are split so each chunk stays within the model's
    comfortable context; chunks are re-joined (with short silences) by the
    caller.

    Args:
        text: Input text.
        max_len: Maximum characters per chunk.

    Returns:
        Ordered list of non-empty chunk strings (at least one).
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs:
        sentences = _SENTENCE_SPLIT_RE.split(paragraph)
        current = ""
        for sentence in sentences:
            # A single sentence longer than max_len would otherwise pass through
            # whole, producing an oversized chunk the model cannot handle. Hard-
            # split it on word boundaries (and, as a last resort, mid-word).
            if len(sentence) > max_len:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(_split_oversized(sentence, max_len))
            elif len(current) + len(sentence) + 1 <= max_len:
                current += (" " if current else "") + sentence
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence
        if current:
            chunks.append(current.strip())
    return chunks or [text.strip()]


def _split_oversized(sentence: str, max_len: int) -> list[str]:
    """Break a single over-long sentence into chunks of at most ``max_len``.

    Splits on whitespace; a single token longer than ``max_len`` (e.g. a long
    URL or unbroken symbol run) is sliced mid-token so no chunk ever exceeds
    the limit.
    """
    out: list[str] = []
    current = ""
    for word in sentence.split():
        if len(word) > max_len:
            if current:
                out.append(current)
                current = ""
            for i in range(0, len(word), max_len):
                out.append(word[i : i + max_len])
        elif len(current) + len(word) + 1 <= max_len:
            current += (" " if current else "") + word
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# Tokeniser + speaker style
# ---------------------------------------------------------------------------


class UnicodeProcessor:
    """Codepoint-based text tokeniser for Supertonic.

    Normalises text, strips emojis, applies a small punctuation rewrite, wraps
    it in ``<lang>…</lang>`` markers, then maps each character's Unicode
    codepoint to a token id via ``unicode_indexer.json`` (a list indexed by
    codepoint, or a ``{codepoint: id}`` dict).
    """

    def __init__(self, unicode_indexer_path: str) -> None:
        """Load the codepoint→id table.

        Args:
            unicode_indexer_path: Path to ``unicode_indexer.json``.
        """
        with open(unicode_indexer_path, "r", encoding="utf-8") as fh:
            self.indexer = json.load(fh)
        self._is_dict = isinstance(self.indexer, dict)

    def _lookup(self, codepoint: int) -> int:
        """Map a Unicode codepoint to its token id (0 for out-of-table)."""
        if self._is_dict:
            return int(self.indexer.get(str(codepoint), 0))
        if 0 <= codepoint < len(self.indexer):
            return int(self.indexer[codepoint])
        return 0

    def _preprocess_text(self, text: str, lang: str) -> str:
        """Normalise and language-tag a single string (matches upstream)."""
        text = normalize("NFKD", text)
        text = _EMOJI_RE.sub("", text)
        for old, new in _CHAR_REPLACEMENTS.items():
            text = text.replace(old, new)
        text = re.sub(r"[♥☆♡©\\]", "", text)
        for old, new in _EXPR_REPLACEMENTS.items():
            text = text.replace(old, new)
        for punct in (",", ".", "!", "?", ";", ":", "'"):
            text = text.replace(f" {punct}", punct)
        for dup in ('""', "''", "``"):
            while dup in text:
                text = text.replace(dup, dup[0])
        text = re.sub(r"\s+", " ", text).strip()
        if not re.search(r"[.!?;:,'\"')\]}…。」』【〉》›»]$", text):
            text += "."
        if lang not in AVAILABLE_LANGS:
            lang = "en"
        return f"<{lang}>{text}</{lang}>"

    def __call__(self, text_list: list[str], lang_list: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Tokenise a batch of strings.

        Args:
            text_list: Raw strings.
            lang_list: Parallel language tags.

        Returns:
            ``(text_ids, text_mask)`` — int64 ids ``(B, L)`` and the
            float32 length mask ``(B, 1, L)``.
        """
        processed = [self._preprocess_text(t, lang) for t, lang in zip(text_list, lang_list)]
        lengths = np.array([len(t) for t in processed], dtype=np.int64)
        text_ids = np.zeros((len(processed), int(lengths.max())), dtype=np.int64)
        for i, t in enumerate(processed):
            codepoints = np.array([ord(c) for c in t], dtype=np.uint16)
            text_ids[i, : len(codepoints)] = [self._lookup(int(cp)) for cp in codepoints]
        return text_ids, length_to_mask(lengths)


class Style:
    """A speaker style: the two conditioning tensors Supertonic consumes.

    Attributes:
        ttl: ``style_ttl`` tensor (text-encoder / vector-estimator conditioning).
        dp: ``style_dp`` tensor (duration-predictor conditioning).
    """

    __slots__ = ("ttl", "dp")

    def __init__(self, ttl: np.ndarray, dp: np.ndarray) -> None:
        self.ttl = ttl
        self.dp = dp


def load_voice_style(path: str) -> Style:
    """Load a single voice-style JSON into a batch-of-one :class:`Style`.

    The JSON carries ``style_ttl``/``style_dp`` as ``{"dims": [...],
    "data": [...]}`` blocks; ``data`` is reshaped to ``dims[1:]`` and given a
    leading batch axis.

    Args:
        path: Path to a ``voice_styles/<name>.json`` file.

    Returns:
        A :class:`Style` with batch size 1.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    ttl_dims = raw["style_ttl"]["dims"]
    dp_dims = raw["style_dp"]["dims"]
    ttl = np.array(raw["style_ttl"]["data"], dtype=np.float32).reshape(1, ttl_dims[1], ttl_dims[2])
    dp = np.array(raw["style_dp"]["data"], dtype=np.float32).reshape(1, dp_dims[1], dp_dims[2])
    return Style(ttl, dp)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class SupertonicPipeline:
    """Runs the Supertonic-3 four-graph pipeline and returns raw PCM.

    The instance is **callable** with the signature
    ``SupertonicTTSBackend`` expects for ``inference_fn``::

        pipeline(session, text, *, voice, language, sample_rate) -> bytes

    The ``session`` and ``sample_rate`` arguments are ignored (the pipeline
    owns its own four ONNX sessions and reports its native sample rate via
    :attr:`sample_rate`); they exist only to satisfy the seam contract.

    Loading is eager — the constructor opens all four ONNX sessions, the
    config and the tokeniser table — so build it lazily (e.g. from the
    backend's ``_ensure_session``) to keep object construction cheap.

    Args:
        model_dir: Directory containing ``onnx/`` and ``voice_styles/`` (or the
            ``onnx`` directory itself).
        onnx_subdir: Name of the ONNX subdirectory under ``model_dir``.
        voice_styles_subdir: Name of the voice-styles subdirectory.
        default_voice: Voice id used when the caller passes ``None``.
        total_step: Number of flow-matching denoising steps (higher = smoother,
            slower). Upstream default is 8.
        speed: Speech-rate multiplier (>1 = faster). Upstream default is 1.05.
        use_gpu: Reserved; CPU execution only for now.
    """

    # The vector-estimator's rotary attention table is exported with a fixed
    # maximum sequence length (~1000 latent positions). A pathological duration
    # prediction (e.g. dense symbol soup that slipped past the text sanitiser)
    # can produce a latent_len beyond that, which crashes the ONNX kernel with
    # an opaque broadcast error ("1000 by <N>"). We clamp the predicted duration
    # so latent_len never exceeds this limit. Kept a touch below the true 1000
    # for ceil() headroom.
    _MAX_LATENT_LEN: int = 990

    def __init__(
        self,
        model_dir: str,
        *,
        onnx_subdir: str = "onnx",
        voice_styles_subdir: str = "voice_styles",
        default_voice: str = "M1",
        total_step: int = 8,
        speed: float = 1.05,
        use_gpu: bool = False,
    ) -> None:
        try:
            import onnxruntime as ort  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - exercised via stub
            raise ImportError(
                "Supertonic ONNX inference requires 'onnxruntime'. Install the "
                "extra: pip install 'ai-parrot-integrations[voice-supertonic]'."
            ) from exc

        self.logger = logging.getLogger(__name__)
        self.default_voice = default_voice
        self.total_step = total_step
        self.speed = speed

        self.onnx_dir, self.voice_styles_dir = self._resolve_dirs(model_dir, onnx_subdir, voice_styles_subdir)

        with open(os.path.join(self.onnx_dir, _CFG_JSON), "r", encoding="utf-8") as fh:
            self.cfgs = json.load(fh)
        self.sample_rate = int(self.cfgs["ae"]["sample_rate"])
        self.base_chunk_size = int(self.cfgs["ae"]["base_chunk_size"])
        self.chunk_compress_factor = int(self.cfgs["ttl"]["chunk_compress_factor"])
        self.latent_dim = int(self.cfgs["ttl"]["latent_dim"])

        self.text_processor = UnicodeProcessor(os.path.join(self.onnx_dir, _INDEXER_JSON))

        providers = ["CPUExecutionProvider"]
        if use_gpu:  # pragma: no cover - not exercised in CI
            self.logger.warning(
                "SupertonicPipeline: use_gpu requested; falling back to CPU " "(GPU execution is not yet validated)."
            )
        opts = ort.SessionOptions()
        # Cap ONNX Runtime's CPU parallelism. By default ORT spawns an intra-op
        # pool sized to ALL physical cores PER graph; with four graphs running
        # back-to-back inside a worker thread that pegs every core at 100% and
        # starves the aiohttp event loop (the avatar made the whole server feel
        # frozen). A small, env-tunable cap leaves headroom for the loop while
        # keeping synthesis fast enough for real-time speech.
        _intra = _env_int("SUPERTONIC_ORT_INTRA_OP_THREADS", 2)
        if _intra > 0:
            opts.intra_op_num_threads = _intra
        opts.inter_op_num_threads = _env_int("SUPERTONIC_ORT_INTER_OP_THREADS", 1)

        def _load(name: str) -> "ort.InferenceSession":
            return ort.InferenceSession(os.path.join(self.onnx_dir, name), sess_options=opts, providers=providers)

        self.logger.info("SupertonicPipeline: loading ONNX graphs from %s", self.onnx_dir)
        self.dp_ort = _load(_DP_ONNX)
        self.text_enc_ort = _load(_TEXT_ENC_ONNX)
        self.vector_est_ort = _load(_VECTOR_EST_ONNX)
        self.vocoder_ort = _load(_VOCODER_ONNX)
        self._style_cache: dict[str, Style] = {}
        self.logger.info(
            "SupertonicPipeline: ready (sample_rate=%d, voices_dir=%s)",
            self.sample_rate,
            self.voice_styles_dir,
        )

    # -- resolution helpers --------------------------------------------------

    @staticmethod
    def _resolve_dirs(model_dir: str, onnx_subdir: str, voice_styles_subdir: str) -> tuple[str, str]:
        """Locate the onnx/ and voice_styles/ directories.

        Accepts either the repo root (containing ``onnx/``) or the ``onnx``
        directory itself.

        Returns:
            ``(onnx_dir, voice_styles_dir)`` absolute-ish paths.

        Raises:
            ValueError: If the ONNX graphs cannot be located.
        """
        model_dir = os.path.expanduser(model_dir)
        nested = os.path.join(model_dir, onnx_subdir)
        if os.path.isfile(os.path.join(nested, _VOCODER_ONNX)):
            onnx_dir = nested
            voice_dir = os.path.join(model_dir, voice_styles_subdir)
        elif os.path.isfile(os.path.join(model_dir, _VOCODER_ONNX)):
            # model_dir already IS the onnx directory; styles live next to it.
            onnx_dir = model_dir
            voice_dir = os.path.join(os.path.dirname(model_dir), voice_styles_subdir)
        else:
            raise ValueError(
                f"Supertonic ONNX graphs not found under '{model_dir}'. Expected "
                f"'{onnx_subdir}/{_VOCODER_ONNX}' (run `make install-supertonic`)."
            )
        return onnx_dir, voice_dir

    def _resolve_voice_path(self, voice: Optional[str]) -> str:
        """Resolve a voice id / filename / path to a voice-style JSON path."""
        name = voice or self.default_voice
        if os.path.isfile(name):
            return name
        candidate = os.path.join(self.voice_styles_dir, f"{name}.json")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(self.voice_styles_dir, name)
        if os.path.isfile(candidate):
            return candidate
        raise ValueError(f"Supertonic voice style '{name}' not found in {self.voice_styles_dir}")

    def _get_style(self, voice: Optional[str]) -> Style:
        """Return the (cached) :class:`Style` for a voice id."""
        path = self._resolve_voice_path(voice)
        cached = self._style_cache.get(path)
        if cached is None:
            cached = load_voice_style(path)
            self._style_cache[path] = cached
        return cached

    # -- inference -----------------------------------------------------------

    def _sample_noisy_latent(self, duration: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Draw the initial noisy latent and its mask for the CFM loop."""
        bsz = len(duration)
        wav_len_max = float(duration.max()) * self.sample_rate
        wav_lengths = (duration * self.sample_rate).astype(np.int64)
        chunk_size = self.base_chunk_size * self.chunk_compress_factor
        latent_len = int((wav_len_max + chunk_size - 1) // chunk_size)
        latent_dim = self.latent_dim * self.chunk_compress_factor
        noisy = np.random.randn(bsz, latent_dim, latent_len).astype(np.float32)
        latent_mask = get_latent_mask(wav_lengths, self.base_chunk_size, self.chunk_compress_factor)
        return noisy * latent_mask, latent_mask

    def _infer_chunk(self, text: str, lang: str, style: Style) -> tuple[np.ndarray, np.ndarray]:
        """Run the four graphs for one (single-item) text chunk.

        Returns:
            ``(wav, duration)`` — float32 waveform ``(1, T)`` and duration
            ``(1,)`` in seconds.
        """
        text_ids, text_mask = self.text_processor([text], [lang])

        # 1) Duration predictor -> seconds, scaled by speed.
        duration, *_ = self.dp_ort.run(None, {"text_ids": text_ids, "style_dp": style.dp, "text_mask": text_mask})
        duration = duration / self.speed

        # Clamp the predicted duration so the resulting latent_len stays within
        # the vector estimator's positional limit (see _MAX_LATENT_LEN). Without
        # this, an over-long duration crashes the ORT kernel with an opaque
        # broadcast error; clamping truncates the audio instead.
        chunk_size = self.base_chunk_size * self.chunk_compress_factor
        max_duration = self._MAX_LATENT_LEN * chunk_size / self.sample_rate
        if float(duration.max()) > max_duration:
            self.logger.warning(
                "SupertonicPipeline: predicted duration %.1fs exceeds model "
                "limit %.1fs for a %d-char chunk; clamping (audio truncated).",
                float(duration.max()),
                max_duration,
                len(text),
            )
            duration = np.minimum(duration, max_duration)

        # 2) Text encoder -> text embedding.
        text_emb, *_ = self.text_enc_ort.run(
            None,
            {"text_ids": text_ids, "style_ttl": style.ttl, "text_mask": text_mask},
        )

        # 3) Vector estimator: iterative flow-matching denoising.
        xt, latent_mask = self._sample_noisy_latent(duration)
        total_step_np = np.array([self.total_step], dtype=np.float32)
        for step in range(self.total_step):
            current_step = np.array([step], dtype=np.float32)
            xt, *_ = self.vector_est_ort.run(
                None,
                {
                    "noisy_latent": xt,
                    "text_emb": text_emb,
                    "style_ttl": style.ttl,
                    "text_mask": text_mask,
                    "latent_mask": latent_mask,
                    "current_step": current_step,
                    "total_step": total_step_np,
                },
            )

        # 4) Vocoder -> waveform.
        wav, *_ = self.vocoder_ort.run(None, {"latent": xt})
        return wav, duration

    def synthesize_pcm(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        silence_duration: float = 0.3,
    ) -> bytes:
        """Synthesize ``text`` to raw PCM (16-bit LE mono at :attr:`sample_rate`).

        Long text is chunked, synthesized chunk-by-chunk, and concatenated with
        short silences. The final waveform is trimmed to the predicted total
        duration and quantised to int16.

        Args:
            text: Text to speak (non-empty).
            voice: Voice id (``M1``..``M5`` / ``F1``..``F5``), a filename, or a
                path. ``None`` uses :attr:`default_voice`.
            language: BCP-47 tag; only the primary subtag is used and unknown
                languages fall back to English.
            silence_duration: Gap inserted between chunks, in seconds.

        Returns:
            Raw PCM bytes (16-bit little-endian, mono).
        """
        lang = (language or "en").split("-")[0].lower()
        if lang not in AVAILABLE_LANGS:
            self.logger.warning("SupertonicPipeline: language '%s' unsupported; using 'en'.", language)
            lang = "en"

        style = self._get_style(voice)
        max_len = 120 if lang in ("ko", "ja") else 300

        wav_cat: Optional[np.ndarray] = None
        total_seconds = 0.0
        for chunk in chunk_text(text, max_len=max_len):
            if not chunk:
                continue
            wav, duration = self._infer_chunk(chunk, lang, style)
            if wav_cat is None:
                wav_cat = wav
                total_seconds = float(duration[0])
            else:
                silence = np.zeros((1, int(silence_duration * self.sample_rate)), dtype=np.float32)
                wav_cat = np.concatenate([wav_cat, silence, wav], axis=1)
                total_seconds += float(duration[0]) + silence_duration

        if wav_cat is None:
            return b""

        trimmed = wav_cat[0, : int(self.sample_rate * total_seconds)]
        pcm = np.clip(trimmed, -1.0, 1.0)
        return (pcm * 32767.0).astype("<i2").tobytes()

    def __call__(
        self,
        session=None,
        text: str = "",
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> bytes:
        """``inference_fn`` adapter — see :meth:`synthesize_pcm`.

        ``session`` and ``sample_rate`` are accepted for contract compatibility
        and ignored (the pipeline owns its own sessions and sample rate).
        """
        return self.synthesize_pcm(text, voice=voice, language=language)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class SupertonicONNXBackend(SupertonicTTSBackend):
    """:class:`SupertonicTTSBackend` wired for the real Supertonic-3 weights.

    Overrides session creation to load the four-graph
    :class:`SupertonicPipeline` and bind it as the backend's ``inference_fn``.
    Everything else (async offload, WAV wrapping, empty-text guard, truthful
    ``mime_format``) is inherited unchanged.

    Construction stays cheap — the heavy ONNX load happens lazily on the first
    ``synthesize`` call, via :meth:`_ensure_session`.

    Args:
        model_dir: Directory with ``onnx/`` and ``voice_styles/``. Defaults to
            ``SUPERTONIC_MODEL_PATH``.
        voice: Default voice id (``M1``..``F5``). ``None`` → ``default_voice``.
        onnx_subdir: ONNX subdirectory name.
        voice_styles_subdir: Voice-styles subdirectory name.
        default_voice: Voice used when neither ``voice`` nor the call supplies one.
        total_step: Flow-matching denoising steps.
        speed: Speech-rate multiplier.
        use_gpu: Reserved (CPU only).
        **kwargs: Forwarded to :class:`SupertonicTTSBackend`.
    """

    def __init__(
        self,
        *,
        model_dir: Optional[str] = None,
        voice: Optional[str] = None,
        onnx_subdir: str = "onnx",
        voice_styles_subdir: str = "voice_styles",
        default_voice: str = "M1",
        total_step: int = 8,
        speed: float = 1.05,
        use_gpu: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(voice=voice, model_path=model_dir, **kwargs)
        self._onnx_subdir = onnx_subdir
        self._voice_styles_subdir = voice_styles_subdir
        self._default_voice = default_voice
        self._total_step = total_step
        self._speed = speed
        self._use_gpu = use_gpu
        self._pipeline: Optional[SupertonicPipeline] = None

    def _resolve_model_dir(self) -> str:
        """Resolve the model directory, validated.

        Resolution order:
            1. the ``model_dir=`` constructor argument,
            2. the ``SUPERTONIC_MODEL_PATH`` environment variable,
            3. ``<BASE_DIR>/models/supertonic-3`` — where
               ``make install-supertonic`` downloads the weights, so a standard
               checkout needs no configuration.

        Raises:
            ValueError: If the resolved directory does not exist.
        """
        path = self.model_path or os.environ.get("SUPERTONIC_MODEL_PATH") or str(BASE_DIR / "models" / "supertonic-3")
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            raise ValueError(
                f"Supertonic model directory not found: {path}. Run "
                "`make install-supertonic`, pass model_dir=..., or set "
                "SUPERTONIC_MODEL_PATH."
            )
        return path

    def _ensure_session(self) -> None:
        """Lazily build the four-graph pipeline and wire it as ``inference_fn``.

        Overrides the base single-session loader: Supertonic-3 is four graphs,
        so the pipeline manages its own sessions. The base ``_synthesize_sync``
        then drives it through the inherited ``inference_fn`` seam.

        Raises:
            ImportError: If ``onnxruntime`` (the ``voice-supertonic`` extra) is
                not installed.
            ValueError: If the resolved model directory does not exist.
        """
        if self._inference_fn is not None:
            return
        model_dir = self._resolve_model_dir()
        pipeline = SupertonicPipeline(
            model_dir,
            onnx_subdir=self._onnx_subdir,
            voice_styles_subdir=self._voice_styles_subdir,
            default_voice=self._default_voice,
            total_step=self._total_step,
            speed=self._speed,
            use_gpu=self._use_gpu,
        )
        self._pipeline = pipeline
        # Align the WAV header sample rate with the model's native rate.
        self.sample_rate = pipeline.sample_rate
        # Non-None session sentinel + the inference callable the base expects.
        self._session = pipeline
        self._inference_fn = pipeline
