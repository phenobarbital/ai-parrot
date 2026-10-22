# FirefliesInsightsAgent

`FirefliesInsightsAgent` processes Fireflies.ai meeting transcripts into
wiki inbox entries, extracts insights (decisions, risks, action items) via
the configured LLM, sends a summary to a Telegram channel, and creates
Jira tickets for confirmed action items.

## How it works

1. **Sync**: `sync_meetings` fetches recent transcripts from the Fireflies
   MCP server (paginated, deduped by a local `MeetingRegistry`).
2. **Drop**: each new meeting is written as a Markdown file into the wiki
   inbox directory for knowledge-graph ingestion.
3. **Insights**: the LLM extracts `MeetingInsights` (decisions, risks,
   action items) from the transcript.
4. **Notify**: insights are formatted and sent to the configured Telegram
   channel. Each action item includes a `/fireflies_ticket <id>` command.
5. **Confirm**: a human confirms a ticket by sending the command; the agent
   creates a Jira issue via the configured template and records the key so
   a replayed confirmation returns the existing ticket.

Ingestion (steps 1-2) and insights (steps 3-4) are independent: a failure
in one path does not block the other, and both are reported in the
`InsightRunReport`.

## Configuration

| Setting | Source | Description |
|---|---|---|
| `fireflies_token` | Constructor / env `FIREFLIES_API_KEY` | Fireflies API token for the MCP server |
| `wiki_root` | Constructor | Path to the wiki project root; `inbox_dir` is resolved from `wiki.json` |
| `public_channel_id` | Constructor | Telegram chat ID where insights are posted |
| `jira_project` | Constructor | Default Jira project key for tickets |
| `jira_templates_dir` | Constructor | Directory containing Jira issue templates (Jinja2) |
| `FIREFLIES_REGISTRY_DIR` | Env variable | Directory for the meeting registry and approval state file |

## Commands

### `/fireflies_sync [N]`

Fetch the latest meetings (default limit: 50) and run the full sync +
insights pipeline. The optional numeric argument overrides the fetch limit.

### `/fireflies_ticket <id>`

Create a Jira ticket from a previously reported action item. The `<id>` is
the 12-character stable identifier shown in the Telegram notification.

- **Authorization**: the command must come from the same chat that received
  the original notification.
- **TTL**: approvals expire after **72 hours**. An expired confirmation is
  refused with a clear message.
- **Idempotency**: confirming the same action item twice returns the
  existing Jira ticket key without creating a duplicate.
- **Ordering**: the ticket key is persisted to the state file **before**
  the reply is sent, so a crash after Jira answers cannot cause a second
  ticket on retry.

## Jira template

Tickets are created through the `fireflies/action_item` template
(`agents/fireflies_insights/templates/fireflies/action_item.j2`). The
template receives these keys:

| Key | Type | Description |
|---|---|---|
| `meeting_title` | `str` | Title of the meeting |
| `meeting_date` | `str` | ISO date of the meeting |
| `meeting_id` | `str` | Fireflies meeting identifier |
| `action_title` | `str` | Title of the action item |
| `owner` | `str` | Assigned owner |
| `due_date` | `str \| None` | Due date if extracted |
| `evidence` | `str` | Verbatim transcript quote |
| `decisions` | `list[str]` | Decisions from the meeting |
| `risks` | `list[str]` | Risks/blockers from the meeting |
| `wiki_url` | `str \| None` | Best-effort wiki source link |

## Skills

File-based skills live in `agents/fireflies_insights/skills/`. The base
skill `meeting-insights` provides the system prompt for insight extraction.
The agent uses only the file-based skill registry (`enable_skill_registry =
False`); it never creates the database-backed skill store.

## Install

```bash
uv pip install "ai-parrot[filesystem-transport-full]"  # for --watch mode
```

The Fireflies MCP server (`@anthropic/fireflies-mcp`) must be configured
and available; the agent connects lazily on first use.
