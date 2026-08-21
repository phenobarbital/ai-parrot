"""Captura y replicación del error de un bug, antes de investigarlo.

``log_sources`` trae logs ya escritos. Esto hace lo otro: leer el trace que
pegó quien reporta, y **volver a provocar** el error contra un entorno para
verlo de primera mano — estado, cuerpo y traceback observados, no relatados.

Es lo que ``BugIntakeNode`` declaraba como su razón de ser ("severity
classification, stack-trace parsing") y no implementaba.

El objetivo del blanco es un **entorno** (dev, staging), no la app corriendo
en la máquina de quien pide: reproducir contra el entorno donde el 500 pasa
de verdad evita montar el servicio y su base localmente para cada bug.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

#: Severidad derivada de lo observado, no declarada por quien reporta.
Severity = Literal["critical", "high", "medium", "low"]

#: `File "path", line N, in func` — un frame de traceback de Python.
_PY_FRAME_RE = re.compile(
    r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)'
)

#: `TipoDeError: mensaje` en la última línea de un traceback de Python.
_PY_EXC_RE = re.compile(
    r"^(?P<type>[A-Z][A-Za-z0-9_.]*(?:Error|Exception|Warning|Exit))"
    r"(?::\s*(?P<message>.*))?$"
)

#: `at Object.foo (/ruta/archivo.ts:12:34)` — un frame de Node/TypeScript.
_JS_FRAME_RE = re.compile(
    r"at\s+(?P<func>[^\s(]+)\s*\((?P<file>[^):]+):(?P<line>\d+)(?::\d+)?\)"
)

#: `GET /api/v1/xyz` o `/api/v1/xyz` dentro de texto libre.
_ENDPOINT_RE = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)?\s*"
    r"(?P<path>/[A-Za-z0-9._~\-/{}]*)",
)

#: Directorios de dependencias: un frame acá casi nunca es el bug propio,
#: solo el camino por donde pasó.
_VENDOR_MARKERS = (
    "/node_modules/", "/site-packages/", "/dist-packages/", "/.venv/",
    "/vendor/", "<frozen ",
)

#: Excepciones que casi siempre significan "se cae para todos", no "para un
#: caso raro": arrancar mal, perder la base, quedarse sin memoria.
_CRITICAL_EXCEPTIONS = frozenset({
    "ImportError", "ModuleNotFoundError", "SystemExit", "MemoryError",
    "OperationalError", "InterfaceError", "ConnectionError",
})


@dataclass(frozen=True)
class StackFrame:
    """Un frame de un traceback.

    Attributes:
        file: Archivo del frame.
        line: Línea.
        function: Función o método.
    """

    file: str
    line: int
    function: str


@dataclass
class StackTrace:
    """Un traceback parseado.

    Attributes:
        language: ``python``, ``javascript`` o ``unknown``.
        exception_type: Tipo de la excepción, si se pudo identificar.
        message: Mensaje de la excepción.
        frames: Frames, en el orden del texto.
        raw: El texto original.
    """

    language: str = "unknown"
    exception_type: Optional[str] = None
    message: str = ""
    frames: List[StackFrame] = field(default_factory=list)
    raw: str = ""

    @property
    def culprit(self) -> Optional[StackFrame]:
        """El frame que mejor identifica el bug propio.

        Dos cuidados. El orden de los frames depende del stack: Python los
        imprime de afuera hacia adentro (el último es donde reventó) y
        Node/V8 al revés (el primero). Y en cualquiera de los dos, el frame
        más interno suele caer en ``node_modules`` o ``site-packages``, que
        es por dónde pasó el error y no dónde está el bug.

        Así que se recorre desde el frame más interno hacia afuera y se
        devuelve el primero que no sea de una dependencia; si todos lo son,
        se devuelve el más interno, que es mejor que nada.
        """
        if not self.frames:
            return None
        # Del más interno al más externo, según el stack.
        inner_first = (
            self.frames if self.language == "javascript" else self.frames[::-1]
        )
        for frame in inner_first:
            if not any(marker in frame.file for marker in _VENDOR_MARKERS):
                return frame
        return inner_first[0]

    def summary(self) -> str:
        """Una línea con lo esencial del trace."""
        if not self.exception_type and not self.frames:
            return "sin traceback reconocible"
        parts = []
        if self.exception_type:
            parts.append(f"{self.exception_type}: {self.message[:120]}")
        if self.culprit is not None:
            parts.append(f"en {self.culprit.file}:{self.culprit.line}")
        return " ".join(parts)


@dataclass(frozen=True)
class ReplicationTarget:
    """Entorno contra el que reproducir el error.

    Attributes:
        base_url: Raíz del servicio (``https://dev.example.com``).
        name: Etiqueta del entorno, para documentar contra qué se reprodujo.
        headers: Cabeceras fijas (autenticación, tenant).
        timeout_seconds: Tope por request.
        verify_ssl: ``False`` para entornos con certificado propio.
    """

    base_url: str
    name: str = "dev"
    headers: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    verify_ssl: bool = True


@dataclass
class ReplicationResult:
    """Lo que pasó al intentar reproducir el error.

    Attributes:
        attempted: Si se llegó a hacer el request.
        reproduced: Si se observó una respuesta de error (>= 500).
        target: Nombre del entorno.
        url: URL exacta que se pidió.
        method: Método HTTP usado.
        status: Código devuelto.
        body_excerpt: Comienzo del cuerpo de la respuesta.
        trace: Traceback encontrado en el cuerpo, si vino.
        error: Por qué no se pudo intentar o completar.
    """

    attempted: bool = False
    reproduced: bool = False
    target: str = ""
    url: str = ""
    method: str = "GET"
    status: Optional[int] = None
    body_excerpt: str = ""
    trace: Optional[StackTrace] = None
    error: str = ""

    def summary(self) -> str:
        """Una línea para el brief."""
        if not self.attempted:
            return f"no se intentó reproducir: {self.error or 'sin blanco configurado'}"
        if self.error:
            return f"{self.method} {self.url} falló al reproducir: {self.error}"
        verdict = "REPRODUCIDO" if self.reproduced else "no reproducido"
        return f"{verdict} — {self.method} {self.url} -> {self.status}"


def parse_stack_trace(text: str) -> StackTrace:
    """Parsear un traceback pegado en el reporte.

    Reconoce Python y Node/TypeScript, que son los dos stacks de la
    plataforma. Un texto sin frames devuelve un :class:`StackTrace` vacío en
    lugar de fallar: que el reportante no haya pegado un trace es lo normal,
    no un error.

    Args:
        text: Texto libre que puede contener un traceback.

    Returns:
        El trace parseado, posiblemente vacío.
    """
    if not text or not text.strip():
        return StackTrace(raw=text or "")

    frames = [
        StackFrame(file=m.group("file"), line=int(m.group("line")),
                   function=m.group("func"))
        for m in _PY_FRAME_RE.finditer(text)
    ]
    language = "python" if frames else "unknown"
    if not frames:
        frames = [
            StackFrame(file=m.group("file"), line=int(m.group("line")),
                       function=m.group("func"))
            for m in _JS_FRAME_RE.finditer(text)
        ]
        if frames:
            language = "javascript"

    exception_type: Optional[str] = None
    message = ""
    # La excepción está en la última línea del bloque, así que se recorre de
    # atrás hacia adelante y se corta en la primera que matchea.
    for line in reversed([l.strip() for l in text.strip().splitlines() if l.strip()]):
        match = _PY_EXC_RE.match(line)
        if match:
            exception_type = match.group("type")
            message = (match.group("message") or "").strip()
            break

    return StackTrace(
        language=language,
        exception_type=exception_type,
        message=message,
        frames=frames,
        raw=text,
    )


def extract_endpoint(text: str) -> Tuple[str, Optional[str]]:
    """Sacar del reporte el método y la ruta a reproducir.

    Se ignoran las rutas que son claramente de archivo (con extensión) o
    que salen de un traceback: ``/usr/lib/python3/site-packages/x.py`` no es
    un endpoint. Sin ruta reconocible no hay nada que reproducir.

    Args:
        text: Resumen y descripción del reporte.

    Returns:
        ``(method, path)``; ``path`` es ``None`` si no se encontró ninguna.
    """
    for match in _ENDPOINT_RE.finditer(text or ""):
        path = match.group("path")
        if not path or path == "/":
            continue
        tail = path.rsplit("/", 1)[-1]
        if "." in tail:  # archivo, no endpoint
            continue
        if path.startswith(("/usr/", "/home/", "/opt/", "/var/", "/etc/")):
            continue
        return (match.group("method") or "GET").upper(), path
    return "GET", None


def classify_severity(
    trace: Optional[StackTrace],
    replication: Optional[ReplicationResult] = None,
) -> Severity:
    """Clasificar la severidad con lo que se observó.

    La escala es deliberadamente simple y se apoya en evidencia, no en la
    urgencia que declare quien reporta: un error reproducido pesa más que
    uno relatado, y una excepción de arranque o de base de datos pesa más
    que una de dominio.

    Args:
        trace: Traceback parseado, si hay.
        replication: Resultado de la reproducción, si se intentó.

    Returns:
        La severidad.
    """
    exception_type = (trace.exception_type if trace else None) or ""
    reproduced = bool(replication and replication.reproduced)

    if exception_type in _CRITICAL_EXCEPTIONS:
        return "critical"
    if reproduced and (replication.status or 0) >= 500:
        return "high"
    if reproduced:
        return "medium"
    if exception_type:
        return "medium"
    return "low"


async def replicate_endpoint(
    target: ReplicationTarget,
    method: str,
    path: str,
    *,
    payload: Optional[Any] = None,
) -> ReplicationResult:
    """Pegarle al endpoint en el entorno y quedarse con lo que devuelva.

    Un error de red no es un fallo del análisis: se registra en
    ``error`` y el flujo sigue con lo que haya. Lo que no puede pasar es
    que un entorno caído aborte el intake entero.

    Args:
        target: Entorno contra el que reproducir.
        method: Método HTTP.
        path: Ruta, relativa a ``target.base_url``.
        payload: Cuerpo JSON opcional, para métodos que lo llevan.

    Returns:
        El :class:`ReplicationResult`.
    """
    import aiohttp

    url = f"{target.base_url.rstrip('/')}/{path.lstrip('/')}"
    result = ReplicationResult(
        attempted=True, target=target.name, url=url, method=method.upper()
    )
    timeout = aiohttp.ClientTimeout(total=target.timeout_seconds)
    try:
        connector = aiohttp.TCPConnector(ssl=target.verify_ssl)
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector, headers=target.headers
        ) as session:
            async with session.request(
                method.upper(), url, json=payload
            ) as response:
                body = await response.text()
                result.status = response.status
                result.body_excerpt = body[:2000]
                result.reproduced = response.status >= 500
    except Exception as exc:  # noqa: BLE001 — ver docstring
        result.error = f"{type(exc).__name__}: {exc}"
        logger.warning("No se pudo reproducir %s %s: %s", method, url, exc)
        return result

    # Muchos servicios devuelven el traceback en el cuerpo del 500; si está,
    # es mejor evidencia que la que pegó quien reporta.
    trace = parse_stack_trace(result.body_excerpt)
    if trace.frames or trace.exception_type:
        result.trace = trace
    return result


def proposed_regression_test(
    result: ReplicationResult, trace: Optional[StackTrace] = None
) -> Optional[Dict[str, str]]:
    """Proponer el test de regresión que cierra el bug.

    No escribe archivos: a la hora del intake todavía no existe el worktree
    (se provisiona antes de Development). Devuelve el contenido propuesto y
    el comando que lo corre, para que Development lo materialice y QA lo use
    como criterio de aceptación — el fix está listo cuando este test pasa.

    ``pytest`` está en ``ACCEPTANCE_CRITERION_ALLOWLIST``, así que el comando
    es ejecutable como criterio sin más permisos.

    Args:
        result: La reproducción observada.
        trace: Traceback asociado, para el docstring del test.

    Returns:
        ``{"path", "content", "command"}``, o ``None`` si no hubo nada
        reproducido que testear.
    """
    if not result.reproduced or not result.url:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", result.url.rsplit("/", 2)[-1].lower()).strip("_")
    slug = slug or "endpoint"
    path = f"tests/regression/test_bug_{slug}.py"
    detail = trace.summary() if trace else f"status {result.status}"
    content = f'''"""Regresión: {result.method} {result.url} devolvía {result.status}.

Observado al hacer el intake contra el entorno {result.target!r}:
{detail}

El bug está arreglado cuando este test pasa.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("TARGET_BASE_URL", "{result.url.rsplit(result.method, 1)[0] or ''}")


@pytest.mark.regression
def test_endpoint_does_not_return_server_error():
    response = requests.request("{result.method}", "{result.url}", timeout=30)
    assert response.status_code < 500, (
        f"{result.method} {result.url} devolvió {{response.status_code}}: "
        f"{{response.text[:500]}}"
    )
'''
    return {"path": path, "content": content, "command": f"pytest {path}"}
