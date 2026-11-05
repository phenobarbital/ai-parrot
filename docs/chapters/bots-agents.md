# Bots & Agents

A **bot** in AI-Parrot is a stateful conversational entity wrapped
around an `AbstractClient`. An **agent** extends that with tool calling
and a ReAct-style reasoning loop. A **crew** orchestrates several
agents together via sequential, parallel or DAG-based execution.

## What lives here

- **`AbstractBot`** — base class for everything conversational.
- **`Chatbot`** — single-LLM, single-turn-aware, stateful chat.
- **`Agent` / `BasicAgent`** — tool-using ReAct agents.
- **`AgentCrew`** — orchestrator with three execution modes:
  - `run_sequential()` — output of agent _n_ feeds agent _n+1_
  - `run_parallel()` — agents run concurrently, results merged
  - `run_flow()` — DAG defined with `task_flow()`
- **Plugin agents** — see `parrot.agents` for the dynamic-import
  registry that resolves agents by name.

## Picking the right primitive

| You need… | Use |
|---|---|
| A single-LLM conversation, no tools | `Chatbot` |
| One agent + a set of tools | `Agent` / `BasicAgent` |
| Several agents in a pipeline | `AgentCrew.run_sequential` |
| Independent agents fanning out | `AgentCrew.run_parallel` |
| Branching dependencies between agents | `AgentCrew.run_flow` |

## Read next

- [Agents](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-AgentTalk-Integration-Guide), [Agent Mesh](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-Agent-Mesh)
- [Crew Handler](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-Usage-Example)
- [WebAgent](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-WebAgent-%E2%80%94-Browser-Interaction-via-Chrome-DevTools) (Chrome DevTools) and
  [WebNavigatorAgent](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-WebNavigatorAgent-%E2%80%94-Catalogued-Web-Navigation-on-Your-Chrome-Profile) (catalogued browsing)
- [AgentCrew Guide](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-AgentCrew-User-Guide) and
  [AgentsFlow Guide](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-AgentsFlow-User-Guide)

## API reference

[API Reference → Bots](../api-reference/bots.md)
