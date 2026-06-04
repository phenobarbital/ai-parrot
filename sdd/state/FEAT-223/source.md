---
kind: inline
jira_key: null
fetched_at: 2026-06-05
summary_oneline: Add Multi-Party Conferencing (cross-pollination + structured confidence vote) to OrchestratorAgent
---

# Source — orchestratoragent-multiparty

El actual `OrchestratorAgent` (`parrot/bots/flows/agents/orchestrator.py`) agrega
agentes y los usa a través de `AgentTool` (expone un Agente como un Tool del
Orchestrator). La pregunta:

¿Podrían los agentes que actúan como tool tener un **Multi-Party Conferencing**?
Es decir, hacer **cross-pollination** de una pregunta:

1. Todos los agentes responden a la MISMA pregunta.
2. Se cruzan entre ellos las respuestas.
3. Se les pide "¿con cuál respuesta te quedas?" — y esto sea un **structured
   output** a cada agente que reciba: la pregunta, las respuestas de los otros
   agentes, y una respuesta que indique con cuál se queda + un **porcentaje de
   confianza**.

¿Cómo podemos implementar algo así en `OrchestratorAgent`?
