---
id: F002
query_id: Q021
type: read
intent: "Read IdentityMixin: how identity is resolved and injected into the prompt."
executed_at: 2026-10-30T16:41:41Z
duration_ms: 900
parent_id: null
depth: 0
merged_from: [FC-002-identity-mixin-files, FW-002-identity-capability-spec]
---

# F002 — IdentityMixin already loads a per-agent `identity/` directory of five Markdown files with hot reload

## Summary

*[FC-002-identity-mixin-files]* `IdentityMixin` (FEAT-321, 324 lines) is opt-in via `enable_identity = True`. It resolves `<agent module dir>/identity`, reads `{role,goal,capabilities,backstory,rationale}.md` via `load_identity()` (mtime-keyed cache), sets them as instance attrs before `AbstractBot.__init__`, snapshots a pristine builder, and on `_build_prompt` re-reads the files and swaps the builder when they changed (carrying over transient layers such as `skill_active`). This is the existing file-based persona precedent: field-per-file rather than a single `persona.md`, and it maps onto the `identity` layer plus `CAPABILITIES_LAYER`.

*[FW-002-identity-capability-spec]* Spec FEAT-321 (approved) defines `load_identity(directory) -> IdentityFields` reading five per-field Markdown files (`role.md`, `goal.md`, `capabilities.md`, `backstory.md`, `rationale.md`), a `CAPABILITIES_LAYER` at priority 11, an `"identity"` preset, and `IdentityMixin` (opt-in `enable_identity`, `identity_dir`) that injects fields pre-`super().__init__`, clones the builder pristine, and hot-reloads via an `_build_prompt` override (mtime cache). Resolution precedence: kwarg > file > class attr > package default. The mixin wiring mirrors `SkillRegistryMixin`/`EpisodicMemoryMixin`: a flag + explicit `async _configure_*()` call after `super().configure()`. A single sectioned `persona.md` was explicitly REJECTED in that brainstorm (Options A/C/D) in favour of per-field files.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/mixins/identity.py`
  lines: 40-60
  symbol: `IdentityMixin`
  excerpt: |
    class IdentityMixin:
        enable_identity: bool = False
        identity_dir: Union[str, Path, None] = None
        _identity_fields: Optional[IdentityFields] = None
        _identity_pristine: Optional[PromptBuilder] = None

- path: `packages/ai-parrot/src/parrot/bots/mixins/identity.py`
  lines: 65-80
  symbol: `IdentityMixin.__init__`
  excerpt: |
    directory = self._resolve_identity_dir()
    fields = load_identity(directory)
    for name, value in fields.as_kwargs().items():
        setattr(self, name, value)

- path: `packages/ai-parrot/src/parrot/bots/mixins/identity.py`
  lines: 119-128
  symbol: `IdentityMixin._resolve_identity_dir`
  excerpt: |
    return Path(inspect.getfile(type(self))).parent / "identity"

- path: `packages/ai-parrot/src/parrot/bots/mixins/identity.py`
  lines: 202-260
  symbol: `IdentityMixin._build_prompt / _reload_identity`
  excerpt: |
    fields = load_identity(directory)
    if fields != self._identity_fields: self._reload_identity(fields)
    ... carry_over = set(old_builder.layer_names) - set(fresh.layer_names)

- path: `packages/ai-parrot/src/parrot/bots/prompts/identity.py`
  lines: 27-40
  symbol: `IDENTITY_FILES / IdentityFields`
  excerpt: |
    IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities", "backstory", "rationale")
    class IdentityFields(BaseModel):
        role: Optional[str] ... rationale: Optional[str]

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

*[FC-002-identity-mixin-files]* Identity dir is derived from the Python module of the class, not from a declarative bundle path — an expert bundle would need `identity_dir` set explicitly. Spec: `sdd/specs/promptbuilder-identity-capability.spec.md`.

*[FW-002-identity-capability-spec]* Direct tension with the source: the brainstorm proposes a single `persona.md` with four fixed sections (Core Responsibilities / Collaboration / Memory Focus / Key Principles) — FEAT-321 rejected the "sectioned single-file identity" shape. An ExpertManifest could either reuse the `identity/` five-file layout or add a parser for the AI-DLC four-section persona; both plug into the same `_configure_identity`/pristine-clone seam.
[cross-lane: type=read, intent=verify IdentityMixin._build_prompt hot-reload and pristine clone in bots/mixins/identity.py]
