---
id: F006
query: Q007
type: grep+read
target: packages/ai-parrot/src/parrot/clients/base.py
---

# F006 — AbstractClient Verification

**Status**: Significant discrepancies from proposal

## AbstractClient(EventEmitterMixin, ABC) — packages/ai-parrot/src/parrot/clients/base.py

### Actual abstract methods
| Method | Signature | Notes |
|--------|-----------|-------|
| `ask` | `(prompt, model, max_tokens, temperature, files?, system_prompt?, structured_output?, tools?, ...) -> MessageResponse` | Primary abstract method |
| `ask_stream` | `(prompt, model?, ...) -> AsyncIterator[Union[str, AIMessage]]` | Streaming |
| `invoke` | `(prompt, *, output_type?, structured_output?, model?, ...) -> InvokeResult` | Structured output |
| `get_client` | `() -> Any` | Provider SDK client |
| `resume` | `(session_id, user_input, state) -> MessageResponse` | Session resumption |

### Concrete convenience method
- `complete(prompt, *, model?, system_prompt?, max_tokens?, temperature?) -> str` — wraps `ask()`

### CRITICAL DISCREPANCY
- **No `embed()` method** on AbstractClient
- **No `completion()` method** — actual is `ask()` / `complete()`
- **No `stream()` method** — actual is `ask_stream()`
- Proposal's reference to `AbstractClient` for embeddings is WRONG

### Correct embedding infrastructure
Embeddings live in `parrot.embeddings.EmbeddingModel` (separate ABC):
- `encode(texts) -> np.ndarray`
- Three providers: HuggingFace, OpenAI, Google
- `EmbeddingRegistry` for singleton caching
