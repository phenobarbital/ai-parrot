## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-891/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define the FEAT-887 integration contract before implementation (architecture) | CONFIRM | FEAT-887 has no pre-tool path; the dependency is reduced to one module with unverified anchors | §2 Overview, M8, M11 |
| S2 | Keep procedure hook evaluation on a dedicated stdlib fast path (risk) | CONFIRM | required by the hook budget | M5, §5 |
| S3 | Specify an atomic compiled-index publication protocol (architecture) | CONFIRM | readers must see one complete snapshot | §2 Plane and index, M4 |
| S4 | Separate procedure requirements into typed fields (api) | CONFIRM | makes cycle detection and validation unambiguous | §2 Data Models, M3 |
| S5 | Make the skill producer preserve graph metadata explicitly (api) | CONFIRM | the parser copies fields by hand | M2 |
| S6 | Reuse the existing source-slice and provenance mechanisms (architecture) | CONFIRM | no store subclass is needed | M4 |
| S7 | Constrain hook probes to bounded local evidence (risk) | CONFIRM | probe cost classes; remote probes are CLI-only | §2 Probes, M5, M6 |
| S8 | Define how the resolver knows the last completed procedure (architecture) | CONFIRM | position is derived from `done_when` probes, not recorded | §2 Overview, M6 |
| S9 | Treat mandatory confirmation as future metadata, not current authorization (api) | CONFIRM | `confirm` and `executor` are inert in v1 | §1 Non-Goals, §7 |
| S10 | Integrate the manifest into the existing packaged-asset lifecycle (testing) | CONFIRM | asset entry, package data, twin test, wheel-only smoke | M9, M12 |

Summary: **10** confirmed · **0** rejected · **0** escalated. Every `affected_paths` entry was
checked for containment and existence.

---

