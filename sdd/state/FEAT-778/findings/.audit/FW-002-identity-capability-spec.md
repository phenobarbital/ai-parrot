---
id: FW-002
query_id: Q002
type: wiki_page
intent: "Identity capability spec: file-based identity, hot reload, mixin pattern"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-002 — FEAT-321 already ships file-based identity (`identity/*.md` → IdentityFields) with hot reload via `IdentityMixin`; persona-as-files is a solved precedent

## Summary

Spec FEAT-321 (approved) defines `load_identity(directory) -> IdentityFields` reading five per-field Markdown files (`role.md`, `goal.md`, `capabilities.md`, `backstory.md`, `rationale.md`), a `CAPABILITIES_LAYER` at priority 11, an `"identity"` preset, and `IdentityMixin` (opt-in `enable_identity`, `identity_dir`) that injects fields pre-`super().__init__`, clones the builder pristine, and hot-reloads via an `_build_prompt` override (mtime cache). Resolution precedence: kwarg > file > class attr > package default. The mixin wiring mirrors `SkillRegistryMixin`/`EpisodicMemoryMixin`: a flag + explicit `async _configure_*()` call after `super().configure()`. A single sectioned `persona.md` was explicitly REJECTED in that brainstorm (Options A/C/D) in favour of per-field files.

## Citations

- path: `sdd/specs/promptbuilder-identity-capability.spec.md`
  lines: 1-120
  symbol: `FEAT-321 IdentityMixin / load_identity / CAPABILITIES_LAYER`
  wiki_page_id: file:sdd/specs/promptbuilder-identity-capability.spec.md
  score: 0.89
  excerpt: |
    class IdentityMixin:
        enable_identity: bool = False
        identity_dir: Union[str, Path, None] = None
        async def _configure_identity(self) -> None: ...
        def _build_prompt(self, *args, **kwargs): ...   # hot-reload seam
    # "Construct-time-only loading, capabilities-only hot reload, and sectioned
    #  single-file identity were rejected in brainstorm"

- path: `packages/ai-parrot/src/parrot/bots/mixins/identity.py`
  symbol: `IdentityMixin`
  wiki_page_id: file:docs/prompts/identity-capability.md
  score: 1.00
  excerpt: |
    (module exists; see codebase lane read Q021 for line-level detail)

## Notes

Direct tension with the source: the brainstorm proposes a single `persona.md` with four fixed sections (Core Responsibilities / Collaboration / Memory Focus / Key Principles) — FEAT-321 rejected the "sectioned single-file identity" shape. An ExpertManifest could either reuse the `identity/` five-file layout or add a parser for the AI-DLC four-section persona; both plug into the same `_configure_identity`/pristine-clone seam.
[cross-lane: type=read, intent=verify IdentityMixin._build_prompt hot-reload and pristine clone in bots/mixins/identity.py]
