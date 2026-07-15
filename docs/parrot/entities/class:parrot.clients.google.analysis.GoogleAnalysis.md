---
type: Wiki Entity
title: GoogleAnalysis
id: class:parrot.clients.google.analysis.GoogleAnalysis
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin class for Google Generative AI analysis capabilities.
---

# GoogleAnalysis

Defined in [`parrot.clients.google.analysis`](../summaries/mod:parrot.clients.google.analysis.md).

```python
class GoogleAnalysis
```

Mixin class for Google Generative AI analysis capabilities.

## Methods

- `def analyze_sentiment(self, text: str, model: Union[GoogleModel, str]=GoogleModel.GEMINI_2_5_FLASH, temperature: Optional[float]=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None, use_structured: bool=False) -> AIMessage` — Perform sentiment analysis on text and return an AIMessage response.
- `def analyze_product_review(self, review_text: str, product_id: str, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, temperature: Optional[float]=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None, use_structured: bool=True) -> AIMessage` — Analyze a product review and extract structured or unstructured information.
- `async def video_understanding(self, prompt: str, model: Union[str, GoogleModel]=GoogleModel.GEMINI_FLASH_LATEST, prompt_instruction: Optional[str]=None, video: Optional[Union[str, Path]]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, stateless: bool=True, offsets: Optional[tuple[str, str]]=None, reference_images: Optional[List[Union[str, Path, Image.Image]]]=None, timeout: Optional[int]=600, top_p: Optional[float]=None, top_k: Optional[int]=None, max_output_tokens: Optional[int]=None, candidate_count: Optional[int]=None, progress_log_interval: int=10, as_image: bool=False, interval_sec: Optional[int]=None, structured_output: Union[type, StructuredOutputConfig, None]=None) -> AIMessage` — Using a video (local or youtube) no analyze and extract information from videos.
- `async def image_understanding(self, prompt: str, images: Union[str, Path, bytes, Image.Image, List[Union[str, Path, bytes, Image.Image]]], model: Union[str, GoogleModel]=GoogleModel.GEMINI_3_FLASH_PREVIEW, prompt_instruction: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, stateless: bool=True, timeout: Optional[int]=600, temperature: Optional[float]=None, detect_objects: bool=False, response_schema: Optional[Any]=None, structured_output: Union[type, StructuredOutputConfig, None]=None) -> AIMessage` — Using single or multiple images to analyze and extract information, with optional object detection.
- `async def document_understanding(self, prompt: str, documents: Union[str, Path, List[Union[str, Path]]], model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, prompt_instruction: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, stateless: bool=True, timeout: Optional[int]=600, temperature: float=0.0, structured_output: Optional[Union[type, StructuredOutputConfig]]=None, max_output_tokens: Optional[int]=None) -> AIMessage` — Analyze and extract information from one or more documents.
- `async def image_identification(self, prompt: str, image: Union[Path, bytes, Image.Image], detections: List[DetectionBox], shelf_regions: List[ShelfRegion], reference_images: Optional[Dict[str, Union[Path, bytes, Image.Image]]]=None, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_PRO, temperature: float=0.0, user_id: Optional[str]=None, session_id: Optional[str]=None) -> List[IdentifiedProduct]` — Identify products using detected boxes, reference images, and Gemini Vision.
- `def summarize_text(self, text: str, max_length: int=1200, min_length: int=100, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, temperature: Optional[float]=None, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Generates a summary for a given text in a stateless manner.
- `def translate_text(self, text: str, target_lang: str, source_lang: Optional[str]=None, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, temperature: Optional[float]=0.2, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Translates a given text from a source language to a target language.
- `def extract_key_points(self, text: str, num_points: int=5, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, temperature: Optional[float]=0.3, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Extract *num_points* bullet-point key ideas from *text* (stateless).
- `async def detect_objects(self, image: Union[str, Path, Image.Image], prompt: str, reference_images: Optional[List[Union[str, Path, Image.Image]]]=None, output_dir: Optional[Union[str, Path]]=None) -> List[Dict[str, Any]]` — Detects objects and segmentation masks using Gemini 3 Flash.
