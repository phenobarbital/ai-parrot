---
type: Wiki Entity
title: OpenAIClient
id: class:parrot.clients.gpt.OpenAIClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for interacting with OpenAI's API.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# OpenAIClient

Defined in [`parrot.clients.gpt`](../summaries/mod:parrot.clients.gpt.md).

```python
class OpenAIClient(AbstractClient)
```

Client for interacting with OpenAI's API.

## Methods

- `async def get_client(self) -> 'AsyncOpenAI'` — Initialize the OpenAI client.
- `async def ask(self, prompt: str, model: Union[str, OpenAIModel]=OpenAIModel.GPT4_1, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, vector_store_ids: Optional[List[str]]=None, enable_web_search: bool=True, enable_code_interpreter: bool=False, lazy_loading: bool=False) -> AIMessage` — Ask OpenAI a question with optional conversation memory.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended model execution.
- `async def ask_stream(self, prompt: str, model: Union[str, OpenAIModel]=OpenAIModel.GPT5_MINI, max_tokens: int=None, temperature: float=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, vector_store_ids: Optional[List[str]]=None, enable_web_search: bool=True, enable_code_interpreter: bool=False, lazy_loading: bool=False) -> AsyncIterator[Union[str, AIMessage]]` — Stream OpenAI's response with optional conversation memory.
- `async def batch_ask(self, requests) -> List[AIMessage]` — Process multiple requests in batch.
- `async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images: Optional[List[Union[Path, bytes, Image.Image]]]=None, model: str=OpenAIModel.GPT5_MINI.value, max_tokens: int=None, temperature: float=None, structured_output: Optional[type]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, no_memory: bool=False, low_quality: bool=False) -> AIMessage` — Ask OpenAI a question about an image with optional conversation memory.
- `async def summarize_text(self, text: str, max_length: int=500, min_length: int=100, model: Union[OpenAIModel, str]=OpenAIModel.GPT5_MINI, temperature: Optional[float]=None, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Generate a concise summary of *text* (single paragraph, stateless).
- `async def translate_text(self, text: str, target_lang: str, source_lang: Optional[str]=None, model: Union[OpenAIModel, str]=OpenAIModel.GPT5_MINI, temperature: float=0.2, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Translate *text* from *source_lang* (auto‑detected if None) into *target_lang*.
- `async def extract_key_points(self, text: str, num_points: int=5, model: Union[OpenAIModel, str]=OpenAIModel.GPT5_MINI, temperature: float=0.3, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Extract *num_points* bullet‑point key ideas from *text* (stateless).
- `async def analyze_sentiment(self, text: str, model: Union[OpenAIModel, str]=OpenAIModel.GPT5_MINI, temperature: float=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Perform sentiment analysis on *text* and return a structured explanation.
- `async def analyze_product_review(self, review_text: str, product_id: str, product_name: str, model: Union[OpenAIModel, str]=OpenAIModel.GPT5_MINI, temperature: float=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Analyze a product review and extract structured information.
- `async def image_identification(self, *, image: Union[Path, bytes, 'Image.Image'], detections: List[DetectionBox], shelf_regions: List[ShelfRegion], reference_images: Optional[List[Union[Path, bytes, 'Image.Image']]]=None, model: Union[OpenAIModel, str]=OpenAIModel.GPT4_1_MINI, prompt: Optional[str]=None, temperature: float=0.0, ocr_hints: bool=True, user_id: Optional[str]=None, session_id: Optional[str]=None, max_tokens: Optional[int]=None) -> List[IdentifiedProduct]` — Step-2: Identify products using the detected boxes + reference images.
- `async def generate_video(self, prompt: Union[str, Any], *, model_name: str='sora-2', duration: Optional[int]=None, ratio: Optional[str]=None, output_path: Optional[Union[str, Path]]=None, poll_interval: float=2.0, timeout: float=15 * 60, extra: Optional[Dict[str, Any]]=None)` — Generate a video with Sora using the Videos API and return an AIMessage.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for OpenAIClient.
