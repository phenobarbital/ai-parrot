"""Gunicorn configuration for the AI-Parrot server (API + embedded web UI).

Usage (from the repository root, venv active)::

    gunicorn --config deploy/gunicorn.conf.py "run:create_app()"

``run.create_app()`` builds the same Navigator application ``python run.py``
serves (``app.Main``: BotManager, navigator-auth, the web UI at ``/``,
``/login``, ``/agents`` and ``/admin``), once per worker.

Every value below can be overridden through the environment, so the same
file serves development and supervisord/systemd deployments:

- ``APP_HOST`` / ``APP_PORT``   bind address (same settings ``run.py`` reads; default 0.0.0.0:5000)
- ``PARROT_BIND``               full bind spec, overrides the two above (e.g. ``unix:/run/parrot.sock``)
- ``WEB_CONCURRENCY``           worker processes (default: 2)
- ``GUNICORN_TIMEOUT``          worker silence timeout in seconds (default: 300, agent calls are long)
- ``GUNICORN_LOGLEVEL``         gunicorn log level (default: info)

``AUTH_SECRET_KEY`` MUST be set (env or navconfig) when running more than one
worker — see :func:`on_starting`.

Each worker runs its own asyncio loop (``aiohttp.GunicornWebWorker``) and its
own BotManager, so per-request state must live in Redis/PostgreSQL — which is
already the case for sessions (navigator-auth) and conversation history.
"""
import os

_host = os.environ.get("APP_HOST", "0.0.0.0")
_port = os.environ.get("APP_PORT", "5000")

bind = os.environ.get("PARROT_BIND", f"{_host}:{_port}")
worker_class = "aiohttp.GunicornWebWorker"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# Streaming chat responses and tool-calling agents can keep a request open
# for minutes: be generous before killing a silent worker.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 120
keepalive = 5

# Recycle workers periodically to bound memory growth from ML libraries.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "2000"))
max_requests_jitter = 200

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")


def on_starting(server):
    """Fail fast on a multi-worker setup without a shared auth secret.

    navigator-auth signs login JWTs with ``AUTH_SECRET_KEY``; when it is unset
    each process generates a random key at import time, so a token minted by
    one worker is rejected (401) by every other worker right after login.
    """
    if workers <= 1:
        return
    from navconfig import config  # pylint: disable=import-outside-toplevel

    if not config.get("AUTH_SECRET_KEY"):
        server.log.error(
            "AUTH_SECRET_KEY is not set: with %s workers each one would sign "
            "login tokens with its own random key and users would get 401s "
            "after signing in. Set AUTH_SECRET_KEY (shared by all workers) or "
            "run with WEB_CONCURRENCY=1.",
            workers,
        )
        raise SystemExit(1)
