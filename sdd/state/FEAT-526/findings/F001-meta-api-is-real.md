# F001 — Meta Model API endpoint is live and OpenAI-shaped

**Query**: live HTTP probe of `api.meta.ai` / `dev.meta.ai` (external)

- `GET https://api.meta.ai/v1/models` → **HTTP 401**, body:
  `{"error":{"code":"invalid_api_key","message":"Unauthorized","param":null,"type":"authentication_error"}}`
  — this is verbatim OpenAI's error envelope shape (`error.{code,message,param,type}`).
- `https://dev.meta.ai/docs/sdks` → HTTP 200 (client-rendered SPA; raw HTML has no content).
- Machine-readable docs index found at `https://dev.meta.ai/docs/llms.txt` (16.9 KB),
  and every docs page is retrievable as Markdown by appending `.md`
  (e.g. `/docs/models.md`). 15 capability/protocol pages fetched (211 KB total).

**Conclusion**: the platform is real and externally verifiable — not an
assumption carried from the user's brief. Product name: **Meta Model API**;
model family **Muse Spark**.
