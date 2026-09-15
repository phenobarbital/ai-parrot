---
kind: inline
jira_key: null
fetched_at: 2026-09-15T00:00:00Z
summary_oneline: Refactor QSSourceTool into a tenant-scoped QuerysourceToolkit that explains, lists, inspects and executes query-slugs and MultiQuery pipelines.
---

# Source (inline, verbatim)

Slug requested by user: `querysource-toolkit-refactor`

Querysource (../querysource y https://github.com/phenobarbital/querysource) es una libreria que permite registrar en una tabla en postgres (public.queries) queries parametrizables a diferentes bases de datos, los queries pueden tener placeholders que son usados para filtrar e interactuar y construir un query dinámico, es una librería bastante establecida con muchos años en la compañía y usamos su versión "RESTful API" para alimentar métricas de diferentes clientes, necesitamos actualizar el Tool que actualmente invoca el componente interno QS() de Querysource para darle a un agente la capacidad de:

1. entender el dialecto de filtrado JSON de querysource
2. invocar query-slugs (como llamamos a los queries con nombre: ejemplo: epson_field_activity) con distintas condiciones de filtrado requeridas por el usuario: (ejemplo: filtrar epson_field_activity con "conditions": {"firstdate": "2026-08-09", "lastdate": "2026-08-15"}) permitiéndole al LLM entender toda los argumentos y parámetros que soporta el componente `QS()`, ya hay un componente pero tiene precisamente ese lack de no explicarle con suficiente exactitud cómo funciona QuerySource,

pero es además recientemente incorporamos "MultiQuery", es un JSON pipeline que describe una serie de operaciones sobre los datos extraídos (hay una API para listar los componentes soportados por multi-query (/api/v3/qs/components: esta es la API REST, pero revisando el codebase de esa API declarada en Querysource, encontrarás la librería Querysource que se invoca), un ejemplo de componente:

```json
{
    "name": "Concat",
    "category": "Operators",
    "description": "Concatenate two or more DataFrames into a single DataFrame.",
    "usage": "Use in a MultiQuery pipeline to append rows from multiple DataFrames that share the same schema, equivalent to SQL UNION ALL.",
    "attributes": [],
    "json_schema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": "Concat",
        "properties": {},
        "required": []
    },
    "example": "{\n    \"Concat\": {}\n}",
    "icon": "git-merge"
}
```

y el JSON pipeline tiene una forma como esta:

```json
{
  "queries": {
    "pokemon_all_fso_odoo": {"slug": "pokemon_all_fso_odoo_new"},
    "pokemon_warehouses_kiosks": {"slug": "pokemon_warehouses_kiosk_all_fso"},
    "node_1789431043582_1d32g": {"query": "select * from hisense.stores", "driver": "pg"}
  },
  "Join": [
    {
      "type": "left",
      "left": "pokemon_all_fso_odoo",
      "right": "pokemon_warehouses_kiosks",
      "using": ["warehouse_alias", "kiosk_name"],
      "args": {"validate": "many_to_one"}
    }
  ],
  "Output": [
    {
      "tableOutput": {
        "flavor": "postgresql",
        "tablename": "all_fso_odoo_new",
        "schema": "pokemon",
        "pk": ["warehouse_alias", "name_fso", "product_sku"]
      }
    }
  ]
}
```

por lo que debemos hacer un refactor del current QSSourceTool y convertirlo en un Toolkit (QuerysourceToolkit) que:

1. permita al LLM "consultar" qué query invoca un query-slug
2. permitir que ejecute un query-slug con las condiciones indicadas por el usuario transformadas en el payload que espera `QS()`
3. permitir listar los query-slugs existentes
4. listar los componentes soportados por multi-query
5. invocar multi-queries
6. usar la API de MultiQuery para que el propio LLM pueda crear multi-queries.

Todas estas tools del Toolkit deberían poder restringirse por tenant, todos los queries en "public.queries" tienen un atributo "program_slug" que hace alusión al "tenant" o cliente, yo pudiera permitir que este LLM solamente pueda ejecutar o registrar slugs a nombre del tenant Pokemon, por ejemplo.
