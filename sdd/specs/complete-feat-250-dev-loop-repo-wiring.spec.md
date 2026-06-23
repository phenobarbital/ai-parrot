---
type: feature
base_branch: dev
---

# Feature Specification: Complete FEAT-250 Repo Wiring — BASE_DIR-anchored worktrees & declared-repo provisioning

**Feature ID**: FEAT-253
**Date**: 2026-06-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.7.x (`ai-parrot`)

> **Lineage**: Completes the repo-provisioning half of FEAT-250
> (`dev-loop-refactor.spec.md`). FEAT-250 landed `RepoSpec`,
> `ResearchNode._provision_repos`, `GitToolkit.clone_repo`/`pull_repo`, the
> declarative definition + factories, and `ResearchOutput.repo_path`, but its
> own §8 deferred multi-repo / primary-cwd handling to "v1 = one repo" and the
> wiring was never connected end-to-end. This spec finishes the connection and
> defines the **local (no-repo-declared) fallback** behaviour the user asked
> for: anchor everything at `BASE_DIR`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop flow (`examples/dev_loop/server.py`) can only ever edit the folder
the server happens to be launched from, and the FEAT-250 repo machinery — which
was supposed to let a run target an arbitrary git repository — is wired only
half-way:

1. **The demo never declares a repo.** `examples/dev_loop/server.py:389` calls
   `build_dev_loop_flow(...)` with **no** `git_toolkit=` and **no** `repos=`, so
   `ResearchNode._provision_repos()` short-circuits
   (`research.py:260`: `if not self._repos or self._git_toolkit is None: return ""`)
   and nothing is ever cloned.

2. **Nothing turns `DEV_LOOP_REPOS` into `RepoSpec`s.** `conf.DEV_LOOP_REPOS`
   (`conf.py:870`) is a raw `list[str]`; the docstring says the *flow config*
   should parse it into `RepoSpec` objects, but no such parser exists. There is
   no way to declare a repo via environment.

3. **Paths are anchored to the process launch dir, not the repo root.**
   `WORKTREE_BASE_PATH` defaults to the **relative** string `".claude/worktrees"`
   (`conf.py:846`); `_provision_repos` and the dispatcher guard both call
   `os.path.abspath(...)` on it, so the resolved location silently depends on
   *where* the server was started. A run launched from anywhere other than the
   repo root provisions into the wrong place.

4. **No defined "local" behaviour.** When no repo is declared we run dev-loop
   locally against the current checkout. There is no first-class notion that
   "the repository is the local checkout rooted at `BASE_DIR`", so
   `_provision_repos` returns `""` and the design intent ("use `BASE_DIR` as the
   base repo to create a worktree from") is undocumented and unimplemented.

### Goals

- **G1 — `BASE_DIR`-anchored paths.** Resolve `WORKTREE_BASE_PATH` and
  `DEV_LOOP_REPO_BASE_PATH` against `navconfig.BASE_DIR` so worktrees and clones
  always land at `BASE_DIR/.claude/worktrees[/repos/<run_id>/<alias>]`,
  independent of the process's launch directory. The dispatcher cwd-safety guard
  keeps passing because everything stays under `BASE_DIR/.claude/worktrees`.
- **G2 — Local fallback to `BASE_DIR`.** When **no** repo is declared, the run's
  **base repository** is the local checkout rooted at `BASE_DIR`. The per-run
  worktree is created **from** `BASE_DIR`; `ResearchOutput.repo_path` is set to
  `BASE_DIR`. `worktree_path` (the Development cwd) is **not** overwritten with
  `BASE_DIR`.
- **G3 — Declared-repo provisioning, end-to-end.** When `DEV_LOOP_REPOS` (or a
  programmatic `repos=` list) is supplied, the primary repo is cloned/pulled into
  `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`, that clone becomes the
  run's **base repository** (`repo_path`), and the per-run worktree is created
  **from the clone** (not from the outer `BASE_DIR` repo).
- **G4 — `DEV_LOOP_REPOS` parser.** Add a parser that turns each
  `DEV_LOOP_REPOS` entry — an `owner/name` slug, a full clone URL (incl.
  `git@github.com:phenobarbital/ai-parrot.git`), or a JSON object string — into
  a `RepoSpec`. Lives in the `dev_loop` package (not `conf.py`, which must not
  import `dev_loop`).
- **G5 — Wire the demo server.** `examples/dev_loop/server.py` builds a
  `GitToolkit` and passes `git_toolkit=` + `repos=` (parsed from
  `DEV_LOOP_REPOS`) into `build_dev_loop_flow(...)`, so the demo can target
  `git@github.com:phenobarbital/ai-parrot.git` when configured and falls back to
  the local checkout when not.

### Non-Goals (explicitly out of scope)

- **Pointing `DevelopmentNode` at the clone/`BASE_DIR` directly.** The agent
  always codes in the isolated `worktree_path`; we do **not** set Development's
  cwd to `repo_path`. (Rejected per user: "not overwrite the worktree_path".)
- **Multi-repo Development in one run.** Like FEAT-250, v1 supports a single
  **primary** base repository (the first `RepoSpec`). Additional repos may be
  cloned but Development branches from the primary only.
- **Relaxing the dispatcher cwd-safety guard.** All clones and worktrees stay
  under `BASE_DIR/.claude/worktrees`; the guard is unchanged.
- The code-review QA gate, draft PR, and revision loop (already delivered in
  FEAT-250) — untouched here.

---

## 2. Architectural Design

### Overview

A run operates on a **base repository** (a real git repo). The per-run
**worktree** is created *from* that base repository and is where the
`Development` node codes (`worktree_path`). `ResearchOutput.repo_path` records
the base repository (its source), **distinct** from `worktree_path`.

Base-repository resolution (in `ResearchNode`, FEAT-250's `_provision_repos`):

- **No repos declared →** base repository = the local checkout at `BASE_DIR`.
  No clone happens; `repo_path = str(BASE_DIR)`. The worktree branches from
  `BASE_DIR` (today this already happens because the `sdd-research` dispatch runs
  with `cwd` inside the `BASE_DIR` repo).
- **Repos declared →** clone/pull the primary `RepoSpec` into
  `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`; `repo_path =` that clone.
  The worktree is created **from the clone**, so the `sdd-research` dispatch runs
  with `cwd = repo_path` (the clone) — its `/sdd-spec`, `/sdd-task`, and
  `git worktree add` then all operate on the clone, not the outer `BASE_DIR`
  repo. This requires provisioning to run **before** the `sdd-research` dispatch.

All paths are anchored at `BASE_DIR` so the absolute locations don't depend on
the launch directory, and they remain under `BASE_DIR/.claude/worktrees` so the
dispatcher's `_enforce_cwd_under_worktree_base` guard passes unchanged.

### Component Diagram

```
DEV_LOOP_REPOS (env: slug | url | json)
        │  parse_repo_specs()
        ▼
   [RepoSpec, ...] ──► build_dev_loop_flow(git_toolkit=GitToolkit, repos=...)
                              │
                              ▼
                       ResearchNode._provision_repos(run_id)
             ┌──────────────────────────┴───────────────────────────┐
   repos == []                                          repos != []
   base repo = BASE_DIR                     clone primary RepoSpec into
   repo_path = str(BASE_DIR)                BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>
   (no clone; sdd-research cwd =            repo_path = <clone path>
    WORKTREE_BASE_PATH, branches            (sdd-research cwd = clone → worktree
    worktree from BASE_DIR)                  branches from the clone)
             └──────────────────────────┬───────────────────────────┘
                                        ▼
            worktree created FROM repo_path  →  worktree_path (Development cwd)
                                        ▼
                   DevelopmentNode(cwd = worktree_path)   # UNCHANGED
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.conf.WORKTREE_BASE_PATH` (`conf.py:846`) | modifies | Anchor at `BASE_DIR` (e.g. `str(BASE_DIR / ".claude/worktrees")`), keeping the same default leaf so existing layouts are unchanged. |
| `parrot.conf.DEV_LOOP_REPO_BASE_PATH` (`conf.py:873`) | modifies | Default becomes `BASE_DIR/.claude/worktrees/repos` (anchored), still under `WORKTREE_BASE_PATH`. |
| `ResearchNode._provision_repos` (`research.py:250`) | modifies | Return `str(BASE_DIR)` when no repos/no git toolkit (instead of `""`); anchor the clone base at `BASE_DIR`; when a clone is the base repo, ensure the `sdd-research` dispatch uses `cwd = repo_path`. |
| `ResearchNode.execute` (`research.py:133`) | modifies | Run provisioning **before** the `sdd-research` dispatch and pass `cwd = repo_path` (the clone) to that dispatch when a repo is declared; for the local case `cwd` stays `WORKTREE_BASE_PATH`. Set `repo_path` on `ResearchOutput`. |
| `parrot.flows.dev_loop` (new helper) | adds | `parse_repo_specs(raw: list[str]) -> list[RepoSpec]`. |
| `examples/dev_loop/server.py:389` | modifies | Build `GitToolkit`, parse `conf.DEV_LOOP_REPOS`, pass `git_toolkit=`/`repos=`. |
| `DevelopmentNode.execute` (`development.py:88`) | **unchanged** | Continues to dispatch with `cwd = research.worktree_path`. |
| `RevisionHandoffNode` (`revision_handoff.py:61`) | **unchanged** | Already prefers `repo_path` → `worktree_path`. |
| `ClaudeCodeDispatcher._enforce_cwd_under_worktree_base` (`dispatcher.py:301`) | uses (unchanged) | Guard still passes because all clones/worktrees live under `BASE_DIR/.claude/worktrees`. |
| `GitToolkit.clone_repo`/`pull_repo` (`gittoolkit.py:1599,1662`) | uses (unchanged) | Already implemented; idempotent (re-clone → pull). |

### Data Models

No new models. Existing fields are reused with clarified semantics:

```python
# parrot/flows/dev_loop/models.py  (semantics clarified, no schema change)
class ResearchOutput(BaseModel):
    worktree_path: str   # per-run worktree — the Development cwd (UNCHANGED)
    repo_path: str = ""  # BASE REPOSITORY the worktree was branched from:
                         #   str(BASE_DIR) when no repo declared, else the clone.
                         #   NEVER equal to/overwriting worktree_path.

class RepoSpec(BaseModel):     # unchanged (FEAT-250)
    alias: str
    url: str                   # owner/name slug, https URL, or git@... URL
    branch: str = "main"
    private: bool = False
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/__init__.py  (or dev_loop/config.py)
def parse_repo_specs(raw: list[str]) -> list[RepoSpec]:
    """Parse DEV_LOOP_REPOS entries into RepoSpec objects.

    Each entry is one of:
      * a JSON object string  -> RepoSpec(**json)
      * a full clone URL      -> RepoSpec(alias=<derived>, url=<entry>)
                                 (https://…/owner/name(.git) or git@host:owner/name.git)
      * an 'owner/name' slug  -> RepoSpec(alias=<name>, url=<entry>)
    The alias defaults to the repo's <name> component; 'branch' defaults to
    'main' and 'private' to False unless given in the JSON form.
    """
```

---

## 3. Module Breakdown

### Module 1: `BASE_DIR`-anchored config
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Resolve `WORKTREE_BASE_PATH` against `BASE_DIR` (already
  imported at `conf.py:5`) — e.g.
  `config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))`,
  and when the configured value is relative, join it onto `BASE_DIR`. Update
  `DEV_LOOP_REPO_BASE_PATH`'s fallback to be anchored under that. Keep the
  emitted leaf (`.claude/worktrees`, `.../repos`) identical so existing
  worktrees/tests are unaffected.
- **Depends on**: nothing new (`BASE_DIR` already imported).

### Module 2: `DEV_LOOP_REPOS` → `RepoSpec` parser
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/` (new helper, e.g.
  `config.py`, re-exported from `__init__.py`).
- **Responsibility**: Implement `parse_repo_specs(raw)` (slug / URL / JSON →
  `RepoSpec`), including alias derivation for `git@github.com:owner/name.git`,
  `https://github.com/owner/name(.git)`, and `owner/name`. Tolerant of blank
  lines; invalid JSON falls back to URL/slug handling.
- **Depends on**: `RepoSpec` (M-none).

### Module 3: Provisioning — local fallback + clone-sourced worktree
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
- **Responsibility**:
  - `_provision_repos`: return `str(BASE_DIR)` when `self._repos` is empty or
    `self._git_toolkit is None` (instead of `""`). Anchor the clone base at
    `BASE_DIR` (use the anchored `conf.DEV_LOOP_REPO_BASE_PATH`). Primary clone
    path → `repo_path`.
  - `execute`: run `_provision_repos` **before** the `sdd-research` dispatch;
    when the base repo is a **clone**, pass `cwd = repo_path` to that dispatch so
    `/sdd-spec` / `/sdd-task` / `git worktree add` operate on the clone; for the
    **local** case keep `cwd = conf.WORKTREE_BASE_PATH` (branches the worktree
    from `BASE_DIR`). Always set `ResearchOutput.repo_path` to the resolved base
    repository, leaving `worktree_path` as the per-run worktree.
- **Depends on**: M1, M2.

### Module 4: Demo server wiring
- **Path**: `examples/dev_loop/server.py`
- **Responsibility**: In `_on_startup`, build a `GitToolkit` (PAT/`gh` auth from
  env), call `parse_repo_specs(conf.DEV_LOOP_REPOS)`, and pass
  `git_toolkit=` + `repos=` into `build_dev_loop_flow(...)`. Document the
  `DEV_LOOP_REPOS` env in the module docstring with the
  `git@github.com:phenobarbital/ai-parrot.git` example. No behavioural change
  when `DEV_LOOP_REPOS` is unset (local fallback).
- **Depends on**: M2, M3.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/`
- **Responsibility**: §4.
- **Depends on**: M1–M4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_worktree_base_path_anchored_at_base_dir` | M1 | `conf.WORKTREE_BASE_PATH` resolves under `BASE_DIR` regardless of `os.getcwd()`. |
| `test_repo_base_path_under_worktree_base` | M1 | `DEV_LOOP_REPO_BASE_PATH` is under `WORKTREE_BASE_PATH` and anchored at `BASE_DIR`. |
| `test_parse_repo_specs_slug` | M2 | `"phenobarbital/ai-parrot"` → `RepoSpec(alias="ai-parrot", url="phenobarbital/ai-parrot")`. |
| `test_parse_repo_specs_ssh_url` | M2 | `"git@github.com:phenobarbital/ai-parrot.git"` → alias `ai-parrot`, url preserved. |
| `test_parse_repo_specs_https_url` | M2 | `"https://github.com/phenobarbital/ai-parrot.git"` → alias `ai-parrot`. |
| `test_parse_repo_specs_json` | M2 | JSON object string round-trips all `RepoSpec` fields (branch/private). |
| `test_parse_repo_specs_skips_blanks` | M2 | Empty / whitespace entries are ignored. |
| `test_provision_repos_local_fallback_returns_base_dir` | M3 | No repos / no git toolkit → `_provision_repos` returns `str(BASE_DIR)` (not `""`). |
| `test_provision_repos_clone_path_anchored` | M3 | Declared repo clones into `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`; `repo_path` set to it. |
| `test_research_sets_repo_path_distinct_from_worktree` | M3 | `ResearchOutput.repo_path` is set and is **not** equal to `worktree_path`. |
| `test_research_dispatch_cwd_is_clone_when_declared` | M3 | With a declared repo, the `sdd-research` dispatch receives `cwd == repo_path` (the clone). |
| `test_research_dispatch_cwd_is_worktree_base_when_local` | M3 | With no repo declared, the `sdd-research` dispatch `cwd == conf.WORKTREE_BASE_PATH`. |
| `test_provision_runs_before_dispatch` | M3 | Provisioning is invoked before the `sdd-research` dispatch (ordering guard). |
| `test_development_cwd_still_worktree_path` | M3 | `DevelopmentNode` dispatch `cwd == research.worktree_path` (regression: repo_path does NOT leak in). |
| `test_server_builds_flow_with_repos` | M4 | With `DEV_LOOP_REPOS` set, `_on_startup` passes a non-empty `repos=` + a `git_toolkit` to `build_dev_loop_flow`. |
| `test_server_local_fallback_no_repos` | M4 | With `DEV_LOOP_REPOS` unset, `build_dev_loop_flow` is called with `repos=[]` (or omitted) and still boots. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_clone_then_worktree_from_clone` (`@pytest.mark.live`) | With a declared public fixture repo, a run clones it under `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>` and the resulting `worktree_path` is a git worktree branched from the **clone**. Skipped without `git`/network. |
| `test_e2e_local_run_worktree_from_base_dir` (`@pytest.mark.live`) | With no repo declared, a run creates a worktree branched from `BASE_DIR`; `repo_path == str(BASE_DIR)`. |

### Test Data / Fixtures

```python
@pytest.fixture
def ai_parrot_repo_spec() -> RepoSpec:
    return RepoSpec(alias="ai-parrot",
                    url="git@github.com:phenobarbital/ai-parrot.git",
                    branch="dev", private=True)
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `conf.WORKTREE_BASE_PATH` and `conf.DEV_LOOP_REPO_BASE_PATH` resolve as
  absolute paths anchored at `navconfig.BASE_DIR`, independent of the process's
  current working directory, and both remain under `BASE_DIR/.claude/worktrees`.
- [ ] With **no** repo declared, `ResearchNode._provision_repos` resolves the
  base repository to `str(BASE_DIR)` and sets `ResearchOutput.repo_path = str(BASE_DIR)`;
  the per-run worktree is branched from `BASE_DIR`; `worktree_path` is **not**
  overwritten with `BASE_DIR`.
- [ ] With a repo declared, the primary repo is cloned/pulled into
  `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`, `repo_path` is set to that
  clone, and the per-run worktree is branched **from the clone** (the
  `sdd-research` dispatch runs with `cwd = repo_path`).
- [ ] Provisioning runs **before** the `sdd-research` dispatch.
- [ ] `parse_repo_specs` turns `owner/name` slugs, `https://…` URLs, and
  `git@github.com:owner/name.git` URLs, and JSON object strings into `RepoSpec`
  objects, deriving a sensible `alias`.
- [ ] `examples/dev_loop/server.py` builds a `GitToolkit` and passes
  `git_toolkit=` + `repos=parse_repo_specs(conf.DEV_LOOP_REPOS)` to
  `build_dev_loop_flow(...)`; it targets `git@github.com:phenobarbital/ai-parrot.git`
  when `DEV_LOOP_REPOS` is set and falls back to the local checkout when not.
- [ ] `DevelopmentNode` is unchanged and still dispatches with
  `cwd = research.worktree_path`; the dispatcher cwd-safety guard passes in both
  local and declared-repo modes.
- [ ] All unit tests in §4 pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`.
- [ ] No breaking changes to `GitToolkit`, `ResearchOutput`/`RepoSpec`,
  `build_dev_loop_flow`, or `DevLoopRunner` public APIs; an existing run with no
  repos behaves as before (modulo the `repo_path` now being `BASE_DIR` instead of
  `""`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was verified by
> `read`/`grep` against the working tree on `dev` (2026-06-23).

### Verified Imports

```python
from navconfig import config, BASE_DIR                      # used in conf.py:5 (BASE_DIR is a pathlib.PosixPath)
from parrot import conf                                     # conf.py
from parrot.flows.dev_loop.models import RepoSpec, ResearchOutput  # models.py:185,240
from parrot.flows.dev_loop import build_dev_loop_flow       # flow.py:164 (re-exported in __init__.py)
from parrot.flows.dev_loop.nodes.research import ResearchNode        # research.py
from parrot.flows.dev_loop.nodes.development import DevelopmentNode  # development.py:30
from parrot_tools.gittoolkit import GitToolkit              # gittoolkit.py:968
```

### Existing Class Signatures (verified)

```python
# packages/ai-parrot/src/parrot/conf.py
from navconfig import config, BASE_DIR                       # :5  (BASE_DIR == /home/jesuslara/proyectos/navigator/ai-parrot)
WORKTREE_BASE_PATH: str = config.get("WORKTREE_BASE_PATH", fallback=".claude/worktrees")   # :846  (RELATIVE today)
DEV_LOOP_REPOS: list[str] = config.getlist("DEV_LOOP_REPOS", fallback=[]) or []            # :870
DEV_LOOP_REPO_BASE_PATH: str = config.get(
    "DEV_LOOP_REPO_BASE_PATH", fallback=f"{WORKTREE_BASE_PATH}/repos")                       # :873

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):
    def __init__(self, *, dispatcher, jira_toolkit, log_toolkits=None,
                 summarizer_llm=None, plan_llm=None,
                 git_toolkit=None, repos=None, name="research"): ...       # :104
    async def execute(self, ctx, deps=None, **kwargs) -> ResearchOutput:  # :133
        # current order: logs → jira → DISPATCH sdd-research(cwd=conf.WORKTREE_BASE_PATH)  (:206,213-220)
        #                → _ensure_worktree_safe (:232) → _provision_repos (:237)
    async def _provision_repos(self, run_id: str) -> str:                 # :250  (returns "" when no repos/git toolkit)
        # clones into os.path.join(os.path.abspath(conf.DEV_LOOP_REPO_BASE_PATH), run_id or "run", alias)  (:263-266)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
class DevelopmentNode(DevLoopNode):
    async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:
        research = shared["research_output"]
        dev_out = await self._dispatcher.dispatch(..., cwd=research.worktree_path)  # :88  (KEEP)

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class RepoSpec(BaseModel):                                  # :185
    alias: str; url: str; branch: str = "main"; private: bool = False
class ResearchOutput(BaseModel):                           # :240
    worktree_path: str  # :279   (AliasChoices "worktree_path","worktree")
    repo_path: str = "" # :284   (AliasChoices "repo_path","repo","clone_path")

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:             # :301
    # raises if os.path.abspath(cwd) is not under os.path.abspath(conf.WORKTREE_BASE_PATH)

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):                                        # :968
    def __init__(self, default_repository=None, default_branch="main",
                 github_token=None, auth_type="pat", app_id=None,
                 installation_id=None, private_key=None,
                 private_key_path=None, repositories=None, **kwargs): ...  # :977
    async def clone_repo(self, repository, dest_dir, branch=None, *,
                         private=False, depth=None) -> Dict[str, Any]: ... # :1599 (idempotent: pulls if dest is a clone)
    async def pull_repo(self, repo_path, branch=None) -> Dict[str, Any]: ... # :1662

# examples/dev_loop/server.py
async def _on_startup(app):                                               # :380
    app["flow"] = build_dev_loop_flow(dispatcher=..., jira_toolkit=...,
        log_toolkits=..., redis_url=..., name="dev-loop-demo")            # :389  (NO git_toolkit / repos today)

# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py
def build_dev_loop_node_factories(*, dispatcher, jira_toolkit, redis_url,
    git_toolkit=None, log_toolkits=None, repos=None): ...                 # :42  (already forwards git_toolkit + repos to ResearchNode :84-85)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| anchored paths | `_enforce_cwd_under_worktree_base` | `os.path.abspath(conf.WORKTREE_BASE_PATH)` | `dispatcher.py:307` |
| `parse_repo_specs` | `build_dev_loop_flow(repos=...)` | call in `server._on_startup` | `flow.py:174`, `server.py:389` |
| local fallback / clone base | `ResearchNode._provision_repos` | return `str(BASE_DIR)` / anchored clone | `research.py:250-284` |
| clone-sourced worktree | `sdd-research` dispatch `cwd` | `cwd=repo_path` when clone | `research.py:213-220` |
| repo provisioning deps | `ResearchNode(..., git_toolkit=, repos=)` | already forwarded by factory | `factories.py:84-85` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parse_repo_specs`~~ — must be created (M2). No `DEV_LOOP_REPOS`→`RepoSpec`
  parser exists anywhere today.
- ~~`ResearchOutput.repo_path` defaulting to `BASE_DIR`~~ — today
  `_provision_repos` returns `""` and `repo_path` defaults to `""`
  (`models.py:284`); the `BASE_DIR` fallback is new (M3).
- ~~`WORKTREE_BASE_PATH` being absolute~~ — it is the **relative** string
  `".claude/worktrees"` today (`conf.py:846`); anchoring is new (M1).
- ~~`DevelopmentNode` honoring `repo_path`~~ — it does **not** today and must
  **stay** on `worktree_path` (`development.py:88`); this spec deliberately does
  **not** change it.
- ~~`examples/dev_loop/server.py` passing `git_toolkit`/`repos`~~ — it does not
  today (`server.py:389`); added in M4.
- ~~A separate "create worktree" toolkit method~~ — worktree creation remains the
  responsibility of the `sdd-research` subagent (driven by its cwd); no new
  deterministic worktree-creation API is introduced here.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; never block the event loop (clone/pull already use
  `asyncio.create_subprocess_exec` inside `GitToolkit`).
- Anchor paths with `BASE_DIR` (a `pathlib.PosixPath`); emit `str(...)` for the
  `conf` string values to preserve existing types.
- Keep `conf.py` free of any `dev_loop` import — the `RepoSpec` parser lives in
  the `dev_loop` package and is called by `server.py`, not by `conf`.
- Never log clone tokens — `GitToolkit` already scrubs; do not re-echo URLs.
- Reuse the FEAT-250 factory plumbing (`factories.py` already forwards
  `git_toolkit` + `repos` to `ResearchNode`); no factory change needed.

### Known Risks / Gotchas
- **R1 — Path anchoring must stay backward-compatible.** Resolving
  `WORKTREE_BASE_PATH` under `BASE_DIR` must yield the *same* effective location
  when the server is launched from the repo root (the common case), so existing
  worktrees/tests don't move. Honor an explicitly-set absolute
  `WORKTREE_BASE_PATH` env verbatim; only join relative values onto `BASE_DIR`.
- **R2 — Reordering provisioning before dispatch.** FEAT-250 clones *after* the
  `sdd-research` dispatch. Moving it before changes when the Jira ticket/branch
  name are known. Verify `_ensure_worktree_safe` and branch-name handling still
  work when the worktree is branched from a clone whose `cwd` is the clone dir.
- **R3 — Worktree-from-clone path.** When `sdd-research` runs with `cwd` = the
  clone, its `git worktree add` must place the worktree under
  `BASE_DIR/.claude/worktrees` (guard) — confirm the subagent prompt / SDD
  worktree convention produces a path the dispatcher accepts for the subsequent
  `Development` dispatch.
- **R4 — `git@` SSH URLs need a key.** `git@github.com:...` clones require an SSH
  agent/key on the host; `parse_repo_specs` preserves the URL as-is and relies on
  `GitToolkit`'s existing auth (token-in-URL for `https`, `gh`/SSH otherwise).
  Document that private SSH clones need host SSH config.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `git` CLI | system | clone/pull/worktree |
| `gh` CLI | optional | private clone fallback (already used by `GitToolkit`) |
| `navconfig` | present | `BASE_DIR` anchor (already a dependency) |

---

## 8. Open Questions

- [x] When no repo is declared, what is the base repository? — *Resolved with
  user (2026-06-23)*: `BASE_DIR` (the local checkout). It is the base root used
  to **create the worktree from**; it does **not** overwrite `worktree_path`.
- [x] How are paths anchored? — *Resolved with user (2026-06-23)*: everything is
  rooted at `BASE_DIR`, i.e. `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`.
- [x] Should `DevelopmentNode` cd into the clone/`repo_path`? — *Resolved with
  user (2026-06-23)*: **No** — Development always codes in the isolated
  `worktree_path`; the base repo is only the worktree's source.
- [x] For declared repos, is the worktree branched from the clone or from the
  outer `BASE_DIR` repo? — *Resolved (2026-06-23)*: from the **clone** (the
  `sdd-research` dispatch runs with `cwd = repo_path`), which implies
  provisioning runs before that dispatch.
- [x] Multi-repo runs (>1 `RepoSpec`): secondary repos are cloned but not used as
  the Development base. Confirm whether secondary clones are needed at all in v1
  or should be deferred entirely. — *Owner: Jesus Lara (decide at /sdd-task)*: secondary clones are not needed in v1, defer to follow-up

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — tasks are sequential and centre on
  `conf.py` + `parrot/flows/dev_loop/nodes/research.py` + the parser + the demo
  server; they share state and should land in one worktree.
- **Parallelizable sub-tasks**: M2 (parser) is independent of M1 (config) and can
  be written/tested in parallel; M3 depends on both; M4 depends on M2+M3.
- **Cross-feature dependencies**: none — FEAT-250 is already merged on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-23 | Jesus Lara | Initial draft — complete FEAT-250 repo wiring: BASE_DIR-anchored paths, local BASE_DIR fallback, declared-repo clone-sourced worktrees, DEV_LOOP_REPOS parser, demo-server wiring. |
