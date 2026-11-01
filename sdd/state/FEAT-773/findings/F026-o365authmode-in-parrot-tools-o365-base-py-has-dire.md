---
id: F026
query_id: Q046
type: grep
intent: "O365: O365AuthMode enum values + where delegated tokens are read in the base O365 tool."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-027]
---

# F026 — O365AuthMode in parrot_tools/o365/base.py has DIRECT, OBO, DELEGATED (and CACHED); OBO is auto-selected from _current_pctx; DELEGATED = interactive login, not vault-backed

## Summary

`parrot_tools/o365/base.py`: `class O365AuthMode: DIRECT="direct"; OBO="on_behalf_of"; DELEGATED="delegated"` (:22-26) plus a `CACHED` branch (:180). `default_auth_mode` param (:88). Branches at :155-180 select client-credentials / OBO (needs `user_assertion`) / delegated interactive / cached. At :247-254 the tool reads `self._current_pctx` and switches to OBO when a permission context is present (TASK test `test_o365_permission_context_bridge`).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`
  lines: 22-26
  symbol: `O365AuthMode`
  excerpt: |
    class O365AuthMode:
        DIRECT = "direct"
        OBO = "on_behalf_of"
        DELEGATED = "delegated"
- path: `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`
  lines: 141-180
  symbol: `O365Tool auth branches`
  excerpt: |
    if auth_mode == O365AuthMode.OBO: ... user_assertion required
    elif auth_mode == O365AuthMode.DELEGATED: ... interactive
    elif auth_mode == O365AuthMode.CACHED: ...
- path: `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`
  lines: 247-254
  symbol: `O365Tool pctx bridge`
  excerpt: |
    pctx = getattr(self, "_current_pctx", None)
    ... auth_mode = O365AuthMode.OBO

## Notes

Brainstorm §3 row 'O365AuthMode enum (DIRECT, OBO, DELEGATED)' → EXISTS; its DELEGATED mode is an interactive MSAL login, NOT the vault-backed 3LO path — that is `Office365Toolkit` + `O365OAuthManager` (FC-026/FC-049).
