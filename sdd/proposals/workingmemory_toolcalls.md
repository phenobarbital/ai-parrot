# Adding WorkingMemory to ToolManager

if a WorkingMemoryToolkit is added to an agent (and is passed by reference to the agent's ToolManager) then results can be automatically registered into the WorkingMemoryToolkit by an ID (maybe {tool name}_{turn_id}_{random number})  
And generating an internal document proof of execution.

Something like this:
- Execution Proof voucher
```
{
  "execution_id": "exec_123",
  "tool": "database_query",
  "status": "succeeded",
  "attempt": 1,
  "result": {
    "dataset_id": "wm_sales_456",
    "row_count": 4200000,
    "column_count": 18,
    "schema_ref": "wm_sales_456_schema"
  }
}
```

Proposed Flow:
```
flowchart TD
    P["LLM thinking"] -->|"Subtarea acotada"| S["Modelo pequeño"]
    S -->|"Tool y argumentos"| R["Runtime"]
    R --> T["Tool de consulta"]
    T -->|"Dataset completo"| W["Memoria de trabajo"]
    W -->|"ID registrado"| T
    T -->|"Estado y referencia"| R
    R -->|"Comprobante"| P
    P -->|"Análisis por ID"| A["Tool de análisis"]
    W -->|"Datos"| A
    A -->|"Agregados y evidencia"| P
```

Thinking LLM pass a "Plan" to the small LLM (like needle3 or cloud-based cheap models as haiku), model proposed calls, the runtime executes the code and returns the proof of execution, when all tools are retrieved, those execution vouchers are returned to the master LLM client.

With this approach, any data would stay in the working memory and only the Execution Proof voucher is moving between agents, a tool on any agent (a tool served by WorkingMemoryToolkit) allow agents to retrieve data using the Execution Proof voucher.

My recommendation for ai-parrot would be to first establish a performance-based contract for tool execution, independent of the model. Afterward, I would evaluate a small-scale executor by measuring argument accuracy, retries, latency, and the number of "thinking" interventions avoided.
