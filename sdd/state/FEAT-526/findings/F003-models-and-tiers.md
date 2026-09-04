# F003 — Model catalog and the Contributor-tier data-training caveat

**Source**: `dev.meta.ai/docs/models.md`

| Model ID | Tier | Context | Modalities in |
|---|---|---|---|
| `muse-spark-1.3` | Standard | 1,048,576 | text, image, video, audio*, PDF |
| `muse-spark-1.3-contributor` | Contributor | 1,048,576 | same |
| `muse-spark-1.2` / `-contributor` | Standard / Contributor | 1,048,576 | same |
| `muse-spark-1.1` | Standard | 1,048,576 | same |

- `muse-spark-1.3` is the vendor-recommended default for new work.
- Other families: `muse-image-1.0` (image out), `muse-voice-transcribe-1.0`
  (ASR, incl. `wss://api.meta.ai/v1/asr/realtime`), `muse-glimmer` (open weights,
  self-hosted — NOT served on Model API).
- `* audio on 1.3 is "not fully supported ... quality may be degraded"`.

**⚠️ Contributor tier**: docs state it *"trades a lower price for permission to
train on your prompts and completions."* The brief nominates
`muse-spark-1.3-contributor` for end-to-end tests.

**Implication**: acceptable for synthetic e2e-test prompts; must NOT become the
library default, and the risk must be documented at the call site.
