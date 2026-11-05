# Bots & Agents

A **bot** in AI-Parrot is a stateful conversational entity wrapped around an `AbstractClient`. An **agent** extends that with tool calling and a ReAct-style reasoning loop. A **crew** orchestrates several agents together via sequential, parallel or DAG-based execution. These three primitives provide a flexible toolkit for building everything from simple chatbots to complex multi-agent systems that can tackle sophisticated problems.

## Key Concepts

- **AbstractBot** — the base class for everything conversational in the framework. It provides the foundation for building stateful chat components that can maintain context across multiple turns.
- **Chatbot** — a single-LLM, single-turn-aware, stateful chat component. It's ideal for straightforward conversational applications where you need a simple, reliable chat interface.
- **Agent** — a tool-using agent that follows a ReAct-style reasoning loop. It can call tools, reason about their outputs, and iteratively refine its responses to solve complex tasks.
- **AgentCrew** — an orchestrator that can run agents sequentially, in parallel, or as a DAG. This enables sophisticated workflows where different agents specialize in different aspects of a problem.

## What You Can Build

- Build a simple chatbot for customer support that responds to user queries and maintains context across a conversation.
- Create a tool-using agent that can search the web, read files, and execute code to answer complex questions or perform automated tasks.
- Orchestrate multiple agents to solve complex problems, such as a research assistant that coordinates a writer, a coder, and a reviewer to produce a comprehensive report.

## Deep Dive

For API reference, class signatures, and implementation details, see the [Bots & Agents section in the Wiki](https://github.com/phenobarbital/ai-parrot/wiki/Home).
