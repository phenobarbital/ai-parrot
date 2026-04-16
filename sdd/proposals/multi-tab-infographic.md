# SDD Brainstorm: Multi-Tab Infographic Template + New Component Blocks

**Feature ID:** FEAT-XXX
**Author:** Jesus
**Date:** 2025-04-15
**Status:** Brainstorm
**Scope:** `packages/ai-parrot` → `parrot.models.infographic`, `parrot.models.infographic_templates`, `parrot.outputs.formats.infographic_html`

---

## 1. Motivación y Contexto

### 1.1 Problema actual

El sistema de infografías actual (`InfographicResponse`) define una lista **plana** de bloques ordenados:

```
InfographicResponse
  ├── template: str
  ├── theme: str
  └── blocks: List[InfographicBlock]  ← flat, sin agrupación
```

Esto funciona bien para reportes de una sola "vista" (executive, dashboard, comparison), pero **no soporta** infografías largas y complejas con múltiples secciones navegables como la de "Metodología de implementación de agentes de IA", que tiene:

- **5 tabs** (Conocimientos previos, Tipo de solución, Fases + I/O, Cronograma, QA)
- Cada tab con su propia estructura de bloques independiente
- Bloques que no existen en el sistema actual: accordions, checklists, tablas estilizadas con headers semánticos

### 1.2 Referencia visual

La infografía de referencia (`metodologia_agentes_ia_V1.html`) demuestra un patrón reutilizable:

```
┌─────────────────────────────────────────────────┐
│  Título principal + subtítulo                   │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  │ Tab1 │ │ Tab2 │ │ Tab3 │ │ Tab4 │ │ Tab5 │  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘  │
│  ─────────────────────────────────────────────  │
│  ┌─────────────────────────────────────────┐    │
│  │  Vista activa (bloques del tab)         │    │
│  │  ┌─ accordion ──────────────────────┐   │    │
│  │  │ ▸ Sección colapsable             │   │    │
│  │  │   → contenido HTML interno       │   │    │
│  │  └──────────────────────────────────┘   │    │
│  │  ┌─ styled_table ──────────────────┐   │    │
│  │  │  Header │ Col A │ Col B │ Col C │   │    │
│  │  │  Row 1  │  ...  │  ...  │  ...  │   │    │
│  │  └──────────────────────────────────┘   │    │
│  │  ┌─ checklist ─────────────────────┐   │    │
│  │  │  ☐ Criterio de aceptación 1     │   │    │
│  │  │  ☐ Criterio de aceptación 2     │   │    │
│  │  └──────────────────────────────────┘   │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### 1.3 Objetivo

Diseñar un **template `multi_tab`** que permita al LLM generar infografías con navegación por tabs, donde cada tab contiene su propia secuencia de bloques. Además, introducir **4 nuevos tipos de bloque** que cubren patrones comunes en reportes empresariales.

---

## 2. Análisis de la Arquitectura Actual

### 2.1 Modelo de datos (`infographic.py`)

```python
# Bloques actuales (12 tipos)
BlockType = Enum(
    TITLE, HERO_CARD, SUMMARY, CHART, BULLET_LIST,
    TABLE, IMAGE, QUOTE, CALLOUT, DIVIDER,
    TIMELINE, PROGRESS
)

# Unión discriminada por "type"
InfographicBlock = Union[
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock,
    CalloutBlock, DividerBlock, TimelineBlock, ProgressBlock,
]

# Respuesta: lista plana de bloques
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    blocks: List[InfographicBlock]
    metadata: Optional[Dict]
```

### 2.2 Templates (`infographic_templates.py`)

```python
class BlockSpec(BaseModel):
    block_type: BlockType
    required: bool = True
    description: Optional[str]
    min_items: Optional[int]
    max_items: Optional[int]
    constraints: Optional[Dict[str, str]]

class InfographicTemplate(BaseModel):
    name: str
    description: str
    block_specs: List[BlockSpec]  # ← flat list, sin concepto de tabs
    default_theme: Optional[str]
```

### 2.3 Rendering pipeline (`abstract.py` → `infographic_html.py`)

```
get_infographic(question, template="basic", theme="corporate")
  │
  ├── 1. Resuelve template → to_prompt_instruction()
  ├── 2. Llama ask() con structured_output=InfographicResponse
  ├── 3. Content negotiation:
  │      accept="text/html" → InfographicHTMLRenderer.render_to_html()
  │      accept="application/json" → JSON crudo
  └── 4. Retorna AIMessage con .content = HTML y .structured_output
```

### 2.4 Gaps identificados

| Gap | Descripción |
|-----|-------------|
| **Sin agrupación** | `blocks` es una lista plana; no hay manera de agrupar bloques en secciones/tabs |
| **Sin tab navigation** | El renderer no genera pestañas ni JS para mostrar/ocultar vistas |
| **Sin accordion** | No existe bloque colapsable con contenido HTML rico |
| **Sin checklist** | `BulletListBlock` no soporta checkboxes visuales ni semántica de criterios |
| **Tabla limitada** | `TableBlock` es funcional pero carece de opciones de styling: striped, bordered, highlight row, column groups |
| **Bullet list sin título** | `BulletListBlock` tiene `title` pero no soporta sub-agrupaciones ni styled headers |
| **Template plano** | `InfographicTemplate.block_specs` no puede expresar "Tab A tiene estos bloques, Tab B tiene estos otros" |

---

## 3. Diseño Propuesto

### 3.1 Nuevos Block Types

Se proponen 4 nuevos bloques + 1 bloque contenedor de tab:

```python
class BlockType(str, Enum):
    # ... existentes ...

    # ── Nuevos ──
    TITLED_BULLET_LIST = "titled_bullet_list"   # Bullet list con header estilizado
    STYLED_TABLE = "styled_table"               # Tabla con opciones de estilo
    ACCORDION = "accordion"                     # Secciones colapsables con HTML
    CHECKLIST = "checklist"                      # Lista con checkboxes visuales
    TAB_VIEW = "tab_view"                        # Contenedor de tabs (meta-bloque)
```

#### 3.1.1 `TitledBulletListBlock`

**Propósito:** Lista de bullets agrupada bajo un título con dot-indicator coloreado, como la sección "Conocimientos necesarios" de la referencia.

```python
class BulletItem(BaseModel):
    """Un item dentro de una titled bullet list."""
    text: str = Field(..., description="Texto del item")
    icon: Optional[str] = Field(None, description="Emoji o icono opcional")

class TitledBulletListBlock(BaseModel):
    """Bullet list con un título/header prominente y dot indicators."""
    type: Literal["titled_bullet_list"] = "titled_bullet_list"
    title: str = Field(..., description="Título de la sección")
    items: List[BulletItem] = Field(..., description="Items de la lista")
    color: Optional[str] = Field(
        None,
        description="Color del dot indicator (hex). Hereda del tema si None"
    )
    columns: Optional[int] = Field(
        None,
        ge=1, le=4,
        description="Número de columnas para layout grid (None=single col)"
    )
```

**HTML esperado:**
```html
<div class="titled-bullet-list">
  <div class="titled-bullet-list__header">Fundamentos de IA y LLMs</div>
  <ul class="titled-bullet-list__items">
    <li><span class="dot" style="background:#534AB7;"></span>Qué es un LLM...</li>
    <li><span class="dot" style="background:#534AB7;"></span>Diferencia entre...</li>
  </ul>
</div>
```

#### 3.1.2 `StyledTableBlock`

**Propósito:** Tabla con opciones avanzadas de presentación: headers semánticos, filas destacadas, column groups, estilo striped/bordered.

```python
class TableStyle(str, Enum):
    """Estilos visuales para la tabla."""
    DEFAULT = "default"         # Bordes sutiles
    STRIPED = "striped"         # Filas alternas
    BORDERED = "bordered"       # Bordes completos
    COMPACT = "compact"         # Padding reducido
    COMPARISON = "comparison"   # Primera columna como label, headers con color

class ColumnDef(BaseModel):
    """Definición de columna con opciones de estilo."""
    header: str = Field(..., description="Texto del header")
    width: Optional[str] = Field(None, description="CSS width (e.g., '200px', '30%')")
    align: Optional[Literal["left", "center", "right"]] = Field(None)
    color: Optional[str] = Field(None, description="Header accent color")

class StyledTableBlock(BaseModel):
    """Tabla con opciones avanzadas de estilo."""
    type: Literal["styled_table"] = "styled_table"
    title: Optional[str] = Field(None, description="Título opcional de la tabla")
    columns: List[ColumnDef] = Field(..., description="Definiciones de columna")
    rows: List[List[str]] = Field(..., description="Filas de datos (texto)")
    style: TableStyle = Field(
        TableStyle.DEFAULT,
        description="Estilo visual de la tabla"
    )
    highlight_first_column: bool = Field(
        False,
        description="Si True, la primera columna se muestra como label/header"
    )
    responsive: bool = Field(
        True,
        description="Si True, se apila en mobile"
    )
    caption: Optional[str] = Field(None, description="Pie de tabla")
```

**Diferencia vs `TableBlock` existente:**
- `TableBlock` tiene `headers: List[str]` y `rows: List[List[str]]` — funcional pero sin opciones de estilo.
- `StyledTableBlock` agrega `ColumnDef` con width/align/color, `TableStyle` enum, y `highlight_first_column` para el patrón de comparison tables visto en la referencia.

**Decisión de diseño — ¿Extender `TableBlock` o nuevo bloque?**

| Opción | Pros | Contras |
|--------|------|---------|
| **Extender `TableBlock`** | Backward compatible, un solo tipo | Rompe simplicidad, campos opcionales confusos para el LLM |
| **Nuevo `StyledTableBlock`** | Separación clara, LLM puede elegir | Dos tipos de tabla, posible confusión |
| **`TableBlock` con `style_config` opcional** | Hybrid, backward compat | Más complejo internamente |

**Recomendación:** Nuevo `StyledTableBlock` como bloque separado. El `TableBlock` existente sigue siendo la opción "simple" para datos tabulares básicos. El prompt del template indica cuál usar.

#### 3.1.3 `AccordionBlock`

**Propósito:** Sección colapsable (expandir/colapsar) con contenido HTML rico adentro. Como las "Phase cards" de la referencia.

```python
class AccordionItem(BaseModel):
    """Una sección individual dentro de un accordion."""
    id: Optional[str] = Field(
        None,
        description="ID único (autogenerado si None)"
    )
    title: str = Field(..., description="Título visible cuando colapsado")
    subtitle: Optional[str] = Field(None, description="Subtítulo o metadata")
    badge: Optional[str] = Field(None, description="Badge/tag text (e.g., 'Semanas 1-2')")
    badge_color: Optional[str] = Field(None, description="Badge color (hex)")
    number: Optional[int] = Field(
        None,
        description="Número de orden visual (se muestra en circle badge)"
    )
    number_color: Optional[str] = Field(None, description="Number circle color")
    # ── Contenido interno ──
    content_blocks: List["InfographicBlock"] = Field(
        default_factory=list,
        description="Bloques internos renderizados al expandir (recursión)"
    )
    # Alternativa: contenido HTML crudo (para cuando el LLM
    # genera contenido que no encaja en bloques tipados)
    html_content: Optional[str] = Field(
        None,
        description="HTML crudo como alternativa a content_blocks"
    )
    expanded: bool = Field(
        False,
        description="Si True, el item se renderiza expandido por defecto"
    )

class AccordionBlock(BaseModel):
    """Grupo de secciones colapsables."""
    type: Literal["accordion"] = "accordion"
    title: Optional[str] = Field(None, description="Título del grupo accordion")
    items: List[AccordionItem] = Field(
        ...,
        description="Secciones colapsables"
    )
    allow_multiple: bool = Field(
        True,
        description="Si True, múltiples items pueden estar abiertos a la vez"
    )
```

**Decisión de diseño clave — `content_blocks` vs `html_content`:**

```
Opción A: Solo content_blocks (recursión de InfographicBlock)
  ✅ Type-safe, themeable, el renderer controla todo
  ❌ El LLM tiene que generar bloques tipados anidados — más complejo
  ❌ Limita a los block types que soportamos

Opción B: Solo html_content (HTML crudo)
  ✅ Máxima flexibilidad, el LLM puede generar cualquier estructura
  ❌ XSS risk si no sanitizamos
  ❌ No respeta el theme system
  ❌ Inconsistencia visual

Opción C: Ambos, con prioridad a content_blocks (RECOMENDADO)
  ✅ content_blocks es el default type-safe
  ✅ html_content como escape hatch para layouts custom
  ✅ El renderer sanitiza html_content con bleach/ammonia
  ✅ El template prompt puede indicar cuál usar
```

**Recomendación:** Opción C. `content_blocks` tiene prioridad; `html_content` se usa solo si `content_blocks` está vacío. El renderer sanitiza `html_content` con una allowlist de tags HTML seguros.

#### 3.1.4 `ChecklistBlock`

**Propósito:** Lista de ítems con checkboxes visuales, como "Criterios de aceptación para cierre del QA".

```python
class ChecklistItem(BaseModel):
    """Un item con checkbox visual."""
    text: str = Field(..., description="Texto del criterio/item")
    checked: bool = Field(
        False,
        description="Si True, se muestra marcado (solo visual)"
    )
    description: Optional[str] = Field(
        None,
        description="Descripción adicional debajo del texto principal"
    )

class ChecklistBlock(BaseModel):
    """Lista con checkboxes visuales (acceptance criteria style)."""
    type: Literal["checklist"] = "checklist"
    title: Optional[str] = Field(None, description="Título (e.g., 'Criterios de aceptación')")
    items: List[ChecklistItem] = Field(
        ...,
        description="Items con checkbox"
    )
    style: Optional[Literal["default", "acceptance", "todo", "compact"]] = Field(
        "default",
        description="Estilo visual del checklist"
    )
```

**HTML esperado:**
```html
<div class="checklist checklist--acceptance">
  <div class="checklist__title">Criterios de aceptación</div>
  <div class="checklist__items">
    <div class="checklist__item">
      <div class="checklist__checkbox"></div>
      <span>Todos los flujos críticos tienen al menos un caso ejecutado</span>
    </div>
    <div class="checklist__item checklist__item--checked">
      <div class="checklist__checkbox">✓</div>
      <span>Bugs registrados en Jira con pasos de reproducción</span>
    </div>
  </div>
</div>
```

### 3.2 Tab System — El contenedor `TabViewBlock`

Este es el bloque más complejo porque introduce **agrupación** en un sistema que hasta ahora era plano.

#### 3.2.1 Modelo de datos

```python
class TabPane(BaseModel):
    """Un panel individual dentro de un tab view."""
    id: str = Field(..., description="ID único del tab (slug)")
    label: str = Field(..., description="Texto del tab button")
    icon: Optional[str] = Field(None, description="Emoji o icono")
    blocks: List[InfographicBlock] = Field(
        ...,
        description="Bloques de contenido de este tab"
    )

class TabViewBlock(BaseModel):
    """Contenedor de navegación por tabs."""
    type: Literal["tab_view"] = "tab_view"
    tabs: List[TabPane] = Field(
        ...,
        min_length=2,
        description="Lista de tabs (mínimo 2)"
    )
    active_tab: Optional[str] = Field(
        None,
        description="ID del tab activo por defecto (None = primero)"
    )
    style: Optional[Literal["pills", "underline", "boxed"]] = Field(
        "pills",
        description="Estilo visual de la navegación"
    )
```

#### 3.2.2 Impacto en `InfographicResponse`

Dos alternativas de diseño:

**Alternativa A — TabViewBlock como un bloque más en la unión:**

```python
InfographicBlock = Union[
    TitleBlock,
    # ... existentes ...
    TabViewBlock,         # ← se agrega a la unión
    TitledBulletListBlock,
    StyledTableBlock,
    AccordionBlock,
    ChecklistBlock,
]

# La respuesta sigue siendo plana, pero puede tener un TabViewBlock
# que internamente contiene tabs con sus propios bloques
class InfographicResponse(BaseModel):
    blocks: List[InfographicBlock]  # puede incluir TabViewBlock
```

**Alternativa B — `InfographicResponse` con tabs como campo explícito:**

```python
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    # Modo clásico: bloques planos
    blocks: List[InfographicBlock] = Field(default_factory=list)
    # Modo tabs: agrupación explícita
    tabs: Optional[List[TabPane]] = Field(None)
    metadata: Optional[Dict]

    @model_validator(mode="before")
    def _validate_content(cls, values):
        """Asegurar que hay blocks O tabs, no ambos vacíos."""
        has_blocks = bool(values.get("blocks"))
        has_tabs = bool(values.get("tabs"))
        if not has_blocks and not has_tabs:
            raise ValueError("InfographicResponse must have blocks or tabs")
        return values
```

**Análisis comparativo:**

| Criterio | Alternativa A (TabView como bloque) | Alternativa B (tabs en Response) |
|----------|-------------------------------------|----------------------------------|
| Backward compat | ✅ Sin cambios en InfographicResponse | ⚠️ Requiere model_validator |
| Composabilidad | ✅ TabView puede ir dentro de otros bloques | ❌ tabs es top-level only |
| LLM simplicity | ⚠️ Nested blocks en JSON | ✅ Estructura más clara |
| Template prompt | ⚠️ Más complejo de describir | ✅ Puede describir tabs como secciones |
| Flexibilidad | ✅ Tabs + bloques planos en un mismo infographic | ❌ Es uno u otro |
| Profundidad de anidación | ⚠️ Podría tener TabView dentro de Accordion, etc. | ✅ Solo 1 nivel de tabs |

**Recomendación: Alternativa A** (TabViewBlock como bloque en la unión).

Razones:
1. **Zero breaking changes** — `InfographicResponse` no cambia.
2. **Composabilidad** — Un infographic puede tener un `TitleBlock` arriba seguido de un `TabViewBlock`, exactamente como la referencia (título + subtítulo arriba, tabs abajo).
3. **Consistente con la filosofía** — todo es un bloque, el renderer sabe qué hacer con cada tipo.
4. **Límite de anidación controlado** — El template prompt puede indicar "el TabViewBlock debe estar al top level" y el renderer puede imponer `max_depth=2`.

### 3.3 Template `multi_tab`

```python
TEMPLATE_MULTI_TAB = InfographicTemplate(
    name="multi_tab",
    description=(
        "Multi-section report organized as tabbed views. "
        "Contains a title block followed by a single tab_view block "
        "where each tab holds its own independent set of content blocks. "
        "Ideal for methodologies, multi-chapter reports, process documentation, "
        "and any long-form content that benefits from navigation."
    ),
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Main report title and subtitle",
        ),
        BlockSpec(
            block_type=BlockType.TAB_VIEW,
            description=(
                "Tabbed navigation containing 3-7 tabs. "
                "Each tab has a label and contains its own sequence of blocks. "
                "Blocks inside each tab can be any valid block type including: "
                "summary, titled_bullet_list, styled_table, accordion, "
                "checklist, chart, hero_card, timeline, callout, etc."
            ),
            min_items=3,
            max_items=7,
        ),
    ],
)
```

### 3.4 Extended Template Prompt Generation

El método `to_prompt_instruction()` necesita manejar el nuevo concepto de tabs:

```python
# Pseudo-código para la instrucción del LLM
def to_prompt_instruction(self) -> str:
    # ... existente para bloques planos ...

    # Si hay un BlockSpec de tipo TAB_VIEW, generar instrucciones especiales:
    """
    The tab_view block MUST contain a "tabs" array where each tab has:
      - "id": unique slug (e.g., "overview", "phases", "qa")
      - "label": display text for the tab button
      - "blocks": array of content blocks for this tab

    Each tab's blocks array can contain any of the following block types:
      summary, titled_bullet_list, styled_table, accordion, checklist,
      chart, hero_card, bullet_list, table, callout, timeline, progress,
      divider, quote, image

    The first tab should contain an overview or introduction.
    Subsequent tabs should group related content logically.
    """
```

### 3.5 Rendering — `InfographicHTMLRenderer`

#### 3.5.1 Tab Navigation HTML

```html
<!-- Generado por render_tab_view_block() -->
<div class="tab-view">
  <nav class="tab-view__nav tab-view__nav--pills">
    <button class="tab-view__btn active" onclick="showTab('overview', this)">
      Resumen
    </button>
    <button class="tab-view__btn" onclick="showTab('phases', this)">
      Fases
    </button>
    <button class="tab-view__btn" onclick="showTab('qa', this)">
      QA
    </button>
  </nav>

  <div class="tab-view__pane active" id="tab-overview">
    <!-- bloques renderizados recursivamente -->
  </div>
  <div class="tab-view__pane" id="tab-phases">
    <!-- bloques renderizados recursivamente -->
  </div>
  <div class="tab-view__pane" id="tab-qa">
    <!-- bloques renderizados recursivamente -->
  </div>
</div>

<script>
function showTab(id, btn) {
  document.querySelectorAll('.tab-view__pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-view__btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
}
</script>
```

#### 3.5.2 CSS Design Tokens (integración con ThemeConfig)

```css
/* Tab navigation */
.tab-view__nav { display: flex; gap: 6px; flex-wrap: wrap; padding-bottom: 1.25rem;
                  border-bottom: 0.5px solid var(--neutral-border); margin-bottom: 1.25rem; }
.tab-view__btn { padding: 6px 14px; border-radius: 20px; border: 0.5px solid var(--neutral-border);
                 background: transparent; color: var(--neutral-muted); font-size: 13px; cursor: pointer; }
.tab-view__btn.active { background: var(--neutral-bg); border-color: var(--primary);
                         color: var(--neutral-text); font-weight: 500; }
.tab-view__pane { display: none; }
.tab-view__pane.active { display: block; }

/* Accordion */
.accordion__item { border: 0.5px solid var(--neutral-border); border-radius: 12px; overflow: hidden; }
.accordion__header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }
.accordion__header:hover { background: var(--neutral-bg); }
.accordion__body { display: none; border-top: 0.5px solid var(--neutral-border); }
.accordion__item.open .accordion__body { display: block; }

/* Checklist */
.checklist__item { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; }
.checklist__checkbox { width: 14px; height: 14px; border-radius: 3px;
                        border: 0.5px solid var(--neutral-border); flex-shrink: 0; }
.checklist__item--checked .checklist__checkbox { background: var(--accent-green);
                                                   border-color: var(--accent-green); }

/* Styled Table */
.styled-table { border: 0.5px solid var(--neutral-border); border-radius: 12px; overflow: hidden; }
.styled-table--striped tr:nth-child(even) { background: var(--neutral-bg); }
.styled-table--comparison td:first-child { font-weight: 500; font-size: 12px; }

/* Titled Bullet List */
.titled-bullet-list__header { font-size: 13px; font-weight: 500; padding-bottom: 8px;
                                border-bottom: 0.5px solid var(--neutral-border); margin-bottom: 10px; }
.titled-bullet-list__dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
```

#### 3.5.3 Múltiples TabViews en un mismo infographic

Si el infographic contiene más de un `TabViewBlock`, cada uno necesita IDs únicos para que el JS no colisione:

```python
# En el renderer:
def render_tab_view_block(self, block: TabViewBlock, instance_id: int) -> str:
    prefix = f"tv{instance_id}"  # tv0, tv1, ...
    # Los IDs de tabs se prefijan: tv0-overview, tv0-phases, etc.
    # La función JS se genera con scope por instance
```

---

## 4. Flujo de Datos End-to-End

```
User: "Genera un reporte multi-tab sobre la metodología de agentes IA"
  │
  ▼
get_infographic(question, template="multi_tab", theme="light")
  │
  ├── 1. Resuelve TEMPLATE_MULTI_TAB → to_prompt_instruction()
  │      Genera instrucciones para el LLM describiendo la estructura con tabs
  │
  ├── 2. ask() con structured_output=InfographicResponse
  │      El LLM retorna JSON con:
  │      {
  │        "template": "multi_tab",
  │        "blocks": [
  │          { "type": "title", "title": "Metodología...", "subtitle": "..." },
  │          { "type": "tab_view", "tabs": [
  │            { "id": "overview", "label": "Resumen", "blocks": [
  │              { "type": "summary", "content": "..." },
  │              { "type": "titled_bullet_list", ... }
  │            ]},
  │            { "id": "phases", "label": "Fases", "blocks": [
  │              { "type": "accordion", "items": [...] }
  │            ]},
  │            { "id": "qa", "label": "QA", "blocks": [
  │              { "type": "checklist", "items": [...] },
  │              { "type": "styled_table", ... }
  │            ]}
  │          ]}
  │        ]
  │      }
  │
  ├── 3. InfographicResponse valida con Pydantic discriminated union
  │      ├── _normalise_payload() maneja aliases comunes del LLM
  │      └── TabViewBlock valida recursivamente los bloques internos
  │
  ├── 4. InfographicHTMLRenderer.render_to_html()
  │      ├── render_title_block()
  │      ├── render_tab_view_block()
  │      │     ├── Genera nav con botones de tab
  │      │     └── Para cada TabPane:
  │      │           └── render_block() recursivo para cada bloque interno
  │      │                 ├── render_accordion_block()
  │      │                 ├── render_checklist_block()
  │      │                 ├── render_styled_table_block()
  │      │                 └── render_titled_bullet_list_block()
  │      └── Inyecta CSS + JS de tabs/accordion en el <head>
  │
  └── 5. Retorna AIMessage con .content = HTML completo
```

---

## 5. Forward References y Recursión en Pydantic

### 5.1 El problema de las circular references

`AccordionItem.content_blocks` y `TabPane.blocks` ambos referencian `InfographicBlock`, que a su vez incluye `AccordionBlock` y `TabViewBlock`. Esto crea una referencia circular.

### 5.2 Solución

Pydantic v2 maneja forward references con `model_rebuild()`:

```python
# 1. Definir bloques base (sin recursión)
class AccordionItem(BaseModel):
    content_blocks: List["InfographicBlock"] = Field(default_factory=list)

class TabPane(BaseModel):
    blocks: List["InfographicBlock"] = Field(...)

# 2. Definir la unión DESPUÉS de todos los bloques
InfographicBlock = Union[
    TitleBlock, HeroCardBlock, ...,
    TabViewBlock, AccordionBlock, ...,
]

# 3. Rebuild models que usan forward refs
AccordionItem.model_rebuild()
TabPane.model_rebuild()
InfographicResponse.model_rebuild()
```

### 5.3 Límite de profundidad

Para evitar recursión infinita del LLM (TabView dentro de TabView dentro de Accordion...):

```python
class TabViewBlock(BaseModel):
    # El template prompt DEBE indicar: "tab_view blocks must be top-level only"
    # El renderer puede imponer max_depth:
    pass

# En el renderer:
def render_block(self, block, depth=0, max_depth=3):
    if depth > max_depth:
        return f"<!-- max nesting depth exceeded -->"
    if isinstance(block, TabViewBlock):
        return self.render_tab_view_block(block, depth=depth+1)
    # ...
```

---

## 6. Impacto en Componentes Existentes

### 6.1 Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `parrot/models/infographic.py` | +4 nuevos block models, +1 TabViewBlock, ampliar `BlockType` enum, actualizar `InfographicBlock` union |
| `parrot/models/infographic_templates.py` | +`TEMPLATE_MULTI_TAB`, actualizar `_register_builtins()` |
| `parrot/outputs/formats/infographic_html.py` | +5 nuevos métodos `render_*_block()`, +CSS de tabs/accordion/checklist, +JS para interactividad |
| Tests unitarios | +tests para cada nuevo bloque, +test de serialización/deserialización con recursión |

### 6.2 Archivos que NO cambian

| Archivo | Por qué |
|---------|---------|
| `parrot/bots/abstract.py` | `get_infographic()` ya es genérico; el template se pasa como string |
| `parrot/models/infographic.py` (ThemeConfig) | Los CSS vars actuales cubren los nuevos bloques |
| Bloques existentes | Backward compatible al 100%, no se tocan |

### 6.3 Riesgo: Tamaño del JSON generado por el LLM

Un infographic multi-tab con 5 tabs, cada uno con 3-5 bloques, genera un JSON considerablemente más grande que un infographic plano. Estimaciones:

```
Infographic básico (5 bloques):    ~2-4 KB JSON
Infographic multi-tab (5×4 bloques): ~15-25 KB JSON
```

Esto está bien dentro del output window de Gemini/Claude/GPT-4, pero es relevante para:
- **Token budget**: Puede necesitar `max_tokens` más alto en la llamada al LLM.
- **Structured output reliability**: JSON más grande = más probabilidad de errores del LLM. El `_normalise_payload()` debe ser robusto.

---

## 7. Consideraciones de UX del Renderer

### 7.1 Dark mode

Todos los nuevos bloques DEBEN usar CSS variables de `ThemeConfig`, nunca colores hardcodeados. La referencia usa `prefers-color-scheme: dark` — nuestro renderer debe soportarlo via themes.

### 7.2 Responsive

| Bloque | Comportamiento mobile |
|--------|----------------------|
| Tab navigation | Wrap a múltiples líneas (flex-wrap) |
| StyledTableBlock | Scroll horizontal o stack vertical |
| AccordionBlock | Full width, sin cambios |
| TitledBulletListBlock | Columnas → single column |
| ChecklistBlock | Full width, sin cambios |

### 7.3 Print / Export

El HTML generado debe ser print-friendly:
```css
@media print {
  .tab-view__nav { display: none; }
  .tab-view__pane { display: block !important; page-break-before: always; }
  .accordion__body { display: block !important; }
}
```

---

## 8. Tareas Propuestas (para SDD Spec)

```
TASK-01: Definir nuevos block models en infographic.py
         - TitledBulletListBlock, StyledTableBlock, AccordionBlock, ChecklistBlock
         - Ampliar BlockType enum
         - Actualizar InfographicBlock union
         - model_rebuild() para forward refs
         Estimación: S

TASK-02: Definir TabViewBlock y TabPane models
         - Forward references con model_rebuild()
         - Validación de min 2 tabs
         - Tests de serialización con recursión
         Estimación: S

TASK-03: Crear TEMPLATE_MULTI_TAB
         - BlockSpec para title + tab_view
         - Actualizar to_prompt_instruction() para tabs
         - Registrar en _register_builtins()
         Estimación: S

TASK-04: Renderer — render_titled_bullet_list_block()
         - HTML + CSS con dot indicators y grid columns
         Estimación: S

TASK-05: Renderer — render_styled_table_block()
         - HTML + CSS con TableStyle variants
         - Responsive behavior
         Estimación: M

TASK-06: Renderer — render_accordion_block()
         - HTML + CSS + JS para expand/collapse
         - Renderizado recursivo de content_blocks
         - Sanitización de html_content
         Estimación: M

TASK-07: Renderer — render_checklist_block()
         - HTML + CSS con checkbox visuals
         - Estilos: default, acceptance, todo, compact
         Estimación: S

TASK-08: Renderer — render_tab_view_block()
         - HTML nav + panes + JS show/hide
         - Renderizado recursivo de bloques por tab
         - Soporte para múltiples TabViews (instance IDs)
         - Print CSS
         Estimación: L

TASK-09: Tests unitarios
         - Serialización/deserialización de cada nuevo bloque
         - Round-trip: Pydantic → JSON → Pydantic
         - Recursión: TabView con Accordion dentro
         - Edge cases: tabs vacíos, accordion sin content_blocks
         Estimación: M

TASK-10: Test de integración E2E
         - Generar infographic multi_tab con LLM real
         - Validar HTML output
         - Validar interactividad de tabs y accordions
         Estimación: M
```

---

## 9. Preguntas Abiertas

1. **¿Limitar profundidad de anidación?** — ¿`max_depth=2` (TabView → Accordion → bloques planos) o `max_depth=3`?: max_depth=3

2. **¿`html_content` en AccordionItem necesita sanitización?** — Propongo usar `bleach` con allowlist restrictiva. ¿O solo soportar `content_blocks` y eliminar `html_content`?: `bleach` con allowlist

3. **¿Extender `BulletListBlock` vs nuevo `TitledBulletListBlock`?** — `BulletListBlock` ya tiene `title: Optional[str]`. ¿Basta agregar `color` y `columns` al existente en vez de crear uno nuevo?: si, agregar estilo, color y columna al existente.

4. **¿El `TableBlock` existente se depreca a favor de `StyledTableBlock`?** — ¿O ambos coexisten indefinidamente?: o le aplicamos estilos y tema al TableBlock.

5. **¿Soporte para interactividad en Telegram WebApp?** — ¿El renderer de tabs/accordions debe generar HTML compatible con Telegram WebApp (sin JS externo)?: deferred to v2.

6. **¿Tab icons?** — La referencia no usa íconos en tabs, pero ¿soportamos emoji/iconos por si el LLM quiere usarlos?: si, darle soporte.

---

## 10. Diagrama de Dependencias

```
infographic.py (models)
  ├── BlockType enum ← +5 nuevos valores
  ├── Nuevos blocks ← TitledBulletListBlock, StyledTableBlock,
  │                    AccordionBlock, ChecklistBlock, TabViewBlock
  ├── InfographicBlock union ← +5 nuevos tipos
  └── model_rebuild() ← resolver forward refs
          │
          ▼
infographic_templates.py
  ├── TEMPLATE_MULTI_TAB ← nuevo
  ├── to_prompt_instruction() ← extender para tab_view
  └── _register_builtins() ← registrar multi_tab
          │
          ▼
infographic_html.py (renderer)
  ├── render_titled_bullet_list_block() ← nuevo
  ├── render_styled_table_block() ← nuevo
  ├── render_accordion_block() ← nuevo (con recursión)
  ├── render_checklist_block() ← nuevo
  ├── render_tab_view_block() ← nuevo (con recursión)
  ├── CSS: +tabs, +accordion, +checklist, +styled-table
  └── JS: +showTab(), +toggleAccordion()
          │
          ▼
abstract.py (no changes)
  └── get_infographic() ← ya soporta cualquier template name
```
