# F006 — There is a documented 7-step recipe for adding a provider

**Path**: `docs/clients/openai-compatible.md` § "Adding a New OpenAI-Compatible Provider"

1. Subclass `OpenAIBaseClient` (never `OpenAIClient`).
2. Register in `LLMFactory.SUPPORTED_CLIENTS` (`factory.py`).
3. Override `get_client()` only for a non-`AsyncOpenAI` SDK or extra client kwargs.
4. Override `_chat_completion()` only to inject payload data or adapt a native SDK.
5. Re-add business-logic overrides only for real provider-specific behavior —
   *"write a payload-parity test first."*
6. Never set model defaults to a `gpt-*` id.
7. Add a smoke script in `examples/clients/smoke/` + a doc page.

Existing test rosters that a new subclass must be added to:
- `tests/clients/test_openai_compatible_defaults.py::WIRE_SUBCLASSES`
- `tests/clients/test_openai_base_parity.py::WIRE_SUBCLASSES`

**Implication**: scope, file list and acceptance criteria are pre-determined by
an existing, enforced convention — very low design risk for the CC path.
