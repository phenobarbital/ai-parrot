# FEAT-589 Google paid verification

User authorizes paid Agent calls using google:gemini-3.5-flash.
Scope: evaluation-only provider configuration, Google raw model-version evidence, tests and documentation.
Use existing GoogleGenAIClient and configured fallback gemini-3.1-flash-lite, 16 logical calls for eight paired fixtures, 1024 output tokens per call. No core client edits.
Verify offline behavior before paid calls. Preserve per-arm usage/model evidence and report actual provider routing. Risks: model availability, token truncation, network sandbox, SDK retries beyond logical call budget. No credentials in artifacts.

Completed: provider option, Google credential lookup and provider-version evidence, including actual google_genai tag. Initial 16 paid calls returned usage but lacked retained actual-model evidence; original incomplete report preserved. Separate two-call confirmation exited 0 with raw provider model gemini-3.6-flash for requested gemini-3.5-flash. 18 successful paid logical calls total; no cheap-model routing occurred. Regression/lint checks passed.
