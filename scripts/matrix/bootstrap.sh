#!/usr/bin/env bash
# Bootstrap the AI-Parrot Matrix dev stack (FEAT-463).
#
# Steps:
#   1. Generate the initial Synapse homeserver.yaml (if missing).
#   2. Render homeserver.yaml from the template with envsubst.
#   3. Generate the parrot AppService registration
#      (python -m parrot.integrations.matrix.registration).
#   4. Start the stack (docker compose up -d).
#   5. Create the coordinator user via register_new_matrix_user.
#   6. Print the Element Web URL, Element X server address, and next steps.
#
# Usage:
#   ./scripts/matrix/bootstrap.sh [--dry-run] [--bridges]
#
# --dry-run  Print every step without executing anything.
# --bridges  Also start the `bridges` compose profile (Slack/Signal/Discord).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.matrix.yml"
ENV_FILE="${ROOT_DIR}/docker/matrix/.env"
SYNAPSE_DIR="${ROOT_DIR}/docker/matrix/synapse"
TEMPLATE="${SYNAPSE_DIR}/homeserver.yaml.tmpl"
RENDERED="${SYNAPSE_DIR}/homeserver.yaml"
APPSERVICES_DIR="${SYNAPSE_DIR}/appservices"

DRY_RUN=false
WITH_BRIDGES=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --bridges) WITH_BRIDGES=true ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

COMPOSE_PROFILE_ARGS=()
if [ "$WITH_BRIDGES" = true ]; then
    COMPOSE_PROFILE_ARGS=(--profile bridges)
fi

run() {
    # Print the command; execute it unless --dry-run was passed.
    echo "+ $*"
    if [ "$DRY_RUN" = false ]; then
        "$@"
    fi
}

echo "AI-Parrot Matrix dev stack bootstrap (FEAT-463)"
echo "================================================"
echo "Dev-only stack: no TLS, no Synapse workers."
echo

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "NOTE: ${ENV_FILE} not found — copy docker/matrix/.env.example and fill it in." >&2
    echo "      Falling back to defaults from .env.example for this dry-run." >&2
fi

# --- Step 1: generate initial Synapse config (first run only) ----------
echo
echo "[1/6] Generate Synapse config (first run only)"
if [ -f "${SYNAPSE_DIR}/homeserver.yaml" ]; then
    echo "      Already present — skipping."
else
    run docker compose -f "$COMPOSE_FILE" run --rm synapse generate
fi

# --- Step 2: render homeserver.yaml from the template -------------------
echo
echo "[2/6] Render homeserver.yaml from template (envsubst)"
run bash -c "envsubst < '$TEMPLATE' > '$RENDERED'"

# --- Step 3: generate the parrot AppService registration ----------------
echo
echo "[3/6] Generate parrot AppService registration"
run mkdir -p "$APPSERVICES_DIR"
run bash -c "python -m parrot.integrations.matrix.registration > '${APPSERVICES_DIR}/parrot.yaml'"

# --- Step 4: start the stack ---------------------------------------------
echo
echo "[4/6] Start the stack (docker compose up -d)"
run docker compose -f "$COMPOSE_FILE" "${COMPOSE_PROFILE_ARGS[@]}" up -d

# --- Step 5: create the coordinator user ---------------------------------
echo
echo "[5/6] Create the coordinator user (register_new_matrix_user)"
run docker compose -f "$COMPOSE_FILE" exec synapse \
    register_new_matrix_user -u "${MATRIX_COORDINATOR_USER:-parrot-bot}" \
    -p "${MATRIX_COORDINATOR_PASSWORD:-parrot-bot-password}" -a \
    -c /data/homeserver.yaml http://localhost:8008

# --- Step 6: print next steps --------------------------------------------
echo
echo "[6/6] Next steps"
cat <<EOF
      Element Web:          http://localhost:8080
      Element X (mobile):   server address 'parrot.local' (via /.well-known on :8448)
      Homeserver (Synapse): http://localhost:8008
      Coordinator login:    ${MATRIX_COORDINATOR_USER:-parrot-bot} / (see docker/matrix/.env)

      Point your MatrixCrewConfig / matrix_crew.yaml at:
        homeserver_url: http://localhost:8008
        server_name: ${MATRIX_SERVER_NAME:-parrot.local}
        appservice_port: 8449

      Optional bridges (Slack/Signal/Discord) — see docs/integrations/matrix/BRIDGES.md:
        docker compose -f docker-compose.matrix.yml --profile bridges up -d
EOF
