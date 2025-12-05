## 🔍 Cómo funciona

1. Durante `configure()`, se busca `AGENTS_DIR/<agent_name>/kb/*.md`
2. Los archivos se cargan y chunkean inteligentemente
3. Se vectorizan con FAISS y se guardan en cache (`.kb_cache.faiss`)
4. En subsecuentes cargas, usa el cache (muy rápido)
5. Detecta cambios en archivos y recarga automáticamente
6. En `_build_context()`, busca chunks relevantes y los inyecta al prompt

El contexto se formatea como:
```
## RevenueAnalyst_local Knowledge Base:

### From database_queries.md:
[contenido relevante del KB]

### From prophet_forecasting.md:
[contenido relevante del KB]