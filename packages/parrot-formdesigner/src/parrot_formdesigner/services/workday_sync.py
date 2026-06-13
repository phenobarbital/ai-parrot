"""WorkdayIdentitySyncAdapter — stub de sincronización de identidades con Workday.

FEAT-302 Module 4 — STUB ONLY (§8 RESUELTO).

Por qué solo stub:
- FEAT-026 / FEAT-027 (Workday Identity Sync en ai-parrot) **no existen**.
- Su construcción está bloqueada por un spec prerequisito de guardrails
  ABAC/PBAC para la API de Workday y el Toolkit de Workday.
- Hasta que ese spec esté aprobado e implementado, cualquier llamada HTTP
  real a la API de Workday es prematura e insegura.

Contrato de upgrade:
- La interfaz pública (``sync_user()``) es estable; un upgrade drop-in
  a cliente real requiere únicamente:
  1. Poner ``base_url`` y ``api_key`` reales.
  2. Implementar el cuerpo HTTP en ``sync_user()`` según el contrato del
     spec de guardrails Workday.
  3. Eliminar la bandera ``stub=True`` del retorno.
- El adapter NO modifica permisos; para revocar acceso completo combinar
  con ``RBACService.revoke_all()``.

Uso::

    adapter = WorkdayIdentitySyncAdapter()  # stub
    result = await adapter.sync_user(
        "user-abc",
        action="provision",
        org_id=7,
    )
    # → {"status": "accepted", "stub": True, "action": "provision",
    #    "user_id": "user-abc", "org_id": 7}
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)


class WorkdayIdentitySyncAdapter:
    """Stub de sincronización de identidades hacia Workday.

    Interfaz estable para upgrade drop-in cuando FEAT-026/027 estén
    disponibles. Actualmente: loggea la operación y devuelve un dict
    de aceptación con ``stub=True``; **cero llamadas HTTP**.

    Args:
        base_url: URL base del endpoint Workday (ignorada en stub mode).
            Cuando ``None``, el adapter opera siempre en stub mode.
        api_key: API key para autenticación Workday (ignorada en stub mode).
            Cuando ``None``, no se intenta autenticación.

    Note:
        ``WORKDAY_SYNC_BASE_URL`` no existe como variable de entorno definida
        porque el endpoint upstream no está disponible (§8). No leer esa
        variable hasta que el spec de guardrails Workday esté aprobado.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def sync_user(
        self,
        user_id: str,
        *,
        action: Literal["provision", "deprovision"],
        org_id: int,
    ) -> dict[str, Any]:
        """Stub: loggea la operación y devuelve aceptación sin llamada HTTP.

        Contrato de retorno estable (no cambia al hacer upgrade):
        - ``status``: siempre ``"accepted"`` (HTTP 202).
        - ``stub``: ``True`` en stub mode; se elimina al implementar real.
        - ``action``: la acción recibida.
        - ``user_id``: el usuario afectado.
        - ``org_id``: la organización de contexto.

        Args:
            user_id: Identificador del usuario a provisionar/desprovisionar.
            action: ``"provision"`` (crear acceso) o ``"deprovision"``
                (revocar acceso). Para deprovisión completa combinar con
                ``RBACService.revoke_all()``.
            org_id: Identificador de la organización de contexto.

        Returns:
            Dict de aceptación::

                {
                    "status": "accepted",
                    "stub": True,
                    "action": "provision" | "deprovision",
                    "user_id": str,
                    "org_id": int,
                }

        Note:
            Esta implementación no abre ningún ``aiohttp.ClientSession``
            ni hace ninguna llamada de red. El stub es seguro de llamar
            sin internet y en entornos de CI.
        """
        self.logger.info(
            "WorkdayIdentitySyncAdapter.sync_user: STUB — action=%s user_id=%s org_id=%s"
            " (FEAT-026/027 not available; spec prerequisite pending)",
            action,
            user_id,
            org_id,
        )
        return {
            "status": "accepted",
            "stub": True,
            "action": action,
            "user_id": user_id,
            "org_id": org_id,
        }
