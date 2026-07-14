---
type: Wiki Summary
title: parrot_tools.codeinterpreter.models
id: mod:parrot_tools.codeinterpreter.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.codeinterpreter.models
relates_to:
- concept: class:parrot_tools.codeinterpreter.models.BaseCodeResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.BugIssue
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.ClassComponent
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.CodeAnalysisResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.CodeFlowStep
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.CodeReference
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.ComplexityMetrics
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.ConceptExplanation
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.CoverageGap
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.DebugResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.Dependency
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.DocstringFormat
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.DocumentationResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.DocumentedElement
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.ExecutionStatus
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.ExplanationResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.FunctionComponent
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.GeneratedTest
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.OperationType
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.QualityObservation
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.Severity
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.TestGenerationResponse
  rel: defines
- concept: class:parrot_tools.codeinterpreter.models.TestType
  rel: defines
---

# `parrot_tools.codeinterpreter.models`

## Classes

- **`OperationType(str, Enum)`** — Tipos de operaciones soportadas por el CodeInterpreterTool
- **`ExecutionStatus(str, Enum)`** — Estados posibles de ejecución
- **`Severity(str, Enum)`** — Niveles de severidad para issues detectados
- **`CodeReference(BaseModel)`** — Referencias a ubicaciones específicas en código fuente
- **`BaseCodeResponse(BaseModel)`** — Modelo base para todas las respuestas del CodeInterpreterTool
- **`ComplexityMetrics(BaseModel)`** — Métricas de complejidad del código
- **`FunctionComponent(BaseModel)`** — Información sobre una función identificada en el código
- **`ClassComponent(BaseModel)`** — Información sobre una clase identificada en el código
- **`Dependency(BaseModel)`** — Información sobre una dependencia externa
- **`QualityObservation(BaseModel)`** — Observación sobre calidad del código
- **`CodeAnalysisResponse(BaseCodeResponse)`** — Respuesta completa para operación de análisis de código
- **`DocstringFormat(str, Enum)`** — Formatos soportados de docstrings
- **`DocumentedElement(BaseModel)`** — Elemento individual que ha sido documentado
- **`DocumentationResponse(BaseCodeResponse)`** — Respuesta completa para operación de generación de documentación
- **`TestType(str, Enum)`** — Tipos de tests generados
- **`GeneratedTest(BaseModel)`** — Información sobre un test generado
- **`CoverageGap(BaseModel)`** — Brecha en cobertura de tests
- **`TestGenerationResponse(BaseCodeResponse)`** — Respuesta completa para operación de generación de tests
- **`BugIssue(BaseModel)`** — Issue o bug potencial identificado
- **`DebugResponse(BaseCodeResponse)`** — Respuesta completa para operación de detección de bugs
- **`CodeFlowStep(BaseModel)`** — Paso individual en el flujo de ejecución
- **`ConceptExplanation(BaseModel)`** — Explicación de un concepto técnico utilizado
- **`ExplanationResponse(BaseCodeResponse)`** — Respuesta completa para operación de explicación de código
