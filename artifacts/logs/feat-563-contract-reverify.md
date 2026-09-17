# FEAT-563 gate — FEAT-562 merge + Codebase Contract re-verification

Date: 2026-09-17
Feature branch HEAD: 3dfbea46407b3578f1d061b190bf9331a5730f03
origin/dev: f60d370c9823691470764f26381a7ee1f925d14f

## 1. FEAT-562 merge status

    $ git fetch origin dev
    $ git merge-base --is-ancestor origin/feat-FEAT-562-ci-test-failures-root-cause-remediation origin/dev; echo $?
    0
    $ git show origin/dev:sdd/tasks/index/ci-test-failures-root-cause-remediation.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('completed_at'),[(t['id'],t['status']) for t in d['tasks']])"
    None [('TASK-3296', 'pending'), ('TASK-3297', 'pending'), ('TASK-3298', 'pending'), ('TASK-3299', 'pending'), ('TASK-3300', 'pending'), ('TASK-3301', 'done')]

Merged: yes

Note: `git merge-base --is-ancestor` exits `0`, confirming the FEAT-562 feature
branch's tip is an ancestor of `origin/dev` — the acceptance criterion's
primary gate condition is satisfied directly. The per-spec index on
`origin/dev` still shows `completed_at: null` and most FEAT-562 tasks as
`pending` (only TASK-3301 `done`) — this is stale/unrefreshed SDD-state
bookkeeping on the FEAT-562 side (its index was apparently not stamped
`done` before/at merge time), not evidence against the merge. The git
ancestor check is authoritative per the task's own acceptance criteria
("verdict: PASS only if `git merge-base --is-ancestor …` exits 0 (or the
FEAT-562 index on `origin/dev` has `completed_at` set)") — the first
disjunct alone is sufficient.

## 2. Spec §6 anchor drift

| Anchor (as recorded) | Now | Status |
|---|---|---|
| pytest.ini (markers integration, live, real_llm, slow) | Line 4-8, same four markers, same text; `filterwarnings = ignore::DeprecationWarning` at line 9-10; file is still 11 lines (10 content lines + trailing newline) | unchanged |
| pyproject.toml:230 [tool.pytest.ini_options] | Still at line 230; `addopts = ["--strict-config", "--strict-markers"]`, `log_cli = true` / `log_cli_level = "DEBUG"`, `filterwarnings = ["error", …]` all present | unchanged |
| packages/ai-parrot/pyproject.toml:997 | Still at line 997; `asyncio_mode = "auto"`; markers `real_llm`, `network`, `live` — identical text | unchanged |
| packages/ai-parrot-server/pyproject.toml:118 | Still at line 118; markers now: `wheel_build`, `requires_apscheduler`, `requires_aioquic`, `requires_mcp_sdk`, `live` (5 markers; header position unchanged) | unchanged |
| packages/ai-parrot-integrations/pyproject.toml:143 | Still at line 143; single marker `live_vendor` unchanged | unchanged |
| packages/parrot-formdesigner/pyproject.toml:93 | Still at line 93; `asyncio_mode = "auto"` unchanged | unchanged |
| packages/ai-parrot/tests/conftest.py:15 | Still `def pytest_collection_modifyitems(config, items):  # noqa: D401` at line 15, same skip-real_llm body | unchanged |
| packages/ai-parrot/tests/benchmarks/conftest.py:13 | Still `def pytest_collection_modifyitems(config, items):` at line 13 | unchanged |
| packages/ai-parrot-tools/tests/research/conftest.py:20 | Still `def pytest_collection_modifyitems(config, items):` at line 20 | unchanged |
| packages/ai-parrot-tools/tests/company_info/conftest.py:21 | Still `def pytest_collection_modifyitems(config, items):` at line 21 | unchanged |
| .github/workflows/ci.yml:147 | Still `run: uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors` at line 147, verbatim | unchanged (line number identical) |
| .gitignore:363-366 | Still `.codex/*` / `!.codex/` / `!.codex/agents/` / `!.codex/agents/*.toml` at lines 363-366, verbatim | unchanged |

**Notable FEAT-562-era addition near the CI anchor (not itself an anchor, but adjacent):**
a new comment block just above the "Scaffold NavConfig environment" step
(seen at `.github/workflows/ci.yml:140`, and its duplicates at `:380`,
`:469` for the other CI jobs): "a runner (pytest exited 4 on a conftest
ImportError). An empty dev env is enough to let navconfig bootstrap …" —
this documents a `pytest.importorskip`/conftest-bootstrap guard FEAT-562
introduced elsewhere in the CI job bodies, but it does not move or alter
the anchor line (`:147`) itself.

## 3. Marker inventory (post-FEAT-562)

    $ grep -n -A12 "^markers" pytest.ini
    4:markers =
    5-    integration: Integration tests with external APIs (Telegram, Massive, etc)
    6-    live: Live integration tests that require external services (claude CLI, Redis, real LLM API). Skipped when prerequisites are missing.
    7-    real_llm: Real LLM integration tests (require PARROT_TEST_REAL_LLM=1 env var)
    8-    slow: Long-running tests (multiprocess contention, large fixtures). Deselect with -m "not slow".

    $ grep -n -A15 "tool.pytest.ini_options" packages/*/pyproject.toml
    packages/ai-parrot/pyproject.toml:997        -> markers: real_llm, network, live
    packages/ai-parrot-server/pyproject.toml:118 -> markers: wheel_build, requires_apscheduler, requires_aioquic, requires_mcp_sdk, live
    packages/ai-parrot-integrations/pyproject.toml:143 -> markers: live_vendor
    packages/ai-parrot-openlit-bridge/pyproject.toml:50 -> [tool.pytest.ini_options] present (not in original anchor list; not registering markers relevant to this feature)
    packages/navrules/pyproject.toml:53 -> [tool.pytest.ini_options] present (not in original anchor list)
    packages/parrot-formdesigner/pyproject.toml:93 -> asyncio_mode only, no markers list

    $ grep -rn "def pytest_collection_modifyitems\|def pytest_configure\|addinivalue_line" --include=conftest.py tests packages/*/tests conftest.py
    tests/knowledge/wiki/conftest.py:27:def pytest_configure(config)
    tests/knowledge/wiki/conftest.py:34:    config.addinivalue_line(...)
    packages/ai-parrot-embeddings/tests/conftest.py:15:def pytest_configure(config)
    packages/ai-parrot-embeddings/tests/conftest.py:17,21,25,29: config.addinivalue_line(...)
    packages/ai-parrot-server/tests/conftest.py:141:def pytest_configure(config)
    packages/ai-parrot-server/tests/conftest.py:143,147,151,155: config.addinivalue_line(...)
    packages/ai-parrot/tests/benchmarks/conftest.py:13:def pytest_collection_modifyitems(config, items)
    packages/ai-parrot/tests/conftest.py:15:def pytest_collection_modifyitems(config, items)
    packages/ai-parrot-tools/tests/company_info/conftest.py:21:def pytest_collection_modifyitems(config, items)
    packages/ai-parrot-tools/tests/research/conftest.py:20:def pytest_collection_modifyitems(config, items)

    No `e2e` marker is registered anywhere in the tree (grep for `\be2e\b` in
    pytest.ini and every packages/*/pyproject.toml returns nothing).

    None of the discovered `pytest_collection_modifyitems` / `pytest_configure`
    hooks perform directory-based auto-marking (path-segment inspection). All
    of them either skip by an existing marker (real_llm/apscheduler/aioquic/…)
    or register markers via `addinivalue_line`. TASK-3316's directory-based
    `integration`/`e2e` auto-marking is therefore still greenfield work — it
    extends, it does not duplicate, any FEAT-562 hook.

## 4. Notes for the orchestrator (fold into spec §6 / TASK-3316)

- All twelve re-verified anchors are **unchanged** in both line number and
  content since the spec's 2026-09-17 pre-FEAT-562 recording. FEAT-562 did
  **not** touch `pytest.ini`, the six `[tool.pytest.ini_options]` blocks
  listed in the contract, the four listed conftest hooks, the `ci.yml:147`
  command, or the `.gitignore` codex block. Spec §6 needs no anchor edits.
- FEAT-562 did add a CI-only conftest-ImportError/NavConfig-bootstrap
  comment/step immediately above the `ci.yml:147` anchor (and its two
  duplicate CI jobs) — informational only, out of scope for FEAT-563 (CI
  selection changes are FEAT-562's non-goal boundary per spec §1).
- No `e2e` marker exists yet anywhere — TASK-3316 must add it fresh, not
  merge with an existing registration.
- No directory-based auto-marking hook exists anywhere in the tree —
  TASK-3316 is pure addition, no risk of duplicating FEAT-562 logic.
- `ai-parrot-openlit-bridge/pyproject.toml:50` and `navrules/pyproject.toml:53`
  also carry `[tool.pytest.ini_options]` blocks but were not part of the
  original spec §6 anchor list and register no markers relevant to this
  feature — noted for completeness, no action needed.
- The FEAT-562 per-spec index (`ci-test-failures-root-cause-remediation.json`
  on `origin/dev`) still reports `completed_at: null` with 5 of 6 tasks
  `pending` despite its branch being an ancestor of `origin/dev` — likely a
  stale index snapshot from before/around the merge. Flagged for the
  orchestrator's awareness; does not block this gate (see §1 note).

verdict: PASS
