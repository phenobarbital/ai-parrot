# F002 — parrot.interfaces.soap.SOAPClient (CORE) + placement tension
**Type:** read/grep  **Confidence:** high
## Summary
`parrot.interfaces` is the established home for shared interfaces in the CORE pkg:
`packages/ai-parrot/src/parrot/interfaces/{soap.py,http.py}`.
`SOAPClient(ABC)` (soap.py:50) public API near-identical to flowtask's:
start/_get_bearer_token/get_transport/get_settings/get_client/bind_service/run/close/__aenter__/__aexit__.
The current toolkit already imports `from parrot.interfaces.soap import SOAPClient` (tool.py:74).
## Tension
User requested target `parrot_tools/interfaces/workday`, but NO `parrot_tools/interfaces/` dir exists, and the interface convention lives in CORE `parrot.interfaces`. Decision point: parrot_tools vs parrot core.
## Citations
- packages/ai-parrot/src/parrot/interfaces/soap.py:50 class SOAPClient(ABC)
- tool.py:74 from parrot.interfaces.soap import SOAPClient
