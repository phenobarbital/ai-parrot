# Dev-loop kick-off from Slack (FEAT-555)

Dispatch and steer `parrot devloop` runs from Slack: `/devloop --type feature|bug …`,
Open Questions answered in the run thread, gate approvals, cancel and status.

Every run executes in its own headless `parrot devloop run --headless` child
process (see [`examples/dev_loop/README.md`](../../examples/dev_loop/README.md)):
a crashed or hung run never takes the Slack bot down, and the bot never runs
inside it.

## Install

```bash
pip install "ai-parrot-integrations[slack,devloop]"
```

The `devloop` extra adds `redis>=5.0` (state tail + run registry). It is
separate from the `slack` extra (`slack-sdk`, `slack-bolt`) because `redis`
is otherwise only reachable through the `msteams` / `broadcast` extras
(design research S12) — a Slack bot without dev-loop enabled never needs it.

## Slack app manifest

- **Bot token scopes**: `commands`, `chat:write`, `chat:write.public`,
  `im:write`, `users:read`, `users:read.email`
- **Slash command** `/devloop` → `https://<host>/api/slack/<chatbot_id>/commands`
- **Interactivity request URL** → `https://<host>/api/slack/<chatbot_id>/interactive`
  (Slack-signature verified; FEAT-555 TASK-3205 hardening)
- **Events** (webhook mode) → `https://<host>/api/slack/<chatbot_id>/events`;
  or Socket Mode with an `xapp-` app-level token (`connection_mode: socket`)

`users:read.email` is optional but recommended: without it, `WorkBrief.reporter`
/ `escalation_assignee` fall back to `bootstrap.default_identities()` instead
of a real Jira identity resolved from the initiator's Slack email.

## Configuration (`integrations_bots.yaml`)

Add a `devloop:` section under the Slack bot entry:

```yaml
my-bot:
  kind: slack
  bot_token: "${MY_BOT_SLACK_BOT_TOKEN}"
  signing_secret: "${MY_BOT_SLACK_SIGNING_SECRET}"
  allowed_channel_ids: ["C0123456789"]
  allowed_user_ids: null  # null = anyone in the allowed channels
  devloop:
    enabled: true
    repo_path: /srv/ai-parrot          # cwd of the headless child; default: current working directory
    command: ["parrot", "devloop", "run"]
    redis_url: ""                      # "" = fall back to the process-wide REDIS_URL
    socket_dir: ""                     # "" = <tempdir>/parrot-devloop
    use_tcp: false                     # true = 127.0.0.1 loopback instead of a Unix socket
    default_component: "ai-parrot"     # WorkBrief.affected_component default for bug runs
    default_acceptance_criteria:       # mandatory (non-empty) when enabled; ShellCriterion dicts
      - kind: shell
        name: unit
        command: "pytest packages/ai-parrot/tests -q"
    status_card: true                  # live node-status card in the run thread
    max_concurrent_runs: null          # null = unlimited (decision); set an int for a soft cap
    run_retention_seconds: 86400       # TTL applied to a terminal run's Redis record
    handshake_timeout_seconds: 120.0   # how long to await the child's handshake
    cancel_grace_seconds: 45.0         # parent-side escalation to terminate() after a cancel
    tail_drain_seconds: 5.0            # how long the tail may run after the child exits
```

Every key mirrors `DevLoopIntegrationConfig` (spec §2 Data Models) 1:1.
Unset keys fall back to `{NAME}_DEVLOOP_*` environment variables
(`repo_path`, `redis_url`, `socket_dir`), same pattern as
`SlackAgentConfig`'s own env fallbacks.

## Command syntax

```
/devloop --type feature|bug [--jira KEY] [--base dev|staging] [--title "…"] [--component NAME] [--ac "<cmd>"] <prompt>
/devloop status
/devloop cancel <run-id>
/devloop help
```

- `--type` is mandatory for a dispatch and must be `feature` or `bug` —
  `enhancement` and document intake (`--doc`) are **not** available on
  Slack yet (headless itself accepts `enhancement`; only the Slack parser
  rejects it).
- Both kinds post a **confirm card** (Confirm / Edit / Cancel) before
  anything is spawned — `dispatch()` never launches a run directly.
  Pressing **Edit** opens a pre-filled modal; the resubmission re-validates
  the brief. An unconfirmed card expires after 15 minutes.
- An `open_questions` gate appears in the run thread with an **Answer**
  button (opens a modal, one optional multiline input per question) and an
  **Abort ideation** button. You may also reply directly in the thread with
  `1: answer one` / `2) answer two` lines — at least one valid line is
  required.
- Every other gate kind gets **Approve** / **Reject** buttons, with an
  ephemeral notice on a second resolve or an already-expired gate.
- `/devloop status` lists only the caller's own runs; `/devloop cancel <id>`
  only cancels a run the caller started — every command, button and thread
  reply is checked against the run's initiator.

## How a run executes (headless child)

The Slack integration spawns one child per run:

```
parrot devloop run --brief <file> --yes --headless --run-id <id> --command-socket <path>
```

- The child prints exactly one JSON **handshake** line on stdout —
  `{"event":"ready","run_id":…,"command_endpoint":"unix://…","kind":…,"pid":…}`
  — before any other output; all logging goes to stderr.
- The per-run bearer token travels only via the `PARROT_DEVLOOP_COMMAND_TOKEN`
  environment variable, never argv, and is required on every request in
  both Unix-socket and TCP modes.
- Exit codes: `0` completed, `1` failed, `2` cancelled, `3` bootstrap/preflight
  failure.
- `preflight()` runs with `topology="dev_flow"` for `feature` runs: the
  Jira check becomes advisory (a hint only — the dev-flow never creates
  issues) while Redis (a real `PING`), the coding CLI and the worktree base
  path stay hard requirements. `bug` runs use the existing dev-loop
  preflight unchanged.
- The headless child's own environment (coding CLI credentials, Jira env if
  configured) is inherited by every run it spawns — configure the *bot's*
  process environment, not just Slack's.
- QA reviewer default for `feature` runs is the **model-plan review pair**
  (primary + counter-model), not the judge panel the HTML console uses by
  default (spec Q5) — re-homing the judge panel for Slack is a possible
  follow-up, not part of this feature.

## Limitations

- **Single host**: the Slack bot and every headless child it spawns must run
  on the same machine (Unix socket / 127.0.0.1 loopback only); a
  multi-host deployment was considered (Redis inbound command stream) and
  deferred.
- Slack truncates slash-command text at **3000 characters** — the ack tells
  the user to shorten; document intake (`--doc`) is a follow-up.
- `--type enhancement` is not exposed on Slack in v1.
- The live node-status card (`status_card: true`) is best-effort: a
  `chat.update` failure never affects the run, and updates are debounced to
  at most one edit every 2 seconds per run.
- Runs are **not** stopped when the bot restarts or shuts down — children
  are spawned as session leaders (`start_new_session=True`) and keep
  running; the bot re-attaches to every live run (from its Redis registry)
  on the next startup.
