# F009 — AbstractClient contract + recent git history

**Query**: Q009/Q015 · **Type**: grep + git_log

`AbstractClient(EventEmitterMixin, ABC)` (`clients/base.py`, 2,527 lines)
abstract methods a NovaClient must implement:
- `get_client()` (base.py:845)
- `ask()` (base.py:1525)
- `ask_stream()` (base.py:1563)
- `resume()` (base.py:1592)
- `invoke()` (base.py:1614)

Git history of nova_sonic.py (last 6 months):
- `e34e59600` feat(bedrock-client-llm): TASK-1748 — NovaSonicClient Experimental Voice Client
- `36bf8c57e` fix: base64 encode/decode audio wire format
- Parent feature: FEAT-302 (bedrock-client-llm spec, Module 7);
  `sdd/specs/bedrock-client-llm.spec.md` is the authoritative design doc.
- `3672eb2f4` "wip: nova model" (HEAD~1, Jul 17 2026): adds `aws_id` kwarg to
  BedrockConverseClient + `nova-2-lite` map entry — the user has already
  started moving toward FEAT-315's credential story.

## Citations
- packages/ai-parrot/src/parrot/clients/base.py:845,1525,1563,1592,1614
- git log nova_sonic.py; git show 3672eb2f4
