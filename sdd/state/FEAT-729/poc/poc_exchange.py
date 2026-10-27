"""PoC capa 3: intercambio real token Azure -> sesion navigator-auth.

Levanta una app aiohttp DESECHABLE en proceso con navigator-auth cargando
AzureAuth + TokenExchangeAuth (que NO esta habilitado en el servicio vivo
de :5000), y hace el POST /api/v1/login real.

Uso:
    python poc_exchange.py <fichero_con_el_token>      # access token Graph
    python poc_exchange.py <fichero> --id-token <fichero_id_token>

El token se lee de un FICHERO, nunca de argv, para que no quede en `ps`.
"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

SEP = "=" * 72


def banner(text):
    print(f"\n{SEP}\n{text}\n{SEP}")


def claims_of(token):
    """Decodifica el payload de un JWT SIN verificar firma (solo inspeccion)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as err:
        print(f"  no se pudo decodificar el token como JWT: {err}")
        return {}


def mask(value, keep=6):
    if not value:
        return "<vacio>"
    v = str(value)
    return f"{v[:keep]}...{v[-4:]}" if len(v) > keep + 6 else v


async def whoami(request):
    """Ruta protegida: demuestra que navigator-auth sabe QUIEN es el usuario."""
    from parrot.auth.session_identity import resolve_session_user, resolve_user_id

    user = resolve_session_user(request)
    session = None
    try:
        from navigator_session import get_session

        session = await get_session(request)
    except Exception as err:
        print(f"  (get_session fallo: {err})")

    nav_user_id = resolve_user_id(request, session)
    payload = {
        "nav_user_id": nav_user_id,
        "identity_type": type(user).__name__ if user is not None else None,
        "username": getattr(user, "username", None),
        "email": getattr(user, "email", None),
        "auth_method": getattr(user, "auth_method", None),
    }
    return web.json_response(payload)


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    token = Path(sys.argv[1]).read_text().strip()
    id_token = None
    if "--id-token" in sys.argv:
        id_token = Path(sys.argv[sys.argv.index("--id-token") + 1]).read_text().strip()

    # ------------------------------------------------------------------
    banner("PASO 1 — inspeccion del token recibido (sin verificar firma)")
    c = claims_of(token)
    now = int(time.time())
    print(f"  aud   = {c.get('aud')}")
    print(f"  appid = {c.get('appid') or c.get('azp')}")
    print(f"  oid   = {c.get('oid')}")
    print(f"  tid   = {c.get('tid')}")
    print(f"  upn   = {c.get('upn') or c.get('unique_name') or c.get('preferred_username')}")
    print(f"  scp   = {c.get('scp')}")
    exp = c.get("exp")
    print(f"  exp   = {exp} ({(exp - now) if exp else '?'}s restantes)")
    if id_token:
        ic = claims_of(id_token)
        print(f"  [id_token] aud={ic.get('aud')} oid={ic.get('oid')} tid={ic.get('tid')}")

    # ------------------------------------------------------------------
    banner("PASO 2 — contrato de AZURE_TRUSTED_APPIDS")
    import navigator_auth.backends.azure as azmod
    from navigator_auth.conf import AZURE_ADFS_CLIENT_ID

    appid = c.get("appid") or c.get("azp")
    print(f"  AZURE_ADFS_CLIENT_ID      = {mask(AZURE_ADFS_CLIENT_ID)}")
    print(f"  appids confiables (antes) = {[mask(a) for a in azmod._AZURE_TRUSTED_APPIDS]}")
    print(f"  audiencias aceptadas      = {[mask(a) for a in azmod._AZURE_GRAPH_AUDIENCES]}")

    if appid and appid not in azmod._AZURE_TRUSTED_APPIDS:
        azmod._AZURE_TRUSTED_APPIDS = frozenset(
            {*azmod._AZURE_TRUSTED_APPIDS, appid}
        )
        print(f"\n  >> appid {mask(appid)} NO estaba confiado. Lo anado en caliente.")
        print("  >> En produccion esto es exactamente:")
        print(f"     AZURE_TRUSTED_APPIDS={appid}")
        print("     (lo mismo que habria que hacer con el app id del bot de Teams)")
    else:
        print("\n  >> el appid del token ya esta confiado; sin cambios")

    # ------------------------------------------------------------------
    banner("PASO 2b — ¿existe ya el usuario en auth.users? (requisito D4)")
    candidato = (
        c.get("upn") or c.get("unique_name") or c.get("preferred_username") or ""
    )
    if candidato:
        import asyncpg
        from navconfig import config as nc

        dsn = (
            f"postgres://{nc.get('PG_USER')}:{nc.get('PG_PASSWORD')}"
            f"@{nc.get('PG_HOST')}:{nc.get('PG_PORT')}/{nc.get('PG_DATABASE')}"
        )
        try:
            conn = await asyncpg.connect(dsn, timeout=8)
            row = await conn.fetchrow(
                "select user_id, username, email from auth.users "
                "where lower(email) = lower($1) or lower(username) = lower($1) "
                "or lower(alt_email) = lower($1) limit 1",
                candidato,
            )
            await conn.close()
            if row:
                print(f"  OK: {candidato} existe -> user_id={row['user_id']}")
                print("  el intercambio podra resolver la fila de auth.users")
            else:
                print(f"  AVISO: {candidato} NO esta en auth.users")
                print("  TokenExchangeAuth NUNCA provisiona usuarios (decision D4):")
                print("  el intercambio dara 401 'Invalid Credentials' con motivo")
                print("  reason=user_not_found en el log, aunque el token sea valido.")
        except Exception as err:
            print(f"  no se pudo consultar auth.users: {type(err).__name__}: {err}")
    else:
        print("  el token no trae upn/unique_name/preferred_username;")
        print("  la resolucion dependera del email que devuelva Graph /me")

    # ------------------------------------------------------------------
    banner("PASO 3 — app desechable con AzureAuth + TokenExchangeAuth")
    from navigator_auth import AuthHandler

    app = web.Application()
    auth = AuthHandler(
        backends=[
            "navigator_auth.backends.azure.AzureAuth",
            "navigator_auth.backends.exchange.TokenExchangeAuth",
        ],
        authz_backends=[],
        enable_authdb=True,
    )
    auth.setup(app)
    app.router.add_get("/poc/whoami", whoami)

    print(f"  backends cargados: {sorted(auth.backends.keys())}")
    assert "TokenExchangeAuth" in auth.backends, "TokenExchangeAuth no cargo"
    print("  OK: TokenExchangeAuth presente (en :5000 vivo NO lo esta)")

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # --------------------------------------------------------------
        banner("PASO 4 — POST /api/v1/login  (X-Auth-Method: TokenExchangeAuth)")
        body = {"provider": "azure", "token": token, "token_type": "Bearer"}
        if id_token:
            body["id_token"] = id_token

        resp = await client.post(
            "/api/v1/login",
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Auth-Method": "TokenExchangeAuth",
            },
        )
        raw = await resp.text()
        print(f"  HTTP {resp.status}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
            print(f"  cuerpo: {raw[:600]}")

        if data:
            secretos = ("token", "access_token", "id_token", "session_id", "refresh_token")
            safe = {
                k: (f"<redactado len={len(str(v))}>" if k in secretos else v)
                for k, v in data.items()
            }
            print(f"  cuerpo: {json.dumps(safe, indent=2, default=str)[:1800]}")

        if resp.status != 200:
            banner("RESULTADO — intercambio RECHAZADO")
            print("  El fallo es informativo: indica en que gate murio.")
            print("  - 'Unacceptable Auth Method' -> backend no cargado")
            print("  - 400 unsupported/not loaded  -> provider azure ausente")
            print("  - 401 Invalid Credentials     -> token invalido / aud / appid")
            print("    o Graph /me lo rechazo, o el email no existe en auth.users")
            print("  Revisa el log WARNING de arriba: dice el motivo exacto.")
            return 1

        # --------------------------------------------------------------
        banner("PASO 5 — ¿QUE usuario es?  (sesion Navigator viva)")
        session_token = data.get("token") or data.get("access_token")
        who = await client.get(
            "/poc/whoami",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        print(f"  HTTP {who.status}")
        print(f"  {await who.text()}")

        banner("RESULTADO — ARGUMENTO VALIDADO")
        print("  token delegado de Azure -> sesion navigator-auth -> nav user id.")
        print("  Es el eslabon que faltaba: con el token del usuario de Teams")
        print("  (via OAuth connection del Azure Bot) este mismo POST da una")
        print("  sesion Navigator identificando al hablante.")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
