# Spike S1 — clean-machine install matrix (FEAT-633)

## How to run
- GitHub → Actions → **install-matrix** → Run workflow (inputs: `spec`, default `ai-parrot ai-parrot-tools`;
  `python`, default `3.12`), or `gh workflow run install-matrix.yml -f spec="ai-parrot ai-parrot-tools" -f python=3.12`.
- Each leg uploads `smoke-<os>.json` (`SmokeReport`). Local: `uv run --no-project --python 3.12
  scripts/install/smoke_install.py --json-out smoke.json`.

## Results (fill from the run)
| OS | Run URL | install_ok | sdist_failures | tools deps wheel-only (PyGithub → cryptography/pynacl, ruamel-yaml) | parrot | wikitoolkit | bookstore | mcp_ok |
|---|---|---|---|---|---|---|---|---|
| ubuntu-latest (x64) | | | | | | | | |
| macos-latest (arm64) | | | | | | | | |
| windows-latest (x64) | | | | | | | | |

## Decision rule (spec §3 M0)
- All three legs green ⇒ S1 passes; bootstrap (TASK-4074/4075) may proceed in any order vs TASK-4094.
- Any leg with `sdist_failures` or `install_ok=false` ⇒ S1 FAILS: TASK-4094 (core wheel matrix)
  ships BEFORE the bootstrap; list each failing package and its proposed remedy (marker-guarded
  extra, upstream wheel, in-repo wheel build) here.
- `mcp_ok=false` with install green ⇒ a `parrot_tools` import error in the MCP stderr is a
  missing-dependency failure (the install spec lacks ai-parrot-tools, rev 0.5 C20) — fix the spec;
  otherwise file a ledger issue (stdio/stdout pollution) — blocks M1/M2. `mcp_ok` also
  requires `tools/list` to hold `wiki_query`; a handshake without the wiki tools is not a pass.
- Per leg, record whether ai-parrot-tools' dependencies (PyGithub → cryptography/pynacl, ruamel-yaml)
  installed without a compiler (none of them in `sdist_failures`) — rev 0.5 C20.

## Verdict
<!-- pass | fail — with date and run URLs -->

## Local Linux evidence (TASK-4068, 2026-10-26, `--allow-build`, Python 3.12, PyPI ai-parrot + ai-parrot-tools)
- `install_ok=true`, `sdist_failures=[]`, `wikitoolkit` / `bookstore` `--help` OK, `mcp_ok=true`
  (`initialize` + `tools/list` holding `wiki_query`).
- **Finding F1**: `parrot --help` exits non-zero on a clean install: `Error: 'parrot e2e' is unavailable: could not import
  'parrot.e2e.cli' (ModuleNotFoundError: No module named 'pytest')`. `pytest` is not a runtime dependency of core; the
  `parrot e2e` command group is registered eagerly. Needs a follow-up (lazy/optional group) — outside this task.
- **Finding F2**: navconfig derives its project root from the venv's parent and aborts without `env/<env>/.env`; the
  harness scaffolds an empty `env/dev/.env` next to the throwaway venv. The `--global` bootstrap venv (M2) must do the
  same or set `SITE_ROOT`.

## Local Linux evidence with this branch's wheels (FEAT-633 R7, 2026-10-28)
This is the local equivalent of the `smoke-core` leg on ubuntu x64. Both wheels were built from the branch at
`9efbcb711` with `uv build --wheel --python 3.12`: `ai_parrot-1.2.5-cp312-cp312-linux_x86_64.whl` and
`ai_parrot_tools-1.2.5-py3-none-any.whl`. They were smoked with
`smoke_install.py --wheel … --wheel … --python 3.12` (`UV_PYTHON_PREFERENCE=only-managed`, `PYTHONPATH`,
`VIRTUAL_ENV`, `PARROT_PROJECT` and `CLAUDE_PROJECT_DIR` unset).
- `install_ok=true`, `sdist_failures=[]`, `errors=[]`.
- `scripts_ok`: `parrot` / `wikitoolkit` / `bookstore` all `true`. **F1 is resolved:** `parrot --help` now exits 0
  without `pytest` installed (R1, `LazyGroup.format_commands`).
- `mcp_ok=true`.

The macOS arm64, Windows x64 and ubuntu arm64 legs, plus `smoke-sdd-foreign`, still need a CI run. `install-matrix.yml`
is not on the default branch, so it cannot be dispatched by itself. The route is `release.yml`, which is on `main` with
`workflow_dispatch`, dispatched against this branch. Its `smoke-core` job calls this workflow with the freshly built
`{core-dist-*,dist-tools}` wheels, and its `deploy` job is gated on `github.event_name == 'release'`, so nothing is
published:
`gh workflow run release.yml --repo phenobarbital/ai-parrot --ref feat-FEAT-633-parrot-installer`.

**F2 resolution (FEAT-633 R9, 2026-10-28).** The owner's decision: navconfig and its `env/<env>/.env` are mandatory
for ai-parrot, because credentials live there. But the shipped SDD helpers need no credentials. They crashed only
because the `parrot.flows.dev_loop` and `dev_loop.sdd_coder` package `__init__` files eagerly imported the runner
and the roster, which pulled in navconfig. Both packages now resolve their public names lazily (PEP 562). The
wheel-only foreign-repo test (C3) no longer scaffolds `env/dev/.env` and passes 6/6.
