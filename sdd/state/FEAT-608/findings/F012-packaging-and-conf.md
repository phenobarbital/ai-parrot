---
id: F012
query_id: Q015
type: grep
intent: Google extras / pins in pyproject and Google conf keys (Q015 + Q016)
executed_at: 2026-09-25T22:54:10Z
duration_ms: 700
parent_id: null
depth: 0
---

# F012 — `aiogoogle` is pinned `==5.17.0` inside the big `agents` extras, `5.19.0` is installed, and there is no dedicated core extra for Google Workspace

## Summary

`packages/ai-parrot/pyproject.toml` lists `aiogoogle==5.17.0` and
`google-api-python-client>=2.151.0` three times (inside `agents`,
`agents-lite`-style bundles at :409/:425, :465/:476, :500/:511) and a
`google = [...]` extra at :599 that pins `google-api-python-client>=2.166.0,<=2.177.0`
(GenAI-oriented). `ai-parrot-tools` has `google = ["aiogoogle>=5.17", "google-api-python-client>=2.151"]`.
The venv has `aiogoogle 5.19.0` and `navigator-api 4.0.0`. The FEAT-603
worktree added an `msgraph` extra at :396 and folded it into `all` — the
packaging precedent. Conf exposes `GOOGLE_CREDENTIALS_FILE` (default
`env/google/key.json`) and `GOOGLE_API_KEY`; no Drive-specific keys exist.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 409, 425
  symbol: `[project.optional-dependencies]` (agents bundle)
  excerpt: |
    "google-api-python-client>=2.151.0",
    "aiogoogle==5.17.0",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 604
  symbol: `google` extra
  excerpt: |
    "google-api-python-client>=2.166.0,<=2.177.0",

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 81
  symbol: `google` extra
  excerpt: |
    google = ["aiogoogle>=5.17", "google-api-python-client>=2.151"]

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/pyproject.toml`
  lines: 396, 599, 882
  symbol: `msgraph / google / all` extras
  excerpt: |
    msgraph = [        # :396 — FEAT-603 precedent
    google = [         # :599
    all = [            # :882

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 430-435
  symbol: `GOOGLE_API_KEY / GOOGLE_CREDENTIALS_FILE`
  excerpt: |
    GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")
    GOOGLE_CREDENTIALS_FILE = Path(config.get("GOOGLE_CREDENTIALS_FILE", fallback=BASE_DIR.joinpath("env", "google", "key.json")))

## Notes

`aiogoogle==5.17.0` (exact pin) vs installed `5.19.0` means the pin is
already violated in the dev venv; a new extra should use `>=5.17,<6`.
