# `parrot agent` — Agent Terminal Workspace

`parrot agent <name>` opens an interactive session with a registered agent. On a
real terminal it starts a full-screen **workspace** (Textual); when piped, or
with `--ui inline`, it runs the classic **inline console** (Rich + prompt_toolkit).

## Usage

```bash
parrot agent [NAME] [--ui auto|inline|tui] [--session ID|last] [--user USER_ID]
             [--server URL] [--token TOKEN] [--no-stream] [--no-history] [--list]
```

| Option | Default | Meaning |
|---|---|---|
| `--ui` | `auto` | `auto` picks `tui` when stdin **and** stdout are TTYs and `TERM` is not `dumb`, else `inline`. |
| `--session ID\|last` | — | Resume a prior conversation from the agent's memory (`last` = the last session used with this agent). Standalone mode only. |
| `--user` | `cli-user` | Identity sent with each request. **Refused with `--server`** (exit 2): identity there comes from the token. |
| `--server URL` / `--token` | — | Talk to a running server; `--token` (or `PARROT_SERVER_TOKEN`) is sent as `Authorization: Bearer`. |
| `--no-stream` | off | Wait for the full answer instead of streaming. |
| `--no-history` | off | Do not persist composer history. |
| `--list` | — | List registered agents and exit. |

## Keys (workspace)

The full-screen TUI workspace supports the following keybindings:

| Key | Action |
|---|---|
| `enter` | Send the current message / query. |
| `ctrl+j` / `shift+enter` | Insert a newline in the composer. **Note**: `ctrl+j` is the guaranteed newline key across all terminals. |
| `up` / `down` | Navigate input history. |
| `tab` | Complete slash commands starting with `/`. |
| `pageup` / `pagedown` | Scroll the chat history pane. |
| `end` | Follow chat (scroll to the bottom). |
| `ctrl+c` | Cancel the active generation. If idle, pressing twice quits the application. |
| `ctrl+d` | Quit the application. |
| `f2` | Toggle the tools panel. |
| `f3` | Toggle the logs panel. |
| `ctrl+l` | Clear the screen (equivalent to `/clear`). |

## Slash commands

Slash commands can be typed directly into the composer to control the session or query metadata:

* `/tools` — List available tools for the current agent.
* `/info` — Show metadata about the current agent and session.
* `/clear` — Clear the chat screen and start a new session ID.
* `/export [path]` — Export the current conversation history as a JSON file.
* `/stream` — Toggle streaming mode on/off.
* `/resume <id|last>` — Resume a prior session by ID or the last active session.
* `/help` — Show help text.
* `/quit` (or `/exit`) — Exit the application.
* `/create_agent` — Create a new agent configuration.

When running in daemon mode (`agentd`), the following additional commands are available:
* `/status` — Show daemon status and active jobs.
* `/schedules` — List scheduled tasks.
* `/invoke` — Manually invoke a background job.

## Conversation resume vs. input history

* **Conversation Resume**: Managed via `--session <id|last>` or the `/resume` slash command. This restores the actual conversation state and memory from the agent's backend memory. This is only available in standalone mode (server/daemon mode does not support session resume).
* **Input History**: Persisted locally in `$PARROT_HOME/cli/history/<slug>.txt` with file permissions set to `0600` (owner read/write only). This history is independent of the agent's memory and can be disabled entirely using the `--no-history` flag.

## Server mode

When connecting to a remote server using `--server URL`:
* **Authentication**: The `--token` option or the `PARROT_SERVER_TOKEN` environment variable is sent in the `Authorization: Bearer <token>` header.
* **User Identity**: The `--user` option is refused (exits with code 2) because user identity is determined server-side from the authentication token.
* **Session Resume**: Resume is not available in server mode (the `--session` flag and `/resume` command are disabled).
* **Live Tool Progress**: Live tool execution events and progress are streamed from the server via Server-Sent Events (SSE).
* **Server Routes**: The client interacts with the following API endpoints:
  * `GET /api/v1/bots` — List available bots/agents.
  * `GET /api/v1/chatbots/{name}` — Get details for a specific agent.
  * `POST /api/v1/agents/chat/{agent_id}` — Send a chat message.
  * `POST /bots/{bot_id}/stream/sse` — Stream chat responses and tool events.

## Non-interactive use (pipes and scripts)

When stdin or stdout is not a TTY (e.g., when piping input or running in a script):
* **Name Requirement**: An agent name must be explicitly provided (exits with code 2 if missing).
* **UI Mode**: `--ui tui` is refused (exits with code 2). The interface defaults to plain line mode.
* **Input Processing**: The client processes one query per line from stdin.
* **Output**: Plain text output is produced without ANSI escape sequences or interactive widgets.
* **Exit Codes**:
  * `0` — Success.
  * `1` — Load/REPL error, or if any turn in a batch/piped run failed.
  * `2` — Usage error (e.g., missing name, invalid flags, or `--user` with `--server`).

## Troubleshooting

* **`TERM=dumb`**: If your terminal is detected as `TERM=dumb`, the client automatically falls back to the inline console (`--ui inline`).
* **Garbled Screen**: If the TUI workspace renders incorrectly or has visual artifacts, force the inline console using `--ui inline`.
* **"No previous session"**: If you receive this error when trying to resume, run the agent once without the `--session` flag to establish a session first.
