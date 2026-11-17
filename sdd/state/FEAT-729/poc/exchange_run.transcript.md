# FEAT-729 — successful exchange run (2026-10-22)

Raw stdout of `poc_exchange.py` for the run that returned `HTTP 200`.
Secrets appear only as `<redactado len=N>`; verified: 0 JWTs, 0 base64 strings over 40 chars.

```

========================================================================
PASO 1 — inspeccion del token recibido (sin verificar firma)
========================================================================
  aud   = https://graph.microsoft.com
  appid = bbc8ff0c-f3f5-4294-a692-f90e17f3782a
  oid   = 4e2aa0ea-56b8-49fe-85cf-05e97d479ba6
  tid   = af176793-abc4-423e-8fab-dfc4e2bf8b9d
  upn   = jlara@trocglobal.com
  scp   = AllSites.Manage AllSites.Read Calendars.ReadWrite email Files.Read.All IMAP.AccessAsUser.All Mail.Read Mail.Read.Shared Mail.ReadBasic Mail.ReadBasic.Shared Mail.ReadWrite Mail.ReadWrite.Shared Mail.Send Mail.Send.Shared MyFiles.Read MyFiles.Write openid People.Read Presence.Read Presence.Read.All profile Sites.Read.All SMTP.Send Tasks.Read User.Read User.ReadBasic.All User.ReadWrite
  exp   = 1792690921 (93s restantes)

========================================================================
PASO 2 — contrato de AZURE_TRUSTED_APPIDS
========================================================================
[32m[DEBUG] 2026-10-22 19:40:30,120 root(conf.py:19) :: ::: STARTING APP: Navigator ::: [0m
USE SSL::  False
[32m[DEBUG] 2026-10-22 19:40:30,120 root(conf.py:295) :: :: Settings Directory: /home/jesuslara/proyectos/ai-parrot/settings[0m
  AZURE_ADFS_CLIENT_ID      = bbc8ff...782a
  appids confiables (antes) = ['bbc8ff...782a']
  audiencias aceptadas      = ['bbc8ff...782a', 'https:....com', '000000...0000']

  >> el appid del token ya esta confiado; sin cambios

========================================================================
PASO 2b — ¿existe ya el usuario en auth.users? (requisito D4)
========================================================================
  OK: jlara@trocglobal.com existe -> user_id=35
  el intercambio podra resolver la fila de auth.users

========================================================================
PASO 3 — app desechable con AzureAuth + TokenExchangeAuth
========================================================================
[32m[DEBUG] 2026-10-22 19:40:30,191 Auth.IdP(__init__.py:62) :: User Model: <class 'navigator_auth.models.User'>[0m
[32m[DEBUG] 2026-10-22 19:40:30,192 root(auth.py:248) :: Auth: Loading Backend AzureAuth[0m
[32m[DEBUG] 2026-10-22 19:40:30,192 root(auth.py:248) :: Auth: Loading Backend TokenExchangeAuth[0m
[32m[DEBUG] 2026-10-22 19:40:30,192 SessionHandler(session.py:40) :: :::: Session Handler Loaded ::::[0m
[94m[NOTICE] 2026-10-22 19:40:30,193 :: :: Initializing Identity Provider ::[0m
[32m[DEBUG] 2026-10-22 19:40:30,193 root(auth.py:658) :: :::: Auth Handler Loaded ::::[0m
  backends cargados: ['AzureAuth', 'TokenExchangeAuth']
  OK: TokenExchangeAuth presente (en :5000 vivo NO lo esta)
[37m[INFO] 2026-10-22 19:40:30,319 numexpr.utils(utils.py:162) :: NumExpr defaulting to 12 threads.[0m
/home/jesuslara/proyectos/ai-parrot/.venv/lib/python3.12/site-packages/pandas/core/computation/expressions.py:22: UserWarning: Pandas requires version '2.11.0' or newer of 'numexpr' (version '2.10.2' currently installed).
  from pandas.core.computation.check import (
[32m[DEBUG] 2026-10-22 19:40:30,711 root(abstract.py:65) :: Starting Auth DB driver=redis On: <Application 0x75a0d0706090>[0m
[32m[DEBUG] 2026-10-22 19:40:30,731 root(abstract.py:65) :: Starting Auth DB driver=pg On: <Application 0x75a0d0706090>[0m
[32m[DEBUG] 2026-10-22 19:40:30,731 navigator.vault(config.py:54) :: Loaded 1 master key version(s): [1][0m
[32m[DEBUG] 2026-10-22 19:40:30,732 navigator.vault(keyring.py:198) :: Vault KeyRing loaded: key ids [1], active v1, write alg aesgcm, naming v1[0m
[37m[INFO] 2026-10-22 19:40:30,760 navigator.vault(migrations.py:57) :: Vault tables ensured.[0m
[37m[INFO] 2026-10-22 19:40:30,767 navigator.identity(migrations.py:57) :: Identity credential columns ensured.[0m

========================================================================
PASO 4 — POST /api/v1/login  (X-Auth-Method: TokenExchangeAuth)
========================================================================
DISCOVERY URL:  https://login.microsoftonline.com/af176793-abc4-423e-8fab-dfc4e2bf8b9d/.well-known/openid-configuration
[33;20m[WARNING] 2026-10-22 19:40:31,148 Auth.AzureAuth(external.py:888) :: azure: JWT rejected: Signature verification failed[0m
[33;20m[WARNING] 2026-10-22 19:40:31,148 Auth.AzureAuth(azure.py:484) :: azure: access-token signature not independently verifiable (weaker path, appid/aud already matched): bad_signature[0m
[32m[DEBUG] 2026-10-22 19:40:31,450 root(external.py:961) :: https://graph.microsoft.com/v1.0/me with response: 200, <ClientResponse(https://graph.microsoft.com/v1.0/me) [200 OK]>
<CIMultiDictProxy('Cache-Control': 'no-cache', 'Transfer-Encoding': 'chunked', 'Content-Type': 'application/json;odata.metadata=minimal;odata.streaming=true;IEEE754Compatible=false;charset=utf-8', 'Content-Encoding': 'gzip', 'Vary': 'Accept-Encoding', 'Strict-Transport-Security': 'max-age=31536000', 'request-id': 'a33ca71d-a72d-476f-a1fe-0fd985fd10e2', 'client-request-id': 'a33ca71d-a72d-476f-a1fe-0fd985fd10e2', 'x-ms-ags-diagnostic': '{"ServerInfo":{"DataCenter":"France Central","Slice":"E","Ring":"5","ScaleUnit":"003","RoleInstance":"PA1PEPF00181A21"}}', 'x-ms-resource-unit': '1', 'OData-Version': '4.0', 'Date': 'Thu, 22 Oct 2026 17:40:31 GMT')>
[0m
[32m[DEBUG] 2026-10-22 19:40:31,452 navigator.vault(config.py:54) :: Loaded 1 master key version(s): [1][0m
[33;20m[WARNING] 2026-10-22 19:40:31,484 Auth.TokenExchangeAuth(exchange.py:192) :: TokenExchange: vault write failed provider=azure user_id=35: Error on get user_identities: Error: Model GET over auth.user_identities: column "identity_id" does not exist, code: 0, code: 0[0m
[37m[INFO] 2026-10-22 19:40:31,485 Auth.TokenExchangeAuth(exchange.py:213) :: TokenExchange: success provider=azure user_id=35 cap=89[0m
[33;20m[WARNING] 2026-10-22 19:40:31,487 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: associate_id[0m
[33;20m[WARNING] 2026-10-22 19:40:31,487 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: group_id[0m
[33;20m[WARNING] 2026-10-22 19:40:31,487 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: groups[0m
[33;20m[WARNING] 2026-10-22 19:40:31,488 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: programs[0m
[33;20m[WARNING] 2026-10-22 19:40:31,488 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: birthday[0m
[33;20m[WARNING] 2026-10-22 19:40:31,488 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: start_date[0m
[33;20m[WARNING] 2026-10-22 19:40:31,489 Auth.TokenExchangeAuth(abstract.py:191) :: Error UserData: asking for a non existing attribute: job_code[0m
[32m[DEBUG] 2026-10-22 19:40:31,490 Auth.TokenExchangeAuth(abstract.py:179) :: User Created > jlara@trocglobal.com[0m
[32m[DEBUG] 2026-10-22 19:40:31,494 SessionHandler(redis.py:302) :: :::::: CREATING A NEW SESSION FOR 0e984277460e4e7899cdc7b42b82e188 ::::: [0m
/home/jesuslara/proyectos/ai-parrot/.venv/lib/python3.12/site-packages/jwt/api_jwt.py:149: InsecureKeyLengthWarning: The HMAC key is 6 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
  return self._jws.encode(
/home/jesuslara/proyectos/ai-parrot/.venv/lib/python3.12/site-packages/jwt/api_jwt.py:370: InsecureKeyLengthWarning: The HMAC key is 6 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
  decoded = self.decode_complete(
[32m[DEBUG] 2026-10-22 19:40:31,521 Auth.IdP(__init__.py:494) :: Decoded Token: {'exp': 1792690920.500563, 'iat': 1792690831, 'iss': 'Mobileinsight', 'jti': '46f42ed0-4f0e-4f6c-860c-1f2a372ac1d2', 'user': 35, 'username': 'jlara@trocglobal.com', 'user_id': 35, 'id': 'jlara@trocglobal.com', 'session_id': '0e984277460e4e7899cdc7b42b82e188', 'auth_method': 'basic', 'auth_origin': 'azure', 'external_expires_at': '2026-10-22T17:42:01+00:00'}[0m
[32m[DEBUG] 2026-10-22 19:40:31,526 SessionHandler(redis.py:159) :: :::::: LOAD SESSION FOR 0e984277460e4e7899cdc7b42b82e188 ::::: [0m
[93;1m[ERROR] 2026-10-22 19:40:31,534 navigator.vault(session_vault.py:457) :: Vault secret failed integrity check: user=35 key=account error=UnsupportedFormatError[0m
[37m[INFO] 2026-10-22 19:40:31,538 navigator.vault(session_vault.py:490) :: Vault loaded for user=35: 0 secret(s), 1 integrity failure(s)[0m
[37m[INFO] 2026-10-22 19:40:31,539 navigator.vault(integration.py:95) :: Vault loaded for user 35[0m
  HTTP 200
  cuerpo: {
  "token": "<redactado len=529>",
  "session": {
    "user_id": 35,
    "username": "jlara@trocglobal.com",
    "first_name": "Jesus",
    "last_name": "Lara",
    "email": "jlara@trocglobal.com",
    "enabled": true,
    "superuser": true,
    "last_login": "2026-10-12T20:47:00.686917Z",
    "title": "Consultant",
    "user": "jlara",
    "domain": "trocglobal.com",
    "auth_method": "basic",
    "auth_origin": "azure",
    "external_expires_at": "2026-10-22T17:42:01+00:00",
    "provider_user_id": "4e2aa0ea-56b8-49fe-85cf-05e97d479ba6"
  },
  "username": "jlara@trocglobal.com",
  "id": "jlara@trocglobal.com",
  "user_id": 35,
  "name": "Jesus Lara",
  "email": "jlara@trocglobal.com",
  "upn": "jlara@trocglobal.com",
  "auth_method": "basic",
  "auth_origin": "azure",
  "external_expires_at": "2026-10-22T17:42:01+00:00",
  "provider_user_id": "4e2aa0ea-56b8-49fe-85cf-05e97d479ba6",
  "created": 1792690831.495259,
  "last_visit": 1792690831.495259,
  "session_id": "<redactado len=32>",
  "refresh_token": "<redactado len=43>",
  "expires_in": 1792690920.500563,
  "token_type": "Bearer"
}

========================================================================
PASO 5 — ¿QUE usuario es?  (sesion Navigator viva)
========================================================================
[32m[DEBUG] 2026-10-22 19:40:31,543 Nav.Auth(auth.py:1065) :: :: AUTH MIDDLEWARE ::[0m
[32m[DEBUG] 2026-10-22 19:40:31,544 Auth.IdP(__init__.py:494) :: Decoded Token: {'exp': 1792690920.500563, 'iat': 1792690831, 'iss': 'Mobileinsight', 'jti': '46f42ed0-4f0e-4f6c-860c-1f2a372ac1d2', 'user': 35, 'username': 'jlara@trocglobal.com', 'user_id': 35, 'id': 'jlara@trocglobal.com', 'session_id': '0e984277460e4e7899cdc7b42b82e188', 'auth_method': 'basic', 'auth_origin': 'azure', 'external_expires_at': '2026-10-22T17:42:01+00:00'}[0m
[32m[DEBUG] 2026-10-22 19:40:31,545 SessionHandler(redis.py:159) :: :::::: LOAD SESSION FOR 0e984277460e4e7899cdc7b42b82e188 ::::: [0m
  HTTP 200
  {"nav_user_id": "35", "identity_type": "BasicUser", "username": "jlara@trocglobal.com", "email": "jlara@trocglobal.com", "auth_method": null}

========================================================================
RESULTADO — ARGUMENTO VALIDADO
========================================================================
  token delegado de Azure -> sesion navigator-auth -> nav user id.
  Es el eslabon que faltaba: con el token del usuario de Teams
  (via OAuth connection del Azure Bot) este mismo POST da una
  sesion Navigator identificando al hablante.
[32m[DEBUG] 2026-10-22 19:40:31,550 root(postgres.py:33) ::  === Closing Auth Postgres Connections === [0m
[32m[DEBUG] 2026-10-22 19:40:31,557 root(postgres.py:38) :: Exiting ...[0m
[32m[DEBUG] 2026-10-22 19:40:31,557 root(redis.py:24) ::  === Closing Auth Redis Connections === [0m
```
