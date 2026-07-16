---
type: Wiki Entity
title: GoogleGeneration
id: class:parrot.clients.google.generation.GoogleGeneration
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin class for Google Generative AI generation capabilities (Image, Video,
  Audio).
---

# GoogleGeneration

Defined in [`parrot.clients.google.generation`](../summaries/mod:parrot.clients.google.generation.md).

```python
class GoogleGeneration
```

Mixin class for Google Generative AI generation capabilities (Image, Video, Audio).

## Methods

- `async def generate_images(self, prompt: Union[str, ImageGenerationPrompt], model: Optional[Union[str, GoogleModel]]=None, reference_image: Optional[Path]=None, output_directory: Optional[Path]=None, aspect_ratio: Optional[str]=None, resolution: Optional[str]=None, number_of_images: Optional[int]=None, negative_prompt: Optional[str]=None, person_generation: Optional[str]=None, safety_filter_level: Optional[str]=None, seed: Optional[int]=None, add_watermark: Optional[bool]=None, output_mime_type: Optional[str]=None, service_tier: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, **kwargs: Any) -> AIMessage` — Generates images using Google's Imagen models.
- `async def create_conversation_script(self, report_data: ConversationalScriptConfig, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, user_id: Optional[str]=None, session_id: Optional[str]=None, temperature: float=0.7, use_structured_output: bool=False, max_lines: int=20) -> AIMessage` — Creates a conversation script using Google's Generative AI.
- `async def generate_speech(self, prompt_data: SpeechGenerationPrompt, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH_TTS, output_directory: Optional[Path]=None, system_prompt: Optional[str]=None, temperature: float=0.7, mime_format: str='audio/wav', user_id: Optional[str]=None, session_id: Optional[str]=None, max_retries: int=3, retry_delay: float=1.0) -> AIMessage` — Generates speech from text using either a single voice or multiple voices.
- `async def create_speech(self, prompt: str, voice: Union[str, SpeakerConfig]='Puck', output_path: Optional[Union[str, Path]]=None, generate_script: bool=True, speaker_count: int=1, language: str='en-US', prompt_instruction: Optional[str]=None) -> AIMessage` — Generates speech from text, optionally creating a script first.
- `async def video_generation(self, prompt: Union[str, VideoGenInput], output_directory: Optional[Union[str, Path]]=None, model: Union[str, GoogleModel]=GoogleModel.VEO_3_1, aspect_ratio: Union[str, AspectRatio]=AspectRatio.RATIO_16_9, negative_prompt: Optional[str]=None, number_of_videos: int=1, reference_image: Optional[Union[str, Path, Image.Image]]=None, generate_image_first: bool=False, image_prompt: Optional[str]=None, duration: int=8, resolution: Optional[str]=None, person_generation: str='allow_adult', include_audio: bool=True, last_frame: Optional[Union[str, Path, Image.Image]]=None, reference_images: Optional[List[Union[str, Path, Image.Image]]]=None, reference_type: str='asset', extend_video: Optional[Any]=None, seed: Optional[int]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, **kwargs: Any) -> AIMessage` — Generates videos using Google's Veo models.
- `async def generate_music_stream(self, prompt: str, genre: Optional[Union[str, MusicGenre]]=None, mood: Optional[Union[str, MusicMood]]=None, bpm: int=90, temperature: float=1.0, density: float=0.5, brightness: float=0.5, timeout: int=300) -> AsyncIterator[bytes]` — Stream music using Lyria RealTime API.
- `async def generate_music(self, prompt: str, genre: Optional[Union[str, MusicGenre]]=None, mood: Optional[Union[str, MusicMood]]=None, bpm: int=90, temperature: float=1.0, density: float=0.5, brightness: float=0.5, timeout: int=300) -> AsyncIterator[bytes]` — Deprecated: Use generate_music_stream() instead.
- `async def generate_music_batch(self, prompt: str, negative_prompt: Optional[str]=None, seed: Optional[int]=None, sample_count: int=1, output_directory: Optional[Path]=None, genre: Optional[Union[str, MusicGenre]]=None, mood: Optional[Union[str, MusicMood]]=None, timeout: int=120) -> List[Path]` — Generate music using Vertex AI Lyria batch API.
- `async def generate_image(self, prompt: Union[str, ImageGenerationPrompt], model: Optional[Union[str, GoogleModel]]=None, reference_images: Optional[List[Union[str, Path, Image.Image]]]=None, google_search: bool=False, aspect_ratio: Optional[Union[str, AspectRatio]]=None, resolution: Optional[Union[str, ImageResolution]]=None, number_of_images: Optional[int]=None, negative_prompt: Optional[str]=None, person_generation: Optional[str]=None, safety_filter_level: Optional[str]=None, seed: Optional[int]=None, add_watermark: Optional[bool]=None, output_mime_type: Optional[str]=None, service_tier: Optional[str]=None, temperature: Optional[float]=None, prompt_instruction: Optional[str]=None, output_directory: Optional[str]=None, as_base64: bool=False, user_id: Optional[str]=None, session_id: Optional[str]=None, stateless: bool=True, **kwargs: Any) -> AIMessage` — Generate images using Google's Gemini image models (a.k.a. Nano-Banana).
- `async def generate_videos(self, prompt: Union[str, VideoGenerationPrompt], reference_image: Optional[Path]=None, output_directory: Optional[Path]=None, mime_format: str='video/mp4', model: Union[str, GoogleModel]=GoogleModel.VEO_3_1) -> AIMessage` — Generate a video using the specified model and prompt (handler-facing method).
- `async def generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path]=None, file_manager: Optional[FileManagerInterface]=None, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Generates a complete video reel from a high-level request.
- `async def generate_image_batch(self, requests: List[Dict[str, Any]], use_flex: bool=False, persist_results: bool=True, batch_id: Optional[str]=None, save_dir: Optional[Union[str, Path]]=None, **kwargs) -> List[Union[AIMessage, Exception]]` — Generate multiple images in batch using Google's image models.
- `async def generate_video_batch(self, requests: List[Dict[str, Any]], persist_results: bool=True, batch_id: Optional[str]=None, save_dir: Optional[Union[str, Path]]=None, **kwargs) -> List[Union[AIMessage, Exception]]` — Generate multiple videos in batch using Google's Veo models.
