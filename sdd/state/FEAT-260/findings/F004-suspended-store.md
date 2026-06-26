# F004 — SuspendedExecutionStore exists; resume trigger is HITL-message, not OAuth (PARTIAL)

**Query**: Q002 (read `human/suspended_store.py`)
**Verdict**: EXISTS, but reuse needs a new trigger — matches brainstorm §8 claim.

- `packages/ai-parrot-server/src/parrot/human/suspended_store.py` — `SuspendedExecution` (Pydantic) + `SuspendedExecutionStore` (Redis, key `hitl:suspended:{interaction_id}`, TTL-aligned, `save/load/delete`).
- Built for FEAT-204 stateless Web HITL SUSPEND: a tool raises `HumanInteractionInterrupt`; handler serialises tool-loop state; later `hitl_response` reloads + calls `agent.resume()` injecting the human's answer as the `ask_human` tool_result.
- `SuspendedExecution` fields: `interaction_id, session_id, user_id, agent_name, tool_call_id, messages, created_at`.

**Implication**: Reusable for credential-suspend, BUT existing resume assumes a **human-approver message on a parrot channel**. The credential-acquisition resume trigger (OAuth callback / form POST correlated by nonce) is genuinely NEW, exactly as brainstorm §5/§8 states. Identity field `user_id` is already first-class — depends on OQ#1 being resolvable.
