from typing import Any, Union, List, Optional
from collections.abc import Callable
from abc import abstractmethod
import gc
import os
import logging
from pathlib import Path
from moviepy.editor import VideoFileClip
from pydub import AudioSegment
import soundfile as sf
import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav
from sklearn.cluster import AgglomerativeClustering
import torch
from transformers import (
    pipeline,
    AutoModelForSpeechSeq2Seq,
    AutoProcessor,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    WhisperProcessor,
    WhisperForConditionalGeneration
)
from navconfig import config
from ..stores.models import Document
from .abstract import AbstractLoader


logging.getLogger(name='numba').setLevel(logging.WARNING)
logging.getLogger(name='pydub.converter').setLevel(logging.WARNING)

def extract_video_id(url):
    parts = url.split("?v=")
    video_id = parts[1].split("&")[0]
    return video_id

def _collapse_labels_to_segments(times_sec: np.ndarray, labels: np.ndarray):
    """
    Collapse frame-level labels into contiguous (start, end, label) segments.
    times_sec is the center time of each frame (shape: [N]).
    """
    if len(labels) == 0:
        return []
    segs = []
    cur_label = labels[0]
    start_t = times_sec[0]
    for i in range(1, len(labels)):
        if labels[i] != cur_label:
            end_t = times_sec[i-1]
            segs.append((float(start_t), float(end_t), int(cur_label)))
            cur_label = labels[i]
            start_t = times_sec[i]
    # tail
    segs.append((float(start_t), float(times_sec[-1]), int(cur_label)))
    return segs

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
        asr: Any = None,
        speaker_names: Optional[List[str]] = None,
        output_srt_path: Optional[Path] = None,
        frame_hop_s: float = 0.75,
        distance_threshold: float = 0.6,
    ) -> str:
        """
        Generate SRT with speaker labels using Resemblyzer diarization + Whisper ASR.

        Steps:
        - ensure 16k mono WAV
        - Whisper transcription -> chunk timestamps + text
        - Resemblyzer partial embeddings -> Agglomerative clustering with distance threshold
        - Assign the majority speaker label to each ASR chunk
        - Render SRT ("Speaker N:" or mapped names)

        Args:
            speaker_names: Optional list like ["Agent", "Customer", ...] to map 0,1,2...
            distance_threshold: Lower -> more speakers; higher -> fewer.
        """
        # 1) Make sure we have 16k mono WAV for robust/consistent embeddings
        wav_path = self.ensure_wav_16k_mono(audio_path)

        # 3) Resemblyzer embeddings over sliding windows
        wav = preprocess_wav(wav_path)  # resampled to 16k internally
        encoder = VoiceEncoder()

        # We want partials/frames to diarize over time
        _, partial_embeds, wav_splits = encoder.embed_utterance(
            wav, return_partials=True, rate=int(1 / frame_hop_s)
        )
        # partial_embeds: [N, 256], wav_splits: list of (start_sample, end_sample)
        if len(partial_embeds) == 0:
            raise RuntimeError("Could not compute partial embeddings for diarization.")
        partial_embeds = np.asarray(partial_embeds)

        # 4) Frame centers (seconds) based on wav_splits at 16k
        sr = 16000.0
        times_sec = np.array([(s + e) / 2.0 / sr for (s, e) in wav_splits], dtype=np.float32)

        # 5) Cluster with automatic number of speakers (via distance_threshold)
        clustering = AgglomerativeClustering(
            n_clusters=None,
            affinity="euclidean",
            linkage="average",
            distance_threshold=distance_threshold
        )
        labels = clustering.fit_predict(partial_embeds)

        # 6) Collapse frame-level labels to contiguous segments (helps later lookup)
        diar_segments = _collapse_labels_to_segments(times_sec, labels)
        # (start, end, speaker_id) with end < next start by construction

        # Helper to find majority label for an interval
        def majority_label(start_t: float, end_t: float) -> int:
            # Select frames whose centers fall inside [start_t, end_t]
            mask = (times_sec >= start_t) & (times_sec <= end_t)
            if not np.any(mask):
                # fallback: nearest frame
                nearest = int(np.argmin(np.abs(times_sec - (0.5 * (start_t + end_t)))))
                return int(labels[nearest])
            ls = labels[mask]
            # majority vote
            vals, counts = np.unique(ls, return_counts=True)
            return int(vals[np.argmax(counts)])

        # 7) Build SRT lines by assigning a speaker to each ASR chunk
        srt_lines = []
        idx = 1
        for ch in asr["chunks"]:
            # Whisper HF pipeline returns chunk dicts with ("timestamp": (start, end), "text": ...)
            ts = ch.get("timestamp")
            if (not ts) or (ts[0] is None) or (ts[1] is None):
                continue
            start, end = float(ts[0]), float(ts[1])
            if end <= start:
                continue

            # tiny guard: ensure interval has some diar frames (or pick nearest)
            spk_id = majority_label(start, end)

            speaker_label = f"Speaker {spk_id + 1}"
            if speaker_names and spk_id < len(speaker_names):
                speaker_label = speaker_names[spk_id]

            text = ch.get("text", "").strip().replace("\n", " ")
            if not text:
                continue

            start_s = _fmt_srt_time(start)
            end_s = _fmt_srt_time(end)
            srt_lines.append(f"{idx}\n{start_s} --> {end_s}\n{speaker_label}: {text}\n")
            idx += 1

        srt = "\n".join(srt_lines) + ("\n" if srt_lines else "")

        if output_srt_path:
            output_srt_path = Path(output_srt_path)
            output_srt_path.write_text(srt, encoding="utf-8")

        return srt


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

    def transcript_to_srt(self, transcript: str) -> str:
        """
        Convert a transcript to SRT format.
        """
        # lines = transcript.split("\n")
        srt = ""
        for i, chunk in enumerate(transcript['chunks'], start=1):
            start, end = chunk['timestamp']
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces
            # Convert start and end times to SRT format HH:MM:SS,MS
            start_srt = f"{start // 3600:02}:{start % 3600 // 60:02}:{start % 60:02},{int(start * 1000 % 1000):03}"
            end_srt = f"{end // 3600:02}:{end % 3600 // 60:02}:{end % 60:02},{int(end * 1000 % 1000):03}"
            srt += f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n"
        return srt

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
        # Model selection (keeping your existing logic)
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
        audio_path = Path(audio_path)
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
