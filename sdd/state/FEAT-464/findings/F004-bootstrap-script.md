# F004: scripts/matrix/bootstrap.sh

**Query**: read scripts/matrix/bootstrap.sh
**Source**: scripts/matrix/bootstrap.sh

## Key Facts

6-step automated bootstrap:
1. Generate Synapse config (first run only)
2. Render homeserver.yaml from template with envsubst
3. Generate parrot AppService registration (python -m parrot.integrations.matrix.registration)
4. docker compose up -d
5. Create coordinator user (register_new_matrix_user)
6. Print Element Web URL + next steps

Supports `--dry-run` and `--bridges` flags. Sources docker/matrix/.env if present.

## Implication for FEAT-464
Bootstrap script handles everything. Sample README should just say "run bootstrap.sh" not reinvent the wheel.
