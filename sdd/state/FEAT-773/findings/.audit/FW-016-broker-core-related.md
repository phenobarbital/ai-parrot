---
id: FW-016
query_id: Q016
type: wiki_related
intent: "Related edges of the broker core module — who consumes CredentialBroker."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-016 — `broker/core.py` edges: defines `CredentialBroker` (+ `__init__`, `from_config`, `register`, `resolve`) and `CredentialBrokerConfigError`; consumers found by query: `AbstractBot.configure`, `ToolManager`, A2AServer gate, scraping `Authenticate` (TASK-2389), business_automation fixtures, BYOK resolver

## Summary

`wiki_related` on the file returned only its `defines` edges (6 symbols). Consumers surfaced via the FEAT-264/FEAT-602 findings and tests: `tests/unit/test_credential_broker.py`, `tests/auth/test_a2a_credential_var.py` (A2AServer `_try_invoke_with_gate` injects `_CREDENTIAL_VAR`), `parrot_tools/tests/scraping/test_authenticate_broker.py` + TASK-2389 (broker-backed `Authenticate` step, no credentials in plan JSON), `parrot_tools/tests/business_automation/fixtures/broker.py` (`fake_broker`), `handlers/studio/byok.py` (`_UserLLMKeyResolver`, `set_user_llm_key_store`). FEAT-602 F003 states "CredentialBroker + a ready adapter already turn a provider name into an authenticate credential, failing closed". `CredentialBroker.resolve(provider, channel, user_id, **ctx)` fails closed (`KeyError` for unknown provider; `NeedsAuth` on resolver `None`).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: n/a
  symbol: `CredentialBroker.resolve`, `CredentialBroker.from_config`, `CredentialBroker.register`, `CredentialBrokerConfigError`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/auth/broker/core.py#CredentialBroker.resolve
- path: `packages/ai-parrot/tests/unit/test_credential_broker.py`
  lines: n/a
  symbol: TASK-1667 unit tests
  wiki_page_id: file:packages/ai-parrot/tests/unit/test_credential_broker.py (score=0.72)
- path: `tests/auth/test_a2a_credential_var.py`
  lines: n/a
  symbol: `A2AServer._try_invoke_with_gate` injects `_CREDENTIAL_VAR`
  wiki_page_id: file:tests/auth/test_a2a_credential_var.py (score=0.43)
- path: `sdd/tasks/completed/TASK-2389-broker-backed-authenticate.md`
  lines: n/a
  symbol: broker-backed `Authenticate` (scraping)
  wiki_page_id: file:sdd/tasks/completed/TASK-2389-broker-backed-authenticate.md (score=0.38)
- path: `sdd/state/FEAT-602/findings/F003-credential-broker.md`
  lines: n/a
  symbol: F003 CredentialBroker fail-closed adapter
  wiki_page_id: file:sdd/state/FEAT-602/findings/F003-credential-broker.md (score=0.81)

## Notes

`test_a2a_credential_var.py` still references `_try_invoke_with_gate`, which FEAT-264 M6 said it would replace — possible stale test or the gate kept as adapter. `[cross-lane: type=grep, intent=_try_invoke_with_gate|wire_jira_resolver in packages/ai-parrot-server/src/parrot/a2a/server.py to confirm the FEAT-264 replacement landed]`.
