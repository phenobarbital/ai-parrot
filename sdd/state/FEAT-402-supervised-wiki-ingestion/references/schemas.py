"""Schemas para assisted ingestion de wikitoolkit (bosquejo).

Tres capas, en orden de aparición en el pipeline:

1. ``TriageOutput``      — lo que emite el LLM (structured output de ai-parrot).
                           Nota: el LLM puntúa dimensiones; el *composite* lo
                           calcula el código con los pesos del charter. Nunca
                           dejes que el modelo se auto-pondere.
2. ``ManifestDocEntry``  — TriageOutput + metadatos de pipeline (audit flag,
                           escalation, decisión humana). Es la fila del JSONL.
3. ``Charter``           — la política editorial (charter.yaml) validada.

Flujo: build --dry-run  → manifest.jsonl (decision=None en todas)
       humano edita     → rellena `decision` (o el TUI lo hace)
       build --review manifest.jsonl → ejecuta; en --auto solo se revisan
       las filas con audit=True y la agreement rate calibra la zona gris.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Action(str, Enum):
    """Destinos posibles de un documento. Rechazar no es borrar."""

    ADMIT = "admit"        # entra completo al wiki (todos sus claims)
    EXTRACT = "extract"    # entra parcialmente: solo los claims listados
    ARCHIVE = "archive"    # indexado y buscable, fuera del grafo del wiki
    DISCARD = "discard"    # no se conserva (spam, duplicado exacto, sensitive)
    DEFER = "defer"        # zona gris → decide el humano


class DecisionSource(str, Enum):
    AUTO = "auto"          # decidió el router (composite fuera de zona gris)
    HUMAN = "human"        # decidió el humano (defer, o edición del manifest)
    AUDIT = "audit"        # el humano confirmó/corrigió una decisión auto
                           # muestreada — es la señal de calibración


class AuditReason(str, Enum):
    UNIFORM = "uniform"                # muestreo aleatorio uniforme
    NEAR_THRESHOLD = "near_threshold"  # composite cerca de un umbral


class ClaimOp(str, Enum):
    ADD = "add"            # nuevo contenido en la página destino
    UPDATE = "update"      # corrige/actualiza contenido existente


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Capa 1 — salida del LLM (structured output)
# ---------------------------------------------------------------------------

class DimensionScores(BaseModel):
    """Puntuaciones por dimensión, [0, 1]. Las emite el LLM."""

    density: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    durability: float = Field(ge=0, le=1)

    def composite(self, weights: "ScoringWeights") -> float:
        """El código pondera; el LLM no ve los pesos."""
        return round(
            self.density * weights.density
            + self.novelty * weights.novelty
            + self.durability * weights.durability,
            4,
        )


class Claim(BaseModel):
    """Unidad de admisión: un hecho destilado con página destino."""

    claim_id: str
    text: str = Field(description="El hecho, autocontenido y datado si aplica")
    target_page: str = Field(description="Página del wiki destino (slug)")
    op: ClaimOp = ClaimOp.ADD
    score: float = Field(ge=0, le=1)
    status: ClaimStatus = ClaimStatus.PROPOSED
    source_span: Optional[str] = Field(
        default=None,
        description="Anclaje al documento fuente (p.ej. 'min 42-47' o offsets)",
    )


class TriageOutput(BaseModel):
    """Lo que el modelo de triage devuelve por documento.

    Este es el modelo que se pasa a ai-parrot como structured output.
    proposed_action la puede sugerir el LLM, pero el pipeline la
    recalcula desde composite + umbrales del charter (el LLM propone,
    los umbrales disponen).
    """

    doctype: str
    category: str
    briefing: str = Field(description="2-4 frases: qué es y qué contiene")
    scores: DimensionScores
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim] = Field(default_factory=list)
    review_flags: list[str] = Field(
        default_factory=list,
        description="p.ej. 'sensitive', 'charter_gap', 'possible_duplicate'",
    )
    defer_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Capa 2 — manifest JSONL
# ---------------------------------------------------------------------------

class NoveltyEvidence(BaseModel):
    """Vecino más cercano en el wiki actual (chequeo pre-LLM con PgVector)."""

    page: str
    similarity: float = Field(ge=0, le=1)


class ManifestDocEntry(BaseModel):
    """Una fila del manifest: TriageOutput + metadatos de pipeline."""

    kind: str = "doc"
    doc_id: str = Field(description="hash estable del contenido (sha256:…)")
    path: str
    doctype: str
    category: str
    briefing: str
    scores: dict[str, float] = Field(
        description="dimensiones + 'composite' (calculado, no del LLM)"
    )
    novelty_evidence: list[NoveltyEvidence] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    proposed_action: Action
    defer_reason: Optional[str] = None
    claims: list[Claim] = Field(default_factory=list)

    # --- lo que rellena el humano (o queda en auto) ---
    decision: Optional[Action] = Field(
        default=None,
        description="None en dry-run; el humano/auto la fija antes de aplicar",
    )
    decision_source: Optional[DecisionSource] = None
    decision_by: Optional[str] = None
    decision_note: Optional[str] = Field(
        default=None,
        description="Por qué el humano corrigió — alimenta few-shots/autotune",
    )

    # --- calibración ---
    audit: bool = False
    audit_reason: Optional[AuditReason] = None

    # --- provenance ---
    escalated: bool = False
    model: str
    charter_version: int

    @model_validator(mode="after")
    def _check(self) -> "ManifestDocEntry":
        if self.proposed_action is Action.DEFER and not self.defer_reason:
            raise ValueError("defer requiere defer_reason")
        if self.proposed_action is Action.EXTRACT and not self.claims:
            raise ValueError("extract sin claims no tiene sentido")
        if self.audit and self.audit_reason is None:
            raise ValueError("audit=True requiere audit_reason")
        if "composite" not in self.scores:
            raise ValueError("scores debe incluir 'composite'")
        return self


class RunStats(BaseModel):
    proposed: dict[str, int]
    escalated: int = 0
    audit_sample_size: int = 0


class RunCalibration(BaseModel):
    strategy: str
    near_threshold: int = 0
    uniform: int = 0
    prior_agreement: Optional[float] = Field(
        default=None, ge=0, le=1,
        description="agreement rate de la corrida anterior, si existe",
    )


class ManifestRunHeader(BaseModel):
    """Primera línea del JSONL: metadatos de la corrida."""

    kind: str = "run_header"
    run_id: str
    created_at: datetime
    source: dict
    charter: dict = Field(description="{name, version, sha256} — reproducibilidad")
    mode: str = Field(description="dry-run | auto | interactive | review")
    models: dict[str, str]
    stats: RunStats
    calibration: RunCalibration


# ---------------------------------------------------------------------------
# Capa 3 — charter.yaml
# ---------------------------------------------------------------------------

class ScopeRule(BaseModel):
    id: str
    description: str


class ScoringWeights(BaseModel):
    density: float
    novelty: float
    durability: float

    @model_validator(mode="after")
    def _sum_to_one(self) -> "ScoringWeights":
        total = self.density + self.novelty + self.durability
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"los pesos deben sumar 1.0 (suman {total})")
        return self


class Dimension(BaseModel):
    weight: float = Field(ge=0, le=1)
    description: str


class Thresholds(BaseModel):
    admit: float = Field(ge=0, le=1)
    reject: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "Thresholds":
        if self.reject >= self.admit:
            raise ValueError("reject debe ser < admit (si no, no hay zona gris)")
        return self

    def route(self, composite: float) -> Action:
        if composite >= self.admit:
            return Action.ADMIT
        if composite <= self.reject:
            return Action.ARCHIVE  # default_reject_destination del charter
        return Action.DEFER


class AuditSample(BaseModel):
    rate: float = Field(gt=0, le=1)
    strategy: str = "stratified"
    near_threshold_fraction: float = 0.6
    uniform_fraction: float = 0.4

    @model_validator(mode="after")
    def _fractions(self) -> "AuditSample":
        if self.strategy == "stratified":
            total = self.near_threshold_fraction + self.uniform_fraction
            if abs(total - 1.0) > 1e-6:
                raise ValueError("las fracciones del estratificado deben sumar 1")
        return self


class Calibration(BaseModel):
    audit_sample: AuditSample
    min_agreement: float = Field(ge=0, le=1)
    on_low_agreement: str = "widen_gray_zone"   # widen_gray_zone | halt | warn
    gray_zone_step: float = 0.05
    autotune: str = "propose"                   # off | propose | apply


class CharterExample(BaseModel):
    summary: str
    why: str
    destination: Optional[str] = None


class Amendment(BaseModel):
    version: int
    date: date  # YAML ya parsea fechas ISO como date
    change: str
    source: str


class Charter(BaseModel):
    """charter.yaml validado. Se serializa (sin ejemplos largos) al prompt
    del triage; el sha256 del fichero viaja en el run_header."""

    name: str
    version: int
    language: str = "en"
    description: str
    audience: str
    scope: dict[str, list[ScopeRule]]
    scoring_dimensions: dict[str, Dimension] = Field(alias="dimensions")
    thresholds: Thresholds
    routing: dict
    calibration: Calibration
    examples: dict[str, list[CharterExample]] = Field(default_factory=dict)
    examples_file: Optional[str] = None
    amendments: list[Amendment] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def weights(self) -> ScoringWeights:
        return ScoringWeights(
            **{k: v.weight for k, v in self.scoring_dimensions.items()}
        )


# ---------------------------------------------------------------------------
# Calibración post-review (bosquejo de la mecánica, no del schema)
# ---------------------------------------------------------------------------

def agreement_rate(entries: list[ManifestDocEntry]) -> Optional[float]:
    """Acuerdo humano↔router sobre la muestra auditada.

    Cuenta solo filas audit=True ya decididas. Acuerdo = la decisión humana
    coincide con la proposed_action. Con esto:
      - rate >= charter.calibration.min_agreement → se mantiene la zona gris
      - rate <  min_agreement → widen_gray_zone (admit += step, reject -= step)
        y los desacuerdos (con decision_note) se vuelven candidatos a
        few-shots / enmiendas del charter.
    """
    audited = [
        e for e in entries
        if e.audit and e.decision is not None
    ]
    if not audited:
        return None
    agreed = sum(1 for e in audited if e.decision == e.proposed_action)
    return round(agreed / len(audited), 4)
