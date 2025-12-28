┌─────────────────────────────────────────────────────────────────────┐
│                        SERVIR (Exponer)                              │
├─────────────────────────────────────────────────────────────────────┤
│  MCP:  MCPServerConfig / ParrotMCPServer                            │
│        → Expone TOOLS de Parrot como MCP servers                    │
│                                                                      │
│  A2A:  A2AServer                                                     │
│        → Expone AGENTES de Parrot como servicios A2A                │
│        → /.well-known/agent.json (discovery para externos)          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       CONSUMIR (Usar)                                │
├─────────────────────────────────────────────────────────────────────┤
│  MCP:  MCPClientMixin en BaseAgent                                  │
│        → Agente Parrot consume MCP tools remotas                    │
│        → Las ve como herramientas                                   │
│                                                                      │
│  A2A:  A2AClientMixin en BaseAgent                                  │
│        → Agente Parrot consume agentes A2A remotos                  │
│        → Los ve como herramientas                                   │
└─────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                         ORQUESTACIÓN EN PARROT                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  AgentCrew (LLM-driven)              A2AProxyRouter (Rule-driven)   │
│  ─────────────────────               ───────────────────────────    │
│  • LLM decide qué agente usar        • Reglas predefinidas          │
│  • Razonamiento complejo             • Matching simple (skill/tag)  │
│  • Puede improvisar                  • Determinístico               │
│  • Mayor latencia + costo            • Latencia mínima, sin costo   │
│  • Agentes LOCALES                   • Agentes REMOTOS (A2A)        │
│                                                                      │
│  Caso: "No sé qué necesito,          Caso: "Sé exactamente a quién  │
│         ayúdame a resolver esto"            preguntar"              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘



# Ejemplo 1: Gateway simple
async def create_gateway():
    # Crear mesh con agentes conocidos
    mesh = A2AMeshDiscovery()
    await mesh.register("http://agent1:8080")
    await mesh.register("http://agent2:8080")
    await mesh.register("http://agent3:8080")
    await mesh.start()

    # Crear router
    router = A2AProxyRouter(mesh, name="APIGateway")

    # Configurar rutas
    router.route_by_skill("data_analysis", "DataAnalyst")
    router.route_by_skill("customer_support", "SupportBot")
    router.route_by_tag("finance", ["FinanceBot1", "FinanceBot2"])  # Load balance
    router.set_default("GeneralAssistant")

    # Exponer como servicio
    app = web.Application()
    router.setup(app)

    return app


# Ejemplo 2: Uso programático (sin HTTP)
async def proxy_request():
    mesh = A2AMeshDiscovery()
    await mesh.register("http://expert-agent:8080")

    router = A2AProxyRouter(mesh)
    router.set_default("ExpertAgent")

    # Passthrough directo - sin LLM!
    task = await router.route_message(
        "¿Cuál es el análisis de ventas Q4?"
    )

    # task.artifacts contiene la respuesta AS-IS del agente remoto
    return task.artifacts[0].parts[0].text


# Ejemplo 3: Router como "facade" de múltiples agentes
async def multi_agent_facade():
    mesh = A2AMeshDiscovery()

    # Registrar varios agentes especializados
    await mesh.register("http://sales-analyst:8080")
    await mesh.register("http://inventory-manager:8080")
    await mesh.register("http://customer-service:8080")

    router = A2AProxyRouter(
        mesh,
        name="BusinessAssistant",
        description="Unified interface for business operations"
    )

    # Routing por regex en el mensaje
    router.route_by_regex(r"ventas|sales|revenue", "SalesAnalyst")
    router.route_by_regex(r"inventario|stock|inventory", "InventoryManager")
    router.route_by_regex(r"cliente|customer|queja", "CustomerService")

    # El router se expone como UN solo agente
    # pero internamente distribuye a los especialistas
    app = web.Application()
    router.setup(app)

    # Desde afuera: GET /.well-known/agent.json
    # Muestra skills agregadas de todos los agentes
```

## Diagrama de arquitectura completa
```
                                CONSUMIDORES EXTERNOS
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────┐
│                     A2AProxyRouter (Gateway)                       │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  /.well-known/agent.json → AgentCard agregado               │  │
│  │  /a2a/message/send → route_message() → passthrough          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                    ┌─────────┴─────────┐                          │
│                    ▼                   ▼                          │
│            ┌──────────────┐    ┌──────────────┐                   │
│            │ RoutingRules │    │ A2AMeshDisc. │                   │
│            │  - by skill  │    │  - health    │                   │
│            │  - by tag    │    │  - discovery │                   │
│            │  - by regex  │    │              │                   │
│            └──────────────┘    └──────────────┘                   │
└───────────────────────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
           ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
           │ A2A Agent 1  │    │ A2A Agent 2  │    │ A2A Agent 3  │
           │ (Parrot)     │    │ (Parrot)     │    │ (Externo)    │
           │              │    │              │    │              │
           │ A2AServer    │    │ A2AServer    │    │   ???        │
           └──────────────┘    └──────────────┘    └──────────────┘

stats = orchestrator.stats
print(f"Success rate: {stats.success_rate:.1%}")
print(f"Avg latency: {stats.avg_latency_ms:.0f}ms")
print(f"Rules used: {stats.rules_used}")
print(f"LLM fallback: {stats.llm_fallback_used}")
```

## Arquitectura Completa
```
┌─────────────────────────────────────────────────────────────────┐
│                      A2AOrchestrator                             │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │  Rules Engine    │  │  LLM Decision    │  │  Execution    │  │
│  │  (A2AProxyRouter)│  │  Engine          │  │  Engine       │  │
│  │                  │  │                  │  │               │  │
│  │  - Skill match   │  │  - Agent select  │  │  - Single     │  │
│  │  - Tag match     │  │  - Strategy pick │  │  - Parallel   │  │
│  │  - Regex match   │  │  - Reasoning     │  │  - Sequential │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬───────┘  │
│           │                     │                    │          │
│           └─────────────────────┼────────────────────┘          │
│                                 ▼                               │
│                        ┌───────────────────┐                    │
│                        │ A2AMeshDiscovery  │                    │
│                        │ (Agent Catalog)   │                    │
│                        └───────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
