"""Verifica cada ancla del Codebase Contract de la spec msteams-user-auth-lane.

Imprime path:linea + conteo de ocurrencias para cada simbolo, y confirma que
las entradas 'Does NOT Exist' realmente no existen. Sin red.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/jesuslara/proyectos/ai-parrot")
VENV = ROOT / ".venv/lib/python3.12/site-packages"

INT = "packages/ai-parrot-integrations/src/parrot/integrations"
CORE = "packages/ai-parrot/src/parrot"
SRV = "packages/ai-parrot-server/src/parrot"

# (etiqueta, path, ancla literal)
ANCHORS = [
    ("_get_user_id", f"{INT}/msteams/commands/jira_commands.py", "def _get_user_id("),
    ("resolve_email", f"{INT}/msteams/commands/knowledge_upload.py", "async def resolve_email("),
    ("TeamsKnowledgeUpload", f"{INT}/msteams/commands/knowledge_upload.py", "class TeamsKnowledgeUpload:"),
    ("TeamsInfo import", f"{INT}/msteams/commands/knowledge_upload.py", "from botbuilder.core.teams import TeamsInfo"),
    ("MSTeamsAgentWrapper", f"{INT}/msteams/wrapper.py", "class MSTeamsAgentWrapper("),
    ("wrapper._is_authorized", f"{INT}/msteams/wrapper.py", "def _is_authorized("),
    ("wrapper.on_message_activity", f"{INT}/msteams/wrapper.py", "async def on_message_activity("),
    ("Router.register", f"{INT}/msteams/commands/__init__.py", "def register("),
    ("Router.try_dispatch", f"{INT}/msteams/commands/__init__.py", "async def try_dispatch("),
    ("register_jira_commands", f"{INT}/msteams/commands/jira_commands.py", "def register_jira_commands("),
    ("MSTeamsAgentConfig", f"{INT}/msteams/models.py", "class MSTeamsAgentConfig"),
    ("NavigatorAuthClient", f"{INT}/telegram/auth.py", "class NavigatorAuthClient:"),
    ("NavigatorAuthClient.login", f"{INT}/telegram/auth.py", "async def login("),
    ("TelegramUserSession", f"{INT}/telegram/auth.py", "class TelegramUserSession:"),
    ("set_authenticated", f"{INT}/telegram/auth.py", "def set_authenticated("),
    ("UserContext", f"{CORE}/auth/context.py", "class UserContext:"),
    ("resolve_user_id", f"{CORE}/auth/session_identity.py", "def resolve_user_id("),
    ("resolve_session_user", f"{CORE}/auth/session_identity.py", "def resolve_session_user("),
    ("post_login", f"{CORE}/bots/abstract.py", "async def post_login("),
    ("clone_for_user", f"{CORE}/bots/abstract.py", "def clone_for_user("),
    ("BFTokenServiceResolver", f"{INT}/msagentsdk/auth.py", "class BFTokenServiceResolver("),
    ("_fetch_token", f"{INT}/msagentsdk/auth.py", "async def _fetch_token("),
    ("obo_scopes wiring", f"{INT}/msagentsdk/wrapper.py", "obo_scopes=config.obo_scopes,"),
    ("IdentityMappingService", f"{SRV}/services/identity_mapping.py", "class IdentityMappingService:"),
    ("_UPSERT_SQL", f"{SRV}/services/identity_mapping.py", "ON CONFLICT (user_id, auth_provider)"),
    ("upsert_identity", f"{SRV}/services/identity_mapping.py", "async def upsert_identity("),
    ("msteams jira callback", f"{INT}/msteams/oauth_callback.py", "def handle_msteams_jira_callback("),
]

VENV_ANCHORS = [
    ("TokenExchangeAuth", "navigator_auth/backends/exchange.py", "class TokenExchangeAuth(BasicAuth):"),
    ("ExchangeRequest", "navigator_auth/backends/exchange.py", "class ExchangeRequest:"),
    ("verify_external_token", "navigator_auth/backends/azure.py", "async def verify_external_token("),
    ("_verify_access_token", "navigator_auth/backends/azure.py", "async def _verify_access_token("),
    ("_AZURE_TRUSTED_APPIDS", "navigator_auth/backends/azure.py", "_AZURE_TRUSTED_APPIDS = frozenset("),
    ("IdentityStore", "navigator_auth/identity/store.py", "class IdentityStore:"),
    ("save_linked_identity", "navigator_auth/identity/store.py", "async def save_linked_identity("),
    ("find_user_by_provider_account", "navigator_auth/identity/store.py", "async def find_user_by_provider_account("),
    ("get_by_provider", "navigator_auth/identity/store.py", "async def get_by_provider("),
    ("UserIdentity model", "navigator_auth/models.py", "class UserIdentity(Model):"),
    ("AUTHENTICATION_BACKENDS", "navigator_auth/conf.py", "AUTHENTICATION_BACKENDS = tuple("),
    ("TOKEN_EXCHANGE_PROVIDERS", "navigator_auth/conf.py", "TOKEN_EXCHANGE_PROVIDERS = ["),
]

# (etiqueta, patron regex, ambito) — DEBEN dar 0 resultados
ABSENT = [
    ("OAuthPrompt en msteams/", r"OAuthPrompt", f"{INT}/msteams"),
    ("get_user_token en msteams/", r"get_user_token", f"{INT}/msteams"),
    ("signin/tokenExchange en msteams/", r"signin/tokenExchange", f"{INT}/msteams"),
    ("OBO en integrations/", r"acquire_token_on_behalf_of", INT),
    ("comando /login en msteams/", r"register\(\s*[\"']login", f"{INT}/msteams"),
    ("MSTeamsUserSession", r"MSTeamsUserSession", "packages"),
    ("llamador de TokenExchangeAuth", r"TokenExchangeAuth", "packages"),
    ("X-Auth-Method TokenExchange", r"X-Auth-Method.*TokenExchange", "packages"),
]


def grep_n(path: Path, anchor: str):
    """(primera linea, conteo) de las lineas que contienen anchor literal."""
    if not path.is_file():
        return None, 0
    hits = [
        i
        for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if anchor in line
    ]
    return (hits[0] if hits else None), len(hits)


def main():
    bad = 0
    print("=" * 78)
    print("ANCLAS EN ai-parrot (repo)")
    print("=" * 78)
    for label, rel, anchor in ANCHORS:
        line, count = grep_n(ROOT / rel, anchor)
        flag = "OK " if count == 1 else ("AMB" if count > 1 else "ERR")
        if count != 1:
            bad += 1
        print(f"  {flag} {label:<28} {rel}:{line}  (x{count})")

    print()
    print("=" * 78)
    print("ANCLAS EN navigator_auth 0.28.7 (.venv, PyPI — NO editable)")
    print("=" * 78)
    for label, rel, anchor in VENV_ANCHORS:
        line, count = grep_n(VENV / rel, anchor)
        flag = "OK " if count == 1 else ("AMB" if count > 1 else "ERR")
        if count != 1:
            bad += 1
        print(f"  {flag} {label:<30} {rel}:{line}  (x{count})")

    print()
    print("=" * 78)
    print("DOES NOT EXIST (deben dar 0)")
    print("=" * 78)
    for label, pattern, scope in ABSENT:
        target = ROOT / scope
        res = subprocess.run(
            ["grep", "-rEl", "--include=*.py", pattern, str(target)],
            capture_output=True,
            text=True,
        )
        files = [f for f in res.stdout.strip().splitlines() if f]
        # Los tests no cuentan como implementacion.
        impl = [f for f in files if "/tests/" not in f]
        if impl:
            print(f"  ERR {label:<34} ENCONTRADO en:")
            for f in impl[:4]:
                print(f"        {Path(f).relative_to(ROOT)}")
            bad += 1
        else:
            extra = f"  (solo en tests: {len(files)})" if files else ""
            print(f"  OK  {label:<34} 0 resultados{extra}")

    print()
    print(f"RESULTADO: {'TODO VERIFICADO' if bad == 0 else f'{bad} entradas a revisar'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
