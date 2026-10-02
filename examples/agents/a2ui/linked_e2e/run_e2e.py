"""FEAT-611 M9 asserting HTTP runner — S1/S2/S3/S5 against a running linked_e2e server (live: staging or dev).

    ENV=dev E2E_USER=... E2E_PASSWORD=... python examples/agents/a2ui/linked_e2e/run_e2e.py \\
        --base-url http://127.0.0.1:5000 [--deny-base-url http://127.0.0.1:5001] \\
        [--noguard-base-url http://127.0.0.1:5002] [--via-agent] [--scenarios s1,s2,s3,s5]

Optional env: E2E_SHARE_USER / E2E_SHARE_PASSWORD (a second user for the share-bearer refresh),
E2E_S2_RANGE_A / E2E_S2_RANGE_B ("firstdate:lastdate", two ranges KNOWN to hold different data),
E2E_RANGE ("firstdate:lastdate" used by S1/S3/S5 and the S2 publish; must hold data).
Defaults per ENV: staging → FDOM:TODAY / YESTERDAY:YESTERDAY; dev (data only 2024-12-31..2025-03-23) →
2025-03-01:2025-03-07 / 2025-03-11:2025-03-15, and E2E_RANGE defaults to range A.
Every row prints PASS / FAIL / SKIP; SKIP never counts as a pass. Exit 0 only when at least one check ran
and every non-skipped check passed; 1 otherwise; 2 when refused (ENV not in LIVE_ENVS).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
MQ_SLUG = "epson_e2e_activity_vs_targets_mq"  # == seed_staging.MQ_SLUG (TASK-3832)
ACTIVITY_SLUG = "epson_e2e_activity"  # == seed_staging.ACTIVITY_SLUG
AGENT_NAME = "epson_linked"
#: Live targets the runner accepts (== seed_staging.LIVE_ENVS); production is always refused.
LIVE_ENVS: tuple[str, ...] = ("staging", "dev")
DEFAULT_RANGE_A = "FDOM:TODAY"
DEFAULT_RANGE_B = "YESTERDAY:YESTERDAY"
#: The dev DB only holds 2024-12-31..2025-03-23; these two ranges hold different data.
DEV_RANGE_A = "2025-03-01:2025-03-07"
DEV_RANGE_B = "2025-03-11:2025-03-15"
logger = logging.getLogger("examples.a2ui.linked_e2e.run_e2e")


@dataclass
class ScenarioResult:
    id: str
    passed: bool
    detail: str
    skipped: bool = False


@dataclass
class E2EContext:
    session: aiohttp.ClientSession
    base_url: str
    token: str
    share_token_user: str | None = None  # bearer JWT of the second (share) user, when configured
    deny_base_url: str | None = None
    noguard_base_url: str | None = None
    via_agent: bool = False
    credentials: tuple[str, str] | None = None  # re-login on the deny/noguard servers
    tool_pctx: Any = None  # the runner's own in-process TOOL call runs guarded under the example policy
    tool_guard: Any = None
    state: dict[str, Any] = field(default_factory=dict)  # surface ids etc. shared between checks

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json"}


async def login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> str:
    """POST /api/v1/login with X-Auth-Method: BasicAuth (NA auth.py:684); returns the bearer token."""
    user_key = os.environ.get("AUTH_USERNAME_ATTRIBUTE", "username")  # BasicAuth.username_attribute
    password_key = os.environ.get("AUTH_PASSWORD_ATTRIBUTE", "password")
    async with session.post(
        f"{base_url}/api/v1/login",
        json={user_key: user, password_key: password},
        headers={"X-Auth-Method": "BasicAuth"},
    ) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200 or not isinstance(body, dict) or "token" not in body:
            raise RuntimeError(f"login failed ({resp.status}) for {user!r}")
        return body["token"]


def check(results: list[ScenarioResult], sid: str, ok: bool, detail: str) -> bool:
    results.append(ScenarioResult(sid, bool(ok), detail))
    return bool(ok)


def skip(results: list[ScenarioResult], sid: str, detail: str) -> None:
    results.append(ScenarioResult(sid, False, detail, skipped=True))


def _range(value: str) -> tuple[str, str]:
    first, _, last = value.partition(":")
    return first, last or first


def s2_default_ranges() -> tuple[str, str]:
    """Return the (A, B) S2 range defaults for the selected ENV (env overrides are applied by run_s2)."""
    if os.environ.get("ENV") == "dev":
        return DEV_RANGE_A, DEV_RANGE_B
    return DEFAULT_RANGE_A, DEFAULT_RANGE_B


def live_range() -> tuple[str, str]:
    """Return the (firstdate, lastdate) S1/S3/S5 use: E2E_RANGE, else the ENV's S2 range A."""
    return _range(os.environ.get("E2E_RANGE") or s2_default_ranges()[0])


def load_dashboard_tool():
    spec = importlib.util.spec_from_file_location("linked_e2e_dashboard_tool", HERE / "dashboard_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def publish(
    ctx: E2EContext, envelope: dict, title: str, base_url: str | None = None, token: str | None = None
) -> tuple[int, dict]:
    """POST /api/v1/ui/surfaces {kind: dashboard, title, envelope} → (status, body)."""
    async with ctx.session.post(
        f"{base_url or ctx.base_url}/api/v1/ui/surfaces",
        headers=ctx.headers(token),
        json={"kind": "dashboard", "title": title, "envelope": envelope},
    ) as resp:
        return resp.status, await resp.json(content_type=None)


def _short(body: Any) -> str:
    return json.dumps(body, default=str)[:200]


def rows_of(body: dict, key: str) -> list | None:
    """dataModel[key].rows of a GET/refresh body ({status, envelope: <inner CreateSurface>, metadata})."""
    envelope = body.get("envelope") if isinstance(body, dict) else None
    root = ((envelope or {}).get("dataModel") or {}).get(key)
    return root.get("rows") if isinstance(root, dict) else None


def _canon(rows: list | None) -> list[str]:
    """Order-insensitive row comparison key."""
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in (rows or []))


def linked_envelope(surface_id: str, components: list[dict], sources: dict[str, Any]) -> dict:
    """A TOOL-shaped linked CreateSurface dict with empty rows; the server snapshots it on publish."""
    from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID  # noqa: PLC0415

    return {
        "surfaceId": surface_id,
        "catalogId": DEFAULT_CATALOG_ID,
        "components": components,
        "dataModel": {key: {"rows": []} for key in sources},
        "metadata": {
            "extensions": {
                "parrot_data_sources": {
                    key: src.model_dump(mode="json", by_alias=True, exclude_none=False) for key, src in sources.items()
                }
            }
        },
    }


def static_envelope() -> dict:
    """A baked, non-recipe surface (no parrot_data_sources) → not refreshable (409)."""
    from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID  # noqa: PLC0415

    return {
        "surfaceId": "feat611-static",
        "catalogId": DEFAULT_CATALOG_ID,
        "components": [{"id": "root", "component": "Text", "text": "FEAT-611 static surface"}],
    }


def mq_source(multi_output: str | None, *, key: str = "mq"):
    from parrot.outputs.a2ui.linked.conditions import derive_conditions  # noqa: PLC0415
    from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest  # noqa: PLC0415

    first, last = live_range()
    request = SourceRequest(placeholders={"firstdate": first, "lastdate": last})
    return LinkedDataSource(
        slug=MQ_SLUG,
        is_multiquery=True,
        multi_output=multi_output,
        conditions=derive_conditions(request, locked={}),
        request=request,
        target=f"/{key}/rows",
    )


def activity_source(tenant: str | None, *, key: str = "activity"):
    from parrot.outputs.a2ui.linked.conditions import derive_conditions  # noqa: PLC0415
    from parrot.outputs.a2ui.linked.models import LinkedDataSource, ParamSpec, SourceRequest  # noqa: PLC0415

    first, last = live_range()
    request = SourceRequest(placeholders={"firstdate": first, "lastdate": last})
    return LinkedDataSource(
        slug=ACTIVITY_SLUG,
        tenant=tenant,
        conditions=derive_conditions(request, locked={}),
        request=request,
        target=f"/{key}/rows",
        params={
            "firstdate": ParamSpec(type="date", accepts_keywords=True),
            "lastdate": ParamSpec(type="date", accepts_keywords=True),
        },
    )


async def dashboard_envelope(ctx: E2EContext) -> dict:
    """The S2 TOOL's inner CreateSurface (snapshot=False); guarded in-process when a guard is available."""
    tool = load_dashboard_tool()
    first, last = live_range()
    result = await tool.build_epson_activity_dashboard(
        first, last, snapshot=False, pctx=ctx.tool_pctx, guard=ctx.tool_guard
    )
    return result["a2ui_envelope"]


async def refresh(
    ctx: E2EContext, surface_id: str, params: dict, *, token: str | None = None, share: str | None = None
) -> tuple[int, dict, Any]:
    url = f"{ctx.base_url}/api/v1/ui/surfaces/{surface_id}/refresh"
    query = {"share": share} if share else None
    async with ctx.session.post(url, headers=ctx.headers(token), params=query, json={"params": params}) as resp:
        return resp.status, await resp.json(content_type=None), resp.headers.copy()


async def get_surface(ctx: E2EContext, surface_id: str, fmt: str | None = None) -> tuple[int, Any]:
    query = {"format": fmt} if fmt else None
    async with ctx.session.get(
        f"{ctx.base_url}/api/v1/ui/surfaces/{surface_id}", headers=ctx.headers(), params=query
    ) as resp:
        body = await resp.text()
        if fmt == "html" and resp.status == 200:
            return resp.status, body
        try:
            return resp.status, json.loads(body)
        except ValueError:
            return resp.status, body


def _stamps(body: Any) -> dict[str, Any]:
    envelope = body.get("envelope") if isinstance(body, dict) else None
    sources = (((envelope or {}).get("metadata") or {}).get("extensions") or {}).get("parrot_data_sources") or {}
    return {key: src.get("snapshot_at") for key, src in sources.items()}


async def via_agent_envelope(ctx: E2EContext, results: list[ScenarioResult]) -> dict | None:
    """--via-agent: drive AgentTalk (output_mode=a2ui) and lift response.a2ui_envelope (TASK-3835 v1.0 wrapper)."""
    first, last = live_range()
    query = (
        "Build the Epson activity dashboard with build_epson_activity_dashboard "
        f"(firstdate {first}, lastdate {last}, snapshot false) and return it as an A2UI surface."
    )
    async with ctx.session.post(
        f"{ctx.base_url}/api/v1/agents/chat/{AGENT_NAME}",
        headers=ctx.headers(),
        params={"output_mode": "a2ui"},
        json={"query": query},
    ) as resp:
        body = await resp.json(content_type=None)
        status = resp.status
    wrapper = body.get("a2ui_envelope") if isinstance(body, dict) else None
    if isinstance(wrapper, list):
        wrapper = next((w for w in wrapper if isinstance(w, dict) and "createSurface" in w), None)
    inner = wrapper.get("createSurface") if isinstance(wrapper, dict) else None
    if not check(
        results,
        "s1.via_agent_envelope",
        status == 200 and isinstance(inner, dict),
        f"{status} a2ui_envelope={'present' if inner else 'missing'}",
    ):
        return None
    return inner


async def _s1_negatives_403(ctx: E2EContext, results: list[ScenarioResult], envelope: dict) -> None:
    """Publish the linked envelope to the deny / no-guard servers (other guard modes of server.py)."""
    for sid_key, url, expect in (
        ("s1.403_no_policy", ctx.deny_base_url, "Data source not permitted"),
        ("s1.403_no_guard", ctx.noguard_base_url, "data-plane guard"),
    ):
        if url is None:
            skip(results, sid_key, "server URL for this guard mode not given")
            continue
        token = ctx.token
        if ctx.credentials is not None:
            token = await login(ctx.session, url, *ctx.credentials)
        status, body = await publish(ctx, envelope, sid_key, base_url=url, token=token)
        check(results, sid_key, status == 403 and expect in json.dumps(body), f"{status} {_short(body)}")


async def run_s1(ctx: E2EContext) -> list[ScenarioResult]:
    """Server lane + share + PBAC (spec §2 S1, including every negative case)."""
    results: list[ScenarioResult] = []
    envelope = await dashboard_envelope(ctx)
    if ctx.via_agent:
        envelope = await via_agent_envelope(ctx, results)
        if envelope is None:
            return results
    status, body = await publish(ctx, envelope, "FEAT-611 S1")
    if not check(results, "s1.publish", status == 201, f"{status} {_short(body)}"):
        return results
    sid = ctx.state["s1_surface_id"] = body["surface_id"]
    g_status, g_body = await get_surface(ctx, sid)
    rows = rows_of(g_body, "activity") if isinstance(g_body, dict) else None
    check(
        results,
        "s1.get_json",
        g_status == 200 and isinstance(rows, list) and bool(rows),
        f"{g_status} activity rows={len(rows) if isinstance(rows, list) else None}",
    )
    h_status, _ = await get_surface(ctx, sid, "html")
    if h_status == 501:
        skip(results, "s1.get_html", "501: ai-parrot-visualizations not installed on the server")
    else:
        check(results, "s1.get_html", h_status == 200, f"{h_status}")
    g2_status, g2_body = await get_surface(ctx, sid)
    check(
        results,
        "s1.get_no_execution",
        g2_status == 200 and _stamps(g2_body) == _stamps(g_body),
        "snapshot_at unchanged across GET json/html/json",
    )
    first, last = live_range()
    status, body, _ = await refresh(ctx, sid, {"firstdate": first, "lastdate": last})
    check(results, "s1.refresh_params", status == 200, f"{status} {_short(body) if status != 200 else ''}")
    status, _, headers = await refresh(ctx, sid, {"activity": {"store_id": 7}})
    warnings = headers.get("X-Parrot-Refresh-Warnings", "")
    check(
        results, "s1.warnings_undeclared", status == 200 and "store_id" in warnings, f"{status} {warnings or 'missing'}"
    )
    await _s1_share(ctx, results, sid)
    await _s1_negatives_409(ctx, results, sid)
    await _s1_negatives_403(ctx, results, envelope)
    return results


async def _s1_share(ctx: E2EContext, results: list[ScenarioResult], sid: str) -> None:
    async with ctx.session.post(
        f"{ctx.base_url}/api/v1/ui/surfaces/{sid}/share", headers=ctx.headers(), json={}
    ) as resp:
        status, body = resp.status, await resp.json(content_type=None)
    if not check(results, "s1.share_mint", status == 201 and "token" in body, f"{status}"):
        return
    bearer = ctx.share_token_user or ctx.token
    note = "second user" if ctx.share_token_user else "same user (E2E_SHARE_USER not set)"
    status, body, _ = await refresh(ctx, sid, {}, token=bearer, share=body["token"])
    check(results, "s1.share_bearer_refresh", status == 200, f"{status} {note}")


async def _s1_negatives_409(ctx: E2EContext, results: list[ScenarioResult], sid: str) -> None:
    status, body = await publish(ctx, static_envelope(), "FEAT-611 S1 static")
    if check(results, "s1.static_publish", status == 201, f"{status} {_short(body)}"):
        status, body, _ = await refresh(ctx, body["surface_id"], {})
        check(results, "s1.409_baked", status == 409 and body.get("refreshable") is False, f"{status} {_short(body)}")
    (s_a, b_a, _), (s_b, b_b, _) = await asyncio.gather(refresh(ctx, sid, {}), refresh(ctx, sid, {}))
    statuses = sorted((s_a, s_b))
    if statuses == [200, 200]:
        skip(results, "s1.409_stale", "both concurrent refreshes won (no race); offline tier covers it")
        return
    stale = b_a if s_a == 409 else b_b
    check(
        results,
        "s1.409_stale",
        statuses == [200, 409] and stale.get("error") == "stale refresh",
        f"{statuses} {_short(stale)}",
    )


async def run_s2(ctx: E2EContext) -> list[ScenarioResult]:
    """Dashboard TOOL envelope publishes (validates server-side) and a FilterBar-param refresh changes rows."""
    results: list[ScenarioResult] = []
    status, body = await publish(ctx, await dashboard_envelope(ctx), "FEAT-611 S2")
    if not check(results, "s2.publish_validates", status == 201, f"{status} {_short(body)}"):
        return results
    sid = body["surface_id"]
    observed: dict[str, tuple[list | None, list | None]] = {}
    default_a, default_b = s2_default_ranges()
    for label, env_key, default in (("a", "E2E_S2_RANGE_A", default_a), ("b", "E2E_S2_RANGE_B", default_b)):
        first, last = _range(os.environ.get(env_key, default))
        status, rbody, _ = await refresh(ctx, sid, {"activity": {"firstdate": first, "lastdate": last}})
        ok = check(results, f"s2.refresh_range_{label}", status == 200, f"{status} {first}..{last}")
        observed[label] = (rows_of(rbody, "activity"), rows_of(rbody, "targets")) if ok else (None, None)
    (act_a, tgt_a), (act_b, tgt_b) = observed["a"], observed["b"]
    if act_a is None or act_b is None:
        skip(results, "s2.activity_rows_differ", "a range refresh failed")
        return results
    check(
        results,
        "s2.activity_rows_differ",
        _canon(act_a) != _canon(act_b),
        f"rows a={len(act_a)} b={len(act_b)} (set E2E_S2_RANGE_A/B to two ranges with different data)",
    )
    check(results, "s2.targets_unchanged", _canon(tgt_a) == _canon(tgt_b), f"targets rows={len(tgt_a or [])}")
    return results


async def run_s3(ctx: E2EContext) -> list[ScenarioResult]:
    """Multiquery DataTable over MQ_SLUG: multi_output / 'result' fallback / missing output → 502 (spec §2 S3)."""
    results: list[ScenarioResult] = []
    columns: dict[str, frozenset] = {}
    for case, multi_output in (("multi_output", "targets"), ("result_fallback", None)):
        component = {"id": "root", "component": "DataTable", "data": {"path": "/mq/rows"}}
        envelope = linked_envelope(f"feat611-s3-{case}", [component], {"mq": mq_source(multi_output)})
        status, body = await publish(ctx, envelope, f"FEAT-611 S3 {case}")
        if not check(results, f"s3.{case}.publish", status == 201, f"{status} {_short(body)}"):
            continue
        status, rbody, _ = await refresh(ctx, body["surface_id"], {})
        rows = rows_of(rbody, "mq") or []
        check(results, f"s3.{case}.refresh", status == 200, f"{status} rows={len(rows)}")
        columns[case] = frozenset(rows[0]) if rows else frozenset()
    if all(columns.get(case) for case in ("multi_output", "result_fallback")):
        check(
            results,
            "s3.frames_distinct",
            columns["multi_output"] != columns["result_fallback"],
            f"targets cols={sorted(columns['multi_output'])} result cols={sorted(columns['result_fallback'])}",
        )
    else:
        skip(results, "s3.frames_distinct", "a frame was empty or failed")
    component = {"id": "root", "component": "DataTable", "data": {"path": "/mq/rows"}}
    envelope = linked_envelope("feat611-s3-missing", [component], {"mq": mq_source("nope")})
    status, body = await publish(ctx, envelope, "FEAT-611 S3 missing output")
    check(
        results, "s3.missing_output_502", status == 502 and body.get("code") == "data_stage", f"{status} {_short(body)}"
    )
    return results


def _qs_rows(body: Any) -> list | None:
    """QS route bodies are a bare row list or {data|result: rows}."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "result", "rows"):
            if isinstance(body.get(key), list):
                return body[key]
    return None


async def _qs_post(ctx: E2EContext, path: str, payload: dict) -> tuple[int, list | None]:
    async with ctx.session.post(f"{ctx.base_url}{path}", headers=ctx.headers(), json=payload) as resp:
        if resp.status == 204:  # QuerySource "Empty Result": zero rows, no body
            return resp.status, []
        return resp.status, _qs_rows(await resp.json(content_type=None))


async def run_s5(ctx: E2EContext) -> list[ScenarioResult]:
    """tenant='public' descriptor: the tenant route, the browser's v2 route, the v3 lane and /refresh all agree."""
    results: list[ScenarioResult] = []
    first, last = live_range()
    payload = {"firstdate": first, "lastdate": last, "querylimit": 5000}
    t_status, tenant_rows = await _qs_post(ctx, f"/api/v1/public/queries/{ACTIVITY_SLUG}", payload)
    check(
        results,
        "s5.tenant_route",
        t_status == 200 and tenant_rows is not None,
        f"{t_status} rows={len(tenant_rows or [])}",
    )
    # The browser lane POSTs a regular (non-multiquery, no-tenant) slug to v2 — plain QS, never MultiQS.
    b_status, v2_rows = await _qs_post(ctx, f"/api/v2/services/queries/{ACTIVITY_SLUG}", payload)
    check(results, "s5.v2_route", b_status == 200 and v2_rows is not None, f"{b_status} rows={len(v2_rows or [])}")
    v_status, v3_rows = await _qs_post(ctx, f"/api/v3/queries/{ACTIVITY_SLUG}", payload)
    check(results, "s5.v3_route", v_status == 200 and v3_rows is not None, f"{v_status} rows={len(v3_rows or [])}")
    if tenant_rows is not None and v2_rows is not None and v3_rows is not None:
        check(
            results,
            "s5.routes_equal",
            _canon(tenant_rows) == _canon(v2_rows) == _canon(v3_rows),
            f"tenant={len(tenant_rows)} v2={len(v2_rows)} v3={len(v3_rows)}",
        )
    if v2_rows is not None and v3_rows is not None:
        check(results, "s5.v2_equals_v3", _canon(v2_rows) == _canon(v3_rows), f"v2={len(v2_rows)} v3={len(v3_rows)}")
    refreshed: dict[str, list | None] = {}
    for label, tenant in (("default", None), ("public", "public")):
        component = {
            "id": "root",
            "component": "Chart",
            "type": "bar",
            "x": "day",
            "y": ["visits"],
            "data": {"path": "/activity/rows"},
        }
        envelope = linked_envelope(f"feat611-s5-{label}", [component], {"activity": activity_source(tenant)})
        status, body = await publish(ctx, envelope, f"FEAT-611 S5 tenant={tenant}")
        if not check(results, f"s5.{label}.publish", status == 201, f"{status} {_short(body)}"):
            refreshed[label] = None
            continue
        status, rbody, _ = await refresh(ctx, body["surface_id"], {"firstdate": first, "lastdate": last})
        refreshed[label] = rows_of(rbody, "activity") if status == 200 else None
        check(results, f"s5.{label}.refresh", status == 200, f"{status} rows={len(refreshed[label] or [])}")
    if refreshed.get("default") is None or refreshed.get("public") is None:
        skip(results, "s5.tenant_rows_equal", "a tenant/default refresh failed")
    else:
        check(
            results,
            "s5.tenant_rows_equal",
            _canon(refreshed["default"]) == _canon(refreshed["public"]),
            f"default={len(refreshed['default'])} public={len(refreshed['public'])}",
        )
    return results


def write_table(results: list[ScenarioResult], stream: Any = None) -> None:
    """Write the PASS/FAIL/SKIP table (the CLI's result output) to `stream` (default stdout)."""
    stream = stream or sys.stdout
    width = max((len(r.id) for r in results), default=10)
    for r in results:
        verdict = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        stream.write(f"{r.id:<{width}}  {verdict:<4}  {r.detail[:160]}\n")


def verdict(results: list[ScenarioResult]) -> int:
    """0 iff at least one non-skipped check ran and every non-skipped check passed; SKIP never counts as pass."""
    ran = [r for r in results if not r.skipped]
    return 0 if ran and all(r.passed for r in ran) else 1


RUNNERS = {"s1": run_s1, "s2": run_s2, "s3": run_s3, "s5": run_s5}


async def run_all(ctx: E2EContext, scenarios: list[str]) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for name in scenarios:
        try:
            results.extend(await RUNNERS[name](ctx))
        except Exception as exc:  # noqa: BLE001 — one broken scenario must not hide the others' rows
            logger.exception("scenario %s crashed", name)
            results.append(ScenarioResult(f"{name}.crashed", False, f"{type(exc).__name__}: {exc}"))
    return results


def _tool_guard(user: str) -> tuple[Any, Any]:
    """Guard + pctx for the runner's in-process TOOL call (example policy); (None, None) when PBAC is absent."""
    from aiohttp import web  # noqa: PLC0415

    from parrot.auth.pbac import setup_dataplane_guard  # noqa: PLC0415
    from parrot.auth.permission import build_principal_context  # noqa: PLC0415

    guard = setup_dataplane_guard(web.Application(), policy_dir=str(POLICY_DIR))
    if guard is None:
        logger.warning("no data-plane guard for the in-process TOOL call — it runs unguarded")
        return None, None
    return guard, build_principal_context(user, channel="ui_surfaces")


async def open_context(
    session: aiohttp.ClientSession,
    base_url: str,
    *,
    deny_base_url: str | None = None,
    noguard_base_url: str | None = None,
    via_agent: bool = False,
) -> E2EContext:
    """Log in E2E_USER (+ optional E2E_SHARE_USER) and build the shared E2EContext (used by main and pytest)."""
    user, password = os.environ["E2E_USER"], os.environ["E2E_PASSWORD"]
    token = await login(session, base_url, user, password)
    share_token = None
    if os.environ.get("E2E_SHARE_USER") and os.environ.get("E2E_SHARE_PASSWORD"):
        share_token = await login(session, base_url, os.environ["E2E_SHARE_USER"], os.environ["E2E_SHARE_PASSWORD"])
    guard, pctx = _tool_guard(user)
    return E2EContext(
        session=session,
        base_url=base_url.rstrip("/"),
        token=token,
        share_token_user=share_token,
        deny_base_url=deny_base_url,
        noguard_base_url=noguard_base_url,
        via_agent=via_agent,
        credentials=(user, password),
        tool_pctx=pctx,
        tool_guard=guard,
    )


async def _amain(args: argparse.Namespace) -> int:
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = sorted(set(scenarios) - set(RUNNERS))
    if unknown:
        logger.error("unknown scenarios: %s", unknown)
        return 1
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout)) as session:
        try:
            ctx = await open_context(
                session,
                args.base_url,
                deny_base_url=args.deny_base_url,
                noguard_base_url=args.noguard_base_url,
                via_agent=args.via_agent,
            )
        except (RuntimeError, aiohttp.ClientError) as exc:
            logger.error("cannot open the E2E context: %s", exc)
            return 1
        results = await run_all(ctx, scenarios)
    write_table(results)
    return verdict(results)


def main(argv: list[str] | None = None) -> int:
    """Exit code 0 only when every non-skipped check passed (and at least one ran)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--deny-base-url", default=os.environ.get("E2E_DENY_BASE_URL"))
    parser.add_argument("--noguard-base-url", default=os.environ.get("E2E_NOGUARD_BASE_URL"))
    parser.add_argument("--via-agent", action="store_true", help="S1 envelope from AgentTalk (needs an LLM)")
    parser.add_argument("--scenarios", default="s1,s2,s3,s5")
    parser.add_argument("--timeout", type=float, default=300.0, help="per-session HTTP timeout (seconds)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if os.environ.get("ENV") not in LIVE_ENVS:
        logger.error("run_e2e refuses to run unless ENV is one of %s", list(LIVE_ENVS))
        return 2
    if not (os.environ.get("E2E_USER") and os.environ.get("E2E_PASSWORD")):
        logger.error("E2E_USER and E2E_PASSWORD are required")
        return 2
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
