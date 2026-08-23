# F007 — FlowDefinition still has no tenant field; models are now CLOSED
**Query**: G003 + F001 commits · **Confidence**: high

- `flow/definition.py`: grep 'tenant' → no matches. Claim holds (CrewDefinition has it, FlowDefinition doesn't).
- NEW constraint: cda45e33a "close the FlowDefinition models and tag the action union" + 60811a57b "keep already-stored crews loadable under extra=forbid" — definition models now reject unknown fields, and there is a live concern about already-stored definitions. Adding `tenant` (and wiring `enable_execution_memory`) must account for stored-definition compatibility (catalog bundles, saved crews).
