---
id: F025
query_id: Q025
type: read
intent: Video loader inputs — transcript_to_blocks shape, whisper/whisperx transcripts, YoutubeLoader timestamp path, VideoUnderstandingLoader output
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F025 — Video transcripts give timed blocks with float seconds; Gemini video understanding gives untimed "scenes"

## Summary
`BaseVideoLoader.transcript_to_blocks` takes a Whisper-style dict `{text, chunks:[{text, timestamp:(start,end), words?}]}` and returns a list of dicts with the keys `id, start_time, end_time` (SRT strings), `start_seconds, end_seconds` (floats) and `text`. It skips chunks that have a None timestamp. `get_whisperx_transcript` always returns word-level `words:[{word,start,end}]` inside each chunk. `get_whisper_transcript` has a `word_timestamps=False` flag. `YoutubeLoader.load_video` (in youtube.py, not video.py) calls `get_whisper_transcript(audio_path)` with the defaults, so no word timestamps. It writes a parent `video_transcript` Document with `metadata['vtt']` plus one child `video_dialog` Document per block, carrying start/end seconds and a `?t=Ns` deeplink. `VideoUnderstandingLoader` calls `GoogleGenAIClient.video_understanding(video, prompt, prompt_instruction, temperature, stateless=True)` and passes no `offsets`. It parses the output with `extract_scenes_from_response`, whose "timestamp" is a label such as "Scene 3" or "Full Video" unless the model returns JSON `{"scenes":[...]}`. So the output has no real timecodes.

## Citations
- path: `packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py`
  lines: 860-887
  symbol: `BaseVideoLoader.transcript_to_blocks`
  excerpt: |
    def transcript_to_blocks(self, transcript: str) -> list:
        for i, chunk in enumerate(transcript['chunks'], start=1):
            start, end = chunk['timestamp']
            if start is None or end is None: ... continue
            current_window['start_time'] = start_srt
            current_window['start_seconds'] = float(start)
            current_window['text'] = text
- path: `packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py`
  lines: 1002-1132
  symbol: `BaseVideoLoader.get_whisperx_transcript(audio_path, language="en", model_name=None, batch_size=8, compute_type_gpu="float16", compute_type_cpu="int8")`
  excerpt: |
    chunks.append({"text": text, "timestamp": (s, e), "words": words_out})
    return {"text": " ".join(full_text_parts).strip(), "chunks": chunks, "language": lang}
- path: `packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py`
  lines: 1134-1209
  symbol: `BaseVideoLoader.get_whisper_transcript(audio_path, chunk_length=30, word_timestamps=False, manual_chunk=True, max_chunk_duration=60)`
  excerpt: |
    GPU + long audio -> self._process_chunks(..., max_chunk_duration, word_timestamps)  (L1289-1543)
    else            -> self._process_pipeline(..., chunk_length, word_timestamps)      (L1211-1287)
- path: `packages/ai-parrot-loaders/src/parrot_loaders/youtube.py`
  lines: 298-395
  symbol: `YoutubeLoader.load_video`
  excerpt: |
    transcript_whisper = await ...run_in_executor(None, self.get_whisper_transcript, audio_path)
    vtt_content = self.transcript_to_vtt(transcript_whisper, transcript_path)
    dialogs = self.transcript_to_blocks(transcript_whisper)
    deeplink = f"{watch_url}{'&' if '?' in watch_url else '?'}t={int(start_s)}s"
    ... doctype='video_dialog', start_seconds=start_s, end_seconds=end_s, deeplink=deeplink
- path: `packages/ai-parrot-loaders/src/parrot_loaders/video.py`
  lines: 9-88
  symbol: `VideoLoader`
  excerpt: |
    abstract; `_load` passes transcript=None to abstract `load_video`
- path: `packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py`
  lines: 163-187
  symbol: `VideoUnderstandingLoader._analyze_video_with_ai`
  excerpt: |
    response = await ai_client.video_understanding(
        video=video_path, prompt=prompt, prompt_instruction=instructions,
        temperature=self.temperature, stateless=True,)
- path: `packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py`
  lines: 51-103
  symbol: `extract_scenes_from_response`
  excerpt: |
    if "scenes" in json_data: return json_data["scenes"]
    scene_pattern = r"(?:Scene|Step)\s*(\d+)[:.]?\s*(.*?)(?=(?:Scene|Step)\s*\d+|$)"
    "timestamp": f"Scene {scene_num}" ...   # fallback: "Full Video"
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 208-229, 272-273
  symbol: `GoogleGenAIClient.video_understanding(prompt, model=GoogleModel.GEMINI_FLASH_LATEST, ..., offsets: Optional[tuple[str,str]]=None, ..., structured_output=None)`
  excerpt: |
    if offsets:
        video_metadata = types.VideoMetadata(start_offset=offsets[0], end_offset=offsets[1])

## Notes
- There is no `YoutubeLoader` in video.py. It lives in `youtube.py:30` (`YoutubeLoader(VideoLoader)`), and `vimeo.py:6` subclasses it. The brainstorm's `video.py::YoutubeLoader` is wrong.
- The type hint `transcript_to_blocks(self, transcript: str)` is wrong: the method indexes a dict.
- `offsets` and `structured_output` exist only on the client method. The loader uses neither, so to get timecoded scenes you would call the client directly with `structured_output`.
- Probable bug: the loader builds `GoogleGenAIClient(model=self.model)` with the default model "gemini-3.1-pro-preview", but it does not pass `model=` to `video_understanding`, whose own default is `GEMINI_FLASH_LATEST`. The image loader, by contrast, does pass `model=self.model`.
- The default prompt is hard-coded for Workday training videos (L140-149).
- The YouTube path never asks for word timestamps. Word-level alignment only comes from `get_whisperx_transcript`.
