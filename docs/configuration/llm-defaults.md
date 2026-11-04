# Per-component LLM defaults (FEAT-796)

## Variables

| Variable | Component | Builtin default |
|---|---|---|
| `DEFAULT_LLM` | Global fallback | `None` (falls back to builtin) |
| `AGENT_LLM` | Agent | `google:gemini-2.5-pro` |
| `CREW_LLM` | Crew | `google:gemini-2.5-pro` |
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

The `UsageRecord.component` field captures the component tag for LLM calls. It is durable store/span data for attribution and is never used as a metric label. The tag values are:

- `AGENT` (Agent HTTP handler)
- `CREW` (AgentCrew entry points)
- `EXPERT_JUDGMENT`, `EXPERT_BALANCED`, `EXPERT_TEMPLATED` (ExpertAgent tiers)
- `None` when the call is not attributed to a component

`DEFAULT_LLM` only changes which provider/model is selected; it does not add a tag value.
