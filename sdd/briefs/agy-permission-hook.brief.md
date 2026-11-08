---
kind: brief
slug: agy-permission-hook
key: agy-permission-hook
base_branch: dev
source:
  type: text
  ref: "operator report 2026-11-08: agy asks permission for every shell command (`find packages/ -path \"*/sdd*\" -o -path \"*/dev_loop*\" 2>/dev/null | head -n 50`), so /sdd-spec, /sdd-task, /sdd-brief and /sdd-fix are unusable from an Antigravity console"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-08"
---

# Brief: Make the SDD command surface usable from the Antigravity CLI (agy)

## Problem

The operator pasted this agy prompt, shown for a plain read-only search:

```
Requesting permission for:
   find packages/ -path "*/sdd*" -o -path "*/dev_loop*" 2>/dev/null | head -n 50

Run this command?
> 1. Yes, run command
  2. Yes, and always allow in this conversation for commands that start with 'find packages/ -path "*/sdd*" -o -path "*/dev_loop*" 2>/dev/null'
  3. Yes, and always allow for commands that start with '...' (Persist to settings.json)
  4. No, cancel
```

Every `run_command` that no agy permission rule covers stops on this prompt, and the offered "always
allow" rule is the literal command, which is useless to persist. Under Codex (workspace-write sandbox)
and Claude Code (allow rules plus the C32 guard) the same SDD skills run unattended. Goal: `/sdd-spec`,
`/sdd-task`, `/sdd-brief` and `/sdd-fix` run from an agy console without a prompt on routine commands,
while destructive commands are still blocked or confirmed.

## Root cause

agy's default `toolPermission` is `request-review` (operator config, `agy -p "/config"`): a command runs
without asking only when a `permissions.allow` rule in the user's agy `settings.json` matches it. The
SDD installer ships no agy permission policy at all. `parrot sdd install` registers its PreToolUse
guard only for the Claude host (`packages/ai-parrot/src/parrot/sdd/installer.py:568`,
`if dangerous_guard and "claude" in _validate_hosts(hosts):`), the `hooks` CLI noun serves only the
Claude-shaped guard (`packages/ai-parrot/src/parrot/sdd/cli.py:322`), and that guard only understands
Claude payloads (`packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:411`,
`if tool == "Bash":`), so agy gets neither auto-approval nor the destructive-action safety net.

## Research findings

**agy protocol, verified live 2026-11-08** (agy 1.4.12, interactive sessions driven through tmux and
headless `-p`, scratch workspace, model `gemini-3.8-flash-low`):

| Hook response (`.agents/hooks.json`, matcher `run_command`) | Settings rules | Result |
|---|---|---|
| `{"decision":"allow"}` | none | **prompt shown** (interactive); auto-denied (headless) |
| `allow` + `permissionOverrides: ["command(find)","command(head)"]` | none | **prompt shown**; auto-denied |
| `{"decision":"deny","reason":"M"}` | none | blocked: `tool call denied by pre-tool hook: M` |
| `{"decision":"ask"}` | `command(find)`, `command(head)` | runs, no prompt (neutral) |
| `{"decision":"force_ask","reason":"M"}` | `command(find)`, `command(head)` | prompt shown with `Reason: M` |

- **A hook cannot auto-approve in agy 1.4.12.** Only `permissions.allow` rules do. A hook can still
  `deny`, and `force_ask` overrides a matching allow rule. `ask` leaves the decision to the rules.
- **Rule grammar** (strings embedded in the binary): `command(<word prefix>)`, `read_file(<abs path>)`,
  `write_file(<abs path>)`, `mcp(<server>/<tool>|*)`, `read_url(<domain>)`, `execute_url(<domain>)`.
  Settings keys: `permissions.allow`, `permissions.deny`, `toolPermission`, `agentMode`.
- **Matching, verified:** a pipeline is checked per subcommand (`find … | head -n 5` runs with
  `command(find)` + `command(head)`); leading `VAR=value` assignments are ignored (`FOO=bar find …`
  runs with `command(find)`); `cd x && cmd` needs no rule for `cd`; but `git -C . status` does **not**
  match `command(git status)`, so the `git -C <wt> …` calls in `/sdd-brief` and `/sdd-fix` need a
  `command(git -C)` rule.
- **Payload, captured:** `{"toolCall": {"name": "run_command", "args": {"CommandLine": "…",
  "WaitMsBeforeAsync": 5000, "toolSummary": "…"}}, "workspacePaths": ["<abs>"], "conversationId": …,
  "stepIdx": …, "modelName": …, "lastUserInput": …, "transcriptPath": …}`. `args.Cwd` is absent when
  the command runs in the workspace root. The hook command runs via `sh -c` with its working directory
  set to the folder holding `hooks.json`; stdout must be one JSON object.
- **No repository-scoped permissions.** agy reads permission rules only from the user's settings, the
  shared `~/.gemini/config/config.json` and agy "project" grants, never from the workspace.
  `--settings <json|file>` with a `permissions` key replaces the global list for that session (verified).
  Settings file: `~/.gemini/antigravity-cli/settings.json`; the snap build keeps it under
  `~/snap/antigravity-cli/common/.gemini/antigravity-cli/settings.json` (its `HOME` is
  `$SNAP_USER_COMMON`).
- **Snap build cannot run the SDD flow at all** (environment, not code): inside its confinement the
  project venv's interpreter (`/usr/bin/python3.12`) does not exist (core26 ships 3.14), so `parrot`
  and `wikitoolkit` fail with `bad interpreter`; `ssh` cannot be executed (git over SSH fails) and
  `~/.gitconfig` is invisible. The official non-snap install is
  `curl -fsSL https://antigravity.google/cli/install.sh | bash` (installs `~/.local/bin/agy`).
- **Reuse:** `parrot.sdd.scripts.dangerous_actions.evaluate(payload, *, root)` (stdlib at import time,
  blast radius = its own `main` and tests) supplies the deny rules; `protected_branches(root)` and the
  lazy `parrot.sdd.config.load_sdd_config` give the hotfix branch. The C32 installer wiring
  (`dangerous_hook_command`, `_install_dangerous_guard`, `_remove_dangerous_guard`,
  `_dangerous_guard_report`, `installer.py:361-487`) is the template for the agy registration. The
  managed global launcher (`~/.parrot/bin/parrot`) makes the bare `parrot sdd hooks … --hook` form work
  without an activated venv; `parrot sdd hooks dangerous-actions --hook` answers in ~0.2 s with clean
  stdout.
- **SDD command surface of the four agy skills** (`.agents/skills/sdd-{spec,task,brief,fix}/SKILL.md`):
  `parrot sdd {worktree,ids,spec,task,brief,tests,techwiki}`, `wikitoolkit {query,page,related,symbols,
  ledger,spec}`, `git checkout|pull|push|add|commit|rev-parse|diff`, `git -C <wt> add|commit|push`,
  `gh pr create|view`, `gh issue view`, `gh api`, `rg`, `grep`, `test -e … && sed -n '<n>p' …`,
  `ruff check --fix`, `PYTHONPATH=… pytest <files>`.
- **Ledger:** `wikitoolkit ledger context` on `installer.py`, `cli.py`, `dangerous_actions.py` shows only
  `issue:bdc696964162` (worker_notification mount parity), unrelated.
- **Concurrent work:** no branch, brief, spec or proposal mentions agy/Antigravity permissions.

## Decisions

1. **Two layers** (forced by the protocol table above). Auto-approval comes from a managed list of
   agy `permissions.allow` rules; the PreToolUse hook narrows it: `deny` for destructive commands,
   `force_ask` for risky variants that a broad rule would otherwise approve, `ask` (neutral) otherwise.
2. **Rules go into the user's global agy settings, written by `parrot sdd install --host google`**
   (operator choice): additive and idempotent, never removing or reordering user rules; uninstall
   removes only the rules this install added (recorded in the receipt). Every agy `settings.json` that
   already exists (non-snap and snap paths) is updated; when none exists, the non-snap one is created.
3. **`pytest`, `ruff` and `black` are auto-approved only with at least one explicit path inside the
   workspace** (operator choice); without a path (full suite) the hook returns `force_ask`.
4. **`git push` whose destination is `main`, `master` or the configured `hotfix_base` is denied**
   (operator choice), including a bare `git push` while the checkout is on one of those branches.
   `PARROT_ALLOW_DANGEROUS=1` disables every deny and force_ask, as it does for the C32 guard.
5. The hook is served as `parrot sdd hooks agy-permissions --hook`, registered in the workspace
   `.agents/hooks.json` under one named hook `parrot-sdd-permissions` (matcher `run_command`), and
   tracked in ai-parrot in its bare form. `--no-agy-permissions` skips both the hook and the rules.
6. The snap build is documented as unsupported for the SDD flow, with the non-snap install command.

## Fix plan

- **HOTFIX-agy-permission-hook-1:** the policy module `parrot/sdd/scripts/agy_permissions.py`
  (managed rule list, command classifier, agy hook `main`), the `hooks agy-permissions` verb, the
  tracked `.agents/hooks.json`, and tests.
- **HOTFIX-agy-permission-hook-2** (depends on 1): `parrot sdd install|uninstall|status` register the
  hook and merge the managed rules into the user's agy settings for the google host, the
  `--no-agy-permissions` flag, tests, and the install docs (snap caveat included).

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_agy_permissions.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`
