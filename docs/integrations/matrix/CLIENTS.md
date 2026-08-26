# Matrix Clients for the AI-Parrot Swarm (FEAT-463)

This page documents which Matrix client to use when developing against, or
demoing, the AI-Parrot agent swarm — and why. It complements
`examples/matrix_crew/MATRIX_CREW_GUIDE.md` (setup/usage) and
`docker-compose.matrix.yml` / `scripts/matrix/bootstrap.sh` (the dev stack
these clients connect to).

## Recommended clients

| Client | Platform | Version | License | Why |
|---|---|---|---|---|
| **Element Desktop / Element Web** | Linux (primary) | v1.12.x | AGPL-3.0 | Full feature set: Spaces, threads, reply-to rendering, pinned messages. Hides unrecognised custom events (`m.parrot.*`) cleanly instead of erroring. Best default choice for demoing the swarm to non-technical users. |
| **Nheko** | Linux (secondary) | v0.12.x | GPL-3.0 | Native Qt client, low RAM footprint. Shows the **raw event source** for any message — useful for inspecting `m.parrot.task` / `m.parrot.result` / `m.parrot.channel` / `m.parrot.tunnel` events directly while developing the swarm. |
| **Element X** | Mobile (iOS/Android) | v26.08 | AGPL-3.0 | Modern Rust-based client. Requires **native sliding sync** (Synapse ≥1.114, already pinned by the dev stack) and `.well-known/matrix/client` discovery (served by the `well-known` sidecar container on `:8448`). |

### Alternatives (not the default, but usable)

- **Fractal** (GTK, GPL-3.0) and **Cinny** (web, AGPL-3.0) are lighter
  alternatives to Element on Linux; both render reply-to and Spaces
  correctly but lack Nheko's raw-event inspector.
- **FluffyChat** (cross-platform, AGPL-3.0) works for basic messaging but
  **does not render threads** — since the swarm's collaborative sessions
  and cross-pollination echoes rely on `m.in_reply_to` (not `m.thread`,
  see spec §6 "Does NOT Exist"), this is a soft caveat rather than a
  blocker, but thread-heavy conversations will look flatter in FluffyChat.

## Login walkthrough (dev stack)

1. Start the dev stack: `./scripts/matrix/bootstrap.sh` (see
   `docker/matrix/.env.example` for the secrets it needs first).
2. **Element Web**: open `http://localhost:8080`.
3. **Element Desktop / Nheko / Fractal / Cinny**: point at homeserver
   `http://localhost:8008` directly, or by server name `parrot.local`
   (resolved via the well-known sidecar on `http://localhost:8448`).
4. **Element X** (mobile, same machine or LAN): enter server name
   `parrot.local`; discovery works only if your mobile device can reach
   `http://localhost:8448/.well-known/matrix/client` — on a real network
   this means exposing the well-known + Synapse ports, not just
   `localhost`.
5. Log in with the coordinator account created by `bootstrap.sh`
   (`MATRIX_COORDINATOR_USER` / `MATRIX_COORDINATOR_PASSWORD` from
   `docker/matrix/.env`), or register a new personal account if
   `enable_registration` is turned on for your dev homeserver.
6. Join the general room (or any declared `swarm`/`mention` channel) to
   start talking to the agents — see `MATRIX_CREW_GUIDE.md` for the full
   command reference (`!channels`, `!agents`, `!tunnels`, `!investigate`).

## Notes

- All of the above are **dev-only** recommendations — the compose stack
  runs without TLS or Synapse workers (see `docker-compose.matrix.yml`
  header comment).
- Nheko's raw-event view is the fastest way to debug a swarm feature that
  isn't behaving as expected (mis-routed tunnel task, missing echo line,
  etc.) without adding logging to the Python side.
