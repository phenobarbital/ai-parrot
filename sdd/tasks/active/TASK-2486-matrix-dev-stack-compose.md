# TASK-2486: Matrix Dev Stack — docker-compose, bridges profile, bootstrap script

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Replaces the bare single-service `docker-compose.matrix.yml` with a dev
stack: Synapse (pinned) + Postgres 16 + Element Web + a `.well-known` sidecar (Element X
discovery), and a `bridges` profile with **mautrix-signal, mautrix-slack, mautrix-discord**
only (resolved decisions: no e-mail, Instagram/XMPP docs-only). Zero overlap with Python
tasks — `parallel: true`.

---

## Scope

- Rewrite `docker-compose.matrix.yml`:
  - `postgres` (`postgres:16-alpine`, db `synapse` + bridge dbs via init script `docker/matrix/postgres/init.sql`), healthcheck.
  - `synapse` (`ghcr.io/element-hq/synapse:v1.15x` — pin the current stable at implementation time,
    ≥1.114 for native sliding sync), `SYNAPSE_SERVER_NAME=parrot.local`, volume `./docker/matrix/synapse:/data`,
    port 8008, depends_on postgres healthy, healthcheck `/health`.
  - `element-web` (`vectorim/element-web:v1.12.x`), port 8080, `docker/matrix/element/config.json`
    (`default_server_config.m.homeserver.base_url=http://localhost:8008`, `default_server_name=parrot.local`).
  - `well-known` (`nginx:alpine`) serving `/.well-known/matrix/client` and `/server` JSON on port 8448→80.
  - profile `bridges`: `mautrix-signal` (`dock.mau.dev/mautrix/signal:v26.07`), `mautrix-slack`
    (`dock.mau.dev/mautrix/slack:v26.08`), `mautrix-discord` (`dock.mau.dev/mautrix/discord:v0.7.7`), each with
    `./docker/matrix/bridges/<name>:/data` and a committed `config.yaml` template + generated `registration.yaml`
    (git-ignored); Synapse `homeserver.yaml` template lists them under `app_service_config_files` plus
    `/data/appservices/parrot.yaml`.
- `docker/matrix/synapse/homeserver.yaml.tmpl` — Postgres, `enable_registration: false`, registration shared secret from env,
  `app_service_config_files`, `rc_message` relaxed for bots, `experimental_features` none.
- `scripts/matrix/bootstrap.sh` (bash, `set -euo pipefail`, `--dry-run` flag): (1) `docker compose ... run --rm synapse generate`
  if no config; (2) render `homeserver.yaml` from template with `envsubst`; (3) generate the parrot AppService registration by
  calling `python -m parrot.integrations.matrix.registration` — add a `__main__` guard to `registration.py` that prints
  `generate_registration(...)` YAML from env; (4) start stack; (5) `register_new_matrix_user` for the coordinator; (6) print
  Element Web URL, Element X server address, and next steps. Secrets via `.env` (`docker/matrix/.env.example` committed).
- `.gitignore`: `docker/matrix/**/registration.yaml`, `docker/matrix/synapse/*.signing.key`, `docker/matrix/.env`.
- Test: `tests/test_matrix_compose.py` validating `docker compose config` (skip if docker missing) and
  the `registration.py` `__main__` output.

**NOT in scope**: Python swarm code; docs beyond inline comments (TASK-2487).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docker-compose.matrix.yml` | MODIFY | full dev stack |
| `docker/matrix/synapse/homeserver.yaml.tmpl` | CREATE | Synapse config template |
| `docker/matrix/postgres/init.sql` | CREATE | create bridge databases |
| `docker/matrix/element/config.json` | CREATE | Element Web config |
| `docker/matrix/well-known/{nginx.conf,client.json,server.json}` | CREATE | discovery |
| `docker/matrix/bridges/{signal,slack,discord}/config.yaml` | CREATE | bridge config templates |
| `docker/matrix/.env.example` | CREATE | secrets template |
| `scripts/matrix/bootstrap.sh` | CREATE | bootstrap |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/registration.py` | MODIFY | `__main__` entry |
| `.gitignore` | MODIFY | ignore generated secrets |
| `packages/ai-parrot-integrations/tests/test_matrix_compose.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.registration import generate_registration, generate_tokens   # registration.py:20, :15
```

### Existing Signatures to Use
```python
# registration.py
def generate_tokens() -> tuple[str, str]                                  # :15  (as_token, hs_token)
def generate_registration(...)                                            # :20  — read the file for its parameters before use (id, url, tokens, namespaces)
# current docker-compose.matrix.yml: single service `synapse` (matrixdotorg/synapse:latest), port 8008, volume synapse-data, healthcheck on /health
# AppService listener defaults: MatrixAppServiceConfig.listen_port=9090 (models.py:7), MatrixCrewConfig.appservice_port=8449 (config.py:139)
```
External facts: mautrix bridges mount `/data`, generate `registration.yaml` on first run
(`docker run --rm -v $(pwd)/data:/data <image>`), and need `homeserver.address` + `appservice.address` reachable from Synapse
(use compose service names, e.g. `http://mautrix-slack:29335`). Synapse reads AppService files from `app_service_config_files`.

### Does NOT Exist
- ~~Postgres, Element, bridges, `.well-known` in the current compose~~ — you add them.
- ~~e-mail (Postmoogle), Instagram (mautrix-meta), XMPP services~~ — MUST NOT be added (resolved decision).
- ~~`registration.py __main__`~~ — you add it.

---

## Implementation Notes

### Compose skeleton
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: synapse, POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-synapse}, POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C" }
    volumes: [ pgdata:/var/lib/postgresql/data, ./docker/matrix/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro ]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U synapse"], interval: 5s, retries: 10 }
  synapse:
    image: ghcr.io/element-hq/synapse:${SYNAPSE_VERSION:-v1.157.2}
    depends_on: { postgres: { condition: service_healthy } }
    environment: [ SYNAPSE_SERVER_NAME=parrot.local, SYNAPSE_REPORT_STATS=no ]
    volumes: [ ./docker/matrix/synapse:/data ]
    ports: [ "8008:8008" ]
    extra_hosts: [ "host.docker.internal:host-gateway" ]   # so Synapse reaches the parrot AppService on the host (:8449)
  element-web: { image: vectorim/element-web:${ELEMENT_VERSION:-v1.12.26}, ports: ["8080:80"], volumes: [ ./docker/matrix/element/config.json:/app/config.json:ro ] }
  well-known: { image: nginx:alpine, ports: ["8448:80"], volumes: [ ./docker/matrix/well-known/nginx.conf:/etc/nginx/conf.d/default.conf:ro, ./docker/matrix/well-known:/usr/share/nginx/html/.well-known/matrix:ro ] }
  mautrix-signal:  { image: dock.mau.dev/mautrix/signal:v26.07,  profiles: [bridges], volumes: [ ./docker/matrix/bridges/signal:/data ],  depends_on: [synapse] }
  mautrix-slack:   { image: dock.mau.dev/mautrix/slack:v26.08,   profiles: [bridges], volumes: [ ./docker/matrix/bridges/slack:/data ],   depends_on: [synapse] }
  mautrix-discord: { image: dock.mau.dev/mautrix/discord:v0.7.7, profiles: [bridges], volumes: [ ./docker/matrix/bridges/discord:/data ], depends_on: [synapse] }
volumes: { pgdata: {} }
```

### Key Constraints
- Dev-only: no TLS, no workers (resolved decision). Say so in the header comment.
- The parrot AppService runs on the host (`appservice_port: 8449`); its registration `url` must be
  `http://host.docker.internal:8449`.
- Never commit generated tokens/keys.

---

## Acceptance Criteria

- [ ] `docker compose -f docker-compose.matrix.yml --profile bridges config` succeeds (CI-safe test skips without docker)
- [ ] Services present: postgres, synapse, element-web, well-known, mautrix-signal, mautrix-slack, mautrix-discord — nothing else
- [ ] `scripts/matrix/bootstrap.sh --dry-run` prints the six steps without side effects
- [ ] `python -m parrot.integrations.matrix.registration` prints valid registration YAML (test parses it)
- [ ] Generated secrets are git-ignored (`git check-ignore docker/matrix/bridges/slack/registration.yaml`)

---

## Test Specification

```python
# tests/test_matrix_compose.py
import shutil, subprocess, sys, yaml, pytest, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[3]

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_compose_config_valid():
    out = subprocess.run(["docker", "compose", "-f", "docker-compose.matrix.yml", "--profile", "bridges", "config"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    services = set(yaml.safe_load(out)["services"])
    assert services == {"postgres", "synapse", "element-web", "well-known", "mautrix-signal", "mautrix-slack", "mautrix-discord"}

def test_compose_has_no_dropped_bridges():
    text = (ROOT / "docker-compose.matrix.yml").read_text()
    for banned in ("postmoogle", "mautrix/meta", "instagram", "jabber", "slidge", "xmpp"):
        assert banned not in text.lower()

def test_registration_main_outputs_yaml():
    out = subprocess.run([sys.executable, "-m", "parrot.integrations.matrix.registration"], capture_output=True, text=True, check=True,
                         env={"PATH": "", "MATRIX_AS_URL": "http://host.docker.internal:8449", "MATRIX_SERVER_NAME": "parrot.local"}).stdout
    reg = yaml.safe_load(out)
    assert reg["url"] == "http://host.docker.internal:8449" and "as_token" in reg and "hs_token" in reg

def test_bootstrap_dry_run():
    r = subprocess.run(["bash", "scripts/matrix/bootstrap.sh", "--dry-run"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "register_new_matrix_user" in r.stdout
```

---

## Agent Instructions

Same as TASK-2478. This task may run in its own worktree (`parallel: true`).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
