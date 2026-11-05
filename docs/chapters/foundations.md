# Foundations

The foundations layer holds the core abstractions every other module in AI-Parrot is built on: the hook/event bus, the data models shared between clients, bots and tools, and the architectural decisions that keep the framework vendor-agnostic and fully async. This layer provides the essential building blocks that enable the rest of the framework to function correctly, ensuring that all components can communicate and interact in a consistent manner.

## Key Concepts

- **Event bus** — a cross-cutting infrastructure that agents use to publish lifecycle events, attach observers and compose middleware. This allows different parts of the system to react to important events without tight coupling.
- **Pydantic data models** — `AIMessage`, `SourceDocument`, `MessageResponse`, `ToolCall` and friends serve as the lingua franca between clients, bots and integrations. These models ensure type safety and validation across the entire framework.
- **Async-first design** — the entire framework is built around async/await patterns, ensuring non-blocking I/O and efficient concurrency. This design choice is critical for handling multiple LLM calls, network operations, and background tasks simultaneously.

## What You Can Build

- Build a custom event-driven agent that reacts to lifecycle events (startup, shutdown, tool execution) to implement custom behavior at key moments.
- Create reusable data models for your own tools and integrations that integrate seamlessly with the existing framework, ensuring consistency across your application.
- Design middleware that can intercept and modify messages before they reach the LLM, enabling features like logging, validation, or transformation.

## Deep Dive

For API reference, class signatures, and implementation details, see the [Architecture section in the Wiki](https://github.com/phenobarbital/ai-parrot/wiki/Architecture).
