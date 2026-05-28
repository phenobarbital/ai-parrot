---
id: F002
query_id: Q002
type: read
intent: Identificar la arquitectura de registro (lazy renderers, OutputMode enum)
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F002 — Registry con lazy-loading basado en `OutputMode` (ideal para extracción)

## Summary

`formats/__init__.py` define el `Renderer` Protocol, dos dicts globales
(`RENDERERS`, `_PROMPTS`), el decorador `@register_renderer(mode, prompt)`
para que cada módulo de formato se auto-registre, y `get_renderer(mode)`
que hace lazy `import_module('.<formato>', 'parrot.outputs.formats')`
solo cuando hace falta. Hoy el switch de lazy-load lista 23 formatos
codificados a mano. La arquitectura está ya pensada para registro
desacoplado — extraer renderers a otro paquete sólo requiere reemplazar
el switch hardcoded por descubrimiento vía entry-points o por iteración
sobre módulos en paquetes registrados.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
  lines: 1-31
  excerpt: |
    from ...models.outputs import OutputMode

    class Renderer(Protocol):
        @staticmethod
        def render(data: Any, **kwargs) -> Any: ...

    RENDERERS: Dict[OutputMode, Type[Renderer]] = {}
    _PROMPTS: Dict[OutputMode, str] = {}

    def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
        def decorator(cls):
            RENDERERS[mode] = cls
            if system_prompt:
                _PROMPTS[mode] = system_prompt
            return cls
        return decorator

- path: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
  lines: 33-91
  excerpt: |
    def get_renderer(mode: OutputMode) -> Type[Renderer]:
        if mode not in RENDERERS:
            with contextlib.suppress(ImportError):
                if mode == OutputMode.TERMINAL:
                    import_module('.terminal', 'parrot.outputs.formats')
                elif mode == OutputMode.HTML:
                    import_module('.html', 'parrot.outputs.formats')
                ... (23 ramas, una por OutputMode)
        try: return RENDERERS[mode]
        except KeyError as exc:
            raise ValueError(f"No renderer registered for mode: {mode}") from exc

## Notes

Acoplamiento de `formats/__init__.py` con el core: importa
`OutputMode` desde `parrot.models.outputs`. Eso significa que el nuevo
paquete `ai-parrot-visualizations` debe depender de `ai-parrot` (al
menos del enum). Aceptable porque el enum es estable.

`formatter.py` también importa `from .formats import get_renderer,
get_output_prompt, has_system_prompt` — el orquestador queda en core
y consulta al registry, que se llena dinámicamente desde el paquete
externo cuando se importa.
