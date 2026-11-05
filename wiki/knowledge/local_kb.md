# Local Knowledge Base

## 🔍 How It Works

1. During `configure()`, it searches `AGENTS_DIR/<agent_name>/kb/*.md`
2. The files are loaded and chunked intelligently
3. They are vectorized with FAISS and stored in a cache (`.kb_cache.faiss`)
4. On subsequent loads, the cache is used (very fast)
5. It detects file changes and reloads automatically
6. In `_build_context()`, it searches for relevant chunks and injects them into the prompt

The context is formatted as:
```
## RevenueAnalyst_local Knowledge Base:

### From database_queries.md:
[relevant KB content]

### From prophet_forecasting.md:
[relevant KB content]
