"""The dedicated-stack deployer, driven against a fake executor.

No Pulumi CLI and no Docker daemon are involved. What is being tested is the
part that is ours: the three workarounds for gaps in ``PulumiExecutor``, and
the rule that a stack's connection string never becomes a plain output.

The live path — a real ``pulumi up`` against a real daemon — is
``test_pulumi_live.py``, which skips unless both are present.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parrot_saas.provisioning.models import DeploymentStatus
from parrot_saas.provisioning.pulumi_deployer import (
    DEFAULT_PROGRAM_DIR,
    DSN_SECRET_TEMPLATE,
    PulumiDeployer,
    default_port,
    stack_name,
)
from parrot_saas.tenancy.context import TenantContext

DSN = "postgres://parrot:hunter2@parrot-bar-pepe-postgres:5432/parrot"


@pytest.fixture
def tenant() -> TenantContext:
    """The tenant being provisioned."""
    return TenantContext(
        tenant_id="bar-pepe", name="Bar Pepe", mode="dedicated"
    )


class _Result:
    """Stand-in for ``PulumiOperationResult``."""

    def __init__(self, success=True, outputs=None, summary=None, error=None):
        self.success = success
        self.outputs = outputs or {}
        self.summary = summary or {}
        self.error = error


class _Executor:
    """Records every call and returns whatever the test wants."""

    def __init__(self, **results) -> None:
        self.calls: list[tuple] = []
        self.results = results

    def _answer(self, name):
        return self.results.get(name, _Result())

    async def preview(self, project_path, stack=None, **kw):
        self.calls.append(("preview", project_path, stack, kw))
        return self._answer("preview")

    async def up(self, project_path, stack=None, **kw):
        self.calls.append(("up", project_path, stack, kw))
        return self._answer("up")

    async def destroy(self, project_path, stack=None, **kw):
        self.calls.append(("destroy", project_path, stack, kw))
        return self._answer("destroy")

    async def stack_output(self, project_path, stack=None, **kw):
        self.calls.append(("stack_output", project_path, stack, kw))
        return self._answer("stack_output")


class _Store:
    """Recording stand-in for the secret store."""

    def __init__(self, *, fail=None) -> None:
        self.put_calls: list = []
        self.deleted: list = []
        self.fail = fail

    async def put(self, tenant_id, key, value):
        if self.fail is not None:
            raise self.fail
        self.put_calls.append((tenant_id, key, value))
        return object()

    async def delete(self, tenant_id, key):
        self.deleted.append((tenant_id, key))
        return True


@pytest.fixture
def program(tmp_path: Path) -> Path:
    """A stand-in program directory, so nothing writes into the real one."""
    (tmp_path / "Pulumi.yaml").write_text("name: parrot-saas-tenant\n")
    return tmp_path


def _deployer(program: Path, executor=None, store=None, **kw) -> PulumiDeployer:
    return PulumiDeployer(
        program_dir=program,
        executor=executor or _Executor(),
        secret_store=store,
        **kw,
    )


@pytest.fixture(autouse=True)
def _pulumi_on_path(monkeypatch):
    """Pretend the CLI exists; its absence has its own test."""
    monkeypatch.setattr(
        "parrot_saas.provisioning.pulumi_deployer.shutil.which",
        lambda name: f"/usr/local/bin/{name}",
    )


# ---------------------------------------------------------------------------
# Gap 1: config_values is discarded, so the stack config is written by hand
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stack_config_is_written_because_config_values_is_dropped(
    tenant, program
):
    """``preview()``/``up()`` take ``config_values`` and never forward it.

    Passing the tenant through that argument would build the stack with no
    tenant id at all — or with the previous one, which is worse. So the config
    goes into the file the CLI actually reads.
    """
    executor = _Executor()
    await _deployer(program, executor).apply(tenant)

    written = (program / f"Pulumi.{stack_name('bar-pepe')}.yaml").read_text()
    assert "parrot-saas-tenant:tenantId: bar-pepe" in written
    assert "parrot-saas-tenant:hostPort:" in written
    # And nothing was smuggled through the argument that ignores it.
    _, _, _, kwargs = executor.calls[0]
    assert "config_values" not in kwargs


@pytest.mark.asyncio
async def test_a_tenants_settings_override_the_defaults(tenant, program):
    """A tenant that pinned a port or an image gets it on the next apply."""
    pinned = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        mode="dedicated",
        settings={"host_port": 18999, "worker_image": "ai-parrot:2026.8"},
    )

    await _deployer(program).apply(pinned)

    written = (program / f"Pulumi.{stack_name('bar-pepe')}.yaml").read_text()
    assert "hostPort: 18999" in written
    assert "image: ai-parrot:2026.8" in written


@pytest.mark.asyncio
async def test_the_config_is_rewritten_on_every_operation(tenant, program):
    """Otherwise a changed setting would be silently ignored forever."""
    deployer = _deployer(program)
    await deployer.apply(tenant)

    changed = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        mode="dedicated",
        settings={"host_port": 18500},
    )
    await deployer.plan(changed)

    written = (program / f"Pulumi.{stack_name('bar-pepe')}.yaml").read_text()
    assert "hostPort: 18500" in written


def test_a_tenants_port_is_stable_across_provisions(tenant):
    """A port that moved on every apply would break every URL pointing at it."""
    assert default_port(tenant) == default_port(tenant)

    from parrot_saas import conf

    assert conf.SAAS_TENANT_PORT_MIN <= default_port(tenant) <= conf.SAAS_TENANT_PORT_MAX


# ---------------------------------------------------------------------------
# Gaps 2 and 3: the backend URL and the Docker socket
# ---------------------------------------------------------------------------


def test_the_executor_never_runs_pulumi_in_docker(tmp_path, monkeypatch):
    """The toolkit's Docker mode cannot reach the daemon it must drive.

    ``_build_docker_command`` mounts the project directory and nothing else —
    never ``/var/run/docker.sock`` — so Pulumi in a container has no Docker to
    talk to. This is the one setting that cannot drift.
    """
    from parrot_saas.provisioning.pulumi_deployer import build_executor

    executor = build_executor(
        state_dir=tmp_path / "state", passphrase="pw", timeout=30
    )

    assert executor.config.use_docker is False


def test_the_state_backend_is_set_through_the_environment(tmp_path, monkeypatch):
    """``PulumiConfig.state_backend`` is a dead field — nothing reads it.

    Left alone, a default install would try to reach Pulumi Cloud. The
    executor's environment starts from ``os.environ.copy()``, which is why
    exporting the variable works.
    """
    from parrot_saas.provisioning.pulumi_deployer import build_executor

    monkeypatch.delenv("PULUMI_BACKEND_URL", raising=False)
    state = tmp_path / "state"

    executor = build_executor(state_dir=state, passphrase="pw", timeout=30)

    assert executor._build_process_env()["PULUMI_BACKEND_URL"] == f"file://{state}"
    assert state.is_dir()


# ---------------------------------------------------------------------------
# The connection string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dsn_goes_to_the_secret_store_not_the_outputs(tenant, program):
    """``outputs`` is a jsonb column the control plane reads freely.

    A DSN there is a plaintext password in a table, and in every backup of it.
    """
    executor = _Executor(
        stack_output=_Result(
            outputs={"dsn": DSN, "host_port": 18351, "worker_container": "w"}
        )
    )
    store = _Store()

    result = await _deployer(program, executor, store).apply(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.READY.value
    assert "dsn" not in result.outputs
    assert DSN not in str(result.outputs)
    ref = DSN_SECRET_TEMPLATE.format(stack=stack_name("bar-pepe"))
    assert store.put_calls == [("bar-pepe", ref, DSN)]
    assert result.secret_refs == [ref]
    assert result.outputs["secret_refs"] == [ref]
    # The rest is ordinary infrastructure detail and stays public.
    assert result.outputs["host_port"] == 18351


@pytest.mark.asyncio
async def test_status_never_reports_the_dsn_either(tenant, program):
    """The status route is polled, so a leak here would be a repeated one."""
    executor = _Executor(stack_output=_Result(outputs={"dsn": DSN, "host_port": 1}))

    result = await _deployer(program, executor).status(tenant)

    assert DSN not in str(result.to_json())


@pytest.mark.asyncio
async def test_an_unstorable_dsn_is_not_logged(tenant, program, caplog):
    """The failure path is where a value most often escapes into a log."""
    executor = _Executor(stack_output=_Result(outputs={"dsn": DSN}))
    store = _Store(fail=RuntimeError("no vault key"))

    with caplog.at_level(logging.DEBUG):
        result = await _deployer(program, executor, store).apply(tenant)

    assert DSN not in caplog.text
    assert result.secret_refs == []
    # And the apply still succeeded: the containers are up either way.
    assert result.success is True


@pytest.mark.asyncio
async def test_no_secret_store_says_where_to_find_the_dsn(tenant, program, caplog):
    """Losing it is recoverable; writing it to a plain column is not."""
    executor = _Executor(stack_output=_Result(outputs={"dsn": DSN}))

    with caplog.at_level(logging.WARNING):
        result = await _deployer(program, executor).apply(tenant)

    assert "pulumi stack output" in caplog.text
    assert DSN not in caplog.text
    assert "dsn" not in result.outputs


@pytest.mark.asyncio
async def test_destroy_forgets_the_stored_dsn(tenant, program):
    """A credential for a database that no longer exists invites a mistake."""
    store = _Store()

    result = await _deployer(program, _Executor(), store).destroy(tenant)

    assert result.status == DeploymentStatus.DESTROYED.value
    assert store.deleted == [
        ("bar-pepe", DSN_SECRET_TEMPLATE.format(stack=stack_name("bar-pepe")))
    ]


@pytest.mark.asyncio
async def test_a_failed_destroy_keeps_the_dsn(tenant, program):
    """The database may still be there; forgetting its password strands it."""
    store = _Store()
    executor = _Executor(destroy=_Result(success=False, error="state locked"))

    result = await _deployer(program, executor, store).destroy(tenant)

    assert result.success is False
    assert store.deleted == []


# ---------------------------------------------------------------------------
# Statuses and preconditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_plan_never_reports_ready(tenant, program):
    """A preview builds nothing; saying 'ready' would be a lie."""
    result = await _deployer(program).plan(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.PENDING.value


@pytest.mark.asyncio
async def test_a_failed_up_is_reported_with_pulumis_own_message(tenant, program):
    """"Provisioning failed" with no reason costs an operator an afternoon."""
    executor = _Executor(
        up=_Result(success=False, error="port 18351 is already allocated")
    )

    result = await _deployer(program, executor).apply(tenant)

    assert result.success is False
    assert result.status == DeploymentStatus.FAILED.value
    assert "already allocated" in result.detail


@pytest.mark.asyncio
async def test_a_stack_that_exists_but_was_never_applied_is_pending(
    tenant, program
):
    """``stack output`` on a fresh stack succeeds and returns nothing."""
    result = await _deployer(program, _Executor(stack_output=_Result())).status(
        tenant
    )

    assert result.success is True
    assert result.status == DeploymentStatus.PENDING.value


@pytest.mark.asyncio
async def test_a_missing_cli_is_a_result_not_an_exception(
    tenant, program, monkeypatch
):
    """The API must boot without Pulumi installed and say so when asked."""
    monkeypatch.setattr(
        "parrot_saas.provisioning.pulumi_deployer.shutil.which", lambda name: None
    )

    result = await _deployer(program).apply(tenant)

    assert result.success is False
    assert result.status == DeploymentStatus.FAILED.value
    assert "not on PATH" in result.detail


@pytest.mark.asyncio
async def test_a_missing_program_directory_names_itself(tenant, tmp_path):
    """A packaging mistake should be readable from the response."""
    deployer = PulumiDeployer(
        program_dir=tmp_path / "nowhere", executor=_Executor()
    )

    result = await deployer.apply(tenant)

    assert result.success is False
    assert "missing" in result.detail


@pytest.mark.asyncio
async def test_outputs_are_read_back_because_up_does_not_carry_them(
    tenant, program
):
    """``up --json`` does not always include the stack's outputs."""
    executor = _Executor(stack_output=_Result(outputs={"host_port": 18351}))

    result = await _deployer(program, executor).apply(tenant)

    assert ("stack_output", str(program), stack_name("bar-pepe"), {}) in [
        (name, path, stack, kw) for name, path, stack, kw in executor.calls
    ]
    assert result.outputs["host_port"] == 18351


@pytest.mark.asyncio
async def test_unreadable_outputs_do_not_fail_a_successful_apply(
    tenant, program
):
    """The containers are up whether or not their outputs can be read."""

    class _Flaky(_Executor):
        async def stack_output(self, project_path, stack=None, **kw):
            raise RuntimeError("state file locked")

    result = await _deployer(program, _Flaky()).apply(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.READY.value


# ---------------------------------------------------------------------------
# The shipped program
# ---------------------------------------------------------------------------


def test_the_shipped_program_exists_and_declares_the_outputs_contract():
    """A sibling cloud program must export the same names.

    That contract is the whole of the ``program_dir`` seam — if these drift,
    swapping providers stops being a directory change.
    """
    main = (DEFAULT_PROGRAM_DIR / "__main__.py").read_text()

    assert (DEFAULT_PROGRAM_DIR / "Pulumi.yaml").is_file()
    assert (DEFAULT_PROGRAM_DIR / "requirements.txt").is_file()
    for name in (
        "tenant_id",
        "network",
        "host_port",
        "worker_container",
        "postgres_container",
        "redis_container",
        "redis_url",
        "dsn",
    ):
        assert f'pulumi.export("{name}"' in main


def test_the_programs_dsn_is_exported_as_a_secret():
    """Otherwise it sits in plaintext in the state file."""
    main = (DEFAULT_PROGRAM_DIR / "__main__.py").read_text()

    assert 'pulumi.export("dsn", pulumi.Output.secret(' in main


def test_the_database_publishes_no_host_port():
    """A published database port is one firewall mistake from being public.

    Only the worker publishes; Postgres and Redis are reachable on the
    tenant's own network and nowhere else.
    """
    main = (DEFAULT_PROGRAM_DIR / "__main__.py").read_text()
    postgres = main.split("postgres = docker.Container")[1].split("redis =")[0]
    redis = main.split("redis = docker.Container")[1].split("# Container-name")[0]

    assert "ContainerPortArgs" not in postgres
    assert "ContainerPortArgs" not in redis
    assert "ContainerPortArgs" in main.split("worker = docker.Container")[1]


def test_the_pulumi_sdk_is_not_a_workspace_dependency():
    """It runs under Pulumi's interpreter, not ours.

    An API deployment that never provisions anything should not resolve and
    install the Pulumi SDK.
    """
    requirements = (DEFAULT_PROGRAM_DIR / "requirements.txt").read_text()
    project = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text()

    assert "pulumi" in requirements
    assert "pulumi>=" not in project
    assert "pulumi-docker" not in project
