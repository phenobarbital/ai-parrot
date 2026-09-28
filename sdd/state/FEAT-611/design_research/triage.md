
| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | One canonical linked-surface envelope boundary (architecture) | CONFIRM | Matches F014 blockers 4 and 5; wrap at `finalize_a2ui_response`; test 3 output paths | §3 M5, §4 |
| S2 | Route linked surfaces through a generic canvas path (architecture) | CONFIRM | Verified `infographic-tab-builder.ts:60` rejects widget/Column roots | §3 M6 |
| S3 | Carry the persisted surface id; consume refresh responses (api) | CONFIRM | `serverRefresh` discards the response (A2UISurface.svelte:146-153); warnings header added | §3 M3, M5, M6 |
| S4 | Authorize execution before returning rows (risk) | CONFIRM + ESCALATE | Verified toolkit.py:386 `pctx=None, guard=None`. The example TOOL is hardened; the core toolkit change is escalated | §3 M8, §8 Q4 |
| S5 | Verify the exact PBAC resource/action (risk) | CONFIRM | The resource string is inferred (no `ResourceType.SOURCE`); M2 proves allow/deny and logs the evaluated strings | §3 M2, §7 |
| S6 | One conformance fixture for Python/TS conditions (testing) | CONFIRM | Already the M8 design; extended to ignored/locked params | §3 M8 |
| S7 | Identical multiquery frame selection across lanes (api) | CONFIRM | Verified divergence: Python raises (query_slug.py:238), TS falls back to `result`/`[]` (fetch.ts:22-40) | §3 M3, §4 |
| S8 | Validate FilterBar bindings at envelope validation (api) | CONFIRM | Already M4; locked names are an explicit issue code | §3 M4 |
| S9 | Separate the fake tier from the gated staging verdict (testing) | CONFIRM | Already M9 (offline + `-m staging`); the staging suite refuses non-staging targets | §3 M9 |
| S10 | Keep the Epson TOOL thin and example-scoped (alternative) | CONFIRM | Consistent with the M8 design | §3 M8 |

Summary: **10** confirmed (1 also escalated) · **0** rejected · **1** escalated.
