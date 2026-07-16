---
type: Wiki Entity
title: BaseVideoLoader
id: class:parrot_loaders.basevideo.BaseVideoLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generating Video transcripts from Videos.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# BaseVideoLoader

Defined in [`parrot_loaders.basevideo`](../summaries/mod:parrot_loaders.basevideo.md).

```python
class BaseVideoLoader(AbstractLoader)
```

Generating Video transcripts from Videos.

## Methods

- `def build_default_meta(self, path: Union[str, 'Path'], *, language: Optional[str]=None, title: Optional[str]=None, **kwargs) -> dict` — Return canonical metadata for a video/audio source.
- `def summarizer(self)` — Lazy loading property for the summarizer pipeline.
- `def summarizer(self, value)` — Allow external setting of summarizer (for compatibility).
- `def summarizer(self)` — Delete summarizer and free VRAM.
- `def transcript_to_vtt(self, transcript: str, transcript_path: Path) -> str` — Convert a transcript to VTT format.
- `def audio_to_srt(self, audio_path: Path, asr=None, speaker_names=None, output_srt_path=None, pyannote_token: str=None, max_gap_s: float=0.5, max_chars: int=90, max_duration_s: float=8.0, min_speakers: int=1, max_speakers: int=2, speaker_corrections: dict=None, merge_short_segments: bool=True, min_segment_duration: float=0.5)` — Build an SRT subtitle string from a call recording using WhisperX-aligned words and
- `def format_timestamp(self, seconds)`
- `def transcript_to_blocks(self, transcript: str) -> list` — Convert a transcript to blocks.
- `def chunk_text(self, text, chunk_size, tokenizer)`
- `def extract_audio(self, video_path: Path, audio_path: Path, compress_speed: bool=False, output_path: Optional[Path]=None, speed_factor: float=1.5)` — Extract audio from video. Prefer WAV 16k mono for Whisper.
- `def ensure_wav_16k_mono(self, src_path: Path) -> Path` — Ensure `src_path` is a 16 kHz mono PCM WAV. Returns the WAV path.
- `def get_whisperx_transcript(self, audio_path: Path, language: str='en', model_name: str=None, batch_size: int=8, compute_type_gpu: str='float16', compute_type_cpu: str='int8')` — WhisperX-based transcription with word-level timestamps.
- `def get_whisper_transcript(self, audio_path: Path, chunk_length: int=30, word_timestamps: bool=False, manual_chunk: bool=True, max_chunk_duration: int=60)` — Enhanced Whisper transcription with manual chunking for GPU memory management.
- `def clear_cuda(self)` — Clear CUDA cache and free all GPU memory used by this loader.
- `async def load_video(self, url: str, video_title: str, transcript: str) -> list`
