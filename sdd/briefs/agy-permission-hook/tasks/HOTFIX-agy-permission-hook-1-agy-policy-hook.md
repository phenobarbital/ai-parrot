# HOTFIX-agy-permission-hook-1: agy permission policy module and `hooks agy-permissions` verb

**Feature**: agy-permission-hook — make the SDD command surface usable from the Antigravity CLI
**Spec**: `sdd/briefs/agy-permission-hook.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

agy 1.4.12 auto-approves a command only through `permissions.allow` rules in the user's settings; a
PreToolUse hook can `deny`, `force_ask` (overrides a matching allow rule) or `ask` (neutral), but its
`allow` is ignored (brief, protocol table). This task ships the single source of truth for the managed
rule list and the hook that narrows those rules. Task 2 writes the rules and registers the hook.

## Scope

Create `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py`, stdlib-only at import time like
`dangerous_actions.py` (no `parrot` import at module level; `parrot.sdd.config` only lazily and guarded):

1. **`SDD_ALLOW_RULES: tuple[str, ...]`** — the managed agy rules, each `command(<words>)`:
   - read-only: `ls cat head tail wc grep rg find sed jq sort uniq cut tr diff file stat tree pwd echo
     printf basename dirname realpath readlink test which nl comm du date mkdir`
   - git: `git status`, `git log`, `git diff`, `git show`, `git rev-parse`, `git ls-files`, `git ls-tree`,
     `git blame`, `git grep`, `git describe`, `git merge-base`, `git rev-list`, `git show-ref`,
     `git for-each-ref`, `git cat-file`, `git branch`, `git remote`, `git config`, `git worktree list`,
     `git fetch`, `git add`, `git commit`, `git pull`, `git push`, `git checkout`, `git switch`,
     `git merge`, `git -C`
   - gh: `gh pr create`, `gh pr view`, `gh pr list`, `gh pr checks`, `gh pr diff`, `gh pr status`,
     `gh issue view`, `gh issue list`, `gh api`, `gh run list`, `gh run view`, `gh repo view`
   - SDD: `parrot sdd`, `parrot wiki`, `wikitoolkit`
   - tests/lint: `pytest`, `python -m pytest`, `python3 -m pytest`, `ruff check`, `ruff format`, `black`
   - venv: `source .venv/bin/activate`, `. .venv/bin/activate`
2. **`rule_covers(words: Sequence[str]) -> bool`** — replicates agy's matching for one simple command:
   drop leading `NAME=value` assignments, then true when some rule's words are a prefix of `words`.
3. **`evaluate(payload: dict, *, root: Path | None) -> Decision`** with
   `Decision(decision: Literal["deny","force_ask","ask"], reason: str = "")` (frozen dataclass):
   - Not `toolCall.name == "run_command"`, or no string `toolCall.args.CommandLine` → `ask`.
   - `PARROT_ALLOW_DANGEROUS=1` → `ask`.
   - Run `dangerous_actions.evaluate({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd},
     root=root)`: `deny` → `deny` with its reason; `warn` → `force_ask` with its reason.
   - Parse the command (below). Any segment that is a `git push` to `main`, `master` or the configured
     `hotfix_base` → `deny` (reason names the branch and says to open a PR against it). A push with no
     refspec counts as a push of the current branch, read from the repo's `HEAD` file (no subprocess;
     follow a `.git` file to its gitdir for worktrees).
   - Any segment that `rule_covers` but is risky (table below) → `force_ask`, reasons joined with `; `.
   - Otherwise `ask`. Segments not covered by a managed rule are never escalated (agy prompts for them
     anyway, and the user's own rules are theirs).
4. **Parsing.** Drop heredoc bodies (`<<[-]?['"]?WORD` … line equal to `WORD`), treat remaining newlines
   as `;`. Extract `$( … )`, backtick and `<( … )`/`>( … )` bodies outside single quotes, recursively, and
   classify each body as its own command; replace the substitution with an opaque token that is never
   path-checked. Tokenize with `shlex.shlex(posix=True, punctuation_chars=True)`; split segments on
   `; && || | |& & ( ) { }`. Strip leading `NAME=value` tokens: names other than `PYTHONPATH`,
   `PYTHONDONTWRITEBYTECODE`, `GIT_TERMINAL_PROMPT`, `GIT_PAGER`, `PAGER`, `NO_COLOR`, `TERM`, `LANG`,
   `LC_ALL`, `TZ` make a covered segment risky. A `cd <dir>` segment updates the working directory used
   for later relative paths. An unparseable command (shlex `ValueError`) → `force_ask` "could not parse".
5. **Paths.** Workspace roots = `workspacePaths`, plus each root's main checkout (when `<root>/.git` is a
   file `gitdir: <main>/.git/worktrees/<n>`, the main checkout is `Path(gitdir).parents[2]`). Working
   directory = `args.Cwd` (relative → joined to the first root), else the first root, else
   `os.getcwd()`. A token is path-like when it contains `/` or starts with `~`, `$HOME` or `${HOME}`
   (expand those to `Path.home()`); option values `--x=/p` are checked too. `/dev/null` is always fine.
   A path-like token resolving (lexically, `os.path.normpath`) outside every root is "outside".
6. **Risk table** (only for covered segments; the git rules apply after `git -C <path>`, whose path
   must be inside a root, and after `--no-pager`; `git -c` is risky):

   | Command | Risky when |
   |---|---|
   | any covered command | a path-like argument or redirect target is outside the roots; a `>`/`>>`/`&>`/`>|` target that `dangerous_actions` denies as a Write (secrets, `.venv/`, credentials) |
   | `find` | `-exec -execdir -ok -okdir -delete -fprint -fprint0 -fprintf -fls` |
   | `sed` | `-i`, `-i<suffix>`, `--in-place`, a short cluster containing `i`, `-f`, or a script that is not print-only (`^\s*(\d+|\$)(\s*,\s*(\d+|\$))?\s*p\s*$` or `^/[^/]*/(,/[^/]*/)?p$`) |
   | `sort` / `tree` / `uniq` | `-o`/`--output` / `-o` / two or more positional arguments |
   | `rg` | `--pre`, `--pre-glob` |
   | `git <read>` (status…cat-file) | `--output`, `--output=` |
   | `git branch` | `-d -D --delete -m -M --move -c -C --copy -f --force -u --set-upstream-to --unset-upstream --edit-description` |
   | `git remote` | any subcommand other than none, `-v`, `get-url`, `show` |
   | `git config` | not one of `--get --get-all --get-regexp --list -l` |
   | `git worktree` | not `list` |
   | `git fetch` | a refspec containing `:` or starting with `+`; `-f`, `--force`, `--update-head-ok` |
   | `git commit` | `--amend`, `--no-verify`, `-n`, a short cluster containing `n` |
   | `git pull` | `-f`, `--force` |
   | `git push` | `-f --force --force-with-lease --force-if-includes -d --delete --mirror --all --prune --no-verify`, a refspec starting with `:` or `+` |
   | `git checkout` | anything but `git checkout <protected branch>` or `git checkout -b <new> [<start>]` |
   | `git switch` | `-f --force --discard-changes -C --force-create` |
   | `git -C <p> <sub>` | `<sub>` not in the git rule list above, or its own rule is risky |
   | `gh api` | `-X`/`--method` other than `GET`; `-f -F --field --raw-field --input` |
   | `parrot sdd` | noun `install`, `uninstall`, `launch`, `closeout`; `worktree remove`, `worktree push-protection`, `hooks install` |
   | `wikitoolkit` / `parrot wiki` | subcommand `claude codex gemini google mcp serve` |
   | `pytest`, `python[3] -m pytest`, `ruff check`, `ruff format`, `black` | no positional path argument (decision 3) |

7. **`main(argv) -> None`**: `--hook` required (argparse, like `dangerous_actions.main`); read the payload
   from stdin; `root = dangerous_actions.find_root(<working directory>)`; write exactly one JSON object
   `{"decision": "...", "reason": "..."}` (omit `reason` when empty) and a newline; always exit 0. Any
   exception → `{"decision": "ask", "reason": "agy-permissions: checks skipped (<Type>: <msg>)"}`.

Also:
- Mount the verb in `packages/ai-parrot/src/parrot/sdd/cli.py` `VERBS["hooks"]`:
  `"agy-permissions": ("agy_permissions", (), "Serve the Antigravity (agy) PreToolUse permission policy (--hook).")`.
- Create the tracked `.agents/hooks.json` (bare form, exactly what task 2's installer writes):
  ```json
  {
    "parrot-sdd-permissions": {
      "PreToolUse": [
        {
          "matcher": "run_command",
          "hooks": [
            {"type": "command", "command": "parrot sdd hooks agy-permissions --hook", "timeout": 10}
          ]
        }
      ]
    }
  }
  ```

**NOT in scope**: writing agy settings or registering the hook from the installer (task 2); docs
(task 2); file-write tools (the hook matcher is `run_command` only — a hook answering `ask` for other
tools could add prompts).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py` | CREATE | rule list, classifier, hook `main` |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | mount `hooks agy-permissions` |
| `.agents/hooks.json` | CREATE | tracked bare hook registration |
| `packages/ai-parrot/tests/sdd/test_agy_permissions.py` | CREATE | classifier and hook tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ f426e44f8d, 2026-11-08)
```
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:35   class Verdict: decision: Literal["allow", "deny", "warn"]; reason: str = ""
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:58   def find_root(cwd: str | Path | None) -> Path | None:
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:73   def protected_branches(root: Path | None) -> tuple[str, ...]:   (dev, main, master, staging + config)
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:83   from parrot.sdd.config import load_sdd_config  (lazy + guarded pattern to copy; config.hotfix_base)
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:403  def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict:   (Claude shape: tool_name/tool_input)
packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:436  def main(argv: Sequence[str] | None = None) -> None:   (--hook, stdin, one JSON line, exit 0)
packages/ai-parrot/src/parrot/sdd/cli.py:320                        "hooks": {   "install": …, "dangerous-actions": ("dangerous_actions", (), "…") }
packages/ai-parrot/src/parrot/sdd/cli.py:332                        def mounted_modules() -> set[str]:
packages/ai-parrot/tests/sdd/test_sdd_cli.py:240                    def test_sdd_cli_mounts_every_helper() -> None:   (new module with main() must be mounted)
```

### agy hook contract (captured live, agy 1.4.12)
```json
stdin:  {"toolCall": {"name": "run_command", "args": {"CommandLine": "find . | head -n 5", "WaitMsBeforeAsync": 5000, "toolSummary": "…"}},
         "workspacePaths": ["/abs/workspace"], "conversationId": "…", "stepIdx": 2, "modelName": "…",
         "lastUserInput": "…", "transcriptPath": "…", "artifactDirectoryPath": "…"}
stdout: {"decision": "deny" | "force_ask" | "ask", "reason": "…"}      ("allow" is accepted but ignored by agy)
```

### Does NOT Exist
- No agy/Antigravity permission policy, rule list or `.agents/hooks.json` exists in the repo today.
- agy reads no workspace permission file; there is no `.agents/settings.json`.

---

## Acceptance Criteria

- [ ] `echo '<payload>' | parrot sdd hooks agy-permissions --hook` prints one JSON object and exits 0.
- [ ] `find packages/ -path "*/sdd*" -o -path "*/dev_loop*" 2>/dev/null | head -n 50` → `ask`.
- [ ] `find . -name x -delete`, `sed -i s/a/b/ f`, `cat ~/.ssh/id_rsa`, `git -C . reset --soft HEAD~1`,
      `git push --force origin feat-x`, bare `pytest` → `force_ask` with a reason.
- [ ] `git push origin main`, `git push origin HEAD:main`, bare `git push` on `main`, `git reset --hard`
      → `deny`; `git push origin dev` and `git push -u origin fix-x` → `ask`.
- [ ] `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_x.py -q` → `ask`;
      `LD_PRELOAD=x pytest p` → `force_ask`.
- [ ] A non-`run_command` tool, malformed JSON or a non-object payload → `ask`.
- [ ] `test_sdd_cli_mounts_every_helper` passes with the new verb.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_agy_permissions.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`

## Agent Instructions

Read the brief first. Touch only the listed files. Keep the module stdlib-only at import time.
Parametrize the tests over the risk table (one allowed and one risky case per row), and test
`rule_covers` against the three verified matching facts (env prefix ignored, `cd` ignored,
`git -C` needs its own rule).

## Completion Note

`parrot/sdd/scripts/agy_permissions.py` (stdlib + sibling `dangerous_actions` only at import time):
`SDD_ALLOW_RULES` (83 `command(...)` rules built from `RULE_WORDS`), `rule_covers` (agy word-prefix matching,
leading `NAME=value` dropped), `evaluate` → `Decision(deny|force_ask|ask)` and `main --hook` (one JSON object,
exit 0, neutral `ask` with a reason on any error). Parsing strips heredoc bodies, extracts `$(…)`/backticks/
`<(…)` recursively, tokenizes with `shlex(punctuation_chars=True)`, sees through `time/timeout/nice/env/nohup`
wrappers and tracks `cd`. Only segments a managed rule covers are escalated; `dangerous_actions` denies run
first (its `warn` becomes `force_ask`), redirects into secret files are denied, a push to main/master/
`hotfix_base` (bare push on those branches included, branch read from `HEAD`) is denied.

Deviations from the task text, all in the conservative direction: a path argument built from a shell variable
or from a command substitution is `force_ask` unless the substitution is a trusted repo-path producer
(`git rev-parse`, `git branch --show-current`, `pwd`, `parrot sdd worktree root`); git positional arguments
are not path-checked (git cannot touch files outside the repository except via `-C`, which is checked).

Validation: test_agy_permissions.py → 123 passed; test_sdd_cli.py + test_dangerous_actions.py → 146 passed;
ruff clean, black applied. Live check (agy 1.4.12, interactive, `--settings` carrying `SDD_ALLOW_RULES`, the
worktree hook in `.agents/hooks.json`): `find . -maxdepth 1 -name '*.txt' | head -n 5` ran with no prompt;
`find . -maxdepth 1 -name 'zzz*.tmp' -delete` prompted with `Reason: \`find -delete\` runs or deletes`.

Addendum (after the adversarial review, commits dbd7ea23a5, c66cf41957, c22113dbe0): the classifier was rewritten
to positive allowlists for the high-risk commands, the tracked `.agents/hooks.json` now runs
`scripts/sdd/agy_hook.sh`, and any failure answers `force_ask` (see HOTFIX-agy-permission-hook-2's note).
