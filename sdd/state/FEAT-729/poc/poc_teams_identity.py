"""PoC capa 1+2: identidad del usuario de MS Teams y contrato del token-exchange.

Ejecuta las funciones REALES del repo (no reimplementaciones) contra una
Activity sintética de Teams, y luego ejercita el verificador real de
navigator-auth para demostrar qué exige exactamente.

Hermetico: no hace llamadas de red. El unico punto que las haria
(`AzureAuth._verify_jwt` -> JWKS) se stubbea para forzar la rama
documentada "signature not independently verifiable".
"""
import asyncio
import base64
import json
import time

SEP = "=" * 72


def banner(text):
    print(f"\n{SEP}\n{text}\n{SEP}")


def unsigned_jwt(claims):
    """JWT sin firma valida — suficiente para los chequeos de aud/appid/exp."""
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256', 'typ': 'JWT'})}.{seg(claims)}.c2ln"


# ---------------------------------------------------------------------------
# CAPA 1 — ¿quien habla?
# ---------------------------------------------------------------------------

def capa1_identidad():
    banner("CAPA 1 — identidad asertada por Teams (codigo real del repo)")

    from botbuilder.schema import Activity, ActivityTypes, ChannelAccount
    from botbuilder.schema.teams import TeamsChannelAccount
    from parrot.integrations.msteams.commands.jira_commands import _get_user_id

    # Activity tal como la entrega el Bot Framework en un canal de Teams.
    activity = Activity(
        type=ActivityTypes.message,
        text="@bot cuanto vendimos ayer?",
        from_property=ChannelAccount(
            id="29:1aBcDeFgHiJkLmNoPqRsTuVwXyZ_teams_scoped_id",
            name="Jesus Lara",
            aad_object_id="7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f",
        ),
        channel_data={"tenant": {"id": "11112222-3333-4444-5555-666677778888"}},
        channel_id="msteams",
        conversation=type("C", (), {"id": "a:conv-id-123"})(),
    )

    class _Ctx:
        def __init__(self, act):
            self.activity = act

    turn_context = _Ctx(activity)

    print("Campos crudos de la Activity:")
    print(f"  from_property.id        = {activity.from_property.id}")
    print(f"  from_property.aad_object_id = {activity.from_property.aad_object_id}")
    print(f"  from_property.name      = {activity.from_property.name}")
    print(f"  channel_data.tenant.id  = {activity.channel_data['tenant']['id']}")

    # Funcion REAL: msteams/commands/jira_commands.py
    resolved = _get_user_id(turn_context)
    print(f"\n[REAL] jira_commands._get_user_id() -> {resolved}")
    assert resolved == activity.from_property.aad_object_id, "deberia preferir aad_object_id"
    print("  OK: prefiere aad_object_id (identidad estable de Entra ID)")

    # Fallback cuando no hay AAD (entornos no corporativos)
    activity.from_property.aad_object_id = None
    fallback = _get_user_id(turn_context)
    print(f"[REAL] sin aad_object_id        -> {fallback}")
    assert fallback == activity.from_property.id
    print("  OK: cae al id de Teams")
    activity.from_property.aad_object_id = "7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f"

    # Funcion REAL: msteams/commands/knowledge_upload.py -> resolve_email()
    from parrot.integrations.msteams.commands import knowledge_upload as ku

    roster_member = TeamsChannelAccount(
        id=activity.from_property.id,
        name="Jesus Lara",
        given_name="Jesus",
        surname="Lara",
        email="jesus.lara@empresa.com",
        user_principal_name="jesus.lara@empresa.com",
        aad_object_id="7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f",
        tenant_id="11112222-3333-4444-5555-666677778888",
    )

    class _FakeTeamsInfo:
        @staticmethod
        async def get_member(ctx, user_id):
            print(f"  (TeamsInfo.get_member llamado con user_id={user_id})")
            return roster_member

    original = ku.TeamsInfo
    ku.TeamsInfo = _FakeTeamsInfo
    try:
        import logging

        shim = type("S", (), {"logger": logging.getLogger("poc")})()
        email = asyncio.run(
            ku.TeamsKnowledgeUpload.resolve_email(shim, turn_context)
        )
    finally:
        ku.TeamsInfo = original

    print(f"[REAL] knowledge_upload.resolve_email() -> {email}")
    assert email == "jesus.lara@empresa.com"
    print("  OK: email/UPN disponible via roster del bot")

    print("\nVEREDICTO CAPA 1: la identidad del hablante esta disponible")
    print("  (oid de Entra + email/UPN + tenant) usando codigo YA presente.")
    print("  LIMITE: es una asercion de Teams obtenida con credenciales del")
    print("  BOT. No es un token del usuario; no sirve como prueba de")
    print("  posesion frente a otra API.")

    return {
        "aad_object_id": resolved,
        "email": email,
        "tenant_id": activity.channel_data["tenant"]["id"],
    }


# ---------------------------------------------------------------------------
# CAPA 2 — contrato del intercambio en navigator-auth
# ---------------------------------------------------------------------------

def capa2_contrato_exchange(identidad):
    banner("CAPA 2 — contrato REAL de TokenExchangeAuth / AzureAuth")

    from navigator_auth.backends.azure import (
        AzureAuth,
        _AZURE_GRAPH_AUDIENCES,
        _AZURE_TRUSTED_APPIDS,
    )
    from navigator_auth.conf import (
        AZURE_ADFS_CLIENT_ID,
        TOKEN_EXCHANGE_MAX_TTL,
        TOKEN_EXCHANGE_PROVIDERS,
    )
    from navigator_auth.exceptions import InvalidAuth

    def mask(value):
        if not value:
            return "<vacio>"
        v = str(value)
        return f"{v[:8]}...{v[-4:]}" if len(v) > 14 else v

    print("Config efectiva de ESTE despliegue:")
    print(f"  TOKEN_EXCHANGE_PROVIDERS = {TOKEN_EXCHANGE_PROVIDERS}")
    print(f"  TOKEN_EXCHANGE_MAX_TTL   = {TOKEN_EXCHANGE_MAX_TTL}s")
    print(f"  AZURE_ADFS_CLIENT_ID     = {mask(AZURE_ADFS_CLIENT_ID)}")
    print(f"  audiencias aceptadas     = {sorted(mask(a) for a in _AZURE_GRAPH_AUDIENCES)}")
    print(f"  appids confiables        = {sorted(mask(a) for a in _AZURE_TRUSTED_APPIDS)}")
    print(f"  (AZURE_TRUSTED_APPIDS extra configurados: "
          f"{len(_AZURE_TRUSTED_APPIDS) - 1})")

    backend = AzureAuth.__new__(AzureAuth)
    import logging

    backend.logger = logging.getLogger("poc.azure")

    async def _verify_jwt_stub(*args, **kwargs):
        raise InvalidAuth("JWKS no consultado (PoC hermetica)")

    backend._verify_jwt = _verify_jwt_stub

    now = int(time.time())
    casos = [
        (
            "Token de Teams SSO (aud = la propia app del bot)",
            {
                "aud": "api://bot.empresa.com/botid-aaaa-bbbb",
                "appid": AZURE_ADFS_CLIENT_ID,
                "oid": identidad["aad_object_id"],
                "exp": now + 3600,
                "tid": identidad["tenant_id"],
            },
        ),
        (
            "Token Graph de una app NO confiable",
            {
                "aud": "https://graph.microsoft.com",
                "appid": "99999999-dead-beef-0000-111111111111",
                "oid": identidad["aad_object_id"],
                "exp": now + 3600,
                "tid": identidad["tenant_id"],
            },
        ),
        (
            "Token Graph de la app confiable, CADUCADO",
            {
                "aud": "https://graph.microsoft.com",
                "appid": AZURE_ADFS_CLIENT_ID,
                "oid": identidad["aad_object_id"],
                "exp": now - 60,
                "tid": identidad["tenant_id"],
            },
        ),
        (
            "Token Graph de la app confiable, vigente",
            {
                "aud": "https://graph.microsoft.com",
                "appid": AZURE_ADFS_CLIENT_ID,
                "oid": identidad["aad_object_id"],
                "exp": now + 3600,
                "tid": identidad["tenant_id"],
                "scp": "User.Read Mail.Read",
            },
        ),
    ]

    print("\n[REAL] AzureAuth._verify_access_token() por caso:")
    for titulo, claims in casos:
        token = unsigned_jwt(claims)
        try:
            out = asyncio.run(backend._verify_access_token(token))
            print(f"  PASA   | {titulo}")
            print(f"         | oid={out.get('oid')} scp={out.get('scp')!r}")
        except InvalidAuth as err:
            print(f"  RECHAZA| {titulo}")
            print(f"         | InvalidAuth({err})")

    print("\nOBSERVACION de seguridad (del codigo, azure.py:476-488):")
    print("  en la rama 'access token sin id_token' el fallo de verificacion")
    print("  de firma se TOLERA (solo warning) si aud+appid cuadran. El unico")
    print("  gate real de ese camino es la llamada posterior a Graph /me.")
    print("  -> el token del PoC pasa el verificador local pero moriria en")
    print("     Graph /me; con id_token la verificacion si es completa (JWKS).")

    # Contrato del payload de entrada
    from navigator_auth.backends.exchange import ExchangeRequest

    req = ExchangeRequest(provider="azure", token="<access_token>", id_token=None)
    print(f"\n[REAL] forma del body esperado: {req}")
    print("  POST /api/v1/login  +  X-Auth-Method: TokenExchangeAuth")

    print("\nVEREDICTO CAPA 2: el mecanismo existe y su contrato es exactamente")
    print("  el descrito: token con aud Graph + appid en AZURE_TRUSTED_APPIDS,")
    print("  o id_token con aud = AZURE_ADFS_CLIENT_ID (verificacion fuerte).")


if __name__ == "__main__":
    identidad = capa1_identidad()
    capa2_contrato_exchange(identidad)
    banner("FIN — capas 1 y 2 demostradas sin red ni credenciales")
