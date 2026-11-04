# Per-component LLM defaults (FEAT-796)

## Variables

| Variable | Component | Builtin default |
|---|---|---|
| `DEFAULT_LLM` | Global fallback | `None` (falls back to builtin) |
| `AGENT_LLM` | Agent | Builtin agent default |
| `CREW_LLM` | Crew | Builtin crew default |
| `EXPERT_JUDGMENT_LLM` | Expert (Judgment tier) | `google:gemini-2.5-pro` |
| `EXPERT_BALANCED_LLM` | Expert (Balanced tier) | `google:gemini-2.5-flash` |
| `EXPERT_TEMPLATED_LLM` | Expert (Templated tier) | `google:gemini-2.5-flash` |

## API keys

The API keys follow the pattern `<COMPONENT>_<PROVIDER>_API_KEY`. For Google providers, the pattern resolves to `GOOGLE` as the provider token. The cascade order is as follows:

1. Explicit credential in the component's configuration (e.g., `api_key` in `llm_kwargs`)
2. `<COMPONENT>_<PROVIDER>_API_KEY` (e.g., `CREW_GOOGLE_API_KEY`)
3. Legacy variables (if any)
4. `GOOGLE_API_KEY` (for Google providers)

`CREW_GOOGLE_API_KEY` is the primary key for crew operations, with `CREW_AI_KEY` as a silent alias. If neither is set, the system falls back to `GOOGLE_API_KEY`.

## Usage attribution

The `UsageRecord.component` field captures the component tag for LLM calls. This field is used for attribution and is never used as a metric label. The possible values include:

- `agent`
- `crew`
- `expert_judgment`
- `expert_balanced`
- `expert_templated`
- `global` (for `DEFAULT_LLM`)
