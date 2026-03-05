# Finance Demo Full Cycle

End-to-end demo of the finance trading pipeline: research → deliberation → execution → summary.

## Quick Start

```bash
# DRY_RUN — local simulation, no API keys needed
python -m parrot.finance.demo_full_cycle --print

# PAPER — real Alpaca paper-API calls
python -m parrot.finance.demo_full_cycle --mode paper --print

# Save output to file
python -m parrot.finance.demo_full_cycle --mode paper --output demo_output.md
```

## Execution Modes

### `dry_run` (default)

Local simulation via `VirtualPortfolio`. No trading API keys required.

- Orders are filled instantly with configurable slippage (5 bps) and delay (100ms)
- No network calls to any broker
- Useful for testing the full pipeline logic without credentials

### `paper`

Real API calls to broker sandbox/paper environments:

| Broker | Endpoint | Port | Requirements |
|--------|----------|------|--------------|
| **Alpaca** | `paper-api.alpaca.markets` | HTTPS | `ALPACA_TRADING_API_KEY` + `ALPACA_TRADING_API_SECRET` (paper account) |
| **IBKR** | TWS/Gateway simulation | 7497 (or custom `IBKR_PORT`) | TWS or IB Gateway running in paper mode |

- Alpaca orders go through real order matching on their paper exchange
- IBKR is optional — if TWS is not running, the demo gracefully skips it with a warning
- Orders fill at real market paper-prices, no simulated slippage

## Pipeline Stages

```
  ┌──────────┐    ┌───────────────┐    ┌──────────────┐    ┌───────────┐
  │ Research │───▸│ Deliberation  │───▸│  Execution   │───▸│  Summary  │
  │ (5 crews)│    │ (CIO+Analysts)│    │ (Orchestrator)│    │  Report   │
  └──────────┘    └───────────────┘    └──────────────┘    └───────────┘
```

1. **Research** — `FinanceResearchService` runs 5 research crews sequentially (macro, equity, crypto, sentiment, risk). Requires Redis.
2. **Deliberation** — `CommitteeDeliberation` orchestrates cross-pollination between analysts, CIO-led debate, and Secretary memo generation.
3. **Execution** — `ExecutionOrchestrator` converts memo recommendations into `TradingOrder`s, routes them to the appropriate executor (Alpaca for stocks, Binance/Kraken for crypto, IBKR for multi-asset), and processes them.
4. **Summary** — Human-readable report of memo, orders, fills, and portfolio state.

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--mode` | `dry_run` | `dry_run` or `paper` |
| `--redis-url` | `REDIS_URL` env or `redis://localhost:6379` | Redis connection for research service |
| `--print` | off | Print summary to stdout |
| `--output FILE` | none | Write summary to a file |

## Prerequisites

### All Modes

- Redis running locally (for `FinanceResearchService`)
- LLM API keys configured (Gemini, Anthropic) for research and deliberation agents

### Paper Mode Only

- **Alpaca**: Paper trading account credentials in env:
  ```
  ALPACA_TRADING_API_KEY=PKxxxxx
  ALPACA_TRADING_API_SECRET=xxxxx
  ALPACA_PCB_PAPER=true
  ```
- **IBKR** (optional): TWS or IB Gateway running in paper/simulated mode on port 7497.
  See `docs/finance/docker-compose.yml` for a Docker-based IB Gateway setup.

## Programmatic Usage

```python
from parrot.finance.demo_full_cycle import run_demo, format_execution_summary

# DRY_RUN
result = await run_demo()

# PAPER
result = await run_demo(mode="paper")

# Format output
print(format_execution_summary(result))

# Access structured data
print(result.memo.id)
print(result.mode)  # "dry_run" or "paper"
for report in result.execution_reports:
    print(f"{report.execution_details.symbol}: {report.action_taken}")
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PAPER_TRADING_MODE` | Global default: `paper`, `dry_run`, or `live` |
| `REDIS_URL` | Redis connection string |
| `ALPACA_TRADING_API_KEY` | Alpaca API key (paper account) |
| `ALPACA_TRADING_API_SECRET` | Alpaca API secret |
| `ALPACA_PCB_PAPER` | Set to `true` for paper trading |
| `IBKR_HOST` | IBKR TWS host (default: `127.0.0.1`) |
| `IBKR_PORT` | IBKR TWS port (default: `7497` for paper, `7496` for live) |
