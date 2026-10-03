# wikitoolkit lint

`wikitoolkit lint` checks the wiki knowledge graph (any backend), its markdown export,
agent memories and ADRs. It reports by default; `--fix` applies only safe, idempotent
fixes and never deletes pages or edges.

## Rules

| Rule id | Pack | Severity | Fixable |
|---|---|---|---|
| `broken-link` | plane | error | no |
| `orphan-page` | plane | warning | no |
| `orphan-source` | plane | warning | no |
| `duplicate-slug` | plane | warning | no |
| `missing-body` | plane | warning | no |
| `stale-source` | plane | warning | no |
| `asymmetric-related` | plane | warning | yes |
| `fts-index-drift` | plane | warning | yes |
| `frontmatter-schema` | export | error | no |
| `export-drift` | export | warning | yes |
| `export-dangling-relates-to` | export | error | no |
| `adr-superseded-active` | adr | warning | no |
| `adr-supersedes-broken` | adr | error | no |
| `adr-conflict` | adr | warning | no |
| `memory-dangling-link` | memory | error | no |
| `stale-memory` | memory | warning | no |
| `contradiction-llm` | llm | warning | no |

### Engine / bookkeeping findings

These ids are emitted by the engine or by a rule's own guard, not by a selectable rule.

| Finding id | Severity | Meaning |
|---|---|---|
| `export-missing` | info | No export directory configured or found; export rules were skipped. |
| `llm-skipped` | info | The `--llm` pass could not run (no model, client error, timeout). Never fails the run. |
| `rule-crashed` | error | A rule raised; the other rules still ran. |
| `schema-mismatch` | error | `--fix` refused because the plane schema version differs from this code. |

### OKF knowledge-base checks

`OKFToolkit.lint_knowledge_base()` keeps its own report and is not part of the `wikitoolkit lint`
rule set. Its rules are exposed as engine findings with these ids: `okf-orphan` (warning),
`okf-broken-link` (error), `okf-missing-concept` (warning) and `okf-stale` (warning). None are fixable.

## Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--path` | str | auto-detect | Repo root |
| `--ns` | str | all | Namespace to lint |
| `--rules` | str | all | Comma-separated rule ids or pack names (plane, export, adr, memory, llm) |
| `--skip` | str (repeatable) | none | Rule id to skip; repeat the option for several |
| `--fix` | flag | false | Apply safe, idempotent fixes |
| `--llm` | flag | false | Run the opt-in LLM contradiction pass |
| `--llm-model` | str | auto | LLM spec; else `WIKI_LINT_LLM` / `WIKI_EXTRACT_LLM` |
| `--llm-max-pairs` | int | 50 | Maximum number of memory pairs (memories linking the same page) to judge |
| `--report` | str | md | Report format (json, md) |
| `--output` | str | auto | Report directory (default: `<storage>/lint`) |
| `--ledger/--no-ledger` | flag | true | Write findings to the work ledger |
| `--notes/--no-notes` | flag | false | Append notes to authored subject pages (writes to the store) |
| `--export-dir` | str | none | OKF export directory to lint; without it export rules are skipped |
| `--fail-on` | str | error | Fail on error, warning, or none |
| `--json` | flag | false | Emit the report as JSON |

## Defaults and writes

A default run (no `--fix`, no `--notes`) never modifies pages or edges. It may write
`report.json`/`report.md` to the report directory and a `LINT` line to the wiki `log.md`.
`--fix` is the only way to change the plane (edges, FTS index) or re-export a bundle.

## Where findings go

- **Ledger** (when `--ledger`): Only `warning`/`error` findings that are not fixable.
  - `kind="tech_debt"` for warnings, `"bug"` for errors.
  - `discovered_from="lint:<rule-id>"`.
  - Deduplicated on the `<!-- lint-fp:<fingerprint> -->` marker in the body.
  - Over `ledger_cap_per_rule` (default 20), the rest are aggregated into one issue.
- **Report files**: `report.json` and `report.md`, written to `--output` (default
  `<storage>/lint/`).
- **Page notes** (only with `--notes`; off by default so a default run never writes to the store): appended to `authored` pages only (generated and memory pages are rewritten by `build`/sync). Appended through the same path as the `note`
  command, attributed `by="lint"`. Deduplicated on the fingerprint.

## LLM contradiction pass

`--llm` resolves the model from `--llm-model`, `WIKI_LINT_LLM`, `WIKI_EXTRACT_LLM`,
then coding-agent auto-detection (`PARROT_NO_AUTO_LLM=1` disables). When no model can be resolved or the client cannot be built, an `llm-skipped` info finding says why. At most
`--llm-max-pairs` (default 50) pairs are judged. A per-call timeout or provider
failure records an `llm-skipped` info finding. It never fails the deterministic run.

## CI

The `test-wiki-extras` job in `.github/workflows/ci.yml` builds a plane over a
small committed fixture and runs:

```bash
uv run wikitoolkit build --path tests/knowledge/lint/fixtures/repo --no-git --quiet
uv run wikitoolkit lint --path tests/knowledge/lint/fixtures/repo --fail-on error --no-ledger --no-notes
```

The fixture is tiny and committed so CI is offline and deterministic (no `--llm`).
