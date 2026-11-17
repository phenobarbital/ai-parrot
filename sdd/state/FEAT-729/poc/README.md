# FEAT-729 — proof of concept (2026-10-22)

Evidence behind the spec. Secrets are redacted; no JWT is stored here.

| File | What it proves | How to re-run |
|---|---|---|
| `poc_teams_identity.py` | Layers 1-2: the real repo functions extract the speaker's `aad_object_id` / email, and `AzureAuth._verify_access_token` accepts/rejects the four token shapes. Hermetic, no network. | `python poc_teams_identity.py` |
| `poc_exchange.py` | Layer 3: boots a throwaway aiohttp app with `AzureAuth` + `TokenExchangeAuth` and drives `POST /api/v1/login`. Needs a live delegated Graph token in a file. | `python poc_exchange.py <token-file>` |
| `exchange_run.transcript.md` | The successful run: `HTTP 200`, Navigator session for `user_id=35`, `provider_user_id` == the Entra `oid`, `nav_user_id="35"`. | — |
| `verify_contract.py` | Every §6 anchor and every "Does NOT Exist" entry, with line numbers. | `python verify_contract.py` |

`verify_contract.py` is the one worth re-running when the spec ages: it fails
loudly when an anchor moves or when something listed as absent starts existing.
