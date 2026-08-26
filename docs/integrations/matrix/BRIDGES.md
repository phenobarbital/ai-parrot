# Matrix Bridges for the AI-Parrot Swarm (FEAT-463)

Bridges let humans on Slack, Signal, and Discord talk to the agent swarm as
if they were native Matrix users — bridged puppets are classified as human
by `MatrixCrewRegistry.is_human()` exactly like anyone else (mentions and
`swarm`-policy channels behave identically for them). This page documents
which bridges ship with the dev stack, how to configure them, and which
integrations were **evaluated and rejected**.

## Licensing

Synapse, Element Web, and every mautrix bridge listed below are
**AGPL-3.0-licensed** and run as **separate Docker containers** — they are
never imported by, linked against, or distributed with the MIT-licensed
`ai-parrot` Python code. `docker-compose.matrix.yml` only orchestrates
them as independent processes communicating over the Matrix
Application Service HTTP protocol.

## Shipped bridges (`bridges` compose profile)

```bash
docker compose -f docker-compose.matrix.yml --profile bridges up -d
```

| Bridge | Image | Config template | Notes |
|---|---|---|---|
| **Signal** | `dock.mau.dev/mautrix/signal:v26.07` | `docker/matrix/bridges/signal/config.yaml` | Uses linked-device login (no phone number stored by the bridge). Run `docker compose exec mautrix-signal signal-cli-link` (or the bridge's own `link` bot command in a DM) after first start. |
| **Slack** | `dock.mau.dev/mautrix/slack:v26.08` | `docker/matrix/bridges/slack/config.yaml` | Login via cookie/token in a DM with the bridge bot (`slackbot`); prefer a dedicated Slack account over your personal one. |
| **Discord** | `dock.mau.dev/mautrix/discord:v0.7.7` | `docker/matrix/bridges/discord/config.yaml` | **Bot-account login is recommended** over a user token — create a Discord bot application and DM the bridge bot with `login-bot`; this avoids Discord ToS risk associated with self-bot tokens. |

All three bridges share the Postgres instance from `docker-compose.matrix.yml`
(separate `mautrix_signal` / `mautrix_slack` / `mautrix_discord` databases,
created by `docker/matrix/postgres/init.sql`). Credentials (Slack token,
Discord bot token, etc.) are entered interactively via DM to each bridge
bot after it starts — **never put them in `docker/matrix/.env`** beyond
the shared `POSTGRES_PASSWORD`; per-bridge `registration.yaml` files are
generated on first run and are git-ignored (`docker/matrix/**/registration.yaml`).

## Not shipped (documented only)

These integrations were evaluated during the FEAT-463 brainstorm and
**deliberately excluded** from `docker-compose.matrix.yml`:

### Instagram (`mautrix-meta`)

Meta's private API used by `mautrix-meta` for Instagram DMs is
unofficial and has historically been unstable across Meta's backend
changes. If you need it anyway, add a service block modeled on the
shipped bridges:

```yaml
  mautrix-meta-instagram:
    image: dock.mau.dev/mautrix/meta:latest
    profiles: [bridges]
    volumes:
      - ./docker/matrix/bridges/instagram:/data
    depends_on:
      - synapse
```

### XMPP (`mautrix-jabber` / `slidge` + `matridge`)

XMPP bridging via `mautrix-jabber` (unmaintained) or the newer
`slidge` + `matridge` combination is immature upstream relative to the
Signal/Slack/Discord bridges above. If needed, follow the same pattern —
a new profiled service pointing at a `slidge`/`matridge` image, its own
Postgres database, and a `registration.yaml` referenced from
`docker/matrix/synapse/homeserver.yaml.tmpl`'s `app_service_config_files`.

### E-mail (Postmoogle)

Rejected. AI-Parrot agents already have a first-class e-mail channel via
`parrot.notifications.NotificationMixin`
(`packages/ai-parrot/src/parrot/notifications/__init__.py:60`,
the `async-notify` integration) — routing e-mail through a Matrix bridge
would duplicate that capability for no benefit. If an agent needs to
send e-mail, use `NotificationMixin` directly rather than Matrix
(`grep -rn "class notificationmixin" packages/ai-parrot/src/parrot/notifications/ -i`
to find it if the class ever moves).

## Alternative homeserver

**Tuwunel** (Apache-2.0, a Rust reimplementation of the Matrix homeserver
API) is a lighter-weight alternative to Synapse for local development.
The dev stack pins Synapse because it is the reference implementation
with the widest bridge/client compatibility, but Tuwunel is documented
here as an option if you want to experiment with a lower-resource
homeserver — the `MatrixCrewConfig` / `MatrixAppService` layer only
depends on the standard Client-Server and Application Service HTTP APIs,
so either homeserver works without code changes.

## See also

- `docs/integrations/matrix/CLIENTS.md` — which Matrix client to use for
  development.
- `examples/matrix_crew/MATRIX_CREW_GUIDE.md` — swarm usage, including how
  bridged/human classification works (`human_namespace_patterns`).
- `docker-compose.matrix.yml` — the full dev stack definition.
