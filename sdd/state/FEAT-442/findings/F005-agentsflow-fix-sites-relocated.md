# F005 — S3a fix sites re-verified at NEW line numbers
**Query**: R001, R002, R003 + grep · **Confidence**: high

- Scheduler completion: `flow.py:1881` `ctx.mark_completed(nid, result=event.result)` — still no `response=` → `FlowContext.responses` stays empty. (Was claimed at :1734.)
- Aggregation: `flow.py:955` `_aggregate_result`; at :988-992 passes `response=resp, output=resp` where `resp = results.get(nid)` = the raw `{"response","output","execution_time","prompt"}` envelope. (Was claimed at :841.)
- `core/result.py:619` `build_node_metadata`: AgentResponse branch :654, AIMessage :671, generic branch :680-683 getattr's model/provider/tool_calls off the raw object and **never extracts `usage` at all** → dict envelope yields empty tool_calls/usage/model. Claim confirmed.
- NEW nuance: the checkpoint-resume path `flow.py:1360-1364` DOES pass `response=decoded_responses.get(node_id)` — so the API supports it; only the live scheduler path omits it. `unwrap_node_response()` remains the right shape; there are now potentially THREE call sites to audit (:988, :1881, plus resume seeding at :1360 which is already correct).
