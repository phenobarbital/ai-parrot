# F013 — Live key verified; real model catalog captured

**Query**: live authenticated call, key from `navconfig.config.get('META_API_KEY')`

- `META_API_KEY` **is set** and reachable via navconfig (`env/.env`).
  `MODEL_API_KEY` is **unset** — confirming the user's naming decision is the
  only one that works in this repo today.
- **Key format note**: the stored key is 48 chars beginning `LLM_` with **zero
  `|` characters**, whereas `docs/authentication.md` shows pipe-delimited
  `LLM|607358788850350|nx9.....LJY`. Verified that navconfig is **not**
  mangling it — the raw `env/.env` bytes and the navconfig value are identical.
  The key authenticates successfully, so the underscore form is valid; the doc
  example is simply not the only shape. **No action needed** — recorded so a
  future reader does not "fix" a working key.

- `GET /v1/models` → **HTTP 200**, 7 models, exactly matching `docs/models.md`:

```
muse-image-1.0
muse-spark-1.1
muse-spark-1.2
muse-spark-1.2-contributor
muse-spark-1.3
muse-spark-1.3-contributor
muse-voice-transcribe-1.0
```

**Implication**: `MetaModel` enum members are ground truth, not transcribed
from docs. Note `muse-spark-1.1` has **no** contributor variant.
