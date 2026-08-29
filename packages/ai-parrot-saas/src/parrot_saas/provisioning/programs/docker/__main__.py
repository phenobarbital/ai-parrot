"""A dedicated stack for one AI-Parrot SaaS tenant, on a local Docker daemon.

This is a Pulumi program, not part of the application. It runs under Pulumi's
interpreter in its own virtualenv, so it imports nothing from ``parrot_saas``
and nothing here is importable by the API.

**What it builds and why.** A network, a Postgres with a persistent volume, a
Redis, and a worker container. The Postgres is the whole point of the dedicated
mode: on the shared plane a tenant's isolation is a ``tenant_id`` column and
the repository discipline around it, which is sound but is a property of our
code. A customer paying for a dedicated stack is buying a database no other
tenant's query can reach even in principle — an isolation boundary at the
deployment, not in a WHERE clause.

**Ports.** Only the worker publishes one. Postgres and Redis are reachable on
the tenant's own network under their container names and nowhere else: a
published database port on the host is one firewall mistake away from being a
public database, and nothing outside this stack needs to reach them.

**The DSN never becomes a plain stack output.** It is marked secret, so it is
encrypted in the state file, and the deployer moves it into the tenant secret
store rather than into ``saas.deployments.outputs``.

The AWS and GCP variants are sibling directories selected by ``program_dir``;
the resource shapes differ, the outputs contract below does not.
"""
import pulumi
import pulumi_docker as docker
import pulumi_random as random

config = pulumi.Config()

tenant_id = config.require("tenantId")
image = config.get("image") or "ai-parrot:latest"
host_port = config.get_int("hostPort") or 18000
postgres_image = config.get("postgresImage") or "postgres:16-alpine"
redis_image = config.get("redisImage") or "redis:7-alpine"

#: Every resource is named from the tenant, so two stacks on one daemon cannot
#: collide and `docker ps` reads as a list of tenants.
prefix = f"parrot-{tenant_id}"

# A password is generated here rather than passed in when the caller supplies
# none, so a stack can be stood up without the deployer having to invent one —
# and `random` keeps it stable across updates instead of rotating the database
# password on every `pulumi up`.
db_password = config.get_secret("dbPassword") or random.RandomPassword(
    f"{prefix}-db-password",
    length=32,
    special=False,
).result

network = docker.Network(f"{prefix}-net", name=f"{prefix}-net")

db_volume = docker.Volume(f"{prefix}-pgdata", name=f"{prefix}-pgdata")

postgres_img = docker.RemoteImage(
    f"{prefix}-postgres-image", name=postgres_image, keep_locally=True
)
redis_img = docker.RemoteImage(
    f"{prefix}-redis-image", name=redis_image, keep_locally=True
)

postgres = docker.Container(
    f"{prefix}-postgres",
    name=f"{prefix}-postgres",
    image=postgres_img.image_id,
    restart="unless-stopped",
    envs=[
        "POSTGRES_USER=parrot",
        pulumi.Output.concat("POSTGRES_PASSWORD=", db_password),
        "POSTGRES_DB=parrot",
    ],
    volumes=[
        docker.ContainerVolumeArgs(
            volume_name=db_volume.name, container_path="/var/lib/postgresql/data"
        )
    ],
    networks_advanced=[
        docker.ContainerNetworksAdvancedArgs(name=network.name, aliases=["postgres"])
    ],
    # Without this the worker starts against a database that is still
    # initialising and dies on its first query; Docker restarts it, and the
    # stack comes up looking flaky rather than ordered.
    healthcheck=docker.ContainerHealthcheckArgs(
        tests=["CMD-SHELL", "pg_isready -U parrot"],
        interval="5s",
        timeout="3s",
        retries=12,
    ),
)

redis = docker.Container(
    f"{prefix}-redis",
    name=f"{prefix}-redis",
    image=redis_img.image_id,
    restart="unless-stopped",
    networks_advanced=[
        docker.ContainerNetworksAdvancedArgs(name=network.name, aliases=["redis"])
    ],
    healthcheck=docker.ContainerHealthcheckArgs(
        tests=["CMD", "redis-cli", "ping"],
        interval="5s",
        timeout="3s",
        retries=12,
    ),
)

# Container-name hosts, not localhost: these resolve on the tenant's own
# network and are meaningless outside it, which is exactly the property that
# keeps the database unreachable from anywhere else.
dsn = pulumi.Output.concat(
    "postgres://parrot:", db_password, f"@{prefix}-postgres:5432/parrot"
)
redis_url = f"redis://{prefix}-redis:6379/0"

worker = docker.Container(
    f"{prefix}-worker",
    name=f"{prefix}-worker",
    image=image,
    restart="unless-stopped",
    envs=[
        f"PARROT_SAAS_TENANT_ID={tenant_id}",
        pulumi.Output.concat("SAAS_PG_DSN=", dsn),
        f"SAAS_REDIS_URL={redis_url}",
        "SAAS_PG_SCHEMA=saas",
    ],
    ports=[docker.ContainerPortArgs(internal=5000, external=host_port)],
    networks_advanced=[
        docker.ContainerNetworksAdvancedArgs(name=network.name, aliases=["worker"])
    ],
    opts=pulumi.ResourceOptions(depends_on=[postgres, redis]),
)

# The outputs contract. A sibling cloud program must produce the same names:
# the deployer reads these and nothing else, so keeping them stable is what
# makes `program_dir` the only thing that changes between providers.
pulumi.export("tenant_id", tenant_id)
pulumi.export("network", network.name)
pulumi.export("host_port", host_port)
pulumi.export("worker_container", worker.name)
pulumi.export("postgres_container", postgres.name)
pulumi.export("redis_container", redis.name)
pulumi.export("redis_url", redis_url)
# Secret, so Pulumi encrypts it in the state file. The deployer moves it to the
# tenant secret store and records only a reference in the control plane.
pulumi.export("dsn", pulumi.Output.secret(dsn))
