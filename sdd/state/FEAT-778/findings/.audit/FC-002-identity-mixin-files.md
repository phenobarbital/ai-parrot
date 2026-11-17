---
id: FC-002
query_id: Q021
type: read
intent: "Read IdentityMixin: how identity is resolved and injected into the prompt."
executed_at: 2026-10-30T16:41:41Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-002 — IdentityMixin already loads a per-agent `identity/` directory of five Markdown files with hot reload

## Summary

`IdentityMixin` (FEAT-321, 324 lines) is opt-in via `enable_identity = True`. It resolves `<agent module dir>/identity`, reads `{role,goal,capabilities,backstory,rationale}.md` via `load_identity()` (mtime-keyed cache), sets them as instance attrs before `AbstractBot.__init__`, snapshots a pristine builder, and on `_build_prompt` re-reads the files and swaps the builder when they changed (carrying over transient layers such as `skill_active`). This is the existing file-based persona precedent: field-per-file rather than a single `persona.md`, and it maps onto the `identity` layer plus `CAPABILITIES_LAYER`.

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

## Notes

Identity dir is derived from the Python module of the class, not from a declarative bundle path — an expert bundle would need `identity_dir` set explicitly. Spec: `sdd/specs/promptbuilder-identity-capability.spec.md`.
