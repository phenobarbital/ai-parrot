---
type: Wiki Entity
title: YoutubeLoader
id: class:parrot_loaders.youtube.YoutubeLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Loader for Youtube videos.
relates_to:
- concept: class:parrot_loaders.video.VideoLoader
  rel: extends
---

# YoutubeLoader

Defined in [`parrot_loaders.youtube`](../summaries/mod:parrot_loaders.youtube.md).

```python
class YoutubeLoader(VideoLoader)
```

Loader for Youtube videos.

## Methods

- `def get_video_info(self, url: str) -> dict`
- `def download_audio_wav(self, url: str, path: Optional[Union[str, Path]]=None) -> Path` — Download best audio and convert to WAV (16 kHz mono) via ffmpeg (required by yt-dlp).
- `def download_video(self, url: str, path: Path) -> Path` — Downloads a video from a URL using yt-dlp with enhanced error handling.
- `async def save_file_async(self, file_path: Path, content: Union[str, bytes]) -> None` — Async file saving utility.
- `async def read_file_async(self, file_path: Path) -> str` — Async file reading utility.
- `async def load_video(self, url: str, video_title: str, transcript: Optional[Union[str, None]]=None) -> List[Document]` — Async method to load video and create documents.
- `async def extract_video(self, url: str) -> dict` — Extract video and return metadata with file paths.
- `async def extract(self) -> List[dict]` — Extract all videos and return metadata.
