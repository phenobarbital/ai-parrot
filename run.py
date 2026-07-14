#!/usr/bin/env python3
from navigator import Application
from navigator.ext.memcache import Memcache
from app import Main

# define a new Application
app = Application(Main, enable_jinja2=True)
mcache = Memcache()
mcache.setup(app)

# Enable WebSockets Support
app.add_websockets()

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
    import os
    import sys
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
        # Full stacks so the exact blocking library can be pinpointed and,
        # if desired, fixed at the source in a later pass.
        faulthandler.dump_traceback(file=sys.stderr)

    # Flush the async log worker / stdout so nothing buffered is lost, since
    # os._exit skips atexit handlers and buffer flushing.
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
