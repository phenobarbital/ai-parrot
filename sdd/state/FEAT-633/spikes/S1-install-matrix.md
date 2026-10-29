# Spike S1 — clean-machine install matrix (FEAT-633)

## How to run
- GitHub → Actions → **install-matrix** → Run workflow (inputs: `spec`, default `ai-parrot ai-parrot-tools`;
  `python`, default `3.12`), or `gh workflow run install-matrix.yml -f spec="ai-parrot ai-parrot-tools" -f python=3.12`.
- Each leg uploads `smoke-<os>.json` (`SmokeReport`). Local: `uv run --no-project --python 3.12
  scripts/install/smoke_install.py --json-out smoke.json`.

## Results (fill from the run)
| OS | Run URL | install_ok | sdist_failures | tools deps wheel-only (PyGithub → cryptography/pynacl, ruamel-yaml) | parrot | wikitoolkit | bookstore | mcp_ok |
|---|---|---|---|---|---|---|---|---|
| ubuntu-latest (x64) | [run](https://github.com/phenobarbital/ai-parrot/actions/runs/40813681936) | true | [] | yes | ok | ok | ok | true |
| ubuntu-24.04-arm (aarch64) | [run](https://github.com/phenobarbital/ai-parrot/actions/runs/40813681936) | **false** | python-datamodel (first blocker) | not reached | — | — | — | false |
| macos-latest (arm64) | [run](https://github.com/phenobarbital/ai-parrot/actions/runs/40813681936) | **false** | python-datamodel (first blocker) | not reached | — | — | — | false |
| windows-latest (x64) | [run](https://github.com/phenobarbital/ai-parrot/actions/runs/40813681936) | **false** | navigator-auth (first blocker) | not reached | — | — | — | false |

The run is a `release.yml` dispatch at `ac5211118` (2026-10-29); `deploy` was skipped. The `sdist_failures` column
in the uploaded JSON reads `["from"]`: `parse_sdist_failures` matched "building **from** source" in uv's resolver
hint. That parser was fixed afterwards on this branch, and the names above come from uv's error text.

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
**FAIL (2026-10-29, [run 40813681936](https://github.com/phenobarbital/ai-parrot/actions/runs/40813681936)).** ubuntu x64 is green. The other three legs cannot install
without a compiler. ai-parrot's own wheels were built for every platform (`build-core` was green on all four), so
the failures are all in dependencies.

uv stops at its first blocker, so the full set comes from resolving the core + tools wheels for each platform
(`uv pip compile --python-platform …`, 227–228 pins) and checking PyPI for a cp312, abi3 or `py3-none-any` wheel per
pin. The pins without one are:

| Package (version resolved) | macOS arm64 | Linux aarch64 | Windows x64 | Pulled in by | Owner |
|---|---|---|---|---|---|
| python-datamodel 0.11.0 | no wheel | no wheel | ok | ai-parrot | phenobarbital |
| navconfig 3.0.0 | no wheel | no wheel | ok | ai-parrot | phenobarbital |
| navigator-api 4.0.1 | no wheel | no wheel | ok | ai-parrot | phenobarbital |
| navigator-auth 0.28.9 | no wheel | no wheel | **no wheel** | ai-parrot | phenobarbital |
| asyncdb 2.16.3 | ok | no wheel | ok | ai-parrot, navigator-api | phenobarbital |
| pytomlpp 1.1.0 | ok | no wheel | ok | navconfig | third party |
| uvloop 0.23.0 | ok | ok | **unsupported** | proxylists (unguarded `uvloop>=0.19.0`) | phenobarbital (proxylists) |

The ai-parrot-tools dependencies (PyGithub → cryptography/pynacl, ruamel-yaml) all have wheels on every leg
(rev 0.5 C20).

Proposed remedies are upstream, outside this repository:
1. Add cibuildwheel legs for macOS arm64 and Linux aarch64 to python-datamodel, navconfig, navigator-api,
   navigator-auth and asyncdb, plus Windows for navigator-auth.
2. Guard uvloop in proxylists with `uvloop>=0.19.0; sys_platform != 'win32'`. uvloop does not support Windows, so
   no wheel can fix that leg.
3. In navconfig, replace pytomlpp with `tomllib` (stdlib on Python ≥ 3.11), or keep pytomlpp only where a wheel
   exists.

Tracked as `issue:d725faabd9a8`. Until then the bootstrap supports Linux x86_64 only, or any platform with a C toolchain (`--allow-build`). Per the
decision rule this is a TASK-4094 blocker, but the fix lies in the upstream packages, not in this repository's core
wheel matrix.

`smoke-sdd-foreign` also failed in this run, but in the harness. Pytest loaded the checkout's `conftest.py`, which
imports navconfig without an `env/`. It now runs with `--noconftest` and passes 6/6 locally against this run's own
cp312 wheel.

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
