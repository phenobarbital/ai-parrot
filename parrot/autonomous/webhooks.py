# parrot/autonomy/webhooks.py
import hmac
import hashlib
import json
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from aiohttp import web
from navconfig.logging import logging


@dataclass
class WebhookEndpoint:
    """Configuración de un endpoint webhook."""
    path: str
    agent_name: str
    secret: Optional[str] = None             # Para validar HMAC
    allowed_sources: List[str] = field(default_factory=list)  # IPs permitidas
    transform_fn: Optional[Callable[[Dict], str]] = None  # payload -> prompt
    crew_name: Optional[str] = None
    method_name: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Stats
    call_count: int = 0
    last_called: Optional[datetime] = None


class WebhookListener:
    """
    Listener HTTP para triggers externos.
    
    Permite que sistemas externos disparen ejecuciones de agentes via webhooks.
    """
    
    def __init__(
        self,
        base_path: str = "/webhooks",
        require_auth: bool = True
    ):
        self.base_path = base_path.rstrip("/")
        self.require_auth = require_auth
        
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._agent_executor: Optional[Callable] = None
        self._event_bus: Optional["EventBus"] = None
        
        self.logger = logging.getLogger("parrot.autonomy.webhooks")
    
    def set_executor(self, executor: Callable):
        """
        Configura el ejecutor de agentes.
        
        Args:
            executor: async fn(agent_name, prompt, **kwargs) -> result
        """
        self._agent_executor = executor
    
    def set_event_bus(self, event_bus: "EventBus"):
        """Conecta con el event bus para emitir eventos."""
        self._event_bus = event_bus
    
    def register_endpoint(
        self,
        path: str,
        agent_name: str,
        **kwargs
    ) -> WebhookEndpoint:
        """
        Registra un nuevo endpoint webhook.
        
        Args:
            path: Path del endpoint (ej: "/github", "/stripe")
            agent_name: Agente a ejecutar cuando se reciba el webhook
            **kwargs: Opciones adicionales para WebhookEndpoint
        """
        full_path = f"{self.base_path}{path}"
        endpoint = WebhookEndpoint(
            path=full_path,
            agent_name=agent_name,
            **kwargs
        )
        self._endpoints[full_path] = endpoint
        self.logger.info(f"Registered webhook endpoint: {full_path} -> {agent_name}")
        return endpoint
    
    def setup(self, app: web.Application):
        """Configura las rutas en la aplicación aiohttp."""
        # Ruta genérica que captura todos los webhooks
        app.router.add_post(
            f"{self.base_path}/{{webhook_id:.*}}",
            self._handle_webhook
        )
        
        # Ruta para listar endpoints
        app.router.add_get(
            f"{self.base_path}/_list",
            self._list_endpoints
        )
        
        # Guardar referencia
        app['webhook_listener'] = self
    
    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Procesa un webhook entrante."""
        path = request.path
        endpoint = self._endpoints.get(path)
        
        if not endpoint:
            return web.json_response(
                {"error": "Unknown webhook endpoint"},
                status=404
            )
        
        if not endpoint.enabled:
            return web.json_response(
                {"error": "Webhook endpoint disabled"},
                status=503
            )
        
        # Validar source IP si está configurado
        if endpoint.allowed_sources:
            client_ip = request.remote
            if client_ip not in endpoint.allowed_sources:
                self.logger.warning(
                    f"Webhook {path} rejected from {client_ip}"
                )
                return web.json_response(
                    {"error": "Source not allowed"},
                    status=403
                )
        
        # Validar HMAC si está configurado
        if endpoint.secret:
            if not await self._validate_signature(request, endpoint.secret):
                return web.json_response(
                    {"error": "Invalid signature"},
                    status=401
                )
        
        # Parsear payload
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {"raw": await request.text()}
        
        # Construir prompt
        if endpoint.transform_fn:
            try:
                prompt = endpoint.transform_fn(payload)
            except Exception as e:
                self.logger.error(f"Transform error: {e}")
                prompt = json.dumps(payload, indent=2)
        else:
            prompt = f"Process this webhook payload:\n```json\n{json.dumps(payload, indent=2)}\n```"
        
        # Actualizar stats
        endpoint.call_count += 1
        endpoint.last_called = datetime.now()
        
        # Generar request ID
        request_id = str(uuid.uuid4())
        
        # Emitir evento
        if self._event_bus:
            await self._event_bus.emit(
                "webhook.received",
                {
                    "endpoint": path,
                    "agent_name": endpoint.agent_name,
                    "request_id": request_id,
                    "payload": payload
                },
                source="webhook_listener"
            )
        
        # Ejecutar agente (async, no bloqueante)
        if self._agent_executor:
            # Fire and forget o esperar?
            # Opción 1: Async (responder inmediatamente)
            import asyncio
            asyncio.create_task(
                self._execute_and_notify(
                    endpoint, prompt, request_id, payload
                )
            )
            
            return web.json_response({
                "status": "accepted",
                "request_id": request_id,
                "message": f"Webhook received, agent {endpoint.agent_name} triggered"
            }, status=202)
        
        return web.json_response({
            "status": "received",
            "request_id": request_id,
            "warning": "No executor configured"
        })
    
    async def _execute_and_notify(
        self,
        endpoint: WebhookEndpoint,
        prompt: str,
        request_id: str,
        payload: Dict[str, Any]
    ):
        """Ejecuta el agente y notifica resultado."""
        try:
            result = await self._agent_executor(
                agent_name=endpoint.agent_name,
                prompt=prompt,
                crew_name=endpoint.crew_name,
                method_name=endpoint.method_name,
                metadata={
                    "webhook_path": endpoint.path,
                    "request_id": request_id,
                    "payload": payload
                }
            )
            
            if self._event_bus:
                await self._event_bus.emit(
                    "webhook.completed",
                    {
                        "request_id": request_id,
                        "agent_name": endpoint.agent_name,
                        "success": True,
                        "result": str(result)[:500]  # Truncar
                    }
                )
                
        except Exception as e:
            self.logger.error(f"Webhook execution error: {e}")
            if self._event_bus:
                await self._event_bus.emit(
                    "webhook.failed",
                    {
                        "request_id": request_id,
                        "agent_name": endpoint.agent_name,
                        "error": str(e)
                    }
                )
    
    async def _validate_signature(
        self,
        request: web.Request,
        secret: str
    ) -> bool:
        """Valida firma HMAC del webhook."""
        # Soportar diferentes headers de firma
        signature_headers = [
            "X-Hub-Signature-256",      # GitHub
            "X-Signature-256",          # Generic
            "Stripe-Signature",         # Stripe
            "X-Webhook-Signature"       # Custom
        ]
        
        signature = None
        for header in signature_headers:
            if sig := request.headers.get(header):
                signature = sig
                break
        
        if not signature:
            return False
        
        # Calcular firma esperada
        body = await request.read()
        expected = hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        # Comparar (timing-safe)
        if signature.startswith("sha256="):
            signature = signature[7:]
        
        return hmac.compare_digest(expected, signature)
    
    async def _list_endpoints(self, request: web.Request) -> web.Response:
        """Lista todos los endpoints registrados."""
        endpoints = [
            {
                "path": e.path,
                "agent_name": e.agent_name,
                "enabled": e.enabled,
                "call_count": e.call_count,
                "last_called": e.last_called.isoformat() if e.last_called else None
            }
            for e in self._endpoints.values()
        ]
        return web.json_response({"endpoints": endpoints})