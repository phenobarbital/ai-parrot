---
id: F010
query_id: Q001
type: read
intent: Verificar soporte vigente de herramientas Nova 2 Sonic
executed_at: 2026-09-07T05:36:39.417510+00:00
parent_id: F005
depth: 2
---

# F010 — Contrato oficial AWS

## Summary

AWS documenta tool-calling de Nova 2 Sonic y el retorno de toolResult para cada toolUse, incluso ante errores. La aplicación ejecuta la herramienta y Nova incorpora el resultado a su respuesta hablada. Esto respalda la viabilidad de conservar audio y un canal visual de aplicación; no acredita JSON-schema output nativo simultáneo con audio.

## Citations

- url: https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-tool-configuration.html
  title: Tool configuration — Amazon Nova 2
  accessed: 2026-09-07
  sections: Receiving and processing tool use events; Best practices

## Notes

El riesgo de espera circular de F005 es una inferencia de código + contrato, no un fallo reproducido contra AWS. No se propone cambiar la serialización del protocolo basándose en ejemplos simplificados de documentación.
