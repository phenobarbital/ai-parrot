# TASK-4375: docker/helixdb stack, `make docker-helixdb`, docs skeleton and embedded two-writer spike

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4373, TASK-4374
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (delegation-eligible): the local/shared HelixDB **server** stack, its
Makefile target, the operator docs skeleton, and the embedded two-writer spike (resolved
Q4 — wording only). The server is what serves the local multi-process workflow (G8:
post-commit hook + MCP server + parallel sessions). The spike records the exact error a
second embedded writer sees on the same `Disk` source; TASK-4376 uses that wording for the
`wiki.lock` guard message and TASK-4397 completes the docs.

Depends on TASK-4373 only because the spike needs the `helix-db-embedded` wheel declared
in the dev group and `open_helix_client`.

---

## Scope

- Create `docker/helixdb/Dockerfile`, `docker/helixdb/docker-compose.yml`, `docker/helixdb/README.md`
  following the `docker/arango/` precedent.
- Add a `docker-helixdb` Makefile target (before `docker-dev:`), its help line, and the
  `.PHONY` entry. **No** embedded-mode target (resolved Q2).
- Create `docs/wiki/helixdb.md` skeleton: Start · Env vars · Modes (server / embedded / memory).
- Add one cheatsheet line next to the ArangoDB `build --backend` example.
- Run the two-writer spike and write `sdd/state/FEAT-670/spike-embedded-two-writers.md`.

**NOT in scope**: migration-per-plane, ledger rebuild, projections and embedded-guard
sections of `docs/wiki/helixdb.md` (TASK-4397); live compose test `test_compose_readyz`
(TASK-4397); the `wiki.lock` guard code itself (TASK-4376); any CI workflow edit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docker/helixdb/Dockerfile` | CREATE | thin `FROM ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG}` wrapper with labels |
| `docker/helixdb/docker-compose.yml` | CREATE | service `helixdb`, named volume, `/readyz` healthcheck |
| `docker/helixdb/README.md` | CREATE | Start · Env vars · Persistence · Upgrading (backup first) · Troubleshooting |
| `Makefile` | MODIFY | `docker-helixdb` target + help line + `.PHONY` |
| `docs/wiki/helixdb.md` | CREATE | skeleton (start, env vars, modes) |
| `docs/wiki/cheatsheet.md` | MODIFY | `wikitoolkit build --backend helixdb` line |
| `sdd/state/FEAT-670/spike-embedded-two-writers.md` | CREATE | observed error class/message of a second embedded writer |

---

## Codebase Contract (Anti-Hallucination)

Verified on dev @ `1c239a5ca`.

### Verified Imports
```python
# spike script only (kept out of the repo, e.g. in /tmp or the session scratchpad):
from parrot.knowledge.helix import HelixMode, HelixSettings, open_helix_client   # TASK-4373/4374
```

### Existing Signatures to Use
```text
docker/arango/Dockerfile            — precedent: `# syntax=docker/dockerfile:1.7`, FROM, OCI LABELs, EXPOSE
docker/arango/docker-compose.yml    — precedent: container_name parrot-*, restart unless-stopped,
                                      "${PORT:-…}:…", named volumes `name: parrot-*-data`, wget --spider healthcheck
Makefile:4-12   .PHONY list; line 9 ends `injection-model docker-tool-worker docker-integrations docker-dev \`
Makefile:917-923  `docker-dev:` target (comment block above at :917-919)
Makefile:1097   `	@echo "    docker-whatsapp-bridge   - Build and run in Docker"`
docs/wiki/cheatsheet.md:43  `wikitoolkit build --backend arangodb # plano compartido en ArangoDB`
Server (spec §6): image ghcr.io/helixdb/helixdb:v0.0.12, container port 8080, /healthz, /readyz, HELIX_DATA_DIR, uid 65532
```

### Edit anchors
| File | Verbatim anchor | `grep -c -F` | Line |
|---|---|---|---|
| `Makefile` | `docker-dev:` | 1 | :920 |
| `Makefile` | `	@echo "    docker-whatsapp-bridge   - Build and run in Docker"` | 1 | :1097 |
| `Makefile` | `		install-supertonic install-obscura injection-model docker-tool-worker docker-integrations docker-dev \` | 1 | :9 |
| `docs/wiki/cheatsheet.md` | `wikitoolkit build --backend arangodb # plano compartido en ArangoDB` | 1 | :43 |

### Does NOT Exist
- ~~`docker/helixdb/`, `docs/wiki/helixdb.md`, `sdd/state/FEAT-670/`~~ — created here.
- ~~A Makefile target for embedded mode~~ — deliberately not created (Q2, AC12).
- ~~`helix compile` / `helix deploy` / `.hx` files~~ — legacy workflow; v3 has no deploy step.
- ~~`curl` in the HelixDB image~~ — unverified; use `wget -q --spider` as the spec's compose sketch does.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docker/helixdb/Dockerfile", "action": "CREATE"},
    {"path": "docker/helixdb/docker-compose.yml", "action": "CREATE"},
    {"path": "docker/helixdb/README.md", "action": "CREATE"},
    {"path": "Makefile", "action": "MODIFY"},
    {"path": "docs/wiki/helixdb.md", "action": "CREATE"},
    {"path": "docs/wiki/cheatsheet.md", "action": "MODIFY"},
    {"path": "sdd/state/FEAT-670/spike-embedded-two-writers.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Exclusive resource**: `Makefile` (spec Worktree Strategy). No other task edits it.
- Compose (spec §3 M2, AC12): `image: ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG:-v0.0.12}`,
  `container_name: parrot-helixdb`, `ports: ["${HELIXDB_PORT:-6969}:8080"]`,
  `HELIX_DATA_DIR: /var/lib/helix`, volume `helixdb-data` named `parrot-helixdb-data`,
  healthcheck `wget -q --spider http://127.0.0.1:8080/readyz || exit 1` (interval 5s, timeout 3s,
  retries 20, start_period 10s), `user: "65532:65532"`, `restart: unless-stopped`.
  If `wget` is absent from the image (verify with `docker run --rm --entrypoint sh <image> -c 'command -v wget'`),
  record it in the Completion Note and switch the healthcheck to whatever probe the image ships.
- README sections are fixed by spec §3 M2: Start · Env vars (`HELIXDB_URL`, `HELIXDB_API_KEY`,
  `HELIXDB_IMAGE_TAG`, `HELIXDB_PORT`) · Persistence · **Upgrading** (one-way index storage version;
  back up first with
  `docker run --rm -v parrot-helixdb-data:/data -v "$PWD":/backup alpine tar czf /backup/helixdb-<date>.tgz -C /data .`)
  · Troubleshooting (`/healthz`, `/readyz`, uid 65532 on bind mounts).
- Spike: open two **separate processes** (not two clients in one process) on the same
  `Disk(<tmp>, "spike")` writer source via `open_helix_client(HelixSettings(mode=EMBEDDED, root=…, database="spike"))`;
  record Python exception class, `HelixError` attribute flags (`.embedded`, `.embedded_unavailable`, …),
  message text, SDK/wheel versions, OS/glibc, and whether a reader (`read_only=True`) can coexist.
  The spike script itself is **not** committed; paste it into the spike document.
- Never `uv sync` in the worktree; run the spike with
  `uv run --no-sync --with helix-db==0.3.4 --with helix-db-embedded==0.3.3 python <script>`.
  If the wheel cannot be installed (no network / glibc < 2.28) write the spike doc with
  "NOT RUN — reason" and close the task `partial`.
- Docs are English Markdown; the cheatsheet is Spanish — match its tone on the new line.

---

## Implementation Blueprint

### Steps (in order)
1. Write `docker/helixdb/*` — *why*: AC12.
2. Edit the Makefile — *why*: AC12 (`make docker-helixdb` exists, no embedded target).
3. Write `docs/wiki/helixdb.md` skeleton + cheatsheet line — *why*: AC17 (docs updated); TASK-4397 completes it.
4. Run the spike, write the spike doc — *why*: AC13 (observed error class recorded).

### `docker/helixdb/Dockerfile` (CREATE)
```dockerfile
# syntax=docker/dockerfile:1.7
# Thin wrapper so `docker build` works like docker/arango; compose uses the pinned image directly.
ARG HELIXDB_IMAGE_TAG=v0.0.12
FROM ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG}

LABEL org.opencontainers.image.title="ai-parrot-helixdb" \
      org.opencontainers.image.description="Local HelixDB server for AI-Parrot development" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

ENV HELIX_DATA_DIR=/var/lib/helix
EXPOSE 8080
```

### `docker/helixdb/docker-compose.yml` (CREATE)
```yaml
services:
  helixdb:
    image: ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG:-v0.0.12}
    container_name: parrot-helixdb
    restart: unless-stopped
    user: "65532:65532"
    ports:
      - "${HELIXDB_PORT:-6969}:8080"
    environment:
      HELIX_DATA_DIR: /var/lib/helix
    volumes:
      - helixdb-data:/var/lib/helix
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://127.0.0.1:8080/readyz || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 10s

volumes:
  helixdb-data:
    name: parrot-helixdb-data
```

### `Makefile` (MODIFY)
```make
# occurrences: 1 (verified: grep -c -F 'docker-dev:' Makefile)
# BEFORE — insert above the comment block that precedes `docker-dev:` (verified: Makefile:917-920)
# Local HelixDB server (FEAT-670) — persistent volume parrot-helixdb-data; no embedded target by design.
docker-helixdb:
	@docker compose -f docker/helixdb/docker-compose.yml up -d
	@echo "✅ HelixDB starting on http://127.0.0.1:$${HELIXDB_PORT:-6969} (set HELIXDB_URL to use it)"

# occurrences: 1 (verified: grep -c -F '	@echo "    docker-whatsapp-bridge   - Build and run in Docker"' Makefile)
# AFTER — insert below that help line (verified: Makefile:1097)
	@echo ""
	@echo "  HelixDB:"
	@echo "    docker-helixdb           - Start the local HelixDB server (docker/helixdb)"

# occurrences: 1 (verified: grep -c -F 'injection-model docker-tool-worker docker-integrations docker-dev \' Makefile)
# REPLACE in .PHONY (Makefile:9): `... docker-integrations docker-dev \` → `... docker-integrations docker-dev docker-helixdb \`
```
**Why**: target shape follows the `docker-dev` precedent (spec §3 M2); the help block mirrors the WhatsApp Bridge block.

### `docs/wiki/cheatsheet.md` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c -F 'wikitoolkit build --backend arangodb # plano compartido en ArangoDB' docs/wiki/cheatsheet.md)
# AFTER — insert below that line (verified: cheatsheet.md:43)
wikitoolkit build --backend helixdb  # plano en HelixDB (make docker-helixdb; HELIXDB_URL)
```

### `docs/wiki/helixdb.md` (CREATE)
```markdown
# HelixDB backend

<one paragraph: additional peer backend (ArangoDB unchanged), server vs embedded, see FEAT-670 spec>

## Start
make docker-helixdb · `/readyz` check · `export HELIXDB_URL=http://127.0.0.1:6969`

## Environment
| Key | Default | Used by |  (HELIXDB_URL, HELIXDB_API_KEY, HELIXDB_MODE, HELIXDB_IMAGE_TAG, HELIXDB_PORT — spec §7 table)

## Modes
server (default; multi-process) · embedded (`Disk(<storage_dir>/helix, <db>)`, single process, refused while
`wiki.lock` is held — wording from the spike) · memory (tests only)

<!-- TASK-4397 adds: migration per plane, ledger rebuild, projections, embedded guard details -->
```
# FILL IN: prose for each section — bounded by spec §2 "Deployment modes" and §7 Configuration References

### `sdd/state/FEAT-670/spike-embedded-two-writers.md` (CREATE)
```markdown
# Spike — two embedded writers on one Disk source (FEAT-670, resolved Q4)
- Date / SDK versions (helix-db, helix-db-embedded) / OS + glibc
- Script (verbatim)
- Observed: process A <result>; process B exception class `<module.Class>`, HelixError flags, message
- Reader coexistence (read_only=True while A writes): <result>
- Guard message proposed for TASK-4376: "<text pointing to server mode>"
```
# FILL IN: real observations — bounded by AC13 (never invented; "NOT RUN — reason" if it could not run)

### FILL IN checklist
- [ ] `docs/wiki/helixdb.md` — section prose
- [ ] spike doc — real observed class/message (AC13)
- [ ] healthcheck probe confirmed present in the image (or adjusted and recorded)

---

## Acceptance Criteria

- [ ] AC12: compose uses `${HELIXDB_IMAGE_TAG:-v0.0.12}`, a named volume at `HELIX_DATA_DIR`, a `/readyz`
      healthcheck; `make docker-helixdb` exists; there is **no** embedded Makefile target; README has the
      backup-before-upgrade section.
- [ ] AC13 (spike half): `sdd/state/FEAT-670/spike-embedded-two-writers.md` records the observed error class.
- [ ] `docker compose -f docker/helixdb/docker-compose.yml config` validates; `make -n docker-helixdb` prints the compose command.
- [ ] AC16: nothing under `docker/arango/` changes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_client_settings.py -q`

(No pytest file is created by this task; additionally run, outside pytest:
`docker compose -f docker/helixdb/docker-compose.yml config -q` and `make -n docker-helixdb`.
If Docker is available: `make docker-helixdb && curl -fsS http://127.0.0.1:6969/readyz`.)

---

## Test Specification

No unit tests (infra + docs). The live compose check `test_compose_readyz` is written by TASK-4397
against this stack. Manual verification evidence (compose config output, `make -n`, optional readyz
response, spike transcript) goes in the Completion Note.

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`, never on `dev`.
2. Read spec §2 "Deployment modes"/"Infra", §3 Module 2, §7 Known Risks (server image v0.0.x, one-way upgrade).
3. `TASK-4373` must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-run the four `grep -c -F` anchor checks (each must print `1`).
5. Mark `in-progress`; commit only the index file.
6. Implement; run the spike in two OS processes; never invent spike output.
7. `sdd/state/` may be git-ignored in parts — `git add -f sdd/state/FEAT-670/spike-embedded-two-writers.md` if needed.
8. Commit only the listed files: `feat(helixdb-provider): TASK-4375 — docker/helixdb stack, make target, docs skeleton, spike`.
9. `scripts/sdd/close_task.sh TASK-4375 helixdb-provider verified` (or `partial` if the spike could not run), fill the Completion Note, commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
