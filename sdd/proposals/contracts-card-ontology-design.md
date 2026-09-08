# ContractCard y ontología de contratos — definición base

> Contexto: `claude/contracts-agent-definition.md` (producto y mapeo a ai-parrot). Este documento fija las dos piezas que no existen hoy y de las que depende todo lo demás: la **ficha** (`ContractCard`) y el **vocabulario del grafo** (`contracts.ontology.yaml`). Todo lo verificado contra `main` se indica; lo demás son decisiones de diseño a confirmar.

## 0. Decisiones de diseño (resumen)

| # | Decisión | Razón |
|---|---|---|
| D1 | `ContractCard` es una **ficha hermana** de `BookCard`, no una subclase. Comparten el patrón (una ficha por documento, `tree_name` = `contract_id`, `source_sha256`, `card_origin`, draft por structured output + fallback sin LLM) y los helpers de `carding.py` (`slugify`, `unique_slug`, `derive_toc`, `sample_sections`). | `BookCard` tiene campos de biblioteca (`genre`, `traditions`, `period`) y `catalog.py` está acoplado a `books`/`books_fts`; generalizar ahora costaría más que duplicar el patrón. La generalización a una "familia de cards" es un refactor posterior, cuando haya dos consumidores reales. |
| D2 | **Cada campo extraído lleva proveniencia** (`FieldProvenance`: `node_id`, `page`, `quote`, `origin`, `confidence`) y la ficha lleva un estado de verificación de tres valores: `extracted` → `verified` → `stale`. | Es lo que hace defendible "verified vs. AI-extracted" ante Bob y ante auditoría. `stale` evita que una re-carding silenciosa pise lo que Bob verificó. |
| D3 | **`status`, `notice_deadline`, `renewal_date` y `parent_contract_id` se derivan en Python**, nunca los devuelve el LLM. | Son funciones puras de fechas y de la ficha del padre; el LLM sólo extrae hechos que están en el texto. |
| D4 | Las **obligaciones son entidades de primera clase** (`Obligation`), no un campo de la ficha: cada una es un excerpt verbatim + `node_id` + `kind` cerrado + `standard_id` opcional. | "¿Qué contratos exigen SOC 2?" es un traversal `ComplianceStandard ← Obligation ← Contract`, y cada obligación es citable por sí misma. |
| D5 | El **grafo se escribe determinísticamente desde la ficha** (`ContractGraphLoader`), como `BOEDataSource` en el dominio legal. `discovery: field_match` sólo para las aristas de campo simple (`governed_by`, `imposed_by`, `requires`, `owned_by`, `managed_by`, `represents`, `is_employee`); `party_to` y `signed_by` (con propiedades de arista) las escribe el loader. | El módulo `ontology` valida `field_match` sobre campos escalares; las aristas con `role`/`signed_on` necesitan el loader. Cero LLM en retrieval, igual que `legal.ontology.yaml`. |
| D6 | **Versiones bitemporales embebidas en `Contract.versions[]`**, copiando la convención probada de `Articulo.versions` (`valid_from` inclusivo, `valid_to` exclusivo, `null` = vigente). El plano temporal de graphindex (FEAT-520, Postgres) queda para después. | Reutiliza el patrón `article_in_force` tal cual; una enmienda = nueva versión. |
| D7 | Autorización declarativa por patrón: roles `contract_reader` / `contract_owner` con `default_deny`, más `my_contracts` (siempre permitido, filtra por cadena de mando) y `department` en `Contract` para que `same_department` funcione si se quiere en fase 2. | Responde al punto "access" del cliente con reglas, no con prompt. `AuthorizationChecker` sólo soporta los 5 tipos de regla existentes; `Contract.department` es lo que hace utilizable `same_department` sobre un contrato. |
| D8 | Persistencia del catálogo detrás de un **protocolo `ContractCatalogStore`** con dos backends: SQLite (piloto local / CLI, hereda el esquema de `catalog.py`) y Postgres (multiusuario, patrón `graphindex/persist_postgres.py`). | La ficha no puede esperar a Postgres, pero el piloto con varios usuarios y autorización no puede correr sobre `library.db`. Fijar la interfaz primero. |

## 1. Modelo de datos — `parrot/knowledge/contracts/models.py`

Convenciones heredadas de `bookstore/models.py`: Pydantic v2, taxonomías como `Literal` cerrados con `"other"`, timestamps ISO-8601 como `str` (el módulo ontology no tiene tipo `datetime`), fechas como `date`.

```python
from __future__ import annotations
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

ContractType = Literal["msa", "sow", "nda", "dpa", "amendment", "order_form", "license", "sla", "other"]
ContractStatus = Literal["draft", "active", "expired", "terminated", "superseded", "unknown"]
PartyRole = Literal["customer", "vendor", "partner", "affiliate", "us", "other"]
ObligationKind = Literal[
    "compliance", "insurance", "data_protection", "security", "sla", "audit_right",
    "reporting", "payment", "confidentiality", "termination", "notice", "deliverable", "other",
]
Obligor = Literal["us", "counterparty", "both"]
Verification = Literal["extracted", "verified", "stale"]
ProvenanceOrigin = Literal["llm", "rule", "manual"]   # rule = derivación determinista


class FieldProvenance(BaseModel):
    """De dónde salió el valor de un campo de la ficha.

    quote es el texto literal del que se leyó el valor (≤ 300 chars); su hash
    es lo que decide si una re-carding puede conservar un valor verificado.
    """
    origin: ProvenanceOrigin
    node_id: Optional[str] = None       # nodo PageIndex (tree = contract_id)
    page: Optional[int] = None
    quote: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None


class Party(BaseModel):
    party_id: str                       # slug del nombre legal normalizado
    name: str
    role: PartyRole = "other"
    is_us: bool = False


class Signatory(BaseModel):
    person_id: str                      # slug(nombre) + party_id
    name: str
    title: Optional[str] = None
    party_id: str
    signed_on: Optional[date] = None
    employee_id: Optional[str] = None   # cuando es de los nuestros (base.Employee)


class TermSpec(BaseModel):
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    initial_term_months: Optional[int] = None
    auto_renew: bool = False
    renewal_period_months: Optional[int] = None
    notice_days: Optional[int] = None
    # derivados (origin="rule"), nunca del LLM:
    notice_deadline: Optional[date] = None      # expiration_date - notice_days
    next_renewal_date: Optional[date] = None    # expiration_date si auto_renew


class Obligation(BaseModel):
    obligation_id: str                  # f"{contract_id}:{seq}"
    contract_id: str
    kind: ObligationKind
    obligor: Obligor = "us"
    text: str                           # excerpt verbatim — la cita
    node_id: str
    page: Optional[int] = None
    standard_id: Optional[str] = None   # ComplianceStandard (soc2, gdpr, ...)
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    verification: Verification = "extracted"
    provenance: FieldProvenance


class ContractVersion(BaseModel):
    """Una entrada de Contract.versions[] (convención legal.Articulo.versions)."""
    n: int
    valid_from: date
    valid_to: Optional[date] = None     # exclusivo; None = vigente
    kind: Literal["original", "amendment", "renewal", "restatement"] = "original"
    amended_by: Optional[str] = None    # contract_id de la enmienda
    source_sha256: str
    card_snapshot: dict = Field(default_factory=dict)   # ContractCard.model_dump() en ese momento


class ContractCard(BaseModel):
    """La ficha durable de un contrato. contract_id == PageIndex tree_name."""
    contract_id: str
    tree_name: str
    title: str
    contract_type: ContractType = "other"
    status: ContractStatus = "unknown"              # derivado (rule)
    parties: list[Party] = Field(default_factory=list)
    signatories: list[Signatory] = Field(default_factory=list)
    term: TermSpec = Field(default_factory=TermSpec)
    governing_law: Optional[str] = None
    parent_contract_id: Optional[str] = None        # resuelto (rule) o manual
    supersedes_contract_id: Optional[str] = None
    obligations: list[Obligation] = Field(default_factory=list)
    summary: str = ""
    topics: list[str] = Field(default_factory=list)  # reutiliza la FTS de bookstore
    owner_employee_id: Optional[str] = None         # manual / regla de carpeta
    department: Optional[str] = None
    language: Optional[str] = None
    # documento
    source_uri: str                                 # nunca una copia
    source_path: Optional[str] = None               # caché local temporal, si la hay
    source_sha256: str
    source_format: Literal["pdf", "docx", "md", "txt"]
    page_count: Optional[int] = None
    toc: list["TocEntry"] = Field(default_factory=list)     # bookstore.models.TocEntry
    toc_digest: str = ""
    # proveniencia y verificación
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    verification: Verification = "extracted"
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    stale_fields: list[str] = Field(default_factory=list)   # qué cambió tras una re-carding
    card_origin: Literal["llm", "fallback", "manual"] = "llm"
    versions: list[ContractVersion] = Field(default_factory=list)
    added_at: str
    updated_at: str

    @model_validator(mode="after")
    def _one_us_party(self) -> "ContractCard":
        if sum(p.is_us for p in self.parties) > 1:
            raise ValueError("a ContractCard cannot list more than one 'us' party")
        return self

    def brief(self) -> dict:
        """Salida compacta para listados y tool outputs (misma idea que BookCard.brief)."""
        return {
            "contract_id": self.contract_id, "title": self.title, "type": self.contract_type,
            "status": self.status, "counterparties": [p.name for p in self.parties if not p.is_us],
            "effective_date": self.term.effective_date, "expiration_date": self.term.expiration_date,
            "auto_renew": self.term.auto_renew, "notice_deadline": self.term.notice_deadline,
            "obligation_kinds": sorted({o.kind for o in self.obligations}),
            "standards": sorted({o.standard_id for o in self.obligations if o.standard_id}),
            "verification": self.verification, "parent_contract_id": self.parent_contract_id,
        }
```

### 1.1 El draft del LLM — `ContractCardDraft`

El structured output del carding **no es la ficha**: es un draft donde cada valor viene acompañado de su evidencia, para que el ensamblador pueda construir `field_provenance` sin una segunda llamada.

```python
class Evidence(BaseModel):
    node_id: str
    quote: str = Field(..., max_length=300, description="Verbatim text the value was read from")
    page: Optional[int] = None

class Extracted(BaseModel):          # genérico por campo; se instancia con el tipo concreto
    value: object
    evidence: Optional[Evidence] = None
    confidence: float = Field(ge=0.0, le=1.0)

class PartyDraft(BaseModel):
    name: str; role: PartyRole = "other"; is_us: bool = False; evidence: Optional[Evidence] = None

class SignatoryDraft(BaseModel):
    name: str; title: Optional[str] = None; party_name: str; signed_on: Optional[date] = None
    evidence: Optional[Evidence] = None

class ObligationDraft(BaseModel):
    kind: ObligationKind; obligor: Obligor = "us"; text: str; node_id: str; page: Optional[int] = None
    standard_name: Optional[str] = None       # texto libre; se resuelve a standard_id por alias
    due_date: Optional[date] = None; recurrence: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

class ContractHeaderDraft(BaseModel):
    """Pasada 1 — portada, definiciones, término, firmas."""
    title: Extracted
    contract_type: Extracted            # value: ContractType
    parties: list[PartyDraft]
    signatories: list[SignatoryDraft]
    effective_date: Optional[Extracted] = None
    expiration_date: Optional[Extracted] = None
    initial_term_months: Optional[Extracted] = None
    auto_renew: Optional[Extracted] = None
    renewal_period_months: Optional[Extracted] = None
    notice_days: Optional[Extracted] = None
    governing_law: Optional[Extracted] = None
    parent_contract_title: Optional[Extracted] = None   # "this SOW is governed by the MSA dated ..."
    language: Optional[str] = None
    summary: str = ""
    topics: list[str] = Field(default_factory=list)

class ObligationsDraft(BaseModel):
    """Pasada 2 — una llamada por sección candidata (o por lote de secciones)."""
    obligations: list[ObligationDraft] = Field(default_factory=list)
```

Regla del prompt (misma filosofía que `_CARD_PROMPT`): *"Using ONLY the material below… every value must carry the verbatim quote it was read from; if it is not in the text, return null"*. Un valor sin `evidence` se acepta pero entra con `confidence` capada a 0.5 y aparece en la cola de verificación en primer lugar.

## 2. Pipeline de carding — `parrot/knowledge/contracts/carding.py` + `library.py`

Reutiliza el esqueleto de `Bookstore.add_book` (sha256 → skip/update → `create_tree` → `import_pdf`/`insert_markdown` → carding → `catalog.upsert`) con estas diferencias:

1. **Muestreo dirigido, no "primero + medio".** `sample_sections` de bookstore elige dos nodos representativos; un contrato necesita nodos concretos. `select_carding_nodes(toc, content_loader)` devuelve, con heurística sobre títulos del ToC y regex sobre el cuerpo: la portada/preámbulo (primer nodo), las secciones cuyo título case con `term|duration|renewal|termination|notice|governing law|definitions|parties|scope`, y el **bloque de firmas** (último nodo, o el primero que contenga `IN WITNESS WHEREOF|signed|by:|title:|date:`). Fallback: primero + último + los 3 nodos con más densidad de `shall|must|agrees to`.
2. **Dos pasadas.** Pasada 1 (`ContractHeaderDraft`) con esos nodos concatenados (cap ~12k chars). Pasada 2 (`ObligationsDraft`) iterando por sección candidata: todas las que superen un umbral de densidad de verbos deónticos o que casen con `compliance|SOC|ISO|GDPR|insurance|audit|security|SLA|service level|data protection|confidential`. Coste: 1 + N llamadas por contrato, N acotado (`max_obligation_sections`, default 12). Como en bookstore `relate`, es explícito y re-ejecutable con `--force`.
3. **Ensamblado determinista (`assemble_card`)**: drafts → `ContractCard`. Aquí se construye `field_provenance`, se resuelven `Party.party_id`/`Signatory.person_id` con `slugify`, se mapea `standard_name` → `standard_id` por la tabla de alias de `ComplianceStandard` (`SOC 2 Type II` → `soc2`), y se aplican las derivaciones:
   - `term.notice_deadline = expiration_date - notice_days` (si ambos);
   - `term.next_renewal_date = expiration_date` si `auto_renew`;
   - `status`: `superseded` si existe `supersedes` entrante; `terminated` si hay obligación `kind=termination` con `due_date` pasada y marca manual; `expired` si `expiration_date < today` y no `auto_renew`; `active` si `effective_date <= today` y (`expiration_date` es null o futura o `auto_renew`); `draft` si no hay firmas; `unknown` en otro caso;
   - `parent_contract_id`: si `parent_contract_title` existe, se resuelve contra el catálogo por `contract_type in {msa, ...}` + misma contraparte + similitud de título (rapidfuzz ≥ 0.85); si no hay candidato único, queda `None` y se anota en `stale_fields`/cola de verificación (mejor un hueco que una arista falsa, misma regla que el `SymbolResolver` del plano estructural).
4. **Fallback sin LLM** (`fallback_card_fields`): título del filename, `contract_type` por regex sobre el filename/portada (`MSA|NDA|SOW|DPA|Amendment`), fechas por regex `\d{1,2} \w+ \d{4}` en el primer y último nodo, sin obligaciones. `card_origin="fallback"`, todo con `confidence=0.3`.
5. **Verificación** (`verify_card(contract_id, fields: dict | None, user)`): sin campos = verificar toda la ficha; con campos = sólo esos. Marca `provenance.origin="manual"` cuando Bob corrige el valor, `verified_by/verified_at` en cada campo, y `verification="verified"` en la ficha cuando no queda ningún campo `extracted` con `confidence < threshold` ni `stale_fields`.
6. **Refresh** (`refresh_card`): sha distinto → re-carding completa a un draft nuevo; por cada campo verificado se compara `hash(quote)` viejo vs. nuevo: igual → se conserva el valor y su verificación; distinto → el campo pasa a `stale_fields`, la ficha a `verification="stale"`, y se crea una `ContractVersion` nueva (`kind="amendment"` si el nuevo documento es una enmienda, `"restatement"` si es el mismo contrato re-firmado). Nunca se pierde el valor verificado anterior: queda en `versions[-1].card_snapshot`.

## 3. Persistencia — `ContractCatalogStore`

```python
class ContractCatalogStore(Protocol):
    def upsert(self, card: ContractCard) -> None: ...
    def get(self, contract_id: str) -> ContractCard | None: ...
    def find_by_sha(self, sha256: str) -> ContractCard | None: ...
    def find_by_source_uri(self, uri: str) -> ContractCard | None: ...
    def list_cards(self, *, status: ContractStatus | None = None, verification: Verification | None = None) -> list[ContractCard]: ...
    def search(self, query: str, top_k: int = 8) -> list[tuple[ContractCard, float]]: ...   # FTS
    def expiring(self, *, until: date, key: Literal["expiration_date", "notice_deadline"]) -> list[ContractCard]: ...
    def verification_queue(self, *, limit: int = 50) -> list[ContractCard]: ...
    def taken_slugs(self) -> set[str]: ...
    def remove(self, contract_id: str) -> bool: ...
```

SQLite (`contracts`, `contracts_fts`, `obligations`, `contract_versions`) replica la forma de `catalog.py` — el JSON completo de la ficha en una columna `card_json` más las columnas indexables (`status`, `expiration_date`, `notice_deadline`, `verification`, `source_sha256`, `source_uri`); Postgres, la misma forma con `JSONB` + índices y `tsvector` para la FTS. `expiring()` y `verification_queue()` son consultas SQL, no recorridos del grafo: el scheduler no depende de ArangoDB para el renewal radar.

## 4. Ontología — `ontology/defaults/domains/contracts.ontology.yaml`

Validada con `OntologyDefinition.model_validate` contra `schema.py` de `main` (5 entidades, 11 relaciones, 1 view, 10 patrones). El fichero completo acompaña este documento; aquí, lo que importa de cada bloque.

**Entidades.** `Contract` (proyección de la ficha: tipo, estado, fechas, `notice_deadline`, `parent_contract_id`, `owner_employee_id`, `department`, `counterparty_names` desnormalizado para búsqueda, `verification`, `source_uri`, `source_sha256`, `versions[]`, `summary`), `Party` (nombre legal normalizado + alias), `Person` (firmantes, con `party_id` y `employee_id` opcional), `Obligation` (excerpt + `node_id` + `kind` + `standard_id`), `ComplianceStandard` (taxonomía estática con alias). `Employee`/`Department` vienen de `base.ontology.yaml` (`extends: base`).

**Relaciones.** Escritas por el loader: `party_to` (con `role`), `signed_by` (con `signed_on`, `on_behalf_of`), `amends` (con `effective_date`), `supersedes`. Descubiertas por `field_match`: `governed_by` (`parent_contract_id`), `imposed_by` (`Obligation.contract_id`), `requires` (`Obligation.standard_id`), `represents`, `is_employee`, `owned_by`, `managed_by`. Nota de dirección: `imposed_by` y `requires` salen de `Obligation` porque `field_match` casa un campo escalar de la entidad origen; los traversals las recorren `INBOUND`.

**Search view** `contracts_view`: `Contract.title/summary/counterparty_names`, `Obligation.text`, `Party.name/aliases`, analyzers `text_en` (+ `identity` para nombres). Si el corpus es bilingüe se añade `text_es` como en `legal_articulos_view`.

**Patrones de traversal** (todos `post_action: none` salvo el último; todos con `authorization` explícita):

| Patrón | Pregunta que resuelve | Extracción de entidades |
|---|---|---|
| `contracts_requiring_standard` | "Which agreements require SOC 2?" — devuelve contrato **y** la obligación que lo cita | `ComplianceStandard` fuzzy |
| `expiring_within` | contratos con `expiration_date` en ventana | — (bind `@today`, `@until`) |
| `notice_deadlines_within` | auto-renovables por `notice_deadline` (fallback a expiration) — la query del renewal radar | — |
| `contracts_with_party` | todo lo firmado con una contraparte, con `role` | `Party` fuzzy |
| `contract_family` | MSA ↔ SOWs ↔ enmiendas (`1..3 ANY` sobre `governed_by`, `amends`) | `Contract` hybrid |
| `signatories_of` | quién firmó, por quién, cuándo | `Contract` hybrid |
| `obligations_of_contract` | obligaciones de un contrato, filtro `@kind` opcional | `Contract` hybrid |
| `contract_in_force` | versión vigente en `@as_of` sobre `versions[]` (copia de `article_in_force`) | `Contract` hybrid |
| `my_contracts` | contratos del usuario y de su cadena de mando (`0..10 INBOUND reports_to`) | — (`@user_id`) |
| `search_contracts` | candidatos léxicos BM25 sobre la view; `post_action: vector_search` | — |

Restricciones del esquema que condicionan el YAML (verificadas): `PropertyDef.type` es un `Literal` cerrado sin `datetime` ni modelos anidados (de ahí `versions: list` "shape enforced in Python"); `AuthorizationRule` sólo admite `always | has_role | same_department | target_is_self | target_in_management_chain`; `SearchViewField.path` admite un nivel de anidamiento; los nombres de view y analyzers no pueden ser bind vars dentro de `SEARCH`.

## 5. Contrato de respuesta del agente

```python
class Citation(BaseModel):
    contract_id: str; title: str; node_id: str; page: Optional[int] = None
    quote: str; verification: Verification

class HandoffBrief(BaseModel):
    question: str
    why_judgment: str                          # una frase: por qué no es un lookup
    located_clauses: list[Citation]
    related_contracts: list[str] = Field(default_factory=list)
    suggested_owner: Optional[str] = None      # Bob, o el owner del contrato

class ContractAnswer(BaseModel):
    answer_kind: Literal["lookup", "interpretation_required", "not_found", "out_of_scope", "denied"]
    answer: Optional[str] = None               # sólo en lookup
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["verified", "mixed", "extracted"]   # mínimo común de las citas
    handoff: Optional[HandoffBrief] = None     # sólo en interpretation_required
    pattern: Optional[str] = None              # traversal usado, para el audit log

    @model_validator(mode="after")
    def _lookup_needs_citation(self):
        if self.answer_kind == "lookup" and not self.citations:
            raise ValueError("a lookup answer must carry at least one citation")
        return self
```

El triage `lookup` vs `interpretation_required` se decide con una clasificación de intención de conjunto cerrado (structured output mínimo, `Literal`) **antes** del retrieval; los `trigger_intents` de los patrones son el fast path. Las preguntas cuyo verbo es deóntico o evaluativo (*should we, can we, does this obligate, is X compliant, accept the redline*) se enrutan a hand-off aun cuando el retrieval encuentre las cláusulas — el brief las incluye.

## 6. Preguntas abiertas

1. **Granularidad de `Obligation`**: una por cláusula (muchas, precisas) o una por `kind` por contrato (pocas, agregadas). Propuesta: por cláusula, con `kind` cerrado; la agregación es una query.
2. **`ComplianceStandard` seed**: lista inicial (`soc2, iso27001, gdpr, ccpa, hipaa, pci_dss, nist_800_53, cyber_insurance`) — reutilizable del grafo de compliance del SecurityAdvisor.
3. **Identidad de `Party`**: slug del nombre legal colapsa "Acme Corp" / "Acme Corporation" sólo si se normalizan sufijos (`Inc|Corp|Corporation|Ltd|LLC|S.L.|S.A.`). Hace falta una tabla de alias curable por Bob.
4. **Owner / department**: no están en el documento. Fuentes candidatas: carpeta de SharePoint de origen (regla por ruta), metadata de la biblioteca de SharePoint (`Author`, columnas custom), o asignación manual en la cola de verificación.
5. **Postgres desde el piloto o después**: si el piloto tiene ≥ 3 usuarios concurrentes con roles, Postgres desde el día 1 (D8).

## 7. Corte de tareas v1

1. `contracts/models.py` (§1) + tests de validadores y de `brief()`.
2. `contracts/carding.py`: `select_carding_nodes`, prompts de las dos pasadas, `assemble_card` con derivaciones y proveniencia, `fallback_card_fields`. Tests con un MSA y un SOW sintéticos (md) sin LLM (fallback) y con adapter fake.
3. `contracts/catalog.py`: `ContractCatalogStore` + backend SQLite (esquema §3) + `expiring()`/`verification_queue()`.
4. `contracts/library.py`: `ContractLibrary.add_contract / verify_card / refresh_card / add_folder`, reutilizando `Bookstore._toolkit` (PageIndex) y `_docx_to_markdown`.
5. `contracts.ontology.yaml` en `defaults/domains/` + `ContractGraphLoader` (ficha → vértices/aristas, `versions[]`) + test de merge con `base` (`OntologyMerger.merge` + `_validate_integrity`).
6. `ContractsToolkit(AbstractToolkit, tool_prefix="contracts")`: `catalog_search`, `get_card`, `get_toc`, `read_section`, `obligations`, `expiring`, `verification_queue` (read-only) + `verify_card` (`confirming_tools`).
7. Backend Postgres del catálogo (D8) y el loop de delta de SharePoint — después del primer corte end-to-end.
