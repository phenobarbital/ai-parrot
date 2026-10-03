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
| `frontmatter-schema` | export | warning | no |
| `export-drift` | export | warning | yes |
| `export-dangling-relates-to` | export | warning | no |
| `adr-superseded-active` | adr | warning | no |
| `adr-supersedes-broken` | adr | error | no |
| `adr-conflict` | adr | warning | no |
| `memory-dangling-link` | memory | error | no |
| `stale-memory` | memory | warning | no |
| `contradiction-llm` | llm | info | no |

## Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--path` | str | required | Path to the wiki repository |
| `--backend` | str | auto | Backend to use (sqlite, arangodb, pg, federated) |
| `--ns` | str | all | Namespace to lint |
| `--rules` | str | all | Comma-separated rule ids or pack names |
| `--skip` | str | none | Comma-separated rule ids to skip |
| `--fix` | flag | false | Apply safe, idempotent fixes |
| `--llm` | flag | false | Run the opt-in LLM contradiction pass |
| `--llm-model` | str | auto | LLM spec; else `WIKI_LINT_LLM` / `WIKI_EXTRACT_LLM` |
| `--llm-max-pairs` | int | 50 | Maximum number of memory/ADR pairs to judge |
| `--report` | str | md | Report format (json, md) |
| `--output` | str | auto | Report directory (default: `<storage>/lint`) |
| `--ledger/--no-ledger` | flag | true | Write findings to the work ledger |
| `--notes/--no-notes` | flag | true | Append notes to affected pages |
| `--fail-on` | str | error | Fail on error, warning, or none |
| `--json` | flag | false | Emit the report as JSON |

## Where findings go

- **Ledger** (when `--ledger`): Only `warning`/`error` findings that are not fixable.
  - `kind="tech_debt"` for warnings, `"bug"` for errors.
  - `discovered_from="lint:<rule-id>"`.
  - Deduplicated on the `<!-- lint-fp:<fingerprint> -->` marker in the body.
  - Over `ledger_cap_per_rule` (default 20), the rest are aggregated into one issue.
- **Report files**: `report.json` and `report.md`, written to `--output` (default
  `<storage>/lint/`).
- **Page notes** (when `--notes`): Appended through the same path as the `note`
  command, attributed `by="lint"`. Deduplicated on the fingerprint.

## LLM contradiction pass

`--llm` resolves the model from `--llm-model`, `WIKI_LINT_LLM`, `WIKI_EXTRACT_LLM`,
then coding-agent auto-detection (`PARROT_NO_AUTO_LLM=1` disables). At most
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
If a fixture repo dir is needed, it is created under the test dir declared above.
