# TASK-302 — Unit and Integration Tests for Matrix Crew

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: medium
**Effort**: M
**Depends on**: TASK-296, TASK-297, TASK-298, TASK-299, TASK-300, TASK-301
**Parallel**: false
**Parallelism notes**: Tests all prior tasks; must run after all crew modules are complete.

---

## Objective

Create comprehensive unit and integration tests for the Matrix crew modules: config loading, registry operations, mention parsing, coordinator status board, agent wrapper message handling, and transport routing.

## Files to Create/Modify

- `tests/test_matrix_crew.py` — new test file

## Implementation Details

### Unit Tests

1. **test_matrix_crew_config_from_dict**: Validate `MatrixCrewConfig` with valid data.
2. **test_matrix_crew_config_defaults**: Verify default values (appservice_port=8449, typing=True, etc.).
3. **test_matrix_crew_config_missing_required**: Ensure `ValidationError` on missing `homeserver_url`, `as_token`, etc.
4. **test_matrix_crew_config_from_yaml**: Load a YAML string, verify env var substitution.
5. **test_agent_entry_validation**: Validate `MatrixCrewAgentEntry` fields.

6. **test_mention_parse_plain_text**: `"@analyst what is AAPL?"` → `"analyst"`.
7. **test_mention_parse_pill_html**: Extract from `<a href="https://matrix.to/#/@analyst:server">` → `"analyst"`.
8. **test_mention_parse_no_mention**: `"What is AAPL?"` → `None`.
9. **test_mention_parse_wrong_server**: `"@analyst:other.com"` → `None` when server_name is `"example.com"`.
10. **test_build_pill**: Verify HTML output format.
11. **test_format_reply**: Verify reply formatting.

12. **test_agent_card_status_line_ready**: Verify rendering for ready status.
13. **test_agent_card_status_line_busy**: Verify rendering for busy status with task.
14. **test_agent_card_status_line_offline**: Verify rendering for offline status.

15. **test_registry_register**: Register an agent, verify retrieval.
16. **test_registry_unregister**: Register then unregister, verify gone.
17. **test_registry_update_status**: Register, update to busy, verify status and last_seen.
18. **test_registry_get_by_mxid**: Register, lookup by MXID.
19. **test_registry_all_agents**: Register 3 agents, verify all returned.
20. **test_registry_concurrent_access**: Multiple concurrent status updates don't corrupt state.

### Integration Tests (with mocks)

21. **test_message_routing_dedicated_room**: Mock AppService + BotManager. Send message to dedicated room → correct wrapper receives it.
22. **test_message_routing_mention**: Send `"@analyst question"` to general room → analyst wrapper handles it.
23. **test_message_routing_default_agent**: Send unmentioned message → default agent handles it.
24. **test_message_routing_ignore_self**: Messages from agent MXIDs are ignored.
25. **test_coordinator_refresh**: Mock client.edit_message. Trigger status change → verify edit called with updated board.
26. **test_transport_lifecycle**: `start()` → verify AppService started, agents registered, coordinator pinned. `stop()` → verify cleanup.

### Test Fixtures

```python
@pytest.fixture
def crew_config() -> MatrixCrewConfig:
    """Sample crew config with 2 agents."""
    ...

@pytest.fixture
def mock_appservice():
    """Mock MatrixAppService with bot_intent() returning mock intents."""
    ...

@pytest.fixture
def mock_bot_manager():
    """Mock BotManager.get_bot() returning a stub agent with .ask()."""
    ...
```

## Acceptance Criteria

- [ ] All 26 tests pass.
- [ ] Config validation tests cover valid, invalid, and default cases.
- [ ] Mention parsing covers plain text, pill HTML, no mention, wrong server.
- [ ] Registry tests cover CRUD, concurrent access, and lookup methods.
- [ ] Integration tests verify routing logic with mocked dependencies.
- [ ] No real homeserver connection needed (all external calls mocked).
