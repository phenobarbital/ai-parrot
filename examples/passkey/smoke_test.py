"""Smoke-test a running passkey demo server (no browser needed).

    python examples/passkey/smoke_test.py            # server already started on :5000

Checks: the SPA shell is served, both auth methods are advertised, password
login works, the demo agent is listed, and the passkey ceremony endpoints answer
for the configured origin. The WebAuthn ceremony itself needs a real browser
authenticator — see docs/examples/passkey-e2e.md.
"""

from __future__ import annotations

import asyncio
import os
import sys

import aiohttp

PORT = os.environ.get("DEMO_PORT", "5000")
BASE = f"http://localhost:{PORT}"
USER = os.environ.get("DEMO_USER", "demo")
PASSWORD = os.environ.get("DEMO_PASSWORD", "demo-password")
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Print a PASS/FAIL line and remember failures."""
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}".rstrip())
    if not ok:
        FAILED.append(name)


async def main() -> int:
    """Run every check and return the process exit code."""
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{BASE}/login") as resp:
            check("SPA shell at /login", resp.status == 200, f"({resp.status})")
        async with http.get(f"{BASE}/account/security") as resp:
            check("SPA shell at /account/security", resp.status == 200, f"({resp.status})")
        async with http.get(f"{BASE}/api/v1/auth/methods") as resp:
            methods = await resp.json()
            check(
                "BasicAuth + PasskeyAuth advertised", {"BasicAuth", "PasskeyAuth"} <= set(methods), str(list(methods))
            )
        async with http.post(
            f"{BASE}/api/v1/login",
            headers={"x-auth-method": "BasicAuth"},
            json={"username": USER, "password": PASSWORD},
        ) as resp:
            body = await resp.json()
            token = body.get("token", "")
            check("password login", resp.status == 200 and bool(token), f"({resp.status})")
        auth = {"Authorization": f"Bearer {token}"}
        async with http.get(f"{BASE}/api/v1/bots", headers=auth) as resp:
            text = await resp.text()
            check("demo agent listed", resp.status == 200 and "hello-agent" in text, f"({resp.status})")
        origin = {"Origin": BASE}
        async with http.post(f"{BASE}/api/v1/auth/passkey/login/options", headers=origin, json={}) as resp:
            body = await resp.json()
            key = body.get("publicKey", body)
            check("passkey login options", resp.status == 200 and "challenge" in key, f"({resp.status})")
        async with http.post(
            f"{BASE}/api/v1/auth/passkey/register/options", headers={**auth, **origin}, json={}
        ) as resp:
            body = await resp.json()
            key = body.get("publicKey", body)
            check("passkey register options (signed in)", resp.status == 200 and "challenge" in key, f"({resp.status})")
        async with http.get(f"{BASE}/api/v1/auth/passkey/credentials", headers=auth) as resp:
            check("passkey list (empty before enrolment)", resp.status == 200, f"({resp.status})")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
