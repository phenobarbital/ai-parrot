---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: ShellTool Hardening — integración `rtk` con guard anti-bypass

**Date**: 2026-07-27
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

> **Origen**: capability `shell-rtk-integration` escindida de
> `sdd/proposals/sandbox-hardening.brainstorm.md` por decisión del usuario
> (2026-07-27). El worker persistente del REPL sigue viviendo en aquel
> documento; este cubre **solo** la superficie de `ShellTool`.

---

## Problem Statement

`ShellTool` (`packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`) ejecuta comandos de desarrollo cuyo stdout se devuelve **íntegro** al LLM. Comandos rutinarios — `pytest`, `npm install`, compilaciones, linters — producen salidas de miles de tokens de las que el agente usa una fracción: el resumen final, las líneas de error, el exit code. Ese volumen infla el contexto, encarece cada turno y entierra la señal.

El ecosistema ya validó la solución: **RTK** (`rtk-ai/rtk`, Apache-2.0, Rust) demuestra reducciones del 60–90% sobre salida de comandos de desarrollo conocidos, con un mecanismo `tee` que preserva la salida completa cuando el comando falla (análisis previo en `sdd/proposals/brainstorm-tool-result-compression.md:37-67`). RTK es un **crate binario**, no una librería enlazable: la integración correcta es invocarlo como prefijo de comando (`rtk test pytest ...`), no vía FFI.

### El requisito de seguridad que condiciona todo

`rtk <cualquier-comando>` es un **envoltorio universal de ejecución**. El sanitizer de `ShellTool` valida el **comando base** contra un allowlist (`_check_command_access`, `parrot/security/command_sanitizer.py:827-856`) — si `rtk` entrara en ese allowlist, el sanitizer validaría `rtk` y **no vería lo que rtk va a ejecutar**. Un solo prefijo anularía el allowlist entero, incluida la validación por segmentos de pipe (`_check_pipe_segments`, `:858-885`).

El orden actual del código es el correcto y es la base de la solución: `assert_command_safe()` valida el comando original en `tool.py:146` (modo comando) y `:254` (modo plan), **antes** de que `_make_action_from_cmdobj` (`:167-198`) construya la acción. Insertar el prefijo después de la validación hace que el sanitizer siempre vea el comando real.

### Por qué ahora

- El brainstorm de compresión de `ToolResult` está congelado hasta que aterrice el sandbox del REPL; esta pieza es **totalmente independiente** de ambos (otro paquete, otro fichero, cero código compartido) y puede avanzar en paralelo desde hoy.
- La decisión de equipo (2026-07-27) es que rtk sea **dependencia dura** de `ShellTool`: cuanto antes se fije el contrato, antes pueden prepararse los despliegues.

### Fuera de alcance

- El worker persistente del REPL (`sandbox-hardening.brainstorm.md`).
- La integración de rtk con `ClaudeAgentClient` (`rtk init` en el entorno del sub-agente del CLI `claude`) — sigue siendo el seguimiento independiente `rtk-subprocess-filter` anotado en `brainstorm-tool-result-compression.md:458`. **Decisión del usuario: se mantiene fuera.**
- Filtrar salida arbitraria del REPL — RTK filtra comandos de desarrollo conocidos, no stdout arbitrario (ya descartado en ambos brainstorms previos).

---

## Constraints & Requirements

Decisiones tomadas interactivamente con el usuario (2026-07-27):

- **S1 — rtk es dependencia dura, activada por defecto, sin escape hatch.** `ShellTool` **falla en `__init__`** si el binario `rtk` no está disponible. No existe flag para desactivar el wrapping. `pip install` + `ShellTool()` en una máquina sin rtk es un error explícito de despliegue, no una degradación silenciosa.
- **S2 — El fallo aflora en init, no en el primer comando.** Probe con `shutil.which("rtk")` + chequeo de versión en el constructor, siguiendo el patrón existente de `set_security_policy()` en `tool.py:59-64`. El operador se entera al desplegar, no el LLM a mitad de conversación.
- **S3 — Versión mínima verificada.** `rtk --version` en el probe; se exige un mínimo probado y se **avisa** (no falla) con versiones más nuevas no probadas. La instalación documentada fija la release probada.
- **S4 — Mapa de comandos conocidos.** Solo se envuelven comandos presentes en un mapa mantenido (`comando → subcomando rtk`); todo lo demás corre sin envolver. Nada de `rtk proxy` universal: filtrado genérico sobre salida desconocida arriesga perder información que el agente necesitaba.
- **S5 — Salida completa en fallo.** El filtrado aplica solo a ejecuciones exitosas. Con exit code ≠ 0 el agente recibe stdout/stderr **completos** (mecanismo `tee` de rtk). La fidelidad de depuración se preserva exactamente cuando importa.
- **S6 — `rtk` se rechaza como entrada.** `rtk` nunca entra en ningún allowlist y el sanitizer lo **deniega** explícitamente como comando escrito por agente/usuario. El prefijo lo añade solo la herramienta, después de la validación. Sin strip-and-revalidate: el agente no tiene ninguna razón legítima para escribir `rtk`.
- **S7 — Reescritura prefijo-pura.** La transformación es estrictamente `cmd` → `rtk <subcmd> cmd`. Nunca una reescritura que pueda reintroducir algo que el sanitizer rechazó. Cualquier transformación más lista que un prefijo exigiría revalidar el resultado.
- **S8 — Contrato de salida intacto.** `_result_to_dict()` (`tool.py:200-212`) conserva su forma. El wrapping es transparente para el consumidor del resultado; a lo sumo se añade metadata (`rtk_wrapped: bool`).

---

## Options Explored

### Option A: Filtrado nativo en Python (sin binario)

Reimplementar en Python la reducción de salida por comando (parsers de pytest/npm/cargo, truncado con contexto, deduplicación), enganchada al post-procesado del `ActionResult`, reutilizando la arquitectura del brainstorm de compresión de `ToolResult`.

✅ **Pros:**
- Cero dependencias de despliegue: funciona en cualquier `pip install`.
- Sin superficie de bypass — no hay binario envoltorio que denegar.
- El filtrado vive donde el resto del pipeline de resultados del framework.

❌ **Cons:**
- **Reimplementa el conocimiento por-comando de rtk**, que es justo la parte cara: parsers y heurísticas mantenidas por comando y por versión de herramienta. Es asumir un mantenimiento permanente que upstream ya hace gratis.
- El pipeline de compresión de `ToolResult` está **congelado por decisión de equipo** hasta que aterrice el sandbox del REPL; construir sobre él ahora contradice esa decisión.
- Se pierde `tee` y la telemetría de ahorro (`rtk gain`) ya resueltas upstream.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — (stdlib) | parsers + truncado | todo el conocimiento por-comando hay que escribirlo y mantenerlo |

🔗 **Existing Code to Reuse:**
- `sdd/proposals/brainstorm-tool-result-compression.md` — arquitectura de codecs (congelada as-is)

---

### Option B: Prefijo `rtk` en `_make_action_from_cmdobj` + guard en el sanitizer

El punto de inserción es `_make_action_from_cmdobj` (`tool.py:167-198`): la validación ya ocurrió sobre el comando real (`:146`, `:254`), y ahí se decide el tipo de acción. Un mapa `comando base → subcomando rtk` decide si `RunCommand` recibe `cmd` o `rtk <subcmd> cmd`. En paralelo, `rtk` se añade a los comandos denegados del sanitizer en core (`parrot/security/command_sanitizer.py`) para que ningún agente pueda escribirlo directamente.

✅ **Pros:**
- **Mínimo cambio con máximo apalancamiento**: el binario upstream hace el trabajo; ai-parrot solo decide cuándo invocarlo y garantiza que no sea un bypass.
- El orden validar-luego-prefijar ya existe en el código — no hay que reordenar nada (S7 sale casi gratis).
- `tee` y el modo fallo-salida-completa (S5) vienen resueltos por rtk.
- El guard (S6) es una línea en `_DEFAULT_DENIED_COMMANDS` + tests; protege también a cualquier otro consumidor de `CommandSanitizer` (es el sanitizer de core desde FEAT-252).
- Independiente al 100% del trabajo del sandbox del REPL — puede ir en paralelo.

❌ **Cons:**
- **Dependencia dura de despliegue** (decisión S1): todo entorno que instancie `ShellTool` — dev local, CI, docker — debe aprovisionar el binario. Es un breaking change operativo real y hay que tratarlo como tal (docs, imágenes, mensaje de error con instrucciones).
- La superficie CLI de rtk cambia cada pocas semanas; el mapa de comandos y el mínimo de versión son artefactos mantenidos (mitigado por S3).
- Con `security_policy=None` explícito no hay sanitizer (`tool.py:64`) y el guard S6 no aplica en esa instancia — ya es el modo "todo permitido" documentado, pero conviene dejarlo escrito.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rtk` (binario) | filtrado de salida por comando | `rtk-ai/rtk`, Apache-2.0, Rust. **Crate binario, no librería.** Release cada pocas semanas → versión mínima fijada (S3). No instalado en dev actualmente — verificado |
| `shutil.which` | probe de disponibilidad | stdlib |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py:167-198` — `_make_action_from_cmdobj`, punto de inserción del prefijo
- `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py:145-146, 254` — `assert_command_safe()` antes de construir la acción; el orden se preserva
- `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py:50-64` — patrón de configuración en `__init__` (el probe de rtk va aquí)
- `parrot/security/command_sanitizer.py:170` — `_DEFAULT_DENIED_COMMANDS`, destino del guard S6
- `parrot/security/command_sanitizer.py:770` — `_extract_base_command()`, ya normaliza rutas (`/usr/bin/rtk` → `rtk`), el deny cubre variantes con ruta
- `packages/ai-parrot-tools/tests/shell_tool/` — suites existentes de seguridad donde anclar los tests del guard

---

### Option C (no convencional): Directorio shim en PATH

No tocar los comandos: generar un directorio de shims (`pytest` → script que hace `exec rtk test pytest "$@"`) y anteponerlo al `PATH` del entorno de las acciones. Los comandos se envuelven "solos" al resolverse en el shim.

✅ **Pros:**
- Cero reescritura de comandos — el sanitizer ve siempre exactamente lo que se ejecuta, S7 trivialmente satisfecho.
- Envuelve también invocaciones anidadas (un script que llama a `pytest` por dentro).

❌ **Cons:**
- **Invisible y mágico**: el comando registrado en logs/resultados ya no es lo que corrió de verdad. Auditar qué se ejecutó exige conocer el estado del directorio shim.
- Las acciones corren vía `/bin/sh -lc` (`actions.py:14`) — shells de login pueden reordenar `PATH` (profile, rc files) y romper el shim de forma no determinista por máquina.
- El agente puede fijar `env` por comando (`CommandObject.env`), pisando el `PATH` shim — el wrapping se vuelve evadible *hacia fuera* (perder el filtrado silenciosamente).
- Gestión de ciclo de vida de un directorio generado (staleness cuando cambia el mapa, permisos, tmpfs).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rtk` (binario) | igual que B | — |
| `tempfile` / bootstrap | generación del dir shim | stdlib |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/shell_tool/models.py:187, 270` — construcción de env del subproceso

---

## Recommendation

**Option B.**

Contra A: el valor de rtk es precisamente el conocimiento por-comando mantenido upstream; reimplementarlo es comprar el mantenimiento sin el beneficio, y además construiría sobre un pipeline congelado por decisión de equipo.

Contra C: un shim en PATH viola el principio que gobierna este diseño — que **lo validado y lo ejecutado sean la misma cadena visible**. B mantiene la transformación en un único punto auditable (`_make_action_from_cmdobj`), con la validación ya hecha y el prefijo declarado en la metadata del resultado. C, además, es evadible vía `CommandObject.env` en la dirección mala (perder el filtrado sin que nadie lo note).

**Lo que se sacrifica, explícitamente** (decisión S1, confirmada dos veces con el usuario): `ShellTool` deja de funcionar sin rtk instalado. Es un breaking change operativo — dev local, CI y docker deben aprovisionar el binario antes de actualizar. Se acepta a cambio de un comportamiento uniforme: nunca habrá dos despliegues donde el mismo agente vea salidas distintas según si rtk estaba o no. El coste se mitiga con un mensaje de init accionable (instrucciones de instalación + versión mínima) y documentación de despliegue.

---

## Feature Description

### Arquitectura

```
  agente → ShellTool._execute()
              │
              ├ _run_commands / _run_plan
              │     └ assert_command_safe(comando_real)     ← sanitizer ve SIEMPRE el comando real
              │           └ deny: rtk                        ← guard S6 (en core sanitizer)
              │
              └ _make_action_from_cmdobj(spec)
                    ├ base_cmd ∈ RTK_COMMAND_MAP?
                    │     sí → cmd = "rtk <subcmd> " + cmd   ← único punto de inserción (S7)
                    │     no → cmd sin cambios
                    └ RunCommand(cmd, ...)                   ← /bin/sh -lc, sin cambios

  ShellTool.__init__:
     probe rtk (shutil.which + rtk --version)
        ├ ausente          → RuntimeError con instrucciones de instalación (S1/S2)
        ├ < versión mínima → RuntimeError (S3)
        └ > versión probada→ warning en log, continúa (S3)
```

### User-Facing Behavior

- **Para el agente LLM**: la salida de comandos conocidos (`pytest`, `npm`, etc.) llega reducida 60–90% en ejecuciones exitosas; en fallo llega completa (S5). Si el agente intenta ejecutar `rtk ...` directamente, recibe el mismo `CommandSecurityError` que cualquier comando denegado.
- **Para el desarrollador que despliega**: rtk pasa a ser requisito de instalación de `ShellTool`. El error de init dice exactamente qué instalar y qué versión mínima. Documentación nueva de aprovisionamiento (incl. Dockerfile de ejemplo).
- **Para el operador**: metadata `rtk_wrapped` en cada resultado; los logs muestran el comando original y el envuelto.

### Internal Behavior

1. `__init__` proba el binario una vez (S2): ausencia o versión insuficiente → excepción; versión más nueva que la probada → warning. El resultado del probe se cachea en la instancia.
2. `assert_command_safe()` corre exactamente donde hoy (`:146`, `:254`), sobre el comando original. El guard S6 vive en `_DEFAULT_DENIED_COMMANDS` del sanitizer de core, con lo que aplica a los tres niveles (RESTRICTIVE/MODERATE/PERMISSIVE) y a cualquier otro consumidor del sanitizer.
3. `_make_action_from_cmdobj` consulta el mapa con el comando base ya validado. Solo candidatos a `RunCommand` sin operadores de shell (sin `|`, `;`, `&&`) son envolvibles — un pipe envuelto rompería la garantía prefijo-pura sobre qué proceso recibe qué. `ExecFile` y `ListFiles` nunca se envuelven.
4. En fallo del comando envuelto, la salida completa preservada por el `tee` de rtk es lo que viaja en `stdout`/`stderr` del `ActionResult` (S5). Verificar el mecanismo exacto contra la release fijada es tarea de spec.

### Edge Cases & Error Handling

| Caso | Comportamiento |
|---|---|
| rtk ausente en init | `RuntimeError` con instrucciones — **nunca** passthrough silencioso (S1) |
| rtk < versión mínima | `RuntimeError` en init (S3) |
| rtk > versión probada | Warning en log, continúa (S3) |
| Agente escribe `rtk ...` | `CommandSecurityError` — denegado por el sanitizer (S6) |
| Agente escribe `/usr/local/bin/rtk ...` | Igual — `_extract_base_command()` normaliza la ruta antes del deny |
| Comando fuera del mapa | Corre sin envolver, comportamiento idéntico a hoy (S4) |
| Comando con pipe/operadores | Sin envolver aunque el base esté en el mapa — garantía prefijo-pura |
| Comando envuelto falla (exit ≠ 0) | Salida **completa** vía tee (S5) |
| rtk mismo falla (no el comando) | Distinguir por exit code de rtk vs. del comando envuelto — detalle a fijar en spec contra la release fijada |
| `security_policy=None` explícito | No hay sanitizer → guard S6 no aplica en esa instancia (modo "todo permitido" preexistente, documentado). El prefijo del tool sí sigue aplicando |
| Modo plan (`_run_plan`) | Mismo tratamiento — la validación de plan (`:254`) también precede a `_make_action_from_cmdobj` |

---

## Capabilities

### New Capabilities

- `shell-rtk-integration`: probe de init (dependencia dura + versión mínima), mapa comando→subcomando rtk, inserción prefijo-pura en `_make_action_from_cmdobj`, salida completa en fallo, metadata `rtk_wrapped`. *(Identificador heredado del brainstorm de sandbox-hardening, ahora con brainstorm propio.)*
- `sanitizer-rtk-guard`: `rtk` en `_DEFAULT_DENIED_COMMANDS` del sanitizer de core + tests que garanticen que nunca entra en un allowlist por defecto ni pasa como segmento de pipe. Aplica a todos los consumidores del sanitizer, no solo a `ShellTool`.

### Modified Capabilities

- La spec de FEAT-252 (relocación del `CommandSanitizer` a core) no cambia de requisitos, pero `_DEFAULT_DENIED_COMMANDS` gana una entrada con justificación de seguridad propia — referenciar este documento desde allí.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py` | modifies | Probe en `__init__` (`:50-64`); mapa + prefijo en `_make_action_from_cmdobj` (`:167-198`) |
| `parrot/security/command_sanitizer.py` | modifies | `rtk` → `_DEFAULT_DENIED_COMMANDS` (`:170`) + tests |
| `packages/ai-parrot-tools/src/parrot_tools/shell_tool/models.py` | depends on | `BaseAction` ejecuta el `cmd` ya envuelto vía `/bin/sh -lc`; sin cambios previstos |
| `packages/ai-parrot-tools/tests/shell_tool/` | extends | Tests de probe, mapa, guard, fallo-salida-completa, plan mode |
| Imágenes docker / CI / docs de despliegue | extends | **Breaking operativo**: aprovisionar rtk pasa a ser obligatorio donde se use `ShellTool` |
| `parrot/clients/claude_agent.py` (`ClaudeAgentClient`) | unchanged | Fuera de alcance por decisión del usuario — sigue como seguimiento `rtk-subprocess-filter` |
| `sandbox-hardening.brainstorm.md` (REPL worker) | unchanged | Cero ficheros compartidos; features paralelas |

**Breaking changes:** ninguno en la API Python de `ShellTool`. Uno operativo y deliberado: **`ShellTool.__init__` falla sin rtk instalado** (S1, sin escape hatch). Anunciar en CHANGELOG y guía de migración antes de mergear.

---

## Code Context

> ✅ Verificado contra HEAD de `dev` el 2026-07-27 en este repo.
> ⚠️ **Corrección de rutas respecto al brainstorm de sandbox-hardening**: las rutas
> `parrot/tools/shell/*` de aquel documento no existen en este repo. La ubicación
> real es `packages/ai-parrot-tools/src/parrot_tools/shell_tool/` (paquete satélite,
> namespace `parrot_tools`). Los números de línea de aquel doc sí coinciden con
> estos ficheros.

### User-Provided Code

*(Ninguno en esta sesión; las decisiones S1–S8 provienen de Q&A interactivo.)*

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py:33-64
class ShellTool(SecureShellMixin, AbstractTool):
    name: str = "shell"                                                     # :46
    args_schema = ShellToolArgs                                             # :48
    def __init__(self, security_policy: Any = _NO_POLICY, **kwargs: Any):   # :50
        # _NO_POLICY → SecurityPolicy.moderate(); None explícito → sin sanitizer  # :60-64
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py:167-198
def _make_action_from_cmdobj(self, spec: CommandObject, ...) -> BaseAction:
    raw = spec.command.strip()                                              # :186
    # PUNTO DE INSERCIÓN del prefijo rtk — assert_command_safe ya corrió (:146/:254)
    # dispatch: ls→ListFiles | .sh|./|/→ExecFile | resto→RunCommand         # :193-198
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py:45-120
class SecureShellMixin:
    _sanitizer: Optional[CommandSanitizer] = None                           # :68
    def set_security_policy(self, policy: SecurityPolicy) -> None: ...      # :70
    def validate_command(self, command: str) -> ValidationResult: ...       # :78  (None → ALLOWED)
    def assert_command_safe(self, command: str) -> None: ...                # :97  (NEEDS_REVIEW ⇒ denegado)
```

```python
# From parrot/security/command_sanitizer.py (core, FEAT-252)
_DEFAULT_DENIED_COMMANDS: Set[str]                                          # :170  ← destino del guard S6
_MODERATE_SAFE_DEFAULTS: Set[str]                                           # :210-228  (rtk NO está — verificado)
class SecurityPolicy:                                                       # :327
    @classmethod
    def moderate(cls, allowed_commands=None, sandbox_dir=None): ...         # :434-469
def _extract_base_command(self, token: str) -> str: ...                     # :770  (normaliza rutas)
def _check_command_access(self, base_cmd: str): ...                         # :827-856  (allowlist por nivel)
def _check_pipe_segments(self, command: str): ...                           # :858-885  (valida cada segmento de pipe)
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/shell_tool/actions.py:10-21
class RunCommand(BaseAction):
    # argv = ["/bin/sh", "-lc", self.cmd]                                   # :14  ← el cmd envuelto corre aquí
class ExecFile(BaseAction):
    # argv = ["/bin/sh", self.cmd]                                          # :21  ← NUNCA se envuelve
```

#### Verified Imports

```python
# Confirmados:
from parrot_tools.shell_tool.security import SecurityPolicy, SecureShellMixin   # shim re-export
from parrot.security.command_sanitizer import (                                 # security.py:17-25 (FEAT-252)
    CommandSanitizer, SecurityPolicy, CommandSecurityError, CommandVerdict,
)
```

#### Key Attributes & Constants

- `ShellTool._sanitizer` → `Optional[CommandSanitizer]`; `None` significa **todo permitido** (`security.py:68`, `tool.py:64`)
- `assert_command_safe()` invocado en `tool.py:146` (modo comando) y `:254` (modo plan), **antes** de construir acciones
- `CommandObject.env` → env por comando (`tool.py:180-181`) — razón por la que la Opción C (shim PATH) es evadible
- `_result_to_dict()` → contrato de resultado (`tool.py:200-212`); metadata es el sitio para `rtk_wrapped`

### Does NOT Exist (Anti-Hallucination)

- ~~Binario `rtk` instalado~~ — `which rtk` vacío en la máquina de dev (verificado 2026-07-27). Es dependencia de despliegue a aprovisionar
- ~~Referencia alguna a `rtk` en el código Python de `parrot/` o `parrot_tools/`~~ — cero ocurrencias; todo lo existente son menciones en brainstorms de `sdd/proposals/`
- ~~`rtk` como librería enlazable / `rtk::filter()`~~ — es un crate **binario** (enum `Commands` de Clap en `src/main.rs`); ya descartado en `brainstorm-tool-result-compression.md:63`
- ~~`parrot/tools/shell/tool.py`~~ — ruta del brainstorm de sandbox-hardening; no existe. Real: `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`
- ~~Un mecanismo de wrapping/filtrado de salida en `ShellTool` hoy~~ — no hay nada; se construye desde cero
- ~~Subcomandos rtk verificados~~ — `rtk err/test/proxy <cmd>` provienen del análisis del brainstorm de compresión; la superficie CLI exacta **debe verificarse contra la release fijada** durante la spec (ver Open Questions)

---

## Parallelism Assessment

- **Internal parallelism**: Baja — dos capabilities pequeñas y acopladas por diseño (el guard S6 debe mergearse **antes o junto con** la inserción del prefijo, nunca después). Un solo worktree, tareas secuenciales; probablemente ni worktree amerite (feature de pocas tareas — ver política "When NOT to Use Worktrees").
- **Cross-feature independence**: Independiente del sandbox del REPL (otro paquete, cero ficheros compartidos) y del pipeline de compresión congelado. Único fichero de core tocado: `parrot/security/command_sanitizer.py` (una constante + tests) — vigilar si otra feature en vuelo lo toca.
- **Recommended isolation**: per-spec.
- **Rationale**: la superficie es dos ficheros y sus tests; el orden guard-antes-que-prefijo es la única restricción real y se garantiza mejor en serie.

---

## Open Questions

- [x] ¿Qué pasa si rtk no está instalado? — *Owner: Jesus Lara*: **Dependencia dura: `ShellTool.__init__` falla con error explícito. Activado por defecto, sin escape hatch. Nunca passthrough silencioso.** (decisión 2026-07-27)
- [x] ¿Cuándo aflora el fallo por rtk ausente? — *Owner: Jesus Lara*: **En init (probe `shutil.which` + versión), no en el primer comando.**
- [x] ¿Política de versiones de rtk? — *Owner: Jesus Lara*: **Versión mínima probada exigida en init; warning (no fallo) con versiones más nuevas; instalación documentada fija la release probada.**
- [x] ¿Qué comandos se envuelven y cómo? — *Owner: Jesus Lara*: **Mapa mantenido comando→subcomando rtk; lo no mapeado corre sin envolver. Sin `rtk proxy` universal.**
- [x] ¿Salida en fallo del comando envuelto? — *Owner: Jesus Lara*: **Completa (tee). El filtrado solo aplica a ejecuciones exitosas.**
- [x] ¿Cómo se neutraliza `rtk` como bypass del allowlist? — *Owner: Jesus Lara*: **Rechazo directo como comando denegado en el sanitizer de core; el prefijo lo añade solo la herramienta tras la validación; reescritura prefijo-pura. Sin strip-and-revalidate.**
- [x] ¿Se incluye la integración rtk de `ClaudeAgentClient`? — *Owner: Jesus Lara*: **No — sigue como seguimiento independiente `rtk-subprocess-filter` del brainstorm de compresión.**
- [ ] Fijar la release mínima de rtk y **verificar su superficie CLI real** (subcomandos exactos, semántica de `tee`, exit codes propios vs. del comando envuelto) — tarea de spec contra el binario fijado. — *Owner: Jesus Lara*
- [ ] Contenido inicial del mapa comando→subcomando (candidatos: `pytest`, `npm`, `cargo`, `git`; decidir contra la release fijada). — *Owner: Jesus Lara*
- [ ] Aprovisionamiento: instrucciones de instalación + Dockerfile/CI de referencia; ¿se publica un script `scripts/install-rtk.sh`? — *Owner: Jesus Lara*
- [ ] ¿Telemetría de ahorro (equivalente a `rtk gain`) en v1 o seguimiento? — *Owner: Jesus Lara*
