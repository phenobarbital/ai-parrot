## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.166.0, reasoning high) ·
> Status: completed (2026-11-04 21:29–21:33 UTC, exit 0, 12 suggestions, schema-valid) ·
> Transcript: `sdd/state/FEAT-801/design_research/`
> Every `affected_paths` entry was containment-checked and `test -e`'d: all 26 distinct paths exist.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Model techwiki in the typed SDD configuration (architecture) | CONFIRM | `SddConfig` is `extra="forbid"`; the field and the key land in the same task | §3 M1, §7 gotcha |
| S2 | Do not route docs metadata through FlowMeta (api) | CONFIRM | dedicated `resolve_docs_policy` mirrors `resolve_policy`; never imports a private name | §3 M5, §6 Does NOT Exist |
| S3 | Publish from the release boundary, not every main push (risk) | CONFIRM | `release.yml` fires on `release: created`; a hotfix merge ahead of its tag would publish unreleased code | §2 Overview, §3 M6, Decisions, §8 (confirm) |
| S4 | Source triggers must cover the whole workspace (architecture) | CONFIRM | subsumed by S3 (release event has no path filter); PR job paths cover `packages/*/src/**` | §3 M6 |
| S5 | Specify non-blocking closeout handling explicitly (risk) | CONFIRM | exit 2 and unexpected failures are recorded as `Docs:` lines; "never aborts" is asserted by test | §3 M5, AC-7 |
| S6 | Documentation contract stronger than path existence (testing) | CONFIRM | content rules (empty, no title, `api_modules` syntax) → warning codes; template AC line updated | §2 Data Models, §3 M4/M5, AC-7 |
| S7 | Make the techwiki extra self-contained (risk) | CONFIRM | `requires-python` is `>=3.11,<3.14`, the 3.10 claim was stale; jinja2 lives only in the `agents` extra | §2 interfaces, §3 M1, §7, AC-3b |
| S8 | Freeze the generated API surface with golden fixtures (testing) | CONFIRM | rendering rules fixed; golden test; `--strict` exit 4 on skipped modules | §3 M2, §4, AC-7b |
| S9 | Stable page identifiers instead of title-derived links (architecture) | CONFIRM (partial) | links already resolve by source path / `ref:` module id; a manifest makes that explicit. REJECT a separate ID layer: GitHub needs the title-derived file name anyway, and the U+2010 rule is enforced, not assumed | §2 Data Models, §3 M3, §4 |
| S10 | Plan migration compatibility and link verification (risk) | CONFIRM + ESCALATE | 11 inbound `api-reference/` links verified by grep (index + 6 chapters) → rewritten in M9 under `mkdocs build --strict`; redirect stubs vs accepted breakage escalated | §3 M9, AC-13, §8 Q-redirects |
| S11 | Run bundle validation before merge (testing) | CONFIRM | `pull_request` dry-run job + optional advisory `pre_pr` hook; SDD presence check stays warning-only | §2 Overview, §3 M6, AC-12 |
| S12 | Foreign-repository and asset-sync coverage (testing) | CONFIRM | `check` must run without griffe and only on repo-relative paths; asset sync already gated | AC-3, AC-8, §4 `test_check_repo_relative_only` |

Summary: **12** confirmed (2 partial) · **0** rejected outright · **1** escalated (S10 redirects).

---

