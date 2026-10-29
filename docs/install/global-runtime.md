# Global install: the parrot-managed runtime (reference)

> The install and first-use guide is [docs/getting-started.md](../getting-started.md); this page holds the detail.

`--global` installs AI-Parrot once per machine under `~/.parrot` (or `$PARROT_HOME`): a pinned `uv`, a
uv-managed Python 3.12, `~/.parrot/venv` (`ai-parrot` plus `ai-parrot-tools` at the same version, which
`wikitoolkit mcp` needs) and `parrot` / `wikitoolkit` / `bookstore` on PATH. Your existing `~/.parrot` data
(`wikis.json`, `library/`, `skills/`, `brains/`, `parrot.db`) is never touched; the installer only adds
`bin/`, `venv/` and `python/`, and a failed run removes only what it created.

## What the installer checks and prints

Before writing anything the installer runs a read-only gate, in this order:

1. platform: Linux x86_64 / aarch64, macOS arm64 (Windows x64 for the PowerShell installer);
2. a download tool (`curl` or `wget`) and a checksum tool (`sha256sum` or `shasum`; `Get-FileHash` on Windows);
3. `git`;
4. a writable `PARROT_HOME` (its nearest existing ancestor) with at least 2 GiB free;
5. `https://github.com` and `https://pypi.org/simple/` reachable (skipped under `--dry-run`).

A failure prints `preflight: <what> - fix: <how>` and exits before any file is created. Then the script prints
its plan, which reads:

```text
This installer will download uv 0.11.28 from <url> and verify it against <url>.sha256,
create $PARROT_HOME/{bin,venv,python} (a uv-managed Python 3.12 and a venv with <ai-parrot spec>),
and add $PARROT_HOME/bin to PATH via a marker block in your shell profile.
If missing, it writes a commented-out credentials file $PARROT_HOME/env/.env (mode 0600)
and an empty navconfig $PARROT_HOME/etc/config.ini.
A uv already on your PATH is never used or modified. Existing $PARROT_HOME data is never touched.
Prefer not to pipe a download into bash? Fetch <raw>/install-parrot.sh and
<raw>/SHA256SUMS, run 'sha256sum -c --ignore-missing SHA256SUMS', read the script, then run it.
```

After installing it runs `parrot self doctor --runtime-only`. Only runtime failures (uv, Python, entry points,
PATH) roll the run back; repository readiness never does.

Then it runs `parrot self env --init`, which creates the credentials file and an empty `etc/config.ini` when
they are missing. A failure here only prints a warning.

## Credentials (`$PARROT_HOME/env/.env`)

ai-parrot reads its credentials through navconfig. For the managed runtime, navconfig's project root is
`$PARROT_HOME`, and it reads `env/.env` there while `ENV` is unset, or `env/<ENV>/.env` when you `export ENV=<name>`.

The installer writes that file owner-only: mode `0600` on Linux and macOS, an ACL granting only your user on
Windows. It lists the variables the bundled LLM clients read
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, ...), all commented out, so you only uncomment and fill
the ones you use.

`parrot self env --init` creates the file at any time; it is a no-op when the file exists. It also creates an empty
`$PARROT_HOME/etc/config.ini`, which navconfig reads for INI settings. Without that file, every command logs
"INI file doesn't exists". An empty file changes no setting. The file is never
overwritten by a re-install or `self update`, and `self uninstall` keeps it.
If you export `SITE_ROOT`, navconfig uses that directory as its root instead, and reads `$SITE_ROOT/env/...`.

## Install (Linux / macOS)

```bash
curl -fsSLO https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.sh
curl -fsSLO https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS   # macOS: shasum -a 256 -c --ignore-missing SHA256SUMS
bash install-parrot.sh --global --with sdd
```

## Install (Windows, PowerShell)

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.ps1 -OutFile install-parrot.ps1
Invoke-WebRequest https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/SHA256SUMS -OutFile SHA256SUMS
(Get-FileHash install-parrot.ps1).Hash        # compare with the install-parrot.ps1 line of SHA256SUMS
powershell -ExecutionPolicy Bypass -File install-parrot.ps1 -Global -With sdd
```

The installer edits the USER PATH (never the Machine PATH); reopen the terminal afterwards. The `-Global`
switch accepts `-Version`, `-With` and `-DryRun`, mirroring the POSIX flags.

Flags: `--version <X>` pins `ai-parrot` and `ai-parrot-tools`, `--python <v>` picks the managed Python
(default 3.12), `--with a,b` runs `parrot self add` per component, `--dry-run` prints the plan only.

## Managing the runtime

<!-- verify: cli-verb=self env -->
<!-- verify: flag=self env:--init -->
<!-- verify: cli-verb=self doctor -->
<!-- verify: flag=self doctor:--sdd -->
<!-- verify: flag=self doctor:--runtime-only -->
<!-- verify: cli-verb=self add -->
<!-- verify: flag=self add:--here -->
<!-- verify: cli-verb=self update -->
<!-- verify: flag=self update:--version -->
<!-- verify: cli-verb=self uninstall -->
<!-- verify: flag=self uninstall:--yes -->
```bash
parrot self env
parrot self env --init        # create $PARROT_HOME/env/.env and etc/config.ini if missing
parrot self doctor            # runtime + host configs + components (+ SDD readiness when sdd/ exists)
parrot self doctor --sdd      # SDD readiness checks forced
parrot self add scraping
parrot self add scraping --here
parrot self update
parrot self uninstall --yes
```

- `self env` prints the venv the launcher resolves, the rule that picked it, and versions. `--init` creates the
  navconfig files instead (see above).
- `self doctor` diagnoses the runtime, host configs and toolkit requirements; it exits 1 only when a
  non-informational check in the selected scope fails. `--sdd` forces the repository-readiness checks (origin
  remote, base branch, committed ledger, worktrees ignore, `.gitattributes` block, ledger git hooks, `gh` auth,
  `jq`, SDD files current; host CLIs informational). `--runtime-only` is the bootstrap's scope (managed uv,
  Python, entry points, PATH) and is mutually exclusive with `--sdd`.
- `self add <component>` installs a component's packages (and post-install step) into the managed venv.
  `--here` installs into the project venv instead, and is the only way a dependency enters a project venv.
- `self update` upgrades `ai-parrot` in the managed venv; `--version` pins an exact release.
- `self uninstall` removes `bin/`, `venv/` and `python/`; wikis, library, skills, brains, `parrot.db`, `env/`
  (credentials) and `etc/` stay.

## Which venv runs? (launcher resolution)

From the managed venv, `parrot` / `wikitoolkit` / `bookstore` re-exec into, in order: `PARROT_VENV`; the
project venv (a worktree's own `.venv` first, then the main checkout's); `VIRTUAL_ENV`; else the managed venv.
A project `.venv` without the command is skipped with one stderr warning per session. Outside the managed venv
nothing changes.

## Committable host config: `--portable`

<!-- verify: flag=claude install:--portable -->
<!-- verify: flag=codex install:--portable -->
<!-- verify: flag=google install:--portable -->
```bash
parrot claude install --portable
parrot codex install --portable
parrot google install --portable
```

The default stays baked absolute paths. `--portable` writes bare launcher commands (`wikitoolkit`, `parrot`,
`bookstore`) that need the global launcher on PATH, so the file can be committed:

- Claude Code: `.mcp.json` entries and the `PreToolUse` hook use bare commands; no `PARROT_PROJECT` pin is
  emitted, the host's cwd scopes the project.
- Codex: bare `wikitoolkit` / `parrot` commands and the relative toolkit `--config`, no absolute `cwd`;
  the project comes from the host cwd or a `PARROT_PROJECT` you set.
- Google Antigravity: bare commands with no absolute paths or `cwd`, which a multi-repo-safe
  `~/.gemini/config/mcp_config.json` requires.

Stickiness: `parrot toolkits` re-emits a host's toolkit entries in portable form if, and only if, that host's
current managed `wikitoolkit` entry is already portable. `.mcp.json.example` deliberately keeps the resolver
form for monorepo developers: the portable form only works once the global install puts `wikitoolkit` on PATH.

## The SDD flow in any repository

<!-- verify: cli-verb=sdd install -->
<!-- verify: flag=sdd install:--host -->
<!-- verify: flag=sdd install:--dry-run -->
<!-- verify: flag=sdd install:--force -->
<!-- verify: cli-verb=sdd status -->
<!-- verify: cli-verb=sdd uninstall -->
<!-- verify: flag=sdd uninstall:--dry-run -->
<!-- verify: cli-verb=sdd run -->
```bash
parrot sdd install --host claude --dry-run
parrot sdd install --host claude
parrot sdd status
parrot sdd run reserve_ids --kind task --count 1 --base-branch dev --label demo
parrot sdd uninstall --dry-run
```

- Helpers run as `parrot sdd run <name>`, never `python -m ...`: in a global-only install the repo's `python`
  cannot import parrot.
- `sdd/.sdd-installed.json` records every file parrot wrote with its hash. `parrot sdd status` reports each
  asset as `missing | current | outdated | edited | foreign`, and seeds as `seed-present | missing`.
- Upgrade rule: a file whose hash matches the record is upgraded; one that differs is kept with a warning
  unless `--force`; one parrot did not write is skipped. Seeds are never overwritten, even with `--force`.
- `parrot sdd uninstall` removes only files parrot wrote and you have not edited; seeds and state are kept.
- It also seeds `sdd/tasks/.id_ledger.json` and a `.claude/worktrees/` ignore block, writes a marked
  `.gitattributes` block (`merge=union` for the shared ledger log, recorded in the receipt) and installs the four
  `parrot-ledger` git hooks; `parrot self doctor --sdd` checks both.
- `sdd/config.json` fields: `base_branch` (default `dev`), `staging_branch`, `hotfix_base` (default `main`),
  `issue_tracker` (`jira` | `none`), `jira_host`, `reviewer` (`codex` | `none`), `test_command`, `projects`.
- `test_command`: when set (non-blank), `cache_test_contract` in `/sdd-task` and `select_tests` / `test_report`
  in `/sdd-done` are skipped and the command runs once from the repo root; a non-zero exit blocks the merge and
  a run that executed zero tests is reported as "not run", never as passing. When null, the ai-parrot selection
  steps apply and, if the FEAT-699 kernel cannot be loaded or the planned test runner (e.g. `pytest`) is not
  installed, they stop with a one-line message. `parrot sdd install` warns when it is null.
- `sdd/CONVENTIONS.md` is a seed with `## Repository layout` and `## Project areas`; created once, never
  overwritten. `/sdd-insight` is not installed.

## Version skew

If `wikitoolkit` (or any wiki code) opens a store written with a newer schema than the running runtime, it
refuses with `WikiStoreVersionError`:

```text
wiki store <db> has schema version <n>, newer than this runtime's <m> (ai-parrot <running>). This store was
written by ai-parrot <release>; upgrade to ai-parrot >= <release>: `parrot self update` (managed runtime) or
`parrot self add --here` (project venv).
```

The gate compares the store's schema number only. `min_runtime_version` is stamped and quoted in the message
but informational: a store written by a newer release with the same schema opens normally. Runtimes older than
this release have no gate. The fix is `parrot self update` (managed) or `parrot self add --here` (project venv).

## Windows notes

The PowerShell installer needs an x64 Windows with PowerShell 5.1+ (`Invoke-WebRequest`, `Get-FileHash`),
verifies the uv zip with `Get-FileHash`, and edits only the USER PATH; a rollback is designed to restore the
original value.

> **Windows status (pending CI verification):** the `-Global` path has not yet run on a Windows runner. CI checks the script's syntax, its `-DryRun` plan and its pre-write gates under `pwsh` on Linux; the install itself, the post-install rollback and the USER PATH restore are covered only by an offline harness that is still marked expected-to-fail. They become verified claims when the install-matrix Windows leg passes.
