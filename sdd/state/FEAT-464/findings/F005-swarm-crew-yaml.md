# F005: swarm_crew.yaml Configuration

**Query**: read examples/matrix_crew/swarm_crew.yaml
**Source**: examples/matrix_crew/swarm_crew.yaml

## Key Facts

4 agents: researcher (web-researcher), analyst (financial-analyst), writer (report-writer), summarizer (synthesis-agent)

2 channels:
- general (public, answer_policy: swarm, agents: researcher/analyst/writer)
- finance (private, answer_policy: mention, agents: analyst only)

Tunnels: enabled, ttl=120min, max_hops=3, echo=true
Space: disabled
Collaborative: !investigate command, max_concurrent_sessions=3, cooldown=10s, summarizer=summarizer

Points to localhost:8008 (the compose stack).

## Implication for FEAT-464
Config is complete. Sample needs the AGENT DEFINITIONS (system prompts, tools, LLM clients) to match these chatbot_ids.
