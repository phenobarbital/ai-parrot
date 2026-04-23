# DynamoDB Local (docker-compose)

This page documents the local DynamoDB stack we use for developing the
storage layer (`parrot.storage.dynamodb`, `parrot.storage.chat`,
`parrot.storage.artifacts`) without hitting real AWS.

Compose file: [`docker-compose.dynamodb.yml`](../docker-compose.dynamodb.yml)
Init script:  [`scripts/init_dynamodb_local.py`](../scripts/init_dynamodb_local.py)

---

## What you get

Two containers, one named volume:

| Service           | Image                            | Port  | Purpose                         |
|-------------------|----------------------------------|-------|---------------------------------|
| `dynamodb-local`  | `amazon/dynamodb-local:latest`   | 8000  | The DynamoDB engine             |
| `dynamodb-admin`  | `aaronshaf/dynamodb-admin:latest`| 8001  | Web UI to browse tables / items |

Persistence: the `dynamodb-local-data` named volume — data survives
`docker compose down` but is wiped by `docker compose down -v`.

The `dynamodb-local` container runs with `-sharedDb`, so every client
sees the same database file regardless of the access-key / region it
presents. This matches the "one developer, one laptop" use case — no
accidental partitioning by credentials.

---

## First-time setup

```bash
# 1. Bring the stack up
docker compose -f docker-compose.dynamodb.yml up -d

# 2. Activate the venv (required by project rules)
source .venv/bin/activate

# 3. Create the parrot-conversations and parrot-artifacts tables,
#    plus enable the "ttl" TTL attribute on both.
python scripts/init_dynamodb_local.py
```

After step 3 you can open the admin UI at <http://localhost:8001> and
see two empty tables.

---

## Configuration (env/.env)

A dedicated `[dynamodb]` section is appended to `env/.env`:

```ini
[dynamodb]
DYNAMODB_ENDPOINT_URL=http://localhost:8000
DYNAMODB_REGION=us-east-1
DYNAMODB_CONVERSATIONS_TABLE=parrot-conversations
DYNAMODB_ARTIFACTS_TABLE=parrot-artifacts
```

These map 1-to-1 onto the variables read in
`packages/ai-parrot/src/parrot/conf.py`:

- `DYNAMODB_ENDPOINT_URL` — when set, `parrot.storage.chat` passes it
  through to `aioboto3.resource("dynamodb", endpoint_url=...)`,
  pointing the client at the container instead of AWS.
- `DYNAMODB_REGION` — any valid AWS region string; DynamoDB Local
  does not enforce it, but `boto3` requires one.
- `DYNAMODB_CONVERSATIONS_TABLE` / `DYNAMODB_ARTIFACTS_TABLE` —
  table names used by `ConversationDynamoDB`.

### Credentials

`ConversationDynamoDB` takes its credentials from `AWS_ACCESS_KEY` /
`AWS_SECRET_KEY` in `conf.py`, which fall back to the existing
`AWS_KEY` / `AWS_SECRET` variables in `env/.env`. **No new keys are
required** — DynamoDB Local accepts any non-empty credential pair,
and with `-sharedDb` it ignores the access key for partitioning
anyway. The existing prod-looking AWS keys in `env/.env` work fine.

To use real AWS DynamoDB again, comment out `DYNAMODB_ENDPOINT_URL`
(or delete the line): `conf.py` defaults it to `None`, which makes
`aioboto3` go to the real regional endpoint.

---

## Day-to-day commands

```bash
# Start / stop / tail logs
docker compose -f docker-compose.dynamodb.yml up -d
docker compose -f docker-compose.dynamodb.yml down
docker compose -f docker-compose.dynamodb.yml logs -f dynamodb-local

# Wipe ALL local data (drops the named volume)
docker compose -f docker-compose.dynamodb.yml down -v

# One-shot CLI check against the running container
aws dynamodb list-tables \
  --endpoint-url http://localhost:8000 \
  --region us-east-1
```

---

## Table schema (what the init script creates)

Both tables share the same composite key design, matching the
`_build_pk` / `_build_sk` helpers in
`packages/ai-parrot/src/parrot/storage/dynamodb.py`:

| Attribute | Type   | Role                                               |
|-----------|--------|----------------------------------------------------|
| `PK`      | String | Partition key — `USER#<user_id>#AGENT#<agent_id>`  |
| `SK`      | String | Sort key — `THREAD#<session_id>` / `...#TURN#<id>` |
| `ttl`     | Number | TTL epoch seconds (180-day default)                |

Billing mode is `PAY_PER_REQUEST`. TTL is enabled on the `ttl`
attribute so expired rows disappear automatically (real AWS only —
DynamoDB Local registers the setting but does not actively expire).

---

## Troubleshooting

**`Connection refused` from Python.** Make sure the container is up
(`docker ps | grep parrot-dynamodb-local`) and that
`DYNAMODB_ENDPOINT_URL` is `http://localhost:8000`, not `127.0.0.1`
inside another container.

**`ResourceNotFoundException: Cannot do operations on a non-existent
table`.** You skipped `python scripts/init_dynamodb_local.py`.

**Port 8000 already in use.** Something else owns the port. Edit the
`ports:` block in `docker-compose.dynamodb.yml` (e.g. `"8010:8000"`)
and update `DYNAMODB_ENDPOINT_URL` to match.

**I want a clean slate.** `docker compose -f
docker-compose.dynamodb.yml down -v && docker compose -f
docker-compose.dynamodb.yml up -d && python
scripts/init_dynamodb_local.py`.
