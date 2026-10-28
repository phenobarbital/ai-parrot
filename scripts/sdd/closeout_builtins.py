"""Builtin closeout-hook actions for /sdd-done (FEAT-764)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from scripts.sdd.closeout_hooks_config import HookContext, HookKind, HookResult, HookSpec, PUSH_PROVIDERS

BuiltinFn = Callable[[HookSpec, HookContext, Path], HookResult]
_JIRA_KEY_RE = re.compile(r"\*\*Jira\*\*: \[([A-Z]+-\d+)")


class _Defaulting(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _render(template: str, ctx: HookContext) -> str:
    """Format ``template`` with context fields; unknown placeholders render empty."""
    return template.format_map(_Defaulting(ctx.model_dump()))


async def _request(method: str, url: str, *, headers: dict[str, str] | None = None,
                   json_body: Any = None, data: str | None = None, timeout: int = 60) -> tuple[int, Any]:
    """Single HTTP seam (patched in tests). Returns (status, parsed body or text)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.request(method, url, headers=headers, json=json_body, data=data) as resp:
            try:
                body = await resp.json()
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                body = await resp.text()
            return resp.status, body


def _result(hook: HookSpec, status: str, summary: str, started: float) -> HookResult:
    return HookResult(name=hook.name, kind=HookKind.BUILTIN, status=status, blocking=hook.blocking,
                      duration_s=round(time.monotonic() - started, 3), summary=summary)


def jira_transition(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Transition the spec-linked Jira ticket; skipped when the spec has none."""
    started = time.monotonic()
    try:
        spec_text = Path(ctx.spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return _result(hook, "fail", f"Failed to read spec: {type(exc).__name__}", started)

    key_match = _JIRA_KEY_RE.search(spec_text)
    if not key_match:
        return _result(hook, "skipped", "No Jira key in spec", started)

    key = key_match.group(1)
    jira_instance = os.environ.get("JIRA_INSTANCE")
    jira_username = os.environ.get("JIRA_USERNAME")
    jira_api_token = os.environ.get("JIRA_API_TOKEN")

    if not all([jira_instance, jira_username, jira_api_token]):
        return _result(hook, "skipped", "Missing Jira credentials", started)

    base_url = f"{jira_instance.rstrip('/')}/rest/api/3"
    transitions_url = f"{base_url}/issue/{key}/transitions"

    try:
        # Try to import navconfig for credentials
        try:
            from navconfig import Config
            config = Config()
            jira_instance = config.get("jira", {}).get("instance", jira_instance)
            jira_username = config.get("jira", {}).get("username", jira_username)
            jira_api_token = config.get("jira", {}).get("api_token", jira_api_token)
        except ImportError:
            pass

        status, transitions = asyncio.run(_request("GET", transitions_url, headers={"Accept": "application/json"}, timeout=hook.timeout_s))
        if status != 200:
            return _result(hook, "fail", f"Failed to fetch transitions: HTTP {status}", started)

        target_status = hook.with_.get("status", "Done").lower()
        transition_id = None
        for transition in transitions.get("transitions", []):
            if transition.get("to", {}).get("name", "").lower() == target_status or transition.get("name", "").lower() == target_status:
                transition_id = transition.get("id")
                break

        if not transition_id:
            available = [t.get("to", {}).get("name", t.get("name", "")) for t in transitions.get("transitions", [])]
            return _result(hook, "fail", f"No matching transition for status '{target_status}'. Available: {', '.join(available)}", started)

        payload = {"transition": {"id": transition_id}}
        status, _ = asyncio.run(_request("POST", transitions_url, json_body=payload, headers={"Accept": "application/json"}, timeout=hook.timeout_s))
        if status != 204:
            return _result(hook, "fail", f"Transition failed: HTTP {status}", started)

        comment_url = f"{base_url}/issue/{key}/comment"
        comment_payload = {"body": f"PR merged: {ctx.pr_url or ''}\nSHA: {ctx.merge_sha or ''}"}
        status, _ = asyncio.run(_request("POST", comment_url, json_body=comment_payload, headers={"Accept": "application/json"}, timeout=hook.timeout_s))
        if status != 201:
            return _result(hook, "fail", f"Comment failed: HTTP {status}", started)

        return _result(hook, "pass", f"Transitioned {key} to {target_status} and posted comment", started)
    except Exception as exc:
        return _result(hook, "fail", f"Unexpected error: {type(exc).__name__}", started)


def telegram_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Send a Telegram message via the Bot API."""
    started = time.monotonic()
    token_env = hook.with_.get("token_env", "SDD_TELEGRAM_BOT_TOKEN")
    chat_env = hook.with_.get("chat_id_env", "SDD_TELEGRAM_CHAT_ID")
    token = os.environ.get(token_env)
    chat_id = os.environ.get(chat_env)

    if not token or not chat_id:
        return _result(hook, "skipped", "Missing Telegram credentials", started)

    template = hook.with_.get("template", "{feat_id}: {pr_url}")
    text = _render(template, ctx)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        status, body = asyncio.run(_request("POST", url, json_body=payload, timeout=hook.timeout_s))
        if status != 200:
            return _result(hook, "fail", f"Telegram send failed: HTTP {status}", started)
        return _result(hook, "pass", "Telegram message sent", started)
    except Exception as exc:
        return _result(hook, "fail", f"Unexpected error: {type(exc).__name__}", started)


def _push_ntfy(hook: HookSpec, ctx: HookContext, title: str, message: str, priority: str) -> tuple[str, str]:
    url_env = hook.with_.get("url_env", "SDD_NTFY_URL")
    topic_env = hook.with_.get("topic_env", "SDD_NTFY_TOPIC")
    token_env = hook.with_.get("token_env", "SDD_NTFY_TOKEN")

    url = os.environ.get(url_env)
    topic = os.environ.get(topic_env)
    token = os.environ.get(token_env)

    if not url or not topic:
        return "skipped", "Missing ntfy URL or topic"

    headers = {"Title": title, "Priority": priority}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        status, _ = asyncio.run(_request("POST", f"{url}/{topic}", headers=headers, data=message, timeout=hook.timeout_s))
        if status != 200:
            return "fail", f"ntfy send failed: HTTP {status}"
        return "pass", "ntfy notification sent"
    except Exception as exc:
        return "fail", f"Unexpected error: {type(exc).__name__}"


def _push_gotify(hook: HookSpec, ctx: HookContext, title: str, message: str, priority: str) -> tuple[str, str]:
    url_env = hook.with_.get("url_env", "SDD_GOTIFY_URL")
    token_env = hook.with_.get("token_env", "SDD_GOTIFY_TOKEN")

    url = os.environ.get(url_env)
    token = os.environ.get(token_env)

    if not url:
        return "skipped", "Missing gotify URL"

    payload = {"title": title, "message": message, "priority": priority}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Gotify-Key"] = token

    try:
        status, _ = asyncio.run(_request("POST", f"{url}/message", headers=headers, json_body=payload, timeout=hook.timeout_s))
        if status != 200:
            return "fail", f"gotify send failed: HTTP {status}"
        return "pass", "gotify notification sent"
    except Exception as exc:
        return "fail", f"Unexpected error: {type(exc).__name__}"


_PUSH: dict[str, Callable[..., tuple[str, str]]] = {"ntfy": _push_ntfy, "gotify": _push_gotify}
assert set(_PUSH) == set(PUSH_PROVIDERS)


def push_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Send a push notification through the configured provider (default ntfy)."""
    started = time.monotonic()
    provider = hook.with_.get("provider", "ntfy")
    title = hook.with_.get("title", "SDD Closeout: {feat_id}")
    message = hook.with_.get("message", "{pr_url}")
    priority = hook.with_.get("priority", "5")

    title_rendered = _render(title, ctx)
    message_rendered = _render(message, ctx)

    if provider not in _PUSH:
        return _result(hook, "fail", f"Unknown push provider: {provider}", started)

    status, summary = _PUSH[provider](hook, ctx, title_rendered, message_rendered, priority)
    return _result(hook, status, summary, started)


def webhook_post(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """POST the JSON context to a URL taken from an env var."""
    started = time.monotonic()
    url_env = hook.with_.get("url_env", "SDD_WEBHOOK_URL")
    url = os.environ.get(url_env)

    if not url:
        return _result(hook, "skipped", "Missing webhook URL", started)

    headers_env = hook.with_.get("headers_env")
    headers = {}
    if headers_env:
        headers_json = os.environ.get(headers_env)
        if headers_json:
            try:
                headers = json.loads(headers_json)
            except json.JSONDecodeError:
                return _result(hook, "fail", f"Invalid JSON in {headers_env}", started)

    try:
        status, _ = asyncio.run(_request("POST", url, json_body=ctx.model_dump(), headers=headers, timeout=hook.timeout_s))
        if status != 200:
            return _result(hook, "fail", f"Webhook POST failed: HTTP {status}", started)
        return _result(hook, "pass", "Webhook POST successful", started)
    except Exception as exc:
        return _result(hook, "fail", f"Unexpected error: {type(exc).__name__}", started)


BUILTINS: dict[str, BuiltinFn] = {
    "jira.transition": jira_transition,
    "telegram.send": telegram_send,
    "push.send": push_send,
    "webhook.post": webhook_post,
}


def run_builtin(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Run ``hook.builtin``; any unexpected exception becomes a ``fail`` result, never a crash."""
    started = time.monotonic()
    try:
        fn = BUILTINS.get(hook.builtin)
        if not fn:
            return _result(hook, "fail", f"Unknown builtin: {hook.builtin}", started)
        return fn(hook, ctx, artifact_dir)
    except Exception as exc:
        return _result(hook, "fail", f"Unexpected error: {type(exc).__name__}", started)
