from typing import Any, Union, List, Optional
from collections.abc import Callable
from abc import abstractmethod
import gc
import os
import logging
import math
from pathlib import Path
from moviepy import VideoFileClip
from pydub import AudioSegment
import soundfile as sf
import numpy as np
import whisperx
import torch
from transformers import (
    pipeline,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    WhisperProcessor,
    WhisperForConditionalGeneration
)
from ..conf import HUGGINGFACEHUB_API_TOKEN
from ..stores.models import Document
from .abstract import AbstractLoader


torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True


logging.getLogger(name='numba').setLevel(logging.WARNING)
logging.getLogger(name='pydub.converter').setLevel(logging.WARNING)

def extract_video_id(url):
    parts = url.split("?v=")
    video_id = parts[1].split("&")[0]
    return video_id

def _fmt_srt_time(t: float) -> str:
    hrs, rem = divmod(int(t), 3600)
    mins, secs = divmod(rem, 60)
    ms = int((t - int(t)) * 1000)
    return f"{hrs:02}:{mins:02}:{secs:02},{ms:03}"


class BaseVideoLoader(AbstractLoader):
    """
    Generating Video transcripts from Videos.
    """
    extensions: List[str] = ['.youtube']
    encoding = 'utf-8'

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'video',
        language: str = "en",
        video_path: Union[str, Path] = None,
        download_video: bool = True,
        diarization: bool = False,
        **kwargs
    ):
        self._download_video: bool = download_video
        self._diarization: bool = diarization
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        if isinstance(source, str):
            self.urls = [source]
        else:
            self.urls = source
        self._task = kwargs.get('task', "automatic-speech-recognition")
        # Topics:
        self.topics: list = kwargs.get('topics', [])
        self._model_size: str = kwargs.get('model_size', 'small')
        self.summarization_model = "facebook/bart-large-cnn"
        self._model_name: str = kwargs.get('model_name', 'whisper')
        device, _, dtype = self._get_device()
        self.summarizer = pipeline(
            "summarization",
            tokenizer=AutoTokenizer.from_pretrained(
                self.summarization_model
            ),
            model=AutoModelForSeq2SeqLM.from_pretrained(
                self.summarization_model
            ),
            device=device,
            torch_dtype=dtype,
        )
        # language:
        self._language = language
        # directory:
        if isinstance(video_path, str):
            self._video_path = Path(video_path).resolve()
        self._video_path = video_path

    def transcript_to_vtt(self, transcript: str, transcript_path: Path) -> str:
        """
        Convert a transcript to VTT format.
        """
        vtt = "WEBVTT\n\n"
        for i, chunk in enumerate(transcript['chunks'], start=1):
            start, end = chunk['timestamp']
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces

            if start is None or end is None:
                print(f"Warning: Missing timestamp for chunk {i}, skipping this chunk.")
                continue

            # Convert timestamps to WebVTT format (HH:MM:SS.MMM)
            start_vtt = f"{int(start // 3600):02}:{int(start % 3600 // 60):02}:{int(start % 60):02}.{int(start * 1000 % 1000):03}"  # noqa
            end_vtt = f"{int(end // 3600):02}:{int(end % 3600 // 60):02}:{int(end % 60):02}.{int(end * 1000 % 1000):03}"  # noqa

            vtt += f"{i}\n{start_vtt} --> {end_vtt}\n{text}\n\n"
        # Save the VTT file
        try:
            with open(str(transcript_path), "w") as f:
                f.write(vtt)
            print(f'Saved VTT File on {transcript_path}')
        except Exception as exc:
            print(f"Error saving VTT file: {exc}")
        return vtt

    def audio_to_srt(
        self,
        audio_path: Path,
        asr=None,                        # expects output of get_whisper_transcript() above
        speaker_names=None,              # e.g. ["Bot","Agent","Customer"]
        output_srt_path=None,
        pyannote_token: str = None,
        max_gap_s: float = 0.5,
        max_chars: int = 90,
        max_duration_s: float = 8.0,
        min_speakers: int = 1,
        max_speakers: int = 2,
        speaker_corrections: dict = None,  # Manual corrections for specific segments
        merge_short_segments: bool = True,  # Merge very short adjacent segments
        min_segment_duration: float = 0.5,  # Minimum duration for a segment
    ):
        """
        Build an SRT subtitle string from a call recording using WhisperX-aligned words and
        Pyannote-based diarization (speaker attribution). Optionally writes the result to disk.

        This function consumes a WhisperX-style transcript (with word-level timestamps),
        performs speaker diarization (optionally constrained to a given speaker count),
        assigns speakers to words, and groups words into readable subtitle segments with
        length, gap, and duration constraints.

        Parameters
        ----------
        audio_path : pathlib.Path
            Path to the audio file used for diarization (e.g., preconverted mono 16 kHz WAV).
            Even if `asr` is provided, this file is required to run the diarization pipeline.
        asr : dict, optional
            WhisperX transcript object containing aligned segments and words.
            Expected schema:
                {
                "text": "...",
                "language": "en",
                "chunks": [
                    {
                    "text": "utterance text",
                    "timestamp": (start: float, end: float),
                    "words": [
                        {"word": "Hello", "start": 0.50, "end": 0.72},
                        ...
                    ]
                    },
                    ...
                ]
                }
            If None or missing `chunks`, a ValueError is raised.
        speaker_names : list[str] | tuple[str] | None, optional
            Friendly labels to apply to speakers in **first-appearance order** after diarization.
            For example, `["Bot", "Agent", "Customer"]`. If not provided, WhisperX/Pyannote
            speaker IDs (e.g., "SPEAKER_00") are used as-is. If the number of detected
            speakers exceeds this list, remaining speakers retain their original IDs.
        output_srt_path : str | pathlib.Path | None, optional
            If provided, the generated SRT text is written to this path (UTF-8). If omitted,
            nothing is written to disk.
        pyannote_token : str | None, optional
            Hugging Face access token used by Pyannote diarization models. If not provided,
            the function attempts to read it from the `PYANNOTE_AUDIO_AUTH` environment variable.
            Required for diarization.
        max_gap_s : float, default=0.5
            Maximum allowed *silence* between consecutive words when aggregating them into a
            single SRT subtitle line. A larger value yields longer lines; a smaller value
            creates more, shorter lines.
        max_chars : int, default=90
            Soft limit on the number of characters per SRT subtitle line. When adding the next
            word would exceed this threshold, a new subtitle block is started.
        max_duration_s : float, default=8.0
            Maximum duration (seconds) permitted for a single subtitle block. If adding the next
            word would exceed this duration, a new block is started.
        min_speakers : int, default=1
            Lower bound on the number of speakers provided to the diarization pipeline.
            Useful to avoid the "everything merges into one speaker" failure mode.
        max_speakers : int, default=2
            Upper bound on the number of speakers provided to the diarization pipeline.
            Set both `min_speakers` and `max_speakers` to the exact expected number (e.g., 3)
            to force a fixed speaker count.
        speaker_corrections : dict | None, optional
            Mapping to apply manual, deterministic speaker fixes after diarization and before
            SRT grouping. The expected shape is flexible, but a common pattern is:
                {
                # remap entire diarized IDs
                "SPEAKER_00": "Bot",
                # or time-bounded corrections
                (start_s, end_s): "Customer"
                }
            When keys are tuples (start, end), any words whose timestamps fall within that
            interval are reassigned to the specified label/ID.
        merge_short_segments : bool, default=True
            If True, very short adjacent subtitle segments (e.g., created by rapid speaker
            switches or punctuation) may be merged when safe (same speaker, small gap, within
            `max_chars` and `max_duration_s`), improving readability.
        min_segment_duration : float, default=0.5
            Minimum duration (seconds) target when merging very short segments. Only applies
            if `merge_short_segments=True`.

        Returns
        -------
        str
            A UTF-8 string containing the SRT-formatted transcript with speaker labels, where
            each subtitle block follows the standard:
                <index>
                HH:MM:SS,mmm --> HH:MM:SS,mmm
                <Speaker>: <text>
            If `output_srt_path` is provided, the same content is also written to that file.

        Raises
        ------
        ValueError
            If `asr` is None or does not contain a `chunks` list with valid timestamps.
        RuntimeError
            If the diarization pipeline cannot be initialized (e.g., missing `pyannote_token`)
            or if internal alignment/speaker assignment fails unexpectedly.
        FileNotFoundError
            If `audio_path` does not exist.

        Notes
        -----
        - **Word-level accuracy**: Speaker assignment happens per word (not per sentence),
        allowing accurate handling of interruptions and fast turn-taking.
        - **Speaker mapping**: If `speaker_names` is provided, the first diarized speaker to
        appear in time is mapped to `speaker_names[0]`, the second to `[1]`, etc.
        - **Determinism**: Pyannote diarization can be non-deterministic across environments.
        Pinning dependency versions and disabling/controlling TF32 may help reproducibility.
        - **Performance**: On low-VRAM systems, consider running diarization on CPU while
        keeping ASR/alignment on GPU. The function itself is agnostic to device placement
        as long as the underlying pipeline is configured accordingly.

        Examples
        --------
        Basic usage with forced 3 speakers and file output:

        >>> srt = self.audio_to_srt(
        ...     audio_path=Path("call_16k_mono.wav"),
        ...     asr=transcript,  # from get_whisper_transcript() / WhisperX
        ...     speaker_names=["Bot", "Agent", "Customer"],
        ...     output_srt_path="call.srt",
        ...     pyannote_token=os.environ["PYANNOTE_AUDIO_AUTH"],
        ...     min_speakers=3, max_speakers=3,
        ... )

        Apply manual speaker correction for the first 8 seconds as "Bot":

        >>> srt = self.audio_to_srt(
        ...     audio_path=Path("call.wav"),
        ...     asr=transcript,
        ...     pyannote_token=token,
        ...     speaker_corrections={(0.0, 8.0): "Bot"},
        ... )

        Tighter line grouping (shorter blocks):

        >>> srt = self.audio_to_srt(
        ...     audio_path=Path("call.wav"),
        ...     asr=transcript,
        ...     pyannote_token=token,
        ...     max_gap_s=0.35, max_chars=70, max_duration_s=6.0,
        ... )
        """
        def _safe_float(x):
            try:
                xf = float(x)
                if math.isfinite(xf):
                    return xf
            except Exception:
                pass
            return None

        if not asr or not asr.get("chunks"):
            raise ValueError(
                "audio_to_srt requires the WhisperX transcript (chunks with words)."
            )

        # Use the existing _get_device method
        pipeline_idx, _, _ = self._get_device()
        # Determine device string for WhisperX/pyannote
        if isinstance(pipeline_idx, str):
            # MPS or other special device
            device = pipeline_idx
        elif pipeline_idx >= 0:
            # CUDA device
            device = f"cuda:{pipeline_idx}"
        else:
            # CPU
            device = "cpu"

        token = pyannote_token or HUGGINGFACEHUB_API_TOKEN
        if not token:
            raise RuntimeError(
                "Missing PYANNOTE token. Set PYANNOTE_AUDIO_AUTH or pass pyannote_token=..."
            )

        # 1) Run WhisperX diarization on the file
        try:
            diarizer = whisperx.diarize.DiarizationPipeline(
                use_auth_token=token,
                device=device
            )
        except Exception as e:
            if "mps" in str(e).lower() and device == "mps":
                print(f"[WhisperX] MPS diarization failed ({e}), falling back to CPU")
                device = "cpu"
                diarizer = whisperx.diarize.DiarizationPipeline(
                    use_auth_token=token,
                    device=device
                )
            else:
                raise

        if speaker_names and len(speaker_names) > 1:
            min_speakers = max(2, len(speaker_names) - 1)
            max_speakers = len(speaker_names) + 1
        diar = diarizer(
            str(audio_path),
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        # 2) Build segments for speaker assignment
        segments = []
        for ch in asr["chunks"]:
            s, e = ch.get("timestamp") or (None, None)
            s = _safe_float(s)
            e = _safe_float(e)
            if s is None or e is None or e <= s:
                continue
            seg_words = []
            for w in ch.get("words") or []:
                ws = _safe_float(w.get("start"))
                we = _safe_float(w.get("end"))
                token = (w.get("word") or "").strip()
                if ws is None or we is None or we <= ws or not token:
                    continue
                seg_words.append({"word": token, "start": ws, "end": we})
            segments.append({
                "start": s,
                "end": e,
                "text": ch.get("text") or "",
                "words": seg_words
            })

        # Assign speakers to words
        assigned = whisperx.assign_word_speakers(diar, {"segments": segments})
        segments = assigned.get("segments", [])

        # 3) Detect speaker changes and apply corrections
        speaker_segments = self._detect_speaker_segments(segments, min_segment_duration)

        # Apply manual corrections if provided
        if speaker_corrections:
            speaker_segments = self._apply_speaker_corrections(
                speaker_segments,
                speaker_corrections
            )

        # 4) Map speakers to names
        sp_map = self._create_speaker_mapping(
            speaker_segments,
            speaker_names
        )

        # 5) Generate SRT with improved speaker labels
        srt_lines = self._generate_srt_lines(
            speaker_segments,
            sp_map,
            max_gap_s,
            max_chars,
            max_duration_s,
            merge_short_segments
        )

        srt_text = ("\n".join(srt_lines) + "\n") if srt_lines else ""

        if output_srt_path:
            Path(output_srt_path).write_text(srt_text, encoding="utf-8")

        # Cleanup
        gc.collect()
        if device.startswith("cuda"):
            torch.cuda.empty_cache()

        return srt_text

    def _detect_speaker_segments(self, segments: list, min_duration: float = 0.5) -> list:
        """
        Detect speaker segments with better change detection.

        Groups consecutive words by the same speaker and detects speaker changes
        based on gaps in speech or explicit speaker labels.
        """
        if not segments:
            return []

        speaker_segments = []
        current_speaker = None
        current_start = None
        current_end = None
        current_words = []
        current_text = []

        for seg in segments:
            for w in seg.get("words") or []:
                word = w.get("word", "").strip()
                if not word:
                    continue

                start = w.get("start")
                end = w.get("end")
                speaker = w.get("speaker")

                if start is None or end is None:
                    continue

                # Detect speaker change
                speaker_changed = (current_speaker is not None and speaker != current_speaker)

                # Detect significant gap (might indicate speaker change)
                significant_gap = False
                if current_end is not None:
                    gap = start - current_end
                    significant_gap = gap > 0.9

                # Start new segment if speaker changed or significant gap
                if speaker_changed or significant_gap or current_speaker is None:
                    # Save current segment if it exists
                    if current_words and current_start is not None and current_end is not None:
                        duration = current_end - current_start
                        if duration >= min_duration or len(current_words) > 3:
                            speaker_segments.append({
                                "speaker": current_speaker,
                                "start": current_start,
                                "end": current_end,
                                "words": current_words,
                                "text": " ".join(current_text)
                            })

                    # Start new segment
                    current_speaker = speaker
                    current_start = start
                    current_end = end
                    current_words = [w]
                    current_text = [word]
                else:
                    # Continue current segment
                    current_end = max(current_end, end)
                    current_words.append(w)
                    current_text.append(word)

        # Don't forget the last segment
        if current_words and current_start is not None and current_end is not None:
            speaker_segments.append({
                "speaker": current_speaker,
                "start": current_start,
                "end": current_end,
                "words": current_words,
                "text": " ".join(current_text)
            })

        return speaker_segments

    def _apply_speaker_corrections(self, segments: list, corrections: dict) -> list:
        """
        Apply manual speaker corrections to specific segments.

        Args:
            segments: List of speaker segments
            corrections: Dict mapping segment index to correct speaker name
        """
        for idx, correction_speaker in corrections.items():
            if 0 <= idx < len(segments):
                segments[idx]["speaker"] = correction_speaker
                print(f"[Speaker Correction] Segment {idx}: -> {correction_speaker}")

        return segments

    def _create_speaker_mapping(self, segments: list, speaker_names: list = None) -> dict:
        """
        Create mapping from speaker IDs to names.

        Improved logic that better handles the initial recording message
        and subsequent speakers.
        """
        # Identify unique speakers by order of appearance
        seen_speakers = []
        for seg in segments:
            sp = seg.get("speaker")
            if sp and sp not in seen_speakers:
                seen_speakers.append(sp)

        sp_map = {}

        if speaker_names:
            # Special handling for recordings with initial disclaimer
            # Check if first segment is very early (< 10 seconds) and might be recording
            if segments and segments[0]["start"] < 10:
                first_text = segments[0]["text"].lower()
                # Common recording disclaimer patterns
                recording_patterns = [
                    "this call is being recorded",
                    "call may be recorded",
                    "recording for quality",
                    "this conversation is being recorded"
                ]

                is_recording = any(pattern in first_text for pattern in recording_patterns)

                if is_recording and len(speaker_names) > len(seen_speakers):
                    # First speaker is likely the recording, use first name for it
                    if seen_speakers:
                        sp_map[seen_speakers[0]] = speaker_names[0]  # "Recording" or similar
                    # Map remaining speakers starting from second name
                    for i, sp in enumerate(seen_speakers[1:], start=1):
                        if i < len(speaker_names):
                            sp_map[sp] = speaker_names[i]
                        else:
                            sp_map[sp] = f"Speaker{i}"
                else:
                    # Standard mapping
                    for i, sp in enumerate(seen_speakers):
                        if i < len(speaker_names):
                            sp_map[sp] = speaker_names[i]
                        else:
                            sp_map[sp] = f"Speaker{i+1}"
            else:
                # Standard mapping for normal conversations
                for i, sp in enumerate(seen_speakers):
                    if i < len(speaker_names):
                        sp_map[sp] = speaker_names[i]
                    else:
                        sp_map[sp] = f"Speaker{i+1}"
        else:
            # No names provided, use generic labels
            for i, sp in enumerate(seen_speakers):
                sp_map[sp] = f"Speaker{i+1}"

        # Handle None speaker
        sp_map[None] = "Unknown"

        return sp_map

    def _generate_srt_lines(
        self,
        segments: list,
        sp_map: dict,
        max_gap_s: float,
        max_chars: int,
        max_duration_s: float,
        merge_short: bool
    ) -> list:
        """
        Generate SRT lines from speaker segments.
        """
        def _fmt_srt_time(t: float) -> str:
            if t is None or not math.isfinite(t) or t < 0:
                t = 0.0
            ms = int(round(t * 1000.0))
            h, ms = divmod(ms, 3600000)
            m, ms = divmod(ms,   60000)
            s, ms = divmod(ms,    1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        srt_lines = []
        idx = 1

        for seg in segments:
            speaker = sp_map.get(seg["speaker"], seg["speaker"] or "Unknown")
            text = seg["text"].strip()

            if not text:
                continue

            # Split long segments if needed
            words = seg["words"]
            if len(text) > max_chars or (seg["end"] - seg["start"]) > max_duration_s:
                # Need to split this segment
                sub_segments = self._split_long_segment(
                    words,
                    max_chars,
                    max_duration_s,
                    max_gap_s
                )

                for sub_seg in sub_segments:
                    if sub_seg["text"].strip():
                        srt_lines.append(
                            f"{idx}\n"
                            f"{_fmt_srt_time(sub_seg['start'])} --> {_fmt_srt_time(sub_seg['end'])}\n"
                            f"{speaker}: {sub_seg['text']}\n"
                        )
                        idx += 1
            else:
                # Use segment as is
                srt_lines.append(
                    f"{idx}\n"
                    f"{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n"
                    f"{speaker}: {text}\n"
                )
                idx += 1

        return srt_lines

    def _split_long_segment(
        self,
        words: list,
        max_chars: int,
        max_duration: float,
        max_gap: float
    ) -> list:
        """
        Split a long segment into smaller chunks for better readability.
        """
        sub_segments = []
        current_words = []
        current_start = None
        current_end = None
        current_text = []

        for w in words:
            word = w.get("word", "").strip()
            start = w.get("start")
            end = w.get("end")

            if not word or start is None or end is None:
                continue

            # Check if adding this word would exceed limits
            would_exceed_chars = len(" ".join(current_text + [word])) > max_chars
            would_exceed_duration = (
                current_start is not None and
                (end - current_start) > max_duration
            )

            # Check for natural break point (gap)
            is_natural_break = False
            if current_end is not None:
                gap = start - current_end
                is_natural_break = gap > max_gap

            if (would_exceed_chars or would_exceed_duration or is_natural_break) and current_text:
                # Save current sub-segment
                sub_segments.append({
                    "start": current_start,
                    "end": current_end,
                    "text": " ".join(current_text)
                })
                # Start new sub-segment
                current_words = [w]
                current_start = start
                current_end = end
                current_text = [word]
            else:
                # Add to current sub-segment
                if current_start is None:
                    current_start = start
                current_end = end
                current_words.append(w)
                current_text.append(word)

        # Don't forget the last sub-segment
        if current_text:
            sub_segments.append({
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_text)
            })

        return sub_segments

    def format_timestamp(self, seconds):
        # This helper function takes the total seconds and formats it into hh:mm:ss,ms
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds % 1) * 1000)
        seconds = int(seconds)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

    def transcript_to_blocks(self, transcript: str) -> list:
        """
        Convert a transcript to blocks.
        """
        blocks = []
        for i, chunk in enumerate(transcript['chunks'], start=1):
            current_window = {}
            start, end = chunk['timestamp']
            if start is None or end is None:
                print(f"Warning: Missing timestamp for chunk {i}, skipping this chunk.")
                continue

            start_srt = self.format_timestamp(start)
            end_srt = self.format_timestamp(end)
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces
            current_window['id'] = i
            current_window['start_time'] = start_srt
            current_window['end_time'] = end_srt
            current_window['text'] = text
            blocks.append(current_window)
        return blocks

    def chunk_text(self, text, chunk_size, tokenizer):
        # Tokenize the text and get the number of tokens
        tokens = tokenizer.tokenize(text)
        # Split the tokens into chunks
        for i in range(0, len(tokens), chunk_size):
            yield tokenizer.convert_tokens_to_string(
                tokens[i:i+chunk_size]
            )

    def extract_audio(
        self,
        video_path: Path,
        audio_path: Path,
        compress_speed: bool = False,
        output_path: Optional[Path] = None,
        speed_factor: float = 1.5
    ):
        """
        Extract audio from video. Prefer WAV 16k mono for Whisper.
        """
        video_path = Path(video_path)
        audio_path = Path(audio_path)

        if audio_path.exists():
            print(f"Audio already extracted: {audio_path}")
            return

        # Extract as WAV 16k mono PCM
        print(f"Extracting audio (16k mono WAV) to: {audio_path}")
        clip = VideoFileClip(str(video_path))
        if not clip.audio:
            print("No audio found in video.")
            clip.close()
            return

        # moviepy/ffmpeg: pcm_s16le, 16k, mono
        # Ensure audio_path has .wav
        if audio_path.suffix.lower() != ".wav":
            audio_path = audio_path.with_suffix(".wav")

        clip.audio.write_audiofile(
            str(audio_path),
            fps=16000,
            nbytes=2,
            codec="pcm_s16le",
            ffmpeg_params=["-ac", "1"]
        )
        clip.audio.close()
        clip.close()

        # Optional speed compression (still output WAV @16k mono)
        if compress_speed:
            print(f"Compressing audio speed by factor: {speed_factor}")
            audio = AudioSegment.from_file(audio_path)
            sped = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * speed_factor)})
            sped = sped.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            sped.export(str(output_path or audio_path), format="wav")
            print(f"Compressed audio saved to: {output_path or audio_path}")
        else:
            print(f"Audio extracted: {audio_path}")

    def ensure_wav_16k_mono(self, src_path: Path) -> Path:
        """
        Ensure `src_path` is a 16 kHz mono PCM WAV. Returns the WAV path.
        - If src is not a .wav, write <stem>.wav
        - If src is already .wav, write <stem>.16k.wav to avoid in-place overwrite
        """
        src_path = Path(src_path)
        if src_path.suffix.lower() == ".wav":
            out_path = src_path.with_name(f"{src_path.stem}.16k.wav")
        else:
            out_path = src_path.with_suffix(".wav")

        # Always (re)encode to guarantee 16k mono PCM s16le
        audio = AudioSegment.from_file(src_path)
        audio = (
            audio.set_frame_rate(16000)   # 16 kHz
            .set_channels(1)         # mono
            .set_sample_width(2)     # s16le
        )
        audio.export(str(out_path), format="wav")
        print(f"Transcoded to 16k mono WAV: {out_path}")
        return out_path

    def _get_whisperx_name(self, language: str = 'en', model_size: str = 'small', version: str = 'v3'):
        """
        Get the appropriate WhisperX model name based on language and size.

        WhisperX model naming conventions:
        - English-only models: "tiny.en", "base.en", "small.en", "medium.en"
        - Multilingual models: "tiny", "base", "small", "medium", "large", "large-v1", "large-v2", "large-v3", "turbo"

        Args:
            language: Language code (e.g., "en", "es", "fr")
            model_size: Model size ("tiny", "base", "small", "medium", "large", "turbo")
            model_name: Explicit model name to use (overrides size selection)

        Returns:
            tuple: (model_name, detected_language)
        """
        if language.lower() == 'en' and model_size.lower() in {'tiny', 'base', 'small', 'medium'}:
            return f"{model_size}.en"
        elif model_size.lower() in {'tiny', 'base', 'small', 'medium'}:
            return f"{model_size}"
        else:
            return f"{model_size}-{version}"

    def get_whisperx_transcript(
        self,
        audio_path: Path,
        language: str = "en",
        model_name: str = None,
        batch_size: int = 8,
        compute_type_gpu: str = "float16",
        compute_type_cpu: str = "int8"
    ):
        """
        WhisperX-based transcription with word-level timestamps.
        Returns:
        {
        "text": "...",
        "chunks": [
            {
            "text": "...",
            "timestamp": (start, end),
            "words": [{"word":"...", "start":..., "end":...}, ...]
            },
            ...
        ],
        "language": "en"
        }
        """
        def _safe_float(x):
            try:
                xf = float(x)
                if math.isfinite(xf):
                    return xf
            except Exception:
                pass
            return None

        # Use the existing _get_device method
        pipeline_idx, _, _ = self._get_device()
        # Determine device string for WhisperX
        if isinstance(pipeline_idx, str):
            # MPS or other special device
            device = pipeline_idx
        elif pipeline_idx >= 0:
            # CUDA device
            device = "cuda"
        else:
            # CPU
            device = "cpu"

        # Select compute type based on device
        if device.startswith("cuda"):
            compute_type = compute_type_gpu
        elif device == "mps":
            # MPS typically works better with float32
            compute_type = "float32"
        else:
            compute_type = compute_type_cpu

        # Model selection
        lang = (language or self._language).lower()

        if model_name:
            model_id = model_name
        else:
            model_id = self._get_whisperx_name(lang, self._model_size)

        # 1) ASR
        model = whisperx.load_model(
            model_id,
            device=device,
            compute_type=compute_type,
            language=language
        )
        audio = whisperx.load_audio(str(audio_path))
        asr_result = model.transcribe(audio, batch_size=batch_size)
        lang = asr_result.get("language", language)
        segs = asr_result.get("segments", []) or []

        # 2) Alignment → precise word times
        align_model, align_meta = whisperx.load_align_model(
            language_code=asr_result.get("language", language), device=device
        )
        aligned = whisperx.align(
            segs,
            align_model,
            align_meta,
            audio,
            device=device,
            return_char_alignments=False
        )

        # build the return payload in your existing schema
        chunks = []
        full_text_parts = []
        for seg in aligned.get("segments", []):
            s = _safe_float(seg.get("start"))
            e = _safe_float(seg.get("end"))
            if s is None or e is None or e <= s:
                continue
            text = (seg.get("text") or "").strip()
            words_out = []
            for w in seg.get("words") or []:
                ws = _safe_float(w.get("start"))
                we = _safe_float(w.get("end"))
                token = (w.get("word") or "").strip()
                if ws is None or we is None or we <= ws or not token:
                    continue
                words_out.append({"word": token, "start": ws, "end": we})
            chunks.append({"text": text, "timestamp": (s, e), "words": words_out})
            if text:
                full_text_parts.append(text)

        # Cleanup
        del model
        del align_model
        gc.collect()
        try:
            if device.startswith("cuda"):
                torch.cuda.empty_cache()
        except Exception:
            pass

        return {"text": " ".join(full_text_parts).strip(), "chunks": chunks, "language": lang}

    def get_whisper_transcript(
        self,
        audio_path: Path,
        chunk_length: int = 30,
        word_timestamps: bool = False,
        manual_chunk: bool = True,  # New parameter to enable manual chunking
        max_chunk_duration: int = 60  # Maximum seconds per chunk for GPU processing
    ):
        """
        Enhanced Whisper transcription with manual chunking for GPU memory management.

        The key insight: We process smaller audio segments independently on GPU,
        then merge results with corrected timestamps based on each chunk's offset.
        """
        # Model selection
        lang = (self._language or "en").lower()
        if self._model_name in (None, "", "whisper", "openai/whisper"):
            size = (self._model_size or "small").lower()
            if lang == "en" and size in {"tiny", "base", "small", "medium"}:
                model_id = f"openai/whisper-{size}.en"
            elif size == "turbo":
                model_id = "openai/whisper-large-v3-turbo"
            else:
                model_id = "openai/whisper-large-v3"
        else:
            model_id = self._model_name

        # Load audio once
        if not (audio_path.exists() and audio_path.stat().st_size > 0):
            return None

        wav, sr = sf.read(str(audio_path), always_2d=False)
        if wav.ndim == 2:
            wav = wav.mean(axis=1)
        wav = wav.astype(np.float32, copy=False)

        total_duration = len(wav) / float(sr)
        print(f"[Whisper] Total audio duration: {total_duration:.2f} seconds")

        # Device configuration
        device_idx, dev, torch_dtype = self._get_device()
        # Special handling for MPS or other non-standard devices
        if isinstance(device_idx, str):
            # MPS or other special case - treat as CPU for pipeline purposes
            pipeline_device_idx = -1
            print(
                f"[Whisper] Using {device_idx} device (will use CPU pipeline mode)"
            )
        else:
            pipeline_device_idx = device_idx

        # Determine if we need manual chunking
        # Rule of thumb: whisper-medium needs ~6GB for 60s of audio
        needs_manual_chunk = (
            manual_chunk and
            isinstance(device_idx, int) and device_idx >= 0 and  # Using GPU
            total_duration > max_chunk_duration  # Audio is long
        )

        print('[Whisper] Using model:', model_id, 'Chunking needed: ', needs_manual_chunk)

        if needs_manual_chunk:
            print(
                f"[Whisper] Using manual chunking strategy (chunks of {max_chunk_duration}s)"
            )
            return self._process_chunks(
                wav, sr, model_id, lang, pipeline_device_idx, dev, torch_dtype,
                max_chunk_duration, word_timestamps
            )
        else:
            # Use the standard pipeline for short audio or CPU processing
            return self._process_pipeline(
                wav, sr, model_id, lang, pipeline_device_idx, dev, torch_dtype,
                chunk_length, word_timestamps
            )

    def _process_pipeline(
        self,
        wav: np.ndarray,
        sr: int,
        model_id: str,
        lang: str,
        device_idx: int,
        torch_dev: str,
        torch_dtype,
        chunk_length: int,
        word_timestamps: bool
    ):
        """Use HF pipeline's built-in chunking & timestamping."""
        is_english_only = (
            model_id.endswith('.en') or
            '-en' in model_id.split('/')[-1] or
            model_id.endswith('-en')
        )

        model = WhisperForConditionalGeneration.from_pretrained(
            model_id,
            attn_implementation="eager",   # silence SDPA warning + future-proof
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
        ).to(torch_dev)
        processor = WhisperProcessor.from_pretrained(model_id)

        chunk_length = int(chunk_length) if chunk_length else 30
        stride = 6 if chunk_length >= 8 else max(1, chunk_length // 5)

        asr = pipeline(
            task="automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device_idx if device_idx >= 0 else -1,
            torch_dtype=torch_dtype,
            chunk_length_s=chunk_length,
            stride_length_s=stride,
            batch_size=1
        )

        # Timestamp mode
        ts_mode = "word" if word_timestamps else True

        generate_kwargs = {
            "temperature": 0.0,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
        }
        # Language forcing only when not English-only
        if not is_english_only and lang:
            try:
                generate_kwargs["language"] = lang
                generate_kwargs["task"] = "transcribe"
            except Exception:
                pass

        # Let the pipeline handle attention_mask/padding
        out = asr(
            {"raw": wav, "sampling_rate": sr},
            return_timestamps=ts_mode,
            generate_kwargs=generate_kwargs,
        )

        chunks = out.get("chunks", [])
        # normalize to your return shape
        out['text'] = out.get("text") or " ".join(c["text"] for c in chunks)
        return out

    def _process_chunks(
        self,
        wav: np.ndarray,
        sr: int,
        model_id: str,
        lang: str,
        device_idx: int,
        torch_dev: str,
        torch_dtype,
        max_chunk_duration: int,
        word_timestamps: bool,
        chunk_length: int = 60
    ):
        """
        Robust audio chunking with better error handling and memory management.

        This version addresses several key issues:
        1. The 'input_ids' error by properly configuring the pipeline
        2. The audio format issue in fallbacks
        3. Memory management for smaller GPUs
        4. Chunk processing stability
        """
        # For whisper-small on a 5.6GB GPU, we can use slightly larger chunks than medium
        # whisper-small uses ~1.5GB, leaving ~4GB for processing
        actual_chunk_duration = min(45, max_chunk_duration)  # Can handle 45s chunks with small

        # Set environment variable for better memory management
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

        # English-only models end with '.en' or contain '-en' in their name
        is_english_only = (
            model_id.endswith('.en') or
            '-en' in model_id.split('/')[-1] or
            model_id.endswith('-en')
        )

        print(f"[Whisper] Model type: {'English-only' if is_english_only else 'Multilingual'}")
        print(f"[Whisper] Using model: {model_id}")

        chunk_samples = actual_chunk_duration * sr
        overlap_duration = 2  # 2 seconds overlap to avoid cutting words
        overlap_samples = overlap_duration * sr

        print(f"[Whisper] Processing {len(wav)/sr:.1f}s audio in {actual_chunk_duration}s chunks")

        all_results = []
        offset = 0
        chunk_idx = 0

        # Load model once for all chunks (whisper-small fits comfortably in memory)
        print(f"[Whisper] Loading {model_id} model...")
        model = WhisperForConditionalGeneration.from_pretrained(
            model_id,
            attn_implementation="eager",           # <= fixes SDPA warning
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        ).to(torch_dev)
        processor = WhisperProcessor.from_pretrained(model_id)

        # Base generation kwargs - we'll be careful about what we pass
        base_generate_kwargs = {
            "temperature": 0.0,  # Deterministic to reduce hallucinations
            "compression_ratio_threshold": 2.4,  # Detect repetitive text
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
        }

        # Only add language forcing if it's properly supported
        if not is_english_only:
            try:
                forced_ids = processor.get_decoder_prompt_ids(
                    language=lang,
                    task="transcribe"
                )
                if forced_ids:
                    base_generate_kwargs["language"] = lang
                    base_generate_kwargs["task"] = "transcribe"
                    # Note: We don't pass forced_decoder_ids directly as it can cause issues
            except Exception:
                # If the processor doesn't support this, that's fine
                pass

        while offset < len(wav):
            # Extract chunk
            end_sample = min(offset + chunk_samples, len(wav))
            chunk_wav = wav[offset:end_sample]

            # Calculate timing for this chunk
            time_offset = offset / float(sr)
            chunk_duration = len(chunk_wav) / float(sr)

            print(f"[Whisper] Processing chunk {chunk_idx + 1} "
                f"({time_offset:.1f}s - {time_offset + chunk_duration:.1f}s)")

            # Process this chunk with careful error handling
            chunk_processed = False
            attempts = [
                ("standard", word_timestamps),
                ("chunk_timestamps", False),  # Fallback to chunk timestamps
                ("basic", False)  # Most basic mode
            ]
            chunk_length = int(chunk_length) if chunk_length else 30
            stride = 6 if chunk_length >= 8 else max(1, chunk_length // 5)

            for attempt_name, use_word_timestamps in attempts:
                if chunk_processed:
                    break

                try:
                    # Create a fresh pipeline for each chunk to avoid state issues
                    # This is important for avoiding the 'input_ids' error
                    asr = pipeline(
                        task="automatic-speech-recognition",
                        model=model,
                        tokenizer=processor.tokenizer,
                        feature_extractor=processor.feature_extractor,
                        device=device_idx if device_idx >= 0 else -1,
                        chunk_length_s=chunk_length,
                        stride_length_s=stride,
                        batch_size=1,
                        torch_dtype=torch_dtype,
                    )

                    # Prepare audio input with the CORRECT format
                    # This is crucial - the pipeline expects "raw" not "array"
                    audio_input = {
                        "raw": chunk_wav,
                        "sampling_rate": sr
                    }

                    # Determine timestamp mode based on current attempt
                    if use_word_timestamps:
                        timestamp_param = "word"
                    else:
                        timestamp_param = True  # Chunk-level timestamps

                    # Use a clean copy of generate_kwargs for each attempt
                    # This prevents accumulation of incompatible parameters
                    generate_kwargs = base_generate_kwargs.copy()

                    # Process the chunk
                    chunk_result = asr(
                        audio_input,
                        return_timestamps=timestamp_param,
                        generate_kwargs=generate_kwargs
                    )

                    # Successfully processed - now handle the results
                    if chunk_result and "chunks" in chunk_result:
                        for item in chunk_result["chunks"]:
                            # Adjust timestamps for this chunk's position
                            if "timestamp" in item and item["timestamp"]:
                                start, end = item["timestamp"]
                                if start is not None:
                                    start += time_offset
                                if end is not None:
                                    end += time_offset
                                item["timestamp"] = (start, end)

                            # Add metadata for merging
                            item["_chunk_idx"] = chunk_idx
                            item["_is_word"] = use_word_timestamps

                        all_results.extend(chunk_result["chunks"])
                        print(f"  ✓ Chunk {chunk_idx + 1}: {len(chunk_result['chunks'])} items "
                            f"(mode: {attempt_name})")
                        chunk_processed = True

                    # Clean up the pipeline to free memory
                    del asr
                    gc.collect()
                    if device_idx >= 0:
                        torch.cuda.empty_cache()

                except Exception as e:
                    error_msg = str(e)
                    print(f"  ✗ Attempt '{attempt_name}' failed: {error_msg[:100]}")

                    # Clean up on error
                    if 'asr' in locals():
                        del asr
                    gc.collect()
                    if device_idx >= 0:
                        torch.cuda.empty_cache()

                    # Continue to next attempt
                    continue

            if not chunk_processed:
                print(f"  ⚠ Chunk {chunk_idx + 1} could not be processed, skipping")

            # Move to next chunk
            if end_sample < len(wav):
                offset += chunk_samples - overlap_samples
            else:
                break

            chunk_idx += 1

        # Clean up model after all chunks
        del model
        del processor
        gc.collect()
        if device_idx >= 0:
            torch.cuda.empty_cache()

        # Merge results based on whether we got word or chunk timestamps
        # Check what we actually got (might be mixed if some chunks fell back)
        has_word_timestamps = any(item.get("_is_word", False) for item in all_results)

        if has_word_timestamps:
            print("[Whisper] Merging word-level timestamps...")
            final_chunks = self._merge_word_chunks(all_results, overlap_duration)
        else:
            print("[Whisper] Merging chunk-level timestamps...")
            final_chunks = self._merge_overlapping_chunks(all_results, overlap_duration)

        # Clean the results to remove any garbage/hallucinations
        cleaned_chunks = []
        for chunk in final_chunks:
            text = chunk.get("text", "").strip()

            # Filter out common hallucination patterns
            if not text:
                continue
            if len(set(text)) < 3 and len(text) > 10:  # Repetitive characters
                continue
            if text.count("$") > len(text) * 0.5:  # Too many special characters
                continue
            if text.count("�") > 0:  # Unicode errors
                continue

            chunk["text"] = text
            cleaned_chunks.append(chunk)

        # Build the final result
        result = {
            "chunks": cleaned_chunks,
            "text": " ".join(ch["text"] for ch in cleaned_chunks),
            "word_timestamps": has_word_timestamps
        }

        print(f"[Whisper] Transcription complete: {len(cleaned_chunks)} segments, "
            f"{len(result['text'].split())} words")

        return result

    def _merge_overlapping_chunks(self, chunks: List[dict], overlap_duration: float) -> List[dict]:
        """
        Intelligently merge chunks that might have overlapping content.

        When we process overlapping audio segments, we might get duplicate
        transcriptions at the boundaries. This function:
        1. Detects potential duplicates based on timestamp overlap
        2. Keeps the best version (usually from the chunk where it's not at the edge)
        3. Maintains temporal order
        """
        if not chunks:
            return []

        # Sort by start time
        chunks.sort(key=lambda x: x.get("timestamp", (0,))[0] or 0)

        merged = []
        for chunk in chunks:
            if not chunk.get("text", "").strip():
                continue

            timestamp = chunk.get("timestamp", (None, None))
            if not timestamp or timestamp[0] is None:
                continue

            # Check if this chunk overlaps significantly with the last merged chunk
            if merged:
                last = merged[-1]
                last_ts = last.get("timestamp", (None, None))

                if last_ts and last_ts[1] and timestamp[0]:
                    # If timestamps overlap significantly
                    overlap = last_ts[1] - timestamp[0]
                    if overlap > 0.5:  # More than 0.5 second overlap
                        # Compare text similarity to detect duplicates
                        last_text = last.get("text", "").strip().lower()
                        curr_text = chunk.get("text", "").strip().lower()

                        # Simple duplicate detection
                        if last_text == curr_text:
                            # Skip this duplicate
                            continue

                        # If texts are very similar (e.g., one is subset of another)
                        if len(last_text) > 10 and len(curr_text) > 10:
                            if last_text in curr_text or curr_text in last_text:
                                # Keep the longer version
                                if len(curr_text) > len(last_text):
                                    merged[-1] = chunk
                                continue

            merged.append(chunk)

        return merged

    def _merge_word_chunks(self, chunks: List[dict], overlap_duration: float) -> List[dict]:
        """
        Special merging logic for word-level timestamps.

        Word-level chunks need more careful handling because:
        1. Words at boundaries might appear in multiple chunks
        2. Timestamp precision is more important
        3. We need to maintain word order exactly
        """
        if not chunks:
            return []

        # Sort by start timestamp
        chunks.sort(key=lambda x: (x.get("timestamp", (0,))[0] or 0, x.get("_chunk_idx", 0)))

        merged = []
        seen_words = set()  # Track (word, approximate_time) to avoid duplicates

        for chunk in chunks:
            word = chunk.get("text", "").strip()
            if not word:
                continue

            timestamp = chunk.get("timestamp", (None, None))
            if not timestamp or timestamp[0] is None:
                continue

            # Create a key for duplicate detection
            # Round timestamp to nearest 0.1s for fuzzy matching
            time_key = round(timestamp[0], 1)
            word_key = (word.lower(), time_key)

            # Skip if we've seen this word at approximately this time
            if word_key in seen_words:
                continue

            seen_words.add(word_key)
            merged.append(chunk)

        return merged

    @abstractmethod
    async def _load(self, source: str, **kwargs) -> List[Document]:
        pass

    @abstractmethod
    async def load_video(self, url: str, video_title: str, transcript: str) -> list:
        pass
