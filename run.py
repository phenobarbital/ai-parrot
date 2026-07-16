#!/usr/bin/env python3
import asyncio
import signal
import os
import sys

from navigator import Application
from navigator.ext.memcache import Memcache
from app import Main

# define a new Application
app = Application(Main, enable_jinja2=True)
mcache = Memcache()
mcache.setup(app)

# Enable WebSockets Support
app.add_websockets()


async def _install_force_exit_handler(aiohttp_app) -> None:
    """Replace Navigator's SIGINT/SIGTERM handler with one that allows force-exit.

    First SIGINT triggers graceful shutdown (same as Navigator's default).
    Second SIGINT prints a warning. Third SIGINT calls ``os._exit(1)``
    immediately so the user is never stuck waiting for a hung shutdown.
    """
    loop = asyncio.get_running_loop()
    nav = getattr(aiohttp_app, '_navigator', None) or app
    count = [0]

    def _handler(signame):
        count[0] += 1
        if count[0] >= 3:
            sys.stderr.write(
                f"\n[shutdown] Force exit after {count[0]} {signame} signals\n"
            )
            sys.stderr.flush()
            os._exit(1)

        if count[0] == 1:
            if hasattr(nav, '_shutdown_in_progress'):
                nav._shutdown_in_progress = True
            if hasattr(nav, '_shutdown_event') and nav._shutdown_event:
                nav._shutdown_event.set()
        else:
            sys.stderr.write(
                f"\n[shutdown] Ctrl+C once more to force exit\n"
            )
            sys.stderr.flush()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handler(s.name))


aiohttp_app = app.get_app()
aiohttp_app.on_startup.append(_install_force_exit_handler)


def _hard_exit_after_graceful_shutdown() -> None:
    """Force process termination once Navigator's graceful shutdown returns.

    By the time ``app.run()`` returns, every async resource has already been
    torn down cleanly (DB pools, Redis, bots, MCP subprocesses — see the
    "Navigator Shutdown completed" log line). What remains are non-daemon OS
    threads left behind by native/ML libraries loaded by the agents
    (transformers/torch, TensorFlow via the pytector prompt-injection guard,
    and google-genai/grpc). CPython's interpreter-exit phase tries to *join*
    those threads and blocks forever, hanging the process.

    We can't reliably join threads we don't own, so we dump any survivors for
    diagnosis, flush I/O, then hard-exit to bypass the join. This is the
    accepted remedy for third-party native-thread leaks at shutdown.
    """
    import logging
    import threading
    import faulthandler

    survivors = [
        t for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon
    ]
    if survivors:
        sys.stderr.write(
            f"[shutdown] {len(survivors)} non-daemon thread(s) still alive; "
            "forcing exit to avoid interpreter-join hang. Culprits:\n"
        )
        for t in survivors:
            sys.stderr.write(f"[shutdown]   - {t.name}\n")
        faulthandler.dump_traceback(file=sys.stderr)

    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
    finally:
        _hard_exit_after_graceful_shutdown()
