---
id: F023
query_id: Q023
type: grep
intent: Which clients implement ask_to_image / image_understanding / video_understanding; confirm absent on AbstractClient
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F023 — ask_to_image exists on Anthropic/Google/OpenAI clients only; not on AbstractClient

## Summary
A grep over `packages/**/*.py` (tests excluded) finds `ask_to_image` in exactly four places: AnthropicClient, ClaudeAgentClient (which raises NotImplementedError), GoogleGenAIClient and the OpenAI client. `image_understanding` and `video_understanding` exist only in the Google `GoogleAnalysis` mixin, which `GoogleGenAIClient` composes. `AbstractClient` in `parrot/clients/base.py` has none of these methods, so a vision step needs a capability check (`hasattr`) or an injected client of a specific provider. The three `ask_to_image` implementations share the core parameters `prompt`, `image`, `reference_images`, `model`, `max_tokens`, `temperature`, `structured_output`, `history` and `no_memory`, with provider-specific extras.

## Citations
- path: `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py`
  lines: 1329-1342
  symbol: `AnthropicClient.ask_to_image`
  excerpt: |
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: Union[ClaudeModel, str, None] = None, max_tokens: Optional[int] = None,
        temperature: Optional[float] = None, structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False, history: Optional[Sequence[HistoryMessage]] = None,
        system_prompt: Optional[str] = None, context_1m: bool = False, no_memory: bool = False) -> AIMessage:
- path: `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py`
  lines: 1036-1040
  symbol: `ClaudeAgentClient.ask_to_image`
  excerpt: |
    async def ask_to_image(self, *args: Any, **kwargs: Any) -> AIMessage:
        raise NotImplementedError(
            "ClaudeAgentClient does not support vision / image inputs. " "Use AnthropicClient.ask_to_image instead."
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 5160-5172
  symbol: `GoogleGenAIClient.ask_to_image`
  excerpt: |
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes],
        reference_images: Optional[Union[List[Path], List[bytes]]] = None,
        model: Union[str, GoogleModel] = None, max_tokens: Optional[int] = None,
        temperature: Optional[float] = None, structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False, history: Optional[Sequence[HistoryMessage]] = None,
        no_memory: bool = False) -> AIMessage:
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 103-103
  symbol: `GoogleGenAIClient`
  excerpt: |
    class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 438-452
  symbol: `GoogleAnalysis.image_understanding`
  excerpt: |
    async def image_understanding(self, prompt: str,
        images: Union[str, Path, bytes, Image.Image, List[Union[str, Path, bytes, Image.Image]]],
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_FLASH_PREVIEW,
        prompt_instruction: Optional[str] = None, user_id=None, session_id=None, stateless: bool = True,
        timeout: Optional[int] = 600, temperature: Optional[float] = None, detect_objects: bool = False,
        response_schema: Optional[Any] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None) -> AIMessage:
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 208-208
  symbol: `GoogleAnalysis.video_understanding`
  excerpt: |
    async def video_understanding(
- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py`
  lines: 1468-1479
  symbol: `OpenAIClient.ask_to_image`
  excerpt: |
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: str = OpenAIModel.GPT5_MINI.value, max_tokens: int = None, temperature: float = None,
        structured_output: Optional[type] = None, history: Optional[Sequence[HistoryMessage]] = None,
        no_memory: bool = False, low_quality: bool = False) -> AIMessage:
- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 254-254
  symbol: `AbstractClient`
  excerpt: |
    class AbstractClient(EventEmitterMixin, ABC):
    # grep "ask_to_image|image_understanding" over base.py (2939 lines): 0 matches

## Notes
- CONFIRMED that it is not on AbstractClient.
- Google's `ask_to_image` accepts only `Path` or `bytes` (no PIL) and has no `system_prompt`, while Anthropic's has `system_prompt` and `context_1m`. None of them accept a URL string for `image`. Only Google's `image_understanding` types `images` as `str`, and I did not verify whether that str means a URL or a path.
- Groq, Grok, Bedrock, vLLM and HF clients have no vision method.

