# count_input overhead over a growing coding-loop history (2026-09-12)

Resolves the open question in
`sdd/proposals/sdd-coder-bedrock-token-telemetry.brainstorm.md`:
"What is the actual overhead of `count_input` over a long loop?"

Measured: `MantleBudgetAdapter.count_input` (packages/ai-parrot-client-amazon/
src/parrot/clients/amazon/budget.py:300-347) against a synthetic chat body whose
history grows one assistant message (~120 words) + one tool result (~600 words)
per turn, 8 tool definitions, over 60 turns. Counter resolved to
`tiktoken:o200k_base` (local, no download).

| turn | history (est. tokens) | count_input (ms) | cumulative |
|---|---|---|---|
| 1  |   6,061 |  4.9 |    4.9 ms |
| 5  |  15,654 |  9.4 |   33.4 ms |
| 10 |  27,662 | 13.4 |   93.4 ms |
| 20 |  51,713 | 25.1 |  283.6 ms |
| 30 |  75,715 | 38.6 |  639.8 ms |
| 40 |  99,649 | 73.1 | 1291.9 ms |
| 50 | 123,693 | 63.4 | 2141.9 ms |
| 60 | 147,674 | 65.4 | 2773.4 ms |

**Total tokenizer wall-clock for one 60-turn attempt: 2.77 s.**

Conclusion: cost grows linearly per turn with history size (so quadratically
over the loop, as predicted) but the constant is tiny. Against per-turn network
latency of 10-60 s on a 480B model, the tokenizer is 0.1-0.5% of attempt
wall-clock. The overhead is NOT a reason to restrict the shadow scope to
measurement campaigns.

Caveat worth recording: `count_input` is declared `async` but calls the counter
synchronously (budget.py:345), so it blocks the event loop. With N seats running
concurrently in one MCP-server process, each seat's ~65 ms tail-turn pass blocks
the others; ~2.8 s of blocking per attempt, ~11 s per 4-seat wave. Tolerable
against 10-20 minute attempts; a one-line `asyncio.to_thread` would remove it if
it ever matters.

Script: scratchpad `bench_count_input.py` (synthetic payload, no network, no spend).
