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
| `decided_task_large` | Same, ~150 lines instead of ~10 | Same — the two task rows differ *only* in implementation size |

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

## Tool-schema overhead

The optimized arm is charged `tool_schema_overhead`: the tokens the MCP tool
definitions themselves occupy in the primary model's context. It is measured
from the **real** definitions a host receives (`MCPToolAdapter.to_mcp_tool_definition()`,
the same JSON `tools/list` emits) — not estimated from source.

Three things to understand about that figure:

- It is charged to the **primary** model, because that is whose context holds it.
- It is charged **once per run**, which is a *floor*. Schemas are re-sent every
  turn, so a multi-turn task pays it repeatedly. Treat the number as a lower bound.
- The **baseline arm is charged zero**. The host's own built-in tools exist in
  both arms and cancel; what is measured is the *marginal* cost of adding
  these servers.

It is not small. `LocalGitToolkit`'s six tools alone serialize to roughly
1,880 tokens — larger than the entire payload of the `git_prepare` scenario.
Omitting it (as an earlier version of this harness did) silently flatters
every optimized column.

## What the two task sizes show

`decided_task` (~10 lines) and `decided_task_large` (~150 lines) are built by
the same generator and differ only in size, so the pair isolates the effect of
scale. The offline result:

| Scenario | baseline | optimized | delta | relative |
|---|---:|---:|---:|---:|
| `decided_task` | 518 | 1,765 | **+1,247** | +241% |
| `decided_task_large` | 2,205 | 3,452 | **+1,247** | +57% |

The absolute penalty is **identical** — it is the fixed schema overhead
(1,217) plus the delegate's own tokens. Only its *relative* weight falls as
the work grows.

That is not an accident of the fixtures, it is structural:

- the primary reads the TASK in **both** paths;
- the tokens it would have **written** become tokens it **reads** during hunk
  review, 1:1;
- the delegate's tokens are then added on top.

**So delegation can never win on raw token count.** It is a *cost* argument:
output tokens are several times dearer than input at every major provider, and
the delegate is cheaper per token than the primary. Whether that arithmetic
works out for you depends on your two models' prices and your task sizes —
fill in `prices.yaml` and run `--live`.

Note the offline delegate's token usage is a fixed stub (it does not scale
with the generated code), so the delegate columns are placeholders until you
run `--live`.

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

Once schema overhead is counted, the offline fixtures show only
`targeted_read` as a clear win (~5,940 -> ~1,690 primary tokens). Both
`git_prepare` and a single small `decided_task` come out *net negative*: the
servers cost more to have loaded than one small operation saves. That is a
real result, not a bug — those two tools are bought for determinism, refusal
on conflicting staging, and reviewable patches, and they amortize only across
many operations in one session. Measure your own task mix before claiming
otherwise.
