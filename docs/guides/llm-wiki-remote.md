# LLM Wiki — Remote MCP server (FEAT-569)

## Why

Run one wiki service for a team instead of giving every developer and coding
agent direct access to ArangoDB.  The server owns the graph connection and
ledger files; clients use a bearer token over HTTP(S).

## Server

### `server.yaml` reference

Each key under `wikis` names the mount at `<base_path>/<wiki-name>`.  Its
`root` contains that wiki's `.parrot/wiki.json`; `env`, `ledger_dir`, and
`description` are optional.

```yaml
host: 127.0.0.1             # default
port: 8765                  # default
base_path: /mcp             # default
token_env: WIKITOOLKIT_SERVER_TOKEN
default_actor: agent:unknown
allowed_origins: null
ssl_cert_path: null
ssl_key_path: null
session_ttl: 3600
allow_sqlite_for_tests: false # test-only; production wikis must use ArangoDB
wikis:
  parrot:
    root: /srv/wikis/parrot
    env: production
    ledger_dir: /var/lib/wikitoolkit/parrot-ledger
    description: Shared engineering wiki
```

### Running

Install the server extra, provide a long random token outside the config file,
and start exactly one process:

```bash
pip install 'ai-parrot[wikitoolkit-server]'
export WIKITOOLKIT_SERVER_TOKEN='replace-with-a-secret'
wikitoolkit serve --config server.yaml
```

`--host`, `--port`, `--ssl-cert`, and `--ssl-key` override the file.  The
server keeps MCP sessions in memory, so do not start multiple workers unless a
load balancer supplies sticky routing.  Prefer TLS termination at a reverse
proxy; direct TLS with `--ssl-cert` and `--ssl-key` is also supported.  The
server host, not clients, needs ArangoDB reachability and writable local disk
for the SQLite ledger.

## Client

### Configure a repository

Configure one mounted wiki in `.parrot/wiki.json`:

```json
{
  "wiki_name": "parrot",
  "remote": {
    "url": "https://wiki.example.com/mcp/parrot",
    "token_env": "WIKITOOLKIT_TOKEN",
    "timeout": 30.0,
    "verify_tls": true
  }
}
```

Use `.parrot/wiki.<environment>.json` to overlay this per environment.
`WIKITOOLKIT_REMOTE_URL` overrides the configured URL; the token always comes
from the configured token environment variable (default
`WIKITOOLKIT_TOKEN`).

### What works remotely

`query`, `page`, `related`, `status`, `remember`, `note`, structural
`symbols` commands, and the supported ledger commands proxy to MCP tools.
`build`, `upsert`, and `ingest` scan the local checkout, then push changed
source slices; use `--no-push` to leave a local scan unpushed.  `sync push`
and `sync pull` transfer authored pages and asserted edges.

### What is refused

Remote mode refuses `--store` and `--backend`, `ns`, `communities`, `export`,
`link`, `memories`, `audit`, `ground`, `ingest-jira`, Obsidian sync, and
non-tool ledger subcommands.  This avoids silently opening a local plane when
a repository explicitly chose remote mode.

### Errors

Remote failures exit with code 2 and a `[remote:<code>]` prefix.

| Code | Meaning and fix |
|---|---|
| `token_missing` | Set the configured token environment variable. |
| `unauthorized` | Check the bearer token and reverse-proxy forwarding. |
| `wiki_not_found` | Check the mounted wiki name and URL path. |
| `unreachable` | Check DNS, routing, and that the server is running. |
| `timeout` | Check service load and increase `remote.timeout` if appropriate. |
| `protocol` | Check proxy support for Streamable HTTP MCP. |
| `tool_error` | Inspect the server logs and tool arguments. |
| `session_expired` | Retry a read; writes are deliberately not replayed. |

## Coding agents

### Pass-through (default)

Existing `wikitoolkit mcp` installations automatically forward `tools/list`
and `tools/call` when `remote` is configured.  Nothing must be reinstalled;
the proxy carries `X-Wiki-Actor`.  This is the recommended Codex path.

### Native HTTP (optional)

Native registrations avoid the local proxy:

```bash
parrot claude install --remote --remote-url https://wiki.example.com/mcp/parrot
parrot codex install --remote --remote-url https://wiki.example.com/mcp/parrot
```

Both commands accept `--token-env NAME`; without `--remote-url`, `--remote`
uses the repository configuration.  Codex native HTTP registration cannot
send an actor header, so writes use the server's `default_actor`.

## Limitations (v1)

The ledger remains SQLite on server disk and `merge_blockers` is empty on the
server.  Batch ingestion is atomic per source slice, not across a whole
request.  Sync has no tombstones.  Structural tools require the server's
symbol plane; verify the ArangoDB symbol plane against a real service before
release.  Vector search is not proxied remotely.
