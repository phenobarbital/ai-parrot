---
type: Wiki Entity
title: ComputerAgent
id: class:parrot_tools.computer.agent.ComputerAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent configured for vision-based browser automation via computer-use.
relates_to:
- concept: class:parrot.bots.agent.Agent
  rel: extends
---

# ComputerAgent

Defined in [`parrot_tools.computer.agent`](../summaries/mod:parrot_tools.computer.agent.md).

```python
class ComputerAgent(Agent)
```

Agent configured for vision-based browser automation via computer-use.

Uses a Google Gemini computer-use model (default:
``gemini-2.5-computer-use-preview-10-2025``). Composes
:class:`ComputerInteractionToolkit` for all 13 predefined browser
actions plus screenshot, recording, and loop execution. Optionally
composes :class:`~parrot_tools.scraping.toolkit.WebScrapingToolkit`
for hybrid selector-based extraction workflows.

Features:
- Lazy browser start via ``_pre_execute`` in the toolkit.
- Screenshot memory pruning: conversation history is pruned to keep
  only the last ``max_screenshot_turns`` turns that contain screenshots.
- Safety mode (the model can flag an action with
  ``safety_decision.decision == "require_confirmation"``):
  ``"auto"`` — log and auto-acknowledge safety decisions.
  ``"interactive"`` — emit an event; use ``safety_callback`` if provided,
  otherwise fall back to a terminal y/n prompt.
  ``"hitl"`` — route the confirmation through a
  :class:`~parrot.human.manager.HumanInteractionManager` (an APPROVAL
  interaction on ``safety_channel``), falling back to a terminal prompt
  when no manager is available. Approved actions are acknowledged back to
  Gemini with ``safety_acknowledgement="true"``; rejected actions are
  skipped.

Args:
    model: Gemini computer-use model identifier.
    viewport: Browser viewport as ``(width, height)`` in pixels.
    headless: Whether to run the browser in headless mode.
    initial_url: URL to open when the browser first starts.
    safety_mode: ``"auto"``, ``"interactive"``, or ``"hitl"``.
    max_screenshot_turns: Number of turns whose screenshots to retain in
        the conversation history.
    include_scraping: If True, include WebScrapingToolkit tools.
    safety_callback: Optional callable consulted in ``"interactive"`` mode.
    human_manager: Optional :class:`HumanInteractionManager` used in
        ``"hitl"`` mode (defaults to the process-wide manager).
    safety_channel: HITL channel name for ``"hitl"`` mode (default
        ``"cli"`` — prompts in the terminal).
    safety_approvers: Respondent ids for the HITL APPROVAL interaction.
    safety_timeout: Seconds to wait for the human decision.
    **kwargs: Forwarded to Agent.

## Methods

- `async def configure(self, app: Any=None) -> None` — Configure the agent and wire the computer-use safety handler.
- `def agent_tools(self) -> List[AbstractTool]` — Return the tools available to the ComputerAgent.
- `def prune_screenshots(self, history: list) -> list` — Remove old screenshots from conversation history.
- `def handle_safety_decision(self, decision: dict) -> bool` — Process a safety decision from the model.
