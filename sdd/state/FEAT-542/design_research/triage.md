## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-542/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
>
> Deviation from the `/sdd-spec` §3b precondition, recorded for audit: neither exploration
> document is literally marked `accepted` (brainstorm `Status: exploration`, proposal
> `status: discussion`). The pass was run anyway, at the user's explicit request, because the
> design intent *was* accepted downstream — this spec is `Status: approved` and already
> decomposed into 14 tasks. The brief carried the brainstorm's Problem Statement, Constraints,
> Recommendation and Option A body, the paths (only) from its Code Context, and the user's five
> §8 answers as constraints. No text from this spec was shown to the reviewer.
>
> All 12 suggestions passed path containment and `test -e` verification — the reviewer cited
> only files that exist.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define an explicit LanceDB capability contract (architecture) | REJECT | Already specified: §2 New Public Interfaces gives `fulltext_search`/`hybrid_search` full signatures and `LanceDBOrigin(mode=...)` selects the retrieval mode. No kwargs-driven or generic-hybrid path was ever proposed. | — |
| S2 | Preserve hybrid component scores and conventions (api) | ESCALATE | Direction and kind are already carried (`LanceDBHybridHit.score_kind`/`higher_is_better`, `_lancedb` metadata, and §7's "no cross-origin comparison of raw scores"). Per-leg component scores are genuinely absent, would widen a contract M1 freezes, and depend on unverified SDK column exposure. | §8 Q6 |
| S3 | One filter and parent-visibility policy for every Lance mode (api) | REJECT | Already specified: §2 Filters mandates one shared compiler producing a single conjunctive prefilter applied to vector, FTS and **both** hybrid legs before candidate limits, and §7 explicitly warns against copying PostgreSQL's stricter marker handling — the divergence the reviewer found in `arango.py`. U2/I3 cover the named cases. | — |
| S4 | Prove the SDK async boundary before selecting the implementation (risk) | REJECT | Already specified: §2 Lifecycle requires native async operations with unavoidable blocking work moved off the loop, §2 items 2/8 define connection ownership and shutdown, and I1/TASK-3057 is a hard gate before dependent implementation. U3's event-loop heartbeat is the falsifying test. | — |
| S5 | Design and test true cross-process write behavior (risk) | CONFIRM | The spec directly contradicted the settled requirement — §2 read "Independent writer processes … are unsupported" while §8 requires concurrent independent writers. Correctness now rests on the SDK's commit semantics (established by the I1 gate) with bounded retry, a distinguishable conflict error, or a scoped file lock; the asyncio lock is demoted to a local optimization. | §1 Non-Goals, §1 Baseline, §2 Lifecycle, §4 I9, §5 AC8, §7 |
| S6 | Make collection, FTS-index and freshness lifecycle explicit (architecture) | CONFIRM | Mostly covered already (§2 item 3 for FTS creation and its failure mode, `read_consistency_interval_seconds` for freshness, §7 for post-index write freshness). The one uncovered case — reads while *another process* rebuilds the index — was real and is now required to yield pre- or post-write state, never a partial one. | §2 Lifecycle, §4 I9 |
| S7 | Define stable IDs independently of generated row keys (api) | REJECT | Already specified in full: §2 Data Models fixes ID precedence (explicit `ids` → `metadata["id"]` → SHA-256 of original text plus canonical metadata), upsert-on-same-ID, conflict/duplicate errors, and namespaced `lancedb:<collection_uuid>:<id>` output preventing cross-collection collisions. The concurrent-writer half of the concern is handled by S5. | — |
| S8 | Complete optional-backend registration without eager imports (architecture) | CONFIRM | Lazy imports and the extra were already specified, but the reviewer surfaced a concrete breakage the spec had softened into "existing map entries unchanged": `test_store_backends_present.py::test_supported_stores_unchanged` asserts **exact dict equality** on `supported_stores`, and `STORE_BACKENDS` drives a parametrized test. Both must be edited; neither passes unmodified. | §3 M5, §4 U7 |
| S9 | Enforce whole-origin failure for hybrid errors (risk) | REJECT | Already specified: §2 requires "no silent fallback on a failed leg", propagation of errors and cancellation to the toolkit, and hybrid failure failing that origin while the toolkit retains successful graph/other sections. I6 tests exactly that. | — |
| S10 | Keep LanceDB federation outside GraphExpandedRetriever (architecture) | REJECT | Already a stated Non-Goal ("Replacing GraphIndex's internal semantic seed index") with `GraphIndexOrigin` reused unmodified and I6 exercising the two as sibling origins. A negative test asserting non-substitution would guard a code path this feature never writes. | — |
| S11 | Separate embedded storage from the fully-offline guarantee (risk) | CONFIRM | The sharpest finding. The spec's Non-Goals excluded "certifying an entirely offline agent" while §8 requires exactly that, and I8/AC6 proved only that *storage* needs no network. A local directory does not make an agent offline — the embedding provider must be local and provisioned. I8 now denies sockets across the whole ingest/vector/FTS/hybrid path. | §1 Non-Goals, §2 Baseline, §4 I8, §5 AC6, §7 |
| S12 | Build an acceptance matrix before performance claims (testing) | CONFIRM | §4/§5 already covered restart, stable IDs, parent exclusion, filters, score provenance, index freshness and hybrid-leg failure, and §4 already forbids an SLO claim on the 1,000-row baseline. Two items on the reviewer's list were genuinely missing — multiprocess writes and whole-agent offline execution — and are added as I9 and the widened I8. | §4 I8/I9, §5 AC6/AC8 |

Summary: **4** confirmed · **7** rejected · **1** escalated.

---
