---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [installer, portability, worktree, doctor, mcp-toolkits]
---

# Feature Specification: Installer portability gaps — one root, one portable rule

**Feature ID**: FEAT-804
**Date**: 2026-11-04
**Author**: Jesus Lara (design captured in chat, 2026-11-04)
**Status**: approved
**Target version**: 2.1.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The 2026-11-04 evaluation of the SDD flow on an external repository (`../fieldsync`, migrated to the
packaged flow) and on ai-parrot itself left three installer defects open on `dev` after the FEAT-633
fixes (see `sdd/proposals/parrot-installer-amendments.proposal.md` §5 for what was already closed):

1. **Absolute paths are committed by default, silently.** `parrot claude|codex|google install` default to
   `portable=None`, which `_current_portable_mode()` turns into *baked* on a fresh repository
   (`claude_code/installer.py:139-170`, `codex/installer.py:188-227`, `google/installer.py:75-92`): the
   committed `.mcp.json` / `.codex/config.toml` carry the installing machine's venv path and nothing tells
   the operator. The SDD guard hook already solved the same problem one layer down —
   `guard_hook_command()` (`sdd/installer.py:280-300`) renders the bare command when the managed launcher
   resolves on `PATH` and prints `note: guard hook baked …` otherwise — but the rule is private to it.
2. **`parrot sdd install --portable` does not reach the toolkit entries on a fresh repository.**
   `install_sdd_integration()` passes `portable` to the guard hook and the dangerous-actions guard, but
   `_install_toolkits_step(root, hosts, receipt)` (`sdd/installer.py:1152,1227`) calls
   `install_toolkits(root, names, hosts)` (`mcp/toolkit_install.py:158`) which has no `portable`
   parameter; every `HostAdapter.reconcile(root)` (`mcp/hosts.py:51`) then falls back to the sticky
   inference, and with no host config yet that inference is *baked*. The flag only "works" when a portable
   `.mcp.json` already exists.
3. **Four different answers to "which repository am I installing into".** The host installers resolve
   `find_project_root()` from `knowledge/wiki/project.py:1049`, which prefers the nearest `.parrot/wiki.json`
   *upward* over the worktree's own `.git` file — from a linked worktree that is the primary checkout, so
   `parrot claude install` run inside a worktree rewrites the primary checkout's `.mcp.json` and
   `CLAUDE.md` without saying so. `parrot sdd install` uses the bare cwd (`sdd/cli.py:48-53`: a
   subdirectory becomes the "repository root"); `parrot toolkits` uses `Path.cwd()` seven times
   (`cli/toolkits.py:98,126,164,184,224,249,271`); `parrot self doctor` uses the launcher's nearest-`.git`
   walk (`self_/cli.py:72`). Worse, had the host installers targeted the worktree they would have written
   `<worktree>/.parrot/wiki.json`, after which every `wikitoolkit` call from that worktree would resolve a
   second, empty wiki plane — exactly what FEAT-697 (`find_shared_root`, `project.py:1560`) exists to
   prevent.

### Goals

- **G1 — One portable rule.** A single function decides the form of every emitted command (guard hook,
  dangerous-actions hook, wikitoolkit/bookstore entries, `parrot-*` toolkit entries, Codex rules): an
  explicit flag wins; otherwise an existing managed configuration keeps its form (FEAT-633 stickiness);
  otherwise — a fresh host — *portable when the managed launcher resolves on `PATH`, baked with a printed
  `note:` otherwise*. The same rule `guard_hook_command()` uses today, promoted to all emitters.
- **G2 — The flag reaches every entry.** `parrot sdd install --portable` and a new
  `parrot toolkits install|enable --portable/--no-portable` forward the decision through
  `install_toolkits()` → `HostAdapter.reconcile()` → the three host reconcilers, which already accept
  `portable` (`claude_code/installer.py:705`, `codex/installer.py:263`, `google/installer.py:220`).
- **G3 — One install root.** Every installer-type command (`parrot claude|codex|google install|uninstall`,
  `parrot sdd install|uninstall`, `parrot toolkits install|uninstall|enable|disable`, `parrot self doctor`)
  resolves the same `InstallRoot`: `--path`/`--project` verbatim, else the nearest checkout containing a
  `.git` directory *or file* (so a subdirectory resolves to its repository), never the wiki-plane root.
- **G4 — Refuse linked worktrees.** Without an explicit `--path`, an installer whose resolved root is a
  linked worktree exits 1 naming the primary checkout and the `--path` escape hatch; `doctor` reports it as
  a failing `repo: checkout` check. Read-only verbs (`status`, `list`) only resolve, never refuse.
- **G5 — Say what was written.** The install log prints the form and, when baked, the fix; `doctor`
  reports the form of every host config informationally.
- **G6 — The wiki plane never splits.** Host CLIs and installers use `InstallRoot.shared_root` for
  wiki configuration, remote lookup and initial wiki builds, even when `--path` points at a linked
  worktree. Host assets still target `InstallRoot.root`. Ordinary checkouts with external Git metadata
  keep their own wiki state; an external gitdir alone is not evidence of a linked worktree.

### Non-Goals (explicitly out of scope)

- Changing `knowledge/wiki/project.py::find_project_root` — it answers the *wiki plane* question (FEAT-697)
  and keeps doing so; this spec stops the installers from asking it the *install target* question.
- Relocating the worktree root (`.claude/worktrees` → `.parrot/worktrees`) — FEAT-802
  (`sdd/specs/worktree-root-under-parrot.spec.md`), independent.
- Non-Python repositories' worktree provisioning (`[tool.parrot.worktree]` outside `pyproject.toml`) —
  separate follow-up spec.
- Making `.parrot/mcp-toolkits.yaml` relative: its `repo_root:` is rendered absolute by
  `toolkit_seed.py:184,412`, the file is git-ignored per checkout and read by the local process only; it is
  per-machine state, not a committed path.
- Seeding `.parrot/mcp-toolkits.yaml` into linked worktrees so portable `parrot-*` entries start from a
  worktree session (`mcp/local_cli.py:118-150` stops its walk at the worktree's own `.mcp.json`); recorded
  in §7 as a known gap for the worktree follow-up.
- Removing the `--portable` flags or the sticky inference — they stay; only the fresh-repository default
  and the forwarding change.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:180886adb14f1ed918ba57622caecb4a652862c76d251f6f32c60f6629768ad1 evaluation_digest=sha256:c9b8f821b46b72710ac40b5a590d5cac28be3ce4e52369739445df6386f403a1 rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools

## 2. Architectural Design

### Overview

Two small, stdlib-only primitives are added at the bottom of the stack and every installer is rewired to
them:

1. **`parrot.launcher.install_root()`** — the install-target resolver. It wraps the existing
   `repository_paths()` walk (`launcher.py:58-84`) and returns an `InstallRoot(root, shared_root, linked,
   explicit)`: `root` is the checkout the command targets, `shared_root` the primary checkout
   (`common_git_dir.parent` for a conventional linked worktree, equal to `root` when not linked),
   `linked` whether the checkout's gitdir has valid `commondir` metadata. An external gitdir without
   `commondir` (a submodule or `--separate-git-dir` checkout) is not linked.
   `require_primary_checkout()` turns `linked and not explicit` into `LinkedWorktreeError` with the
   primary checkout and `--path` in the message. The launcher module stays stdlib-only
   (`tests/launcher/test_launcher_stdlib_only.py`). `managed_launcher_on_path()` — the "does `parrot` on
   `PATH` resolve under `parrot_home()`" test currently inlined in `guard_hook_command()` — moves here too,
   because every emitter needs it.
2. **`parrot.mcp.portability.resolve_portable_mode()`** — the one portable rule (G1). Inputs: the explicit
   flag (`bool | None`) and the host's *current* managed form (`bool | None`, `None` meaning "no managed
   entry exists yet"). Output: `PortableDecision(portable, reason, note)` with `reason` in
   `explicit | sticky | launcher | baked-fallback`; `note` is the install-log line for the baked fallback.
   The three `_current_portable_mode()` helpers become tri-state (`None` when no managed entry/block is
   present) so the fresh-repository case is distinguishable from "baked on purpose".

Then the rewiring:

- The six `if portable is None: portable = _current_portable_mode(...)` sites
  (`claude_code/installer.py:736,1280`, `codex/installer.py:294,453`, `google/installer.py:245,404`) become
  `decision = resolve_portable_mode(portable, current=_current_portable_mode(...))`; install entry
  functions and the reconcilers append `decision.note` to their action log when set.
- `guard_hook_command()` becomes tri-state — `None` = launcher rule (today's `False`), `True` = bare,
  `False` = baked on purpose — and calls `managed_launcher_on_path()`; `dangerous_hook_command()`,
  `_install_dangerous_guard()` and `install_sdd_integration()` carry the same `bool | None`.
- `HostAdapter.reconcile(root, *, portable=None)` forwards to the reconcilers; `install_toolkits()` and
  `set_toolkits_enabled()` gain `portable: bool | None = None`; `_install_toolkits_step()` forwards the
  tri-state of `parrot sdd install --portable/--no-portable` (`None` = sticky per host, launcher rule on a
  fresh host). `parrot sdd install` and `parrot toolkits install|enable` carry `--portable/--no-portable`
  (default `None`).
- The three host `_resolve_root()` helpers (`claude_code/cli.py:36`, `codex/cli.py:25`, `google/cli.py:25`),
  `sdd/cli.py::_root` and the seven `Path.cwd()` in `cli/toolkits.py` call `install_root()`; write verbs
  call `require_primary_checkout()`, read verbs do not. Toolkit write verbs gain `--path` and pass it
  as an explicit target. Host CLIs and installers resolve wiki configuration and build targets at
  `InstallRoot.shared_root` (G6), before loading or passing any config object.
- `doctor` gains `repo: checkout` (failing when linked, `fix` names the primary checkout) and
  `host config: form` (informational: `portable` or `baked to <venv>`); `self_/cli.py` keeps the launcher's
  `--project`/`PARROT_PROJECT`/`CLAUDE_PROJECT_DIR` pins — only an actual pin counts as explicit;
  automatic repository discovery must not be passed as an explicit override.

Decisions by the owner (2026-11-04): fresh-repository default = *launcher on PATH ⇒ portable, else baked +
note* (supersedes FEAT-633's "default stays baked"); inside a linked worktree without `--path` = *refuse*,
not redirect, not install-in-place.

### Component Diagram
```
parrot.launcher (stdlib only)
  ├─ repository_paths()  ──► install_root() ──► InstallRoot{root, shared_root, linked, explicit}
  │                                 │                       └─ require_primary_checkout() ─► LinkedWorktreeError
  └─ parrot_home() ──► managed_launcher_on_path()
                               │
parrot.mcp.portability          ▼
  resolve_portable_mode(explicit, current) ──► PortableDecision{portable, reason, note}
        ▲                 ▲                 ▲
        │                 │                 │
 claude_code/installer  codex/installer  google/installer      sdd/installer.guard_hook_command
   _current_portable_mode() → bool|None (tri-state)              (unchanged form, uses managed_launcher_on_path)
        ▲                 ▲                 ▲
        └── HostAdapter.reconcile(root, *, portable) ◄── toolkit_install.install_toolkits(..., portable)
                                                          ▲                      ▲
                                            cli/toolkits.py --portable      sdd/installer._install_toolkits_step
CLIs: claude|codex|google cli._resolve_root · sdd/cli._root · cli/toolkits · self_/cli doctor
      └──────────── all call launcher.install_root(); write verbs add require_primary_checkout()
doctor: repo: checkout (fails when linked) · host config: form (informational)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.launcher.repository_paths` (`launcher.py:58`) | uses | `install_root()` reuses its walk and the `commondir` resolution; no new git subprocess. |
| `parrot.launcher.parrot_home` (`launcher.py:24`) | uses | `managed_launcher_on_path()` compares `shutil.which("parrot")` against `parrot_home()` exactly as `guard_hook_command()` does today (`sdd/installer.py:290-297`). |
| `sdd/installer.guard_hook_command` (`:280`) | refactors | tri-state parameter; body calls `managed_launcher_on_path()`; return values and the `note: guard hook baked …` line are unchanged. |
| `claude_code/installer._current_portable_mode` (`:139`), `codex/installer._current_portable_mode` (`:188`), `google/installer._current_portable_mode` (`:75`) | modifies | return `None` when no managed entry / block exists (today `False`). |
| `claude_code/installer.reconcile_toolkit_entries` (`:705`), `codex/installer.reconcile_toolkit_tables` (`:263`), `google/installer.reconcile_toolkit_entries` (`:220`) | modifies | the `portable is None` branch goes through `resolve_portable_mode`; the baked note is appended to `actions`. |
| `install_claude_integration` (`:1216`), `install_codex_integration` (`:420`), `install_google_integration` (`:380`) and their CLI callers | modifies | same rule; load configuration, resolve remote settings and build the wiki at `InstallRoot.shared_root`; host assets target `root`. |
| `mcp/hosts.HostAdapter.reconcile` (`:51`) + three adapters (`:95,:167,:219`) | extends | keyword `portable: bool | None = None`, forwarded. |
| `mcp/toolkit_install.install_toolkits` (`:158`), `set_toolkits_enabled` (`:222`), `_reconcile_all` (`:145`) | extends | keyword `portable` threaded to `adapter.reconcile`. |
| `sdd/installer._install_toolkits_step` (`:1227`) and its call (`:1152`) | modifies | forward `portable` verbatim, preserving explicit `False`. |
| `knowledge/wiki/project.find_shared_root` (`:1560`) | reference | existing shared-plane resolver remains unchanged; installers use the classified `InstallRoot.shared_root` so external gitdirs are not mistaken for worktrees. |
| `self_/doctor.run_doctor` (`:664`), `_check_host_configs` (`:590`) | extends | new `repo: checkout` check (non-runtime scopes) and `host config: form` informational check. |
| `docs/install/global-runtime.md:182-205` | docs | "The default stays baked" paragraph rewritten; worktree refusal documented. |
| `knowledge/wiki/{claude_code,codex,google}/bookstore_assets.py` ("If MCP is disconnected, run `parrot … install --no-build` in the target repository") | docs | add "from the primary checkout (or pass `--path`)". |

### Data Models
```python
# parrot/launcher.py  (stdlib only)
@dataclasses.dataclass(frozen=True)
class InstallRoot:
    root: Path          # resolved checkout the command targets (explicit path or nearest .git holder, else cwd)
    shared_root: Path   # primary checkout: common_git_dir.parent for a linked worktree, else == root
    linked: bool        # root is a linked worktree (its .git is a file whose gitdir has a commondir)
    explicit: bool      # root came from --path / --project / an environment pin

class LinkedWorktreeError(RuntimeError):
    """Raised by require_primary_checkout(); message names shared_root and the --path escape hatch."""

# parrot/mcp/portability.py
PortableReason = Literal["explicit", "sticky", "launcher", "baked-fallback"]

@dataclasses.dataclass(frozen=True)
class PortableDecision:
    portable: bool
    reason: PortableReason
    note: str | None    # "note: host config baked to absolute paths (<sys.prefix>); install the global launcher
                        #  (install-parrot.sh --global) and re-run with --portable to commit a machine-independent
                        #  config" — only for baked-fallback
```

### New Public Interfaces
```python
# parrot/launcher.py
def managed_launcher_on_path(env: Mapping[str, str] | None = None) -> bool: ...
def explicit_project_pin(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None: ...
def install_root(cwd: Path, *, explicit: Path | None = None) -> InstallRoot: ...
def require_primary_checkout(resolved: InstallRoot) -> InstallRoot: ...

# parrot/mcp/portability.py
def resolve_portable_mode(explicit: bool | None, *, current: bool | None) -> PortableDecision: ...

# CLI
parrot toolkits install <names> [--path DIRECTORY] [--portable | --no-portable]
parrot toolkits enable  <names> [--path DIRECTORY] [--portable | --no-portable]
parrot toolkits uninstall|disable <names> [--path DIRECTORY]
parrot self doctor   → new checks "repo: checkout" (fails in a linked worktree) and "host config: form"
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: launcher resolvers | yes | dataclass + four functions fixed below; stdlib-only; reuse `repository_paths`; error text fixed | — |
| M2: portable rule + tri-state inference | yes | `resolve_portable_mode` truth table fixed below; six call sites listed; note text fixed | — |
| M3: toolkit forwarding | yes | keyword threading only; tri-state forwarded verbatim | — |
| M4: install-root adoption in CLIs + wiki config at shared root | yes | per-file list of call sites; write/read verb split fixed | — |
| M5: doctor checks | yes | check names, `ok`/`informational`/`fix` semantics fixed | — |
| M6: docs + bookstore skill wording | yes | prose only | — |

### Module 1: Launcher resolvers
- **Path**: `packages/ai-parrot/src/parrot/launcher.py` (modify)
- **Responsibility**: `InstallRoot`, `LinkedWorktreeError`, `managed_launcher_on_path()`, `explicit_project_pin()`, `install_root()`,
  `require_primary_checkout()`. Stdlib imports only (`dataclasses`, `shutil` are allowed).
- **Depends on**: existing `repository_paths` (`launcher.py:58`), `parrot_home` (`:24`), `_existing_directory` (`:49`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/launcher.py  (modifies parrot/launcher.py — new symbols after repository_paths, :84)
  @dataclasses.dataclass(frozen=True)
  class InstallRoot:
      """Where an installer-type command writes; see §2 Data Models for the field semantics."""
      root: Path
      shared_root: Path
      linked: bool
      explicit: bool

  class LinkedWorktreeError(RuntimeError):
      """``root`` is a linked worktree and no explicit path was given."""

  def managed_launcher_on_path(env: Mapping[str, str] | None = None) -> bool:
      """True when ``shutil.which("parrot")`` (as found or resolved) lies under ``parrot_home(env)`` (as given or
      resolved) — the test inlined today in guard_hook_command (sdd/installer.py:290-297). Never raises."""

  def install_root(cwd: Path, *, explicit: Path | None = None) -> InstallRoot:
      """Resolve the checkout an installer targets.

      ``explicit`` (``--path``/``--project``/an env pin) is returned verbatim after ``_existing_directory``
      and ``explicit=True``; it is still classified (linked/shared_root) through ``repository_paths``.
      Otherwise ``repository_paths(cwd)`` (launcher.py:58) supplies the discovered checkout and common
      gitdir. Classify the discovered checkout even when the explicit target is a subdirectory.
      Inspect its .git marker and the referenced gitdir before commondir resolution: only a valid
      commondir file resolving to an existing common gitdir establishes linked=True. A gitdir outside
      root/.git without commondir is not linked (submodules and --separate-git-dir checkouts).
      For linked checkouts, shared_root=common.parent; otherwise shared_root=root, preserving the
      explicit target. No .git found without an explicit target → InstallRoot(cwd, cwd, False, False);
      an explicit non-repository directory yields InstallRoot(target, target, False, True).
      Malformed/unreadable .git
      or commondir metadata never raises and must not manufacture a linked classification."""

  def explicit_project_pin(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:
      """Return only a valid explicit project pin, never a discovered repository.

      Preserve find_project_root's pin precedence and validation: leading --project/--project=,
      PARROT_PROJECT, then CLAUDE_PROJECT_DIR; expand user paths, resolve relative to cwd and accept
      existing directories. Return None when no valid pin exists. Extract this logic from the
      existing launcher find_project_root, which delegates here before its unchanged .git walk.
      The launcher resolver's existing public behavior remains unchanged."""

  def require_primary_checkout(resolved: InstallRoot) -> InstallRoot:
      """Return ``resolved`` unchanged unless ``resolved.linked and not resolved.explicit``, in which case
      raise LinkedWorktreeError(f"{resolved.root} is a linked worktree of {resolved.shared_root}; installers
      write to the checkout you run them in — run this from {resolved.shared_root}, or pass --path
      {resolved.root} to install into the worktree on purpose")."""
  ```

### Module 2: Portable rule and tri-state inference
- **Path**: `packages/ai-parrot/src/parrot/mcp/portability.py` (create); `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py`, `packages/ai-parrot/src/parrot/sdd/installer.py` (modify)
- **Responsibility**: the single decision function; the three `_current_portable_mode()` return `None` when
  no managed entry/block exists; the six `portable is None` sites use the decision and surface `note`;
  `guard_hook_command()` delegates the PATH test to M1.
- **Depends on**: M1 (`managed_launcher_on_path`).
- **Interface Skeleton**:
  ```python
  # parrot/mcp/portability.py  (new)
  PortableReason = Literal["explicit", "sticky", "launcher", "baked-fallback"]

  @dataclasses.dataclass(frozen=True)
  class PortableDecision:
      portable: bool
      reason: PortableReason
      note: str | None

  BAKED_NOTE_TEMPLATE: str = (
      "note: host config baked to absolute paths ({prefix}); install the global launcher "
      "(install-parrot.sh --global) and re-run with --portable to commit a machine-independent config"
  )

  def resolve_portable_mode(explicit: bool | None, *, current: bool | None) -> PortableDecision:
      """Truth table, first match wins:
      explicit is not None            → (explicit, "explicit", None)
      current  is not None            → (current,  "sticky",   None)          # FEAT-633 stickiness
      managed_launcher_on_path()      → (True,     "launcher", None)          # verified: launcher (M1)
      otherwise                       → (False,    "baked-fallback", BAKED_NOTE_TEMPLATE.format(prefix=sys.prefix))"""

  # parrot/knowledge/wiki/claude_code/installer.py  (modifies :139 and the sites at :736, :1280)
  def _current_portable_mode(root: Path) -> bool | None:
      """As today, except: no ``.mcp.json``, unparsable JSON, no ``mcpServers`` mapping, or no managed
      ``wikitoolkit``/``parrot-*`` entry → ``None`` (today: False). A managed entry present → bool as today."""
  # at :736 (reconcile_toolkit_entries) and :1280 (install_claude_integration):
  #   decision = resolve_portable_mode(portable, current=_current_portable_mode(root)); portable = decision.portable
  #   if decision.note: actions.append(decision.note)        # once per install / reconcile call

  # parrot/knowledge/wiki/codex/installer.py  (modifies :188 and the sites at :294, :453)
  def _current_portable_mode(root: Path) -> bool | None:
      """``None`` when config.toml is absent/unreadable or carries no managed block (assets.MCP_BEGIN,
      codex/assets.py:19) or the block has neither a stdio wikitoolkit table nor parrot-* tables."""

  # parrot/knowledge/wiki/google/installer.py  (modifies :75 and the sites at :245, :404)
  def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool | None:
      """``None`` when neither the plugin file nor the user-global file holds a ``wikitoolkit`` entry."""

  # parrot/sdd/installer.py  (modifies guard_hook_command :280-300)
  def guard_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:
      """``True`` → bare; ``False`` → baked ``sys.prefix`` parrot script (shlex-quoted) even with the launcher on
      PATH; ``None`` → bare iff managed_launcher_on_path() else baked (today's ``False`` behaviour). The inline
      which/parrot_home comparison is deleted. Same return values and note text as today."""

  def dangerous_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:   # modifies :308
      """Same tri-state, derived from guard_hook_command as today."""

  def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:   # modifies :338
      """Unchanged apart from the parameter type."""

  def install_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False, portable: bool | None = None, base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True, sdd_coder=True) -> list[str]:   # modifies :1064-1074
      """``portable`` is the CLI tri-state; passed verbatim to guard_hook_command, _install_dangerous_guard and
      _install_toolkits_step (M3)."""
  # sdd_status :1568 — `guard_hook_command(portable=False)` becomes `guard_hook_command(portable=None)`.
  ```

### Module 3: Forward the decision into toolkit registration
- **Path**: `packages/ai-parrot/src/parrot/mcp/hosts.py`, `packages/ai-parrot/src/parrot/mcp/toolkit_install.py`, `packages/ai-parrot/src/parrot/sdd/installer.py`, `packages/ai-parrot/src/parrot/sdd/cli.py`, `packages/ai-parrot/src/parrot/cli/toolkits.py` (modify)
- **Responsibility**: `portable` travels from the CLIs to the three reconcilers; nothing else changes.
- **Depends on**: M2 (the reconcilers' `None` branch is what makes the fresh-repo case correct).
- **Interface Skeleton**:
  ```python
  # parrot/mcp/hosts.py  (modifies :51 protocol, :95 Claude, :167 Codex, :219 Google)
  class HostAdapter(Protocol):
      def reconcile(self, root: Path, *, portable: bool | None = None) -> tuple[list[str], list[str]]:
          """Rewrite ONLY this host's parrot-<name> entries; ``portable`` is forwarded verbatim to the host
          reconciler (None = sticky, then launcher rule — M2)."""
  # ClaudeAdapter.reconcile → reconcile_toolkit_entries(root, portable=portable)          # verified: claude_code/installer.py:705
  # CodexAdapter.reconcile  → reconcile_toolkit_tables(root, portable=portable)           # verified: codex/installer.py:263
  # GoogleAdapter.reconcile → reconcile_toolkit_entries(root, self._mcp_path, portable=portable)  # verified: google/installer.py:220

  # parrot/mcp/toolkit_install.py  (modifies :145, :158, :222)
  def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport, *, portable: bool | None = None) -> None: ...
  def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind], *, portable: bool | None = None) -> ActionReport:
      """As today; ``portable`` reaches every adapter.reconcile. uninstall_toolkits is unchanged."""
  def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind], *, portable: bool | None = None) -> ActionReport: ...

  # parrot/sdd/installer.py  (modifies :1227 and the call at :1152)
  def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
      """Calls install_toolkits(root, list(SDD_TOOLKITS), _toolkit_hosts(hosts), portable=portable)."""
  # call site: _install_toolkits_step(root, hosts, receipt, portable=portable)

  # parrot/sdd/cli.py  (modifies the option at :76-83)
  # @click.option("--portable/--no-portable", "portable", default=None, help="Bare launcher commands (portable) or
  #   baked absolute paths for the guard hook, the dangerous guard and the toolkit entries; default keeps each
  #   host's current form and, on a fresh host, follows the managed launcher.")

  # parrot/cli/toolkits.py  (modifies install :180 and enable)
  # @click.option("--portable/--no-portable", default=None, help="Emit bare launcher commands (portable) or baked
  #   absolute paths; default keeps the host's current form, and on a fresh host follows the managed launcher.")
  ```

### Module 4: One install root for every installer CLI; wiki config at the shared root
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py`, `packages/ai-parrot/src/parrot/sdd/cli.py`, `packages/ai-parrot/src/parrot/cli/toolkits.py`, `packages/ai-parrot/src/parrot/self_/cli.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (modify)
- **Responsibility**: every root resolution goes through `install_root()`; write verbs add
  `require_primary_checkout()` and turn `LinkedWorktreeError` into `click.ClickException` (exit 1);
  read verbs (`status`, `list`) only resolve. Host CLIs and installers read/write `.parrot/wiki.json`
  at `InstallRoot.shared_root` and use that same root for remote lookup and initial builds.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/claude_code/cli.py  (modifies _resolve_root :36-46; import at :28 drops find_project_root)
  def _resolve_root(path: Optional[str], *, write: bool = True) -> Path:
      """install_root(Path.cwd(), explicit=Path(path) if path else None); write → require_primary_checkout;
      LinkedWorktreeError → click.ClickException(str(exc)). A non-directory --path aborts as today.
      install/uninstall: write=True · status: write=False · hook: unchanged (it takes no root)."""
  # codex/cli.py :25-34 and google/cli.py :25-34: identical helper, identical verb split.

  # parrot/sdd/cli.py  (modifies _root :48-53)
  def _root(path_: Path | None, *, write: bool = True) -> Path:
      """Same contract; install/uninstall write=True, status write=False."""

  # parrot/cli/toolkits.py  (replaces the seven Path.cwd() at :98,:126,:164,:184,:224,:249,:271)
  def _root(path_: Path | None = None, *, write: bool) -> Path:
      """Resolve install_root(Path.cwd(), explicit=path_); write=True applies require_primary_checkout.
      install/uninstall/enable/disable use write=True; list/status use write=False.
      LinkedWorktreeError becomes click.ClickException; _warn_user_global receives the resolved root."""
  # Add --path to each of install/uninstall/enable/disable:
  # @click.option("--path", "path_", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
  # Each callback accepts path_: Path | None and obtains root = _root(path_, write=True) before any
  # selection, confirmation, config loading or writes. Missing --path keeps discovery/refusal behavior.
  # Read-only list/status call _root(write=False); no path option is required for these verbs.

  # parrot/self_/cli.py  (modifies doctor :72)
  # pin = explicit_project_pin(sys.argv[1:], os.environ, Path.cwd())
  # resolved = install_root(Path.cwd(), explicit=pin)
  # checks = run_doctor(resolved.root, scope=scope, install_root=resolved)     # M5
  # Never use find_project_root's discovered fallback as the explicit argument.

  # All three host CLI install callbacks (claude_code/cli.py:172; codex/cli.py:106; google/cli.py:79):
  #   root = _resolve_root(path_)                          # install target, refusal already enforced
  #   state_root = install_root(root, explicit=root).shared_root
  #   config = load_effective_config(state_root).config
  #   remote lookup uses this config; pass this config to the library installer, never one loaded at root.
  #   config.is_built(state_root) and wiki_build(path_=str(state_root)) use the same shared state root.
  # Apply this to every default first-build path; --no-build still suppresses building.
  # Host config/status reads of wiki state also use state_root; host asset/status paths still use root.
  #
  # Host library installers (claude_code/installer.py:1216ff; codex:420ff; google:380ff):
  #   state_root = install_root(root, explicit=root).shared_root
  #   config = config or load_effective_config(state_root).config; existed = config_path(state_root).exists()
  #   save_project_config(state_root, config)                 # tracked assets still go to `root`
  # An explicitly supplied config remains a deliberate library override. CLI callers must supply
  # shared-root configuration so worktree defaults cannot overwrite existing primary settings.
  ```

### Module 5: Doctor checks
- **Path**: `packages/ai-parrot/src/parrot/self_/doctor.py` (modify)
- **Responsibility**: `repo: checkout` (fails in a linked worktree without a pin) and `host config: form`
  (informational — owner decision 2026-11-04: baked is a valid single-machine state, doctor never fails on it).
- **Depends on**: M1 (`InstallRoot`), M2 (`_current_portable_mode` tri-state for the form).
- **Interface Skeleton**:
  ```python
  # parrot/self_/doctor.py  (modifies run_doctor :664-679; adds two helpers next to _check_host_configs :590)
  def run_doctor(root: Path, *, scope: DoctorScope = "full", install_root: InstallRoot | None = None) -> list[DoctorCheck]:
      """As today; when ``scope != "runtime-only"`` and ``install_root`` is given, ``_check_checkout(install_root)``
      runs first after the runtime checks."""

  def _check_checkout(resolved: InstallRoot) -> DoctorCheck:
      """name="repo: checkout". ok=True detail=f"{root} (primary checkout)" when not linked;
      linked and explicit → ok=True, detail=f"{root} (explicitly selected linked worktree of {shared_root})";
      otherwise ok=False, detail=f"{root} is a linked worktree of {shared_root}", fix=f"run doctor and the
      installers from {shared_root}, or pass --project {root}"."""

  def _check_host_config_forms(root: Path) -> list[DoctorCheck]:
      """One informational check per present host config: name=f"host config: {label} form", ok=True,
      informational=True, detail="portable" | f"baked absolute paths" | "no managed entries" (tri-state from
      the three _current_portable_mode helpers), fix="" | "multi-machine repos: re-install with --portable".
      Appended by _check_host_configs."""
  ```

### Module 6: Docs and shipped guidance
- **Path**: `docs/install/global-runtime.md` (modify, `:182-205`); `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` (modify, the "If MCP is disconnected" line)
- **Responsibility**: document the new default rule, stickiness, the baked note, the worktree refusal and
  `--path`; the bookstore skill tells agents to run the host installer from the primary checkout.
- **Depends on**: M2, M4 (names only).
- **Interface Skeleton**: prose only — the `<!-- verify: flag=… -->` markers in `global-runtime.md:184-186`
  stay, and two are added for `toolkits install:--portable` and `toolkits enable:--portable`.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_install_root_plain_repo_and_subdirectory` | M1 | `install_root(repo/sub/dir)` → `root=repo`, `shared_root=repo`, `linked=False`; no `.git` anywhere → `root=cwd`, `linked=False` |
| `test_install_root_linked_worktree` | M1 | with `linked_worktree_repo` (`tests/launcher/test_launcher_core.py:26`): `root=wt`, `shared_root=main`, `linked=True`; `require_primary_checkout` raises `LinkedWorktreeError` naming both paths; with `explicit=wt` it returns |
| `test_install_root_external_gitdir_is_not_linked` | M1 | real submodule and `git init --separate-git-dir` fixtures: gitdir has no commondir; `linked=False`, `shared_root=root`; installers are not refused and wiki state remains in the checkout |
| `test_install_root_explicit_subdir_and_malformed_metadata` | M1 | explicit subdirectory preserves its target while classification uses its containing checkout; malformed/unreadable .git or commondir never raises or produces a false linked classification |
| `test_explicit_project_pin_provenance` | M1 | no flags/env pins returns None even inside a repository; CLI/env precedence, relative paths and invalid-directory fallback match existing launcher behavior; find_project_root still discovers the repository |
| `test_install_root_stops_at_temp_root` | M1 | a stray `/tmp/.git` never becomes a root (`_is_temp_root`, `launcher.py:37`) |
| `test_managed_launcher_on_path` | M1 | `which` under `parrot_home` (direct and via symlink) → True; elsewhere/absent → False |
| `test_launcher_stdlib_only` (existing, `tests/launcher/test_launcher_stdlib_only.py`) | M1 | still passes with `dataclasses`/`shutil` imported |
| `test_resolve_portable_mode_truth_table` | M2 | the four rows of §3 M2, including the note text containing `sys.prefix` |
| `test_current_portable_mode_tri_state` (×3 hosts; extends `test_portable_mode_parity.py`) | M2 | no file / no managed entry → `None`; baked entry → `False`; portable entry → `True` |
| `test_no_config_follows_launcher_rule` (replaces `test_no_config_is_baked`, `test_portable_mode_parity.py:118`) | M2 | fresh repo: launcher on PATH → portable entries; absent → baked entries + the note line |
| `test_default_install_unchanged` (`test_claude_installer_portable.py:48`), `test_default_emission_unchanged` (`test_codex_portable.py:57`, `test_google_portable.py:78`) | M2 | updated to pin `managed_launcher_on_path → False`; baked output unchanged |
| `test_guard_hook_bare_when_managed_launcher_on_path` / `_baked_when_launcher_absent` (`tests/sdd/test_installer.py:353,370`) | M2 | call `guard_hook_command(portable=None)` (was `False`); same expectations |
| `test_guard_hook_no_portable_forces_baked` | M2 | `guard_hook_command(portable=False)` → baked even with the launcher on PATH; `install_sdd_integration(repo, portable=False)` bakes the guard hook, the dangerous guard and the toolkit entries |
| `test_reconcile_forwards_portable` | M3 | `install_toolkits(..., portable=True)` on a fresh repo → relative `--config`, bare command, no `cwd` for every host; `portable=None` keeps a baked `.mcp.json` baked |
| `test_sdd_install_portable_reaches_toolkits` (extends `tests/sdd/test_installer_toolkits.py`) | M3 | fresh repo + `--portable` → both `parrot-*` entries portable; without the flag and launcher absent → baked + note |
| `test_cli_flag_and_dry_run` (`tests/sdd/test_installer_toolkits.py:121`) | M3 | extended: `--portable` and `--no-portable` accepted; `--dry-run` still writes nothing |
| `test_toolkits_cli_portable_flag` (extends `tests/cli/test_toolkits_cli.py`) | M3 | `--portable` / `--no-portable` accepted by install and enable |
| `test_host_cli_refuses_linked_worktree` (×3 host CLIs) | M4 | `install` from a worktree cwd → exit 1, message names the primary checkout and `--path`; `--path <wt>` proceeds; `status` from the worktree works |
| `test_sdd_cli_refuses_linked_worktree_and_resolves_subdir` (extends `tests/sdd/test_sdd_cli.py`) | M4 | `sdd install` in a worktree → exit 1; in `repo/sub` → installs into `repo` |
| `test_toolkits_cli_resolves_repo_root` | M4 | `toolkits install` from a subdirectory seeds `<repo>/.parrot/mcp-toolkits.yaml`; `list` in a non-git dir still works (`test_list_on_empty_repo` unchanged) |
| `test_toolkits_cli_worktree_path_override` | M4 | parameterize install/uninstall/enable/disable: no --path from a linked worktree exits 1 before prompts/writes; --path wt proceeds on wt; invalid paths fail validation; list/status never refuse |
| `test_host_install_keeps_wiki_config_on_primary_checkout` | M4 | all three library installers at wt_root preserve existing non-default primary wiki settings and create no wt/.parrot/wiki.json; `find_project_root(wt)` (wiki) still returns main |
| `test_host_cli_worktree_preserves_shared_config_and_build_root` | M4 | all three CLIs with --path wt and no local wiki.json: primary wiki name/backend/settings are preserved, config loading and build checks/build invocation target main, no worktree wiki plane is created; --no-build skips builds; Claude/Codex --remote reuse primary remote settings without --remote-url |
| `test_doctor_repo_checkout` (extends `tests/self_/test_doctor_sdd.py`) | M5 | linked worktree without pin → failing `repo: checkout` with fix; primary checkout / explicit pin → ok |
| `test_doctor_cli_pin_provenance` | M5 | invoke doctor from worktree cwd with argv/env pins absent: repo: checkout fails; genuine --project/PARROT_PROJECT/CLAUDE_PROJECT_DIR pins pass and retain linked classification; --runtime-only omits checkout check |
| `test_doctor_host_config_form` (extends `tests/self_/test_doctor.py`) | M5 | baked `.mcp.json` → informational `host config: claude .mcp.json form` with the `--portable` hint; portable → `portable`; never fails doctor |

### Integration Tests
| Test | Description |
|---|---|
| `test_fresh_repo_end_to_end_portable` | temp repo, launcher on PATH (fake `~/.parrot/bin/parrot`): `parrot claude install` then `parrot sdd install` → no absolute path in `.mcp.json`, `.claude/settings.json`, agents' guard hook; `doctor` reports `portable` |
| `test_fresh_repo_end_to_end_baked_with_note` | same with no launcher: baked entries, the note appears once in each installer's output, `doctor` form check is informational |

### Validation Contract

tests:
- packages/ai-parrot/tests/launcher/test_launcher_core.py
- packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py
- packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py
- packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py
- packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py
- packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py
- packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py
- packages/ai-parrot/tests/mcp/test_toolkit_install.py
- packages/ai-parrot/tests/mcp/test_hosts.py
- packages/ai-parrot/tests/cli/test_toolkits_cli.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/sdd/test_installer_toolkits.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/self_/test_doctor.py
- packages/ai-parrot/tests/self_/test_doctor_sdd.py
markers: none

### Test Data / Fixtures
```python
# Reuse: linked_worktree_repo / make_venv (tests/launcher/test_launcher_core.py:11,26) — move them to
# tests/launcher/conftest.py so M4/M5 tests can import them; empty_repo (tests/sdd/test_installer.py:31);
# repo (tests/sdd/test_installer_toolkits.py:21).
@pytest.fixture
def managed_launcher(tmp_path, monkeypatch):
    """A fake ~/.parrot/bin/parrot on PATH so managed_launcher_on_path() is True."""
    home = tmp_path / "home"; (home / "bin").mkdir(parents=True)
    script = home / "bin" / "parrot"; script.write_text("#!/bin/sh\n"); script.chmod(0o755)
    monkeypatch.setenv("PARROT_HOME", str(home)); monkeypatch.setenv("PATH", f"{home / 'bin'}:{os.environ['PATH']}")
    return script
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 `parrot.launcher` still imports only the stdlib (`test_launcher_stdlib_only`), and exposes `InstallRoot`, `LinkedWorktreeError`, `managed_launcher_on_path`, `explicit_project_pin`, `install_root`, `require_primary_checkout`; extracting pin resolution preserves existing `find_project_root` behavior.
- [ ] AC2 Without an explicit target, `install_root()` returns the same `root` for a repository root and any of its subdirectories; a linked worktree with valid commondir metadata yields `linked=True` and `shared_root` = the primary checkout; a directory outside any repository yields itself. Submodules and separate-git-dir checkouts without commondir yield `linked=False`, `shared_root=root`, and are not refused. An explicit subdirectory remains the target while classification uses its containing checkout.
- [ ] AC3 On a fresh repository (no host config) with the managed launcher on `PATH`, `parrot claude|codex|google install`, `parrot sdd install` and `parrot toolkits install` write no absolute path into `.mcp.json`, `.codex/config.toml`, the Google configs, `.claude/settings.json` or the agents' guard hook — without any `--portable` flag.
- [ ] AC4 On a fresh repository with no managed launcher, the same commands write the baked form and each prints exactly one `note: host config baked to absolute paths (…)` line naming the fix; `guard hook baked` keeps its own existing note.
- [ ] AC5 A repository whose host config is already baked stays baked on a plain re-install even with the launcher on `PATH` (sticky), and migrates with an explicit `--portable`; a portable one stays portable; `--no-portable` migrates it back (existing transition tests keep passing).
- [ ] AC6 `parrot sdd install --portable` on a fresh repository produces portable `parrot-sdd-coder` / `parrot-bounded-source` entries for every selected host; `parrot sdd install --no-portable` writes the baked form for the guard hook, the dangerous guard and the toolkit entries even with the launcher on `PATH`; `parrot toolkits install|enable --portable/--no-portable` are accepted and honoured.
- [ ] AC7 Run from inside a linked worktree without `--path`, `parrot claude|codex|google install|uninstall`, `parrot sdd install|uninstall` and `parrot toolkits install|uninstall|enable|disable` write nothing, exit 1 and name the primary checkout and the `--path` escape hatch; with `--path <worktree>` they proceed; `status`/`list` verbs never refuse.
- [ ] AC8 Each host CLI and library installer pointed at a linked worktree preserves existing non-default primary wiki settings, loads configuration and remote settings from the primary checkout, and writes `.parrot/wiki.json` only there. Initial build checks and builds target that same primary checkout; `--no-build` suppresses builds. Host assets remain at the explicit install target, no worktree wiki plane is created, and `wikitoolkit`'s `find_project_root()` from the worktree still resolves the primary checkout.
- [ ] AC9 `parrot self doctor` inside a linked worktree (no `--project`/pin) fails with `repo: checkout` and a fix naming the primary checkout, verified through the CLI with argv/env pins absent. Only a genuine valid CLI/environment pin sets `explicit=True`; with a pin or from the primary checkout the check passes; `--runtime-only` never runs it.
- [ ] AC10 `parrot self doctor` reports one informational `host config: <label> form` check per present host config (`portable` / `baked absolute paths` / `no managed entries`); it never changes doctor's exit code.
- [ ] AC11 `guard_hook_command(portable=None)` and `guard_hook_command(portable=True)` return byte-identical outputs to today's `False`/`True` for the same `PATH`/`PARROT_HOME`; `portable=False` now forces the baked form (`tests/sdd/test_installer.py:353-407` pass after replacing `portable=False` with `portable=None` in the two auto-rule tests).
- [ ] AC12 `docs/install/global-runtime.md` no longer says "The default stays baked absolute paths"; it documents the launcher rule, stickiness, the note, the worktree refusal and `--path`; the three bookstore skill assets tell agents to run the host installer from the primary checkout or pass `--path`.
- [ ] AC13 Every file in the Validation Contract passes with `PYTHONPATH=packages/ai-parrot/src`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `bc9bb3ead6` (dev, 2026-11-04). Paths below are relative to `packages/ai-parrot/src/`.

### Verified Imports
```python
from parrot.launcher import parrot_home, script_path                  # verified: parrot/launcher.py:24,118 (sdd/installer.py:32 imports both)
from parrot.launcher import repository_paths, find_project_root       # verified: parrot/launcher.py:58,87
from parrot.knowledge.wiki.project import find_project_root            # verified: parrot/knowledge/wiki/project.py:1049 (wiki-plane resolver — NOT for installers)
from parrot.knowledge.wiki.project import find_shared_root             # verified: parrot/knowledge/wiki/project.py:1560
from parrot.knowledge.wiki.project import WikiConfigError, load_effective_config, config_path, save_project_config  # verified: project.py:1077,1106 and the wiki CLIs (codex/cli.py:15)
from parrot.mcp.hosts import HostKind, HostAdapter, get_adapter        # verified: parrot/mcp/hosts.py:18,37,228
from parrot.mcp.toolkit_install import install_toolkits, uninstall_toolkits, set_toolkits_enabled, ActionReport  # verified: toolkit_install.py:158,187,222,55
from parrot.knowledge.wiki.claude_code.installer import reconcile_toolkit_entries, _current_portable_mode, install_claude_integration  # verified: :705,:139,:1216
from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables, _current_portable_mode, install_codex_integration          # verified: :263,:188,:420
from parrot.knowledge.wiki.google.installer import reconcile_toolkit_entries, _current_portable_mode, install_google_integration, toolkit_config_paths  # verified: :220,:75,:380,:206
from parrot.sdd.installer import guard_hook_command, dangerous_hook_command, install_sdd_integration, _install_toolkits_step, SDD_TOOLKITS  # verified: :280,:308,:1064,:1227,:42
from parrot.self_.doctor import DoctorCheck, run_doctor, _check_host_configs, DoctorScope  # verified: :40,:664,:590,:29
```

### Existing Class Signatures
```python
# parrot/launcher.py
def parrot_home(env: Mapping[str, str] | None = None) -> Path                                  # :24
def is_managed(prefix: str | None = None, *, env: Mapping[str, str] | None = None) -> bool      # :30
def _is_temp_root(candidate: Path) -> bool                                                     # :37
def _existing_directory(path: Path) -> Path                                                    # :49
def repository_paths(cwd: Path) -> tuple[Path, Path | None]                                    # :58  (repo_root, common_git_dir|None); linked → common != root/.git
def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None   # :87  --project / PARROT_PROJECT / CLAUDE_PROJECT_DIR / nearest .git

# parrot/sdd/installer.py
GUARD_HOOK_LINE = "parrot sdd worktree guard --hook || exit 2"                                 # :70
def _under(path: Path, base: Path) -> bool                                                     # :275
def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]              # :280  (which("parrot") under parrot_home → bare; else baked sys.prefix script)
def dangerous_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]          # :308
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool) -> list[str]  # :338
def install_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False, portable=False, base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True, sdd_coder=True) -> list[str]  # :1064
#   hook, form = guard_hook_command(portable=portable)                                         # :1119
#   actions.extend(_install_toolkits_step(root, hosts, receipt))                               # :1152
def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any]) -> list[str]  # :1227  → install_toolkits(root, list(SDD_TOOLKITS), _toolkit_hosts(hosts))

# parrot/sdd/cli.py
def _root(path_: Path | None) -> Path                                                          # :48  (path_ or Path.cwd()).resolve(); no walk
@click.option("--portable", is_flag=True, ...)                                                 # :77  (sdd install)

# parrot/mcp/hosts.py
class HostAdapter(Protocol):  def reconcile(self, root: Path) -> tuple[list[str], list[str]]   # :37, :51
class ClaudeAdapter:  def reconcile(self, root)  → reconcile_toolkit_entries(root)             # :58, :95
class CodexAdapter:   def reconcile(self, root)  → reconcile_toolkit_tables(root)              # :120, :167
class GoogleAdapter:  def __init__(self, mcp_path=None); def reconcile(self, root) → reconcile_toolkit_entries(root, self._mcp_path)  # :176, :181, :219

# parrot/mcp/toolkit_install.py
class ActionReport(BaseModel): actions: list[str]; warnings: list[str]; failed_hosts: dict[HostKind, str]  # :55
def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None       # :145  (adapter.reconcile(root) at :150)
def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport  # :158
def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport  # :187
def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport  # :222

# parrot/cli/toolkits.py — root = Path.cwd() at :126 (list), :164 (status), :184 (install), :224, :249, :271; config_paths(Path.cwd()) at :98
@toolkits.command() def install(names, hosts_, yes)                                            # :180

# parrot/knowledge/wiki/claude_code/installer.py
def _managed_toolkit_entries(servers: dict[str, Any], root: Path) -> list[Any]                 # :122
def _portable_from_servers(servers: dict[str, Any], root: Path) -> bool                        # :130
def _current_portable_mode(root: Path) -> bool                                                 # :139  (missing/unparsable → False)
def reconcile_toolkit_entries(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]  # :705  (if portable is None: :736)
def _install_mcp_json(root: Path, *, remote=None, portable: bool = False) -> str               # :790
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True, approve_mcp=True, compaction=False, typesafe_api_key=None, plugin_cli=True, remote=None, portable: Optional[bool] = None) -> list[str]  # :1216  (save_project_config(root, config) then `if portable is None:` :1280)

# parrot/knowledge/wiki/codex/installer.py
def _has_toolkit_tables(block_body: Optional[str]) -> bool                                     # :177
def _current_portable_mode(root: Path) -> bool                                                 # :188
def reconcile_toolkit_tables(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]  # :263  (if portable is None: :294)
def install_codex_integration(root, config=None, gitignore=True, bookstore=True, remote=None, portable: Optional[bool] = None) -> list[str]  # :420  (if portable is None: :453)
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"                                                  # codex/assets.py:19

# parrot/knowledge/wiki/google/installer.py
def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool                # :75
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]      # :206
def reconcile_toolkit_entries(root: Path, mcp_path: Optional[Path] = None, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]  # :220  (if portable is None: :245)
def install_google_integration(root, config=None, gitignore=True, bookstore=True, mcp_config_path=None, portable: Optional[bool] = None) -> list[str]  # :380  (if portable is None: :404)
PLUGIN_DIR = Path(".agents/plugins/parrot")                                                    # google/assets.py:21

# parrot/knowledge/wiki/{claude_code,codex,google}/cli.py
def _resolve_root(path: Optional[str]) -> Path                                                 # claude_code:36, codex:25, google:25 — found = find_project_root() (wiki)
# commands: claude install:140 uninstall:255 status:276 hook:311 · codex install:92 uninstall:156 status:181 · google install:69 uninstall:105 status:119

# parrot/knowledge/wiki/project.py
def find_project_root(start: Path | None = None) -> Path | None                                # :1049  nearest .parrot/wiki.json upward, else nearest .git
def find_shared_root(start: Path | None = None) -> Path | None                                 # :1560  nearest .git, then common_dir.parent (primary checkout)
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig           # project.py (used by the host CLIs/installers)

# parrot/self_/doctor.py
class DoctorCheck(BaseModel): name: str; ok: bool; detail: str = ""; fix: str = ""; informational: bool = False  # :40
def _check_host_configs(root: Path) -> list[DoctorCheck]                                      # :590
def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]                # :664  (checks.extend(_check_host_configs(root)) :675)
# parrot/self_/cli.py: root = find_project_root(sys.argv[1:], os.environ, Path.cwd()) or Path.cwd()   # :72

# parrot/mcp/local_cli.py
_PROJECT_MARKERS = (".mcp.json", ".codex/config.toml", ".git")                                 # :115
def _project_root_for(cwd: Path, relative: Path) -> Path                                       # :118  (relative --config never walks past the worktree's own markers)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `install_root()` | `repository_paths()` | call, reuses `(root, common)` | `launcher.py:58-84` |
| `managed_launcher_on_path()` | `guard_hook_command()` | replaces the inline `shutil.which`/`_under` block | `sdd/installer.py:290-297` |
| `resolve_portable_mode()` | six `if portable is None:` sites | replacement expression | `claude_code/installer.py:736,1280`; `codex/installer.py:294,453`; `google/installer.py:245,404` |
| `HostAdapter.reconcile(..., portable=)` | `_reconcile_all` | keyword forward | `toolkit_install.py:150` |
| `_install_toolkits_step(..., portable=)` | `install_sdd_integration` | call site | `sdd/installer.py:1152` |
| `_resolve_root(write=)` | host CLI commands | `install`/`uninstall` write, `status` read | `claude_code/cli.py:140,255,276`; `codex/cli.py:92,156,181`; `google/cli.py:69,105,119` |
| `InstallRoot.shared_root` | host CLIs and installers' wiki config, remote lookup and builds | `load_effective_config`/`config_path`/`save_project_config`/`is_built`/`wiki_build` argument | CLI config loads: `claude_code/cli.py:172`; `codex/cli.py:106`; `google/cli.py:79`; installer entry functions in §2 |
| `_check_checkout()` | `run_doctor` | appended after the runtime checks when scope ≠ runtime-only | `self_/doctor.py:673-675` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.mcp.portability`~~ — created by M2; nothing imports it today.
- ~~`parrot.launcher.install_root` / `InstallRoot` / `LinkedWorktreeError` / `managed_launcher_on_path` / `explicit_project_pin` / `require_primary_checkout`~~ — created by M1.
- ~~`parrot toolkits install|uninstall|enable|disable --path`~~ — added by M4, with explicit target forwarding and directory validation.
- ~~`install_toolkits(..., portable=)`, `HostAdapter.reconcile(..., portable=)`~~ — no `portable` parameter exists on either today (`toolkit_install.py:158`, `hosts.py:51`).
- ~~`parrot toolkits install --portable`~~ — the flag exists only on `claude|codex|google install` (`--portable/--no-portable`) and `sdd install` (`--portable`, boolean flag).
- ~~`run_doctor(..., install_root=)`~~ — added by M5.
- ~~a `.sdd-installed.json` record of the portable mode~~ — the receipt (`sdd/.sdd-installed.json`, `sdd/installer.py:45`) stores `files`, `blocks`, `ledger_hooks`, `settings_hooks`, `toolkits`, `version`; this spec adds nothing to it (the form is inferred from the host configs).
- ~~`find_project_root()` in `knowledge/wiki/project.py` taking a "prefer worktree" flag~~ — unchanged on purpose (Non-Goals).
- ~~`wizard.py` resolving a root~~ — `cli/wizard.py` contains no `Path.cwd()`/root resolution; it is not an edit site.

### Edit Sites (Blueprint Anchors)

Verified against: `bc9bb3ead6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | `def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path \| None:` | `launcher.py:87` | 1 |
| `packages/ai-parrot/src/parrot/mcp/portability.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:` | `installer.py:280` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `            actions.extend(_install_toolkits_step(root, hosts, receipt))` | `installer.py:1152` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any]) -> list[str]:` | `installer.py:1227` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `def _root(path_: Path \| None) -> Path:` | `cli.py:48` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `    "--portable",` | `cli.py:77` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def dangerous_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:` | `installer.py:308` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool) -> list[str]:` | `installer.py:338` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    portable: bool = False,` | `installer.py:1070` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    hook = guard["command"] if guard["form"] in {"bare", "baked"} else guard_hook_command(portable=False)[0]` | `installer.py:1568` | 1 |
| `packages/ai-parrot/src/parrot/mcp/hosts.py` | MODIFY | `    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:` | `hosts.py:51,95,167,219` | 4 (protocol + Claude + Codex + Google, in that order; each carries its own lazy-import body) |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None:` | `toolkit_install.py:145` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:` | `toolkit_install.py:158` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport:` | `toolkit_install.py:222` | 1 |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `    root = Path.cwd()` | `toolkits.py:126,164,184,224,249,271` | 6 (one per verb: list, status, install, uninstall, enable, disable — anchor with the `def <verb>(` line above each) |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `        f"{kind.value}: writes {get_adapter(kind).config_paths(Path.cwd())[0]} — "` | `toolkits.py:98` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `def _current_portable_mode(root: Path) -> bool:` | `installer.py:139` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `    if portable is None:` | `installer.py:736,1280` | 2 (`:736` inside `reconcile_toolkit_entries` after `servers = data["mcpServers"] = {}`; `:1280` inside `install_claude_integration` after `save_project_config(root, config)`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | `def _current_portable_mode(root: Path) -> bool:` | `installer.py:188` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | `    if portable is None:` | `installer.py:294,453` | 2 (`:294` in `reconcile_toolkit_tables`; `:453` in `install_codex_integration` after `save_project_config(root, config)`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | `def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool:` | `installer.py:75` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | `    if portable is None:` | `installer.py:245,404` | 2 (`:245` in `reconcile_toolkit_entries`; `:404` in `install_google_integration` after `save_project_config(root, config)`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | `def _resolve_root(path: Optional[str]) -> Path:` | `cli.py:36` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` | MODIFY | `def _resolve_root(path: Optional[str]) -> Path:` | `cli.py:25` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` | MODIFY | `def _resolve_root(path: Optional[str]) -> Path:` | `cli.py:25` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py`, `…/codex/cli.py`, `…/google/cli.py` | MODIFY | `        config = load_effective_config(root).config` | `claude_code/cli.py:172`; `codex/cli.py:106`; `google/cli.py:79` | 1 per install callback; also route its remote lookup, `config.is_built(root)` and `context.invoke(wiki_build, path_=str(root), quiet=True)` through state_root |
| `packages/ai-parrot/src/parrot/self_/cli.py` | MODIFY | `    root = find_project_root(sys.argv[1:], os.environ, Path.cwd()) or Path.cwd()` | `cli.py:72` | 1 |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:` | `doctor.py:664` | 1 |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `def _check_host_configs(root: Path) -> list[DoctorCheck]:` | `doctor.py:590` | 1 |
| `docs/install/global-runtime.md` | MODIFY | `The default stays baked absolute paths. \`--portable\` writes bare launcher commands (\`wikitoolkit\`, \`parrot\`,` | `global-runtime.md:193` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py`, `…/codex/bookstore_assets.py`, `…/google/bookstore_assets.py` | MODIFY | `If MCP is disconnected, run` | one per file | 1 each (verify with `grep -c` at task time) |
| `packages/ai-parrot/tests/launcher/conftest.py` | CREATE | — (receives `linked_worktree_repo` / `make_venv` from `test_launcher_core.py:11,26`) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **`parrot.launcher` is stdlib-only and hook-critical** (`launcher.py:1-5`): `install_root()` must not
  import `parrot.knowledge.wiki.project`; the primary-checkout resolution is `repository_paths()`'s
  `commondir` logic, which is already there, plus inspection of the original gitdir to establish actual
  linked-worktree metadata. Installers and host CLIs use `InstallRoot.shared_root`; do not substitute
  `find_shared_root()` for classification, since its external-gitdir behavior also assumes common.parent.
- **Stickiness first, launcher second.** `resolve_portable_mode` must never flip an existing baked host to
  portable without `--portable` (AC5) — the tri-state `None` is what makes "fresh" distinguishable; keep the
  tie-break rules of the existing `_current_portable_mode` helpers intact and only change their "nothing
  managed found" return value.
- **One note per command.** The baked note is appended by the installer entry function once; reconcilers
  called from `install_*_integration` must not add a second copy (pass the resolved `bool`, as today).
- **Refuse before writing.** `require_primary_checkout()` runs before any plan/write in every write verb,
  `--dry-run` included; `status`/`list` resolve with `write=False`.
- **Only genuine doctor pins count as explicit.** `self_/cli.py` passes `explicit_project_pin()` as
  `explicit=` so `--project`, `PARROT_PROJECT` and `CLAUDE_PROJECT_DIR` behave as `--path`. The existing
  `find_project_root()` discovery fallback is never evidence of an explicit selection.
- Error and note texts are fixed in §3; tests assert on them.

### Known Risks / Gotchas
- **FEAT-802 touches the same files** (`sdd/installer.py` GITIGNORE block + `install_sdd_integration`
  preamble, `self_/doctor.py` `_check_sdd_git` + a new legacy check, `sdd/cli.py` VERBS mount). Different
  functions, no semantic dependency; whichever feature merges second rebases. Not a blocking dependency.
- **Behaviour change for fieldsync-type repos on the next install:** a fresh host with the launcher on
  `PATH` is now portable. Repos installed before this change keep their baked form (sticky) until an
  explicit `--portable`; `doctor`'s new form check tells them.
- **Portable entries inside linked worktrees.** `parrot mcp-local` resolves a relative `--config` up to the
  worktree's own `.mcp.json`/`.git` (`local_cli.py:115-150`), so a portable `parrot-*` entry started from a
  worktree session needs `<worktree>/.parrot/mcp-toolkits.yaml`, which nothing seeds today (baked entries
  point at the primary checkout's file and keep working). Out of scope here; the non-Python/worktree
  follow-up spec owns it.
- **Shipped guidance that runs installers in place.** The bookstore skill asset says "run `parrot claude
  install --no-build` in the target repository"; from a worktree session that now exits 1 with the
  primary-checkout message (M6 adjusts the wording). `docs/sdd/ledger-outbox.md:38` recommends
  `parrot claude install` for an upgrade — unaffected when run from the primary checkout.
- **Google is user-global.** The form check and the launcher rule apply to both Google files; the existing
  cross-repo collision check (`doctor.py:632-638`) stays the authority for the user-global file.
- **`tests/cli/test_toolkits_cli.py::test_list_on_empty_repo`** runs `toolkits list` in a non-git temp dir:
  `install_root()` must fall back to `cwd` without error when no `.git` is found (G3), and `list` is a
  read verb.
- **Windows**: `managed_launcher_on_path()` compares resolved paths like `guard_hook_command()` does today
  (`parrot.exe` under `Scripts/`); `script_path()` (`launcher.py:118`) remains the only place that knows the
  layout.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | stdlib only (`dataclasses`, `shutil`); `click` already used by every CLI touched |

---

## Worktree Strategy

- **Isolation**: one feature worktree for the whole spec; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph** (evidence in §3 "Depends on"):
  - M2 → M1 (`resolve_portable_mode` and `guard_hook_command` call `managed_launcher_on_path`).
  - M3 → M2 (the reconcilers' `None` branch must apply the launcher rule before forwarding makes the
    fresh-repo case correct; M3's tests assert portable output on a fresh repo).
  - M4 → M1 (`install_root`, `require_primary_checkout`).
  - M5 → M1 (`InstallRoot`) and M2 (tri-state `_current_portable_mode` for the form check).
  - M6 → M2, M4 (names only; prose).
  - M3, M4 and M5 are mutually independent once M1 and M2 are merged and may run concurrently.
- **Shared files** (their tasks get serialized): `sdd/installer.py` (M2 `guard_hook_command` and the
  tri-state signatures; M3 `_install_toolkits_step` + call site); `sdd/cli.py` (M3 `--portable/--no-portable`;
  M4 `_root`); `knowledge/wiki/{claude_code,codex,google}/installer.py` (M2
  tri-state + `portable is None` sites; M4 `InstallRoot.shared_root` state root in the three `install_*_integration`
  functions); `cli/toolkits.py` (M3 `--portable` options; M4 root helper); `self_/doctor.py` (M5 only);
  `self_/cli.py` (M4 only).
- **Exclusive resources**: none (no extension rebuild, no lockfile, no asset regeneration — the bookstore
  skill text lives in Python assets, not in `parrot/sdd/_assets/`).
- **Cross-feature dependencies**: none blocking. FEAT-802 (`worktree-root-under-parrot`) edits other
  functions of `sdd/installer.py`, `self_/doctor.py` and `sdd/cli.py`; whichever lands second rebases.

---

## Decisions

```yaml
schema_version: 1
document_id: installer-portability-gaps
entries:
  - id: single-portable-rule
    statement: Every parrot-emitted host command (hooks, wikitoolkit/bookstore and parrot-* MCP entries, Codex rules) takes its form from parrot.mcp.portability.resolve_portable_mode — explicit flag, else the host's current managed form, else portable when the managed launcher resolves on PATH, else baked with a printed note.
    relation: constrains
    about: [sdd-tooling]
    targets: [sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command, sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration, sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration, sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration]
    contradicts: []
    supersedes: []
    rationale: "FEAT-633 resolved 'default stays baked absolute paths; --portable opt-in' (sdd/proposals/portable-sdd-flow.brainstorm.md, carried into parrot-installer.spec.md §8). That default commits machine paths silently; the guard hook already proved the launcher rule works. Owner decision 2026-11-04."
    rejected_alternatives: ["keep baked default and only print a note", "always portable and refuse without the managed launcher"]
  - id: installers-target-the-checkout-you-run-in
    statement: Installer-type commands resolve their target with parrot.launcher.install_root (explicit path, else the nearest checkout holding a .git directory or file) and never with the wiki-plane resolver knowledge.wiki.project.find_project_root.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/launcher.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py, file:packages/ai-parrot/src/parrot/sdd/cli.py, file:packages/ai-parrot/src/parrot/cli/toolkits.py]
    contradicts: []
    supersedes: []
    rationale: "Four resolvers gave four answers; the wiki-plane root (FEAT-697) is a different question from the install target."
    rejected_alternatives: ["teach find_project_root a prefer-worktree flag"]
  - id: linked-worktrees-refuse-installers
    statement: Without an explicit --path (or --project / PARROT_PROJECT / CLAUDE_PROJECT_DIR for doctor), a write verb whose resolved root is a linked worktree exits 1 naming the primary checkout; it never redirects silently and never installs in place.
    relation: forbids
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/launcher.py, sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor]
    contradicts: []
    supersedes: []
    rationale: "Owner decision 2026-11-04 (block, do not warn). Installing in place would also tempt writing .parrot/wiki.json into the worktree and split the wiki plane; redirecting is what happened by accident and hid the bug."
    rejected_alternatives: ["install into the worktree with a note", "redirect to the primary checkout with a note"]
  - id: wiki-config-lives-on-the-primary-checkout
    statement: Host CLIs and installers load and save wiki configuration, resolve remote settings and perform initial builds at InstallRoot.shared_root, preserving the primary configuration when targeting a linked worktree. Host assets use InstallRoot.root; external gitdirs without commondir are not linked worktrees.
    relation: requires
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/launcher.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py]
    contradicts: []
    supersedes: []
    rationale: "FEAT-697: the plane exists only in the primary checkout; a worktree-local wiki.json would make find_project_root stop at the worktree."
    rejected_alternatives: []
  - id: host-config-form-is-informational
    statement: doctor reports the form of each host config (portable / baked) as an informational check that never changes its exit code.
    relation: constrains
    about: [sdd-tooling]
    targets: [sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs]
    contradicts: []
    supersedes: []
    rationale: "Owner decision 2026-11-04: baked absolute paths are a valid single-machine state; the sticky default keeps writing them for already-installed repos, so failing doctor on them would contradict the installer."
    rejected_alternatives: ["fail when sdd/config.json opts in with a portable_required key", "always fail when baked"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:180886adb14f1ed918ba57622caecb4a652862c76d251f6f32c60f6629768ad1 evaluation_digest=sha256:c9b8f821b46b72710ac40b5a590d5cac28be3ce4e52369739445df6386f403a1 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#single-portable-rule@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration; message: sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration impacts 38 dependent(s): sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_default_install_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_foreign_toolkit_entry_untouched, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_portable_install_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_portable_transitions_both_ways, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_reconcile_respects_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_remote_does_not_reset_portable_mode, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_remote_portable_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_claude, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_baked_install_falls_back_to_the_bare_wikitoolkit_command, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_tie_broken_by_toolkit_entries, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_without_toolkit_entries_is_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_explicit_portable_migrates_a_baked_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_mixed_toolkit_entries_are_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_plain_reinstall_keeps_a_baked_install_baked, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_chains_into_env_bash_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_chains_into_existing_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_claude_md_repaired_when_end_marker_lost, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_customised_nudge_tools_not_overridden, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_duplicate_sharing_an_entry_keeps_the_foreign_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_fresh_install_writes_all_artifacts, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_install_is_idempotent, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_invalid_settings_json_aborts, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_no_git_hook_option, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_preserves_existing_claude_md, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_preserves_existing_settings_hooks, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_collapses_a_quoted_duplicate, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_migrates_nudge_tools, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_migrates_permissions_to_local, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_upgrades_hook_matcher, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_skips_chaining_into_non_sh_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_status_reflects_install_state, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_uninstall_keeps_a_foreign_hook_sharing_our_entry, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_uninstall_removes_only_ours, sym:tests/knowledge/wiki/test_claude_code_compaction.py#TestIntegrationWiring.test_library_default_is_opt_in_and_cli_default_is_on, sym:tests/knowledge/wiki/test_claude_code_compaction.py#TestIntegrationWiring.test_status_labels_include_compaction, sym:tests/knowledge/wiki/test_installer_ledger_hooks.py#test_install_claude_integration_action_count
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers@1; scope: sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor; message: sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor impacts 3 dependent(s): sym:packages/ai-parrot/src/parrot/self_/cli.py#doctor, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_run_doctor_never_raises_on_empty_home, sym:packages/ai-parrot/tests/self_/test_doctor_sdd.py#test_scope_runtime_only_excludes_repo_host_and_component_checks
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#host-config-form-is-informational@1; scope: sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs; message: sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs impacts 8 dependent(s): sym:packages/ai-parrot/src/parrot/self_/cli.py#doctor, sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_doctor_flags_broken_host_config, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_gemini_cross_repo_collision, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_gemini_repo_local_config_checked, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_remote_http_entry_is_not_flagged, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_run_doctor_never_raises_on_empty_home, sym:packages/ai-parrot/tests/self_/test_doctor_sdd.py#test_scope_runtime_only_excludes_repo_host_and_component_checks
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#single-portable-rule@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration; message: sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration impacts 11 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#install, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_default_emission_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_foreign_entries_untouched, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_config_two_roots, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_entries_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_transitions_and_sticky_reconcile, sym:tests/knowledge/wiki/test_google_integration.py#test_install_is_idempotent_and_preserves_unrelated_config, sym:tests/knowledge/wiki/test_google_integration.py#test_install_writes_mcp_skill_instructions_and_plugin, sym:tests/knowledge/wiki/test_google_integration.py#test_invalid_mcp_config_aborts_without_overwriting, sym:tests/knowledge/wiki/test_google_integration.py#test_uninstall_removes_only_managed_assets
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#single-portable-rule@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration; message: sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration impacts 19 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#install, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_default_emission_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_portable_entries_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_portable_transitions_both_ways, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_reconcile_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_remote_does_not_reset_portable_mode, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_remote_portable_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_baked_install_falls_back_to_the_bare_wikitoolkit_command, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_tie_broken_by_toolkit_entries, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_without_toolkit_entries_is_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_explicit_portable_migrates_a_baked_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_plain_reinstall_keeps_a_baked_install_baked, sym:tests/knowledge/wiki/test_codex_installer_toolkit_entries.py#test_codex_install_reconciles_declared_toolkits, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_is_idempotent_and_preserves_unrelated_config, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_replaces_manual_wikitoolkit_mcp_table, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_writes_mcp_skill_instructions_and_permissions, sym:tests/knowledge/wiki/test_codex_integration.py#test_invalid_config_aborts_without_overwriting, sym:tests/knowledge/wiki/test_codex_integration.py#test_uninstall_removes_only_managed_assets, sym:tests/knowledge/wiki/test_codex_toolkit_reconcile.py#test_empty_toolkit_config_hints_at_new_command; inferred: sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_codex
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#single-portable-rule@1; scope: sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command; message: sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command impacts 40 dependent(s): sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_dangerous_guard, sym:packages/ai-parrot/src/parrot/sdd/installer.py#dangerous_hook_command, sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration, sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_agents_dispatched_by_packaged_autopilot_are_installed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_dry_run_changes_nothing, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_existing_gitignore_content_preserved, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_foreign_file_never_touched_even_with_force, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_gitattributes_block_written_recorded_and_removed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_gitignore_block_ignores_worktrees_and_parrot_state, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_absent_is_resolvable, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_baked_when_launcher_absent, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_bare_when_managed_launcher_on_path, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_mode_change_is_outdated_not_edited, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_portable_flag_forces_bare, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_quoting_space_and_quote, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_status_flags_hand_patched_foreign, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_never_writes_through_a_symlink_out_of_the_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_refuses_malformed_config_before_writing, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_warns_when_test_command_is_null, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_installed_for_any_host, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_kept_when_shared_with_claude_integration, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_removed_on_uninstall_when_sdd_created_them, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_modified_file_skipped_unless_force_and_kept_on_uninstall, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_non_claude_host_skills_have_every_file_they_read, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_reinstall_is_idempotent, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_reinstall_upgrades_an_old_gitignore_block, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_sdd_flow_in_foreign_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_sdd_install_into_empty_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_seeds_written_once_never_overwritten_or_removed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_status_shape, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_uninstall_after_hand_deleting_one_asset_still_cleans_up, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_unknown_host_rejected, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_unrecorded_identical_file_is_adopted, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_untouched_file_upgrades_from_older_record, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#stale_repo, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_current_targets_and_seeds_never_stale, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_install_reports_stale_note, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_status_reports_stale, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_unreadable_folder_does_not_break_install_or_status
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#installers-target-the-checkout-you-run-in@1, adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers@1; scope: file:packages/ai-parrot/src/parrot/launcher.py; message: adr:spec:installer-portability-gaps#installers-target-the-checkout-you-run-in (constrains) and adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers (forbids) govern overlapping scope
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers@1, adr:spec:installer-portability-gaps#wiki-config-lives-on-the-primary-checkout@1; scope: file:packages/ai-parrot/src/parrot/launcher.py; message: adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers (forbids) and adr:spec:installer-portability-gaps#wiki-config-lives-on-the-primary-checkout (requires) govern overlapping scope

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: doctor, installer, mcp-toolkits, portability, worktree
- Targets resolved: 12/12
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 12,
    "targets_total": 12,
    "unmapped_tags": [
      "doctor",
      "installer",
      "mcp-toolkits",
      "portability",
      "worktree"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:c9b8f821b46b72710ac40b5a590d5cac28be3ce4e52369739445df6386f403a1",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:084bf2c379d6cef2a486292707fc45a9e76242f2bdd9b3becf94903687b5794b",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration impacts 38 dependent(s): sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_default_install_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_foreign_toolkit_entry_untouched, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_portable_install_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_portable_transitions_both_ways, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_reconcile_respects_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_remote_does_not_reset_portable_mode, sym:packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py#test_remote_portable_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_claude, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_baked_install_falls_back_to_the_bare_wikitoolkit_command, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_tie_broken_by_toolkit_entries, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_without_toolkit_entries_is_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_explicit_portable_migrates_a_baked_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_mixed_toolkit_entries_are_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_plain_reinstall_keeps_a_baked_install_baked, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_chains_into_env_bash_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_chains_into_existing_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_claude_md_repaired_when_end_marker_lost, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_customised_nudge_tools_not_overridden, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_duplicate_sharing_an_entry_keeps_the_foreign_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_fresh_install_writes_all_artifacts, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_install_is_idempotent, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_invalid_settings_json_aborts, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_no_git_hook_option, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_preserves_existing_claude_md, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_preserves_existing_settings_hooks, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_collapses_a_quoted_duplicate, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_migrates_nudge_tools, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_migrates_permissions_to_local, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_reinstall_upgrades_hook_matcher, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_skips_chaining_into_non_sh_git_hook, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_status_reflects_install_state, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_uninstall_keeps_a_foreign_hook_sharing_our_entry, sym:tests/knowledge/wiki/test_claude_code.py#TestInstaller.test_uninstall_removes_only_ours, sym:tests/knowledge/wiki/test_claude_code_compaction.py#TestIntegrationWiring.test_library_default_is_opt_in_and_cli_default_is_on, sym:tests/knowledge/wiki/test_claude_code_compaction.py#TestIntegrationWiring.test_status_labels_include_compaction, sym:tests/knowledge/wiki/test_installer_ledger_hooks.py#test_install_claude_integration_action_count",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#single-portable-rule",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:0d15a3852c89df0e6476db91a1d06d79ccf37d155135b1cf804738fb6a3df23f",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor impacts 3 dependent(s): sym:packages/ai-parrot/src/parrot/self_/cli.py#doctor, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_run_doctor_never_raises_on_empty_home, sym:packages/ai-parrot/tests/self_/test_doctor_sdd.py#test_scope_runtime_only_excludes_repo_host_and_component_checks",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:2ebaa557e4fa010c671c8545aac5865af4ec2e63ca6bfd1866ae5723b86a35b8",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs impacts 8 dependent(s): sym:packages/ai-parrot/src/parrot/self_/cli.py#doctor, sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_doctor_flags_broken_host_config, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_gemini_cross_repo_collision, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_gemini_repo_local_config_checked, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_remote_http_entry_is_not_flagged, sym:packages/ai-parrot/tests/self_/test_doctor.py#test_run_doctor_never_raises_on_empty_home, sym:packages/ai-parrot/tests/self_/test_doctor_sdd.py#test_scope_runtime_only_excludes_repo_host_and_component_checks",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#host-config-form-is-informational",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:a1e1c00aff6332020377d10e3866a870110f435112dd85997fa3a3d2de062e02",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration impacts 11 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#install, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_default_emission_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_foreign_entries_untouched, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_config_two_roots, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_entries_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py#test_portable_transitions_and_sticky_reconcile, sym:tests/knowledge/wiki/test_google_integration.py#test_install_is_idempotent_and_preserves_unrelated_config, sym:tests/knowledge/wiki/test_google_integration.py#test_install_writes_mcp_skill_instructions_and_plugin, sym:tests/knowledge/wiki/test_google_integration.py#test_invalid_mcp_config_aborts_without_overwriting, sym:tests/knowledge/wiki/test_google_integration.py#test_uninstall_removes_only_managed_assets",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#single-portable-rule",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:bb0239655257c296c20a8fe74b1888f21e6db8e0181e29abd8da63e816d0f2dd",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration impacts 19 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#install, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_default_emission_unchanged, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_portable_entries_no_abs_paths, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_portable_transitions_both_ways, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_reconcile_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_remote_does_not_reset_portable_mode, sym:packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py#test_remote_portable_sticky, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_baked_install_falls_back_to_the_bare_wikitoolkit_command, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_tie_broken_by_toolkit_entries, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_bare_wikitoolkit_without_toolkit_entries_is_portable, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_explicit_portable_migrates_a_baked_install, sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_plain_reinstall_keeps_a_baked_install_baked, sym:tests/knowledge/wiki/test_codex_installer_toolkit_entries.py#test_codex_install_reconciles_declared_toolkits, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_is_idempotent_and_preserves_unrelated_config, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_replaces_manual_wikitoolkit_mcp_table, sym:tests/knowledge/wiki/test_codex_integration.py#test_install_writes_mcp_skill_instructions_and_permissions, sym:tests/knowledge/wiki/test_codex_integration.py#test_invalid_config_aborts_without_overwriting, sym:tests/knowledge/wiki/test_codex_integration.py#test_uninstall_removes_only_managed_assets, sym:tests/knowledge/wiki/test_codex_toolkit_reconcile.py#test_empty_toolkit_config_hints_at_new_command; inferred: sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_codex",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#single-portable-rule",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:dcc3abeef9e9118de9c0f8cb285dc68a187cb277ef24934e3befc511639ee944",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command impacts 40 dependent(s): sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_dangerous_guard, sym:packages/ai-parrot/src/parrot/sdd/installer.py#dangerous_hook_command, sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration, sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_agents_dispatched_by_packaged_autopilot_are_installed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_dry_run_changes_nothing, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_existing_gitignore_content_preserved, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_foreign_file_never_touched_even_with_force, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_gitattributes_block_written_recorded_and_removed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_gitignore_block_ignores_worktrees_and_parrot_state, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_absent_is_resolvable, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_baked_when_launcher_absent, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_bare_when_managed_launcher_on_path, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_mode_change_is_outdated_not_edited, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_portable_flag_forces_bare, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_quoting_space_and_quote, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_guard_hook_status_flags_hand_patched_foreign, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_never_writes_through_a_symlink_out_of_the_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_refuses_malformed_config_before_writing, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_install_warns_when_test_command_is_null, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_installed_for_any_host, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_kept_when_shared_with_claude_integration, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_ledger_hooks_removed_on_uninstall_when_sdd_created_them, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_modified_file_skipped_unless_force_and_kept_on_uninstall, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_non_claude_host_skills_have_every_file_they_read, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_reinstall_is_idempotent, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_reinstall_upgrades_an_old_gitignore_block, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_sdd_flow_in_foreign_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_sdd_install_into_empty_repo, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_seeds_written_once_never_overwritten_or_removed, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_status_shape, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_uninstall_after_hand_deleting_one_asset_still_cleans_up, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_unknown_host_rejected, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_unrecorded_identical_file_is_adopted, sym:packages/ai-parrot/tests/sdd/test_installer.py#test_untouched_file_upgrades_from_older_record, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#stale_repo, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_current_targets_and_seeds_never_stale, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_install_reports_stale_note, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_status_reports_stale, sym:packages/ai-parrot/tests/sdd/test_installer_stale.py#test_unreadable_folder_does_not_break_install_or_status",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#single-portable-rule",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:029d4e8a6b300539e3ccc9a77dc9338f0a751aff0270bed24623ce5cd1f08610",
      "kind": "potential-conflict",
      "message": "adr:spec:installer-portability-gaps#installers-target-the-checkout-you-run-in (constrains) and adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers (forbids) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#installers-target-the-checkout-you-run-in",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/launcher.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:559fb283aa6e176840f43923b368a079085ae3987b78693c54ca42e077687218",
      "kind": "potential-conflict",
      "message": "adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers (forbids) and adr:spec:installer-portability-gaps#wiki-config-lives-on-the-primary-checkout (requires) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:installer-portability-gaps#linked-worktrees-refuse-installers",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:installer-portability-gaps#wiki-config-lives-on-the-primary-checkout",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/launcher.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:180886adb14f1ed918ba57622caecb4a652862c76d251f6f32c60f6629768ad1",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:6488397c5f24951c41796856dcbb3c99e68a91b9b5b6a5742b2743721b6432fa",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Default form on a fresh repository — *Resolved by Jesus Lara, 2026-11-04*: launcher on `PATH` ⇒ portable; otherwise baked plus a printed note (supersedes FEAT-633's "default stays baked, `--portable` opt-in").
- [x] Behaviour inside a linked worktree without `--path` — *Resolved by Jesus Lara, 2026-11-04*: refuse (exit 1, name the primary checkout and `--path`); not install-in-place, not redirect.
- [x] Does the worktree-root relocation (FEAT-802) close gap 3? — *Resolved in chat, 2026-11-04*: no; the install-target root and the wiki-plane root are different questions. Independent specs.
- [x] Should `parrot sdd install --portable` stay a boolean flag, or become `--portable/--no-portable`? — *Resolved by Jesus Lara, 2026-11-04*: `--portable/--no-portable`, default `None`; the same tri-state reaches `guard_hook_command`, the dangerous guard and the toolkit entries, so `--no-portable` migrates an SDD install back to baked explicitly.
- [x] Should `doctor`'s `host config: form` check ever fail? — *Resolved by Jesus Lara, 2026-11-04*: informational only; no `sdd/config.json` policy key, doctor's exit code never depends on the form.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (no accepted exploration document — the design was captured in chat on 2026-11-04; the related `portable-sdd-flow.brainstorm.md` and `parrot-installer-amendments.proposal.md` are FEAT-583/FEAT-633 documents, not this feature's)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | Jesus Lara / Claude | Initial draft from the 2026-11-04 installer evaluation and chat decisions |
| 0.2 | 2026-11-04 | Jesus Lara / Claude | §8 resolved: `sdd install --portable/--no-portable` tri-state through the guard hook, dangerous guard and toolkits; doctor form check stays informational (new decision entry) |
| 0.3 | 2026-11-04 | Codex | Resolve review issues 7a8775764864, fad32abb34ef, a7c49cf2413a and f110ff4c0d20: preserve shared wiki config across CLI loading/builds, retain doctor pin provenance, add toolkit --path plumbing, distinguish external gitdirs from linked worktrees; align regression tests and tri-state contracts. |
| 0.4 | 2026-11-04 | Jesus Lara / Claude | Status → approved; decision audit re-rendered for the 0.3 contracts (`pass`, 8 advisory findings) |
