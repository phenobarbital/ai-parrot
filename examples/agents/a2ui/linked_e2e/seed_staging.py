"""FEAT-611 M2 — staging-only verification and idempotent seed for the linked-surface E2E.

Usage (from the repo root, staging only):
    ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py describe
    ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py preview [--firstdate X --lastdate Y]
    ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py prove-policy
    ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py seed --confirm [--yes]

Refuses to run unless ENV=staging (the navconfig selector) AND the configured DBNAME contains 'staging'.
`describe`, `preview` and `prove-policy` are read-only. `seed` is the only write: it refuses without
`--confirm` and then also asks for an interactive 'yes' unless `--yes` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("FEAT611.seed")

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
MQ_SLUG = "epson_activity_vs_targets_mq"
ACTIVITY_SLUG = "epson_field_activity"
TARGETS_SLUG = "epson_program_targets"
MQ_DESCRIPTION = "FEAT-611 E2E: Epson field activity vs program targets (frames: result, targets)"
EXPECTED_FRAMES = ["result", "targets"]
POLICY_RESOURCE_TYPE = "source"
POLICY_ACTION = "source:read"

# FILL IN (verified by the staging `preview` run; record the outcome in F020):
# The MQ_SLUG pipeline. Bounded by (a) validate_pipeline(...).valid is True, (b) the preview's frame keys are
# exactly {"result", "targets"} (spec §3 M2 / S3 needs multi_output="targets", the 'result' fallback, and an
# ambiguous case), and (c) the MultiQS naming facts: a Join stores its output as "<left>.<right>" (Join.py:97),
# so a Join output can never be called "result". Hence no server-side Join: both frames are keyed by their
# query name, and the activity⋈targets join lives in the linked descriptor's transform.ops (M8).
# Offline-verified: ComponentRegistry.validate_pipeline (structural) accepts it (see the guard test).
# Still unverified until staging: that the targets slug tolerates the firstdate/lastdate conditions MultiQS
# forwards to every query, and that both frames come back (a DataNotFound on one frame changes the keys).
MQ_PIPELINE: dict[str, Any] = {
    "queries": {
        "result": {"slug": ACTIVITY_SLUG},
        "targets": {"slug": TARGETS_SLUG},
    },
}


def _current_dbname() -> str:
    """Return the DBNAME navconfig resolved (value is never logged). Tests monkeypatch this."""
    from navconfig import config  # imported lazily: bootstraps navconfig from os.environ["ENV"]

    return str(config.get("DBNAME", fallback="") or "")


def assert_staging() -> None:
    """Raise SystemExit unless ENV=staging and the configured DBNAME contains 'staging'."""
    # Check the SELECTOR, not navconfig.ENV: env/staging/.env sets ENV=production internally, so
    # navconfig.ENV reads "production" on staging (navconfig/__init__.py:93).
    selected = os.environ.get("ENV", "")
    if selected != "staging":
        raise SystemExit(f"refusing to run: ENV={selected!r}, expected 'staging'")
    if "staging" not in _current_dbname().lower():
        raise SystemExit("refusing to run: configured DBNAME does not contain 'staging'")
    logger.info("staging target confirmed (ENV=staging, DBNAME contains 'staging')")


async def describe_slugs(slugs: list[str]) -> dict[str, dict]:
    """Read-only qs_describe_slug for each slug; returns {slug: SlugDetail.model_dump()}."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    tk = QuerysourceToolkit(include_sql=True)  # allow_write=False: describe is a catalog read
    out: dict[str, dict] = {}
    try:
        for slug in slugs:
            detail = await tk.describe_slug(slug)
            out[slug] = detail.model_dump()
            logger.info(
                "describe %s: program=%s multiquery=%s placeholders=%s fields=%s",
                slug,
                detail.program_slug,
                detail.is_multiquery,
                detail.placeholders,
                detail.fields,
            )
    finally:
        await tk._close()
    return out


def build_pipeline() -> dict[str, Any]:
    """The MQ_SLUG pipeline: activity and targets as two frames named 'result' and 'targets'."""
    return json.loads(json.dumps(MQ_PIPELINE))  # fresh deep copy: MultiQS pops keys from its input


def check_frames(frames: list[str]) -> None:
    """Raise SystemExit unless the preview produced exactly the frames spec §3 M2 needs."""
    if sorted(frames) != EXPECTED_FRAMES:
        raise SystemExit(
            f"preview frame keys {sorted(frames)} != {EXPECTED_FRAMES}: fix MQ_PIPELINE or record the "
            "deviation in F020 before seeding"
        )


async def preview_multiquery(conditions: dict[str, Any]) -> dict[str, Any]:
    """Read-only: validate the pipeline and run it inline (no Output step); log frame keys and row counts."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    tk = QuerysourceToolkit(include_sql=True)
    try:
        pipeline = build_pipeline()
        validation = await tk.validate_pipeline(pipeline)
        logger.info("validate_pipeline valid=%s issues=%s", validation.valid, validation.issues)
        if not validation.valid:
            raise SystemExit(f"pipeline invalid: {validation.issues}")
        result = await tk.run_multiquery(pipeline=pipeline, conditions=conditions)
        # MultiQueryResult.results: dict[frame_name, ExecutionResult] (models.py:69-74); never return `rows`.
        frames = {
            name: {"columns": r.columns, "total_rows": r.total_rows, "returned_rows": r.returned_rows}
            for name, r in result.results.items()
        }
        logger.info("preview %s: status=%s frames=%s", MQ_SLUG, result.status, sorted(frames))
        check_frames(list(frames))
        return {"valid": validation.valid, "status": result.status, "frames": frames}
    finally:
        await tk._close()


async def seed_multiquery(*, overwrite: bool = True) -> dict:
    """Upsert MQ_SLUG via QuerysourceToolkit.save_multiquery (verified: toolkit.py:605); idempotent."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    details = await describe_slugs([ACTIVITY_SLUG])
    program = details[ACTIVITY_SLUG]["program_slug"]  # save needs an explicit program (catalog.py:148-150)
    tk = QuerysourceToolkit(programs=[program], allow_write=True)
    try:
        saved = await tk.save_multiquery(
            MQ_SLUG, build_pipeline(), MQ_DESCRIPTION, program=program, overwrite=overwrite
        )
        logger.info("seed %s: action=%s program=%s", saved.slug, saved.action, saved.program_slug)
        return saved.model_dump()
    finally:
        await tk._close()


_UNRELATED_POLICY_YAML = """\
# FEAT-611 policy-proof control: loads a real PBAC evaluator but grants nothing on `source`.
version: "1.0"
policies:
  - name: feat611_control_unrelated_allow
    effect: allow
    description: Control policy for the FEAT-611 deny proof; matches no source resource.
    resources: ["tool:feat611_unrelated_tool"]
    actions: ["tool:execute"]
    subjects: { groups: ["*"] }
    priority: 1
"""


async def run_policy_proof(
    user: str = "feat611-e2e",
    *,
    policy_dir: Path | str = POLICY_DIR,
    slug: str = ACTIVITY_SLUG,
) -> dict[str, str]:
    """Evaluate the guard with `policy_dir` and with a control dir (no source rule). No DB, no staging check.

    The control dir holds one unrelated allow policy so PBAC still initialises and returns a real guard:
    a deny there means "policy absent", never "guard missing" (§9 S5).
    """
    from aiohttp import web
    from parrot.auth.exceptions import AuthorizationRequired
    from parrot.auth.pbac import setup_dataplane_guard
    from parrot.auth.permission import build_principal_context
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

    resources = PhysicalResources(source_type="query_slug", source_id=f"public:{slug}")
    resource_name = f"{resources.source_type}:{resources.source_id}"
    pctx = build_principal_context(user, channel="ui_surfaces")  # same shape as the handler's owner_pctx
    outcome: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="feat611-nopolicy-") as control_dir:
        (Path(control_dir) / "unrelated.yaml").write_text(_UNRELATED_POLICY_YAML, encoding="utf-8")
        for label, pdir in (("with_policy", Path(policy_dir)), ("without_policy", Path(control_dir))):
            guard = setup_dataplane_guard(web.Application(), policy_dir=str(pdir))
            if guard is None:
                outcome[label] = "guard-missing"
                logger.error(
                    "%s: guard missing (PBAC did not initialise) resource_type=%s resource=%s action=%s",
                    label,
                    POLICY_RESOURCE_TYPE,
                    resource_name,
                    POLICY_ACTION,
                )
                continue
            try:
                await guard.authorize_source(pctx, resources)
                outcome[label] = "allow"
            except AuthorizationRequired:
                outcome[label] = "deny"
            logger.info(
                "%s: %s resource_type=%s resource=%s action=%s",
                label,
                outcome[label],
                POLICY_RESOURCE_TYPE,
                resource_name,
                POLICY_ACTION,
            )
    return outcome


async def prove_policy(user: str = "feat611-e2e") -> dict[str, str]:
    """Prove demo_allow_epson_linked_sources: allow with POLICY_DIR, deny without it; logs evaluated strings."""
    assert_staging()
    outcome = await run_policy_proof(user)
    if outcome != {"with_policy": "allow", "without_policy": "deny"}:
        raise SystemExit(f"policy proof failed: {outcome}")
    return outcome


def _confirm(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    if input(f"{prompt} [type 'yes' to continue]: ").strip().lower() != "yes":
        raise SystemExit("aborted by operator")


def main(argv: list[str] | None = None) -> int:
    """CLI: describe | preview | prove-policy | seed. Only `seed` writes (requires --confirm, then a prompt)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["describe", "preview", "prove-policy", "seed"])
    parser.add_argument("--confirm", action="store_true", help="required for `seed` (the only staging write)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive write confirmation")
    parser.add_argument("--firstdate", default="FDOM")
    parser.add_argument("--lastdate", default="TODAY")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    assert_staging()
    if args.command == "describe":
        result: Any = asyncio.run(describe_slugs([ACTIVITY_SLUG, TARGETS_SLUG]))
    elif args.command == "preview":
        result = asyncio.run(preview_multiquery({"firstdate": args.firstdate, "lastdate": args.lastdate}))
    elif args.command == "prove-policy":
        result = asyncio.run(prove_policy())
    else:
        if not args.confirm:
            raise SystemExit("refusing to seed: pass --confirm to write to the STAGING query catalog")
        _confirm(f"WRITE {MQ_SLUG} to the STAGING query catalog?", args.yes)
        result = asyncio.run(seed_multiquery(overwrite=True))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
