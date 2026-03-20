# Feature Specification: Handoff Tool for Integrations Agents

**Feature ID**: FEAT-045
**Date**: 2026-03-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.6.0

---

## 1. Motivation & Business Requirements

> Create a `HandoffTool` mechanism for agents interacting via chat integrations (Telegram, MS Teams, Slack, Matrix). This allows an Agent to pause its current execution to ask a human for required missing information to complete a task, without losing the context of the original request.

### Problem Statement

Currently, when a user asks an Agent to perform an action (e.g., "create a Jira ticket") via a chat integration, but omits required parameters (e.g., the project, component, or issue type), the Agent usually fails or hallucinates parameters. The Agent execution framework does not have a native "pause and ask human" loop that natively integrates with chat platforms. This creates a poor user experience where the user must repeat their request with all parameters included.

### Goals
- Provide a `HandoffTool` (or similar Human-in-the-Loop mechanism) that Agents can invoke when they detect missing required information.
- Suspend the current Agent task/execution.
- Send a prompt to the user via the active chat integration (Telegram, MS Teams, Matrix, Slack) asking for the missing data.
- Wait for the user's response in the chat.
- Resume the Agent's original task using the newly provided information to complete the tool call (e.g., Jira ticket creation).
- Ensure context of the original request is maintained across the conversational turn.

### Non-Goals
- Complex multi-turn form filling beyond simple conversational prompts.
- Web-based handoff UI (this focuses purely on chat integration interactions).
- Fully replacing parameter extraction models—this is a fallback when parameters cannot be deduced.

---

## 2. Architectural Design

### Overview

Implementing a `HandoffTool` requires a Human-in-the-Loop (HITL) pattern natively supported by our `AutonomousOrchestrator` and chat integration transports. 

When the `HandoffTool` is called by an Agent:
1. The tool raises a specific interrupt exception (e.g., `HumanInputRequiredException`) containing the prompt to show the user.
2. The orchestrator catches the exception, suspends the current Execution State, and persists it to a cache/database.
3. The orchestrator forwards the prompt to the chat integration module (Telegram, MS Teams, etc.) to send to the user.
4. When the user replies, the integration routes the message back to the orchestrator.
5. The orchestrator checks if there is a pending suspended execution for this user/chat context.
6. The orchestrator resumes the Agent execution, injecting the user's reply as the result of the `HandoffTool` call.

### Component Diagram

```
┌────────────────────┐      (7) Resumes execution   ┌───────────────────────┐
│                    │ ◀────────────────────────────│                       │
│      Agent         │                              │  AutonomousOrchestrator│
│                    │────(1) Call HandoffTool ────▶│                       │
└────────────────────┘                              └───────┬───────▲───────┘
                                                       (2)  │  (6)  │
                                                      Pause │ Resume│
┌────────────────────┐                              ┌───────▼───────┴───────┐
│   Execution State  │                              │      State Cache      │
│  (Pending Tools)   │◀──────── (3) Store/Load ────▶│   (Redis/DB)          │
└────────────────────┘                              └───────────────────────┘
                                                            │       ▲
                                                        (4) │       │ (5)
                                                      Ask   │       │ Reply
                                                            ▼       │
                                                    ┌───────────────────────┐
                                                    │   Chat Integration    │
                                                    │ (Telegram/Matrix/etc) │
                                                    └───────────────────────┘
```

---

## 3. Detailed Module Design

### 3.1 `parrot/core/tools/handoff.py` — HandoffTool
A tool registered to the Agent that exposes the capability to ask the human for clarification.
- **Input schema**: `prompt` (The question to ask the user, explicitly stating what info is missing).
- **Behavior**: Raises a `HumanInteractionInterrupt` with the prompt.

### 3.2 `parrot/autonomous/orchestrator.py` — Orchestrator Updates
- Needs logic inside the `execute_agent` / `step` loop to catch `HumanInteractionInterrupt`.
- Pauses the execution loop.
- Exits returning a special `requires_action` state along with the prompt.
- Needs an entry point to `resume_agent(session_id, user_input)` that restores memory, tool call state, and injects the user's answer so the LLM knows it received the human's response.

### 3.3 `parrot/integrations/core/state.py` — Integration State Management
- A session manager for chat integrations that tracks if a user is currently in an active "Handoff" state.
- If true, the next message sent by the user in that chat is not treated as a brand new task, but rather routed back to the orchestrator via `resume_agent`.

---

## 4. Integration Points

### 4.1 Chat Transports
- **Telegram/Matrix/MS Teams/Slack**: Current message handlers need to check the session state before dispatching a generic `ask` event. If a session is suspended, the handler must feed the text to the waiting execution.

### 4.2 BotManager
- Must be able to manage agent sessions across multiple conversational turns to retain short-term memory of the suspended task.

---

## 5. Configuration & Dependencies

- **Dependencies**: No new external dependencies. Relies on existing state management (e.g., Redis).
- **Environment Context**: Relies on robust `user_id` or `chat_id` mapping to uniquely identify suspended sessions so replies are correctly correlated.

---

## 6. Acceptance Criteria

1. An Agent equipped with `HandoffTool` and a generic "JiraTool" can successfully pause execution to ask for a missing Jira project key.
2. The user sees the question in Telegram (or Matrix/MS Teams).
3. The user answers "Project is PROJ".
4. The Agent resumes and successfully creates the ticket in Jira using "PROJ".
5. The conversation history remains coherent (the LLM remembers the initial request).
6. Multi-user concurrency: Multiple users can be in handoff states simultaneously across different chat platforms without state leaking.

---

## 7. Testing Strategy

- **Unit Tests**:
  - `test_handoff_tool_raises_interrupt`: Verify the tool behaves correctly.
  - `test_orchestrator_pause_resume`: Mock the LLM and pass a simulated interrupt, then provide a mocked user response and verify the orchestrator continues.
- **Integration Tests**:
  - `test_telegram_handoff_flow`: Set up a dummy Telegram client in testing to verify message dispatching respects the pending state.
  - `test_session_timeout`: If a user doesn't reply in X minutes, the pending handoff task should gracefully expire.

---

## 8. Worktree Strategy

- **Isolation**: Work across `parrot/core/tools/`, `parrot/autonomous/`, and `parrot/integrations/`. 
- Since it touches core orchestration, an isolated branch/worktree (`feature/handoff-tool`) is highly recommended to prevent breaking standard single-turn operations during development.

---

## 9. Example Usage

```python
# System prompt given to Agent:
# "You are a Jira Assistant. If the user asks to create an issue but does not provide a Project ID, use the HandoffTool to ask them for it."

# User (Telegram):
# > "Create a bug ticket saying the login is broken."

# Agent (thinking):
# > Missing Project ID.
# > Action: Call HandoffTool(prompt="I can create that bug ticket for you, but I need to know which Jira Project ID to put it in. Could you provide the project key?")

# User (Telegram) receives message:
# < "I can create that bug ticket for you, but I need to know which Jira Project ID to put it in. Could you provide the project key?"

# User (Telegram) replies:
# > "NAV"

# Agent (resuming):
# > Action: Call CreateJiraIssue(project="NAV", summary="Login is broken", type="Bug")
# > Response: "Ticket NAV-123 created successfully!"
```

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Agent hallucinates rather than using the tool | Task fail | Strong system prompts and tool descriptions emphasizing "DO NOT GUESS parameters, ALWAYS use HandoffTool if missing". |
| User replies with an unrelated command instead of answering | UX confusion | Implement intent detection on the response, or enforce a strict state machine with an option to "cancel" the previous task. |
| Session memory leaks | Server stability | Implement strict TTL (e.g., 10 minutes) on suspended execution states in Redis. |
