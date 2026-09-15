# Contracts catalog performance (FEAT-539, AC14)

Measured warm p95 latency of the operator-facing SQL operations on a
100-card synthetic catalog. LLM and network-generation time is excluded by
construction — none of these code paths touch a model.

## How to reproduce

```bash
# 1. A disposable Postgres with pgvector (the GraphIndex extra needs it):
docker run -d --name contracts-pg \
  -e POSTGRES_PASSWORD=parrot -e POSTGRES_USER=parrot -e POSTGRES_DB=contracts \
  -p 55439:5432 pgvector/pgvector:pg16

# 2. Run the benchmark against it (temporary schema, dropped afterwards):
export GRAPHINDEX_PG_DSN="postgresql://parrot:parrot@127.0.0.1:55439/contracts"
python -m pytest \
  packages/ai-parrot/tests/knowledge/contracts/test_catalog_performance.py -q
```

Each run appends a JSON record to `artifacts/logs/task-3055.log`.

## Dataset and query mix

| Property | Value |
|---|---|
| Cards | 100 (`perf-000` … `perf-099`), deterministic |
| Obligations | 300 (3 per card) |
| Statuses | active / expired / draft (3:1:1) |
| Types | msa, sow, nda, dpa, amendment |
| Standards | soc2, iso27001, gdpr, hipaa, pci_dss, none |
| Expiration dates | span both sides of the frozen "today" (2026-09-09) |
| Verification queue drivers | missing evidence, low confidence (<0.6), stale fields |
| Load time | 0.939 s for the full fixture |

Every measured query returns a non-empty result set — a p95 over an empty
result would prove nothing, so the benchmark asserts `rows > 0`.

## Method

* 5 warmup iterations per operation (discarded), then 30 timed samples.
* p95 = the 95th-percentile sample of the sorted warm timings.
* One asyncpg pool, one temporary schema, no concurrent load.
* Budget: **p95 < 1 s** per operation (spec AC14).

## Measured results

Hardware / configuration of the recorded run:

| Property | Value |
|---|---|
| Platform | Linux 7.0.0-30-generic, x86_64, glibc 2.39 |
| CPUs | 12 |
| Python | 3.12.3 |
| PostgreSQL | 16 (`pgvector/pgvector:pg16` container, localhost) |
| Date | 2026-09-09 |

| Operation | p50 | **p95** | max | rows |
|---|---:|---:|---:|---:|
| `search` (English FTS, top_k=8) | 1.41 ms | **1.54 ms** | 1.74 ms | 8 |
| `verification_queue` (limit 50) | 7.29 ms | **7.86 ms** | 64.30 ms | 50 |
| `expiring_within` (90-day window) | 2.18 ms | **2.37 ms** | 2.40 ms | 16 |
| `notice_deadlines_within` (90-day window) | 2.03 ms | **2.13 ms** | 2.21 ms | 16 |
| `list_cards` (status filter) | 6.37 ms | **6.76 ms** | 6.88 ms | 60 |
| `obligations_due` (90-day window, limit 200) | 3.29 ms | **3.50 ms** | 58.03 ms | 200 |

**Verdict: PASS.** The slowest warm p95 is 7.86 ms — roughly two orders of
magnitude inside the 1 s budget.

## Notes

* The `max` outliers on `verification_queue` and `obligations_due` are
  first-sample effects (plan caching and pool warmup) and disappear from
  p50/p95; they are reported rather than trimmed.
* `verification_queue` is the most expensive operation because it walks
  `card_json->'field_provenance'` with a lateral `jsonb_each` per card. At
  100 cards that costs ~8 ms; if the pilot corpus grows by an order of
  magnitude, materialising the queue reason as typed columns is the obvious
  next step — it was deliberately **not** done for the pilot, since the
  measured headroom does not justify the extra write-path complexity.
* These numbers describe the pilot's own hardware. Re-run the command above
  on the deployment host before quoting them there.
