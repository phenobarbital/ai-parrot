# Knowledge upload from chat (FEAT-647)

Authorized users can attach a PDF, DOCX, or Markdown file to a command in Telegram, Microsoft Teams, or Slack and ingest it into a Bookstore library or an LLM wiki. The original upload is held in memory and staged only while it is being ingested, then deleted even when the ingest fails or is cancelled; only derived knowledge persists.

## Enabling it on a bot

Add one `knowledge_upload` block to the bot configuration. `bookstore` and `wiki` are optional targets; configure the target or targets that this bot may offer.

```yaml
knowledge_upload:
  enabled: true
  allowed_usernames: [jdoe]
  allowed_groups: [knowledge_curators]
  max_size_mb: 10
  allowed_extensions: [.pdf, .docx, .md, .markdown]
  max_concurrent_jobs: 2
  slack_pending_window_s: 300
  bookstore:
    library_dir: "${BOOKSTORE_LIBRARY_DIR}"
    llm: google:gemini-3.1-flash-lite
  wiki:
    wiki_root: "${WIKI_ROOT}"
    charter_path: null
    llm: google:gemini-3.1-flash-lite
```

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Enables chat upload handling for this bot. |
| `allowed_usernames` | `[]` | Navigator-auth usernames permitted to upload. |
| `allowed_groups` | `[]` | Navigator-auth groups permitted to upload. |
| `max_size_mb` | `10` | Maximum uploaded size in MiB; it must be greater than zero. |
| `allowed_extensions` | `[.pdf, .docx, .md, .markdown]` | Case-insensitive file extensions accepted by the service. |
| `max_concurrent_jobs` | `2` | Maximum concurrent ingest jobs; it must be greater than zero. |
| `slack_pending_window_s` | `300` | Seconds for which a Slack slash command waits for the next file from the same user in the same channel. |
| `bookstore.library_dir` | required when `bookstore` is configured | Root directory for the Bookstore library. Environment variables are expanded. |
| `bookstore.llm` | `google:gemini-3.1-flash-lite` | LLM used by Bookstore ingestion. |
| `wiki.wiki_root` | required when `wiki` is configured | Root directory of the LLM wiki. |
| `wiki.charter_path` | `null` | Optional charter path. When omitted, it resolves to `<wiki_root>/.parrot/charter.yaml`. |
| `wiki.llm` | `google:gemini-3.1-flash-lite` | Lightweight and primary model used by wiki triage and ingestion. |

## Who may upload

The two allow-lists are one global policy per bot and apply to both targets. A user is allowed when their username is in `allowed_usernames` **or** any of their groups is in `allowed_groups`. Authorization denies by default: empty lists, unknown users, and ambiguous identities cannot upload.

Telegram users must complete navigator-auth login; the adapter resolves the navigator-auth user from that session. Microsoft Teams and Slack resolve the sender email and look it up in `auth.vw_users`. Do not use platform display names or channel membership as authorization.

## Commands

All platforms accept `--force`, `--title "…"`, repeatable `--author "…"`, and repeatable `--topic "…"`. `--force` requests a re-ingest; it does not bypass wiki triage.

### Telegram

In a private chat, attach a file with one of these captions, or reply to an already-sent document with the command:

```text
/ingest_book [--force] [--title "…"] [--author "…"] [--topic "…"]
/ingest_wiki [--force] [--title "…"] [--author "…"] [--topic "…"]
```

Only targets configured and available at startup are placed in the bot command menu.

### Microsoft Teams

Send a message with a file attachment and one of these command texts:

```text
/ingest_book [--force] [--title "…"] [--author "…"] [--topic "…"]
/ingest_wiki [--force] [--title "…"] [--author "…"] [--topic "…"]
```

The service returns an immediate acknowledgement and sends the terminal outcome as a proactive message when it can.

### Slack

Slack supports either a file message with a bare command word (no leading slash), or a slash command followed by a file during the configured pending window:

```text
ingest_book [--force] [--title "…"] [--author "…"] [--topic "…"]
ingest_wiki [--force] [--title "…"] [--author "…"] [--topic "…"]

/ingest_book [--force] [--title "…"] [--author "…"] [--topic "…"]
/ingest_wiki [--force] [--title "…"] [--author "…"] [--topic "…"]
```

The slash command cannot carry a file. It arms a one-shot `slack_pending_window_s` window for the same user and channel; share the file before that window expires. Use the bare-word form with the file itself because Slack treats leading-slash message text as a slash command.

## What happens after you upload

The service first validates the target, filename extension, size, and authorization. An accepted upload runs in the background and reports a terminal result.

| Outcome | Meaning |
| --- | --- |
| `accepted` | The upload was received and queued for processing. |
| `added` | A new Bookstore card or wiki content was created. |
| `updated` | An existing Bookstore card or wiki content was updated. |
| `skipped` | The same content is already present; use `--force` to request re-ingest. |
| `rejected_by_triage` | Wiki triage did not admit the document; its briefing explains why. |
| `denied` | The uploader did not match the configured global allow-list. |
| `invalid` | The target is unavailable, or the filename, extension, or size is invalid. |
| `failed` | The background ingest failed or was cancelled; the reply includes a job identifier where applicable. |

Two different files uploaded under the same filename replace each other because staging names are stable. Identical content is skipped unless `--force` is supplied. `--force` never bypasses wiki triage: only a triage decision of `admit` reaches the wiki ingest path.

## Wiki prerequisite: the editorial charter

The wiki target requires a user-authored editorial charter at `<wiki_root>/.parrot/charter.yaml`, unless `wiki.charter_path` names an existing alternative. Without a readable charter, `ingest_wiki` is not offered. Wiki uploads are triaged against that charter, and only documents with an `admit` decision are ingested.

## Platform setup notes

- Telegram: the Bot API cannot download files larger than 20 MB, so the effective limit is the smaller of `max_size_mb` and 20 MB. Configure `enable_login: true` and `force_authentication: true` so upload identity comes from navigator-auth.
- Microsoft Teams: set the bot `client_id` to receive proactive terminal-outcome messages. Teams resolves email or UPN from the conversation roster; users without a verified email are denied.
- Slack: grant `files:read`, `users:read`, and `users:read.email` scopes. Define `/ingest_book` and `/ingest_wiki` slash commands in the Slack app manifest, and retain the bare-word `ingest_book`/`ingest_wiki` message form for files attached directly to a message.

## Deployment example (navigator-agent-server)

In `navigator-agent-server`, add this to the relevant curator bot entries in `env/integrations_bots.yaml`. Configure the same login requirements on every bot that accepts uploads.

```yaml
enable_login: true
force_authentication: true
knowledge_upload:
  enabled: true
  allowed_usernames: [jdoe]
  allowed_groups: [knowledge_curators]
  max_size_mb: 10
  bookstore:
    library_dir: "${ODOO_LIBRARY_DIR}"
  wiki:
    wiki_root: "${ODOO_WIKI_ROOT}"
```

Create the user-authored charter at `${ODOO_WIKI_ROOT}/.parrot/charter.yaml` before enabling the wiki target.

## Limitations

- Same-name uploads replace prior staged content; use distinct filenames when the documents must remain distinguishable.
- Bookstore cards and wiki manifests retain a `source_path` to a staged file that has been deleted. Refresh or reingest operations cannot reread it; upload the original again.
- A process restart loses running jobs and removes their staged files during startup cleanup. The user must upload the original again.
