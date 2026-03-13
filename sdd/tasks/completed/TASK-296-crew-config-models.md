# TASK-296 — Matrix Crew Configuration Models

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: S
**Depends on**: (none)
**Parallel**: true
**Parallelism notes**: Pure data models with no imports from other new crew modules. Can run in parallel with TASK-297 (mention utilities).

---

## Objective

Create the Pydantic configuration models for the Matrix crew: `MatrixCrewAgentEntry` and `MatrixCrewConfig`. These are the foundational data structures that all other crew modules import.

## Files to Create/Modify

- `parrot/integrations/matrix/crew/__init__.py` — create empty package init (will be extended later)
- `parrot/integrations/matrix/crew/config.py` — new file

## Implementation Details

### MatrixCrewAgentEntry (Pydantic BaseModel)

Fields per spec section 3.1:
- `chatbot_id: str` — BotManager lookup key
- `display_name: str` — human-readable name
- `mxid_localpart: str` — localpart for virtual MXID (e.g., "analyst")
- `avatar_url: str | None = None` — mxc:// URL
- `dedicated_room_id: str | None = None` — agent's private room
- `skills: list[str] = []` — skill descriptions for status board
- `tags: list[str] = []` — routing tags
- `file_types: list[str] = []` — accepted file MIME types

### MatrixCrewConfig (Pydantic BaseModel)

Fields per spec section 3.1:
- `homeserver_url: str`
- `server_name: str`
- `as_token: str`
- `hs_token: str`
- `bot_mxid: str`
- `general_room_id: str`
- `agents: dict[str, MatrixCrewAgentEntry]`
- `appservice_port: int = 8449`
- `pinned_registry: bool = True`
- `typing_indicator: bool = True`
- `streaming: bool = True`
- `unaddressed_agent: str | None = None`
- `max_message_length: int = 4096`

### YAML Loading

Add a `@classmethod from_yaml(cls, path: str) -> MatrixCrewConfig` that:
1. Reads the YAML file.
2. Substitutes `${ENV_VAR}` patterns from `os.environ`.
3. Validates via Pydantic.

Reference: `parrot/integrations/telegram/crew/config.py` for the env var substitution pattern.

## Acceptance Criteria

- [ ] `MatrixCrewAgentEntry` and `MatrixCrewConfig` models validate correctly.
- [ ] `from_yaml()` loads a YAML file with env var substitution.
- [ ] Invalid configs (missing required fields, bad types) raise `ValidationError`.
- [ ] `parrot/integrations/matrix/crew/__init__.py` exists as a package.
