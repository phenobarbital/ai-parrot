# ai-parrot-saas

Multi-tenant SaaS control plane and agentic business flows for AI-Parrot.

This distribution is the **acyclic leaf** of the workspace. It is the only
package permitted to depend on `ai-parrot` (flows/agents), `ai-parrot-server`
(HTTP layer, `JobManager`), `ai-parrot-tools` (`PulumiExecutor`) and `navrules`
at the same time. Nothing in the workspace depends on it.

## Why a distinct top-level module

The module is `parrot_saas`, **not** `parrot.saas`. Three distributions already
merge into the `parrot.*` namespace through `pkgutil.extend_path`
(`packages/ai-parrot/src/parrot/__init__.py`), and the repository's root
`conftest.py` documents the import-shadowing that causes. This package follows
the `parrot_tools` / `parrot_formdesigner` / `parrot_pipelines` convention.

## Layout

| Path | Contents |
|---|---|
| `db/` | `BaseRepository` (pooled, tenant-scoped) and `schema.py`, which owns all the DDL |
| `tenancy/` | `TenantContext`, tenant models, repository, runtime cache, resolution middleware |
| `llm/` | BYOK agent builder — per-tenant clients from stored credentials |
| `reviews/` | `ReviewSource` port plus the mock and generic-webhook adapters |
| `coupons/` | Coupon domain: models, repository, issuer, delivery |
| `rules/` | navrules integration — Postgres rule storage, ruleset builder, eval context |
| `runs/` | Flow execution records: what ran, for whom, and how it ended |
| `flows/community_manager/` | The Community Manager `AgentsFlow` (definition, nodes, factories, runner) |
| `provisioning/` | `TenantDeployer` port, shared and Pulumi deployers, Pulumi programs |
| `handlers/` | aiohttp `BaseView` handlers and the `setup_saas_api` entry point |

There is no `migrations/` directory, and adding one is a decision rather than
a chore. `db/schema.py` creates every table with idempotent DDL on start-up,
following the convention `packages/parrot-formdesigner/migrations/README.md`
states outright: this repository has no migration framework, and greenfield
installs are expected to be created by the code. Numbered `.sql` files earn
their place the first time a schema change has to reach an installation that
already exists.

## Design rules this package must keep

1. **Tenant is always explicit.** Every repository method takes `tenant_id` as
   its first positional argument, with no default. There is no ContextVar: the
   flow runs from background workers and shutdown hooks where an ambient value
   would silently read `None`, and a `None` tenant is a data leak rather than a
   crash.
2. **Flow predicates are CEL strings, never Python callables.** A single
   callable predicate makes `AgentsFlow.to_definition()` raise
   `FlowNotExportableError`, which disables checkpointing for the whole flow —
   and with `checkpoint=True` it fails *before any node runs*. The CEL
   constants live in `flows/community_manager/definition.py` and are imported
   by `flow.py` so the declarative and executable graphs cannot drift.
3. **Custom flow nodes must declare an `fsm` field.** The base `Node` does not
   have one, but the scheduler calls `node.fsm.schedule()` unconditionally for
   every node.
4. **Coupon rulesets use `Policy.FIRST_MATCH`.** It is the only navrules policy
   that returns the matching rule's `result` payload, and the only one the
   native backend supports on the sync path.
5. **`PostgresRuleStorage` stays here, not in navrules.** navrules is
   deliberately zero-dependency; adding `asyncdb` upstream would couple a pure,
   Rust-accelerated rules library to a database for every future consumer. It
   moves to a `navrules[postgres]` extra only when a second consumer appears.

## Testing

```bash
source .venv/bin/activate

# The offline half — no database, no network.
pytest packages/ai-parrot-saas/tests -q

# Everything, against a real PostgreSQL.
SAAS_TEST_DSN="postgres://postgres@127.0.0.1:5432/parrot_saas_test" \
  pytest packages/ai-parrot-saas/tests -q
```

Most of the suite runs with no external services: navrules is pure Python, and
the flow is exercised with stub agents and the in-memory review source. Tests
that need a database are marked `integration` and **skip silently** unless
`SAAS_TEST_DSN` is set — so a green run without it means most of the suite did
not execute. The Pulumi test is marked `live` and additionally needs
`SAAS_PULUMI_E2E=1`, the `pulumi` CLI on `PATH` and a Docker daemon that
answers; all three are probed, because a live test that quietly ran against
nothing would be worse than none.

Two tests are worth knowing about by name:

- `test_e2e_narrative.py` drives the whole circuit over HTTP — signup, BYOK,
  offer, rule, review, run, coupon, redemption — twice, and asserts the two
  tenants see none of each other's data.
- `test_tenant_isolation.py` is the guard rail: it walks every
  `BaseRepository` subclass in the package and fails if a method issues SQL
  without a tenant predicate and is not declared cross-tenant with a reason.
  Its predecessor covered one repository and kept passing while six more were
  added, so it also asserts *how many* it inspected.

### Writing tests that touch the flow

Do not store a real provider credential (`anthropic:api_key`,
`google:api_key`) in a test that then runs the flow. The tenant's next runtime
builds a live client from it and the drafting node makes a real outbound call.
With no provider key stored, both LLM nodes take their deterministic paths,
which is what keeps the flow runnable offline.

## Running it

One line in `Main.configure()`, after `configure_job_manager` and
`BotManager.setup` (so `app['redis']`, `app['job_manager']` and `app['abac']`
exist) and **between** `auth.setup()` and `setup_pbac()`:

```python
from parrot_saas.handlers.setup import setup_saas_api
setup_saas_api(self.app)
```

The position is not cosmetic. aiohttp runs middlewares outermost-first, and
`setup_pbac` appends the ABAC middleware last — so anything registered after it
runs *inside* a decision already taken. The tenant middleware has to be outside
ABAC for a policy to be able to read `request["tenant"]`, and inside
authentication for the session-claim strategy to have a session.

### Settings that change behaviour

| Setting | Default | Effect |
|---|---|---|
| `SAAS_PG_DSN`, `SAAS_PG_SCHEMA` | `…/parrot`, `saas` | Where every table lives |
| `SAAS_ENABLE_DEDICATED` | `false` | Wires the Pulumi deployer. Off, a `dedicated` tenant's provision request answers 503 naming the modes that *are* configured |
| `SAAS_TENANT_MAX_CONCURRENT_RUNS` | `8` | Flow runs in flight per tenant. The scheduler enforces no cap of its own, so this is the only one |
| `SAAS_TENANT_RUNTIME_MAX` / `_TTL` | `64` / `1800` | Bounds live per-tenant runtimes, each holding open LLM clients |
| `SAAS_CM_NODE_TIMEOUT` | `120.0` | Per-node wall clock. `FlowMetadata.execution_timeout` is not honoured by the scheduler, so nodes bound themselves |
| `SAAS_CM_TRIAGE_MODEL` / `_REPLY_MODEL` | `gemini-2.5-flash` / `claude-sonnet-5` | Overridable per tenant via `settings["triage_model"]` / `["reply_model"]` |

`setup_saas_api(checkpoint_runs=True, checkpoint_store="redis")` is what makes
`POST /runs/{run_id}/resume` possible: without checkpointing a run leaves
nothing to resume from, and the endpoint says so with a 404 rather than
pretending.

### The circuit, by hand

```bash
BASE=localhost:5000/api/v1/saas

curl -X POST $BASE/control/tenants \
     -d '{"tenant_id":"bar-pepe","name":"Bar Pepe"}'

curl -X PUT $BASE/secrets/anthropic:api_key \
     -H 'X-Tenant-Id: bar-pepe' -d '{"value":"sk-ant-…"}'   # 201 + fingerprint

curl -X POST $BASE/coupon-offers -H 'X-Tenant-Id: bar-pepe' -d '{
  "code":"RECOVER20","name":"20% off","discount_type":"percent",
  "discount_value":20,"valid_days":30,"max_coupons":50,"budget_period":"month"}'

curl -X POST $BASE/rules -H 'X-Tenant-Id: bar-pepe' -d '{
  "name":"recover_detractor","priority":100,
  "conditions":{"ctx.rating":{"lte":2},"ctx.reply_published":true,
                "ctx.consent_marketing":true},
  "result":{"offer_code":"RECOVER20","reason":"detractor_recovery"}}'

curl -X POST $BASE/reviews/simulate -H 'X-Tenant-Id: bar-pepe' \
     -d '{"external_id":"demo-1","rating":1,"text":"Cold food.",
          "author_email":"guest@example.com"}'          # 202 {run_id}

curl -H 'X-Tenant-Id: bar-pepe' $BASE/runs/$RUN_ID       # outcome, usage, nodes
curl -H 'X-Tenant-Id: bar-pepe' $BASE/coupons
curl -X POST $BASE/coupons/redeem -H 'X-Tenant-Id: bar-pepe' \
     -d '{"code":"RECOVER20-7KQF9M"}'                    # 200; again → 409
```

A guest created by ingest has **no marketing consent** — a review platform
never conveys it — so the first review is answered without an offer. Consent
comes from the tenant's own systems, and there is deliberately no HTTP route
that sets it.

### Provisioning

```bash
curl -X POST $BASE/control/tenants/bar-pepe/plan     # 202 {job_id}
curl -X POST $BASE/control/tenants/bar-pepe/deploy   # 202 {job_id}
curl $BASE/control/tenants/bar-pepe/deployment       # stored state + live probe
```

Long operations answer 202 and record their outcome on `saas.deployments`;
holding an HTTP request open for a stack that takes minutes would time out at
whatever proxy sits in front. A second operation while one is in flight is a
409, because two `pulumi up` runs on one stack corrupt its state file.
