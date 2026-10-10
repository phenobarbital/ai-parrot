# Design research triage — FEAT-650 a2ui-dialect-formbuilder

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed (codex-cli 0.160.0, reasoning high, 11 suggestions, every `affected_path` verified inside the repo)
> · Transcript: `sdd/state/FEAT-650/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Keep the persisted dialect out of legacy response serialization (api) | CONFIRM (partial) | The one additive key on `GET /forms/{uid}` follows the `is_public`/`unknown_fields` precedent, so the proposed "omit when default" projection is REJECTED as a special case; the golden byte-level test for old persisted forms is adopted and pins that the diff is exactly that key. `/schema` is unaffected (JsonSchemaRenderer builds its own structure). | §5 AC2 |
| S2 | Centralize dialect negotiation after authorization and before rendering (architecture) | CONFIRM | Matches M2: `resolve_dialect` runs after membership + `onSchemaLoaded`, no new early-return path; override handling is defined (translate). | §3 M2, §7 Known Risks |
| S3 | Define a real strict-round-trip fidelity boundary (architecture) | CONFIRM | The renderer does not emit descriptions/dependencies/options_source; sections are recoverable via `sec-<id>`/`sub-<id>` ids. The spec now names the exact strict projection and forbids claims beyond it; the renderer stays frozen (follow-up for a `parrot_*` side-channel). | §5 AC9, §7 Strict projection |
| S4 | Test JSON-Schema round trips against every emitted extension (testing) | CONFIRM | `items.enum`+`x-options` for array-typed props, `default`, `description`, disabled options and both dependency levels were missing from M4; added to the extractor contract and to AC8 with a fixture round-trip. | §3 M4, §5 AC8 |
| S5 | Separate createSurface import detection from action detection (api) | CONFIRM | Already a distinct predicate and branch before the 503 guard; adds `validate_message` + `validate_envelope(origin=TOOL)` → 422 on invalid surfaces and a test that import works with no LLM client. | §3 M6, §4 |
| S6 | Make extraction graph-safe and resource-bounded (risk) | CONFIRM | `validate_envelope` runs before any walk (duplicate ids, dangling children, missing root), cycles are dropped+warned, `A2UI_MAX_IMPORT_COMPONENTS`/`A2UI_MAX_IMPORT_DEPTH` added. | §3 M5, §5 AC10 |
| S7 | Do not build bulk export on the cache-only registry view (architecture) | CONFIRM | `export_tenant` now always hydrates from storage first; `export_all_tenants`/`--all-tenants` removed (list_tenants is a cache view, storage is per-tenant-schema); `published_only` defined on `published_version`. | §3 M3/M7, §8 |
| S8 | Avoid embedding full surfaces in list descriptors (alternative) | CONFIRM | `?dialect=a2ui` on the list is now a manifest (`surface_url`); inline envelopes only with `include=surface`, capped by `A2UI_LIST_MAX`. | §2 wire shapes, §3 M2 |
| S9 | Preserve explicit failure semantics when the extra is absent (risk) | CONFIRM | Already designed: 400 (unknown dialect) vs 415 (`a2ui` unavailable), never a silent legacy fallback; CLI exit 2. Recorded explicitly. | §7 Patterns, §5 AC3 |
| S10 | Add lifecycle, authorization and error-path tests for negotiated GETs (testing) | CONFIRM | Added tests for private-form membership, `onSchemaLoaded` abort and public access under both dialects; abort bodies stay JSON. | §4, §5 AC15 |
| S11 | Treat the CLI as an optional integration with explicit dependency ownership (alternative) | CONFIRM | `click` moves to parrot-formdesigner core deps, `cli.py` gets `main()`, the lazy entry must fail with an install hint; resolves the open `click` question. | §3 M7, §7 External Dependencies, §8 |

Summary: **11** confirmed (S1 partial: projection rejected, test adopted) · **0** rejected · **0** escalated.
