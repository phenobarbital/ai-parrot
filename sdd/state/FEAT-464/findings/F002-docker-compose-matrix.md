# F002: docker-compose.matrix.yml — Full Dev Stack

**Query**: read docker-compose.matrix.yml
**Source**: docker-compose.matrix.yml (root)

## Key Facts

The compose file already implements the FULL dev stack (TASK-2486 appears already done in code):
- **postgres** (16-alpine) with healthcheck + init.sql for bridge DBs
- **synapse** (ghcr.io/element-hq/synapse:v1.157.2) with Postgres, port 8008, healthcheck, extra_hosts for host AppService
- **element-web** (v1.12.26) on port 8080
- **well-known** (nginx:alpine) on port 8448 for Element X discovery
- **bridges profile**: mautrix-signal (v26.07), mautrix-slack (v26.08), mautrix-discord (v0.7.7)
- **pgdata** named volume

### Supporting Files (all exist)
- docker/matrix/synapse/ — Synapse data/config volume
- docker/matrix/postgres/init.sql — bridge DB creation
- docker/matrix/element/config.json — Element Web config
- docker/matrix/well-known/{nginx.conf, client.json, server.json}
- docker/matrix/bridges/{signal,slack,discord}/ — bridge data dirs
- docker/matrix/.env.example — secrets template

### Quickstart
```bash
cp docker/matrix/.env.example docker/matrix/.env
./scripts/matrix/bootstrap.sh          # 6-step automated setup
```

### Implication for FEAT-464
Docker stack is already production-grade. Sample does NOT need its own compose — it should reference/reuse this one. The gap is in agent configuration, not infrastructure.
