# `/sdd-done` closeout hooks

Closeout hooks add checks and notifications to `/sdd-done` without changing its core workflow. Copy
[`sdd_hooks.example.toml`](../../sdd/templates/sdd_hooks.example.toml) to `.parrot/sdd_hooks.toml` in
the feature worktree, then tailor the declared hooks.

## Events

| Event | When it runs | Blocking | Under `--dry-run` |
| --- | --- | --- | --- |
| `pre_pr` | After the test report and before the closeout report or PR | Allowed; failure stops closeout | Runs |
| `post_pr` | After the PR URL or merge SHA is known | Never; failures are reported only | Skipped |
| `on_failure` | When closeout aborts because of a gate, hook, or merge failure | Never | Skipped |

Hooks run sequentially in declaration order. A missing configuration means there are no hooks; a malformed
file is a closeout error, never an empty configuration.

## Configuration

The configuration has `hooks.pre_pr`, `hooks.post_pr`, and `hooks.on_failure` arrays. Every item is a
`HookSpec`:

| Field | Type / default | Meaning |
| --- | --- | --- |
| `name` | required string | Unique lowercase, digit, and hyphen name within its event |
| `kind` | required | `command`, `agent`, or `builtin` |
| `run` | optional string | Shell command for a `command` hook |
| `agent` | optional string | Host subagent type for an `agent` hook |
| `prompt` | optional string | Agent prompt; supports `{feat_id}` and `{artifact_dir}` placeholders |
| `builtin` | optional string | Builtin action identifier |
| `with` | empty table | Builtin-specific options |
| `blocking` | `false` | May be `true` only for `pre_pr` |
| `timeout_s` | `600` | Positive command or builtin timeout in seconds |
| `artifacts` | unset | Glob relative to the hook artifact directory |
| `enabled` | `true` | Disabled hooks remain configured but are not dispatched |

`command` requires `run`; `agent` requires `agent` and `prompt`; `builtin` requires `builtin`. Commands
receive `SDD_HOOK_CONTEXT`, `SDD_HOOK_ARTIFACT_DIR`, `SDD_FEAT_ID`, and `SDD_PR_URL`, and run in the
feature worktree.

## Hook kinds and builtins

`command` runs its shell command. `agent` is returned as pending work for the host. `builtin` supports:

| Builtin | Purpose | Configuration and environment |
| --- | --- | --- |
| `jira.transition` | Transitions the spec-linked Jira ticket and posts the PR/SHA comment | `with.status` defaults to `Done`; uses `JIRA_INSTANCE`, `JIRA_USERNAME`, and `JIRA_API_TOKEN` from environment or navconfig |
| `telegram.send` | Sends a Bot API message | `with.token_env` defaults to `SDD_TELEGRAM_BOT_TOKEN`; `with.chat_id_env` defaults to `SDD_TELEGRAM_CHAT_ID`; `with.template` supports context placeholders |
| `push.send` | Sends a notification through ntfy or Gotify | `with.provider` defaults to `ntfy`; ntfy uses `SDD_NTFY_URL`, `SDD_NTFY_TOPIC`, and optional `SDD_NTFY_TOKEN`; Gotify uses `SDD_GOTIFY_URL` and optional `SDD_GOTIFY_TOKEN`. `url_env`, `topic_env`, and `token_env` override names. |
| `webhook.post` | Posts JSON hook context externally | Set `with.url_env` to the URL environment-variable name; optionally set `with.headers_env` to a JSON-headers environment-variable name |

Builtins skip rather than fail if required credentials are absent. `jira.transition` also skips when its
specification has no linked Jira key.

## Agent hooks and exit codes

Run an event with:

```bash
python -m scripts.sdd.run_closeout_hooks --event pre_pr --context /path/to/context.json
```

An agent hook returns exit code `3` and a `pending_agents` entry. The host dispatches the rendered prompt,
records the result, then finalizes the event:

```bash
python -m scripts.sdd.run_closeout_hooks --event pre_pr --feat-id FEAT-123 \
  --record frontend-e2e --status pass --summary "Screencast captured"
python -m scripts.sdd.run_closeout_hooks --event pre_pr --feat-id FEAT-123 --finalize
```

| Exit code | Meaning |
| --- | --- |
| `0` | Completed; non-blocking failures may be reported |
| `1` | A blocking `pre_pr` hook failed or timed out |
| `2` | Configuration or command-usage error |
| `3` | Agent hooks are pending; dispatch, record, then finalize them |

An agent left pending at finalization becomes a failure. `post_pr` and `on_failure` failures never block.

## Artifacts and trust

Each event writes results under `/tmp/claude-<uid>/sdd-hooks/<FEAT>/`; each hook has a subdirectory.
Result JSON and files selected by `artifacts` stay outside the repository, are never committed, and their
absolute paths appear in the PR `## Evidence` section. Operators retain them. Set
`SDD_HOOKS_ARTIFACT_ROOT` only when the default temporary root is unsuitable.

Command hooks execute shell from a repository-committed configuration file. Treat it with the same trust
level as a Makefile or test-runner configuration, and only run it from the intended feature worktree.

## Migrating from the legacy Jira flag

The legacy Jira flag has been removed. Configure an opt-in `post_pr` `jira.transition` hook instead:

```toml
[[hooks.post_pr]]
name = "jira"
kind = "builtin"
builtin = "jira.transition"
with = { status = "Done" }
```
