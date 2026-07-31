# Performance Evaluation Benchmark

**Date**: 2026-07-30
**Status**: Approved
**Location**: `examples/benchmarks/perf_eval.py`

## Purpose

A standalone script that benchmarks AI-Parrot agent performance across multiple
LLM providers, measuring wall-clock latency, memory usage, and token consumption.
Inspired by [Agno's PerformanceEval](https://docs.agno.com/evals/performance/overview)
but using AI-Parrot's `Chatbot` and `AIMessage` primitives.

## Models Under Test

| Provider string                         | Label              |
|-----------------------------------------|--------------------|
| `anthropic:claude-haiku-4-5-20251001`   | Claude Haiku 4.5   |
| `google:gemini-3.1-flash-lite`          | Gemini Flash Lite  |
| `openai:gpt-5.5`                        | GPT-5.5            |

## Questions

Three short prompts to keep token cost minimal while providing variance:

1. "What is the capital of France?"
2. "Explain quantum computing in one sentence."
3. "What is 25 * 47?"

## Iterations

3 iterations per model. Each iteration runs all 3 questions sequentially.
Total: 9 calls per model, 27 calls overall.

## Measurement Strategy

### Time
`time.perf_counter()` around each `await bot.ask()` call. Captures wall-clock
latency including network round-trip.

### Memory
`tracemalloc` snapshots before/after each call. Reports peak memory delta in MiB.
Captures Python-side memory only (framework overhead), not provider SDK internals.

### Tokens
Read from `AIMessage.usage`: `input_tokens`, `output_tokens`, `total_tokens`.
Uses AI-Parrot's unified `CompletionUsage` model which normalizes across providers.

## Agent Configuration

- **Class**: `Chatbot`
- **System prompt**: `"Be concise, reply with one sentence."`
- **Tools**: None
- **Memory/history**: Disabled
- **Vector store**: None
- **Setup**: `Chatbot` created and `configure()`d once per model, outside the
  measurement loop. Only the `bot.ask()` call is timed.

## Error Handling

If a provider is not configured (missing API key), the script catches the error,
prints a warning, and continues with remaining models. Partial results are still
displayed.

## Output Format

Two console tables printed via Python's built-in string formatting (no external
dependency):

### 1. Per-call detail table
Each individual call showing: model, question (truncated), time, memory delta,
input tokens, output tokens.

### 2. Per-model summary table
Aggregated stats per model: avg/min/max time, avg memory, avg input/output tokens.

## Non-Goals

- No correctness scoring (that's `parrot.eval`'s job)
- No reusable `PerformanceEval` class — single script, extract later if needed
- No streaming benchmark — `bot.ask()` only (non-streaming)
- No CLI arguments — constants at the top of the file are easy to edit
