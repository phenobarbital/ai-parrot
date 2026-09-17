# FEAT-563 spike S2 — rootdir / conftest loading per distribution

Date: 2026-09-17
Worktree: /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-FEAT-563-scoped-test-selection   git-dir: /home/jesuslara/proyectos/ai-parrot/.git/worktrees/feat-FEAT-563-scoped-test-selection   common-dir: /home/jesuslara/proyectos/ai-parrot/.git

Probe plugin (not committed), written to a throwaway `mktemp -d` directory and passed via
`PYTHONPATH` (a literal `/tmp/s2probe.py` does not survive across tool invocations in this
sandbox — each probe run below writes+runs+deletes the plugin file in one shot):

    import sys, os
    def pytest_collection_finish(session):
        cfg = session.config
        print("S2 rootdir=", cfg.rootpath, "inifile=", cfg.inipath)
        print("S2 conftests=", sorted(str(getattr(m, "__file__", "")) for m in cfg.pluginmanager.get_plugins() if str(getattr(m, "__file__", "")).endswith("conftest.py")))
        import parrot
        print("S2 parrot.__file__=", parrot.__file__)
        import parrot.server as pserver
        print("S2 parrot.server.__file__=", pserver.__file__)

Command template (run via a Python `subprocess.run(..., cwd=worktree, env={PATH, HOME,
PYTHONPATH=<probe_dir>})` with a **fully explicit, minimal env** — this matters, see the
methodology note below): `pytest -p s2probe --co -q <target>`

**Methodology note (important):** the interactive shell this spike ran in has a
Claude-Code-injected `PYTHONPATH` that already lists every `packages/*/src` under **this
worktree**, which trivially "fixes" worktree precedence for any bare `pytest` run from this
shell and would have hidden the real bug. All probe rows below were captured with that
`PYTHONPATH` stripped (`env={"PATH":…, "HOME":…, "PYTHONPATH": "<throwaway probe dir only>"}`)
so they reflect what a **plain `subprocess.run(["pytest", …], cwd=worktree, env=<minimal>)`** —
i.e. what `SddCoderEngine`/`LLMCodeDispatcher`/the native hook actually do — will see.

| Target | rootdir | inifile | root conftest loaded | parrot imported from | extra flag |
|---|---|---|---|---|---|
| tests/sdd_scripts/test_check_task_graph.py | worktree root | worktree `pytest.ini` | yes | worktree (`packages/ai-parrot/src/parrot/__init__.py`) | none |
| packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py | `packages/ai-parrot` | `packages/ai-parrot/pyproject.toml` | **no** | `parrot` itself: worktree (via `packages/ai-parrot/conftest.py`'s own `sys.path.insert`) — but **`parrot.server` (cross-package): main checkout** (`/home/jesuslara/proyectos/ai-parrot/packages/ai-parrot-server/src/parrot/server/__init__.py`) | **REQUIRED** — see below |
| packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py | worktree root (no `[tool.pytest.ini_options]` in this dist's pyproject.toml, so pytest climbs to the repo-root `pytest.ini`) | worktree `pytest.ini` | yes | worktree | none |
| packages/ai-parrot-server/tests/handlers/test_a2ui_handler.py (extra target, not in the required three, probed to cross-check the fix's generality) | `packages/ai-parrot-server` | `packages/ai-parrot-server/pyproject.toml` | no | worktree (this dist's own `tests/conftest.py` independently inserts its own src + ai-parrot core src + ai-parrot-integrations src) | none needed here, but harmless to apply uniformly |
| **retry** — packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py **with `--confcutdir=<worktree>`** | `packages/ai-parrot` (**unchanged**) | `packages/ai-parrot/pyproject.toml` (**unchanged**) | **yes** (repo-root `conftest.py` now also loads, alongside the dist's own two) | `parrot`: worktree; **`parrot.server`: worktree** (fixed) | `--confcutdir=<worktree>` |
| **retry** — root and ai-parrot-tools targets **with `--confcutdir=<worktree>`** (regression check) | unchanged (already worktree root) | unchanged | yes (unchanged) | worktree (unchanged) | confirms the flag is a safe no-op when rootdir is already the worktree root |

Markers still applied with the chosen flag (`pytest --confcutdir=<worktree> --markers
packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py`, grepped for
`real_llm|network|live`):

    @pytest.mark.real_llm: mark a test as requiring a live LLM provider
    @pytest.mark.network: mark a test as requiring live network access (e.g. spec drift checks)
    @pytest.mark.live: needs provider credentials; opt-in with -m live

All three of `packages/ai-parrot/pyproject.toml`'s own registered markers are intact — the
dist's `[tool.pytest.ini_options]` (asyncio_mode, markers) stays in effect because
`--confcutdir` only changes how far **up** pytest searches for additional `conftest.py` files;
it does **not** change `rootdir`/`inifile` selection (those still climb from the target to the
nearest ancestor `pyproject.toml`/`pytest.ini` with `[tool.pytest.ini_options]`, unaffected).

## Root cause (for the orchestrator, not just the symptom)

The repo-root `conftest.py` (lines 79–128) explicitly documents and implements the
worktree-precedence fix: it prepends `_EXTRA_PATHS` (worktree src for ai-parrot core, -loaders,
-visualizations, -tools, -server, -integrations) onto `sys.path`, **and** additionally prepends
the worktree's `packages/ai-parrot/src/parrot`, `.../ai-parrot-server/src/parrot`,
`.../ai-parrot-integrations/src/parrot` directly onto the *already-imported* `parrot` namespace
package's `__path__` list (`parrot` uses `pkgutil.extend_path`, so a plain `sys.path` insertion
alone is not enough for cross-distribution submodules like `parrot.server` — the namespace's
own `__path__` must be patched too). This conftest.py is only auto-discovered by pytest when
its rootdir search reaches the worktree root — which does **not** happen for `packages/<dist>/
tests/...` invocations whose own `pyproject.toml` declares `[tool.pytest.ini_options]` (ai-parrot,
ai-parrot-server, ai-parrot-integrations, parrot-formdesigner). Two of those three dists happen
to carry their **own**, independently-written copy of an equivalent (but narrower) fix in a
local conftest.py (`packages/ai-parrot/conftest.py` inserts only its own src;
`packages/ai-parrot-server/tests/conftest.py` and `packages/ai-parrot-integrations/conftest.py`
insert their own src + ai-parrot core + ai-parrot-integrations src) — but none of these local
copies is as complete as the root one, so a per-distribution-scoped invocation can still miss
a cross-package import the root conftest.py would have covered (confirmed for
`packages/ai-parrot/tests/...` → `parrot.server`). `parrot-formdesigner` has **no** local
workaround at all and imports from `parrot.*` core in 5 modules
(`renderers/adaptive_card.py`, `services/sandbox/{gvisor_pool,pool,router}.py`,
`tools/snippet_authoring.py`) — not probed directly (out of this task's three required targets)
but structurally at the same risk as the confirmed `ai-parrot` bug.

## Decision (copied verbatim by TASK-3305 into planner.py)

    PER_DIST_EXTRA_ARGS = ("--confcutdir", "{worktree}")

Rationale: `--confcutdir` forces pytest to keep walking up to `{worktree}` for additional
`conftest.py` files without changing `rootdir`/`inifile` selection, so the per-distribution
invocation still gets that distribution's own `[tool.pytest.ini_options]` (asyncio_mode,
markers) while ALSO loading the repo-root `conftest.py`'s comprehensive worktree-source
`sys.path` + `parrot.__path__` prepending. Verified as a no-op (same rootdir, same conftests,
same resolution) for the two targets whose rootdir already lands on the worktree root, and as
the fix for the one target where a cross-package import (`parrot.server` from
`packages/ai-parrot/tests`) was confirmed silently resolving to the main checkout without it.
This is strictly safer than `--rootdir=<worktree>` (which would also relocate `rootdir` itself
and, per pytest's own precedence rules, could shift which `pyproject.toml`/`pytest.ini` is
selected as `inifile`, risking loss of the distribution's own markers/asyncio_mode) and safer
than `-c <worktree>/pytest.ini` (which would force the **repo-root** ini file, definitely
losing the distribution's own `[tool.pytest.ini_options]` — the exact regression the markers
check above rules out for the chosen flag).

verdict: FLAG_REQUIRED
