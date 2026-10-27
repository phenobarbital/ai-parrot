---
id: F007
query_id: Q030
type: read
intent: "Read docker-compose.matrix.yml: what homeserver stack is already provisioned for local development."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-009
---

# F007 — Matrix dev stack provisioned: Synapse, Element, well-known, bridges

## Summary

`docker-compose.matrix.yml` (FEAT-463) provisions a dev homeserver stack: Postgres 16, Synapse (`ghcr.io/element-hq/synapse:v1.157.2`, server name `parrot.local`, port 8008), Element Web (8080), an nginx well-known sidecar (8448) and an optional `bridges` profile with mautrix Signal/Slack/Discord. The parrot AppService runs on the host on `appservice_port: 8449` (`MatrixCrewConfig` default). Bootstrap is `scripts/matrix/bootstrap.sh`; docs in `docs/integrations/matrix/BRIDGES.md`.

## Citations

- path: `docker-compose.matrix.yml`
  lines: 1-20
  symbol: `header`
  excerpt: |
    # Matrix Agents Swarm — Dev Stack (FEAT-463)
    # The parrot AppService itself runs on the HOST (not in this compose file),
    # listening on `appservice_port: 8449` (MatrixCrewConfig default)

- path: `docker-compose.matrix.yml`
  lines: 39-62
  symbol: `synapse service`
  excerpt: |
    image: ghcr.io/element-hq/synapse:${SYNAPSE_VERSION:-v1.157.2}
    SYNAPSE_SERVER_NAME: parrot.local
    ports: - "8008:8008"

- path: `docker-compose.matrix.yml`
  lines: 86-117
  symbol: `bridges profile`
  excerpt: |
    mautrix-signal / mautrix-slack / mautrix-discord (profiles: [bridges])

## Notes

Spike L-S6 (Matrix carrier) can run against this stack as-is.
