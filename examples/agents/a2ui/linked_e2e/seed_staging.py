"""FEAT-611 M2 — live-target (staging or dev) verification and idempotent seed for the linked-surface E2E.

Usage (from the MAIN checkout root; ENV is `staging` or `dev`):
    ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py describe
    ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py preview [--firstdate X --lastdate Y]
    ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py prove-policy
    ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py seed-sql --confirm [--yes]
    ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py seed --confirm [--yes]

Refuses to run unless ENV (the navconfig selector) is one of LIVE_ENVS AND the configured DBNAME contains that
env name (and never 'prod'); production is always refused. `describe`, `preview` and `prove-policy` are
read-only. `seed-sql` upserts the two dedicated SQL slugs (ACTIVITY_SLUG, TARGETS_SLUG) into the QS queries
table; `seed` does `seed-sql` first and then upserts the multiquery MQ_SLUG. Both writes refuse without
`--confirm` and then also ask for an interactive 'yes' unless `--yes` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("FEAT611.seed")

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
#: Navconfig selectors the live tier may target; production is never one of them.
LIVE_ENVS: tuple[str, ...] = ("staging", "dev")
#: Dedicated E2E slugs (seeded by `seed-sql` / `seed`); all match the demo policy's `epson_*` pattern.
ACTIVITY_SLUG = "epson_e2e_activity"
TARGETS_SLUG = "epson_e2e_targets"
MQ_SLUG = "epson_e2e_activity_vs_targets_mq"
MQ_DESCRIPTION = "FEAT-611 E2E: Epson field activity vs program targets (frames: result, targets)"
#: Program the dedicated slugs belong to (same program_slug/program_id as the real epson_* slugs).
PROGRAM_SLUG = "epson"
PROGRAM_ID = 19
EXPECTED_FRAMES = ["result", "targets"]
POLICY_RESOURCE_TYPE = "source"
POLICY_ACTION = "source:read"

# FILL IN (verified by the live `preview` run — staging or dev; record the outcome in F020):
# The MQ_SLUG pipeline. Bounded by (a) validate_pipeline(...).valid is True, (b) the preview's frame keys are
# exactly {"result", "targets"} (spec §3 M2 / S3 needs multi_output="targets", the 'result' fallback, and an
# ambiguous case), and (c) the MultiQS naming facts: a Join stores its output as "<left>.<right>" (Join.py:97),
# so a Join output can never be called "result". Hence no server-side Join: both frames are keyed by their
# query name, and the activity⋈targets join lives in the linked descriptor's transform.ops (M8).
# Offline-verified: ComponentRegistry.validate_pipeline (structural) accepts it (see the guard test).
# Still unverified until the live preview: that the targets slug tolerates the firstdate/lastdate conditions MultiQS
# forwards to every query, and that both frames come back (a DataNotFound on one frame changes the keys).
# Live-verified on dev (2026-09-29): MultiQS applies conditions ONLY when keyed by child query name
# (`self._conditions.pop(name, {})`, querysource/queries/multi/__init__.py:451) — flat top-level
# conditions (what a linked descriptor sends) never reach the children. So the stored pipeline pins the
# child placeholders itself (MQ_RANGE); a linked multiquery source cannot re-parametrize them per refresh.
MQ_RANGE: tuple[str, str] = ("2025-03-01", "2025-03-07")
MQ_PIPELINE: dict[str, Any] = {
    "queries": {
        "result": {"slug": ACTIVITY_SLUG, "firstdate": MQ_RANGE[0], "lastdate": MQ_RANGE[1]},
        "targets": {"slug": TARGETS_SLUG},
    },
}

#: The two dedicated SQL slugs `seed-sql` upserts. QS placeholder style ({fields}/{where_cond}/{firstdate}/...)
#: follows the real epson slugs; is_cached=False so refresh checks always see live data.
SQL_SLUGS: dict[str, dict[str, Any]] = {
    ACTIVITY_SLUG: {
        "description": "FEAT-611 E2E: Epson visits per day, program and store (dedicated E2E slug)",
        "query_raw": (
            "SELECT {fields} FROM (SELECT visit_date AS day, account_name AS program, store_id, "
            "count(*)::int AS visits FROM epson.vw_form_information "
            "WHERE visit_date BETWEEN {firstdate} AND {lastdate} "
            "AND account_name IS NOT NULL AND store_id IS NOT NULL GROUP BY 1,2,3) t {where_cond}"
        ),
        "conditions": {"firstdate": "FDOM", "lastdate": "CURRENT_DATE"},
        "cond_definition": {"firstdate": "date", "lastdate": "date"},
    },
    TARGETS_SLUG: {
        "description": "FEAT-611 E2E: static per-program visit targets (dedicated E2E slug)",
        "query_raw": (
            "SELECT {fields} FROM (VALUES ('Best Buy'::varchar, 60), ('Office Depot', 40), ('Staples', 30), "
            "('Staples Canada', 20), ('Target', 30), ('BEST BUY CANADA', 15), ('Costco', 25)) "
            "AS t(program, target) WHERE {firstdate}::date IS NOT NULL AND {lastdate}::date IS NOT NULL "
            "{and_cond}"
        ),
        # Live-verified on dev: a slug WITHOUT the firstdate/lastdate placeholders gets them appended as
        # WHERE filters ('column "firstdate" does not exist'), and the server /refresh broadcasts params to
        # every source — so targets declares them as no-op placeholders with the same defaults as activity.
        "conditions": {"firstdate": "FDOM", "lastdate": "CURRENT_DATE"},
        "cond_definition": {"firstdate": "date", "lastdate": "date"},
    },
}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _current_dbname() -> str:
    """Return the DBNAME navconfig resolved (value is never logged). Tests monkeypatch this."""
    from navconfig import config  # imported lazily: bootstraps navconfig from os.environ["ENV"]

    return str(config.get("DBNAME", fallback="") or "")


def assert_live_target() -> str:
    """Raise SystemExit unless ENV is a LIVE_ENVS selector and DBNAME contains it (never 'prod').

    Returns:
        The selected env name (``"staging"`` or ``"dev"``).
    """
    # Check the SELECTOR, not navconfig.ENV: env/staging/.env sets ENV=production internally, so
    # navconfig.ENV reads "production" on staging (navconfig/__init__.py:93).
    selected = os.environ.get("ENV", "")
    if selected not in LIVE_ENVS:
        raise SystemExit(f"refusing to run: ENV={selected!r}, expected one of {list(LIVE_ENVS)}")
    dbname = _current_dbname().lower()
    if selected not in dbname or "prod" in dbname:
        raise SystemExit(f"refusing to run: configured DBNAME does not contain {selected!r} (or names production)")
    logger.info("live target confirmed (ENV=%s, DBNAME contains %r)", selected, selected)
    return selected


#: Backwards-compatible alias (FEAT-611 staging-only name).
assert_staging = assert_live_target


async def describe_slugs(slugs: list[str], *, missing_ok: bool = False) -> dict[str, dict]:
    """Read-only qs_describe_slug for each slug; returns {slug: SlugDetail.model_dump()}.

    Args:
        slugs: Slugs to describe.
        missing_ok: Record ``{"missing": True}`` for an unknown slug instead of raising (CLI `describe`).
    """
    assert_live_target()
    from parrot_tools.querysource.errors import SlugNotFoundError
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    tk = QuerysourceToolkit(include_sql=True)  # allow_write=False: describe is a catalog read
    out: dict[str, dict] = {}
    try:
        for slug in slugs:
            try:
                detail = await tk.describe_slug(slug)
            except SlugNotFoundError:
                if not missing_ok:
                    raise
                logger.warning("describe %s: not in the catalog (run `seed-sql` / `seed`)", slug)
                out[slug] = {"missing": True}
                continue
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
    assert_live_target()
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
    assert_live_target()
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


def _db_params() -> dict[str, Any]:
    """Return asyncpg connect kwargs from navconfig (DBHOST/DBPORT/DBUSER/DBPWD/DBNAME, PGSSLMODE→ssl).

    Values are never logged. Tests monkeypatch this.
    """
    from navconfig import config  # imported lazily: bootstraps navconfig from os.environ["ENV"]

    params: dict[str, Any] = {
        "host": config.get("DBHOST", fallback="localhost"),
        "port": int(config.get("DBPORT", fallback=5432)),
        "user": config.get("DBUSER"),
        "password": config.get("DBPWD"),
        "database": config.get("DBNAME"),
    }
    sslmode = config.get("PGSSLMODE", fallback=None)
    if sslmode:
        params["ssl"] = str(sslmode)  # asyncpg accepts libpq sslmode strings (disable/require/verify-full/...)
    return params


def _queries_table() -> str:
    """Return the quoted ``<QS_QUERIES_SCHEMA>.<QS_QUERIES_TABLE>`` name (defaults ``public.queries``)."""
    from navconfig import config

    schema = str(config.get("QS_QUERIES_SCHEMA", fallback="public") or "public")
    table = str(config.get("QS_QUERIES_TABLE", fallback="queries") or "queries")
    for ident in (schema, table):
        if not _IDENT.match(ident):
            raise SystemExit(f"refusing to seed: unsafe queries table identifier {ident!r}")
    return f'"{schema}"."{table}"'


def _upsert_sql(table: str, overwrite: bool) -> str:
    """Return the INSERT … ON CONFLICT (query_slug) statement; RETURNING tells insert from update."""
    conflict = (
        "DO UPDATE SET description = EXCLUDED.description, query_raw = EXCLUDED.query_raw, "
        "conditions = EXCLUDED.conditions, cond_definition = EXCLUDED.cond_definition, "
        "provider = EXCLUDED.provider, parser = EXCLUDED.parser, is_raw = EXCLUDED.is_raw, "
        "is_cached = EXCLUDED.is_cached, program_id = EXCLUDED.program_id, "
        "program_slug = EXCLUDED.program_slug, updated_at = now()"
        if overwrite
        else "DO NOTHING"
    )
    return (
        f"INSERT INTO {table} (query_slug, description, query_raw, conditions, cond_definition, provider, parser, "
        "is_raw, is_cached, cache_timeout, cache_refresh, dwh, program_id, program_slug, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, 'db', 'pgSQLParser', false, false, 3600, 0, false, $6, $7, "
        f"now(), now()) ON CONFLICT (query_slug) {conflict} RETURNING (xmax = 0) AS inserted"
    )


async def seed_sql_slugs(*, overwrite: bool = True) -> dict[str, str]:
    """Idempotently upsert the SQL_SLUGS (ACTIVITY_SLUG, TARGETS_SLUG) into the QS queries table via asyncpg.

    Args:
        overwrite: Update an existing row (``True``) or leave it untouched (``False``).

    Returns:
        ``{slug: "inserted" | "updated" | "unchanged"}``.
    """
    assert_live_target()
    import asyncpg  # noqa: PLC0415 — imported only after the live-target guard

    table = _queries_table()
    sql = _upsert_sql(table, overwrite)
    outcome: dict[str, str] = {}
    conn = await asyncpg.connect(**_db_params())
    try:
        async with conn.transaction():
            for slug, spec in SQL_SLUGS.items():
                row = await conn.fetchrow(
                    sql,
                    slug,
                    spec["description"],
                    spec["query_raw"],
                    json.dumps(spec["conditions"]),
                    json.dumps(spec["cond_definition"]),
                    PROGRAM_ID,
                    PROGRAM_SLUG,
                )
                outcome[slug] = "unchanged" if row is None else ("inserted" if row["inserted"] else "updated")
                logger.info("seed-sql %s: %s (table=%s)", slug, outcome[slug], table)
    finally:
        await conn.close()
    return outcome


async def seed_all(*, overwrite: bool = True) -> dict[str, Any]:
    """`seed`: the SQL slugs first (the multiquery references them), then MQ_SLUG."""
    sql = await seed_sql_slugs(overwrite=overwrite)
    return {"sql": sql, "multiquery": await seed_multiquery(overwrite=overwrite)}


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
    """Evaluate the guard with `policy_dir` and with a control dir (no source rule). No DB, no live-target check.

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
    assert_live_target()
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
    """CLI: describe | preview | prove-policy | seed-sql | seed. Writes require --confirm, then a prompt."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["describe", "preview", "prove-policy", "seed-sql", "seed"])
    parser.add_argument("--confirm", action="store_true", help="required for `seed-sql` / `seed` (catalog writes)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive write confirmation")
    parser.add_argument("--firstdate", default="FDOM")
    parser.add_argument("--lastdate", default="TODAY")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    target = assert_live_target()
    if args.command == "describe":
        result: Any = asyncio.run(describe_slugs([ACTIVITY_SLUG, TARGETS_SLUG, MQ_SLUG], missing_ok=True))
    elif args.command == "preview":
        result = asyncio.run(preview_multiquery({"firstdate": args.firstdate, "lastdate": args.lastdate}))
    elif args.command == "prove-policy":
        result = asyncio.run(prove_policy())
    else:
        if not args.confirm:
            raise SystemExit(f"refusing to {args.command}: pass --confirm to write to the {target.upper()} catalog")
        slugs = [ACTIVITY_SLUG, TARGETS_SLUG] + ([MQ_SLUG] if args.command == "seed" else [])
        _confirm(f"WRITE {', '.join(slugs)} to the {target.upper()} query catalog?", args.yes)
        if args.command == "seed-sql":
            result = asyncio.run(seed_sql_slugs(overwrite=True))
        else:
            result = asyncio.run(seed_all(overwrite=True))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
