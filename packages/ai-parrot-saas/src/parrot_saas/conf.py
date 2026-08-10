"""Configuration for the AI-Parrot SaaS plane.

Every value is read once at import time through :mod:`navconfig`, mirroring
``parrot.conf``. Reads are ``config.get(name, fallback=...)`` so a value can
come from the environment, an ``.env`` file, or navconfig's own backends.

Nothing here raises on a missing value: components that genuinely cannot run
without one (notably :class:`~parrot_saas.secrets` master key handling) fail
closed at construction time, where the error can name the component.
"""
from pathlib import Path

from navconfig import BASE_DIR, config

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
#: DSN for the SaaS Postgres schema (tenants, reviews, coupons, rules,
#: deployments). Falls back to the crew result-storage DSN so a single-database
#: development box needs no extra configuration.
SAAS_PG_DSN: str = config.get(
    "SAAS_PG_DSN",
    fallback=config.get(
        "CREW_RESULT_STORAGE_PG_DSN",
        fallback="postgres://postgres:postgres@localhost:5432/parrot",
    ),
)

#: Postgres schema holding every SaaS table. Single schema by design — tenant
#: isolation is a ``tenant_id`` column plus repository-level enforcement, not
#: a schema per tenant (self-service signup makes DDL-on-signup untenable).
SAAS_PG_SCHEMA: str = config.get("SAAS_PG_SCHEMA", fallback="saas")

#: Redis URL for ephemeral flow state (checkpoints, jobs, rule invalidation).
SAAS_REDIS_URL: str = config.get(
    "SAAS_REDIS_URL",
    fallback=config.get("REDIS_URL", fallback="redis://localhost:6379/5"),
)

#: Collection (table) used for flow execution audit rows written through
#: ``PersistenceMixin._save_result``.
SAAS_EXECUTIONS_COLLECTION: str = config.get(
    "SAAS_EXECUTIONS_COLLECTION", fallback="saas_cm_executions"
)

# ---------------------------------------------------------------------------
# Tenant runtime cache
# ---------------------------------------------------------------------------
#: Maximum number of live per-tenant runtimes (each holds configured agents
#: with open HTTP clients, so this bounds file descriptors and memory).
SAAS_TENANT_RUNTIME_MAX: int = int(
    config.get("SAAS_TENANT_RUNTIME_MAX", fallback=64)
)

#: Idle seconds before a tenant runtime becomes evictable.
SAAS_TENANT_RUNTIME_TTL: int = int(
    config.get("SAAS_TENANT_RUNTIME_TTL", fallback=1800)
)

#: Concurrent flow runs allowed per tenant. The AgentsFlow scheduler has no
#: concurrency cap of its own, so ingestion throttles here instead.
SAAS_TENANT_MAX_CONCURRENT_RUNS: int = int(
    config.get("SAAS_TENANT_MAX_CONCURRENT_RUNS", fallback=8)
)

# ---------------------------------------------------------------------------
# Secrets (envelope encryption)
# ---------------------------------------------------------------------------
# Key *material* is deliberately NOT configured here. The encrypted secret
# store reuses the key management already established in this repository —
# ``VAULT_MASTER_KEY_v{N}`` (base64, 32 bytes) plus ``VAULT_ACTIVE_KEY_ID``,
# read through ``navigator_session.vault.config`` — so a deployment has one
# set of master keys to escrow, back up and rotate rather than two.
#
# What the SaaS store adds on top is the envelope: a per-tenant data key
# wrapped by that master key, and AAD binding so a ciphertext row cannot be
# relocated to another tenant or another key name and still decrypt. The
# upstream ``encrypt_for_db`` helper passes ``aad=None``, which is why the
# envelope lives in ``parrot.security.secrets.postgres`` rather than reusing
# it wholesale.

#: Table holding wrapped per-tenant data-encryption keys.
SAAS_SECRETS_DEK_TABLE: str = config.get(
    "SAAS_SECRETS_DEK_TABLE", fallback="tenant_deks"
)
#: Table holding encrypted secret values.
SAAS_SECRETS_TABLE: str = config.get(
    "SAAS_SECRETS_TABLE", fallback="tenant_secrets"
)
#: Seconds an unwrapped data key may be cached in process. Bounds the window
#: in which key material is resident without forcing a master-key unwrap on
#: every read.
SAAS_SECRETS_DEK_CACHE_TTL: int = int(
    config.get("SAAS_SECRETS_DEK_CACHE_TTL", fallback=300)
)

# ---------------------------------------------------------------------------
# Community Manager flow
# ---------------------------------------------------------------------------
#: Default bound on the guardrail -> reply_draft repair loop. The engine does
#: not bound cycles; the stop rule lives in ``GuardrailNode._revise_allowed``.
SAAS_CM_MAX_REVISE_ROUNDS: int = int(
    config.get("SAAS_CM_MAX_REVISE_ROUNDS", fallback=2)
)

#: Per-node wall-clock budget. The scheduler honours neither
#: ``execution_timeout`` nor ``on_timeout`` edges, so nodes apply this
#: themselves via ``asyncio.wait_for``.
SAAS_CM_NODE_TIMEOUT: float = float(
    config.get("SAAS_CM_NODE_TIMEOUT", fallback=120.0)
)

#: Default models used when a tenant does not override them in its settings
#: (``settings["triage_model"]`` / ``settings["reply_model"]``).
SAAS_CM_TRIAGE_MODEL: str = config.get(
    "SAAS_CM_TRIAGE_MODEL", fallback="gemini-2.5-flash"
)
#: Sonnet rather than Opus because this is the high-volume path — one call per
#: review — and a tenant that wants more can raise it in its own settings.
SAAS_CM_REPLY_MODEL: str = config.get(
    "SAAS_CM_REPLY_MODEL", fallback="claude-sonnet-5"
)

# ---------------------------------------------------------------------------
# Provisioning (Pulumi)
# ---------------------------------------------------------------------------
#: Path to the ``pulumi`` CLI on the host. The toolkit's Docker mode cannot
#: drive the Docker provider (it never mounts the Docker socket), so the
#: deployer always runs the CLI directly.
SAAS_PULUMI_CLI: str = config.get("SAAS_PULUMI_CLI", fallback="pulumi")

#: Directory backing the local Pulumi state file. ``PulumiConfig.state_backend``
#: is a dead field, so the deployer exports ``PULUMI_BACKEND_URL`` instead.
SAAS_PULUMI_STATE_DIR: Path = Path(
    config.get(
        "SAAS_PULUMI_STATE_DIR",
        fallback=str(Path(BASE_DIR).joinpath(".pulumi-state")),
    )
)

#: Passphrase for the local Pulumi secrets provider.
SAAS_PULUMI_PASSPHRASE: str = config.get(
    "SAAS_PULUMI_PASSPHRASE", fallback="parrot-saas-local"
)

#: Container image deployed for a dedicated tenant worker.
SAAS_TENANT_IMAGE: str = config.get(
    "SAAS_TENANT_IMAGE", fallback="ai-parrot:latest"
)

#: Host port range allocated to dedicated tenant stacks.
SAAS_TENANT_PORT_MIN: int = int(config.get("SAAS_TENANT_PORT_MIN", fallback=18000))
SAAS_TENANT_PORT_MAX: int = int(config.get("SAAS_TENANT_PORT_MAX", fallback=18999))

#: Seconds allowed for a single Pulumi operation.
SAAS_PULUMI_TIMEOUT: int = int(config.get("SAAS_PULUMI_TIMEOUT", fallback=900))

__all__ = (
    "SAAS_CM_MAX_REVISE_ROUNDS",
    "SAAS_CM_NODE_TIMEOUT",
    "SAAS_CM_REPLY_MODEL",
    "SAAS_CM_TRIAGE_MODEL",
    "SAAS_EXECUTIONS_COLLECTION",
    "SAAS_PG_DSN",
    "SAAS_PG_SCHEMA",
    "SAAS_PULUMI_CLI",
    "SAAS_PULUMI_PASSPHRASE",
    "SAAS_PULUMI_STATE_DIR",
    "SAAS_PULUMI_TIMEOUT",
    "SAAS_REDIS_URL",
    "SAAS_SECRETS_DEK_CACHE_TTL",
    "SAAS_SECRETS_DEK_TABLE",
    "SAAS_SECRETS_TABLE",
    "SAAS_TENANT_IMAGE",
    "SAAS_TENANT_MAX_CONCURRENT_RUNS",
    "SAAS_TENANT_PORT_MAX",
    "SAAS_TENANT_PORT_MIN",
    "SAAS_TENANT_RUNTIME_MAX",
    "SAAS_TENANT_RUNTIME_TTL",
)
