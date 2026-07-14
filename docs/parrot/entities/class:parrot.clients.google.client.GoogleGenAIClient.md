---
type: Wiki Entity
title: GoogleGenAIClient
id: class:parrot.clients.google.client.GoogleGenAIClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for interacting with Google's Generative AI, with support for parallel
  function calling.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
- concept: class:parrot.clients.google.analysis.GoogleAnalysis
  rel: extends
---

# GoogleGenAIClient

Defined in [`parrot.clients.google.client`](../summaries/mod:parrot.clients.google.client.md).

```python
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)
```

Client for interacting with Google's Generative AI, with support for parallel function calling.

Only Gemini-2.5-pro works well with multi-turn function calling.
Supports both API Key (Gemini Developer API) and Service Account (Vertex AI).

**Combined tools + structured output**: for models whose identifier starts with a prefix
in ``_default_combined_call_prefixes`` (default: ``gemini-3.1-pro``, ``gemini-3.5-flash``,
``gemini-3.1-flash-lite``), ``ask()`` and ``ask_stream()`` send ``tools`` and
``response_schema`` in a single ``GenerateContentConfig`` (no reformat round-trip).
For all other models (e.g. ``gemini-2.5-pro``), the legacy two-phase flow is preserved.
Override the whitelist per-instance via ``GoogleGenAIClient(combined_call_prefixes=...)``.

## Methods

- `async def get_client(self, model: str=None, **kwargs) -> genai.Client` — Construct and return a fresh Google GenAI client for the current loop.
- `async def close(self) -> None` — Close all per-loop SDK clients.
- `def clean_google_schema(self, schema: dict) -> dict` — Clean a Pydantic-generated schema for Google Function Calling compatibility.
- `async def ask(self, prompt: str, model: Union[str, GoogleModel]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, use_thinking: Optional[bool]=None, stateless: bool=False, deep_research: bool=False, file_search_store_names: Optional[List[str]]=None, lazy_loading: bool=False, max_iterations: int=15, **kwargs) -> AIMessage` — Ask a question to Google's Generative AI with support for parallel tool calls.
- `async def ask_stream(self, prompt: str, model: Union[str, GoogleModel]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, retry_config: Optional[StreamingRetryConfig]=None, on_max_tokens: Optional[str]='retry', tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, use_thinking: Optional[bool]=None, stateless: bool=False, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False, max_iterations: int=15, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Stream Google Generative AI's response using AsyncIterator with support for Tool Calling.
- `async def batch_ask(self, requests: List[Dict[str, Any]]) -> List[AIMessage]` — Process multiple requests in batch. Delegates to ask_batch for efficiency.
- `async def ask_batch(self, requests: List[Dict[str, Any]], use_flex: bool=False, wait_for_completion: bool=True, poll_interval: int=30, webhook_uri: Optional[str]=None, display_name: Optional[str]=None, **kwargs) -> Union[Any, List[AIMessage]]` — Execute a list of requests using Gemini Batch Mode or Flex Inference.
- `async def get_batch_job(self, job_name: str) -> Any` — Retrieve status of an active or completed Batch Job.
- `async def cancel_batch_job(self, job_name: str) -> Any` — Cancel an active Batch Job.
- `async def list_batch_jobs(self) -> List[Any]` — List active or past Batch Jobs.
- `async def persist_batch_results(self, results: List[AIMessage], batch_id: str, save_dir: Optional[Union[str, Path]]=None) -> Path` — Serialize and persist batch results (AIMessage objects, images, videos, and structured data)
- `async def download_and_parse_batch_results(self, job: Any, original_requests: List[Dict[str, Any]]) -> List[AIMessage]` — Download output file from completed Batch Job and parse to List[AIMessage].
- `async def ask_to_image(self, prompt: str, image: Union[Path, bytes], reference_images: Optional[Union[List[Path], List[bytes]]]=None, model: Union[str, GoogleModel]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, structured_output: Union[type, StructuredOutputConfig]=None, count_objects: bool=False, user_id: Optional[str]=None, session_id: Optional[str]=None, no_memory: bool=False) -> AIMessage` — Ask a question to Google's Generative AI using a stateful chat session.
- `async def deep_research(self, query: str, user_id: Optional[str]=None, session_id: Optional[str]=None, files: Optional[List[Union[str, Path]]]=None) -> AIMessage` — Execute a Deep Research task, optionally uploading files first.
- `async def question(self, prompt: str, model: Union[str, GoogleModel]=GoogleModel.GEMINI_2_5_FLASH, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig]=None, use_internal_tools: bool=False) -> AIMessage` — Ask a question to Google's Generative AI in a stateless manner,
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended model execution.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for GoogleGenAIClient.
