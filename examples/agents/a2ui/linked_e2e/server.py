"""FEAT-611 M9 example server: QuerySource → data-plane guard → BotManager(EpsonLinkedAgent) → AuthHandler(BasicAuth).

    ENV=dev python examples/agents/a2ui/linked_e2e/server.py --port 5000 [--guard-mode policy|deny|none]

ENV must be a live target (`staging` or `dev`); production is always refused.

Guard modes (spec §2 S1 negatives):
    policy  the example policies/ dir (allows the public epson_* slugs)            → normal lane
    deny    a temporary policy dir holding ONLY the uri allow: HTTP passes the ABAC middleware, but the guard
            denies every data source                                                → 403 "Data source not permitted"
    none    no guard at all (PARROT_PBAC_POLICY_DIR → a nonexistent dir)          → 403 "... data-plane guard"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Live targets the example server may run against (== seed_staging.LIVE_ENVS).
LIVE_ENVS: tuple[str, ...] = ("staging", "dev")
POLICY_DIR = HERE / "policies"
GUARD_MODES = ("policy", "deny", "none")
#: deny mode's only policy: reach the HTTP endpoints, but no source/slug grant (so the guard denies).
DENY_MODE_URI_POLICY = """version: "1.0"
policies:
  - name: deny_mode_allow_uri_authenticated
    effect: allow
    resources: ["uri:*"]
    actions: ["uri:read", "uri:write", "uri:create", "uri:delete"]
    subjects: { groups: ["*"] }
    priority: 1
"""
NO_POLICY_DIR = HERE / "_no_policies_here"
logger = logging.getLogger("examples.a2ui.linked_e2e.server")


def create_app(guard_mode: str = "policy", *, policy_dir: str | Path | None = None, llm: str | None = None):
    """Build the aiohttp app in the spec §3 M9 mount order. `guard_mode` selects the S1 403 variants.

    Args:
        guard_mode: ``"policy"`` (default), ``"deny"`` or ``"none"`` — see the module docstring.
        policy_dir: Override the policy dir used in ``"policy"`` mode (default: the example ``policies/``).
        llm: Optional ``llm`` string for the agent (e.g. ``"google:gemini-2.5-flash"``); default = Agent's.

    Returns:
        The configured (not yet started) ``web.Application``.
    """
    if guard_mode not in GUARD_MODES:
        raise ValueError(f"guard_mode must be one of {GUARD_MODES}")
    if guard_mode == "none":
        # parrot.conf reads PARROT_PBAC_POLICY_DIR at import time (conf.py:118) — set before importing parrot.
        os.environ["PARROT_PBAC_POLICY_DIR"] = str(NO_POLICY_DIR)
    from aiohttp import web
    from navigator_auth import AuthHandler
    from querysource.services import QuerySource

    from parrot import conf as parrot_conf
    from parrot.auth.pbac import setup_dataplane_guard
    from parrot.manager import BotManager

    if guard_mode == "none" and Path(parrot_conf.PARROT_PBAC_POLICY_DIR) != NO_POLICY_DIR:
        raise RuntimeError("guard_mode='none' needs a fresh process: parrot.conf was imported before create_app")

    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from agent import EpsonLinkedAgent  # noqa: E402 — sibling example module (examples/ is not a package)

    app = web.Application()
    QuerySource(lazy=False).setup(app)  # 1. /api/v2/services/queries + /api/v3/queries + /api/v1/{tenant}/queries
    if guard_mode != "none":
        if guard_mode == "policy":
            pdir = Path(policy_dir or POLICY_DIR)
        else:
            # navigator-auth >= 0.28.3 enforces uri:* on every authenticated request, so an EMPTY dir would
            # 428 at the middleware before the data-plane guard could answer its 403. Allow URIs only.
            pdir = Path(tempfile.mkdtemp(prefix="linked-e2e-deny-"))
            (pdir / "uri-only.yaml").write_text(DENY_MODE_URI_POLICY, encoding="utf-8")
        guard = setup_dataplane_guard(app, policy_dir=str(pdir))  # 2. BEFORE BotManager: its hook reuses it
        logger.info(
            "data-plane guard=%s mode=%s policy_dir=%s", type(guard).__name__ if guard else None, guard_mode, pdir
        )
    agent = EpsonLinkedAgent(**({"llm": llm} if llm else {}))
    manager = BotManager(enable_database_bots=False, enable_registry_bots=False)  # 3.
    manager.add_bot(agent)  # BEFORE startup: _setup_dataplane_guard only walks registered bots
    # The admin UI lists/opens agents via GET /api/v1/bots[/{name}], which reads the DB (ai_bots) and the
    # AgentRegistry — never add_bot'ed instances. Register the instance so manual S4 can open its chat page.
    registry = getattr(manager, "registry", None)
    if registry is not None:
        registry.register_instance(agent.name, agent, tags={"feat-611", "example"}, replace=True)
    manager.setup(app)

    async def _configure_agent(app_: web.Application) -> None:
        # add_bot'ed bots are NOT configured by load_bots (manager.py:396-437); get_bot configures lazily
        # (:823-827). Configure eagerly so a broken LLM config surfaces at startup — but never kill the
        # server over it: the default lane (publish/refresh) does not need the LLM.
        try:
            await agent.configure(app_)
        except Exception:  # noqa: BLE001
            logger.exception("EpsonLinkedAgent.configure failed at startup; will retry lazily on first chat")
        logger.info("epson_linked guard=%s", type(getattr(agent, "_dataplane_guard", None)).__name__)

    app.on_startup.append(_configure_agent)  # runs after BotManager.on_startup and _setup_dataplane_guard
    AuthHandler(backends=["navigator_auth.backends.BasicAuth"]).setup(app)  # 4. /api/v1/login (dotted strings)
    return app


def main(argv: list[str] | None = None) -> None:
    """CLI entry point; refuses to start unless ENV is a live target (staging or dev)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--guard-mode", choices=GUARD_MODES, default="policy")
    parser.add_argument("--llm", default=None, help="agent llm string (only needed for run_e2e --via-agent)")
    args = parser.parse_args(argv)
    if os.environ.get("ENV") not in LIVE_ENVS:
        raise SystemExit(
            f"linked_e2e server refuses to start unless ENV is one of {list(LIVE_ENVS)} (spec §5: no production writes)"
        )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    from aiohttp import web

    web.run_app(create_app(args.guard_mode, llm=args.llm), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
