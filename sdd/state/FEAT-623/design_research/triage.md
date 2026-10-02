| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Progress targets have no A2UI destination (architecture) | CONFIRM | Accepted explicitly: the target travels as `comparisonPeriod` text, and the title as a `Text` in the group | §2, M2 |
| S2 | Define 0–100 → ratio conversion (api) | CONFIRM | Already `value/100`; zero, full and target-zero cases added | M2, §4 |
| S3 | Dual axes in the template HTML lane too (architecture) | CONFIRM | Already M4: second `yAxis` + `yAxisIndex` | M4 |
| S4 | Admin chart scope includes AppChart (architecture) | CONFIRM | Matches the spec-time finding; M5 lists AppChart/chart-contract, with a stop rule | M5, §7 |
| S5 | Table `align`/`width`/`color` contract unaddressed (api) | ESCALATE | Needs a wire decision; recommended: drop and document | §8 Q3 |
| S6 | Parity needs a locale policy (risk) | ESCALATE | AC now scoped to en-US with vitest pinned; pinning TS to en-US is Jesús's call | §5, §8 Q2 |
| S7 | Hero value `0` discarded by `or ""` (risk) | CONFIRM | Verified at `adapters/infographic.py:326`; explicit None check + test | M2, §4, §5, §7 |
| S8 | Specify progress sectioning; >1 section → tabs (architecture) | CONFIRM (decision revised) | Verified in both renderers (`A2UIInfographic.svelte:75`, navigator `Infographic.svelte:115`). Juan chose a group inside the current section over a new section | M2, §5, §7, §8 |
| S9 | Bounded, tested dtype inference (api) | CONFIRM | Explicit `pandas.api.types` map incl. nullable/tz/category | M6, §4 |
| S10 | End-to-end lane parity test (testing) | CONFIRM | `test_infographic_lanes_agree` added | §4 |

Summary: **8** confirmed · **0** rejected · **2** escalated.
