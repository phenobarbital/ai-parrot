"""String templates for AutonomousOrchestrator deployment artifacts."""

GUNICORN_CONFIG_TEMPLATE = '''\
"""Gunicorn configuration for {agent_name}.

Usage:
    gunicorn --config {config_filename} "{module_path}:create_app()"

Session Affinity Notes:
    Each gunicorn worker runs its own asyncio event loop via
    ``aiohttp.GunicornWebWorker``.  Agent state and user sessions are
    distributed across workers.  To keep things consistent:

    1. Store session data in **Redis** (the orchestrator already connects
       to Redis for jobs, events, and hooks).
    2. Do NOT rely on in-process dicts for cross-request state.
    3. The ``_agent_cache`` inside AutonomousOrchestrator is per-worker,
       which is fine — each worker lazily creates its own agent instances.
"""
import multiprocessing

# ---------------------------------------------------------------------------
# Server socket
# ---------------------------------------------------------------------------
bind = "{bind}"

# ---------------------------------------------------------------------------
# Worker processes
# ---------------------------------------------------------------------------
# aiohttp.GunicornWebWorker runs each worker in its own asyncio loop.
worker_class = "aiohttp.GunicornWebWorker"
workers = {workers}

# Graceful timeout (seconds) for in-flight requests on reload/stop.
graceful_timeout = 120

# Max seconds a worker can be silent before being killed & restarted.
timeout = 300

# Restart workers after this many requests (prevents memory leaks).
max_requests = 2000
max_requests_jitter = 200

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
accesslog = "-"
errorlog = "-"
loglevel = "info"

# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting {agent_name} orchestrator …")


def post_fork(server, worker):
    """Called after a worker has been forked."""
    server.log.info(
        "Worker spawned (pid: %s) — each worker has its own event loop "
        "and agent instances.",
        worker.pid,
    )
'''

SUPERVISORD_CONFIG_TEMPLATE = '''\
; ==========================================================================
; Supervisor program: {agent_name}
; ==========================================================================
; Install:
;   sudo cp {config_filename} /etc/supervisor/conf.d/
;   sudo supervisorctl reread && sudo supervisorctl update
;
; Manage:
;   sudo supervisorctl start {agent_name}
;   sudo supervisorctl stop {agent_name}
;   sudo supervisorctl restart {agent_name}
;   sudo supervisorctl status {agent_name}
; ==========================================================================

[program:{agent_name}]
command={venv_path}/bin/gunicorn --config {gunicorn_config_path} "{module_path}:create_app()"
directory={working_dir}
user={user}
numprocs=1
autostart=true
autorestart=true
startsecs=10
startretries=3
stopwaitsecs=120
stopasgroup=true
killasgroup=true

; Environment — adjust as needed for your deployment.
environment=
    PATH="{venv_path}/bin:%(ENV_PATH)s",
    VIRTUAL_ENV="{venv_path}",
    PYTHONUNBUFFERED="1"

; Logging
stdout_logfile=/var/log/{agent_name}/{agent_name}.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile=/var/log/{agent_name}/{agent_name}_err.log
stderr_logfile_maxbytes=50MB
stderr_logfile_backups=10
'''

SYSTEMD_SERVICE_TEMPLATE = '''\
# ==========================================================================
# systemd unit: {agent_name}
# ==========================================================================
# Install:
#   sudo cp {service_filename} /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable {agent_name}
#   sudo systemctl start {agent_name}
#
# Manage:
#   sudo systemctl status {agent_name}
#   sudo journalctl -u {agent_name} -f
# ==========================================================================

[Unit]
Description=AI-Parrot AutonomousOrchestrator — {agent_name}
After=network.target redis.service
Wants=redis.service

[Service]
Type=notify
NotifyAccess=all
User={user}
Group={user}
WorkingDirectory={working_dir}
Environment="PATH={venv_path}/bin:/usr/local/bin:/usr/bin:/bin"
Environment="VIRTUAL_ENV={venv_path}"
Environment="PYTHONUNBUFFERED=1"

ExecStart={venv_path}/bin/gunicorn \\
    --config {gunicorn_config_path} \\
    "{module_path}:create_app()"

ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
'''

SAMPLE_AGENT_TEMPLATE = '''\
"""Sample AutonomousOrchestrator agent.

This script defines a minimal autonomous agent that can be served by
gunicorn behind supervisord / systemd.

Usage (development):
    python {filename}

Usage (production):
    gunicorn --config {filename_stem}_gunicorn.py "{filename_stem}:create_app()"

Generate deployment configs automatically:
    parrot autonomous install --agent {filename}
"""
from aiohttp import web

from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.registry import AgentRegistry
from parrot.bots import Agent


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

def build_agents() -> AgentRegistry:
    """Create and register all agents used by this orchestrator."""
    registry = AgentRegistry()

    # --- Example: general-purpose assistant ---
    assistant = Agent(
        name="Assistant",
        llm="google:gemini-2.5-flash",
        system_prompt=(
            "You are a helpful AI assistant.  Answer user questions "
            "accurately and concisely."
        ),
    )
    registry.register(assistant)

    # --- Example: data analyst ---
    analyst = Agent(
        name="DataAnalyst",
        llm="google:gemini-2.5-flash",
        system_prompt=(
            "You are a data analyst.  When given data or a question about "
            "data, provide clear, data-driven insights."
        ),
    )
    registry.register(analyst)

    return registry


# ---------------------------------------------------------------------------
# Orchestrator factory
# ---------------------------------------------------------------------------

def build_orchestrator(registry: AgentRegistry) -> AutonomousOrchestrator:
    """Instantiate and configure the orchestrator."""
    orchestrator = AutonomousOrchestrator(
        agent_registry=registry,
        redis_url="redis://localhost:6379",
        use_event_bus=True,
        use_webhooks=True,
    )

    # --- Webhooks (uncomment / customise as needed) ---
    # orchestrator.register_webhook(
    #     path="/hooks/github",
    #     target_type="agent",
    #     target_id="Assistant",
    #     secret="your-webhook-secret",
    #     transform_fn=lambda p: f"GitHub event: {{p.get('action')}}",
    # )

    return orchestrator


# ---------------------------------------------------------------------------
# Application factory — required by gunicorn
# ---------------------------------------------------------------------------

async def create_app() -> web.Application:
    """Build the aiohttp application (called by each gunicorn worker)."""
    app = web.Application()

    registry = build_agents()
    orchestrator = build_orchestrator(registry)

    # Start orchestrator components (event bus, Redis jobs, hooks …)
    await orchestrator.start()

    # Mount HTTP routes (webhooks, admin UI, etc.)
    orchestrator.setup_routes(app)

    # Ensure clean shutdown
    async def on_cleanup(_app: web.Application) -> None:
        await orchestrator.stop()

    app.on_cleanup.append(on_cleanup)

    return app


# ---------------------------------------------------------------------------
# Development entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8080)
'''
