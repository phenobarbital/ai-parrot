---
id: F002
query_id: Q011
type: grep
intent: "Inventory every by-name reference to the 2.5 enum members (deleting a member referenced by name is an import-time AttributeError)."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 600
parent_id: null
depth: 0
---

# F002 — GEMINI_2_5_FLASH / GEMINI_2_5_PRO / GEMINI_2_5_FLASH_TTS are load-bearing by name in 3 src files and 2 test files

## Summary

Outside the catalogue itself, `GoogleModel.GEMINI_2_5_FLASH` is referenced by name 16 times across `client.py` (8 sites, as the fallback in batch/embedding/generation helpers and a method default), `analysis.py` (6 method defaults) and `generation.py` (1 method default). `GEMINI_2_5_PRO` is a method default once in `analysis.py`; `GEMINI_2_5_FLASH_TTS` once in `generation.py`. Tests reference `GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH` and `GEMINI_COMPUTER_USE` by name. No reference to these names exists in core `ai-parrot`, `-server`, `-tools`, `-loaders`, `-embeddings` src. Deleting the members without touching these sites is an `AttributeError` at import of `client.py`.

**Merged from F002 (wiki lane):** Wiki page `file:sdd/state/FEAT-688/findings/F010-members-referenced-by-name.md` (sweep dated 2026-10-15 over `ai-parrot-client-google/src`, `ai-parrot-server/src`, `ai-parrot/src`). Twelve `GoogleModel.<MEMBER>` name references exist; among them three 2.5 members: `GEMINI_2_5_FLASH`, `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO`. Deleting any of these is an `AttributeError` at import time, so every call site must be edited in the same commit. The client's own defaults (`_default_model`, `_default_reformat_model`) point at `GEMINI_FLASH_LATEST` / `GEMINI_3_5_FLASH`, not at 2.5. The sweep is three weeks old — a fresh grep is required before deletion.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 3370-3370, 4253-4253, 4792-4792, 4935-4935, 5227-5227, 5330-5330, 5636-5636
  symbol: `GoogleGenAIClient` (fallback chains)
  excerpt: |
    model = self.model or GoogleModel.GEMINI_2_5_FLASH.value                       # 3370, 5330
    self.model or GoogleModel.GEMINI_2_5_FLASH.value                               # 4253
    model = req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value   # 4792, 5227
    batch_model = first_req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value  # 4935
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,                  # 5636

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 64-64, 139-139, 631-631, 815-815, 1075-1075, 1130-1130, 1185-1185
  symbol: (method defaults)
  excerpt: |
    model: Union[GoogleModel, str] = GoogleModel.GEMINI_2_5_FLASH,   # 64,139,631,1075,1130,1185
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_PRO,     # 815

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`
  lines: 405-405, 572-572, 2321-2321
  symbol: (method defaults)
  excerpt: |
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,        # 405
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,    # 572

- path: `packages/ai-parrot/tests/clients/test_google_models.py`
  lines: 11-26
  symbol: (catalogue assertions)
  excerpt: |
    assert "GEMINI_COMPUTER_USE" in GoogleModel.__members__
    assert GoogleModel.__members__["GEMINI_COMPUTER_USE"].value == ("gemini-2.5-computer-use-preview-10-2025")
    assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"
    assert GoogleModel.GEMINI_2_5_FLASH.value == "gemini-2.5-flash"

- path: `packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py`
  lines: 48-100
  symbol: (lifecycle tests)
  excerpt: |
    instance = GoogleGenAIClient(api_key="fake_key", model=GoogleModel.GEMINI_2_5_FLASH.value)
    ... model=GoogleModel.GEMINI_2_5_PRO.value ...

<!-- merged from F002 -->
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-73
  symbol: members referenced by name across src/
  excerpt: |
    GoogleModel.GEMINI_2_5_FLASH        GoogleModel.GEMINI_3_1_FLASH_IMAGE
    GoogleModel.GEMINI_2_5_FLASH_TTS    GoogleModel.GEMINI_3_5_FLASH
    GoogleModel.GEMINI_2_5_PRO          GoogleModel.GEMINI_3_FLASH_PREVIEW   <-- alias of gemini-3.5-flash
    GoogleModel.GEMINI_FLASH_LATEST     GoogleModel.IMAGEN_3 / IMAGEN_4
    GoogleModel.VEO_3_1 / _FAST / _LITE

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 127, 166-172
  symbol: `_default_model`, `_default_reformat_model`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py`
  lines: 34
  symbol: `_default_model`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value

## Notes

- Note the contrast with `client.py:130` (`_default_model = GoogleModel.GEMINI_FLASH_LATEST.value`, see F004): the class-level default is already 2.5-free, but seven *secondary* fallback chains still pin `GEMINI_2_5_FLASH`.

[merged-from: F002] - F010 lists the members but not the file:line of each 2.5 reference; the codebase lane's Q011 grep must produce them.
- [cross-lane: type=grep, intent=locate the exact call sites of GoogleModel.GEMINI_2_5_FLASH / GEMINI_2_5_PRO / GEMINI_2_5_FLASH_TTS (and the parrot_tools / loaders / pipelines trees, which F010 did not sweep)]
- [citation-check: verified] analysis.py:64,139,631,1075,1130,1185 / generation.py:405 / analysis.py:815 — probe anchors c18/c19 carried an inline '# lines' annotation (sheet artifact); re-grepped at HEAD c63e0798b3, all eight sites present.
