"""Admin login page for the Autonomous Orchestrator.

Serves a simple HTML page at ``/autonomous/admin`` that:

1. Collects *username* + *password*.
2. POSTs to ``/api/v1/login`` with header ``X-Auth-Method: BasicAuth``.
3. On success, stores the JWT token and full user payload in **localStorage**.
4. Redirects the admin to the WhatsApp dashboard (or any protected page).
"""
from aiohttp import web


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_ADMIN_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login - AI-Parrot</title>
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
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .login-card {
            background: white;
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
        }

        .login-header {
            text-align: center;
            margin-bottom: 30px;
        }

        .login-header .logo {
            font-size: 3em;
            margin-bottom: 8px;
        }

        .login-header h1 {
            font-size: 1.6em;
            color: #333;
            margin-bottom: 6px;
        }

        .login-header p {
            color: #888;
            font-size: 0.95em;
        }

        .form-group {
            margin-bottom: 20px;
        }

        .form-group label {
            display: block;
            margin-bottom: 6px;
            color: #555;
            font-weight: 500;
            font-size: 0.9em;
        }

        .form-group input {
            width: 100%;
            padding: 12px 14px;
            border: 2px solid #e1e5ee;
            border-radius: 10px;
            font-size: 1em;
            transition: border-color 0.3s;
            outline: none;
        }

        .form-group input:focus {
            border-color: #667eea;
        }

        .btn-login {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.05em;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.3s;
            margin-top: 5px;
        }

        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.45);
        }

        .btn-login:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }

        .alert {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 18px;
            font-size: 0.9em;
            display: none;
        }

        .alert.error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fecaca;
        }

        .alert.success {
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #a7f3d0;
        }

        .session-info {
            margin-top: 24px;
            padding: 16px;
            background: #f0f4ff;
            border-radius: 10px;
            display: none;
        }

        .session-info h3 {
            font-size: 0.95em;
            color: #667eea;
            margin-bottom: 10px;
        }

        .session-info .detail {
            font-size: 0.85em;
            color: #555;
            margin-bottom: 4px;
            word-break: break-all;
        }

        .session-info .detail strong {
            color: #333;
        }

        .quick-links {
            margin-top: 20px;
            text-align: center;
        }

        .quick-links a {
            display: inline-block;
            margin: 6px 8px;
            padding: 8px 18px;
            background: #f3f4f6;
            color: #667eea;
            border-radius: 8px;
            text-decoration: none;
            font-size: 0.9em;
            font-weight: 500;
            transition: background 0.2s;
        }

        .quick-links a:hover {
            background: #e0e7ff;
        }

        .logout-btn {
            display: none;
            margin-top: 12px;
            width: 100%;
            padding: 10px;
            background: #ef4444;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9em;
            transition: background 0.2s;
        }

        .logout-btn:hover {
            background: #dc2626;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="login-header">
            <div class="logo">🤖</div>
            <h1>Admin Login</h1>
            <p>AI-Parrot Autonomous Orchestrator</p>
        </div>

        <div class="alert error" id="alertError"></div>
        <div class="alert success" id="alertSuccess"></div>

        <form id="loginForm" onsubmit="handleLogin(event)">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="user" required
                       placeholder="Enter your username" autocomplete="username">
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required
                       placeholder="Enter your password" autocomplete="current-password">
            </div>

            <button type="submit" class="btn-login" id="loginBtn">Sign In</button>
        </form>

        <div class="session-info" id="sessionInfo">
            <h3>✅ Session Active</h3>
            <div class="detail"><strong>User:</strong> <span id="sessionUser">-</span></div>
            <div class="detail"><strong>Token type:</strong> <span id="sessionScheme">-</span></div>
            <div class="detail"><strong>Expires:</strong> <span id="sessionExpiry">-</span></div>
        </div>

        <div class="quick-links" id="quickLinks" style="display:none;">
            <a href="/api/whatsapp/dashboard">📱 WhatsApp Dashboard</a>
        </div>

        <button class="logout-btn" id="logoutBtn" onclick="handleLogout()">Sign Out</button>
    </div>

    <script>
        // ---- localStorage helpers ----
        function saveSession(data) {
            localStorage.setItem('ai_parrot_token', data.token);
            localStorage.setItem('ai_parrot_session', JSON.stringify(data));
        }

        function getToken() {
            return localStorage.getItem('ai_parrot_token');
        }

        function getSession() {
            try {
                return JSON.parse(localStorage.getItem('ai_parrot_session'));
            } catch { return null; }
        }

        function clearSession() {
            localStorage.removeItem('ai_parrot_token');
            localStorage.removeItem('ai_parrot_session');
        }

        // ---- UI helpers ----
        function showAlert(type, msg) {
            const el = document.getElementById(type === 'error' ? 'alertError' : 'alertSuccess');
            const other = document.getElementById(type === 'error' ? 'alertSuccess' : 'alertError');
            other.style.display = 'none';
            el.textContent = msg;
            el.style.display = 'block';
        }

        function hideAlerts() {
            document.getElementById('alertError').style.display = 'none';
            document.getElementById('alertSuccess').style.display = 'none';
        }

        function showSessionState(session) {
            document.getElementById('loginForm').style.display = 'none';
            document.getElementById('sessionInfo').style.display = 'block';
            document.getElementById('quickLinks').style.display = 'block';
            document.getElementById('logoutBtn').style.display = 'block';

            document.getElementById('sessionUser').textContent =
                session.user || session.username || '-';
            document.getElementById('sessionScheme').textContent =
                session.token_type || 'Bearer';
            document.getElementById('sessionExpiry').textContent =
                session.expires_in || '-';
        }

        function showLoginForm() {
            document.getElementById('loginForm').style.display = 'block';
            document.getElementById('sessionInfo').style.display = 'none';
            document.getElementById('quickLinks').style.display = 'none';
            document.getElementById('logoutBtn').style.display = 'none';
        }

        // ---- login ----
        async function handleLogin(event) {
            event.preventDefault();
            hideAlerts();

            const btn = document.getElementById('loginBtn');
            btn.disabled = true;
            btn.textContent = 'Signing in…';

            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;

            try {
                const resp = await fetch('/api/v1/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Auth-Method': 'BasicAuth'
                    },
                    body: JSON.stringify({ username, password })
                });

                if (!resp.ok) {
                    const errBody = await resp.text();
                    throw new Error(errBody || `HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (!data.token) {
                    throw new Error('No token received from server');
                }

                saveSession(data);
                showAlert('success', 'Login successful! Redirecting…');
                showSessionState(data);

                // Auto-redirect to WhatsApp dashboard after 1.5s
                setTimeout(() => {
                    window.location.href = '/api/whatsapp/dashboard';
                }, 1500);

            } catch (err) {
                showAlert('error', 'Login failed: ' + err.message);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Sign In';
            }
        }

        // ---- logout ----
        async function handleLogout() {
            // Call server-side logout to invalidate session
            try {
                const token = getToken();
                await fetch('/api/v1/logout', {
                    method: 'GET',
                    headers: token
                        ? { 'Authorization': `Bearer ${token}` }
                        : {}
                });
            } catch (e) {
                console.warn('Server logout failed:', e);
            }
            clearSession();
            hideAlerts();
            showLoginForm();
            showAlert('success', 'Signed out successfully');
        }

        // ---- on page load: check existing session ----
        window.addEventListener('load', () => {
            const session = getSession();
            if (session && session.token) {
                showSessionState(session);
            }
        });
    </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# aiohttp handler
# ---------------------------------------------------------------------------

async def admin_login_page(request: web.Request) -> web.Response:  # noqa: ARG001
    """Serve the admin login HTML page (no auth required)."""
    return web.Response(
        text=_ADMIN_LOGIN_HTML,
        content_type='text/html',
        charset='utf-8',
    )
