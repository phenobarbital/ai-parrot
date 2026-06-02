"""Autonomous orchestrator for AI-Parrot.

The autonomous implementation is part of the server layer (ai-parrot-server satellite).

Use: pip install ai-parrot-server[autonomous]
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Lazy loader: resolves public names from the satellite when installed.
# If ai-parrot-server is not installed, raises ImportError with an install hint.
_AUTONOMOUS_CLASSES: dict[str, str] = {
    "AutonomousOrchestrator": "parrot.autonomous.orchestrator",
    "ExecutionTarget": "parrot.autonomous.orchestrator",
    "ExecutionRequest": "parrot.autonomous.orchestrator",
    "ExecutionResult": "parrot.autonomous.orchestrator",
    "TriggerMode": "parrot.autonomous.scheduler",
    "AgentTriggerConfig": "parrot.autonomous.scheduler",
    "AutonomousJob": "parrot.autonomous.scheduler",
    "RedisJobInjector": "parrot.autonomous.redis_jobs",
    "WebhookEndpoint": "parrot.autonomous.webhooks",
    "WebhookListener": "parrot.autonomous.webhooks",
    # Heartbeat — FEAT-209 (autonomous-agent-heartbeat)
    "HeartbeatConfig": "parrot.autonomous.heartbeat",
    "HeartbeatState": "parrot.autonomous.heartbeat",
    "HeartbeatStrategy": "parrot.autonomous.heartbeat",
    "DefaultHeartbeatStrategy": "parrot.autonomous.heartbeat",
    "HeartbeatManager": "parrot.autonomous.heartbeat",
    # Event Ledger — FEAT-212 (event-ledger-resume)
    # App startup wiring sequence:
    #   db = app["database"]
    #   backend = PostgresLedgerBackend(db)
    #   await backend.ensure_schema()
    #   recorder = LedgerRecorder(backend)
    #   recorder.start()
    #   # At orchestrator start (opt-in crash resume):
    #   await orchestrator.resume(backend)
    #   # or: await orchestrator.start(ledger=backend, resume_on_start=True)
    "EventLedger": "parrot.autonomous.ledger",
    "PostgresLedgerBackend": "parrot.autonomous.ledger",
    "LedgerRecorder": "parrot.autonomous.ledger",
    "LedgerEvent": "parrot.autonomous.ledger",
    "LedgerConfig": "parrot.autonomous.ledger",
    "AgentLedgerState": "parrot.autonomous.ledger",
    "IncompleteExecution": "parrot.autonomous.ledger",
    "InMemoryLedgerBackend": "parrot.autonomous.ledger",
}


def __getattr__(name: str):
    """Lazy-import autonomous classes from the satellite package."""
    if name in _AUTONOMOUS_CLASSES:
        import importlib
        module_path = _AUTONOMOUS_CLASSES[name]
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise ImportError(
                f"{name!r} requires the ai-parrot-server package. "
                "Install it with: pip install ai-parrot-server[autonomous]"
            ) from exc
        attr = getattr(module, name, None)
        if attr is None:
            raise AttributeError(
                f"module {module_path!r} has no attribute {name!r}"
            )
        return attr
    raise AttributeError(
        f"module 'parrot.autonomous' has no attribute {name!r}. "
        "Install the server package: pip install ai-parrot-server[autonomous]"
    )
