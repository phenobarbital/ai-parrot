---
id: F002
query: Q002
type: read
target: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
---

# F002 — Schema Types Verification

**Status**: Confirmed with discrepancies from proposal

## TenantContext(BaseModel)
```
tenant_id: str
arango_db: str
pgvector_schema: str          ← NOT in proposal
ontology: MergedOntology      ← proposal says "Ontology"
```

## MergedOntology(BaseModel) — proposal calls this "Ontology"
```
name: str
version: str
entities: dict[str, EntityDef]
relations: dict[str, RelationDef]
traversal_patterns: dict[str, TraversalPattern]
layers: list[str]
merge_timestamp: datetime
```
Methods: `get_entity_collections() -> list[str]`, `get_edge_collections() -> list[str]`,
`get_vectorizable_fields(entity_name) -> list[str]`, `build_schema_prompt() -> str`

## EntityDef(BaseModel) — proposal calls this "Entity"
```
collection: str | None
source: str | None
key_field: str | None
properties: list[dict[str, PropertyDef]]
vectorize: list[str]
extend: bool
```

## RelationDef(BaseModel) — proposal calls this "Relation"
```
from_entity: str (alias="from")
to_entity: str (alias="to")
edge_collection: str
properties: list[dict[str, PropertyDef]]
discovery: DiscoveryConfig
```

## Key Discrepancies
- `Ontology` → actually `MergedOntology`
- `Entity` → actually `EntityDef`
- `Relation` → actually `RelationDef`
- `TenantContext.pgvector_schema` field exists but not mentioned in proposal
- `MergedOntology` has additional fields: `traversal_patterns`, `layers`, `merge_timestamp`
