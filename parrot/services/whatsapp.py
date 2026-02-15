"""WhatsApp Configuration API Handler.

Provides REST endpoints to manage the WhatsApp Bridge:
- QR code authentication (superuser-only)
- Connection status and hook management
- Test messaging and statistics
"""
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import asyncio

from aiohttp import web, ClientSession, ClientTimeout
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import (
    allowed_groups,
    is_authenticated,
    user_session,
)

# ---------------------------------------------------------------------------
# HTML dashboard (served at GET /api/whatsapp/dashboard)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WhatsApp Configuration - AI-Parrot</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }

        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        .header p {
            font-size: 1.1em;
            opacity: 0.9;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }

        .card h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
        }

        .status {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 10px;
        }

        .status.connected {
            background: #10b981;
            color: white;
        }

        .status.disconnected {
            background: #ef4444;
            color: white;
        }

        .status.waiting {
            background: #f59e0b;
            color: white;
        }

        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: white;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        #qrcode {
            text-align: center;
            margin: 20px 0;
        }

        #qrcode img {
            max-width: 256px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            width: 100%;
            margin-top: 10px;
        }

        .btn:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        .btn.danger {
            background: #ef4444;
        }

        .btn.danger:hover {
            background: #dc2626;
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .hooks-list {
            list-style: none;
        }

        .hook-item {
            background: #f3f4f6;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .hook-info {
            flex: 1;
        }

        .hook-name {
            font-weight: bold;
            color: #333;
            margin-bottom: 5px;
        }

        .hook-target {
            color: #666;
            font-size: 0.9em;
        }

        .hook-actions {
            display: flex;
            gap: 10px;
        }

        .hook-actions button {
            padding: 6px 12px;
            font-size: 0.85em;
            width: auto;
            margin: 0;
        }

        .form-group {
            margin-bottom: 15px;
        }

        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #333;
            font-weight: 500;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 1em;
        }

        .form-group textarea {
            min-height: 100px;
            font-family: monospace;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 15px;
        }

        .stat-box {
            text-align: center;
            padding: 15px;
            background: #f3f4f6;
            border-radius: 8px;
        }

        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }

        .stat-label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }

        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal.active {
            display: flex;
        }

        .modal-content {
            background: white;
            border-radius: 12px;
            padding: 30px;
            max-width: 500px;
            width: 90%;
            max-height: 90vh;
            overflow-y: auto;
        }

        .modal-content h2 {
            margin-bottom: 20px;
        }

        .close-modal {
            float: right;
            font-size: 1.5em;
            cursor: pointer;
            color: #999;
        }

        .alert {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
        }

        .alert.success {
            background: #d1fae5;
            color: #065f46;
        }

        .alert.error {
            background: #fee2e2;
            color: #991b1b;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 WhatsApp Configuration</h1>
            <p>AI-Parrot Autonomous Orchestrator</p>
        </div>

        <div class="cards">
            <!-- Status Card -->
            <div class="card">
                <h2>📱 WhatsApp Status</h2>
                <div id="statusContainer">
                    <div class="status waiting">
                        <div class="status-dot"></div>
                        <span>Checking status...</span>
                    </div>
                </div>
                <button class="btn" onclick="refreshStatus()">Refresh Status</button>
                <button class="btn danger" onclick="disconnect()" id="disconnectBtn" disabled>Disconnect</button>
            </div>

            <!-- QR Code Card -->
            <div class="card" id="qrCard">
                <h2>🔐 Authentication</h2>
                <div id="qrStatus">
                    <p>Checking authentication status...</p>
                </div>
                <div id="qrcode"></div>
                <button class="btn" onclick="loadQRCode()" id="qrBtn">Show QR Code</button>
            </div>

            <!-- Stats Card -->
            <div class="card">
                <h2>📊 Statistics</h2>
                <div class="stats-grid" id="statsContainer">
                    <div class="stat-box">
                        <div class="stat-value" id="totalMessages">-</div>
                        <div class="stat-label">Messages</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value" id="successRate">-</div>
                        <div class="stat-label">Success</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value" id="totalHooks">-</div>
                        <div class="stat-label">Hooks</div>
                    </div>
                </div>
                <button class="btn" onclick="refreshStats()">Refresh Stats</button>
            </div>
        </div>

        <!-- Hooks Management -->
        <div class="card">
            <h2>⚙️ Configured Hooks</h2>
            <div id="hooksContainer">
                <p>Loading hooks...</p>
            </div>
            <button class="btn" onclick="showCreateHookModal()">➕ Create New Hook</button>
        </div>
    </div>

    <!-- Create Hook Modal -->
    <div class="modal" id="createHookModal">
        <div class="modal-content">
            <span class="close-modal" onclick="closeModal('createHookModal')">×</span>
            <h2>Create WhatsApp Hook</h2>

            <div id="modalAlert"></div>

            <form id="createHookForm" onsubmit="createHook(event)">
                <div class="form-group">
                    <label>Hook Name</label>
                    <input type="text" id="hookName" required placeholder="e.g., whatsapp_sales">
                </div>

                <div class="form-group">
                    <label>Target Type</label>
                    <select id="targetType">
                        <option value="agent">Agent</option>
                        <option value="crew">Crew</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Target ID</label>
                    <input type="text" id="targetId" required placeholder="e.g., SalesAgent">
                </div>

                <div class="form-group">
                    <label>Command Prefix (optional)</label>
                    <input type="text" id="commandPrefix" placeholder="e.g., ! or /">
                </div>

                <div class="form-group">
                    <label>Allowed Phones (comma-separated, optional)</label>
                    <input type="text" id="allowedPhones" placeholder="14155552671,34612345678">
                </div>

                <div class="form-group">
                    <label>Auto Reply</label>
                    <select id="autoReply">
                        <option value="true">Enabled</option>
                        <option value="false">Disabled</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Routes (JSON, optional)</label>
                    <textarea id="routes" placeholder='[{"keywords": ["hello"], "target_id": "Agent1"}]'></textarea>
                </div>

                <button type="submit" class="btn">Create Hook</button>
            </form>
        </div>
    </div>

    <script>
        const API_BASE = '/api/whatsapp';

        let autoRefresh = null;

        async function fetchAPI(endpoint, options = {}) {
            try {
                // Inject Bearer token from localStorage (set by /autonomous/admin)
                const token = localStorage.getItem('ai_parrot_token');
                if (token) {
                    options.headers = options.headers || {};
                    if (options.headers instanceof Headers) {
                        if (!options.headers.has('Authorization')) {
                            options.headers.set('Authorization', `Bearer ${token}`);
                        }
                    } else {
                        options.headers = {
                            'Authorization': `Bearer ${token}`,
                            ...options.headers
                        };
                    }
                }
                const response = await fetch(API_BASE + endpoint, options);
                if (response.status === 401 || response.status === 403) {
                    // Token may be expired — redirect to login
                    window.location.href = '/autonomous/admin';
                    return { success: false, error: 'Session expired' };
                }
                const data = await response.json();
                return data;
            } catch (error) {
                console.error('API Error:', error);
                return { success: false, error: error.message };
            }
        }

        async function refreshStatus() {
            const data = await fetchAPI('/status');
            const container = document.getElementById('statusContainer');

            if (data.success && data.bridge) {
                const { connected, authenticated, logged_in } = data.bridge;

                let statusClass = 'disconnected';
                let statusText = 'Disconnected';

                if (connected && authenticated && logged_in) {
                    statusClass = 'connected';
                    statusText = 'Connected & Authenticated ✓';
                    document.getElementById('disconnectBtn').disabled = false;
                } else if (connected) {
                    statusClass = 'waiting';
                    statusText = 'Connected - Waiting for Authentication';
                }

                container.innerHTML = `
                    <div class="status ${statusClass}">
                        <div class="status-dot"></div>
                        <span>${statusText}</span>
                    </div>
                    <p style="margin-top: 10px; color: #666; font-size: 0.9em;">
                        Bridge: ${data.bridge_url}<br>
                        Connected: ${connected ? '✓' : '✗'} |
                        Authenticated: ${authenticated ? '✓' : '✗'} |
                        Logged In: ${logged_in ? '✓' : '✗'}
                    </p>
                `;

                if (authenticated) {
                    document.getElementById('qrStatus').innerHTML =
                        '<p style="color: #10b981;">✓ Already authenticated</p>';
                    document.getElementById('qrBtn').disabled = true;
                } else {
                    document.getElementById('qrStatus').innerHTML =
                        '<p style="color: #f59e0b;">Scan QR code to authenticate</p>';
                    document.getElementById('qrBtn').disabled = false;
                }
            } else {
                container.innerHTML = `
                    <div class="status disconnected">
                        <div class="status-dot"></div>
                        <span>Bridge not available</span>
                    </div>
                    <p style="margin-top: 10px; color: #666; font-size: 0.9em;">
                        Error: ${data.error || 'Unknown error'}
                    </p>
                `;
            }
        }

        async function loadQRCode() {
            const qrcode = document.getElementById('qrcode');
            qrcode.innerHTML = '<p>Loading QR code...</p>';

            const data = await fetchAPI('/qr');

            if (data.success && data.qr_available) {
                qrcode.innerHTML = `
                    <img src="${API_BASE}/qr/image?t=${Date.now()}" alt="QR Code">
                    <p style="margin-top: 10px; color: #666; font-size: 0.9em;">
                        ${data.instructions}
                    </p>
                `;

                if (!autoRefresh) {
                    autoRefresh = setInterval(async () => {
                        const status = await fetchAPI('/status');
                        if (status.success && status.bridge.authenticated) {
                            clearInterval(autoRefresh);
                            autoRefresh = null;
                            refreshStatus();
                            qrcode.innerHTML = '<p style="color: #10b981;">✓ Authenticated!</p>';
                        }
                    }, 5000);
                }
            } else if (data.status === 'authenticated') {
                qrcode.innerHTML = '<p style="color: #10b981;">✓ Already authenticated</p>';
            } else {
                qrcode.innerHTML = `<p style="color: #ef4444;">Error: ${data.error}</p>`;
            }
        }

        async function disconnect() {
            if (!confirm('Are you sure you want to disconnect WhatsApp?')) return;

            const data = await fetchAPI('/disconnect', { method: 'POST' });
            if (data.success) {
                alert('WhatsApp disconnected. Restart bridge to reconnect.');
                refreshStatus();
                refreshHooks();
            } else {
                alert('Error: ' + data.error);
            }
        }

        async function refreshHooks() {
            const data = await fetchAPI('/hooks');
            const container = document.getElementById('hooksContainer');

            if (data.success && data.hooks.length > 0) {
                container.innerHTML = `
                    <ul class="hooks-list">
                        ${data.hooks.map(hook => `
                            <li class="hook-item">
                                <div class="hook-info">
                                    <div class="hook-name">${hook.name}</div>
                                    <div class="hook-target">
                                        ${hook.target_type}/${hook.target_id} |
                                        ${hook.enabled ? '✓ Enabled' : '✗ Disabled'}
                                        ${hook.config.command_prefix ? ` | Prefix: ${hook.config.command_prefix}` : ''}
                                    </div>
                                </div>
                                <div class="hook-actions">
                                    <button class="btn" onclick="deleteHook('${hook.hook_id}')">Delete</button>
                                </div>
                            </li>
                        `).join('')}
                    </ul>
                `;
            } else if (data.success) {
                container.innerHTML = '<p>No hooks configured yet.</p>';
            } else {
                container.innerHTML = `<p style="color: #ef4444;">Error: ${data.error}</p>`;
            }
        }

        async function deleteHook(hookId) {
            if (!confirm('Delete this hook?')) return;

            const data = await fetchAPI(`/hooks/${hookId}`, { method: 'DELETE' });
            if (data.success) {
                refreshHooks();
                refreshStats();
            } else {
                alert('Error: ' + data.error);
            }
        }

        async function refreshStats() {
            const data = await fetchAPI('/stats');

            if (data.success && data.stats) {
                document.getElementById('totalMessages').textContent = data.stats.total_executions;
                const successRate = data.stats.total_executions > 0
                    ? Math.round((data.stats.successful / data.stats.total_executions) * 100)
                    : 0;
                document.getElementById('successRate').textContent = successRate + '%';
                document.getElementById('totalHooks').textContent = data.stats.hooks.total;
            }
        }

        function showCreateHookModal() {
            document.getElementById('createHookModal').classList.add('active');
        }

        function closeModal(modalId) {
            document.getElementById(modalId).classList.remove('active');
        }

        async function createHook(event) {
            event.preventDefault();

            const allowedPhonesStr = document.getElementById('allowedPhones').value;
            const allowedPhones = allowedPhonesStr
                ? allowedPhonesStr.split(',').map(p => p.trim()).filter(p => p)
                : null;

            const routesStr = document.getElementById('routes').value;
            let routes = null;
            if (routesStr) {
                try {
                    routes = JSON.parse(routesStr);
                } catch (e) {
                    showModalAlert('Invalid JSON in routes', 'error');
                    return;
                }
            }

            const hookData = {
                name: document.getElementById('hookName').value,
                target_type: document.getElementById('targetType').value,
                target_id: document.getElementById('targetId').value,
                config: {
                    command_prefix: document.getElementById('commandPrefix').value,
                    allowed_phones: allowedPhones,
                    auto_reply: document.getElementById('autoReply').value === 'true',
                    routes: routes
                }
            };

            const data = await fetchAPI('/hooks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(hookData)
            });

            if (data.success) {
                showModalAlert('Hook created successfully!', 'success');
                setTimeout(() => {
                    closeModal('createHookModal');
                    document.getElementById('createHookForm').reset();
                    document.getElementById('modalAlert').innerHTML = '';
                    refreshHooks();
                    refreshStats();
                }, 2000);
            } else {
                showModalAlert('Error: ' + data.error, 'error');
            }
        }

        function showModalAlert(message, type) {
            const alert = document.getElementById('modalAlert');
            alert.innerHTML = `<div class="alert ${type}">${message}</div>`;
        }

        window.addEventListener('load', () => {
            refreshStatus();
            refreshHooks();
            refreshStats();

            setInterval(() => {
                refreshStatus();
                refreshStats();
            }, 30000);
        });
    </script>
</body>
</html>
"""

logger = logging.getLogger("parrot.api.whatsapp")


# ============================================================================
# Shared helpers (used by both handler classes)
# ============================================================================

class _WhatsAppMixin:
    """Shared bridge communication helpers for WhatsApp handlers."""

    @property
    def _bridge_url(self) -> str:
        return self.request.app.get(
            'whatsapp_bridge_url', 'http://localhost:8765'
        )

    @property
    def _orchestrator(self):
        return self.request.app.get('orchestrator')

    async def _get_bridge_status(self) -> Dict[str, Any]:
        """Get health/status from WhatsApp Bridge."""
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"{self._bridge_url}/health",
                    timeout=ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {
                        'success': False,
                        'error': f'Bridge returned status {resp.status}',
                    }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    async def _get_whatsapp_hooks(self) -> list:
        """Return all registered WhatsAppRedisHook instances."""
        orchestrator = self._orchestrator
        if not orchestrator:
            return []

        from ..autonomous.hooks.whatsapp_redis import WhatsAppRedisHook

        return [
            hook
            for hook in orchestrator.hook_manager._hooks
            if isinstance(hook, WhatsAppRedisHook)
        ]

    async def _get_hooks_info(self) -> Dict[str, Any]:
        """Summarise WhatsApp hooks for status responses."""
        hooks = await self._get_whatsapp_hooks()
        return {
            'total': len(hooks),
            'enabled': len([h for h in hooks if h.enabled]),
            'disabled': len([h for h in hooks if not h.enabled]),
            'hooks': [
                {
                    'hook_id': h.hook_id,
                    'name': h.name,
                    'enabled': h.enabled,
                    'target': f"{h.target_type}/{h.target_id}",
                }
                for h in hooks
            ],
        }

    async def _find_hook_by_id(self, hook_id: str):
        """Locate a hook by its hook_id or name."""
        hooks = await self._get_whatsapp_hooks()
        for hook in hooks:
            if hook.hook_id == hook_id or hook.name == hook_id:
                return hook
        return None


# ============================================================================
# Dashboard (no auth — browser navigations can't send Bearer headers).
# The page itself is static HTML; JS fetchAPI handles Bearer tokens for
# the actual API data endpoints.
# ============================================================================

async def whatsapp_dashboard_page(request: web.Request) -> web.Response:  # noqa: ARG001
    """Serve the WhatsApp dashboard HTML (no auth required)."""
    return web.Response(
        text=_DASHBOARD_HTML,
        content_type='text/html',
        charset='utf-8',
    )


# ============================================================================
# Superuser-only: QR code endpoints  (allowed_groups wraps ALL methods)
# ============================================================================

@is_authenticated()
@user_session()
@allowed_groups(groups=['superuser'])
class WhatsAppQRHandler(_WhatsAppMixin, BaseView):
    """Superuser-only endpoints for QR code authentication.

    Routes registered by ``setup_whatsapp_bridge``:
        GET /api/whatsapp/qr         — QR code availability / metadata
        GET /api/whatsapp/qr/image   — raw QR PNG proxied from bridge
    """

    async def get(self):
        """Dispatch GET based on path suffix."""
        path = self.request.path
        if path.endswith('/qr/image'):
            return await self._get_qr_image()
        if path.endswith('/qr'):
            return await self._get_qr_code()
        return self.error("Not found", status=404)

    # -- QR code -------------------------------------------------------------

    async def _get_qr_code(self):
        """Return QR code metadata (JSON)."""
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"{self._bridge_url}/qr.png",
                    timeout=ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return self.json_response({
                            'success': True,
                            'qr_available': True,
                            'qr_url': f"{self._bridge_url}/qr",
                            'qr_image_url': f"{self._bridge_url}/qr.png",
                            'status': 'waiting_for_scan',
                            'instructions': (
                                'Open WhatsApp > Settings > Linked Devices '
                                '> Link a Device > Scan QR'
                            ),
                            'bridge_url': self._bridge_url,
                        })
                    if resp.status == 404:
                        status = await self._get_bridge_status()
                        if status.get('data', {}).get('authenticated'):
                            return self.json_response({
                                'success': True,
                                'qr_available': False,
                                'status': 'authenticated',
                                'message': 'WhatsApp is already connected',
                            })
                        return self.error(
                            'QR code not available and not authenticated',
                            status=500,
                        )
                    return self.error(
                        f'Bridge returned status {resp.status}',
                        status=resp.status,
                    )
        except asyncio.TimeoutError:
            return self.error(
                'Bridge timeout - is it running?', status=504
            )
        except Exception as exc:
            logger.error("Error getting QR code: %s", exc)
            return self.error(str(exc), status=500)

    async def _get_qr_image(self):
        """Proxy the QR PNG image from the bridge."""
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"{self._bridge_url}/qr.png",
                    timeout=ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        return web.Response(
                            body=image_data,
                            content_type='image/png',
                            headers={
                                'Cache-Control': (
                                    'no-cache, no-store, must-revalidate'
                                ),
                                'Pragma': 'no-cache',
                                'Expires': '0',
                            },
                        )
                    if resp.status == 404:
                        return self.error(
                            'QR code not available - already authenticated',
                            status=404,
                        )
                    return self.error(
                        f'Bridge returned status {resp.status}',
                        status=resp.status,
                    )
        except Exception as exc:
            logger.error("Error getting QR image: %s", exc)
            return self.error(str(exc), status=500)


# ============================================================================
# Authenticated users: status, hooks CRUD, send, stats, disconnect
# ============================================================================

@is_authenticated()
@user_session()
class WhatsAppConfigHandler(_WhatsAppMixin, BaseView):
    """Authenticated endpoints for WhatsApp bridge management.

    Routes registered by ``setup_whatsapp_bridge``:
        GET    /api/whatsapp/status           — connection status
        POST   /api/whatsapp/disconnect       — stop hooks
        GET    /api/whatsapp/hooks            — list hooks
        POST   /api/whatsapp/hooks            — create hook
        PUT    /api/whatsapp/hooks/{hook_id}  — update hook
        DELETE /api/whatsapp/hooks/{hook_id}  — delete hook
        POST   /api/whatsapp/send             — send test message
        GET    /api/whatsapp/stats            — message statistics
    """

    async def get(self):
        """Dispatch GET based on path suffix."""
        path = self.request.path
        if path.endswith('/status'):
            return await self._get_status()
        if path.endswith('/hooks'):
            return await self._list_hooks()
        if path.endswith('/stats'):
            return await self._get_stats()
        return self.error("Not found", status=404)

    async def post(self):
        """Dispatch POST based on path suffix."""
        path = self.request.path
        if path.endswith('/disconnect'):
            return await self._disconnect()
        if path.endswith('/hooks'):
            return await self._create_hook()
        if path.endswith('/send'):
            return await self._send_test_message()
        return self.error("Not found", status=404)

    async def put(self):
        """Update an existing WhatsApp hook."""
        return await self._update_hook()

    async def delete(self):
        """Delete an existing WhatsApp hook."""
        return await self._delete_hook()

    # -- status --------------------------------------------------------------

    async def _get_status(self):
        """Return bridge status + hooks summary."""
        status = await self._get_bridge_status()
        hooks_info = await self._get_hooks_info()
        return self.json_response({
            'success': True,
            'bridge': status.get('data', {}),
            'hooks': hooks_info,
            'bridge_url': self._bridge_url,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

    # -- disconnect ----------------------------------------------------------

    async def _disconnect(self):
        """Stop all WhatsApp hooks (full disconnect requires bridge restart)."""
        hooks = await self._get_whatsapp_hooks()
        stopped: list[str] = []
        for hook in hooks:
            try:
                await hook.stop()
                stopped.append(hook.name)
            except Exception as exc:
                logger.error("Error stopping hook %s: %s", hook.name, exc)

        return self.json_response({
            'success': True,
            'message': 'WhatsApp hooks stopped',
            'stopped_hooks': stopped,
            'note': 'To fully disconnect, restart the WhatsApp Bridge',
        })

    # -- hooks CRUD ----------------------------------------------------------

    async def _list_hooks(self):
        """Return detailed info for all WhatsApp hooks."""
        hooks = await self._get_whatsapp_hooks()
        hooks_data = []
        for hook in hooks:
            hooks_data.append({
                'hook_id': hook.hook_id,
                'name': hook.name,
                'enabled': hook.enabled,
                'target_type': hook.target_type,
                'target_id': hook.target_id,
                'config': {
                    'redis_url': hook._config.redis_url,
                    'channel': hook._config.channel,
                    'command_prefix': hook._config.command_prefix,
                    'allowed_phones': hook._config.allowed_phones,
                    'allowed_groups': hook._config.allowed_groups,
                    'auto_reply': hook._config.auto_reply,
                    'routes': hook._config.routes,
                },
            })
        return self.json_response({
            'success': True,
            'total': len(hooks_data),
            'hooks': hooks_data,
        })

    async def _create_hook(self):
        """Create and start a new WhatsApp hook."""
        try:
            data = await self.request.json()

            from ..autonomous.hooks.whatsapp_redis import WhatsAppRedisHook
            from ..autonomous.hooks.models import WhatsAppRedisHookConfig

            config_data = data.get('config', {})
            config = WhatsAppRedisHookConfig(
                name=data.get('name', 'whatsapp_hook'),
                enabled=data.get('enabled', True),
                target_type=data.get('target_type', 'agent'),
                target_id=data.get('target_id'),
                redis_url=config_data.get(
                    'redis_url', 'redis://localhost:6379'
                ),
                channel=config_data.get('channel', 'whatsapp:messages'),
                bridge_url=config_data.get('bridge_url', self._bridge_url),
                auto_reply=config_data.get('auto_reply', True),
                command_prefix=config_data.get('command_prefix', ''),
                allowed_phones=config_data.get('allowed_phones'),
                allowed_groups=config_data.get('allowed_groups'),
                routes=config_data.get('routes'),
            )

            hook = WhatsAppRedisHook(config=config)

            orchestrator = self._orchestrator
            if not orchestrator:
                return self.error('Orchestrator not configured', status=500)

            orchestrator.hook_manager.register_hook(hook)
            await hook.start()

            return self.json_response({
                'success': True,
                'hook_id': hook.hook_id,
                'name': hook.name,
                'message': 'WhatsApp hook created and started',
                'target': f"{hook.target_type}/{hook.target_id}",
            })
        except Exception as exc:
            logger.error("Error creating hook: %s", exc, exc_info=True)
            return self.error(str(exc), status=400)

    async def _update_hook(self):
        """Update and optionally restart an existing hook."""
        hook_id = self.request.match_info.get('hook_id')
        try:
            data = await self.request.json()

            hook = await self._find_hook_by_id(hook_id)
            if not hook:
                return self.error(
                    f'Hook {hook_id} not found', status=404
                )

            await hook.stop()

            if 'enabled' in data:
                hook.enabled = data['enabled']
            if 'target_id' in data:
                hook.target_id = data['target_id']
            if 'target_type' in data:
                hook.target_type = data['target_type']

            config_updates = data.get('config', {})
            if 'command_prefix' in config_updates:
                hook._config.command_prefix = config_updates['command_prefix']
            if 'allowed_phones' in config_updates:
                hook._config.allowed_phones = config_updates['allowed_phones']
                hook._allowed_phones = (
                    set(hook._config.allowed_phones)
                    if hook._config.allowed_phones
                    else None
                )
            if 'auto_reply' in config_updates:
                hook._config.auto_reply = config_updates['auto_reply']
            if 'routes' in config_updates:
                hook._config.routes = config_updates['routes']
                hook._routes = hook._config.routes

            if hook.enabled:
                await hook.start()

            return self.json_response({
                'success': True,
                'hook_id': hook.hook_id,
                'message': 'Hook updated successfully',
            })
        except Exception as exc:
            logger.error("Error updating hook: %s", exc, exc_info=True)
            return self.error(str(exc), status=400)

    async def _delete_hook(self):
        """Stop and unregister a hook."""
        hook_id = self.request.match_info.get('hook_id')
        try:
            hook = await self._find_hook_by_id(hook_id)
            if not hook:
                return self.error(
                    f'Hook {hook_id} not found', status=404
                )

            await hook.stop()

            orchestrator = self._orchestrator
            if orchestrator:
                orchestrator.hook_manager._hooks.remove(hook)

            return self.json_response({
                'success': True,
                'message': f'Hook {hook_id} deleted',
            })
        except Exception as exc:
            logger.error("Error deleting hook: %s", exc, exc_info=True)
            return self.error(str(exc), status=400)

    # -- send / stats --------------------------------------------------------

    async def _send_test_message(self):
        """Proxy a test message to the WhatsApp Bridge."""
        try:
            data = await self.request.json()
            phone = data.get('phone')
            message = data.get('message')

            if not phone or not message:
                return self.error(
                    'phone and message are required', status=400
                )

            async with ClientSession() as session:
                async with session.post(
                    f"{self._bridge_url}/send",
                    json={'phone': phone, 'message': message},
                    timeout=ClientTimeout(total=30),
                ) as resp:
                    result = await resp.json()
                    return self.json_response(result, status=resp.status)
        except Exception as exc:
            logger.error("Error sending test message: %s", exc)
            return self.error(str(exc), status=500)

    async def _get_stats(self):
        """Return WhatsApp-specific execution statistics."""
        orchestrator = self._orchestrator
        if not orchestrator:
            return self.error('Orchestrator not configured', status=500)

        stats = orchestrator.get_stats()

        whatsapp_executions = [
            r
            for r in orchestrator._execution_history
            if r.metadata.get('source') == 'whatsapp'
            or 'whatsapp' in str(r.metadata).lower()
        ]

        return self.json_response({
            'success': True,
            'stats': {
                'total_executions': len(whatsapp_executions),
                'successful': len(
                    [r for r in whatsapp_executions if r.success]
                ),
                'failed': len(
                    [r for r in whatsapp_executions if not r.success]
                ),
                'hooks': stats['components']['hooks'],
                'recent_executions': [
                    {
                        'request_id': r.request_id,
                        'target_id': r.target_id,
                        'success': r.success,
                        'execution_time_ms': r.execution_time_ms,
                        'completed_at': r.completed_at.isoformat(),
                    }
                    for r in whatsapp_executions[-10:]
                ],
            },
        })


# ============================================================================
# Route registration
# ============================================================================

def setup_whatsapp_bridge(
    app: web.Application,
    orchestrator: Optional[object] = None,
    bridge_url: Optional[str] = None,
) -> None:
    """Register WhatsApp configuration API endpoints.

    Args:
        app: aiohttp Application instance.
        orchestrator: AutonomousOrchestrator (or compatible) instance.
        bridge_url: WhatsApp Bridge URL (default ``http://localhost:8765``).

    Usage::

        from parrot.services.whatsapp import setup_whatsapp_bridge

        setup_whatsapp_bridge(app, orchestrator)
    """
    app['orchestrator'] = orchestrator
    app['whatsapp_bridge_url'] = bridge_url or 'http://localhost:8765'

    # Dashboard: standalone handler, no auth decorator
    app.router.add_route(
        'GET', '/api/whatsapp/dashboard', whatsapp_dashboard_page
    )
    # Superuser-only: QR code
    app.router.add_view('/api/whatsapp/qr', WhatsAppQRHandler)
    app.router.add_view('/api/whatsapp/qr/image', WhatsAppQRHandler)

    # Authenticated: status, hooks, send, stats
    app.router.add_view('/api/whatsapp/status', WhatsAppConfigHandler)
    app.router.add_view('/api/whatsapp/disconnect', WhatsAppConfigHandler)
    app.router.add_view('/api/whatsapp/hooks', WhatsAppConfigHandler)
    app.router.add_view(
        '/api/whatsapp/hooks/{hook_id}', WhatsAppConfigHandler
    )
    app.router.add_view('/api/whatsapp/send', WhatsAppConfigHandler)
    app.router.add_view('/api/whatsapp/stats', WhatsAppConfigHandler)

    logger.info(
        "WhatsApp Configuration API registered at /api/whatsapp/*"
    )

    # Dashboard is static HTML — exclude from auth middleware.
    # API data endpoints remain protected; the dashboard JS sends
    # Bearer tokens via fetchAPI.
    from navigator_auth.conf import exclude_list
    for path in ('/api/whatsapp/dashboard', '/api/whatsapp/qr/image'):
        if path not in exclude_list:
            exclude_list.append(path)
