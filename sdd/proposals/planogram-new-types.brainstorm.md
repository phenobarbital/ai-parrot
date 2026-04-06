# Brainstorm: Planogram New Types

**Date**: 2026-04-06
**Author**: Antigravity
**Status**: exploration 
**Recommended Option**: A

---

## Problem Statement

Actualmente el módulo de `planogram_compliance` en `ai-parrot-pipelines` solo tiene implementados dos tipos (composables) base: `graphic_panel_display` y `product_on_shelves`.
Sin embargo, existen dos formatos físicos adicionales que necesitamos validar en tiendas:
1. **Product Counter (`product_counter`)**: Consiste en un producto único exhibido en un mostrador con material promocional de fondo y una etiqueta informativa que lo describe.
2. **Endcap No Shelves Promotional (`endcap_no_shelves_promotional`)**: Consiste en un endcap sin estantes físicos, que destaca por tener un panel superior retro-iluminado (que debe estar encendido) con la marca (ej. "Hello Savings", "EPSON") y un afiche adicional en la parte inferior.

## Constraints & Requirements

- Debe integrarse de manera componible (composable) con el flujo existente y extender de `AbstractPlanogramType`.
- **Product Counter**: La etiqueta puede estar a la derecha u otro lado, basta con detectarla junto con el producto y el material promocional.
- **Endcap No Shelves**: El ROI debe demarcar el exhibidor completo, tomando el panel promocional superior y expandiendo hacia abajo. Se debe validar de forma cualitativa con el LLM si el backlit está encendido o apagado. *No* se buscan productos físicos aquí.
- Generar scripts de python de ejemplo que incluyan los strings de JSON con los `planogramConfig` completos listos para insertarse en la tabla `troc.planograms_configurations` de PostgreSQL.

---

## Options Explored

### Option A: Subclases Especializadas (Reutilizando Base Existente)

Crear las clases `ProductCounter` y `EndcapNoShelvesPromotional` heredando de `AbstractPlanogramType` o composables cercanos (como `GraphicPanelDisplay`) según el nivel de reusabilidad, pero con prompts y logicas particulares predecibles.

✅ **Pros:**
- Reutilizamos funciones utilitarias (como el LLM prompt pipeline).
- Para el counter, adaptamos búsqueda de la etiqueta a nivel macro; para el endcap, reusamos el chequeo de iluminación.

❌ **Cons:**
- Dependencia leve a las implementaciones base.

📊 **Effort:** Low 

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot` | Base Pipeline | |

🔗 **Existing Code to Reuse:**
- `src/parrot_pipelines/planogram/types/graphic_panel_display.py` — Se reusará su logica de chequeo "encendido/apagado" de backlits.
- `src/parrot_pipelines/table.sql` — Inserciones en BD.

---

### Option B: Implementación Independiente por Completo (Duplicación Sana)

Crear ambas clases heredando estrictamente de `AbstractPlanogramType` copiando solo lo mínimo necesario, implementando `compute_roi`, `detect_objects_roi`, `detect_objects` independientemente.

✅ **Pros:**
- Los nuevos tipos de planogramas son 100% aislados a modificaciones (ej. refactors) a los antiguos planogramas.

❌ **Cons:**
- Duplicación de código boilerplate de llamadas al cliente de GEMINI para ROI y objetos.

📊 **Effort:** Medium

---

### Option C: Configuraciones JSON sobre Clases Existentes (Sin nuevas clases en Python)

Ajustar el script JSON para obligar a `GraphicPanelDisplay` a mapearse a un `endcap` promocional y `ProductOnShelves` a un counter.

✅ **Pros:**
- Cero código en la pipeline de Python, solo se crean datos de BD.

❌ **Cons:**
- No escala si los requisitos visuales (validación cualitativa estricta) para el counter/endcap difieren de los flujos pre-fabricados genéricos.
- La petición requiere explicitamente la definición de "planogram types" como clases (composables).

📊 **Effort:** Low

---

## Recommendation

**Option A** is recommended because:
Permite agregar de manera explícita las clases `ProductCounter` y `EndcapNoShelvesPromotional` en `src/parrot_pipelines/planogram/types/`, dándoles un tipo identificable en la base de datos (mediante la enumeración de planogram types) adaptando comportamientos específicos de bounding boxes sin ensuciar el código global de `GraphicPanelDisplay` o `ProductOnShelves`. Al ser subclases, mantenemos herencia lógica reduciendo duplicación de boilerplate.

---

## Feature Description

### User-Facing Behavior
El usuario del sistema (ej. agentes de QC o reportabilidad) al correr la detección enviará como parámetro de configuración uno de los dos nuevos planogram types: `product_counter` o `endcap_no_shelves_promotional`. Obtendrán ComplianceResults exactos sobre "Backlit encendido" y "presencia de etiqueta".

### Internal Behavior
- **`product_counter`**: Su objeto instanciado buscará un ROI general, luego detectará el *producto base*, un *promotional background*, y un *information label*. La validación iterará sobre estas presencias para el puntaje final, ignorando estantes o grillas.
- **`endcap_no_shelves_promotional`**: Buscará aislar el objeto identificando el "promotional panel" encendido utilizando los LLMs y luego el afiche base asumiendo un offset extendido hacia abajo.

### Edge Cases & Error Handling
- Si no detecta la etiqueta en el product counter, el status debería ser penalizado pero no anular el producto per-se si el objeto existe.
- Si hay mucha luz ambiental y el LLM se confunde con el panel "Backlit" de Epson, el workflow implementaría la lógica existente de preguntarle si el brillo emana "desde adentro" de la caja promocional.

---

## Capabilities

### New Capabilities
- `planogram-type-product-counter`: Planograma especializado para detectar producto con afiche e info de validación sobre mostrador.
- `planogram-type-endcap-promotional`: Planograma sin niveles que verifica backlits y afiches inferiores para branding general en pasillos.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_pipelines/planogram/types/` | Add | Dos nuevos archivos python `product_counter.py` y `endcap_no_shelves_promotional.py` |
| `parrot_pipelines/planogram/plan.py` | Modifies | Add dynamic imports and type mapping string a las nuevas clases |

---

## Code Context

### User-Provided Code
N/A

### Verified Codebase References

#### Classes & Signatures
```python
# From src/parrot_pipelines/planogram/types/abstract.py:22
class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
        ...
```

```python
# From src/parrot_pipelines/planogram/types/graphic_panel_display.py:39
class GraphicPanelDisplay(AbstractPlanogramType):
    # Has _check_illumination_from_roi method.
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.detections import Detection, BoundingBox, Detections, IdentifiedProduct, ShelfRegion
from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
```

#### Key Attributes & Constants
- `GraphicPanelDisplay._DEFAULT_ILLUMINATION_PENALTY` → `float` (parrot_pipelines/planogram/types/graphic_panel_display.py:33)

### Does NOT Exist (Anti-Hallucination)
- ~~`ProductCounter`~~ — no existe (será creada)
- ~~`EndcapNoShelvesPromotional`~~ — no existe (será creada)

---

## Open Questions

- [ ] Definir los pesos (weights) que tendrá la falta de etiqueta vs la falta del material promocional dentro del product counter. *Owner: SDD Implementer*
