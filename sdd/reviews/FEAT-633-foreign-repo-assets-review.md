<!--
FEAT-633 — foreign-repository review of the shipped SDD assets (2026-10-30).
Produced by an independent Claude review subagent; verified the same day by Jesus Lara, who corrected two causes:
- B4: the fix is not the foreign repo's .gitignore — worker logs move to ${SDD_LOGS_ROOT:-/tmp/claude-$(id -u)/sdd-logs}
  (the FEAT-764 hook-context pattern).
- B5: brief_meta.py already reads sdd/config.json; the bug is the installed /sdd-brief prompt.
Group 1 (B1–B5, B11, B12, B14 and the qa-runner part of B2) is fixed by commit 5e95cabbf (spec rev 0.8 C29);
the rest is in the SDD ledger, discovered_from spec:FEAT-633. Line numbers refer to the assets before 5e95cabbf.
-->

# Review: `parrot sdd install` assets in a foreign repository

Worktree: `.claude/worktrees/feat-FEAT-633-parrot-installer` (branch `feat-FEAT-633-parrot-installer`), read-only review.
Nothing under `sdd/references/` was read.

## Scope and method

What gets installed, and where it lands, comes from `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` plus
`installer.py`. The asset paths in this report are the **installed target paths**. Line numbers are identical to the
packaged copies: `scripts.sdd.check_asset_sync --check` exits 0, so the assets are byte-identical to the repo
sources.

| Packaged source | Installed target | Hosts |
|---|---|---|
| `claude/commands/sdd-*.md` | `.claude/commands/sdd-*.md` | claude, codex, google |
| `claude/agents/*.md` (sdd-*, code-reviewer, qa-runner) | `.claude/agents/*.md` | claude |
| `claude/rules/worktree-management.md`, `claude/hooks/sdd-worker-format.sh`, `claude/skills/second-opinion/SKILL.md` | same under `.claude/` | claude |
| `agents/skills/sdd-*/SKILL.md` | `.agents/skills/…` | codex, google |
| `agents/agents/sdd-*/agent.md` | `.agents/agents/…` | google |
| `agent/workflows/sdd-*.md` | `.agent/workflows/…` | google |
| `codex/agents/sdd-worker.toml` | `.codex/agents/sdd-worker.toml` | codex |
| `sdd/WORKFLOW.md`, `sdd/CONVENTIONS.md` (seed), `sdd/sdd_templates/*` | `sdd/WORKFLOW.md`, `sdd/CONVENTIONS.md`, `sdd/templates/*` | all |
| `sdd/CODEX.md` | `docs/sdd/CODEX.md` | codex, google |

The installer also writes these, outside the asset tree:

- a `.gitignore` block containing **only** `.claude/worktrees/` (`installer.py:43-45`)
- a `.gitattributes` block
- four `parrot-ledger` git hooks
- `sdd/tasks/.id_ledger.json`, `sdd/config.json` and `sdd/.sdd-installed.json`

The global runtime exposes only `parrot`, `wikitoolkit` and `bookstore` as shims, plus `uv` in `~/.parrot/bin`
(`scripts/install/install-parrot.sh:280,306`). It installs `ai-parrot` and `ai-parrot-tools`, and does **not**
install `ai-parrot-server`.

### What I checked

- **Helper registry.** `parrot sdd run` accepts every module under `parrot.sdd.scripts` (`cli.py:53-58`). All 21
  helper names used in the assets exist and have a `__main__` guard. I ran `--help` against every referenced helper
  and its subcommands. They match the flags documented in the assets; truncated forms are only prose line-wraps.
- **`wikitoolkit` CLI.** Every `wikitoolkit …` / `wikitoolkit ledger …` verb and flag the assets use exists (checked
  with `--help`).
- **`parrot` CLI.** `parrot e2e` exists only as a lazy command from `ai-parrot-server` (`cli/__init__.py:198`), which
  the global runtime lacks. The E2E gate treats a missing server as "MISSING evidence" and the default policy is
  `optional`, so it does not break by default.
- **Result.** No dangling `parrot sdd run` helper names, invalid helper flags or invalid `wikitoolkit` verbs were
  found. The issues below are of other kinds.

---

## (a) Findings that break the workflow in a foreign repo

### B1. `/sdd-task` requires pytest-only Validation Commands, and its own gate rejects anything else (non-Python repos)

- **Where:**
  - `.claude/commands/sdd-task.md:430-445` and `:477-497`
  - `.agent/workflows/sdd-task.md:426-441`
  - `.agents/skills/sdd-task/SKILL.md:105`
- **Text:**
  - "Every generated task MUST carry a `## Validation Commands` section … each a backticked `pytest` invocation"
  - "New per-spec index headers MUST include `"validation_contract": "required"`"
  - §4b: "**Errors** (exit 1) block the commit"
- **Why it fails:** `check_task_graph` emits the **error** `non-pytest-validation-command` for any command that is
  not pytest (`check_task_graph.py:306-318`), whatever `sdd/config.json` says (the file never reads
  `test_command`).
  - In a JS, Go or Rust repo `/sdd-task` cannot commit its tasks unless it writes pytest commands that can never run.
  - The `test_command` switch only relaxes `cache_test_contract`, not this gate.
  - §4b's list of validation errors does not even name `non-pytest-validation-command`.
- **Verified:** I built a scratch repo with a task whose command is `npm test -- src/x.test.ts` and ran
  `python -m parrot.sdd.scripts.check_task_graph sdd/tasks/index/x.json`. It printed
  `ERROR non-pytest-validation-command …` and exited 1. `grep test_command check_task_graph.py` finds nothing.
- **Severity:** breaks (every non-Python repo).

### B2. `qa-runner` treats a missing `.venv` as a hard failure and needs `ruff` to pass

- **Where:** `.claude/agents/qa-runner.md` (a packaged-only, hand-maintained asset), lines 40-42, 56-59, 81-90 and
  136-138.
- **Text:**
  - "**Activate the venv first.** … ALWAYS `source .venv/bin/activate` before any `python`/`pytest`/`ruff`/`mypy`/`uv` command"
  - Line 58: `source .venv/bin/activate`
  - "`PASS` only if … `ruff` returns 0"
  - "Only hard errors (worktree path missing, `.venv` absent, git not a repo) are true failures; surface those plainly so the autopilot can stop."
- **Why it fails:**
  - A foreign repo has no `.venv`, so the QA stage reports a hard error and `sdd-autopilot` stops.
  - In a non-Python repo `ruff` is absent or meaningless, so the verdict can never be PASS.
- **Verified:** read the file. Running `parrot.sdd.audit.scan_paths` over `_assets/` flags lines 41 and 58 as
  `venv-path`, but no test gates `venv-path` on shipped files.
- **Severity:** breaks (the `sdd-autopilot` QA stage, claude host).

### B3. `/sdd-done` hook-context writer needs a `python` binary; without one the pre_pr step aborts closeout

- **Where:** `.claude/commands/sdd-done.md:198-226` (`write_hook_context`), used at `:334-347`.
- **Text:** `HOOK_ABORT_REASON="$1" DRY_RUN="${DRY_RUN:-}" python - "$HOOKS_DIR/context.json" <<'PY'`
- **Why it fails:** the global runtime puts no `python` on PATH, and many hosts ship only `python3`. When `python` is
  missing:
  1. `context.json` is never written.
  2. `parrot sdd run run_closeout_hooks --context …` hits an OSError on `read_text` and returns `EXIT_USAGE` = 2
     (`run_closeout_hooks.py:31,320-326`).
  3. The §4.8 table maps exit 2 to "run on_failure, then abort before Step 7".

  This happens even when the repo has no `.parrot/sdd_hooks.toml`. The script itself is stdlib-only, so only the
  binary name is wrong.
- **Verified:**
  - `env -i PATH=/usr/local/bin:/usr/bin:/bin command -v python` finds nothing on this Linux host (only `python3`).
  - The installer's shim list is at `install-parrot.sh:306`.
  - I read `run_closeout_hooks.main`.
- **Severity:** breaks on any host without a `python` alias.

### B4. Workflow output in un-ignored paths; `/sdd-done` cannot remove the worktree

- **Where (writers):**
  - `.claude/agents/sdd-worker.md:573-575`: `mkdir -p artifacts/logs; parrot sdd run select_tests … --run > artifacts/logs/merge-tests-TASK-<NNN>.log 2>&1`, run inside the worktree.
  - Also `.claude/agents/sdd-worker.md:481`, `.codex/agents/sdd-worker.toml:91`, `.agents/skills/sdd-start/SKILL.md:123` and `docs/sdd/CODEX.md:404`, all writing to `artifacts/logs/`.
- **Where (false "ignored" claims):**
  - `.claude/agents/sdd-coder.md:193`: "`artifacts/` is ignored repo-wide"
  - `.claude/commands/sdd-brief.md:124` and `.agent/workflows/sdd-brief.md:128`: "This location is git-ignored" (`sdd/state/.brief/`)
  - `.agents/skills/sdd-brief/SKILL.md:24,38`
  - `.claude/commands/sdd-spec.md:54` and `.agent/workflows/sdd-spec.md:58` (`sdd/state/.intake/` "git-ignored")
  - `sdd/WORKFLOW.md:367`
- **Why it fails:** these paths are ignored only by ai-parrot's own `.gitignore` (lines 286, 392, 418, 420, 423,
  425, 427). The installer's managed block adds only `.claude/worktrees/`.
  - In a foreign repo, `artifacts/logs/*.log` stays untracked inside the feature worktree.
  - `/sdd-done` §11 (`sdd-done.md:869`, `git worktree remove "$WORKTREES_DIR/feat-…"`) then refuses, and the rules
    forbid `--force`.
  - `sdd/state/.brief|.intake|.design_research` and the ledger's `.parrot/` are also left untracked in the primary
    checkout.
- **Verified:** scratch repro of `git worktree remove` on a worktree that contains an untracked
  `artifacts/logs/merge.log` → `fatal: '../wt' contains modified or untracked files, use --force to delete it`
  (exit 128). Checked `GITIGNORE_BLOCK` in `installer.py` and grepped ai-parrot's `.gitignore`.
- **Severity:** breaks (cleanup of any worktree where the sequential `sdd-worker` lane ran). The "git-ignored"
  statements are false in every foreign repo.

### B5. `/sdd-brief` hard-codes `main`/`dev`/`staging` instead of `sdd/config.json`

- **Where:**
  - `.claude/commands/sdd-brief.md:28-30` and `:61`
  - `.agent/workflows/sdd-brief.md:32-34` and `:65`
- **Text:**
  - "Accept only `main`, `dev`, or `staging` for `--base-branch`"
  - "For every other source, default to `main` unless `--base-branch` overrides it"
  - The command then passes `--base-branch <base>` to `ensure_worktree`.
- **Why it fails:** the helper allows the *configured* branches (`brief_base_branches(config)`,
  `brief_meta.py:34-71`), and `ensure_worktree` defaults a brief to `cfg.hotfix_base` (`ensure_worktree.py:341`).
  - In a repo configured with, say, `base_branch: develop` / `hotfix_base: master`, the command refuses the valid
    branch.
  - It then passes `--base-branch main`, which `_check_base_branch` rejects with "base_branch must be one of [...]".
  - The Codex skill (`.agents/skills/sdd-brief/SKILL.md:30-33`) is already config-aware; the Claude and Google twins
    are not.
- **Verified:** read the helper code alongside both twins.
- **Severity:** breaks (any repo whose branches are not literally `main`/`dev`/`staging`).

### B6. Jira commands carry the ai-parrot org's project, component, labels and custom-field IDs as defaults

- **Where:**
  - `.claude/commands/sdd-tojira.md` (same lines in `.agent/workflows/sdd-tojira.md`):
    - `:31` "`--project <KEY>` … (default: `NAV`)"
    - `:36` "Default target: Project `NAV`, Component `Nav-AI`"
    - `:54`, `:104` `jql="project = NAV …"`
    - `:195-216` `project_key="NAV"`, `components="Nav-AI"`, `"labels": ["ai-parrot", "memory"]`
    - `:237`, `:251`
    - `:261-272` `customfield_10021/10022/10035`
    - `:303`, `:319`, `:388`
  - `.agents/skills/sdd-tojira/SKILL.md:31,34`
  - `.claude/commands/sdd-fromjira.md:60,73,99`, which reads acceptance criteria from `customfield_10021/10022/10035`
  - `.claude/agents/sdd-autopilot.md:108`
- **Why it fails:** custom-field IDs and project/component keys are specific to one Jira instance.
  - On another org's Jira, `/sdd-tojira` with no `--project` targets `NAV`/`Nav-AI`: a 400 error, or the wrong
    project if `NAV` happens to exist.
  - AC writes and reads use non-existent fields, so `/sdd-fromjira` silently returns empty AC.
  - `SddConfig` has `jira_host` but no project or component field (`extra="forbid"`, `config.py:19-35`), so there is
    nowhere to configure them.
- **Verified:**
  - grep of the assets, and read `config.py`.
  - The `org-data` audit does not catch these: `TICKET_KEY_RE` needs digits (`NAV-XXXX` and bare `NAV` do not
    match), and custom-field IDs are not scanned.
- **Severity:** breaks (any repo with `issue_tracker: jira`).

### B7. `/sdd-brief` says "Fetch with `jiratoolkit`", which is not a runnable command

- **Where:**
  - `.claude/commands/sdd-brief.md:43`: `| Jira | Jira key | Fetch with \`jiratoolkit\` |`
  - `.agent/workflows/sdd-brief.md:47`
  - `.agents/skills/sdd-brief/SKILL.md:32`
- **Why it fails:** there is no `jiratoolkit` executable; `[project.scripts]` has only `parrot`, `parrot-graphindex`,
  `wikitoolkit` and `bookstore`.
  - `parrot jiratoolkit` (from ai-parrot-tools) has only `auth`, `status`, `logout` and `sync-kb`
    (`parrot_tools/jira_cli.py:261-395`). There is no issue fetch.
  - The Python `JiraToolkit` cannot be imported by the foreign repo's `python`.
  - Unlike `/sdd-fromjira`, no MCP or curl fallback is given here.
- **Verified:** `cli/__init__.py:196` lazy registry, `jira_cli.py` command list, `pyproject.toml:205-212`.
- **Severity:** breaks (Jira-sourced `/sdd-brief`).

### B8. `/remove-worktree` is referenced but never installed

- **Where:**
  - `.claude/commands/sdd-fix.md:46`, `.agent/workflows/sdd-fix.md:50` and `.agents/skills/sdd-fix/SKILL.md:51`:
    "reap the tree: `/remove-worktree` for `fix-…`", in the Fast lane's mandatory reap step.
  - `.claude/rules/worktree-management.md:67,75`
  - `.claude/commands/sdd-status.md:83,196`, `.agent/workflows/sdd-status.md:83,196` and
    `.agents/skills/sdd-status/SKILL.md:39`
- **Why it fails:** `remove-worktree` is a repo-only command (`.claude/commands/remove-worktree.md`). It is not in
  `ASSET_SOURCES` or the manifest.
  - `/sdd-fix` names it as the only reap mechanism and forbids `--force`.
  - In worktree-management and sdd-status, `git worktree remove` is also offered, so those mentions are only
    dangling hints.
- **Verified:** manifest grep; `ls .claude/commands/`.
- **Severity:** breaks for `/sdd-fix`'s Fast-lane reap; cosmetic elsewhere.

### B9. `sdd-autopilot` Stage 5 calls a command that is not installed, and uses different Jira env-var names

- **Where:**
  - `.claude/agents/sdd-autopilot.md:437` (also `:101`, `:725`): `claude -p "/pr-review $PR_URL $JIRA_KEY --auto-draft"`
  - Same in `.agents/agents/sdd-autopilot/agent.md:444`
  - `.claude/agents/sdd-autopilot.md:102-103` and `:774-775` (Google twin `:111-112` and `:779-780`):
    `curl -s -u "$JIRA_USERNAME:$JIRA_TOKEN" "$JIRA_SERVER_URL/rest/api/3/…"`
- **Why it fails:**
  - `/pr-review` is repo-only (`.claude/commands/pr-review.md`), not in the manifest. Stage 5 runs whenever the spec
    has a Jira key.
  - Every other asset uses `JIRA_API_TOKEN` / `JIRA_INSTANCE`. With only those set, the autopilot's Jira fetch
    (stage 1) and completion comment use empty credentials.
- **Verified:** manifest grep; grep of every `$JIRA_*` variable across the assets.
- **Severity:** breaks (autopilot with Jira).

### B10. The Google-host `sdd-autopilot` subagent dispatches Claude agents the google install does not ship

- **Where:** `.agents/agents/sdd-autopilot/agent.md:334-409`:
  `claude --agent sdd-worker …`, `claude --agent code-reviewer`, `claude --agent qa-runner`.
  It also cites `.claude/agents/*.md` at `:34`, `:299`, `:552` and `:798-799`.
- **Why it fails:** for `--host google`, every `.claude/agents/*` target is `hosts: ["claude"]` in the manifest, and
  the stage loop also needs the `claude` CLI.
- **Verified:** manifest. `test_agents_dispatched_by_packaged_autopilot_are_installed`
  (`tests/sdd/test_installer.py:419`) checks only the default claude install.
- **Severity:** breaks (google-only install).

### B11. `/sdd-fix` Fast lane validation is Python- and monorepo-specific, with no `test_command` branch

- **Where:**
  - `.claude/commands/sdd-fix.md:40-42`
  - `.agent/workflows/sdd-fix.md:44-46`
  - `.agents/skills/sdd-fix/SKILL.md:45-47`
- **Text:** "run the affected package's tests from `<wt>` with `PYTHONPATH` set to the worktree's package source (a
  bare `pytest` there imports the main checkout), `ruff check --fix` the changed files"
- **Why it fails:**
  - "Package source" and "bare `pytest` imports the main checkout" describe ai-parrot's editable shared venv.
  - Non-Python repos have no applicable step, and Python repos without ruff fail.
  - Unlike `/sdd-done`, `/sdd-task`, `qa-runner` and `sdd-worker`, there is no `test_command` alternative (no
    `test_command` match in any sdd-fix twin).
  - It slips past the C22 gate, which matches `PYTHONPATH=` (with `=`) only.
- **Verified:** read the files; grepped them for `test_command`.
- **Severity:** breaks (non-Python repos; Python repos without ruff).

### B12. `/sdd-done` §4.5 "Full Lint Pass" assumes ruff is the repo's linter

- **Where:**
  - `.claude/commands/sdd-done.md:161-191`
  - `.agent/workflows/sdd-done.md:138-153`
  - `.agents/skills/sdd-done/SKILL.md:90-95`
- **Text:**
  - "This step is the ONE place the repo's full ruff rule set is enforced"
  - `ruff check --fix --exit-zero …` then `git commit -m "style(<slug>): … full lint pass"`
  - "Residual syntax errors … are merge blockers"
- **Why it fails:** in a Python repo without ruff, the step fails ("command not found") and the merge-blocker
  bookkeeping is undefined. With ruff installed but not used by the repo, ruff's default rules auto-fix and commit
  style changes into the feature. Non-Python repos are a no-op (`*.py` filter). There is no CONVENTIONS- or
  config-driven switch. (`ruff` is also not in the install-time audit's `EXTERNAL_TOOLS`.)
- **Verified:** read the twins and `audit.py:22`.
- **Severity:** breaks (Python repos without ruff); unwanted commits otherwise.

### B13. `/sdd-start` ledger `task.started` emission imports `parrot` from the repo's `python3`, so it never runs

- **Where:** `.claude/commands/sdd-start.md:119-145` and `.agent/workflows/sdd-start.md:117-140` (from `:121`):

  ```bash
  python3 - "<TASK-NNN>" "<feature-slug>" <<'PYEOF' || true
  from parrot.knowledge.wiki.ledger.events import LedgerEvent
  ```
- **Why it fails:** in a global-only install the repo's `python3` cannot import `parrot`. The `try/except` plus
  `|| true` turns this into a silent no-op, so `task.started` is never recorded in a foreign repo.
- **Verified:** read the files. `test_no_inline_python_imports_parrot` matches only
  `python -c "…parrot.sdd.scripts"`, so it does not catch this. `parrot sdd run` has no ledger-emit helper.
- **Severity:** breaks (silently; ledger history loses `task.started`).

### B14. `worktree-management.md` "Create" block starts with `source .venv/bin/activate`

- **Where:** `.claude/rules/worktree-management.md:24`.
- **Why it fails:** a foreign repo has no `.venv`; `source` fails with "No such file or directory" (exit 1). Under
  `set -e`, or when the block is pasted with `&&`, the `ensure_worktree` lines never run. With the global launcher
  it is unnecessary anyway.
- **Verified:** read the file; the audit flags it as `venv-path`, and no test gates that on shipped files.
- **Severity:** breaks (the first command of the documented create step fails; harmless only if lines run one by
  one).

### B15. The design-research prompt tells codex the project is ai-parrot

- **Where:** `sdd/templates/design_research.prompt.md:15-16`, rendered by `parrot sdd run spec_tools render-brief`
  (`spec_tools.py:31`, `DEFAULT_PROMPT = Path("sdd/templates/design_research.prompt.md")`) and piped to
  `codex exec` in `/sdd-spec` §3b.
- **Text:** "You are an independent design reviewer for **ai-parrot**, an async-first Python framework for AI agents (aiohttp, Pydantic v2)."
- **Why it fails:** every foreign repo's design review is framed with the wrong project identity and stack, which
  biases its suggestions toward aiohttp and Pydantic.
- **Verified:** read the template and `spec_tools.py`.
- **Severity:** breaks semantically (wrong context in a live prompt); it does not crash.

### B16. Codex `sdd-worker` encodes branch rules that ignore `sdd/config.json`

- **Where:** `.codex/agents/sdd-worker.toml:63-68`.
- **Text:**
  - "Validate branch rules: feature defaults to dev … feature must not base on main … hotfix bases on main"
  - Line 63: "parse type/base_branch with parrot.sdd.scripts.sdd_meta" names a module, not `parrot sdd run sdd_meta`.
- **Why it fails:** `SddConfig` allows any distinct `base_branch` / `hotfix_base` (for example `base_branch: main`,
  `hotfix_base: production`). There, the Codex worker's own validation rejects every feature. The Claude twin
  (`sdd-worker.md:181-190`) is config-aware, since it aborts only when `base_branch == hotfix_base`. Line 63 invites
  `python -m parrot.sdd.scripts.sdd_meta`, which fails in a global-only install (see the `cli.py:138-140` docstring).
- **Verified:** read `config.py` and the TOML. `branch-literal` audit only matches operator positions
  (`origin/dev`, `--base dev`, …), not this prose.
- **Severity:** breaks (conditional on the repo's branch names).

---

## (b) Cosmetic / ai-parrot-flavoured or dangling-but-non-blocking

### C1. Dangling documentation paths (files the install does not write)

- **Not-installed docs:**
  - `sdd/WORKFLOW.md:57`: "The manual (no-command) procedure is in `docs/sdd/WORKFLOW.md`". Only `docs/sdd/CODEX.md`
    is installed.
  - `docs/sdd/ledger-outbox.md`, cited at `.claude/commands/sdd-done.md:534,579`,
    `.agent/workflows/sdd-done.md:409,451` and `.agents/skills/sdd-done/SKILL.md:200`.
  - `sdd/templates/sdd_hooks.example.toml:1`: "Docs: docs/sdd/closeout-hooks.md".
  - `docs/sdd/CODEX.md:446-448`: `[SDD Workflow](./WORKFLOW.md)`, `[SDD Guide](./GUIDE.md)`,
    `[SDD Platform](./PLATFORM.md)`, none of which is installed next to it.
- **Wrong path:** `sdd/templates/brainstorm.md:139,144` gives a "spec file at `docs/sdd/specs/<name>.spec.md`".
  Specs live in `sdd/specs/`; this is a legacy path even in ai-parrot.
- **Verified:** manifest. `test_non_claude_host_skills_have_every_file_they_read` checks only `](../…)` links from
  `.agents/skills`.

### C2. `AGENTS.md` / `.agent/CONTEXT.md` treated as present and authoritative

- **Where:**
  - `.agent/workflows/sdd-tojira.md:447`: "Auto-commit rule: `AGENTS.md` and `sdd/WORKFLOW.md`". The Claude twin
    points only at `sdd/WORKFLOW.md`, and a foreign `AGENTS.md` will not hold this rule.
  - `.codex/agents/sdd-worker.toml:12-13`
  - `.agents/skills/sdd-explain/SKILL.md:56-57`
  - `.agents/skills/sdd-start/SKILL.md:95`
  - `docs/sdd/CODEX.md:99,449`
  - `.claude/agents/code-reviewer.md:18`
  - `.claude/agents/qa-runner.md:40`
- **Why:** these files are not installed. The `claude-md-ref` audit matches only `CLAUDE.md`.

### C3. Stale or dangling cross-references

- `.claude/commands/sdd-proposal.md:136-137` (and its Google twin): "load `JIRA_INSTANCE` … via navconfig (see
  `/sdd-fromjira` for the eval snippet)". `/sdd-fromjira` no longer has a navconfig snippet; it expects exported
  env vars. navconfig is an ai-parrot dependency. (C22 only matches `from navconfig`.)
- `.claude/commands/sdd-fromjira.md:55` and `.agent/workflows/sdd-done.md:729` say the Jira env vars are exported
  "(see sdd/CONVENTIONS.md)", but the seeded `sdd/CONVENTIONS.md` has no Jira section.
- `.claude/skills/second-opinion/SKILL.md:7`: "the reviewer rules in `sdd/WORKFLOW.md` apply". `sdd/WORKFLOW.md`
  contains no reviewer rules (no CONFIRM/REJECT text).
- `.claude/commands/sdd-spec.md:239` (also the Google twin): "identical to the Adversarial Cross-Check in
  `.claude/agents/code-reviewer.md`". That file is not installed for codex or google; the rules are restated inline,
  so it is harmless.
- `.claude/commands/sdd-done.md:708`: "CI's `parrot.sdd.scripts.check_task_state` fails the PR". No CI is installed,
  so the safety net it describes does not exist.
- `sdd/templates/sdd_hooks.example.toml:5`: `agent = "e2e-ui-tester"` is not installed (example only).
- `.claude/agents/code-reviewer.md:8,17` has garbled rewrites: "Read the project's the project instructions file",
  and "Read `the project instructions file`", which renders as a code path.

### C4. Module paths written where a command is expected

- **Where:**
  - `parrot.sdd.scripts.sdd_meta.plan_worktree`: `worktree-management.md:16`, `sdd-worker.md:277`, `sdd-planner.md:73`
  - `parrot.sdd.scripts.<x>` mentions: `sdd-task.md:35-36`, `sdd-spec.md:26,165`, `sdd/WORKFLOW.md:36,232,295-322`,
    `sdd-done.md:275,708,950`, `sdd-status.md:210`
  - `.agents/skills/sdd-done/SKILL.md:94`: "selector from `parrot.sdd.scripts.select_tests`"
- **Why:** they name a function or module, not a command. `plan_worktree` is not reachable via `parrot sdd run`;
  `sdd_meta` has only `parse`, `taxonomy` and `resolve-flow`. The prose is accurate, but an agent may translate it
  to `python -m …`, which fails in a global-only install. `test_every_invocation_uses_parrot_sdd_run` catches only
  the literal `python -m parrot.sdd.scripts.`.

### C5. Hard-coded `dev` / `main` / `staging` in prose

- **Where:**
  - `.claude/commands/sdd-task.md:43` ("`dev` for features, `main` for hotfixes")
  - `.claude/agents/sdd-worker.md:181-183`
  - `.claude/rules/worktree-management.md:19,33,61-62`
  - `.claude/commands/sdd-proposal.md:61-63` ("You must be on `dev`, `staging`, …")
  - `.claude/commands/sdd-spec.md:14,167,201`
  - `.claude/commands/sdd-status.md:51-52`
  - `.claude/commands/sdd-done.md:48,811-825`
  - `.claude/agents/sdd-autopilot.md:56,265-266,756,763`
  - `.claude/agents/sdd-ideation.md:31,70`
  - `.claude/hooks/sdd-worker-format.sh:44,51`
  - `docs/sdd/CODEX.md:122-124,192,239-240,368-375,406,440`
  - `.agents/skills/sdd-brainstorm/SKILL.md:49-59`
- **Why:** misleading when `sdd/config.json` names other branches. The breaking cases are B5 and B16.

### C6. ai-parrot-specific content presented as generic

- **Templates:**
  - `sdd/templates/spec.md:65-70` ("existing AI-Parrot components", `AbstractClient`, `AgentCrew`)
  - `sdd/templates/spec.md:107-126,254-261` (`parrot/…` paths)
  - `sdd/templates/spec.md:312-315`: "Patterns to Follow" defaults of "Use `AbstractBase` pattern from
    `parrot/base/`", async-first, Pydantic and `self.logger`, written as content rather than placeholders
  - `sdd/templates/task.md:37-60,94`
  - `sdd/templates/research_plan.prompt.md:5` and `synthesis.prompt.md:5` ("AI-Parrot SDD pipeline"), plus the
    Nextstop examples throughout
- **Commands and docs:**
  - `.claude/commands/sdd-spec.md:396` (AbstractClient / AgentCrew / BaseLoader)
  - `projects:` examples naming ai-parrot packages: `sdd-spec.md:452`, `sdd-fromjira.md:272`,
    `sdd/WORKFLOW.md:130`, `sdd-ideation.md:183`
  - `sdd-worker.md:264-271` (`[tool.parrot.worktree]`, `parrot.utils.types`, `import parrot.utils`, maturin)
  - `worktree-management.md:53`
  - `sdd-task.md:117,132-138` (querysource, Cython `make build-inplace`)
  - `docs/sdd/CODEX.md:1-3,94-101` ("AI-Parrot's SDD")
- **Agents:**
  - `sdd-autopilot.md` as a whole (a design doc with `parrot/integrations/jira/oauth.py` examples and "Comparison
    with ai-parrot AgentCrew")
  - `sdd-research.md:59` (the `flow-bot` service account)
  - `sdd-qa.md:49-59` (`flowtask`, ruff and mypy)
  - `sdd-tojira.md:443` (`JiraToolkit.jira_create_issue()`)
- **Model pins:** `sdd-spec.md` (`gpt-5.6-luna`) and `sdd-ideation.md` (`gpt-5.6-sol`).

### C7. uv / `.venv` shared-environment policy text

- **Where:**
  - `.claude/agents/sdd-coder.md:37-45`
  - `.claude/agents/sdd-worker.md:49-58,69,271`
  - `.codex/agents/sdd-worker.toml:36-45`
  - `.claude/rules/worktree-management.md:54-55`
  - `docs/sdd/CODEX.md:67`
- **Why:** uv-specific ("`uv run --no-sync`", "`.pth` files", "`uv venv .task-venv`"). It is harmless in other
  ecosystems, but irrelevant to them.

### C8. `sdd-worker-format.sh` (opt-in hook)

- **Where:** `.claude/hooks/sdd-worker-format.sh`.
- **Issues:**
  - Line 116 hard-codes the commit trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
  - Line 95's comment says "line-length comes from the root pyproject: 120".
  - Lines 82-96 run `black` whenever it is on PATH, without the `[tool.black]` check that `/sdd-done` uses, so it
    can reformat a repo that does not use black.

### C9. Ledger git-hook block text written into the foreign repo's `.git/hooks`

- **Where:** generated by `parrot/knowledge/wiki/claude_code/assets.py:266-279`.
- **Text:** "Installed by `parrot claude install`; remove with `parrot claude uninstall`", and "/sdd-done delivers
  them to origin/dev".
- **Why:** in a foreign repo the hooks were written by `parrot sdd install` and are removed by
  `parrot sdd uninstall`.

### C10. The wiki and MCP are assumed but never provisioned

- **Where:**
  - Wiki-first instructions: `.codex/agents/sdd-worker.toml:14`, `sdd-brief.md:86-90`, and the
    `sdd-brainstorm`/`sdd-spec`/`sdd-fromjira`/`sdd-proposal` skills
  - MCP-only tools: `.claude/agents/sdd-ideation.md:44,117-127` ("you have three read-only tools backed by this
    repo's … knowledge-graph plane"), and the `sdd-worker.md:26` `tools:` list of `mcp__parrot-sdd-coder__*`,
    `mcp__parrot-bounded-source__*` and `mcp__wikitoolkit__*`
- **Why:** `parrot sdd install` builds no wiki and writes no `.mcp.json`, and the "SDD flow in any repository" doc
  section does not mention `parrot claude install` or `wikitoolkit build`. `sdd-worker` has a sequential fallback
  and most assets fall back to grep, so this degrades rather than breaks.
- **Verified:** `wikitoolkit query "auth handler"` in an empty scratch repo prints
  `Error: Wiki not built yet … Run wikitoolkit build first`.

### C11. Install-time tooling audit misses tools the assets depend on

- **Why:** `audit.EXTERNAL_TOOLS` (`audit.py:22`) covers `jq`, `gh`, `tmux`, `codex`, `git-lfs`, `agy`, `black` and
  `pylint`. It does not cover:
  - `ruff` (B11, B12)
  - `python` (B3)
  - `rg` (Codex skills: "Use `rg` for source search")
  - `timeout` (`sdd-done.md:302`)
  - `bwrap` (required by the `worktree_environment` hook)
- **Effect:** `parrot sdd install` cannot warn about them.

---

## What existing tests already guard (and what they miss)

| Category | Guard | Covers | Misses |
|---|---|---|---|
| `scripts/sdd/…` / `python -m scripts.sdd…` refs | `tests/sdd/test_no_repo_script_refs.py::test_no_repo_script_findings_at_all` | all repo-checkout asset sources | — |
| `python -m parrot.sdd.scripts.` in assets | `…::test_every_invocation_uses_parrot_sdd_run`; also asserted in `test_wheel_only_foreign_repo._collect_invocations` | literal form | bare module names (C4, B16 line 63) |
| `parrot.sdd.scripts.<name>` resolves | `…::test_every_rewritten_reference_resolves`, `…::test_moved_names_all_resolve` | names only | — |
| `python -c "…parrot.sdd.scripts"` | `…::test_no_inline_python_imports_parrot` | that one module path | heredoc `python3 - <<…` importing `parrot.knowledge…` (B13); bare `python` binary (B3) |
| Org data / `CLAUDE.md` refs / branch literals (C11) | `…::test_no_publication_findings_in_shipped_files` (audit kinds `org-data`, `claude-md-ref`, `branch-literal`) | `*.atlassian.net`, `KEY-123`, `CLAUDE.md`, branch in operator position | `NAV`/`Nav-AI`/custom-field IDs (B6), `AGENTS.md` (C2), branch prose (B5, B16, C5) |
| Monorepo paths/text (C16/C22) | `…::test_no_monorepo_source_paths_in_shipped_files` + `scripts/sdd/check_asset_sync.py --check/--wheel` (the latter also scans packaged-only assets) | `packages/`, `scripts/`, `$CLAUDE_PROJECT_DIR/`, `tests/sdd_scripts/`, `from navconfig`, `PYTHONPATH=`, `reference/sdd-insight/` | `` `PYTHONPATH` set to `` (B11), `source .venv/bin/activate` (B2, B14), navconfig without `from` (C3) |
| `/sdd-insight` not advertised | `…::test_packaged_assets_do_not_advertise_sdd_insight` | — | other repo-only commands: `/remove-worktree` (B8), `/pr-review` (B9) |
| Every documented `parrot sdd run <helper> <args>` works in a foreign repo | `tests/sdd/test_wheel_only_foreign_repo.py::test_install_then_every_documented_helper_invocation` | helper names + flags, run against the managed install | — (this is why no helper/flag findings appear above) |
| Codex/Google skills' linked files exist | `tests/sdd/test_installer.py::test_non_claude_host_skills_have_every_file_they_read` | `](../…)` links from `.agents/skills` | `./GUIDE.md` etc. in `docs/sdd/CODEX.md`, backticked doc paths (C1) |
| Autopilot's `claude --agent X` targets installed | `test_installer.py::test_agents_dispatched_by_packaged_autopilot_are_installed` | claude host | google host (B10) |
| `test_command` switch documented / helpers fail cleanly | `tests/sdd/test_test_command_fallback.py`, `test_wheel_only_foreign_repo.py::test_c21_test_step_outcomes` | `cache_test_contract`, `select_tests`, `test_report` | `check_task_graph`'s `non-pytest-validation-command` (B1); `/sdd-fix` (B11) |
| `venv-path` / `uv-run` audit kinds | `parrot.sdd.audit` defines them (`test_audit.py` unit-tests the regexes) | — | no test asserts zero over shipped files; currently 6 `venv-path` + 5 `uv-run` hits in `_assets/` |

---

## Adjacent observations (not foreign-repo-specific; verify separately)

- **Google `/sdd-done` twin has drifted.** `.agent/workflows/sdd-done.md` differs from the Claude command by about
  441 lines. It has no brief lane (`/sdd-done <KEY>` for `/sdd-brief` output), refuses to run inside a worktree, and
  still has `--resolve-jira` curl logic instead of the closeout-hooks flow.
- **`.autopilot/` is not ignored.** `qa-runner` writes `.autopilot/qa-report.md` into the worktree, and even
  ai-parrot's `.gitignore` lacks `.autopilot/`. That is the same `git worktree remove` failure as B4.
- **macOS and other non-Linux hosts.**
  - `worktree_environment.py:246-248` refuses every Bash call when `bwrap` is missing (maintainer policy; global
    install is Linux-only by doc).
  - The assets also use GNU-isms: `mapfile` (bash ≥4), `grep -oP`, `timeout -k`.
- **Possible cross-repo leak in `wikitoolkit symbols lookup` (cause not determined).** In an empty scratch repo with
  no wiki, `wikitoolkit symbols lookup foo` returned symbols from the ai-parrot monorepo
  (`packages/ai-parrot-server/tests/…`), while `wikitoolkit query` correctly said "Wiki not built". It may depend on
  this machine's remote/namespace configuration; worth a separate check.

## Counts

- (a) Breaks: **16** findings (B1-B16). B5, B6, B7, B9, B12 and B16 are conditional on repo branch names, Jira use or
  ruff absence; B13 fails silently.
- (b) Cosmetic or non-blocking: **11** findings (C1-C11). Each covers several locations.
- No dangling `parrot sdd run` helper names, invalid helper flags or invalid `wikitoolkit` verbs.
