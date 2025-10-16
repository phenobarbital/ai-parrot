from typing import Literal, Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from pydantic import BaseModel, Field, field_validator, ConfigDict


class OperationType(str, Enum):
    """Tipos de operaciones soportadas por el CodeInterpreterTool"""
    ANALYZE = "analyze"
    DOCUMENT = "document"
    TEST = "test"
    DEBUG = "debug"
    EXPLAIN = "explain"


class ExecutionStatus(str, Enum):
    """Estados posibles de ejecución"""
    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_with_warnings"
    FAILED = "failed"


class Severity(str, Enum):
    """Niveles de severidad para issues detectados"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CodeReference(BaseModel):
    """Referencias a ubicaciones específicas en código fuente"""
    file_path: Optional[str] = Field(
        None,
        description="Ruta al archivo fuente, si está disponible"
    )
    start_line: int = Field(
        ...,
        ge=1,
        description="Línea inicial (1-indexed)"
    )
    end_line: int = Field(
        ...,
        ge=1,
        description="Línea final (1-indexed)"
    )
    code_snippet: str = Field(
        ...,
        description="Fragmento de código referenciado"
    )

    @field_validator('end_line')
    @classmethod
    def validate_line_range(cls, v, info):
        if 'start_line' in info.data and v < info.data['start_line']:
            raise ValueError('end_line debe ser mayor o igual a start_line')
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


class BaseCodeResponse(BaseModel):
    """Modelo base para todas las respuestas del CodeInterpreterTool"""
    operation_id: UUID = Field(
        default_factory=uuid4,
        description="Identificador único de la operación"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp de ejecución en UTC"
    )
    operation_type: OperationType = Field(
        ...,
        description="Tipo de operación realizada"
    )
    status: ExecutionStatus = Field(
        ...,
        description="Estado de ejecución de la operación"
    )
    execution_time_ms: int = Field(
        ...,
        ge=0,
        description="Tiempo de ejecución en milisegundos"
    )
    code_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hash del código analizado"
    )
    language: str = Field(
        default="python",
        description="Lenguaje del código analizado"
    )
    error_message: Optional[str] = Field(
        None,
        description="Mensaje de error si status es FAILED"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Advertencias generadas durante la ejecución"
    )

    model_config = ConfigDict(
        use_enum_values=True,
        str_strip_whitespace=True
    )


class ComplexityMetrics(BaseModel):
    """Métricas de complejidad del código"""
    cyclomatic_complexity: int = Field(
        ...,
        ge=1,
        description="Complejidad ciclomática calculada"
    )
    lines_of_code: int = Field(
        ...,
        ge=0,
        description="Líneas de código (excluyendo comentarios y blanks)"
    )
    cognitive_complexity: Optional[int] = Field(
        None,
        ge=0,
        description="Score de complejidad cognitiva"
    )
    maintainability_index: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Índice de mantenibilidad (0-100)"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class FunctionComponent(BaseModel):
    """Información sobre una función identificada en el código"""
    name: str = Field(..., description="Nombre de la función")
    signature: str = Field(..., description="Signatura completa con tipos")
    purpose: str = Field(..., description="Propósito de la función")
    parameters: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping de nombre de parámetro a descripción"
    )
    return_type: str = Field(..., description="Tipo de retorno")
    return_description: str = Field(
        ...,
        description="Descripción del valor de retorno"
    )
    side_effects: List[str] = Field(
        default_factory=list,
        description="Side effects observables"
    )
    location: CodeReference = Field(
        ...,
        description="Ubicación en el código fuente"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class ClassComponent(BaseModel):
    """Información sobre una clase identificada en el código"""
    name: str = Field(..., description="Nombre de la clase")
    purpose: str = Field(..., description="Propósito de la clase")
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping de nombre de atributo a descripción con tipo"
    )
    methods: List[str] = Field(
        default_factory=list,
        description="Lista de métodos públicos con descripciones concisas"
    )
    inheritance: List[str] = Field(
        default_factory=list,
        description="Clases padre de las que hereda"
    )
    relationships: Dict[str, str] = Field(
        default_factory=dict,
        description="Relaciones con otras clases (composición, agregación)"
    )
    location: CodeReference = Field(
        ...,
        description="Ubicación en el código fuente"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class Dependency(BaseModel):
    """Información sobre una dependencia externa"""
    name: str = Field(..., description="Nombre del módulo o paquete")
    version: Optional[str] = Field(
        None,
        description="Versión específica si es detectable"
    )
    dependency_type: Literal["stdlib", "third_party", "internal"] = Field(
        ...,
        description="Tipo de dependencia"
    )
    usage_description: str = Field(
        ...,
        description="Cómo se utiliza la dependencia"
    )
    coupling_level: Literal["tight", "moderate", "loose"] = Field(
        ...,
        description="Nivel de acoplamiento"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class QualityObservation(BaseModel):
    """Observación sobre calidad del código"""
    category: Literal["strength", "improvement"] = Field(
        ...,
        description="Si es una fortaleza o área de mejora"
    )
    title: str = Field(..., description="Título conciso de la observación")
    description: str = Field(
        ...,
        description="Descripción detallada y específica"
    )
    impact: Literal["high", "medium", "low"] = Field(
        ...,
        description="Impacto de la observación"
    )
    actionable_suggestion: Optional[str] = Field(
        None,
        description="Sugerencia accionable si es mejora"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class CodeAnalysisResponse(BaseCodeResponse):
    """Respuesta completa para operación de análisis de código"""
    operation_type: Literal[OperationType.ANALYZE] = OperationType.ANALYZE

    executive_summary: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Resumen ejecutivo del propósito del código"
    )
    detailed_purpose: str = Field(
        ...,
        description="Descripción detallada de funcionalidad y contexto"
    )
    functions: List[FunctionComponent] = Field(
        default_factory=list,
        description="Funciones identificadas en el código"
    )
    classes: List[ClassComponent] = Field(
        default_factory=list,
        description="Clases identificadas en el código"
    )
    dependencies: List[Dependency] = Field(
        default_factory=list,
        description="Dependencias externas identificadas"
    )
    complexity_metrics: ComplexityMetrics = Field(
        ...,
        description="Métricas de complejidad del código"
    )
    quality_observations: List[QualityObservation] = Field(
        default_factory=list,
        description="Observaciones sobre calidad del código"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocstringFormat(str, Enum):
    """Formatos soportados de docstrings"""
    GOOGLE = "google"
    NUMPY = "numpy"
    SPHINX = "sphinx"


class DocumentedElement(BaseModel):
    """Elemento individual que ha sido documentado"""
    element_type: Literal["function", "class", "method", "module"] = Field(
        ...,
        description="Tipo de elemento documentado"
    )
    element_name: str = Field(
        ...,
        description="Nombre del elemento"
    )
    location: CodeReference = Field(
        ...,
        description="Ubicación en el código fuente"
    )
    generated_docstring: str = Field(
        ...,
        description="Docstring generado"
    )
    justification: Optional[str] = Field(
        None,
        description="Justificación de decisiones no obvias"
    )
    cross_references: List[str] = Field(
        default_factory=list,
        description="Referencias a otros elementos relacionados"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentationResponse(BaseCodeResponse):
    """Respuesta completa para operación de generación de documentación"""
    operation_type: Literal[OperationType.DOCUMENT] = OperationType.DOCUMENT

    docstring_format: DocstringFormat = Field(
        ...,
        description="Formato de docstring utilizado"
    )
    modified_code: str = Field(
        ...,
        description="Código con docstrings insertados"
    )
    documented_elements: List[DocumentedElement] = Field(
        default_factory=list,
        description="Elementos que fueron documentados"
    )
    module_documentation: Optional[str] = Field(
        None,
        description="Documentación de nivel módulo en markdown"
    )
    documentation_coverage: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Porcentaje de elementos documentados"
    )
    saved_files: List[str] = Field(
        default_factory=list,
        description="Rutas de archivos guardados con documentación"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class TestType(str, Enum):
    """Tipos de tests generados"""
    UNIT = "unit"
    INTEGRATION = "integration"
    PROPERTY_BASED = "property_based"
    REGRESSION = "regression"


class GeneratedTest(BaseModel):
    """Información sobre un test generado"""
    name: str = Field(
        ...,
        description="Nombre descriptivo del test"
    )
    test_type: TestType = Field(
        ...,
        description="Tipo de test"
    )
    test_code: str = Field(
        ...,
        description="Código fuente completo del test"
    )
    fixtures_required: List[str] = Field(
        default_factory=list,
        description="Fixtures requeridas para ejecutar el test"
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="Dependencias adicionales para el test"
    )
    estimated_coverage: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Porcentaje estimado de cobertura"
    )
    covers_lines: List[int] = Field(
        default_factory=list,
        description="Líneas del código original cubiertas"
    )
    is_edge_case: bool = Field(
        default=False,
        description="Si el test cubre un edge case"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class CoverageGap(BaseModel):
    """Brecha en cobertura de tests"""
    location: CodeReference = Field(
        ...,
        description="Ubicación del código no cubierto"
    )
    gap_type: Literal["branch", "line", "condition"] = Field(
        ...,
        description="Tipo de brecha en cobertura"
    )
    description: str = Field(
        ...,
        description="Descripción de qué no está cubierto"
    )
    suggested_test: Optional[str] = Field(
        None,
        description="Sugerencia de test adicional"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class TestGenerationResponse(BaseCodeResponse):
    """Respuesta completa para operación de generación de tests"""
    operation_type: Literal[OperationType.TEST] = OperationType.TEST

    test_framework: str = Field(
        default="pytest",
        description="Framework de testing utilizado"
    )
    generated_tests: List[GeneratedTest] = Field(
        default_factory=list,
        description="Tests generados"
    )
    test_file_path: Optional[str] = Field(
        None,
        description="Ruta del archivo de tests generado"
    )
    overall_coverage: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Cobertura total estimada"
    )
    coverage_gaps: List[CoverageGap] = Field(
        default_factory=list,
        description="Brechas en cobertura identificadas"
    )
    setup_instructions: Optional[str] = Field(
        None,
        description="Instrucciones para ejecutar los tests"
    )
    saved_files: List[str] = Field(
        default_factory=list,
        description="Archivos guardados con tests"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class BugIssue(BaseModel):
    """Issue o bug potencial identificado"""
    severity: Severity = Field(
        ...,
        description="Severidad del issue"
    )
    category: str = Field(
        ...,
        description="Categoría del bug (logic, exception_handling, etc.)"
    )
    title: str = Field(
        ...,
        description="Título conciso del issue"
    )
    location: CodeReference = Field(
        ...,
        description="Ubicación exacta del problema"
    )
    description: str = Field(
        ...,
        description="Explicación detallada del problema"
    )
    trigger_scenario: str = Field(
        ...,
        description="Escenario específico que triggerea el bug"
    )
    expected_behavior: str = Field(
        ...,
        description="Comportamiento esperado correcto"
    )
    actual_behavior: str = Field(
        ...,
        description="Comportamiento observable incorrecto"
    )
    suggested_fix: str = Field(
        ...,
        description="Código o descripción de la solución propuesta"
    )
    fix_diff: Optional[str] = Field(
        None,
        description="Diff del cambio propuesto si está disponible"
    )
    alternative_solutions: List[str] = Field(
        default_factory=list,
        description="Soluciones alternativas con trade-offs"
    )
    impact_analysis: str = Field(
        ...,
        description="Análisis del impacto del bug"
    )
    likelihood: Literal["high", "medium", "low"] = Field(
        ...,
        description="Probabilidad de que se manifieste en producción"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DebugResponse(BaseCodeResponse):
    """Respuesta completa para operación de detección de bugs"""
    operation_type: Literal[OperationType.DEBUG] = OperationType.DEBUG

    issues_found: List[BugIssue] = Field(
        default_factory=list,
        description="Issues potenciales identificados"
    )
    critical_count: int = Field(
        default=0,
        ge=0,
        description="Número de issues críticos"
    )
    high_count: int = Field(
        default=0,
        ge=0,
        description="Número de issues high severity"
    )
    medium_count: int = Field(
        default=0,
        ge=0,
        description="Número de issues medium severity"
    )
    low_count: int = Field(
        default=0,
        ge=0,
        description="Número de issues low severity"
    )
    static_analysis_results: Optional[Dict[str, Any]] = Field(
        None,
        description="Resultados de herramientas de análisis estático"
    )
    priority_order: List[int] = Field(
        default_factory=list,
        description="Índices de issues_found en orden de prioridad"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class CodeFlowStep(BaseModel):
    """Paso individual en el flujo de ejecución"""
    step_number: int = Field(
        ...,
        ge=1,
        description="Número del paso en secuencia"
    )
    location: CodeReference = Field(
        ...,
        description="Ubicación del paso en código"
    )
    description: str = Field(
        ...,
        description="Descripción de qué hace este paso"
    )
    purpose: str = Field(
        ...,
        description="Propósito del paso en el algoritmo mayor"
    )
    data_transformation: Optional[str] = Field(
        None,
        description="Cómo se transforman los datos en este paso"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class ConceptExplanation(BaseModel):
    """Explicación de un concepto técnico utilizado"""
    concept_name: str = Field(
        ...,
        description="Nombre del concepto técnico"
    )
    simplified_explanation: str = Field(
        ...,
        description="Explicación simplificada del concepto"
    )
    code_example: Optional[str] = Field(
        None,
        description="Ejemplo de código simplificado"
    )
    usage_in_analyzed_code: str = Field(
        ...,
        description="Cómo se usa el concepto en el código analizado"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class ExplanationResponse(BaseCodeResponse):
    """Respuesta completa para operación de explicación de código"""
    operation_type: Literal[OperationType.EXPLAIN] = OperationType.EXPLAIN

    analogy: Optional[str] = Field(
        None,
        description="Analogía o metáfora para facilitar comprensión"
    )
    high_level_summary: str = Field(
        ...,
        description="Resumen de alto nivel del código"
    )
    execution_flow: List[CodeFlowStep] = Field(
        default_factory=list,
        description="Flujo de ejecución paso a paso"
    )
    key_concepts: List[ConceptExplanation] = Field(
        default_factory=list,
        description="Conceptos técnicos clave explicados"
    )
    data_structures_used: Dict[str, str] = Field(
        default_factory=dict,
        description="Estructuras de datos utilizadas con explicaciones"
    )
    algorithm_description: Optional[str] = Field(
        None,
        description="Descripción del algoritmo si es relevante"
    )
    complexity_analysis: Optional[str] = Field(
        None,
        description="Análisis de complejidad temporal y espacial"
    )
    visualization: Optional[str] = Field(
        None,
        description="Diagrama ASCII o visualización textual"
    )
    user_expertise_level: Literal["beginner", "intermediate", "advanced"] = Field(
        default="intermediate",
        description="Nivel de expertise asumido del usuario"
    )

    model_config = ConfigDict(str_strip_whitespace=True)
