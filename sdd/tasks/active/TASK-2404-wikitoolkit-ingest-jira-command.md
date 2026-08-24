# TASK-2404: `wikitoolkit ingest-jira` CLI command

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2403
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** (spec §3 M5, §2 "CLI surface", G10). One new click
command that turns the sweep into the single line a cron can run: resolve
config, sweep, then **build the plane by default** so it can never silently
lag the files.

`cli.py` is a 123 KB hot file every wiki feature touches (§7). Keep the new
command **self-contained and appended** — do not interleave edits into
existing commands, and do not refactor anything on the way past. A textual
conflict here blocks other in-flight wiki work.

---

## Scope

- Add one `@wiki.command()` named `ingest-jira` to
  `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`, appended near the
  existing `ingest` command, with exactly the options in the spec's CLI
  surface.
- Resolve configuration navconfig-then-env (the `_cfg` idiom), with
  `--project KEY` as shorthand for `project = KEY`.
- Construct a `JiraInterface` from the resolved credentials.
- Call `sweep_jira_issues`, then — unless `--no-build` — invoke the existing
  build path in **vault mode** against the issues directory.
- Report the `SweepReport` (human-readable, or raw JSON with `--json`,
  or one summary line with `-q/--quiet`).
- Exit non-zero when the sweep recorded errors, so a cron surfaces failure.
- Fail with a single actionable message (no traceback) when `jira` is absent.
- Write the CLI tests listed below.

**NOT in scope**:
- Implementing `--enrich`. Accept the flag, and **fail fast** with
  "`--enrich` is not implemented in v1" rather than silently ignoring it —
  a silently-ignored flag is worse than an absent one.
- Modifying `build`, `ns`, `link`, `ingest`, `upsert`, `query`, `page`,
  `related`, or any shared helper.
- Registering the namespace. `ns add` is a documented **one-time operator
  action** (TASK-2406's runbook) — *"This is the only writer of namespace
  entries — neither `build` nor any other command ever self-registers a
  wiki"* (`ns_add` docstring). Do not self-register.
- Scheduling. The runbook documents cron; no scheduler ships.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Append the `ingest-jira` command only |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_ingest_jira.py` | CREATE | CLI option/exit-code/build-invocation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
# Already imported at the top of cli.py — reuse, do not re-import:
#   click, wiki_write_lock (cli.py:77), _resolve_project (:330),
#   _require_built (:351), _open_store (:358), path_option
# New — import LAZILY inside the command body, mirroring how `build`
# imports vault_scan at cli.py:1118-1121:
from parrot.knowledge.wiki.jira_sync import (      # TASK-2403
    SweepReport, resolve_issues_dir, sweep_jira_issues,
)
from parrot.interfaces.jira import (               # TASK-2400
    JiraAuthError, JiraDependencyError, JiraInterface,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@click.group(name="wiki")                     # :1009  — the group to hang off
def wiki() -> None: ...
# Existing commands (do not touch): mcp :1030, build :1044, upsert :1281,
#   query :1394, page :1483, related :1530, status :1572, communities :2010,
#   export :2117, remember :2406, note :2571, link :2643, memories :2705,
#   audit :2736, ground :2790, ingest :3030, claude-hook :3431
@wiki.group(name="ns")                        # :1774
@ns.command("list") :1779   @ns.command("add") :1826   @ns.command("remove") :1979

def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]: ...  # :330
#   With an explicit `path`: resolves it, raises ClickException if not a dir,
#   then load_project_config(root). load_project_config returns DEFAULTS when
#   no .parrot/wiki.json exists (project.py:538) — so this works on a bare
#   issues directory with NO pre-created config. That is how `build --path
#   <issues-dir> --vault` can run on a fresh corpus.

# --- THE BUILD COMMAND, cli.py:1044-1090 (the path to reuse) --------------
@wiki.command()
@path_option
@click.option("--name", default=None, ...)
@click.option("--backend", type=click.Choice(["sqlite","memory","arangodb"]), ...)
@click.option("--force", is_flag=True, ...)
@click.option("--no-git", is_flag=True, ...)
@click.option("--quiet", "-q", is_flag=True, ...)
@click.option("--no-export", is_flag=True, ...)
@click.option("--no-graph", is_flag=True, ...)
@click.option("--graph-kinds", default="module,document,overview", ...)
@click.option("--vault/--no-vault", "vault_mode", default=None,
              help="Treat the path as an Obsidian vault ... Default: "
                   "auto-detect via the .obsidian/ directory.")
def build(path_, name, backend, force, no_git, quiet, no_export, no_graph,
          graph_kinds, vault_mode) -> None: ...
# :1104-1112 — build takes wiki_write_lock(config.storage_path(root)) and
#   echoes "Another wiki writer is in progress..." + SystemExit(1) on failure.
# :1118-1133 — lazily imports is_obsidian_vault/scan_vault, then:
#     if vault_mode is None: vault_mode = is_obsidian_vault(root)
#     if vault_mode: scan, vault_stats = scan_vault(root, ...)
#   ^ THIS is why --vault must be passed explicitly: the issues dir has no
#     .obsidian/, so auto-detect would pick REPOSITORY mode and scan the
#     markdown as source code.

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def storage_path(self, root: Path) -> Path: ...   # :381 -> <root>/<storage_dir>
def db_path(self, root: Path) -> Path: ...        # :386 -> <storage>/wiki.db
def load_project_config(root: Path) -> WikiProjectConfig: ...  # :514
def is_built(self, root: Path) -> bool: ...       # :390

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:751-760
#   the _cfg(key, default) idiom: navconfig FIRST, then os.getenv
```

**The CLI surface to implement (spec §2, verbatim):**

```
wikitoolkit ingest-jira [OPTIONS]

  --jql TEXT           JQL scope (default: JIRA_WIKI_JQL, or
                       project = <JIRA_DEFAULT_PROJECT>)
  --project TEXT       Shorthand for `project = <KEY>`
  --since DATE         Override the stored watermark (ISO-8601)
  --issues-dir PATH    Output directory (default: JIRA_WIKI_ISSUES_DIR
                       or ${PARROT_HOME}/wikis/issues)
  --build/--no-build   Build the plane after emitting (default: build)   [G10]
  --enrich             Opt-in LLM summary for thin descriptions (default: off)
  --force              Re-render every issue in scope, ignoring the watermark
  --dry-run            Report what would change; write nothing
  --json               Emit the SweepReport as JSON
  -q, --quiet          Only the final summary line
```

**Configuration keys (spec §2):**

| Key | Default | Purpose |
|---|---|---|
| `JIRA_WIKI_ISSUES_DIR` | `${PARROT_HOME}/wikis/issues` | Off-repo corpus root (G8) |
| `JIRA_WIKI_JQL` | `project = ${JIRA_DEFAULT_PROJECT}` | Default sweep scope |
| `JIRA_WIKI_NAMESPACE` | `issues` | Namespace name used by the runbook |
| `JIRA_WIKI_AC_FIELD` | (unset) | AC custom-field id; by-name fallback when unset |
| `JIRA_INSTANCE`, `JIRA_AUTH_TYPE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_SECRET_TOKEN`, `JIRA_OAUTH_*`, `JIRA_REQUEST_TIMEOUT` | (existing) | Reused verbatim from `JiraToolkit` |

The **shipped default JQL** is `project = ${JIRA_DEFAULT_PROJECT}` — a single
project, **no status filter, no date bound** (spec §8, resolved). Closed and
resolved tickets are in scope deliberately.

### Does NOT Exist

- ~~`wikitoolkit ingest-jira`~~ — created by this task. Confirm it is absent:
  `grep -n 'ingest-jira' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- ~~`ns add --vault` on a plain directory~~ — the option requires `.obsidian/`
  (`cli.py:1864`, `is_obsidian_vault` at `vault_scan.py:62`). Register with
  `--store <issues-dir>/.parrot/wiki`. Only **`build`** has a `--vault`
  *flag* that forces vault mode without the marker directory — that is the one
  this command uses.
- ~~A `build()` Python API~~ — `build` is a click command. To reuse it, either
  invoke its callback directly (`build.callback(...)`) or replicate its
  vault-mode body. **Prefer invoking the callback** so the build stays exactly
  one implementation; verify it is callable outside a click context first, and
  fall back to `ctx.invoke(build, ...)` if not.
- ~~Auto-creating `.obsidian/` in the issues dir to make auto-detect work~~ —
  do not. Pass `--vault` / `vault_mode=True` explicitly.
- ~~Self-registering the namespace~~ — `ns_add`'s docstring forbids it:
  *"This is the only writer of namespace entries."*
- ~~An `--enrich` implementation~~ — v1 accepts and rejects the flag.

---

## Implementation Notes

### Command skeleton

```python
@wiki.command(name="ingest-jira")
@click.option("--jql", default=None, help="JQL scope (default: JIRA_WIKI_JQL, "
              "or `project = <JIRA_DEFAULT_PROJECT>`).")
@click.option("--project", "project_key", default=None,
              help="Shorthand for `project = <KEY>`.")
@click.option("--since", default=None,
              help="Override the stored watermark (ISO-8601).")
@click.option("--issues-dir", "issues_dir_opt", default=None,
              type=click.Path(file_okay=False),
              help="Output directory (default: JIRA_WIKI_ISSUES_DIR or "
                   "${PARROT_HOME}/wikis/issues).")
@click.option("--build/--no-build", "do_build", default=True,
              help="Build the plane after emitting (default: build).")
@click.option("--enrich", is_flag=True,
              help="Opt-in LLM summary for thin descriptions (not in v1).")
@click.option("--force", is_flag=True,
              help="Re-render every issue in scope, ignoring the watermark.")
@click.option("--dry-run", is_flag=True,
              help="Report what would change; write nothing.")
@click.option("--json", "as_json", is_flag=True,
              help="Emit the SweepReport as JSON.")
@click.option("--quiet", "-q", is_flag=True, help="Only the final summary line.")
def ingest_jira(jql, project_key, since, issues_dir_opt, do_build, enrich,
                force, dry_run, as_json, quiet) -> None:
    """Extract Jira tickets into the `issues` markdown corpus and build it.

    Deterministic and zero-LLM by default: every frontmatter field is a Jira
    field or a pure function of one, so two runs over unchanged tickets
    produce byte-identical documents and write nothing.

    Scope is JQL; each run fetches only issues updated since the last
    successful watermark, so a daily cron stays cheap. Content below the
    `<!-- jira-sync:end -->` marker in any document is preserved forever.

    Register the corpus once as a namespace (see the runbook):

        wikitoolkit ns add issues --store <issues-dir>/.parrot/wiki --global
    """
```

Read `build`'s and `ingest`'s decorators before writing yours — match the
project's `help=` phrasing and `show_default` conventions exactly.

### Option/config resolution order

```
--jql            explicit
--project KEY    -> f"project = {KEY}"        (mutually exclusive with --jql;
                                               error if both are given)
JIRA_WIKI_JQL    from _cfg
project = ${JIRA_DEFAULT_PROJECT}             final fallback
```
When none resolves (no `JIRA_DEFAULT_PROJECT` either), raise a
`ClickException` naming both `--jql` and `JIRA_WIKI_JQL` — never sweep an
unbounded `ORDER BY created` over an entire Jira instance by accident.

### Reusing the build path (G10)

```python
    if do_build and not dry_run:
        # vault_mode=True EXPLICITLY: the issues dir has no .obsidian/, and
        # auto-detect (cli.py:1129) would pick repository mode and scan the
        # markdown as source code.
        build.callback(
            path_=str(issues_dir), name=namespace_name, backend=None,
            force=force, no_git=True, quiet=quiet, no_export=True,
            no_graph=True, graph_kinds="module,document,overview",
            vault_mode=True,
        )
```
Verify each of `build`'s parameter names against `cli.py:1081-1092` before
calling — a positional/keyword mismatch here is a silent wrong-mode build.
`no_git=True` matters: the corpus is not a git repo. Decide `no_export` /
`no_graph` deliberately and document the choice in the docstring (defaulting
them **on** keeps a cron cheap; the operator can run `build` by hand for the
extras).

`--dry-run` must skip the build entirely — building would write `wiki.db`,
violating "writes nothing".

### Reporting and exit codes

- Default: a short human block (fetched / written / unchanged / orphaned /
  entity notes / watermark advanced), plus a warning line when
  `unresolved_link_keys` is non-empty — that is the operator's signal to widen
  the JQL (`vault_scan.py:183` drops those edges).
- `--json`: `click.echo(report.model_dump_json(indent=2))` and nothing else.
- `-q`: one summary line.
- **Exit non-zero when `report.errors` is non-empty** so a cron alerts. A
  sweep that ended `"partial"` must not look like success.
- `JiraDependencyError` → `raise click.ClickException(str(exc))`, so the user
  sees one actionable line naming `ai-parrot[jira]`, not a traceback.
- `JiraAuthError` → likewise, one line.

### Key Constraints

- **Append-only edit to `cli.py`.** No reformatting, no import reshuffling, no
  touching a neighbouring command. `cli.py` is contested (§7).
- Lazy imports inside the command body, mirroring `build` at `:1118-1121`, so
  `wikitoolkit --help` never pays for `jira`.
- The command must appear in `wikitoolkit --help`.
- `--enrich` raises `ClickException("--enrich is not implemented in v1 ...")`.
- Never write inside the repository working tree (G8) — the path comes from
  `resolve_issues_dir`.
- Google-style docstring on the command (it is the user-facing help text).

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1044-1215` — `build`,
  the command whose structure and build path this reuses
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3030-3300` — `ingest`
  (FEAT-451), the most recently added command; match its option style
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1826-1978` — `ns add`,
  for the registration command the runbook documents
- `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` — existing CLI test
  style (`click.testing.CliRunner`)

---

## Acceptance Criteria

- [ ] `wikitoolkit ingest-jira --help` works and lists every option in the
      spec's CLI surface.
- [ ] `wikitoolkit --help` lists `ingest-jira`.
- [ ] Scope resolution follows `--jql` → `--project` → `JIRA_WIKI_JQL` →
      `project = ${JIRA_DEFAULT_PROJECT}`; `--jql` with `--project` is an
      error; nothing resolvable is a `ClickException` naming both.
- [ ] **G10**: the command builds the plane with no extra flag — after a run,
      `<issues-dir>/.parrot/wiki/wiki.db` exists. `--no-build` leaves it
      absent.
- [ ] The build is invoked in **vault mode** (`vault_mode=True`), never
      auto-detected.
- [ ] `--dry-run` writes nothing at all — no documents, no state file, no
      `wiki.db` — and still prints accurate counts.
- [ ] `--json` emits only valid `SweepReport` JSON.
- [ ] Exit code is non-zero when the sweep recorded errors.
- [ ] With `jira` absent, the command fails with a single line naming
      `ai-parrot[jira]` — no traceback.
- [ ] `--enrich` fails fast with "not implemented in v1".
- [ ] `wikitoolkit --help` still works with `jira` absent (no eager import).
- [ ] The command does **not** self-register the namespace.
- [ ] `git diff packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` shows an
      **append only** — no hunk inside any pre-existing command.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_ingest_jira.py -v`
- [ ] Existing CLI tests still pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_cli_ingest_jira.py
import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestHelpAndRegistration:
    def test_command_is_registered(self, runner):
        result = runner.invoke(wiki, ["--help"])
        assert result.exit_code == 0
        assert "ingest-jira" in result.output

    def test_help_lists_every_option(self, runner):
        result = runner.invoke(wiki, ["ingest-jira", "--help"])
        assert result.exit_code == 0
        for opt in ("--jql", "--project", "--since", "--issues-dir",
                    "--build", "--no-build", "--enrich", "--force",
                    "--dry-run", "--json", "--quiet"):
            assert opt in result.output

    def test_help_works_without_jira_installed(self, runner, monkeypatch):
        """Lazy import: --help must never pay for `jira`."""
        import builtins
        real = builtins.__import__

        def blocked(name, *a, **k):
            if name == "jira":
                raise ModuleNotFoundError("No module named 'jira'")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", blocked)
        assert runner.invoke(wiki, ["ingest-jira", "--help"]).exit_code == 0


class TestScopeResolution:
    def test_project_shorthand(self, runner, monkeypatch, tmp_path):
        seen = {}

        async def fake_sweep(interface, issues_dir, *, jql, **kw):
            from parrot.knowledge.wiki.jira_sync import SweepReport
            seen["jql"] = jql
            return SweepReport()

        monkeypatch.setattr("parrot.knowledge.wiki.jira_sync.sweep_jira_issues",
                            fake_sweep)
        runner.invoke(wiki, ["ingest-jira", "--project", "NAV", "--no-build",
                             "--issues-dir", str(tmp_path)])
        assert seen["jql"] == "project = NAV"

    def test_jql_and_project_together_is_an_error(self, runner, tmp_path):
        result = runner.invoke(wiki, ["ingest-jira", "--jql", "project = X",
                                      "--project", "NAV", "--no-build",
                                      "--issues-dir", str(tmp_path)])
        assert result.exit_code != 0

    def test_env_default(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_WIKI_JQL", "project = ENV")
        ...

    def test_unresolvable_scope_is_a_click_exception(self, runner, monkeypatch,
                                                    tmp_path):
        monkeypatch.delenv("JIRA_WIKI_JQL", raising=False)
        monkeypatch.delenv("JIRA_DEFAULT_PROJECT", raising=False)
        result = runner.invoke(wiki, ["ingest-jira", "--no-build",
                                      "--issues-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "--jql" in result.output and "JIRA_WIKI_JQL" in result.output


class TestBuildByDefault:
    def test_builds_by_default(self, runner, monkeypatch, tmp_path):
        """G10 — the plane can never silently lag the files."""
        called = {"build": 0, "vault_mode": None}

        def fake_build_callback(**kw):
            called["build"] += 1
            called["vault_mode"] = kw.get("vault_mode")

        ...  # patch build.callback, patch sweep, then:
        # assert called["build"] == 1 and called["vault_mode"] is True

    def test_no_build_skips_it(self, runner, monkeypatch, tmp_path):
        ...

    def test_dry_run_skips_build(self, runner, monkeypatch, tmp_path):
        ...


class TestReportingAndExitCodes:
    def test_json_output_is_valid_sweep_report(self, runner, monkeypatch,
                                               tmp_path):
        ...
        # json.loads(result.output) parses and has the SweepReport keys

    def test_nonzero_exit_when_sweep_had_errors(self, runner, monkeypatch,
                                                tmp_path):
        """A 'partial' sweep must not look like success to cron."""
        ...

    def test_unresolved_links_warning_shown(self, runner, monkeypatch,
                                             tmp_path):
        """The operator's signal to widen the JQL (vault_scan.py:183)."""
        ...

    def test_quiet_prints_one_line(self, runner, monkeypatch, tmp_path):
        ...


class TestFailureModes:
    def test_missing_jira_dependency_is_one_line(self, runner, monkeypatch,
                                                  tmp_path):
        from parrot.interfaces.jira import JiraDependencyError

        async def boom(*a, **k):
            raise JiraDependencyError("install ai-parrot[jira]")

        ...
        # assert "Traceback" not in result.output
        # assert "ai-parrot[jira]" in result.output

    def test_enrich_fails_fast(self, runner, tmp_path):
        result = runner.invoke(wiki, ["ingest-jira", "--enrich", "--no-build",
                                      "--issues-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "not implemented" in result.output.lower()


class TestNoSelfRegistration:
    def test_does_not_register_a_namespace(self, runner, monkeypatch, tmp_path):
        """ns add is the ONLY writer of namespace entries (ns_add docstring)."""
        import inspect
        from parrot.knowledge.wiki import cli
        src = inspect.getsource(cli.ingest_jira)
        for banned in ("ns_add", "save_namespace", "wikis.json"):
            assert banned not in src, banned


class TestAppendOnlyEdit:
    def test_existing_commands_untouched(self):
        """cli.py is contested — the diff must be append-only."""
        # Run manually as part of verification:
        #   git diff -U0 packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
        # and confirm no hunk falls inside a pre-existing command body.
        pytest.skip("manual verification step — see acceptance criteria")
```

> The `...` bodies are placeholders to fill against the real code. Patch
> `sweep_jira_issues` and `build.callback` rather than reaching Jira or
> building a real plane in a unit test — the end-to-end path is covered by
> TASK-2405.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§2 "CLI surface" + "Configuration keys", §3 M5, §7 "cli.py is a 123 KB hot file", G8/G10, and §8's resolved default-JQL decision) for full context
2. **Check dependencies** — TASK-2403 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - `grep -n 'ingest-jira' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
     (must be empty)
   - Read `cli.py:1044-1215` (`build`) in full — you are reusing its build path
   - Read `cli.py:3030-3140` (`ingest`) for the newest option style
   - Confirm `build.callback`'s exact parameter names at `cli.py:1081-1092`
   - Confirm `build.callback(...)` is invocable outside a click context; if
     not, use `ctx.invoke(build, ...)` with `@click.pass_context`
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above.
   Append the command; touch nothing else in `cli.py`.
6. **Verify** all acceptance criteria are met — including the append-only
   diff check
7. **Move this file** to `sdd/tasks/completed/TASK-2404-wikitoolkit-ingest-jira-command.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Build-path reuse**: `build.callback(...)` | `ctx.invoke(build, ...)` | replicated (and why)
**`no_export` / `no_graph` decision**: (and rationale)

**Deviations from spec**: none | describe if any
