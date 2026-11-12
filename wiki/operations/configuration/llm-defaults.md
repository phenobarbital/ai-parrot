---
title: "Per-component and per-agent LLM defaults (FEAT-796, FEAT-882)"
---

# Per-component and per-agent LLM defaults (FEAT-796, FEAT-882)

## Variables

| Variable | Component | Builtin default |
|---|---|---|
| `DEFAULT_LLM` | Global fallback | `None` (falls back to builtin) |
| `AGENT_LLM` | Agent | `google:gemini-4-argon` |
| `CREW_LLM` | Crew | `google:gemini-4-argon` |
| `FLOW_LLM` | AgentsFlow | `google:gemini-4-argon` (applied only when `FLOW_LLM` is set) |
| `EXPERT_JUDGMENT_LLM` | Expert (Judgment tier) | `google:gemini-4-argon` |
| `EXPERT_BALANCED_LLM` | Expert (Balanced tier) | `google:gemini-3.8-flash` |
| `EXPERT_TEMPLATED_LLM` | Expert (Templated tier) | `google:gemini-3.8-flash` |

`gemini-4-argon` does not support Gemini context caching. Set `AGENT_LLM=google:gemini-3.8-flash`
(or `CREW_LLM`, `EXPERT_JUDGMENT_LLM`) to keep caching on that component.

## API keys

The API keys follow the pattern `<COMPONENT>_<PROVIDER>_API_KEY`. For Google providers, the pattern resolves to `GOOGLE` as the provider token. The cascade order is as follows:

1. Explicit credential in the component's configuration (e.g., `api_key` in `llm_kwargs`)
2. `<COMPONENT>_<PROVIDER>_API_KEY` (e.g., `CREW_GOOGLE_API_KEY`)
3. Legacy variables (if any)
4. `GOOGLE_API_KEY` (for Google providers)

`CREW_GOOGLE_API_KEY` is the primary key for crew operations, with `CREW_AI_KEY` as a silent alias. If neither is set, the system falls back to `GOOGLE_API_KEY`.

AgentsFlow uses `FLOW_<PROVIDER>_API_KEY`, for example `FLOW_GOOGLE_API_KEY`. FLOW has no legacy alias.
Component defaults are injected only into agents that do not have an explicit credential.

## Per-agent variables

Use `<AGENT>_MODEL` to select a model for one agent. Its value may be `provider:model`, or a bare model
name that inherits the agent's current provider. Use `<AGENT>_<PROVIDER>_API_KEY` for that agent's provider
credential. Provider tokens follow the component-key convention, including `GOOGLE` for the Google family.

`<AGENT>` comes from the agent name: uppercase it, replace each run of non-alphanumeric characters with a
single underscore, and strip leading or trailing underscores. For example, `odoo-helpdesk` becomes
`ODOO_HELPDESK`.

Do not use agent names that normalize to the reserved tokens `AGENT`, `CREW`, `FLOW`, `DEFAULT`, or the
Expert tier tokens `EXPERT_JUDGMENT`, `EXPERT_BALANCED`, and `EXPERT_TEMPLATED`. Per-agent variables are
ignored for those names. Normalization can also create collisions: for example, `odoo-helpdesk` and
`odoo_helpdesk` both use `ODOO_HELPDESK`. Colliding names cannot be disambiguated through environment
variables.

## Precedence

The following sources are considered from highest to lowest precedence:

| # | Source | Model | Key |
|---|---|---|---|
| 1 | Live `AbstractClient` instance as `llm` | wins; env ignored | wins; env ignored |
| 2 | Explicit credential in `llm_kwargs` (`api_key`, `credentials_file`, `credentials`, `vertexai`) | — | wins |
| 3 | `<AGENT>_MODEL` / `<AGENT>_<PROVIDER>_API_KEY` | overrides declared `llm`/`model` | applies |
| 4 | `llm` / `model` declared in code, `CrewDefinition` or DB | applies | — |
| 5 | Component default: `FLOW_*` (flow agents) / `CREW_*` (crew agents) / `AGENT_*` (handler) | applies when #4 absent | applies |
| 6 | `DEFAULT_LLM` | applies when #4,#5 absent | — |
| 7 | Provider-wide key (`GOOGLE_API_KEY`, …) | — | final fallback |

The per-agent key in row 3 is resolved for the provider selected by the model decision. Component-default
keys placed in `llm_kwargs` are not explicit credentials: a per-agent key therefore overrides a FLOW, CREW,
AGENT, or Expert component key, preserving row 3 over row 5.

## AgentsFlow and already-configured agents

FLOW defaults reach only unconfigured agents, which in practice means agents added to programmatic flows
before configuration. Registry agents are already configured before AgentsFlow receives them, so the flow
cannot replace their client or inject `FLOW_<PROVIDER>_API_KEY`. Configure those agents with
`<AGENT>_<PROVIDER>_API_KEY` (and `<AGENT>_MODEL` when a model override is needed). AgentsFlow emits one INFO
log per skipped agent name per process.

## Usage attribution

The `UsageRecord.component` field captures the component tag for LLM calls. It is durable store/span data for attribution and is never used as a metric label. The tag values are:

- `AGENT` (Agent HTTP handler)
- `CREW` (AgentCrew entry points)
- `FLOW` (AgentsFlow entry points)
- `EXPERT_JUDGMENT`, `EXPERT_BALANCED`, `EXPERT_TEMPLATED` (ExpertAgent tiers)
- `None` when the call is not attributed to a component

`DEFAULT_LLM` only changes which provider/model is selected; it does not add a tag value.
