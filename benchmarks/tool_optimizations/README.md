# Tool optimizations benchmark (FEAT-543)

Measures the three optimized workflows against the baseline a coding host
would otherwise use, reporting **primary tokens, delegate tokens, total
tokens, latency and correctness separately**.

## Run it

```bash
source .venv/bin/activate
python -m benchmarks.tool_optimizations --scenario all --runs 1
```

Offline by default: the delegate is a scripted fake, so the run is free and
deterministic. Reports land in `artifacts/tool-optimizations/benchmarks/`
as a JSON/Markdown pair (`artifacts/` is gitignored — copy a report
elsewhere if you need to share it).

A live comparison against the configured provider costs money and requires
at least five runs per scenario:

```bash
python -m benchmarks.tool_optimizations --scenario all --runs 5 --live
```

## Scenarios

| Name | Baseline | Optimized |
|---|---|---|
| `git_prepare` | The three shell commands from the spec's user-provided code | `git_fetch` + `git_preflight` + `git_prepare_files` |
| `targeted_read` | Whole-file `Read` of a 2,000-line module | `source_info` + one bounded `source_read` |
| `decided_task` | Primary model writes both files itself | `writer_generate` → bounded review → `writer_apply` → `pytest` |

## What the exit code means

Non-zero means an **optimized scenario failed its real acceptance test**.
Correctness parity is the only pass/fail criterion; token and latency
figures are informational.

## What is measured, and what is not claimed

- Baseline token counts are **estimates** (`estimate:chars_div_4`) — a
  host's real tokenizer will differ. They are labelled as estimates in
  every report.
- Delegate token counts come from provider usage. A missing count is
  reported as `null`, never as `0`: unknown is not zero.
- Cost is `unknown` until you fill in `prices.yaml` with sourced prices
  (each row records its provenance and `as_of` date).
- **No savings percentage is claimed anywhere.** Numeric token/cost/latency
  targets are an owner decision (spec §8). The harness reports what it
  measured.

## Reading the results honestly

Fewer primary tokens is not fewer total tokens. Planning, review and repair
are accounted as their own stages precisely so that work moved out of the
primary model does not disappear from the total.

The offline numbers are also shaped by the fixtures: the `git_prepare`
baseline runs against a two-file temporary repository, where terse git
stdout is genuinely smaller than the structured JSON results. On a real
repository — where `git status` output is long and a failed step has to be
diagnosed from raw text — that comparison changes. Draw conclusions from
`--live` runs on representative repositories, not from the offline smoke
run.
